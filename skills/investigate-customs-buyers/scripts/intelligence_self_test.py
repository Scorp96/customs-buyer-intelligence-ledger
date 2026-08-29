#!/usr/bin/env python3
"""Run deterministic, offline regression scenarios for buyer intelligence."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path
from typing import Any

from intelligence_pipeline import (
    REQUIRED_TOP_LEVEL_KEYS,
    CommercialScorer,
    IntelligencePipeline,
    ProductSemanticClassifier,
    load_rules,
    render_chinese_report,
)


SCRIPT_DIR = Path(__file__).resolve().parent
FIXTURE_PATH = SCRIPT_DIR / "fixtures" / "intelligence_cases.json"
PIPELINE_PATH = SCRIPT_DIR / "intelligence_pipeline.py"


def get_path(value: Any, path: str) -> Any:
    current = value
    for segment in path.split("."):
        if isinstance(current, dict) and segment in current:
            current = current[segment]
            continue
        raise AssertionError(f"Missing path {path!r}; stopped at {segment!r}")
    return current


def is_subset(expected: Any, observed: Any) -> bool:
    if isinstance(expected, dict):
        return isinstance(observed, dict) and all(
            key in observed and is_subset(item, observed[key])
            for key, item in expected.items()
        )
    if isinstance(expected, list):
        return isinstance(observed, list) and all(
            any(is_subset(item, candidate) for candidate in observed)
            for item in expected
        )
    return expected == observed


def assert_rule(result: dict[str, Any], assertion: dict[str, Any]) -> None:
    path = assertion["path"]
    operation = assertion["op"]
    expected = assertion.get("value")
    observed = get_path(result, path)
    message = (
        f"{path} {operation} failed: observed={observed!r}, "
        f"expected={expected!r}"
    )
    if operation == "eq":
        assert observed == expected, message
    elif operation == "nonempty":
        assert observed not in (None, "", [], {}), message
    elif operation == "length":
        assert len(observed) == expected, message
    elif operation == "contains":
        assert expected in observed, message
    elif operation == "approx":
        tolerance = float(assertion.get("tolerance", 1e-6))
        assert abs(float(observed) - float(expected)) <= tolerance, message
    elif operation == "list_item_subset":
        assert isinstance(observed, list), message
        assert any(is_subset(expected, item) for item in observed), message
    else:
        raise AssertionError(f"Unsupported assertion operation: {operation!r}")


def assert_output_contract(result: dict[str, Any], case_id: str) -> None:
    assert isinstance(result, dict) and result, f"{case_id}: blank output"
    missing = [key for key in REQUIRED_TOP_LEVEL_KEYS if key not in result]
    assert not missing, f"{case_id}: missing top-level keys {missing}"
    assert result["status"] in {
        "complete",
        "partial",
        "failed",
    }, f"{case_id}: invalid status {result['status']!r}"
    assert result["input_snapshot"]["immutable"] is True
    assert re.fullmatch(r"[0-9a-f]{64}", result["input_snapshot"]["sha256"])
    for key in (
        "contacts",
        "facts",
        "inferences",
        "unknowns",
        "recommended_actions",
        "evidence",
        "errors",
    ):
        assert isinstance(result[key], list), f"{case_id}: {key} is not a list"

    report = render_chinese_report(result)
    assert report.strip(), f"{case_id}: Chinese report is blank"
    assert "# 海关买家情报报告" in report
    assert "## 5. 事实、推断与未知" in report

    for claim in result["facts"] + result["inferences"]:
        for key in (
            "claim_id",
            "claim",
            "classification",
            "evidence_grade",
            "confidence",
            "source_ids",
            "date_checked",
            "reason_codes",
        ):
            assert key in claim, f"{case_id}: claim missing {key}: {claim}"
        assert claim["reason_codes"], f"{case_id}: claim lacks reason_codes"
        assert claim["source_ids"], f"{case_id}: claim lacks source_ids"

    unsafe_email_statuses = {"INFERRED_EMAIL", "UNVERIFIED_EMAIL"}
    for contact in result["contacts"]:
        if contact.get("email_status") in unsafe_email_statuses:
            assert contact.get("usable_for_outreach") is False, (
                f"{case_id}: inferred/unverified email promoted to outreach"
            )


def assert_pipeline_has_no_case_name_rules(fixtures: dict[str, Any]) -> None:
    source = PIPELINE_PATH.read_text(encoding="utf-8").casefold()
    leaked = [
        name
        for name in fixtures["metadata"]["forbidden_pipeline_name_literals"]
        if name.casefold() in source
    ]
    assert not leaked, (
        "Named acceptance cases leaked into intelligence_pipeline.py; "
        f"classification must be evidence-driven, found={leaked}"
    )


def run_product_matrix(
    classifier: ProductSemanticClassifier,
    fixtures: dict[str, Any],
) -> int:
    count = 0
    for item in fixtures["product_matrix"]:
        result = classifier.classify(
            {
                "product": item["description"],
                "product_description_local": None,
            },
            None,
        )
        assert result["match_level"] == item["expected_match"], (
            item["id"],
            result,
        )
        assert result["normalized_category"] == item["expected_category"], (
            item["id"],
            result,
        )
        assert result["reason_codes"], f"{item['id']}: no reason code"
        count += 1
    return count


def run_score_boundaries(
    scorer: CommercialScorer,
    fixtures: dict[str, Any],
) -> int:
    for item in fixtures["score_boundaries"]:
        observed = scorer.grade(int(item["score"]))
        assert observed == item["grade"], (item, observed)
    return len(fixtures["score_boundaries"])


def run_case(
    pipeline: IntelligencePipeline,
    case: dict[str, Any],
) -> dict[str, Any]:
    return pipeline.run(
        normalized=copy.deepcopy(case["normalized"]),
        raw_input=case["raw_input"],
        enrichment=copy.deepcopy(case.get("enrichment") or {}),
        related_records=copy.deepcopy(case.get("related_records") or []),
        mode=case.get("mode", "fast_scan"),
    )


def assert_name_invariance(
    pipeline: IntelligencePipeline,
    case: dict[str, Any],
    baseline: dict[str, Any],
) -> int:
    paths = case.get("name_invariance_paths") or []
    if not paths:
        return 0
    renamed = copy.deepcopy(case)
    renamed["normalized"]["record"]["buyer"] = "Renamed Synthetic Control Entity"
    renamed["raw_input"] = (
        case["raw_input"] + "\nFixture Alias\tRenamed Synthetic Control Entity"
    )
    changed = run_case(pipeline, renamed)
    for path in paths:
        expected = get_path(baseline, path)
        observed = get_path(changed, path)
        assert observed == expected, (
            f"{case['id']}: outcome at {path!r} changed when only the "
            f"buyer label changed: {expected!r} -> {observed!r}"
        )
    return len(paths)


def run() -> dict[str, Any]:
    fixtures = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    assert fixtures["metadata"]["network_allowed"] is False
    assert_pipeline_has_no_case_name_rules(fixtures)

    rules = load_rules()
    pipeline = IntelligencePipeline(rules)
    product_count = run_product_matrix(
        ProductSemanticClassifier(rules),
        fixtures,
    )
    boundary_count = run_score_boundaries(
        CommercialScorer(rules),
        fixtures,
    )

    cases_passed = 0
    assertion_count = 0
    invariance_count = 0
    statuses: dict[str, str] = {}
    for case in fixtures["cases"]:
        result = run_case(pipeline, case)
        assert_output_contract(result, case["id"])
        for assertion in case["assertions"]:
            assert_rule(result, assertion)
            assertion_count += 1
        invariance_count += assert_name_invariance(
            pipeline,
            case,
            result,
        )
        statuses[case["id"]] = result["status"]
        cases_passed += 1

    return {
        "status": "passed",
        "offline": True,
        "scenario_cases": cases_passed,
        "scenario_assertions": assertion_count,
        "name_invariance_assertions": invariance_count,
        "product_matrix_cases": product_count,
        "score_boundary_cases": boundary_count,
        "case_statuses": statuses,
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=True, indent=2))
