from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Any

from .demand_market import is_direct_procurement_source
from .legacy_opportunity_projection import project_legacy_v61_opportunities
from .product_profiles import get_product_profile, list_product_profiles
from .v63_projection import project_product_opportunities

try:
    from .resilience import exclusive_file_lock as _production_exclusive_file_lock
except ImportError:  # preserved r9/reference package does not carry v6.4 resilience module
    _production_exclusive_file_lock = None


_INDEX_SCHEMA = "cbi.v63-opportunity-locator-index.v1"
_V63_EVENT_TYPES = {
    "V63_PRODUCT_OPPORTUNITY_CREATED": "create_product_opportunity",
    "V63_OPPORTUNITY_ANCHOR_PROMOTED": "promote_opportunity_anchor",
}
_PRODUCT_CLAIMS = {
    "product.fit",
    "trade.import_activity",
    "commercial.procurement_need",
}
_CLAIM_SUPPORT_FACTOR = {
    "STRONGLY_SUPPORTED": 1.0,
    "SUPPORTED": 0.82,
    "CONFLICTED": 0.25,
    "STALE": 0.2,
    "REFUTED": 0.0,
    "NEGATIVE_EXHAUSTED": 0.0,
    "BLOCKED": 0.0,
    "NOT_APPLICABLE": 0.0,
    "SEARCHING": 0.0,
    "UNSEEN": 0.0,
}


def _grade_for_score(score: float) -> str:
    if score >= 92:
        return "A+"
    if score >= 84:
        return "A"
    if score >= 76:
        return "A-"
    if score >= 68:
        return "B+"
    if score >= 58:
        return "B"
    if score >= 48:
        return "B-"
    if score >= 35:
        return "C"
    if score > 0:
        return "D"
    return "NQ"


def _exclusive_file_lock(path: Path, timeout_seconds: float = 60.0):
    if _production_exclusive_file_lock is not None:
        return _production_exclusive_file_lock(path, timeout_seconds=timeout_seconds)

    class _Lock:
        def __enter__(self):
            path.parent.mkdir(parents=True, exist_ok=True)
            deadline = time.monotonic() + float(timeout_seconds)
            while True:
                try:
                    self.fd = os.open(str(path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                    os.write(self.fd, f"{os.getpid()}\n".encode("ascii"))
                    return self
                except FileExistsError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError(f"V63_DERIVED_INDEX_LOCK_TIMEOUT:{path}")
                    time.sleep(0.05)

        def __exit__(self, exc_type, exc, tb):
            try:
                os.close(self.fd)
            finally:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            return False

    return _Lock()


def _atomic_json_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".{os.getpid()}.tmp")
    payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
    descriptor = os.open(str(temporary), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    os.replace(temporary, path)
    try:
        directory_fd = os.open(str(path.parent), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _structured_text(value: Any) -> str:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)
    except (TypeError, ValueError):
        return str(value)


def _token_present(text: str, token: str) -> bool:
    normalized = str(token or "").strip().replace("_", " ")
    if not normalized:
        return False
    escaped = re.escape(normalized.casefold()).replace(r"\ ", r"[\s_-]+")
    return re.search(r"(?<![a-z0-9])" + escaped + r"(?![a-z0-9])", text.casefold()) is not None


def _profile_tokens(profile: dict[str, Any]) -> set[str]:
    tokens: set[str] = set()
    profile_id = str(profile.get("profile_id") or "").strip()
    if profile_id:
        tokens.add(profile_id)
    for key in ("commercial_aliases", "subfamilies", "variants"):
        for value in profile.get(key) or []:
            value_text = str(value or "").strip()
            if value_text:
                tokens.add(value_text)
    return tokens


def _canonical_source_categories(row: dict[str, Any]) -> set[str]:
    source = row.get("source") if isinstance(row.get("source"), dict) else {}
    source_type = str(source.get("source_type") or "").strip().upper().replace("-", "_").replace(" ", "_")
    categories: set[str] = set()
    if is_direct_procurement_source(source_type):
        categories.add(source_type)
    elif source_type == "TRADEDATA":
        categories.add("TRADE_DATA")
    elif source_type in {"BILL_OF_LADING", "BOL"}:
        categories.add("SUPPLIER_BUYER_SHIPMENT")
    elif source_type:
        categories.add(source_type)
    return categories


class V63ProductionIntegrationBindingMixin:
    """Bind the v6.3 read-model overlay to existing v6.4 production authorities.

    SessionStore remains the only Product Opportunity event authority. The
    locator index is reconstructible cache metadata only and every query re-reads
    and validates the authoritative hash-chained investigation events.
    """

    def _normalize_v63_opportunity_event(self, investigation_id: str, event: dict[str, Any]) -> dict[str, Any] | None:
        event_type = str(event.get("event_type") or "")
        expected_tool = _V63_EVENT_TYPES.get(event_type)
        if expected_tool is None:
            return None
        payload = event.get("payload")
        if not isinstance(payload, dict):
            raise RuntimeError("V63_DURABLE_EVENT_PAYLOAD_INVALID")
        payload_inv = str(payload.get("investigation_id") or investigation_id).strip()
        if not payload_inv or payload_inv != str(investigation_id).strip():
            raise RuntimeError("V63_DURABLE_EVENT_INVESTIGATION_MISMATCH")
        correlation = event.get("mutation_correlation")
        if not isinstance(correlation, dict):
            raise RuntimeError("V63_DURABLE_EVENT_CORRELATION_MISSING")
        if str(correlation.get("tool") or "") != expected_tool:
            raise RuntimeError("V63_DURABLE_EVENT_CORRELATION_TOOL_MISMATCH")
        correlation_id = str(correlation.get("correlation_id") or "").strip()
        if not correlation_id:
            raise RuntimeError("V63_DURABLE_EVENT_CORRELATION_ID_MISSING")
        row = copy.deepcopy(payload)
        row["event_type"] = event_type
        row["investigation_id"] = payload_inv
        row["correlation_id"] = correlation_id
        row["seq"] = int(event.get("seq") or 0)
        return row

    def _read_v63_durable_events(self, investigation_id: str) -> list[dict[str, Any]]:
        investigation = str(investigation_id or "").strip()
        if not investigation:
            raise ValueError("INVESTIGATION_ID_REQUIRED")
        store = getattr(self, "store", None)
        reader = getattr(store, "read", None)
        if not callable(reader):
            raise RuntimeError("V63_PRODUCTION_SESSION_EVENT_READER_UNAVAILABLE")
        rows: list[dict[str, Any]] = []
        for event in reader(investigation):
            if not isinstance(event, dict):
                continue
            normalized = self._normalize_v63_opportunity_event(investigation, event)
            if normalized is not None:
                rows.append(normalized)
        return rows

    def _v63_project_legacy_v61_opportunities(self, filters: dict[str, Any] | None = None) -> dict[str, Any]:
        """Project eligible v6.1 evidence without appending v6.3 events.

        The v6.3 event chain remains authoritative.  Sessions that already have
        a v6.3 Product Opportunity event are deliberately excluded from this
        bridge so a stale legacy projection can never shadow a durable row.
        """
        args = dict(filters or {})
        store = getattr(self, "store", None)
        root = getattr(store, "root", None)
        if root is None or not callable(getattr(self, "_v6_state", None)):
            return {
                "schema": "cbi.v61-to-v63-evidence-bridge.v1",
                "status": "NOT_APPLICABLE",
                "opportunities": [],
                "projected_opportunity_count": 0,
                "blockers": [],
                "investigation_reports": [],
                "projection_read_only": True,
                "durable_event_present": False,
                "persistent_mutation_performed": False,
            }

        wanted_investigation = str(args.get("investigation_id") or "").strip()
        wanted_account = str(args.get("account_id") or "").strip()
        wanted_opportunity = str(args.get("opportunity_id") or "").strip()
        wanted_profile = str(args.get("product_profile_id") or "").strip().upper()
        if wanted_investigation:
            investigation_ids = [wanted_investigation]
        else:
            investigation_ids = sorted(
                path.stem
                for path in Path(root).glob("INV-*.jsonl")
                if path.is_file()
            )

        projected: list[dict[str, Any]] = []
        blockers: set[str] = set()
        reports: list[dict[str, Any]] = []
        for investigation_id in investigation_ids:
            durable_events = self._read_v63_durable_events(investigation_id)
            if durable_events:
                continue
            state = self._v6_state(investigation_id)
            report = project_legacy_v61_opportunities(
                state,
                evidence_matches_profile=self._evidence_matches_product_profile,
                source_categories=_canonical_source_categories,
                account_id=wanted_account,
                opportunity_id=wanted_opportunity,
                product_profile_id=wanted_profile,
            )
            if report.get("status") in {"PROJECTED", "BLOCKED"}:
                reports.append(copy.deepcopy(report))
            projected.extend(copy.deepcopy(report.get("opportunities") or []))
            blockers.update(str(value) for value in report.get("blockers") or [] if str(value).strip())

        if projected:
            status = "PROJECTED"
        elif blockers:
            status = "BLOCKED"
        else:
            status = "NOT_APPLICABLE"
        return {
            "schema": "cbi.v61-to-v63-evidence-bridge.v1",
            "status": status,
            "opportunities": projected,
            "projected_opportunity_count": len(projected),
            "blockers": sorted(blockers),
            "investigation_reports": reports,
            "projection_read_only": True,
            "durable_event_present": False,
            "persistent_mutation_performed": False,
        }

    def _v63_locator_index_path(self) -> Path:
        root = Path(getattr(getattr(self, "store", None), "root", "")).expanduser().resolve()
        if not str(root):
            raise RuntimeError("V63_SESSION_ROOT_UNAVAILABLE")
        fingerprint = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:16]
        return root.parent / ".cbi-derived" / f"v63-opportunity-locator-{fingerprint}.json"

    def _v63_locator_session_row(self, investigation_id: str) -> dict[str, Any]:
        path = Path(self.store.root) / f"{investigation_id}.jsonl"
        stat = path.stat()
        events = self._read_v63_durable_events(investigation_id)
        projection_error = None
        identity_candidates: list[dict[str, str]] = []
        for event in events:
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("event_type") or "")
            if event_type == "V63_PRODUCT_OPPORTUNITY_CREATED":
                snapshot = event.get("result_snapshot")
                if not isinstance(snapshot, dict):
                    snapshot = event
                identity_candidates.append({
                    "opportunity_id": str(snapshot.get("opportunity_id") or "").strip(),
                    "account_id": str(snapshot.get("account_id") or "").strip(),
                    "product_profile_id": str(snapshot.get("product_profile_id") or "").strip().upper(),
                })
            elif event_type == "V63_OPPORTUNITY_ANCHOR_PROMOTED":
                identity_candidates.append({
                    "opportunity_id": str(event.get("opportunity_id") or "").strip(),
                    "account_id": "",
                    "product_profile_id": "",
                })
        try:
            projected = project_product_opportunities(events)
        except RuntimeError as exc:
            projected = {"opportunities": []}
            error_code = str(exc).split(":", 1)[0].strip()
            projection_error = error_code or "V63_PROJECTION_FAILED"
        except ValueError:
            # The projector raises ValueError for a durable opportunity whose
            # product/profile pin or lifecycle fields fail domain validation.
            # Quarantine only this expected persisted-data error so an
            # unrelated account query can proceed; programming errors with
            # other exception types must still surface.
            projected = {"opportunities": []}
            projection_error = "V63_PRODUCT_OPPORTUNITY_VALIDATION_FAILED"
        opportunities = [
            {
                "opportunity_id": str(row.get("opportunity_id") or ""),
                "account_id": str(row.get("account_id") or ""),
                "product_profile_id": str(row.get("product_profile_id") or "").upper(),
                "lifecycle_stage": str(row.get("lifecycle_stage") or row.get("stage") or ""),
            }
            for row in projected.get("opportunities") or []
            if str(row.get("opportunity_id") or "").strip()
        ]
        return {
            "file_size": int(stat.st_size),
            "mtime_ns": int(stat.st_mtime_ns),
            "opportunities": opportunities,
            "projection_error": projection_error,
            "identity_candidates": identity_candidates,
        }

    def _load_v63_locator_index_unlocked(self, path: Path) -> dict[str, Any]:
        if not path.is_file():
            return {"schema": _INDEX_SCHEMA, "sessions": {}}
        try:
            row = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError):
            return {"schema": _INDEX_SCHEMA, "sessions": {}}
        if not isinstance(row, dict) or row.get("schema") != _INDEX_SCHEMA or not isinstance(row.get("sessions"), dict):
            return {"schema": _INDEX_SCHEMA, "sessions": {}}
        return row

    def _ensure_v63_locator_index(self, *, force_reconcile: bool = False) -> dict[str, Any]:
        cached = getattr(self, "_v63_opportunity_locator_cache", None)
        if isinstance(cached, dict) and not force_reconcile:
            return cached
        index_path = self._v63_locator_index_path()
        lock_path = index_path.with_suffix(index_path.suffix + ".lock")
        with _exclusive_file_lock(lock_path, timeout_seconds=60.0):
            index = self._load_v63_locator_index_unlocked(index_path)
            existing = dict(index.get("sessions") or {})
            current_paths = {path.stem: path for path in Path(self.store.root).glob("INV-*.jsonl") if path.is_file()}
            changed = False
            for investigation_id, path in current_paths.items():
                stat = path.stat()
                prior = existing.get(investigation_id)
                if (
                    isinstance(prior, dict)
                    and int(prior.get("file_size") or -1) == int(stat.st_size)
                    and int(prior.get("mtime_ns") or -1) == int(stat.st_mtime_ns)
                    and isinstance(prior.get("opportunities"), list)
                    and isinstance(prior.get("identity_candidates"), list)
                    and "projection_error" in prior
                ):
                    continue
                existing[investigation_id] = self._v63_locator_session_row(investigation_id)
                changed = True
            for stale in set(existing) - set(current_paths):
                existing.pop(stale, None)
                changed = True
            normalized = {
                "schema": _INDEX_SCHEMA,
                "authority": "DERIVED_LOCATOR_ONLY",
                "session_event_chain_remains_authority": True,
                "sessions": existing,
            }
            if changed or not index_path.is_file():
                _atomic_json_write(index_path, normalized)
            setattr(self, "_v63_opportunity_locator_cache", normalized)
            return normalized

    def _refresh_v63_locator_investigation(self, investigation_id: str) -> None:
        investigation = str(investigation_id or "").strip()
        if not investigation:
            return
        index_path = self._v63_locator_index_path()
        lock_path = index_path.with_suffix(index_path.suffix + ".lock")
        with _exclusive_file_lock(lock_path, timeout_seconds=60.0):
            index = self._load_v63_locator_index_unlocked(index_path)
            sessions = dict(index.get("sessions") or {})
            path = Path(self.store.root) / f"{investigation}.jsonl"
            if path.is_file():
                sessions[investigation] = self._v63_locator_session_row(investigation)
            else:
                sessions.pop(investigation, None)
            normalized = {
                "schema": _INDEX_SCHEMA,
                "authority": "DERIVED_LOCATOR_ONLY",
                "session_event_chain_remains_authority": True,
                "sessions": sessions,
            }
            _atomic_json_write(index_path, normalized)
            setattr(self, "_v63_opportunity_locator_cache", normalized)

    def _query_v63_opportunity_events(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        args = dict(filters or {})
        wanted_investigation = str(args.get("investigation_id") or "").strip()
        account_id = str(args.get("account_id") or "").strip()
        opportunity_id = str(args.get("opportunity_id") or "").strip()
        profile_id = str(args.get("product_profile_id") or "").strip().upper()
        index = self._ensure_v63_locator_index()
        investigation_ids: list[str] = []
        for session_id, meta in dict(index.get("sessions") or {}).items():
            if wanted_investigation and wanted_investigation != str(session_id):
                continue
            if not isinstance(meta, dict):
                continue
            projection_error = str(meta.get("projection_error") or "").strip()
            if projection_error:
                candidates = meta.get("identity_candidates")
                candidates = candidates if isinstance(candidates, list) else []
                scope_matches = not any((account_id, opportunity_id, profile_id))
                if wanted_investigation and wanted_investigation != str(session_id):
                    scope_matches = False
                if not scope_matches:
                    for candidate in candidates:
                        if not isinstance(candidate, dict):
                            continue
                        if account_id and str(candidate.get("account_id") or "") != account_id:
                            continue
                        if opportunity_id and str(candidate.get("opportunity_id") or "") != opportunity_id:
                            continue
                        if profile_id and str(candidate.get("product_profile_id") or "").upper() != profile_id:
                            continue
                        scope_matches = True
                        break
                if scope_matches:
                    raise RuntimeError(
                        "V63_OPPORTUNITY_PROJECTION_BLOCKED:"
                        + str(session_id)
                        + ":"
                        + projection_error
                    )
                continue
            rows = meta.get("opportunities") if isinstance(meta, dict) else []
            if not isinstance(rows, list):
                continue
            matched = False
            for row in rows:
                if not isinstance(row, dict):
                    continue
                if account_id and str(row.get("account_id") or "") != account_id:
                    continue
                if opportunity_id and str(row.get("opportunity_id") or "") != opportunity_id:
                    continue
                if profile_id and str(row.get("product_profile_id") or "").upper() != profile_id:
                    continue
                matched = True
                break
            if matched:
                investigation_ids.append(str(session_id))
        result: list[dict[str, Any]] = []
        for investigation_id in sorted(investigation_ids):
            result.extend(self._read_v63_durable_events(investigation_id))
        return result

    def _v63_evidence_rows(self, investigation_id: str, evidence_ids: list[str]) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
        investigation = str(investigation_id or "").strip()
        if not investigation:
            raise ValueError("INVESTIGATION_ID_REQUIRED_FOR_EVIDENCE_BINDING")
        state = self._v6_state(investigation)
        by_id: dict[str, dict[str, Any]] = {}
        for row in state.get("observations", {}).values():
            evidence_id = str(row.get("evidence_id") or "").strip()
            if evidence_id:
                if evidence_id in by_id:
                    raise RuntimeError("V63_DUPLICATE_EVIDENCE_ID_IN_INVESTIGATION:" + evidence_id)
                by_id[evidence_id] = row
        selected = {evidence_id: by_id[evidence_id] for evidence_id in evidence_ids if evidence_id in by_id}
        return state, selected

    def _validate_v63_evidence_ownership(self, investigation_id: str, account_id: str, evidence_ids: list[str]) -> dict[str, Any]:
        ids = [str(value).strip() for value in evidence_ids if str(value).strip()]
        state, selected = self._v63_evidence_rows(investigation_id, ids)
        target_account = str(account_id or "").strip()
        investigation_account = str(state.get("start", {}).get("account", {}).get("account_id") or "").strip()
        mismatches: list[str] = []
        if not target_account or target_account != investigation_account:
            mismatches.extend(ids or ["<ACCOUNT_CONTEXT>"])
        for evidence_id in ids:
            row = selected.get(evidence_id)
            if not row:
                mismatches.append(evidence_id)
                continue
            if str(row.get("investigation_id") or "") != str(investigation_id):
                mismatches.append(evidence_id)
                continue
            if str(row.get("owner_type") or "").upper() == "ACCOUNT" and str(row.get("owner_id") or "") != target_account:
                mismatches.append(evidence_id)
        return {"valid": not mismatches, "mismatches": sorted(set(mismatches))}

    def _validate_v63_evidence_provenance(self, investigation_id: str, evidence_ids: list[str], required_source_type: str) -> dict[str, Any]:
        ids = [str(value).strip() for value in evidence_ids if str(value).strip()]
        _state, selected = self._v63_evidence_rows(investigation_id, ids)
        required = str(required_source_type or "").strip().upper()
        mismatches: list[str] = []
        for evidence_id in ids:
            row = selected.get(evidence_id)
            if not row:
                mismatches.append(evidence_id)
                continue
            categories = _canonical_source_categories(row)
            if required not in categories:
                mismatches.append(evidence_id)
        return {"valid": bool(ids) and not mismatches, "mismatches": sorted(set(mismatches)), "required_source_type": required}

    def _evidence_matches_product_profile(self, row: dict[str, Any], profile_id: str) -> bool:
        target = str(profile_id or "").strip().upper()
        if not target:
            return False
        structured = {"value": row.get("value"), "commercial_signals": row.get("commercial_signals")}
        explicit_ids: set[str] = set()
        stack: list[Any] = [structured]
        while stack:
            value = stack.pop()
            if isinstance(value, dict):
                for key, child in value.items():
                    if str(key).strip().casefold() in {"product_profile_id", "profile_id"} and child not in (None, ""):
                        explicit_ids.add(str(child).strip().upper())
                    else:
                        stack.append(child)
            elif isinstance(value, (list, tuple, set)):
                stack.extend(value)
        if explicit_ids:
            return explicit_ids == {target}

        source = row.get("source") if isinstance(row.get("source"), dict) else {}
        text = " ".join(
            [
                _structured_text(row.get("value")),
                _structured_text(row.get("commercial_signals")),
                str(row.get("boundary") or ""),
                str(source.get("raw_excerpt") or ""),
                str(row.get("claim_key") or ""),
            ]
        )
        matched_profiles: set[str] = set()
        for profile in list_product_profiles():
            candidate_id = str(profile.get("profile_id") or "").upper()
            if any(_token_present(text, token) for token in _profile_tokens(profile)):
                matched_profiles.add(candidate_id)
        return target in matched_profiles and not (matched_profiles - {target})

    def _validate_v63_opportunity_evidence_binding(self, investigation_id: str, opportunity: dict[str, Any], evidence_ids: list[str]) -> dict[str, Any]:
        ids = [str(value).strip() for value in evidence_ids if str(value).strip()]
        account_id = str(opportunity.get("account_id") or "").strip()
        ownership = self._validate_v63_evidence_ownership(investigation_id, account_id, ids)
        if not ownership.get("valid"):
            return {"valid": False, "mismatches": ownership.get("mismatches") or []}
        _state, selected = self._v63_evidence_rows(investigation_id, ids)
        target_profile = str(opportunity.get("product_profile_id") or "").strip().upper()
        mismatches: list[str] = []
        for evidence_id in ids:
            row = selected.get(evidence_id)
            if not row or str(row.get("result") or "").upper() not in {"POSITIVE", "CONFLICT"}:
                mismatches.append(evidence_id)
                continue
            if not self._evidence_matches_product_profile(row, target_profile):
                mismatches.append(evidence_id)
        return {"valid": bool(ids) and not mismatches, "mismatches": sorted(set(mismatches)), "product_profile_id": target_profile}

    def _derive_v63_opportunity_runtime_view(self, investigation_id: str, opportunity: dict[str, Any]) -> dict[str, Any]:
        get_claims = getattr(self, "get_claims", None)
        if not callable(get_claims):
            return {
                "derived_from_existing_evidence": False,
                "derived_basis": "CLAIMS_READER_NOT_BOUND",
                "derived_state_status": "UNAVAILABLE",
            }
        claims_result = get_claims({"investigation_id": investigation_id})
        claims = dict(claims_result.get("claims") or {})
        product_claims = [key for key in _PRODUCT_CLAIMS if key in claims]
        weighted = 0.0
        total = 0.0
        evidence_ids: set[str] = set()
        for claim_key in product_claims:
            claim = dict(claims.get(claim_key) or {})
            weight = float(claim.get("commercial_weight") or 0.0)
            total += weight
            factor = _CLAIM_SUPPORT_FACTOR.get(str(claim.get("state") or "UNSEEN"), 0.0)
            bound_for_claim: list[str] = []
            for evidence_id in claim.get("evidence_ids") or []:
                candidate = str(evidence_id or "").strip()
                if not candidate:
                    continue
                check = self._validate_v63_opportunity_evidence_binding(investigation_id, opportunity, [candidate])
                if check.get("valid"):
                    bound_for_claim.append(candidate)
            if bound_for_claim:
                weighted += weight * factor
                evidence_ids.update(bound_for_claim)
        view: dict[str, Any] = {
            "derived_from_existing_evidence": True,
            "derived_basis": "PRODUCT_BOUND_V6_CLAIMS_ONLY",
        }
        if total > 0 and evidence_ids:
            score = round(100.0 * weighted / total, 2)
            grade = _grade_for_score(score)
            view.update(
                {
                    "commercial_value_grade": grade,
                    "commercial_value_score": score,
                    "commercial_evidence_ids": sorted(evidence_ids),
                    "lifecycle_target": "QUALIFIED_TARGET" if grade in {"A+", "A", "A-", "B+"} else "OPPORTUNITY_CREATED",
                }
            )
        evaluate_confidence = getattr(self, "evaluate_research_confidence", None)
        if callable(evaluate_confidence):
            confidence = evaluate_confidence({"investigation_id": investigation_id})
            view["research_confidence"] = float(confidence.get("score") or 0.0)
        evaluate_outreach = getattr(self, "evaluate_outreach_readiness", None)
        if callable(evaluate_outreach):
            outreach = evaluate_outreach({"investigation_id": investigation_id})
            view["outreach_readiness"] = str(outreach.get("outreach_readiness") or "BLOCKED")
            view["company_route_status"] = view["outreach_readiness"]
        return view

    def _load_v63_capability_bundle(self) -> dict[str, Any] | None:
        raw_json = str(os.environ.get("CBI_V63_PRIVATE_CAPABILITY_BUNDLE_JSON") or "").strip()
        path_value = str(os.environ.get("CBI_V63_PRIVATE_CAPABILITY_BUNDLE_PATH") or "").strip()
        if raw_json:
            try:
                bundle = json.loads(raw_json)
            except json.JSONDecodeError as exc:
                raise RuntimeError("V63_PRIVATE_CAPABILITY_BUNDLE_JSON_INVALID") from exc
        elif path_value:
            path = Path(path_value).expanduser().resolve()
            try:
                bundle = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise RuntimeError("V63_PRIVATE_CAPABILITY_BUNDLE_PATH_INVALID") from exc
        else:
            return None
        if not isinstance(bundle, dict) or bundle.get("public_git_allowed") is not False:
            raise RuntimeError("V63_PRIVATE_CAPABILITY_BUNDLE_CONTRACT_INVALID")
        return bundle

    def _invoke_v63_durable_mutation(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        result = super()._invoke_v63_durable_mutation(tool_name, arguments)
        if tool_name in {"create_product_opportunity", "promote_opportunity_anchor"}:
            self._refresh_v63_locator_investigation(str(arguments.get("investigation_id") or ""))
        return result
