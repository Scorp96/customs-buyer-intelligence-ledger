#!/usr/bin/env python3
"""Run real-case v6 acceptance without committing production customer data.

A local, gitignored JSON manifest points at existing durable investigations and
defines read-only assertions. No Runtime mutation, CRM writeback, outreach
preparation, migration, account creation, or resume/initialization action is
permitted by this runner.

``cross_assertions`` allow a Golden manifest to prove relationships between
independent read-only case results without changing Runtime state. This is used
for requirements such as the Arecibo regression where three named businesses
must retain distinct Canonical Account identities rather than being silently
merged.
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

GRADE_RANK = {
    "NQ": 0, "D": 1, "C": 2, "B-": 3, "B": 4,
    "B+": 5, "A-": 6, "A": 7, "A+": 8,
}

CROSS_ASSERTION_OPS = {"all_distinct", "all_equal", "eq", "ne"}


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


def assert_rule(response: dict[str, Any], assertion: dict[str, Any]) -> dict[str, Any]:
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
            raise ValueError(f"cases[{index}].case_id must be unique and non-empty")
        seen.add(case_id)
        tool = str(case.get("tool") or "get_account_state").strip()
        if tool not in READ_ONLY_TOOLS:
            raise ValueError(f"{case_id}: tool {tool!r} is not allowed by read-only Golden runner")
        arguments = case.get("arguments")
        assertions = case.get("assertions")
        if not isinstance(arguments, dict):
            raise ValueError(f"{case_id}: arguments must be an object")
        if not isinstance(assertions, list) or not assertions:
            raise ValueError(f"{case_id}: assertions must be a non-empty array")
        normalized.append({
            "case_id": case_id,
            "tool": tool,
            "arguments": arguments,
            "assertions": assertions,
        })
    return normalized


def validate_cross_assertions(
    manifest: dict[str, Any],
    case_ids: set[str],
) -> list[dict[str, Any]]:
    raw = manifest.get("cross_assertions", [])
    if raw is None:
        raw = []
    if not isinstance(raw, list):
        raise ValueError("manifest.cross_assertions must be an array when provided")
    normalized: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, assertion in enumerate(raw):
        if not isinstance(assertion, dict):
            raise ValueError(f"cross_assertions[{index}] must be an object")
        assertion_id = str(assertion.get("assertion_id") or "").strip()
        if not assertion_id or assertion_id in seen:
            raise ValueError(
                f"cross_assertions[{index}].assertion_id must be unique and non-empty"
            )
        seen.add(assertion_id)
        op = str(assertion.get("op") or "").strip().lower()
        if op not in CROSS_ASSERTION_OPS:
            raise ValueError(f"{assertion_id}: unsupported cross assertion op {op!r}")
        refs = assertion.get("refs")
        if not isinstance(refs, list) or len(refs) < 2 or len(refs) > 50:
            raise ValueError(f"{assertion_id}: refs must contain between 2 and 50 references")
        if op in {"eq", "ne"} and len(refs) != 2:
            raise ValueError(f"{assertion_id}: {op} requires exactly two references")
        normalized_refs: list[dict[str, str]] = []
        for ref_index, ref in enumerate(refs):
            if not isinstance(ref, dict):
                raise ValueError(f"{assertion_id}: refs[{ref_index}] must be an object")
            case_id = str(ref.get("case_id") or "").strip()
            path = str(ref.get("path") or "").strip()
            if case_id not in case_ids:
                raise ValueError(f"{assertion_id}: unknown case_id {case_id!r}")
            if not path:
                raise ValueError(f"{assertion_id}: refs[{ref_index}].path must be non-empty")
            normalized_refs.append({"case_id": case_id, "path": path})
        normalized.append({
            "assertion_id": assertion_id,
            "op": op,
            "refs": normalized_refs,
        })
    return normalized


def assert_cross_rule(
    responses: dict[str, dict[str, Any]],
    assertion: dict[str, Any],
) -> dict[str, Any]:
    observed: list[Any] = []
    for ref in assertion["refs"]:
        case_id = ref["case_id"]
        if case_id not in responses:
            raise KeyError(f"case {case_id!r} has no successful read-only response")
        observed.append(get_path(responses[case_id], ref["path"]))
    op = assertion["op"]
    if op == "all_distinct":
        try:
            passed = len(set(observed)) == len(observed)
        except TypeError:
            passed = len({json.dumps(row, sort_keys=True, default=str) for row in observed}) == len(observed)
    elif op == "all_equal":
        passed = all(row == observed[0] for row in observed[1:])
    elif op == "eq":
        passed = observed[0] == observed[1]
    elif op == "ne":
        passed = observed[0] != observed[1]
    else:  # validation prevents this path
        raise ValueError(f"unsupported cross assertion op: {op}")
    return {
        "assertion_id": assertion["assertion_id"],
        "op": op,
        "refs": assertion["refs"],
        "observed": observed,
        "passed": passed,
    }


def run_manifest(runtime: UnifiedRuntime, manifest: dict[str, Any]) -> dict[str, Any]:
    cases = validate_manifest(manifest)
    cross_assertions = validate_cross_assertions(
        manifest,
        {case["case_id"] for case in cases},
    )
    results: list[dict[str, Any]] = []
    responses: dict[str, dict[str, Any]] = {}
    for case in cases:
        try:
            response = getattr(runtime, case["tool"])(case["arguments"])
            responses[case["case_id"]] = response
            assertions = [assert_rule(response, row) for row in case["assertions"]]
            results.append({
                "case_id": case["case_id"],
                "tool": case["tool"],
                "passed": all(row["passed"] for row in assertions),
                "assertions": assertions,
            })
        except Exception as exc:
            results.append({
                "case_id": case["case_id"],
                "tool": case["tool"],
                "passed": False,
                "error": f"{type(exc).__name__}: {exc}",
                "assertions": [],
            })

    cross_results: list[dict[str, Any]] = []
    for assertion in cross_assertions:
        try:
            cross_results.append(assert_cross_rule(responses, assertion))
        except Exception as exc:
            cross_results.append({
                "assertion_id": assertion["assertion_id"],
                "op": assertion["op"],
                "refs": assertion["refs"],
                "passed": False,
                "error": f"{type(exc).__name__}: {exc}",
            })

    passed_count = sum(row["passed"] for row in results)
    cross_passed_count = sum(row["passed"] for row in cross_results)
    passed = (
        passed_count == len(results)
        and cross_passed_count == len(cross_results)
    )
    return {
        "schema": "cbi.private-golden-acceptance.v6.1",
        "read_only": True,
        "case_count": len(results),
        "passed_count": passed_count,
        "failed_count": len(results) - passed_count,
        "cross_assertion_count": len(cross_results),
        "cross_passed_count": cross_passed_count,
        "cross_failed_count": len(cross_results) - cross_passed_count,
        "passed": passed,
        "results": results,
        "cross_assertions": cross_results,
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run read-only v6 Golden acceptance.")
    parser.add_argument("--session-root", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(sys.argv[1:] if argv is None else argv))
    manifest = json.loads(Path(args.manifest).expanduser().resolve().read_text(encoding="utf-8-sig"))
    runtime = UnifiedRuntime(Path(args.session_root).expanduser().resolve())
    result = run_manifest(runtime, manifest)
    rendered = json.dumps(result, ensure_ascii=False, indent=2, default=str)
    if args.output:
        Path(args.output).expanduser().resolve().write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
