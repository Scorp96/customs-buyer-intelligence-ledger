"""Read-only projection of strongly validated legacy Peer receipts into v6.1 views.

The compatibility runtime persisted independently validated Peers as
``PEER_RECEIPT_APPENDED``.  The v6 lifecycle intentionally uses separate
``V6_PEER_*`` events, but hiding the older validated receipts from the public
Account State loses durable research when an investigation is upgraded.

This mixin projects only mechanically replay-safe legacy Peer receipts.  It
never creates a v6 lifecycle event, never promotes an Anchor, and keeps
Decision Saturation open until an explicit v6 reconciliation occurs.
"""

from __future__ import annotations

from typing import Any

from . import v6 as _v6


class V61LegacyPeerProjectionMixin:
    """Expose validated legacy Peers without granting new v6 mutation authority."""

    @staticmethod
    def _section_refs(section: Any) -> tuple[list[str], list[str]]:
        if not isinstance(section, dict) or section.get("passed") is not True:
            return [], []
        attempts = [str(item) for item in section.get("attempt_ids") or [] if str(item).strip()]
        evidence = [str(item) for item in section.get("evidence_ids") or [] if str(item).strip()]
        return attempts, evidence

    def _legacy_peer_receipt_replay_safe(
        self,
        legacy: dict[str, Any],
        receipt: dict[str, Any],
    ) -> tuple[bool, list[str]]:
        peer_id = str(receipt.get("peer_id") or "").strip()
        reasons: list[str] = []
        if not peer_id:
            return False, ["PEER_ID_MISSING"]
        if receipt.get("canonical_dedup_checked") is not True:
            reasons.append("CANONICAL_DEDUP_NOT_PROVEN")
        if receipt.get("inherited_anchor_facts") is not False:
            reasons.append("INHERITED_ANCHOR_FACTS_NOT_EXCLUDED")

        discovery_id = str(receipt.get("discovered_by_attempt_id") or "").strip()
        discovery = legacy.get("attempts", {}).get(discovery_id)
        branch = str(receipt.get("branch") or "").strip()
        if not discovery:
            reasons.append("DISCOVERY_ATTEMPT_MISSING")
        else:
            if branch and str(discovery.get("module_or_branch") or "") != branch:
                reasons.append("DISCOVERY_BRANCH_MISMATCH")
            if peer_id not in (discovery.get("discovered_peer_ids") or []):
                reasons.append("PEER_NOT_BOUND_TO_DISCOVERY_ATTEMPT")

        relationship = receipt.get("relationship")
        relationship_ids = []
        if not isinstance(relationship, dict) or relationship.get("passed") is not True:
            reasons.append("RELATIONSHIP_GATE_NOT_PASSED")
        else:
            relationship_ids = [
                str(item)
                for item in relationship.get("evidence_ids") or []
                if str(item).strip()
            ]
            if not relationship_ids:
                reasons.append("RELATIONSHIP_EVIDENCE_MISSING")
            elif discovery and not set(relationship_ids) <= set(
                (discovery.get("relationship_evidence_ids") or {}).get(peer_id) or []
            ):
                reasons.append("RELATIONSHIP_EVIDENCE_NOT_DISCOVERY_BOUND")

        for label in ("entity", "product", "trade_business", "company_profile"):
            attempts, evidence = self._section_refs(receipt.get(label))
            if not attempts:
                reasons.append(f"{label.upper()}_ATTEMPT_MISSING")
            if not evidence:
                reasons.append(f"{label.upper()}_EVIDENCE_MISSING")
            for attempt_id in attempts:
                row = legacy.get("attempts", {}).get(attempt_id)
                if not row or row.get("owner_id") != peer_id or row.get("result") != "POSITIVE":
                    reasons.append(f"{label.upper()}_ATTEMPT_NOT_PEER_POSITIVE")
                    break
            for evidence_id in evidence:
                row = legacy.get("evidence", {}).get(evidence_id)
                if not row or row.get("owner_id") != peer_id:
                    reasons.append(f"{label.upper()}_EVIDENCE_NOT_PEER_OWNED")
                    break

        contact_attempts, _ = self._section_refs(receipt.get("contact_coverage"))
        if not contact_attempts:
            reasons.append("CONTACT_COVERAGE_ATTEMPT_MISSING")
        else:
            for attempt_id in contact_attempts:
                row = legacy.get("attempts", {}).get(attempt_id)
                if not row or row.get("owner_id") != peer_id:
                    reasons.append("CONTACT_COVERAGE_ATTEMPT_NOT_PEER_OWNED")
                    break

        if str(receipt.get("promotion_decision") or "").upper() not in {
            "PROMOTE",
            "DO_NOT_PROMOTE",
        }:
            reasons.append("PROMOTION_DECISION_INVALID")

        return not reasons, sorted(set(reasons))

    @staticmethod
    def _legacy_peer_display_name(receipt: dict[str, Any]) -> str:
        for key in ("name", "legal_name", "company_name", "canonical_name", "canonical_key"):
            value = str(receipt.get(key) or "").strip()
            if value:
                return value
        return str(receipt.get("peer_id") or "").strip()

    def _legacy_peer_projections(self, investigation_id: str) -> list[dict[str, Any]]:
        # One verified compatibility-state replay already contains the complete
        # append-only event stream.  Derive native v6 Peer IDs from that same
        # stream instead of replaying the hash chain again through _v6_state().
        legacy = self._state(investigation_id)
        v6_peer_ids = {
            str(event.get("payload", {}).get("peer_id") or "")
            for event in legacy.get("events", [])
            if event.get("event_type") in {
                "V6_PEER_DISCOVERED",
                "V6_PEER_EVALUATED",
                "V6_ANCHOR_PROMOTED",
            }
            and str(event.get("payload", {}).get("peer_id") or "").strip()
        }
        rows: list[dict[str, Any]] = []
        for peer_id, receipt in legacy.get("peers", {}).items():
            if peer_id in v6_peer_ids or not isinstance(receipt, dict):
                continue
            safe, reasons = self._legacy_peer_receipt_replay_safe(legacy, receipt)
            if not safe:
                continue
            decision = str(receipt.get("promotion_decision") or "").upper()
            promotion_gate = str(receipt.get("promotion_gate") or "").upper()
            stage = (
                "ANCHOR_ELIGIBLE"
                if decision == "PROMOTE" and promotion_gate == "PASSED"
                else "QUALIFIED"
            )
            evidence_ids = sorted({
                str(evidence_id)
                for label in (
                    "entity",
                    "product",
                    "trade_business",
                    "relationship",
                    "company_profile",
                    "contact_coverage",
                )
                for evidence_id in (
                    receipt.get(label, {}).get("evidence_ids")
                    if isinstance(receipt.get(label), dict)
                    else []
                ) or []
                if str(evidence_id).strip()
            })
            rows.append({
                "peer_id": peer_id,
                "name": self._legacy_peer_display_name(receipt),
                "canonical_key": receipt.get("canonical_key") or "",
                "country": receipt.get("country") or "",
                "branch": receipt.get("branch") or "",
                "stage": stage,
                "legacy_promotion_decision": decision,
                "legacy_promotion_gate": promotion_gate,
                "evidence_ids": evidence_ids,
                "projection_source": "LEGACY_VALIDATED_PEER_RECEIPT",
                "projection_read_only": True,
                "v6_lifecycle_event_present": False,
                "requires_v6_reconciliation": True,
                "v6_anchor_promoted": False,
                "legacy_receipt_replay_safe": True,
                "legacy_receipt_replay_rejection_reasons": reasons,
            })
        return sorted(rows, key=lambda row: str(row.get("peer_id") or "").casefold())

    def get_runtime_contract(self, arguments: dict[str, Any]) -> dict[str, Any]:
        contract = super().get_runtime_contract(arguments)
        contract["legacy_peer_projection_v6_1"] = {
            "source_event": "PEER_RECEIPT_APPENDED",
            "projection_is_read_only": True,
            "requires_mechanical_receipt_replay_safety": True,
            "legacy_promote_maps_at_most_to": "ANCHOR_ELIGIBLE",
            "creates_v6_peer_lifecycle_event": False,
            "grants_v6_anchor_promotion_authority": False,
            "decision_saturation_requires_v6_reconciliation": True,
            "execution_receipt_candidate_auto_promotes_to_peer": False,
            "projection_reuses_verified_legacy_event_stream": True,
        }
        return contract

    def get_account_state(self, arguments: dict[str, Any]) -> dict[str, Any]:
        base = super().get_account_state(arguments)
        investigation_id = _v6._nonempty(arguments.get("investigation_id"), "investigation_id")
        projections = self._legacy_peer_projections(investigation_id)
        network = dict(base.get("network") or {})
        current_peers = [dict(row) for row in network.get("peers") or [] if isinstance(row, dict)]
        current_ids = {str(row.get("peer_id") or "") for row in current_peers}
        combined = current_peers + [row for row in projections if row["peer_id"] not in current_ids]
        network.update({
            "peers": combined,
            "v6_peer_count": len(current_peers),
            "legacy_validated_peer_projection_count": len(projections),
            "legacy_validated_peer_projections": projections,
            "legacy_candidate_receipts_auto_promoted": False,
        })
        return {**base, "network": network}

    def evaluate_decision_saturation(self, arguments: dict[str, Any]) -> dict[str, Any]:
        result = super().evaluate_decision_saturation(arguments)
        investigation_id = _v6._nonempty(arguments.get("investigation_id"), "investigation_id")
        projections = self._legacy_peer_projections(investigation_id)
        if not projections:
            return result

        unresolved = list(result.get("discovered_peers_pending_resolution") or [])
        anchor_pending = list(result.get("anchor_eligible_peers_pending_promotion") or [])
        blockers = list(result.get("blockers") or [])
        for row in projections:
            peer_id = row["peer_id"]
            if row["stage"] == "ANCHOR_ELIGIBLE":
                if peer_id not in anchor_pending:
                    anchor_pending.append(peer_id)
            elif peer_id not in unresolved:
                unresolved.append(peer_id)
            blocker = f"LEGACY_VALIDATED_PEER_REQUIRES_V6_RECONCILIATION:{peer_id}"
            if blocker not in blockers:
                blockers.append(blocker)

        status = str(result.get("status") or "NOT_SATURATED")
        if status not in {"BLOCKED", "PAUSED_RESOURCE_LIMIT"}:
            status = "NOT_SATURATED"
        return {
            **result,
            "status": status,
            "decision_saturated": False,
            "discovered_peers_pending_resolution": sorted(set(unresolved)),
            "anchor_eligible_peers_pending_promotion": sorted(set(anchor_pending)),
            "blockers": blockers,
            "legacy_validated_peers_pending_v6_reconciliation": [
                row["peer_id"] for row in projections
            ],
        }
