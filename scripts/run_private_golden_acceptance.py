#!/usr/bin/env python3
"""Run real-case v6 acceptance without committing production customer data.

A local, gitignored JSON manifest points at existing durable investigations and
defines read-only assertions. Cases may either provide an explicit
``arguments.investigation_id`` or a fail-closed selector resolved against the
public PRODUCTION + ACTIVE portfolio view. No Runtime mutation, CRM writeback,
outreach preparation, migration, account creation, or resume/initialization
action is permitted by this runner.

When ``--session-root`` is omitted, the runner constructs ``UnifiedRuntime()``
exactly as the production MCP entry does. This preserves the production default
session/canonical/pending root derivation instead of accidentally changing
sidecar roots merely for acceptance execution. An explicit session root remains
available for isolated fixtures and intentionally custom layouts.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from unified_runtime import UnifiedRuntime
from unified_runtime.resilience import normalize_scalar


READ_ONLY_TOOLS = {
    "get_runtime_contract",
    "get_investigation_health",
    "get_claims",
    "get_account_state",
    "get_investigation_state",
    "get_next_research_objectives",
    "get_portfolio_queue",
    "get_information_history",
    "get_material_pivots",
    "evaluate_commercial_value",
    "evaluate_research_confidence",
    "evaluate_outreach_readiness",
    "evaluate_decision_saturation",
}

GLOBAL_READ_ONLY_TOOLS = {
    "get_runtime_contract",
    "get_portfolio_queue",
}
INVESTIGATION_SCOPED_TOOLS = READ_ONLY_TOOLS - GLOBAL_READ_ONLY_TOOLS
SELECTOR_FIELDS = {"account_name", "account_id", "investigation_scope"}
PORTFOLIO_SELECTOR_LIMIT = 1000

GRADE_RANK = {
    "NQ": 0,
    "D": 1,
    "C": 2,
    "B-": 3,
    "B": 4,
    "B+": 5,
    "A-": 6,
    "A": 7,
    "A+": 8,
}


def get_path(value: Any, path: str) -> Any:
    current = value
    for segment in path.split(".") if path else []:
        if isinstance(current, dict):
            if segment not in current:
                raise KeyError(f"missing path segment {segment!r} in {path!r}")
            current = current[segment]
        elif isinstance(current, list) and segment.isdigit():
            index = int(segment)
            if not 0 <= index < len(current):
                raise KeyError(f"list index {index} out of range in {path!r}")
            current = current[index]
        else:
            raise KeyError(f"cannot traverse {segment!r} in {path!r}")
    return current


def _contains(observed: Any, expected: Any) -> bool:
    if isinstance(observed, dict):
        return expected in observed or expected in observed.values()
    if isinstance(observed, (list, tuple, set, str)):
        return expected in observed
    return False


def _is_subset(expected: Any, observed: Any) -> bool:
    """Return True when ``expected`` is recursively contained in ``observed``.

    This is intentionally value-only and read-only. It lets Private Golden
    manifests assert semantic facts in unordered public Runtime arrays (for
    example a named Peer with ``stage=ANCHOR_ELIGIBLE``) without depending on
    brittle list indexes or exposing private Investigation identifiers.
    """
    if isinstance(expected, dict):
        return isinstance(observed, dict) and all(
            key in observed and _is_subset(value, observed[key])
            for key, value in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(observed, list) and all(
            any(_is_subset(item, candidate) for candidate in observed)
            for item in expected
        )
    return expected == observed


def assert_rule(
    response: dict[str, Any], assertion: dict[str, Any]
) -> dict[str, Any]:
    path = str(assertion.get("path") or "")
    op = str(assertion.get("op") or "eq").lower()
    expected = assertion.get("value")
    observed = get_path(response, path)
    if op == "eq":
        passed = observed == expected
    elif op == "ne":
        passed = observed != expected
    elif op == "truthy":
        passed = bool(observed)
    elif op == "falsy":
        passed = not bool(observed)
    elif op == "contains":
        passed = _contains(observed, expected)
    elif op == "not_contains":
        passed = not _contains(observed, expected)
    elif op == "in":
        passed = isinstance(expected, (list, tuple, set)) and observed in expected
    elif op == "not_in":
        passed = isinstance(expected, (list, tuple, set)) and observed not in expected
    elif op == "list_item_subset":
        passed = isinstance(observed, list) and any(
            _is_subset(expected, candidate) for candidate in observed
        )
    elif op == "no_list_item_subset":
        passed = isinstance(observed, list) and not any(
            _is_subset(expected, candidate) for candidate in observed
        )
    elif op == "grade_at_least":
        passed = (
            str(observed) in GRADE_RANK
            and str(expected) in GRADE_RANK
            and GRADE_RANK[str(observed)] >= GRADE_RANK[str(expected)]
        )
    elif op == "number_at_least":
        try:
            passed = math.isfinite(float(observed)) and float(observed) >= float(expected)
        except (TypeError, ValueError):
            passed = False
    elif op == "length_at_least":
        try:
            passed = len(observed) >= int(expected)
        except (TypeError, ValueError):
            passed = False
    else:
        raise ValueError(f"unsupported assertion op: {op}")
    return {
        "path": path,
        "op": op,
        "expected": expected,
        "observed": observed,
        "passed": passed,
    }


def _validate_selector(raw: Any, case_id: str) -> dict[str, str]:
    if not isinstance(raw, dict):
        raise ValueError(f"{case_id}: selector must be an object")
    unknown = set(raw) - SELECTOR_FIELDS
    if unknown:
        raise ValueError(
            f"{case_id}: selector contains unsupported fields: {sorted(unknown)}"
        )
    account_name = str(raw.get("account_name") or "").strip()
    account_id = str(raw.get("account_id") or "").strip()
    investigation_scope = str(raw.get("investigation_scope") or "").strip()
    if not account_name and not account_id:
        raise ValueError(
            f"{case_id}: selector requires account_name or account_id"
        )
    return {
        "account_name": account_name,
        "account_id": account_id,
        "investigation_scope": investigation_scope,
    }


def validate_manifest(manifest: Any) -> list[dict[str, Any]]:
    if not isinstance(manifest, dict):
        raise ValueError("manifest root must be an object")
    cases = manifest.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("manifest.cases must be a non-empty array")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, case in enumerate(cases):
        if not isinstance(case, dict):
            raise ValueError(f"cases[{index}] must be an object")
        case_id = str(case.get("case_id") or "").strip()
        if not case_id or case_id in seen:
            raise ValueError(
                f"cases[{index}].case_id must be unique and non-empty"
            )
        seen.add(case_id)
        tool = str(case.get("tool") or "get_account_state").strip()
        if tool not in READ_ONLY_TOOLS:
            raise ValueError(
                f"{case_id}: tool {tool!r} is not allowed by read-only Golden runner"
            )
        arguments = case.get("arguments", {})
        assertions = case.get("assertions")
        if not isinstance(arguments, dict):
            raise ValueError(f"{case_id}: arguments must be an object")
        if not isinstance(assertions, list) or not assertions:
            raise ValueError(
                f"{case_id}: assertions must be a non-empty array"
            )
        selector_raw = case.get("selector")
        selector: dict[str, str] | None = None
        if selector_raw is not None:
            if tool not in INVESTIGATION_SCOPED_TOOLS:
                raise ValueError(
                    f"{case_id}: selector is only valid for Investigation-scoped read-only tools"
                )
            if "investigation_id" in arguments:
                raise ValueError(
                    f"{case_id}: selector and arguments.investigation_id cannot be combined"
                )
            selector = _validate_selector(selector_raw, case_id)
        normalized.append(
            {
                "case_id": case_id,
                "tool": tool,
                "arguments": dict(arguments),
                "selector": selector,
                "assertions": assertions,
            }
        )
    return normalized


def _load_active_production_portfolio(runtime: UnifiedRuntime) -> list[dict[str, Any]]:
    portfolio = runtime.get_portfolio_queue({"limit": PORTFOLIO_SELECTOR_LIMIT})
    queue = portfolio.get("queue")
    if not isinstance(queue, list):
        raise ValueError("portfolio selector: Runtime returned no queue array")
    try:
        active_count = int(portfolio.get("active_count", len(queue)))
    except (TypeError, ValueError) as exc:
        raise ValueError("portfolio selector: active_count is invalid") from exc
    if active_count > PORTFOLIO_SELECTOR_LIMIT:
        raise ValueError(
            "portfolio selector: ACTIVE portfolio exceeds 1000-row public API limit; "
            "use an explicit investigation_id rather than accepting a truncated match"
        )
    for index, row in enumerate(queue):
        if not isinstance(row, dict):
            raise ValueError(f"portfolio selector: queue[{index}] is not an object")
        if row.get("environment") != "PRODUCTION" or row.get("lifecycle") != "ACTIVE":
            raise ValueError(
                "portfolio selector: default Runtime view exposed a non-production or non-active row"
            )
    return queue


def _resolve_selector(
    portfolio_rows: list[dict[str, Any]], selector: dict[str, str]
) -> dict[str, Any]:
    wanted_name = normalize_scalar(selector.get("account_name"))
    wanted_id = str(selector.get("account_id") or "").strip().casefold()
    wanted_scope = str(selector.get("investigation_scope") or "").strip().casefold()
    matches: list[dict[str, Any]] = []
    for row in portfolio_rows:
        if wanted_name and normalize_scalar(row.get("account_name")) != wanted_name:
            continue
        if wanted_id and str(row.get("account_id") or "").strip().casefold() != wanted_id:
            continue
        if (
            wanted_scope
            and str(row.get("investigation_scope") or "").strip().casefold()
            != wanted_scope
        ):
            continue
        matches.append(row)
    if not matches:
        raise ValueError(
            "selector matched no unique PRODUCTION/ACTIVE Investigation"
        )
    if len(matches) != 1:
        investigation_ids = sorted(
            str(row.get("investigation_id") or "") for row in matches
        )
        raise ValueError(
            "selector matched multiple PRODUCTION/ACTIVE Investigations: "
            + ", ".join(investigation_ids)
        )
    row = matches[0]
    investigation_id = str(row.get("investigation_id") or "").strip()
    if not investigation_id:
        raise ValueError("selector matched a row without investigation_id")
    return {
        "investigation_id": investigation_id,
        "account_id": row.get("account_id"),
        "account_name": row.get("account_name"),
        "investigation_scope": row.get("investigation_scope"),
        "environment": row.get("environment"),
        "lifecycle": row.get("lifecycle"),
    }


def run_manifest(runtime: UnifiedRuntime, manifest: dict[str, Any]) -> dict[str, Any]:
    cases = validate_manifest(manifest)
    results: list[dict[str, Any]] = []
    portfolio_rows: list[dict[str, Any]] | None = None
    portfolio_error: Exception | None = None
    for case in cases:
        try:
            arguments = dict(case["arguments"])
            selection = None
            if case["selector"] is not None:
                if portfolio_rows is None and portfolio_error is None:
                    try:
                        portfolio_rows = _load_active_production_portfolio(runtime)
                    except Exception as exc:
                        portfolio_error = exc
                if portfolio_error is not None:
                    raise portfolio_error
                selection = _resolve_selector(
                    portfolio_rows or [], case["selector"]
                )
                arguments["investigation_id"] = selection["investigation_id"]
            response = getattr(runtime, case["tool"])(arguments)
            assertions = [
                assert_rule(response, row) for row in case["assertions"]
            ]
            results.append(
                {
                    "case_id": case["case_id"],
                    "tool": case["tool"],
                    "selection": selection,
                    "passed": all(row["passed"] for row in assertions),
                    "assertions": assertions,
                }
            )
        except Exception as exc:
            results.append(
                {
                    "case_id": case["case_id"],
                    "tool": case["tool"],
                    "selection": None,
                    "passed": False,
                    "error": f"{type(exc).__name__}: {exc}",
                    "assertions": [],
                }
            )
    passed_count = sum(row["passed"] for row in results)
    return {
        "schema": "cbi.private-golden-acceptance.v6.1",
        "read_only": True,
        "selector_policy": {
            "source": "PUBLIC_PRODUCTION_ACTIVE_PORTFOLIO_VIEW",
            "maximum_auto_resolution_rows": PORTFOLIO_SELECTOR_LIMIT,
            "zero_match": "FAIL_CLOSED",
            "multiple_matches": "FAIL_CLOSED",
            "truncated_active_portfolio": "FAIL_CLOSED_REQUIRE_EXPLICIT_INVESTIGATION_ID",
        },
        "case_count": len(results),
        "passed_count": passed_count,
        "failed_count": len(results) - passed_count,
        "passed": passed_count == len(results),
        "results": results,
    }


def build_runtime(session_root: str = "") -> UnifiedRuntime:
    """Construct the exact production-default Runtime unless a root is explicit."""
    cleaned = str(session_root or "").strip()
    if not cleaned:
        return UnifiedRuntime()
    return UnifiedRuntime(Path(cleaned).expanduser().resolve())


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run read-only v6 Golden acceptance."
    )
    parser.add_argument(
        "--session-root",
        default="",
        help=(
            "Optional explicit session root. Omit for the exact production-default "
            "UnifiedRuntime() root semantics."
        ),
    )
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    manifest = json.loads(
        Path(args.manifest)
        .expanduser()
        .resolve()
        .read_text(encoding="utf-8-sig")
    )
    runtime = build_runtime(args.session_root)
    result = run_manifest(runtime, manifest)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if args.output:
        output = Path(args.output).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
