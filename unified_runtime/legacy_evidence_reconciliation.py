"""Fail-closed legacy quantitative Evidence reconciliation for v6.1.

This administrative Runtime primitive projects an already-durable, Account-owned
legacy Evidence fact into one structured v6 Observation.  It is intentionally
not part of the ordinary MCP tool surface.  The caller must pin the exact legacy
provenance and provide explicit arithmetic components whose proof literals are
present in the durable Evidence boundary.  The Runtime recomputes the aggregate,
rejects annualization/inferred metrics, and delegates the append to the normal
v6 research-bundle compiler.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal, InvalidOperation
from typing import Any

from . import v6 as _v6


OBSERVED_COMMERCIAL_NUMERIC_METRICS = (
    "visible_weight_kg",
    "total_weight_kg",
    "import_weight_kg",
    "shipment_count",
    "import_count",
    "visible_shipments",
    "bill_of_lading_count",
)

_RECONCILIATION_SCHEMA = "cbi.legacy-quantitative-evidence-reconciliation.v6.1"
_PROVENANCE_FIELDS = (
    "claim_key",
    "module_or_branch",
    "source_family",
    "source_type",
    "reference_type",
    "url",
    "locator",
    "content_sha256",
    "observed_at",
    "freshness",
)


def _decimal(value: Any, field: str) -> Decimal:
    if isinstance(value, bool):
        raise _v6.ValidationError(f"{field}: finite non-negative number required")
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise _v6.ValidationError(
            f"{field}: finite non-negative number required"
        ) from exc
    if not number.is_finite() or number < 0:
        raise _v6.ValidationError(f"{field}: finite non-negative number required")
    return number


def _json_number(value: Decimal) -> int | float:
    if value == value.to_integral_value():
        return int(value)
    rendered = float(value)
    if not math.isfinite(rendered):
        raise _v6.ValidationError("reconciliation total is not JSON-finite")
    return rendered


def _freshness(value: Any) -> str:
    token = str(value or "UNKNOWN").strip().upper()
    aliases = {
        "CURRENT_CONFIRMED": "CURRENT",
        "CURRENT_LIKELY": "CURRENT",
    }
    token = aliases.get(token, token)
    if token not in _v6.FRESHNESS_LEVELS:
        raise _v6.ValidationError(
            "legacy Evidence freshness cannot be represented by the v6 compiler"
        )
    return token


class V61LegacyEvidenceReconciliationMixin:
    """Project exact observed legacy quantitative facts into native v6 Evidence."""

    @staticmethod
    def _legacy_quantitative_reconciliation_fingerprint(
        *,
        investigation_id: str,
        legacy_evidence_id: str,
        legacy_content_sha256: str,
        metric: str,
        components: list[dict[str, Any]],
        expected_total: int | float,
    ) -> str:
        return _v6.digest({
            "schema": _RECONCILIATION_SCHEMA,
            "investigation_id": investigation_id,
            "legacy_evidence_id": legacy_evidence_id,
            "legacy_content_sha256": legacy_content_sha256,
            "metric": metric,
            "aggregation": "SUM",
            "components": components,
            "expected_total": expected_total,
            "annualized": False,
        })

    @staticmethod
    def _existing_legacy_quantitative_projection(
        state: dict[str, Any], fingerprint: str
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for row in state.get("observations", {}).values():
            if not isinstance(row, dict):
                continue
            value = row.get("value")
            if not isinstance(value, dict):
                continue
            metadata = value.get("legacy_reconciliation")
            if (
                isinstance(metadata, dict)
                and metadata.get("fingerprint") == fingerprint
            ):
                rows.append(row)
        return rows

    def _validate_legacy_quantitative_reconciliation(
        self,
        investigation_id: str,
        reconciliation: dict[str, Any],
    ) -> dict[str, Any]:
        legacy_state = self._state(investigation_id)
        v6_state = self._v6_state(investigation_id)
        account_id = str(legacy_state["start"]["account"]["account_id"])

        legacy_evidence_id = _v6._safe_id(
            reconciliation.get("legacy_evidence_id"),
            "reconciliation.legacy_evidence_id",
        )
        evidence = (legacy_state.get("evidence") or {}).get(legacy_evidence_id)
        if not isinstance(evidence, dict):
            raise _v6.ValidationError(
                "reconciliation.legacy_evidence_id: durable legacy Evidence not found"
            )
        if evidence.get("owner_type") != "ACCOUNT" or str(
            evidence.get("owner_id") or ""
        ) != account_id:
            raise _v6.ValidationError(
                "legacy quantitative reconciliation requires Account-owned Evidence "
                "for the current investigation account"
            )

        expected = _v6._require_object(
            reconciliation.get("expected_provenance"),
            "reconciliation.expected_provenance",
        )
        missing_expected = [key for key in _PROVENANCE_FIELDS if key not in expected]
        if missing_expected:
            raise _v6.ValidationError(
                "reconciliation.expected_provenance missing exact fields: "
                + ", ".join(missing_expected)
            )
        expected_content_sha = _v6._valid_hash(
            expected.get("content_sha256"),
            "reconciliation.expected_provenance.content_sha256",
        )
        if str(evidence.get("content_sha256") or "").lower() != expected_content_sha:
            raise _v6.ValidationError("legacy Evidence content_sha256 changed")
        for key in _PROVENANCE_FIELDS:
            expected_value = expected_content_sha if key == "content_sha256" else expected.get(key)
            observed_value = (
                str(evidence.get(key) or "").lower()
                if key == "content_sha256"
                else evidence.get(key)
            )
            if observed_value != expected_value:
                raise _v6.ValidationError(
                    f"legacy Evidence provenance mismatch for {key}"
                )

        if str(evidence.get("reference_type") or "").upper() != "PUBLIC_URL":
            raise _v6.ValidationError(
                "legacy quantitative reconciliation currently requires PUBLIC_URL Evidence"
            )
        url = str(evidence.get("url") or "").strip()
        if not re.fullmatch(r"https?://\S+", url, flags=re.I):
            raise _v6.ValidationError("legacy Evidence requires a concrete HTTP(S) URL")

        boundary = str(evidence.get("boundary") or "")
        if not boundary:
            raise _v6.ValidationError("legacy Evidence boundary is required")
        expected_boundary_sha = _v6._valid_hash(
            reconciliation.get("expected_boundary_sha256"),
            "reconciliation.expected_boundary_sha256",
        )
        if _v6.digest(boundary.encode("utf-8")) != expected_boundary_sha:
            raise _v6.ValidationError("legacy Evidence boundary changed")

        linked_attempts = [
            row
            for row in (legacy_state.get("attempts") or {}).values()
            if isinstance(row, dict)
            and legacy_evidence_id
            in [str(item) for item in row.get("evidence_ids") or []]
        ]
        positive_attempts = [
            row
            for row in linked_attempts
            if row.get("owner_type") == "ACCOUNT"
            and str(row.get("owner_id") or "") == account_id
            and str(row.get("result") or "").upper() == "POSITIVE"
        ]
        if not positive_attempts:
            raise _v6.ValidationError(
                "legacy Evidence must be bound to at least one positive Account-owned Attempt"
            )

        target_claim_key = str(
            reconciliation.get("target_claim_key") or ""
        ).strip()
        if target_claim_key != "trade.import_activity":
            raise _v6.ValidationError(
                "legacy quantitative reconciliation currently targets trade.import_activity only"
            )

        metric = str(reconciliation.get("metric") or "").strip()
        if metric not in OBSERVED_COMMERCIAL_NUMERIC_METRICS:
            raise _v6.ValidationError(
                "reconciliation.metric is not an allowed observed non-annualized metric"
            )
        if "annual" in metric.casefold() or bool(reconciliation.get("annualized")):
            raise _v6.ValidationError(
                "annualized/inferred quantitative reconciliation is prohibited"
            )
        aggregation = str(reconciliation.get("aggregation") or "").strip().upper()
        if aggregation != "SUM":
            raise _v6.ValidationError("reconciliation.aggregation must be SUM")

        raw_components = _v6._require_list(
            reconciliation.get("components"),
            "reconciliation.components",
        )
        if not raw_components:
            raise _v6.ValidationError("reconciliation.components must not be empty")
        components: list[dict[str, Any]] = []
        proof_literals: set[str] = set()
        total = Decimal("0")
        for index, raw in enumerate(raw_components):
            item = _v6._require_object(raw, f"reconciliation.components[{index}]")
            number = _decimal(
                item.get("value"),
                f"reconciliation.components[{index}].value",
            )
            proof_literal = _v6._nonempty(
                item.get("proof_literal"),
                f"reconciliation.components[{index}].proof_literal",
            )
            if proof_literal in proof_literals:
                raise _v6.ValidationError(
                    "reconciliation component proof literals must be unique"
                )
            if proof_literal not in boundary:
                raise _v6.ValidationError(
                    f"reconciliation.components[{index}].proof_literal not present "
                    "in durable Evidence boundary"
                )
            proof_literals.add(proof_literal)
            total += number
            components.append({
                "value": _json_number(number),
                "proof_literal": proof_literal,
            })

        expected_total_decimal = _decimal(
            reconciliation.get("expected_total"),
            "reconciliation.expected_total",
        )
        if total != expected_total_decimal:
            raise _v6.ValidationError(
                "reconciliation expected_total does not equal the recomputed SUM"
            )
        total_proof_literal = _v6._nonempty(
            reconciliation.get("total_proof_literal"),
            "reconciliation.total_proof_literal",
        )
        if total_proof_literal not in boundary:
            raise _v6.ValidationError(
                "reconciliation.total_proof_literal not present in durable Evidence boundary"
            )

        expected_total = _json_number(expected_total_decimal)
        fingerprint = self._legacy_quantitative_reconciliation_fingerprint(
            investigation_id=investigation_id,
            legacy_evidence_id=legacy_evidence_id,
            legacy_content_sha256=expected_content_sha,
            metric=metric,
            components=components,
            expected_total=expected_total,
        )
        existing = self._existing_legacy_quantitative_projection(
            v6_state, fingerprint
        )
        if len(existing) > 1:
            raise _v6.ValidationError(
                "multiple existing v6 observations share the reconciliation fingerprint"
            )
        if existing:
            row = existing[0]
            value = row.get("value") or {}
            if value.get(metric) != expected_total:
                raise _v6.ValidationError(
                    "existing reconciliation fingerprint has a conflicting metric value"
                )

        expected_tail = _v6._valid_hash(
            reconciliation.get("expected_pre_reconciliation_tail_event_hash"),
            "reconciliation.expected_pre_reconciliation_tail_event_hash",
        )
        if not existing:
            events = self.store.read(investigation_id)
            if not events or events[-1].get("event_hash") != expected_tail:
                raise _v6.ValidationError(
                    "investigation tail changed after reconciliation plan was prepared"
                )

        return {
            "legacy_state": legacy_state,
            "v6_state": v6_state,
            "account_id": account_id,
            "legacy_evidence_id": legacy_evidence_id,
            "evidence": evidence,
            "positive_attempt_ids": sorted({
                str(row.get("attempt_id"))
                for row in positive_attempts
                if row.get("attempt_id")
            }),
            "target_claim_key": target_claim_key,
            "metric": metric,
            "components": components,
            "expected_total": expected_total,
            "total_proof_literal": total_proof_literal,
            "fingerprint": fingerprint,
            "existing": existing,
            "expected_tail": expected_tail,
        }

    def reconcile_legacy_quantitative_evidence(
        self, arguments: dict[str, Any]
    ) -> dict[str, Any]:
        """Validate and optionally append one exact legacy numeric projection.

        This method is intentionally absent from ``V6_CBI_MCP_TOOL_NAMES``.  It is
        an administrative/direct-Runtime primitive for controlled reconciliation.
        """

        args = _v6._require_object(arguments, "arguments")
        investigation_id = _v6._nonempty(
            args.get("investigation_id"), "investigation_id"
        )
        reconciliation = _v6._require_object(
            args.get("reconciliation"), "reconciliation"
        )
        validated = self._validate_legacy_quantitative_reconciliation(
            investigation_id, reconciliation
        )
        evidence = validated["evidence"]
        metric = validated["metric"]
        expected_total = validated["expected_total"]
        fingerprint = validated["fingerprint"]

        plan = {
            "schema": _RECONCILIATION_SCHEMA,
            "investigation_id": investigation_id,
            "legacy_evidence_id": validated["legacy_evidence_id"],
            "legacy_content_sha256": evidence.get("content_sha256"),
            "legacy_boundary_sha256": _v6.digest(
                str(evidence.get("boundary") or "").encode("utf-8")
            ),
            "positive_attempt_ids": validated["positive_attempt_ids"],
            "target_claim_key": validated["target_claim_key"],
            "metric": metric,
            "aggregation": "SUM",
            "components": validated["components"],
            "expected_total": expected_total,
            "total_proof_literal": validated["total_proof_literal"],
            "annualized": False,
            "fingerprint": fingerprint,
        }

        if validated["existing"]:
            row = validated["existing"][0]
            return {
                "schema": _RECONCILIATION_SCHEMA,
                "status": "ALREADY_RECONCILED",
                "idempotent_replay": True,
                "mutation_performed": False,
                "plan": plan,
                "observation_id": row.get("observation_id"),
                "evidence_id": row.get("evidence_id"),
                "commercial_value": self.evaluate_commercial_value({
                    "investigation_id": investigation_id
                }),
            }

        before = self.evaluate_commercial_value({
            "investigation_id": investigation_id
        })
        observation = {
            "claim_key": validated["target_claim_key"],
            "result": "POSITIVE",
            "owner_type": "ACCOUNT",
            "owner_id": validated["account_id"],
            "value": {
                metric: expected_total,
                "legacy_reconciliation": {
                    "schema": _RECONCILIATION_SCHEMA,
                    "fingerprint": fingerprint,
                    "legacy_evidence_id": validated["legacy_evidence_id"],
                    "legacy_content_sha256": evidence.get("content_sha256"),
                    "aggregation": "SUM",
                    "component_count": len(validated["components"]),
                    "annualized": False,
                },
            },
            "source": {
                "source_family": str(evidence.get("source_family") or "legacy_reconciliation"),
                "source_type": str(evidence.get("source_type") or "TRADE_DATA"),
                "reference_type": "PUBLIC_URL",
                "url": str(evidence.get("url") or ""),
                "locator": str(evidence.get("locator") or evidence.get("url") or ""),
                "content_sha256": str(evidence.get("content_sha256") or ""),
                "raw_excerpt": str(evidence.get("boundary") or "")[:2000],
                "authority_level": "C2_SECONDARY_PUBLIC",
                "freshness": _freshness(evidence.get("freshness")),
                "observed_at": str(evidence.get("observed_at") or ""),
            },
            "boundary": (
                f"Structured v6 projection of durable legacy Evidence "
                f"{validated['legacy_evidence_id']}. The Runtime revalidated exact "
                f"provenance and recomputed {metric}={expected_total} from explicit "
                "proof-bound components. This is an observed-value projection only: "
                "no annualization, growth, market share, purchasing authority, grade, "
                "or threshold is inferred."
            ),
            "search_cost": 0.0,
        }
        bundle_id = _v6._stable_id("BUNDLE-LEGACY-QUANT-RECON", plan, size=24)

        if bool(args.get("preview_only")):
            return {
                "schema": _RECONCILIATION_SCHEMA,
                "status": "PREVIEW_VALIDATED",
                "idempotent_replay": False,
                "mutation_performed": False,
                "bundle_id": bundle_id,
                "plan": plan,
                "planned_observation": observation,
                "commercial_value_before": before,
            }

        bundle = self.compile_and_append_research_bundle({
            "investigation_id": investigation_id,
            "bundle": {
                "bundle_id": bundle_id,
                "observations": [observation],
            },
        })
        if bundle.get("status") not in {"ACCEPTED", "PARTIAL_SUCCESS"}:
            raise _v6.ValidationError(
                "legacy quantitative reconciliation bundle was not accepted"
            )
        if int(bundle.get("accepted_count") or 0) != 1:
            raise _v6.ValidationError(
                "legacy quantitative reconciliation must accept exactly one observation"
            )
        after = self.evaluate_commercial_value({
            "investigation_id": investigation_id
        })
        return {
            "schema": _RECONCILIATION_SCHEMA,
            "status": "RECONCILED",
            "idempotent_replay": False,
            "mutation_performed": True,
            "bundle_id": bundle_id,
            "plan": plan,
            "bundle": bundle,
            "commercial_value_before": before,
            "commercial_value_after": after,
            "commercial_score_delta": round(
                float(after.get("score") or 0.0)
                - float(before.get("score") or 0.0),
                4,
            ),
        }

    def get_runtime_contract(self, arguments: dict[str, Any]) -> dict[str, Any]:
        contract = super().get_runtime_contract(arguments)
        contract["legacy_evidence_reconciliation_v6_1"] = {
            "schema": _RECONCILIATION_SCHEMA,
            "runtime_method": "reconcile_legacy_quantitative_evidence",
            "ordinary_mcp_tool_exposed": False,
            "administrative_direct_runtime_only": True,
            "target_claims": ["trade.import_activity"],
            "observed_numeric_metric_whitelist": list(
                OBSERVED_COMMERCIAL_NUMERIC_METRICS
            ),
            "automatic_text_extraction": False,
            "exact_legacy_provenance_required": True,
            "exact_boundary_hash_required": True,
            "positive_account_owned_attempt_required": True,
            "explicit_component_proof_literals_required": True,
            "runtime_recomputes_sum": True,
            "pre_reconciliation_tail_pin_required": True,
            "annualization_allowed": False,
            "growth_inference_allowed": False,
            "purchasing_authority_inference_allowed": False,
            "grade_or_threshold_mutation_allowed": False,
            "append_path": "compile_and_append_research_bundle",
            "preview_supported": True,
            "idempotent_fingerprint": True,
        }
        return contract
