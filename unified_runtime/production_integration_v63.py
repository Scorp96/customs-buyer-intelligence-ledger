from __future__ import annotations

import base64
import copy
import gzip
import json
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from .capability_binding_v63 import bind_private_capability_bundle
from .demand_evidence import classify_demand_evidence
from .v63_projection import project_product_opportunities

_OPPORTUNITY_EVENTS = {"V63_PRODUCT_OPPORTUNITY_CREATED", "V63_OPPORTUNITY_ANCHOR_PROMOTED"}
_PRODUCT_CLAIMS = {"product.fit", "trade.import_activity", "commercial.procurement_need", "relationship.supply_chain"}
_PRODUCT_ALIASES = {
    "PVC": ("FREE PVC FOAM BOARD", "PVC FOAM BOARD", "PVC FOAM SHEET", "EXPANDED PVC", "CELUKA", "FOREX BOARD", "FOAMEX", "SINTRA", "PVC BOARD", "PVC SHEET"),
    "WPC": ("WOOD PLASTIC COMPOSITE", "WPC WALL", "WPC CLADDING", "WPC DECKING", "WPC FENCING", "WPC PANEL"),
    "SPC": ("STONE PLASTIC COMPOSITE", "SPC FLOORING", "SPC FLOOR", "RIGID CORE FLOORING"),
    "ACRYLIC_PMMA": ("ACRYLIC SHEET", "ACRYLIC BOARD", "PMMA", "PLEXIGLASS"),
}
_DIRECT_HINTS = ("CUSTOMS", "TRADE_DATA", "IMPORT_RECORD", "SHIPMENT", "BILL_OF_LADING", "BOL", "MANIFEST", "PURCHASE_ORDER", "INVOICE")


def normalize_v63_durable_event(investigation_id: str, event: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(event, dict) or str(event.get("event_type") or "") not in _OPPORTUNITY_EVENTS:
        return None
    payload, correlation = event.get("payload"), event.get("mutation_correlation")
    if not isinstance(payload, dict) or not isinstance(correlation, dict):
        return None
    row = copy.deepcopy(payload)
    row.update({
        "event_type": str(event.get("event_type") or ""),
        "correlation_id": str(correlation.get("correlation_id") or ""),
        "seq": int(event.get("seq") or 0),
        "investigation_id": str(payload.get("investigation_id") or investigation_id),
    })
    return row


def read_v63_durable_events(runtime: Any, investigation_id: str) -> list[dict[str, Any]]:
    return [row for row in (normalize_v63_durable_event(investigation_id, event) for event in runtime.store.read(investigation_id)) if row]


@dataclass
class V63OpportunityEventIndex:
    creates: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    promotions: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    built: bool = False
    dirty: bool = False

    def clear(self) -> None:
        self.creates.clear()
        self.promotions.clear()
        self.built = False
        self.dirty = False

    def observe_raw(self, investigation_id: str, event: dict[str, Any]) -> None:
        row = normalize_v63_durable_event(investigation_id, event)
        if not row:
            return
        opportunity_id = str(row.get("opportunity_id") or row.get("result_snapshot", {}).get("opportunity_id") or "")
        if not opportunity_id:
            return
        target = self.creates if row["event_type"] == "V63_PRODUCT_OPPORTUNITY_CREATED" else self.promotions
        target.setdefault(opportunity_id, []).append(copy.deepcopy(row))

    def rebuild(self, store: Any) -> None:
        self.clear()
        failures: list[str] = []
        for path in sorted(Path(store.root).glob("INV-*.jsonl")):
            try:
                events = store.read(path.stem)
            except Exception:
                failures.append(path.stem)
                continue
            for event in events:
                self.observe_raw(path.stem, event)
        if failures:
            self.dirty = True
            raise RuntimeError("V63_OPPORTUNITY_INDEX_REBUILD_FAILED:" + ",".join(failures))
        self.built = True

    def ensure_built(self, store: Any) -> None:
        if not self.built or self.dirty:
            self.rebuild(store)

    def query(self, filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        f = dict(filters or {})
        account = str(f.get("account_id") or "")
        opp = str(f.get("opportunity_id") or "")
        profile = str(f.get("product_profile_id") or "").upper()
        inv = str(f.get("investigation_id") or "")
        ids: set[str] = set()
        for oid, rows in self.creates.items():
            for row in rows:
                snap = row.get("result_snapshot") or {}
                if opp and oid != opp:
                    continue
                if account and str(snap.get("account_id") or row.get("account_id") or "") != account:
                    continue
                if profile and str(snap.get("product_profile_id") or row.get("product_profile_id") or "").upper() != profile:
                    continue
                if inv and str(row.get("investigation_id") or "") != inv:
                    continue
                ids.add(oid)
                break
        out: list[dict[str, Any]] = []
        for oid in sorted(ids):
            out.extend(copy.deepcopy(self.creates.get(oid, [])))
            out.extend(copy.deepcopy(self.promotions.get(oid, [])))
        out.sort(key=lambda row: (str(row.get("investigation_id") or ""), int(row.get("seq") or 0)))
        return out


def _index(runtime: Any) -> V63OpportunityEventIndex:
    value = getattr(runtime, "_v63_opportunity_event_index", None)
    if not isinstance(value, V63OpportunityEventIndex):
        value = V63OpportunityEventIndex()
        setattr(runtime, "_v63_opportunity_event_index", value)
    if getattr(runtime, "_v63_opportunity_event_index_lock", None) is None:
        setattr(runtime, "_v63_opportunity_event_index_lock", threading.RLock())
    return value


def _flatten(value: Any) -> str:
    parts: list[str] = []

    def walk(item: Any) -> None:
        if isinstance(item, str):
            parts.append(item)
        elif isinstance(item, dict):
            for key, val in item.items():
                if str(key).lower() not in {"content_sha256", "event_hash", "prev_hash"}:
                    walk(val)
        elif isinstance(item, (list, tuple, set)):
            for val in item:
                walk(val)

    walk(value)
    return " ".join(parts).upper().replace("_", " ").replace("-", " ").replace("/", " ")


def product_mentions(payload: Any) -> set[str]:
    text = _flatten(payload)
    mentions: set[str] = set()
    for profile, aliases in _PRODUCT_ALIASES.items():
        if any(re.search(rf"(?<![A-Z0-9]){re.escape(alias.replace('_',' ').replace('-',' '))}(?![A-Z0-9])", text) for alias in aliases):
            mentions.add(profile)
    return mentions


def _evidence(runtime: Any, investigation_id: str) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("evidence_id")): row
        for row in runtime._v6_state(investigation_id).get("observations", {}).values()
        if row.get("evidence_id")
    }


def validate_v63_evidence_ownership(runtime: Any, investigation_id: str, account_id: str, evidence_ids: Iterable[str]) -> dict[str, Any]:
    state = runtime._v6_state(investigation_id)
    if str(state.get("start", {}).get("account", {}).get("account_id") or "") != str(account_id):
        return {"valid": False, "reason": "INVESTIGATION_ACCOUNT_MISMATCH"}
    rows = _evidence(runtime, investigation_id)
    missing: list[str] = []
    wrong: list[str] = []
    for eid in map(str, evidence_ids):
        row = rows.get(eid)
        if row is None:
            missing.append(eid)
        elif str(row.get("owner_type") or "") != "ACCOUNT" or str(row.get("owner_id") or "") != str(account_id):
            wrong.append(eid)
    return {"valid": not missing and not wrong, "missing_evidence_ids": missing, "wrong_owner_evidence_ids": wrong}


def _direct_procurement(row: dict[str, Any]) -> bool:
    source = dict(row.get("source") or {})
    if str(source.get("reference_type") or "").upper() in {"USER_INPUT", "LEGACY_CRM", "DERIVED_CALCULATION"}:
        return False
    labels = "_".join((str(source.get("source_type") or ""), str(source.get("source_family") or ""))).upper()
    if any(hint in labels for hint in _DIRECT_HINTS):
        return True
    material = _flatten({"value": row.get("value"), "boundary": row.get("boundary"), "source": source})
    return any(marker in material for marker in ("BILL OF LADING", " BOL ", "SHIPMENT", "IMPORTING", "IMPORT RECORD", "CONSIGNEE"))


def validate_v63_evidence_provenance(runtime: Any, investigation_id: str, evidence_ids: Iterable[str], required_source_type: str) -> dict[str, Any]:
    rows = _evidence(runtime, investigation_id)
    required = str(required_source_type or "").upper()
    missing: list[str] = []
    failed: list[str] = []
    tiers: dict[str, str] = {}
    for eid in map(str, evidence_ids):
        row = rows.get(eid)
        if row is None:
            missing.append(eid)
            continue
        direct = _direct_procurement(row)
        source_type = "CUSTOMS" if required in {"CUSTOMS", "TRADE_DATA", "DIRECT_PROCUREMENT"} and direct else str(row.get("source", {}).get("source_type") or "UNKNOWN")
        classified = classify_demand_evidence({"source_type": source_type, "evidence_ids": [eid], "verified": True})
        tiers[eid] = str(classified.get("tier") or "D4")
        if required in {"CUSTOMS", "TRADE_DATA", "DIRECT_PROCUREMENT"} and (not direct or classified.get("supports_procurement") is not True):
            failed.append(eid)
    return {"valid": not missing and not failed, "missing_evidence_ids": missing, "failed_evidence_ids": failed, "tiers": tiers}


def validate_v63_opportunity_evidence_binding(runtime: Any, investigation_id: str, opportunity: dict[str, Any], evidence_ids: Iterable[str]) -> dict[str, Any]:
    target = str(opportunity.get("product_profile_id") or "").upper()
    rows = _evidence(runtime, investigation_id)
    missing: list[str] = []
    wrong: list[str] = []
    ambiguous: list[str] = []
    mentions: dict[str, list[str]] = {}
    if target not in _PRODUCT_ALIASES:
        return {"valid": False, "reason": "UNKNOWN_PRODUCT_PROFILE"}
    for eid in map(str, evidence_ids):
        row = rows.get(eid)
        if row is None:
            missing.append(eid)
            continue
        explicit = str(row.get("product_profile_id") or "").upper()
        if not explicit and isinstance(row.get("value"), dict):
            explicit = str(row["value"].get("product_profile_id") or "").upper()
        found = {explicit} if explicit else product_mentions({
            "value": row.get("value"),
            "boundary": row.get("boundary"),
            "commercial_signals": row.get("commercial_signals"),
            "source": row.get("source"),
        })
        mentions[eid] = sorted(found)
        if found == {target}:
            continue
        if target in found and len(found) > 1:
            ambiguous.append(eid)
        elif found:
            wrong.append(eid)
        else:
            ambiguous.append(eid)
    return {
        "valid": not missing and not wrong and not ambiguous,
        "missing_evidence_ids": missing,
        "wrong_product_evidence_ids": wrong,
        "ambiguous_product_evidence_ids": ambiguous,
        "mentions": mentions,
    }


def _private_bundle(environ: dict[str, str] | None = None) -> tuple[dict[str, Any], str]:
    env = os.environ if environ is None else environ
    raw = [
        str(env.get(k) or "").strip()
        for k in (
            "CBI_V63_CAPABILITY_BUNDLE_JSON",
            "CBI_V63_CAPABILITY_BUNDLE_B64",
            "CBI_V63_CAPABILITY_BUNDLE_GZIP_B64",
            "CBI_V63_CAPABILITY_BUNDLE_PATH",
        )
    ]
    if sum(bool(x) for x in raw) == 0:
        raise RuntimeError("CAPABILITY_PROFILE_NOT_BOUND")
    if sum(bool(x) for x in raw) > 1:
        raise RuntimeError("V63_CAPABILITY_SOURCE_AMBIGUOUS")
    if raw[0]:
        text, source = raw[0], "PRIVATE_ENV_JSON"
    elif raw[1]:
        try:
            text = base64.b64decode(raw[1], validate=True).decode("utf-8")
        except Exception as exc:
            raise RuntimeError("V63_CAPABILITY_BUNDLE_B64_INVALID") from exc
        source = "PRIVATE_ENV_B64"
    elif raw[2]:
        try:
            text = gzip.decompress(base64.b64decode(raw[2], validate=True)).decode("utf-8")
        except Exception as exc:
            raise RuntimeError("V63_CAPABILITY_BUNDLE_GZIP_B64_INVALID") from exc
        source = "PRIVATE_ENV_GZIP_B64"
    else:
        path = Path(raw[3]).expanduser()
        if not path.is_absolute():
            raise RuntimeError("V63_CAPABILITY_BUNDLE_PATH_MUST_BE_ABSOLUTE")
        text, source = path.read_text(encoding="utf-8"), "PRIVATE_FILE"
    try:
        bundle = json.loads(text)
    except json.JSONDecodeError as exc:
        raise RuntimeError("V63_CAPABILITY_BUNDLE_JSON_INVALID") from exc
    if not isinstance(bundle, dict):
        raise RuntimeError("V63_CAPABILITY_BUNDLE_JSON_INVALID")
    return bundle, source


def load_private_capability_bundle_from_env(runtime: Any, environ: dict[str, str] | None = None) -> dict[str, Any]:
    bundle, source = _private_bundle(environ)
    result = bind_private_capability_bundle(runtime, bundle)
    return {**result, "source": source, "private_content_returned": False}


def derive_v63_product_runtime_view(runtime: Any, investigation_id: str, opportunity: dict[str, Any]) -> dict[str, Any]:
    state = copy.deepcopy(runtime._v6_state(investigation_id))
    account = str(state.get("start", {}).get("account", {}).get("account_id") or "")
    if account != str(opportunity.get("account_id") or ""):
        raise RuntimeError("V63_OPPORTUNITY_ACCOUNT_INVESTIGATION_MISMATCH")
    bound: set[str] = set()
    filtered: dict[str, dict[str, Any]] = {}
    for oid, row in state.get("observations", {}).items():
        if str(row.get("claim_key") or "") not in _PRODUCT_CLAIMS:
            filtered[oid] = row
            continue
        eid = str(row.get("evidence_id") or "")
        if eid and validate_v63_opportunity_evidence_binding(runtime, investigation_id, opportunity, [eid]).get("valid"):
            filtered[oid] = row
            if row.get("result") == "POSITIVE":
                bound.add(eid)
    state["observations"] = filtered
    claims = runtime._claims_view(state)

    from .commercial_hardening import OPPORTUNITY_LIFT_WEIGHTS as weights, _CLAIM_STRENGTH as strengths

    baseline = round(
        100
        * sum(c["commercial_weight"] * strengths[c["state"]] for c in claims.values())
        / (sum(c["commercial_weight"] for c in claims.values()) or 1),
        2,
    )
    factors = runtime._commercial_opportunity_factors(state, claims)
    for name in ("strategic_fit", "replacement_opportunity"):
        factor = factors.get(name) or {}
        ids = set(map(str, factor.get("evidence_ids") or []))
        if factor.get("status") == "SUPPORTED" and (not ids or not ids.issubset(bound)):
            factors[name] = {
                "factor": name,
                "status": "UNKNOWN",
                "strength": None,
                "basis": "Product-bound evidence required.",
                "observation_ids": [],
                "evidence_ids": [],
                "evidence_paths": [],
            }
    lift = 0.0
    for name, factor in factors.items():
        contribution = 0.0 if factor.get("strength") is None else weights[name] * float(factor["strength"])
        factor["lift_weight"] = weights[name]
        factor["score_contribution"] = round(contribution, 4)
        lift += contribution
    lift = round(lift, 2)
    score = round(min(100.0, baseline + lift), 2)

    from . import v6 as _v6
    grade = _v6._grade_for_score(score)

    states = {
        k: str((claims.get(k) or {}).get("state") or "UNSEEN")
        for k in sorted(_PRODUCT_CLAIMS)
    }
    stage = str(opportunity.get("stage") or opportunity.get("lifecycle_stage") or "OPPORTUNITY_CREATED").upper()
    if (
        bound
        and states["product.fit"] in {"SUPPORTED", "STRONGLY_SUPPORTED"}
        and any(states[k] in {"SUPPORTED", "STRONGLY_SUPPORTED"} for k in ("trade.import_activity", "commercial.procurement_need"))
        and score >= 68
    ):
        stage = "QUALIFIED_TARGET"
    return {
        "opportunity_id": str(opportunity.get("opportunity_id") or ""),
        "account_id": account,
        "product_profile_id": str(opportunity.get("product_profile_id") or "").upper(),
        "commercial_value_grade": grade,
        "commercial_value_score": score,
        "baseline_claim_score": baseline,
        "opportunity_lift": lift,
        "opportunity_model": "EVIDENCE_BOUND_HEURISTIC_V1",
        "opportunity_factors": factors,
        "commercial_evidence_ids": sorted(bound),
        "lifecycle_stage": stage,
        "product_claim_states": states,
        "derived_from_existing_evidence": True,
        "derived_basis": "PRODUCT_FILTERED_EXISTING_V61_COMMERCIAL_OPPORTUNITY_ENGINE",
    }


class V63ProductionIntegrationMixin:
    def _read_v63_durable_events(self, investigation_id: str) -> list[dict[str, Any]]:
        return read_v63_durable_events(self, investigation_id)

    def _query_v63_opportunity_events(self, filters: dict[str, Any]) -> list[dict[str, Any]]:
        idx = _index(self)
        lock = getattr(self, "_v63_opportunity_event_index_lock")
        with lock:
            idx.ensure_built(self.store)
            return idx.query(filters)

    def _observe_v63_durable_append(self, investigation_id: str, event: dict[str, Any]) -> None:
        idx = _index(self)
        lock = getattr(self, "_v63_opportunity_event_index_lock")
        with lock:
            try:
                idx.observe_raw(investigation_id, event)
            except Exception:
                idx.dirty = True

    def _mark_v63_opportunity_index_dirty(self) -> None:
        _index(self).dirty = True

    def _validate_v63_evidence_ownership(self, investigation_id: str, account_id: str, evidence_ids: Iterable[str]) -> dict[str, Any]:
        return validate_v63_evidence_ownership(self, investigation_id, account_id, evidence_ids)

    def _validate_v63_evidence_provenance(self, investigation_id: str, evidence_ids: Iterable[str], required_source_type: str) -> dict[str, Any]:
        return validate_v63_evidence_provenance(self, investigation_id, evidence_ids, required_source_type)

    def _validate_v63_opportunity_evidence_binding(self, investigation_id: str, opportunity: dict[str, Any], evidence_ids: Iterable[str]) -> dict[str, Any]:
        return validate_v63_opportunity_evidence_binding(self, investigation_id, opportunity, evidence_ids)

    def _derive_v63_opportunity_runtime_view(self, investigation_id: str, opportunity: dict[str, Any]) -> dict[str, Any]:
        return derive_v63_product_runtime_view(self, investigation_id, opportunity)

    def _load_v63_capability_bundle(self) -> dict[str, Any]:
        bundle, source = _private_bundle()
        setattr(self, "_v63_capability_source", source)
        return bundle

    def _ensure_v63_capability_profiles(self) -> bool:
        if getattr(self, "_v63_capability_profiles", None):
            return True
        try:
            bind_private_capability_bundle(self, self._load_v63_capability_bundle())
        except (OSError, ValueError, RuntimeError):
            return False
        return bool(getattr(self, "_v63_capability_profiles", None))

    def get_runtime_contract(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        result = copy.deepcopy(super().get_runtime_contract(arguments or {}))
        v63 = result.setdefault("demand_expansion_v6_3", {})
        cap = self._ensure_v63_capability_profiles()
        tools = ["get_product_opportunities", "get_demand_anchors", "get_market_cells", "evaluate_market_acceptance", "get_expansion_state"]
        bindings = {
            "durable_event_reader": "BOUND",
            "opportunity_event_query": "BOUND",
            "evidence_ownership_verifier": "BOUND",
            "evidence_provenance_verifier": "BOUND",
            "opportunity_evidence_verifier": "BOUND",
            "opportunity_derived_state_provider": "BOUND",
            "capability_profile_source": "BOUND_IN_MEMORY" if cap else "UNBOUND",
        }
        blockers = [] if cap else ["V63_CAPABILITY_PROFILE_SOURCE_NOT_BOUND"]
        exposed = {n: callable(getattr(self, n, None)) for n in tools}
        v63.update({
            "read_model_runtime_bindings_v6_3": bindings,
            "runtime_integration_blockers_v6_3": blockers,
            "runtime_read_model_bindings_complete": not blockers,
            "runtime_read_model_binding_status": "BOUND" if not blockers else "FAIL_CLOSED_INCOMPLETE",
            "runtime_binding_status_is_not_production_acceptance": True,
            "required_read_model_tools_v6_3": tools,
            "read_model_tools_exposed_v6_3": exposed,
            "read_model_tool_surface_complete_v6_3": all(exposed.values()),
            "opportunity_index_authority": "NON_AUTHORITATIVE_REBUILDABLE_MEMORY_INDEX",
            "opportunity_index_source_of_truth": "EXISTING_APPEND_ONLY_SESSION_STORE",
            "capability_source_private": True,
            "capability_source": str(getattr(self, "_v63_capability_source", "UNBOUND")),
        })
        return result

    def _owner_gate(self, inv: str, account: str, ids: list[str]) -> None:
        if not self._validate_v63_evidence_ownership(inv, account, ids).get("valid"):
            raise ValueError("EVIDENCE_OWNER_MISMATCH")

    def _product_gate(self, inv: str, opp: dict[str, Any], ids: list[str]) -> None:
        if not self._validate_v63_opportunity_evidence_binding(inv, opp, ids).get("valid"):
            raise ValueError("EVIDENCE_OPPORTUNITY_BINDING_MISMATCH")

    def _provenance_gate(self, inv: str, ids: list[str], source: str) -> None:
        if not self._validate_v63_evidence_provenance(inv, ids, source).get("valid"):
            raise ValueError(f"{source.upper()}_EVIDENCE_PROVENANCE_MISMATCH")

    def _join_v63_view(self, inv: str, row: dict[str, Any]) -> dict[str, Any]:
        from .opportunity_domain import LIFECYCLE_STAGES

        out = copy.deepcopy(row)
        durable = str(out.get("stage") or out.get("lifecycle_stage") or "OPPORTUNITY_CREATED").upper()
        view = self._derive_v63_opportunity_runtime_view(inv, out)
        ids = list(view.get("commercial_evidence_ids") or [])
        target = str(view.get("lifecycle_stage") or "").upper()
        if (
            view.get("commercial_value_grade")
            or (target in LIFECYCLE_STAGES and LIFECYCLE_STAGES.index(target) >= LIFECYCLE_STAGES.index("QUALIFIED_TARGET"))
        ) and not ids:
            raise ValueError("V63_DERIVED_VIEW_COMMERCIAL_EVIDENCE_REQUIRED")
        if ids:
            self._owner_gate(inv, str(out.get("account_id") or ""), ids)
            self._product_gate(inv, out, ids)
        for key in (
            "commercial_value_grade", "commercial_value_score", "baseline_claim_score",
            "opportunity_lift", "opportunity_model", "opportunity_factors",
            "commercial_evidence_ids", "product_claim_states", "derived_from_existing_evidence",
            "derived_basis",
        ):
            if key in view:
                out[key] = copy.deepcopy(view[key])
        out["durable_stage"] = durable
        out["lifecycle_stage"] = (
            LIFECYCLE_STAGES[max(LIFECYCLE_STAGES.index(durable), LIFECYCLE_STAGES.index(target))]
            if target else durable
        )
        out["derived_state_joined"] = True
        return out

    def get_product_opportunities(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        args = dict(arguments or {})
        inv = str(args.get("investigation_id") or "")
        events = self._read_v63_durable_events(inv) if inv else self._query_v63_opportunity_events(args)
        result = project_product_opportunities(
            events,
            account_id=args.get("account_id"),
            opportunity_id=args.get("opportunity_id"),
            product_profile_id=args.get("product_profile_id"),
        )
        result["opportunities"] = [
            self._join_v63_view(str(row.get("investigation_id") or inv), row)
            for row in result["opportunities"]
        ]
        result["projection_scope"] = "INVESTIGATION" if inv else "VISIBLE_PORTFOLIO_INDEX"
        return result

    def _v63_resolve_opportunity(self, arguments: dict[str, Any]) -> dict[str, Any]:
        inv = str(arguments.get("investigation_id") or "")
        oid = str(arguments.get("opportunity_id") or "")
        supplied = arguments.get("opportunity")
        if inv or oid:
            if not inv or not oid:
                raise ValueError("INVESTIGATION_ID_AND_OPPORTUNITY_ID_REQUIRED")
            rows = self.get_product_opportunities({"investigation_id": inv, "opportunity_id": oid})["opportunities"]
            if len(rows) != 1:
                raise ValueError("OPPORTUNITY_NOT_FOUND")
            durable = copy.deepcopy(rows[0])
            for field in ("account_id", "product_profile_id", "product_profile_version", "product_profile_sha256"):
                if arguments.get(field) not in (None, "") and str(arguments.get(field)).upper() != str(durable.get(field) or "").upper():
                    raise ValueError(f"OPPORTUNITY_CONTEXT_IDENTITY_CONFLICT:{field}")
            if isinstance(supplied, dict):
                for field in ("opportunity_id", "account_id", "product_profile_id", "product_profile_version", "product_profile_sha256"):
                    if supplied.get(field) not in (None, "") and str(supplied.get(field)).upper() != str(durable.get(field) or "").upper():
                        raise ValueError(f"SUPPLIED_OPPORTUNITY_IDENTITY_CONFLICT:{field}")
            return durable
        if isinstance(supplied, dict) and supplied:
            return copy.deepcopy(supplied)
        raise ValueError("INVESTIGATION_ID_AND_OPPORTUNITY_ID_REQUIRED")

    def get_demand_anchors(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        seeds = [dict(x) for x in list(dict(arguments or {}).get("seeds") or []) if isinstance(x, dict)]
        return {"status": "READY", "anchors": [self.derive_demand_anchor(x) for x in seeds], "derived_view": True, "persistent_mutation_performed": False}

    def get_market_cells(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        from .demand_market import derive_market_cell
        cells = [
            derive_market_cell(
                dict(x.get("anchor") or {}),
                list(x.get("application_ids") or []),
                list(x.get("buyer_archetype_ids") or []),
                channel=x.get("channel"),
            )
            for x in list(dict(arguments or {}).get("items") or [])
            if isinstance(x, dict)
        ]
        return {"status": "READY", "market_cells": cells, "derived_view": True, "persistent_mutation_performed": False}

    def evaluate_market_acceptance(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        from .demand_market import evaluate_market_acceptance
        result = evaluate_market_acceptance(list(dict(arguments or {}).get("anchors") or []))
        result.update({"derived_view": True, "persistent_mutation_performed": False})
        return result

    def get_expansion_state(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        result = self.get_product_opportunities(arguments)
        return {
            "status": "READY",
            "product_opportunities": result["opportunities"],
            "product_opportunity_count": result["projected_opportunity_count"],
            "persistent_mutation_performed": False,
        }

    def get_capability_profile(self, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if not getattr(self, "_v63_capability_profiles", None):
            self._ensure_v63_capability_profiles()
        return super().get_capability_profile(arguments or {})

    def preview_customs_seed_expansion(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = copy.deepcopy(arguments)
        inv = str(args.get("investigation_id") or "")
        ids = list(map(str, args.get("source_evidence_ids") or []))
        opp = self._v63_resolve_opportunity(args)
        self._owner_gate(inv, str(opp.get("account_id") or ""), ids)
        self._product_gate(inv, opp, ids)
        self._provenance_gate(inv, ids, "CUSTOMS")
        args["source_type"] = "CUSTOMS"
        return super().preview_customs_seed_expansion(args)

    def plan_contact_exhaustion(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return super().plan_contact_exhaustion({**copy.deepcopy(arguments), "opportunity": self._v63_resolve_opportunity(arguments)})

    def evaluate_route_reuse(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return super().evaluate_route_reuse({**copy.deepcopy(arguments), "opportunity": self._v63_resolve_opportunity(arguments)})

    def get_portfolio_metrics(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = copy.deepcopy(arguments)
        args["opportunities"] = args.get("opportunities") if isinstance(args.get("opportunities"), list) else self.get_product_opportunities(args)["opportunities"]
        return super().get_portfolio_metrics(args)

    def schedule_expansion_research(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = copy.deepcopy(arguments)
        args["opportunities"] = args.get("opportunities") if isinstance(args.get("opportunities"), list) else self.get_product_opportunities(args)["opportunities"]
        return super().schedule_expansion_research(args)

    def evaluate_sales_readiness(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return super().evaluate_sales_readiness({**copy.deepcopy(arguments), "opportunity": self._v63_resolve_opportunity(arguments)})

    def derive_demand_anchor(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from .demand_market import is_direct_procurement_source
        args = copy.deepcopy(arguments)
        inv = str(args.get("investigation_id") or "")
        ids = list(map(str, args.get("source_evidence_ids") or []))
        opp = self._v63_resolve_opportunity(args)
        self._owner_gate(inv, str(opp.get("account_id") or ""), ids)
        self._product_gate(inv, opp, ids)
        if is_direct_procurement_source(str(args.get("source_type") or "")):
            self._provenance_gate(inv, ids, str(args.get("source_type") or ""))
        result = super().derive_demand_anchor(args)
        result["evidence_ownership_verified"] = True
        return result

    def evaluate_product_opportunity(self, arguments: dict[str, Any]) -> dict[str, Any]:
        args = copy.deepcopy(arguments)
        opp = self._v63_resolve_opportunity(args)
        ids = [str(v) for v in dict(args.get("assessment") or {}).get("commercial_evidence_ids", [])]
        self._owner_gate(str(args.get("investigation_id") or ""), str(opp.get("account_id") or ""), ids)
        self._product_gate(str(args.get("investigation_id") or ""), opp, ids)
        args["opportunity"] = opp
        result = super().evaluate_product_opportunity(args)
        result["validated_against_projected_opportunity"] = True
        return result
