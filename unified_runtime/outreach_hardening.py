"""v6.1 outreach preparation bound to the Canonical Route View.

The compatibility implementation validates only compiled route observations.
Production v6.1 must accept the same safe append-only InformationRecord route
that made Outreach Readiness ready, without fabricating or auto-migrating a new
observation. Every non-route outreach safeguard remains fail-closed.
"""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from . import v6 as _v6


class V61OutreachHardeningMixin:
    """Use one canonical Route authority source for readiness and preparation."""

    @staticmethod
    def _route_matches_candidate(
        route: dict[str, Any],
        candidate: dict[str, Any],
        account_id: str,
    ) -> bool:
        kind = str(route.get("kind") or "").upper().strip()
        value = str(route.get("value") or "").strip()
        candidate_channel = str(candidate.get("channel") or "").upper().strip()
        candidate_value = str(candidate.get("value") or "").strip()
        if candidate.get("owner_id") != account_id:
            return False
        if candidate.get("verified") is not True or candidate.get("current") is not True:
            return False
        if candidate.get("route_scope") != "BUYER_DIRECT":
            return False
        if candidate_channel != kind or candidate_value.casefold() != value.casefold():
            return False

        supplied_evidence_ids = {
            str(item).strip()
            for item in route.get("evidence_ids") or []
            if str(item).strip()
        }
        candidate_evidence_ids = {
            str(item).strip()
            for item in candidate.get("evidence_ids") or []
            if str(item).strip()
        }
        # When the canonical source has Evidence IDs, the caller may not bind a
        # different Evidence set. A legacy/public Information route can instead
        # be source-bound by its stored concrete source URL/locator.
        if candidate_evidence_ids:
            if not supplied_evidence_ids:
                return False
            if not supplied_evidence_ids <= candidate_evidence_ids:
                return False
        elif supplied_evidence_ids:
            return False
        elif not (
            str(candidate.get("source_url") or "").strip()
            or str(candidate.get("source_locator") or "").strip()
        ):
            return False
        return True

    @_v6._serialized_v6_mutation
    def prepare_outreach(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = _v6._require_object(arguments, "arguments")
        _v6._walk_no_secrets(args, "arguments")
        investigation_id = _v6._nonempty(args.get("investigation_id"), "investigation_id")
        state = self._v6_state(investigation_id)
        closure_id = _v6._nonempty(args.get("closure_id"), "closure_id")
        closure = state["closures"].get(closure_id)
        reasons: list[str] = []

        if not closure:
            reasons.append("INVALID_CLOSURE_ID")
        elif closure.get("used"):
            reasons.append("CLOSURE_TOKEN_REPLAY")
        elif datetime.fromisoformat(str(closure["expires_at"]).replace("Z", "+00:00")) <= datetime.now(timezone.utc):
            reasons.append("CLOSURE_EXPIRED")
        elif any(
            event["seq"] > closure["seq"]
            and event["event_type"] in _v6.V6_OPERATIONAL_EVENTS
            for event in state["events"]
        ):
            reasons.append("CLOSURE_STALE_AFTER_NEW_RESEARCH")
        if closure and closure.get("status") != "COMPLETE_POSITIVE":
            reasons.append("NEGATIVE_CLOSURE_NOT_OUTREACH_ELIGIBLE")
        if closure and not (closure.get("state_dimensions") or {}).get(
            "outreach_prerequisites_complete"
        ):
            reasons.append("OUTREACH_PREREQUISITES_INCOMPLETE")

        route = args.get("route")
        if not isinstance(route, dict):
            route = {}
            reasons.append("ROUTE_REQUIRED")
        account_id = state["start"]["account"]["account_id"]
        if not (
            route.get("verified") is True
            and route.get("current") is True
            and route.get("owned_by_account") is True
            and route.get("owner_entity_id") == account_id
        ):
            reasons.append("ROUTE_NOT_CURRENT_VERIFIED_ACCOUNT_OWNED")

        kind = str(route.get("kind") or "").upper()
        value = str(route.get("value") or "").strip()
        if kind == "EMAIL" and not _v6._EMAIL_RE.fullmatch(value):
            reasons.append("INVALID_EMAIL_ROUTE")
        elif kind == "PHONE":
            normalized_phone = re.sub(r"[\s()-]", "", value)
            if _v6.MASKED_CONTACT_RE.search(value) or not _v6.INTERNATIONAL_PHONE_RE.fullmatch(normalized_phone):
                reasons.append("INVALID_PHONE_ROUTE")
        elif kind in {"WHATSAPP", "ZALO"}:
            normalized_phone = re.sub(r"[\s()-]", "", value)
            if _v6.MASKED_CONTACT_RE.search(value) or not _v6.INTERNATIONAL_PHONE_RE.fullmatch(normalized_phone):
                reasons.append(f"INVALID_{kind}_INTERNATIONAL_ROUTE")
        elif kind in {"LINKEDIN", "FACEBOOK", "INSTAGRAM", "WEBSITE_FORM"} and not _v6.URL_RE.fullmatch(value):
            reasons.append("INVALID_SOCIAL_OR_FORM_URL")

        canonical_routes = self._canonical_route_view(investigation_id)
        matching_routes = [
            candidate
            for candidate in canonical_routes
            if self._route_matches_candidate(route, candidate, account_id)
        ]
        if not matching_routes:
            # Keep the historical fail-closed reason code for downstream clients
            # while also returning the more precise v6.1 Canonical Route blocker.
            reasons.append("ROUTE_VALUE_OR_CHANNEL_NOT_BOUND_TO_EVIDENCE")
            reasons.append("ROUTE_NOT_BOUND_TO_CANONICAL_ROUTE_VIEW")
        if kind in {"WHATSAPP", "ZALO"} and not matching_routes:
            reasons.append(f"{kind}_CHANNEL_NOT_PROVEN")

        if state["start"].get("opt_out"):
            reasons.append("ACCOUNT_OPTED_OUT")
        if args.get("history_digest") != state["start"].get("history_digest"):
            reasons.append("HISTORY_DIGEST_MISMATCH")
        if args.get("authority_digest") != state["start"].get("authority_digest"):
            reasons.append("AUTHORITY_DIGEST_MISMATCH")

        subject = str(args.get("subject") or "").strip()
        body = str(args.get("body") or "").strip()
        if not subject or not body:
            reasons.append("SUBJECT_AND_BODY_REQUIRED")
        if re.search(
            r"(?:customs data|supplier intelligence|海关数据|你的供应商)",
            f"{subject}\n{body}",
            flags=re.I,
        ):
            reasons.append("CUSTOMS_OR_SUPPLIER_INTELLIGENCE_LEAK")
        authority_claims = set(state["start"].get("authority_claims") or [])
        for claim, pattern in _v6.CONCRETE_CLAIM_PATTERNS.items():
            if pattern.search(f"{subject}\n{body}") and claim not in authority_claims:
                reasons.append(f"UNAUTHORIZED_CONCRETE_{claim.upper()}_CLAIM")

        stage = str(args.get("stage") or "").upper()
        if stage not in _v6.OUTREACH_STAGE_RANK:
            reasons.append("INVALID_STAGE")
        prior_stage = str(state["start"].get("history_highest_stage") or "").upper()
        if (
            prior_stage in _v6.OUTREACH_STAGE_RANK
            and stage in _v6.OUTREACH_STAGE_RANK
            and _v6.OUTREACH_STAGE_RANK[stage] < _v6.OUTREACH_STAGE_RANK[prior_stage]
        ):
            reasons.append("HISTORY_STAGE_REGRESSION")
        if any(
            event["event_type"] == "OUTREACH_PREPARED"
            and str(event["payload"].get("stage") or "").upper() == stage
            for event in state["events"]
        ):
            reasons.append("STAGE_REPLAY")
        if stage == "FIRST_TOUCH":
            words = _v6._word_count(body)
            if words < 80 or words > 110:
                reasons.append("FIRST_TOUCH_WORD_COUNT_OUTSIDE_80_110")
            if len(re.findall(r"https?://[^\s]+", f"{subject}\n{body}", flags=re.I)) > 1:
                reasons.append("FIRST_TOUCH_MULTIPLE_URLS")

        try:
            expires = _v6._parse_time(args.get("expires_at"), "expires_at")
            if (
                expires <= datetime.now(timezone.utc)
                or expires > datetime.now(timezone.utc) + timedelta(hours=24)
            ):
                reasons.append("OUTREACH_EXPIRY_INVALID")
        except _v6.ValidationError:
            expires = datetime.now(timezone.utc)
            reasons.append("OUTREACH_EXPIRY_INVALID")

        if reasons:
            return {
                "status": "DRAFT_BLOCKED",
                "prepared": False,
                "block_reasons": list(dict.fromkeys(reasons)),
                "prepared_id": None,
                "render_token": None,
                "action": None,
                "canonical_route_match_count": len(matching_routes),
            }

        prepared_id = f"PREP-{secrets.token_hex(12)}"
        render_token = f"RENDER-{secrets.token_hex(20)}"
        matched_route = matching_routes[0]
        payload = {
            "schema": "cbi.outreach-preparation.v6.1",
            "prepared_id": prepared_id,
            "render_token": render_token,
            "closure_id": closure_id,
            "investigation_id": investigation_id,
            "account_id": account_id,
            "route": route,
            "canonical_route_binding": {
                "route_source": matched_route.get("route_source"),
                "information_id": matched_route.get("information_id") or "",
                "observation_id": matched_route.get("observation_id") or "",
                "source_url": matched_route.get("source_url") or "",
                "source_locator": matched_route.get("source_locator") or "",
                "evidence_ids": list(matched_route.get("evidence_ids") or []),
            },
            "history_digest": str(
                args.get("history_digest")
                or state["start"].get("history_digest")
                or ""
            ),
            "authority_digest": str(
                args.get("authority_digest")
                or state["start"].get("authority_digest")
                or ""
            ),
            "subject": subject,
            "body": body,
            "chinese_translation": str(args.get("chinese_translation") or ""),
            "stage": stage,
            "issued_at": _v6.iso_utc(),
            "expires_at": _v6._format_time(expires),
            "content_sha256": _v6.digest(
                {
                    "subject": subject,
                    "body": body,
                    "route": route,
                    "canonical_route_binding": matched_route,
                }
            ),
        }
        try:
            self.store.append_if_tail(
                investigation_id,
                state["events"][-1]["event_hash"],
                "OUTREACH_PREPARED",
                payload,
            )
        except _v6.ValidationError:
            return {
                "status": "DRAFT_BLOCKED",
                "prepared": False,
                "block_reasons": ["STATE_CHANGED_DURING_PREPARATION_RETRY_REQUIRED"],
                "prepared_id": None,
                "render_token": None,
                "action": None,
                "canonical_route_match_count": 0,
            }
        return {
            "status": "PREPARED_FOR_RENDER" if kind == "EMAIL" else "PREPARED_CONTENT_ONLY",
            "prepared": True,
            "block_reasons": [],
            "prepared_id": prepared_id,
            "render_token": render_token,
            "expires_at": payload["expires_at"],
            "render_transport": "MAILTO" if kind == "EMAIL" else "CONTENT_ONLY_NO_ONE_CLICK_TRANSPORT",
            "action": None,
            "sends_message": False,
            "canonical_route_match_count": len(matching_routes),
            "canonical_route_binding": payload["canonical_route_binding"],
        }
