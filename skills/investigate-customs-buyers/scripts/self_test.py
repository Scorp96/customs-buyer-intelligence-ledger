#!/usr/bin/env python3
"""Run deterministic regression checks for customs parsing and QUICK planning."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from aggregate_shipments import product_matches, summarize
from build_research_plan import build_plan, government_domain, product_phrase
from normalize_customs_record import (
    add_reconciliation,
    extract_hs,
    extract_hs_candidates,
    extract_pvc_sheet_inference,
    first_number,
    normalize,
    parse_date_info,
    parse_text,
    read_text_safely,
)


PHILIPPINES_SAMPLE = """\
**基本信息**
数据源\t菲律宾(进口)
日期\t2026-06-17
主单号\tSYNPHMASTER0001
供应商\tShandong Synthetic Polymer Co., Ltd.
采购商\tMetro Synthetic Concepts Corp
采购商地址\tMetro Synthetic Concepts Corp., 100 Synthetic Avenue, Davao City 8000, Philippines
**产品信息**
重量（kg）\t394.00
产品\tPvc Foam Board 1220x2440 17mm .65g
**货运信息**
原产地\tChina Mainland
目的地\tPhilippines
目的港\tPort Of Davao
船名\tMv Synthetic Star 0001S
**其它信息**
M A N I F E S T\tSYN0035-26
I T E M_ N O\t6
T Y P E P K G S\tBG
M O D E L D E C L A R A T I O N\t4
I N S U R A N C E\t5.75
N O P A C K A G E S\t6
T O T A L A S S E S S M E N T\t0
L O C G O O D S\tS31
B R O K E R\tSYNTHETIC BROKER ONE
P R O C E D U R E C O D E\t4000
D U T Y R A T E\t0
V A T_ P A I D\t2479.31
D U T I A B L E_ F O R E I G N\t311.01
P R E F_ C O D E\tACFTA
F O B\t305.26
C O L L E C T I O N D A T E\t2026-06-18 00:00:00
P O R T O F E N T R Y\tPort of Davao
E S E R I A L\tC
G R O S S M A S S K G S\t395.92
C O U N T R Y O R I G I N\tCN
A S E S S M E N T D A T E\t2026-06-18 00:00:00
C U R R E N C Y\tUSD
D U T I A B L E V A L U E P H P\t19126.19
P O R T\tP12
C U S T O M S V A L U E\t287.54
O T H E R T A X E S\t0
E X C H A N G E_ R A T E\t61.497
T O T A L F E E S\t0
D U T Y_ P A I D\t0
C O U N T R Y E X P O R T\tCHINA
V A T T A X B A S E\t20660.89
P O R T_1\tP12
E X C I S E A D V A L O R E M\t0
F R E I G H T\t17.72
N A T I O N A L C O D E\t000
N O O F C O N T A I N E R\t0
E Y E A R\t2026
D E S T I N A T I O N\tP12
B R O K E R A D D\tDavao City
T Y P E D E C L A R A T I O N\t4
E S E R I A L_1\tC
Y E L L O W\t1
E N T R Y N O\t20811
F I N E P E N A L T I E S\t0
C O U N T R Y O R I G I N_1\tCN
D U T I E S T A X E S\t2479.31
B R O K E R T I N\t999999999999
"""

VIETNAM_SAMPLE = """\
**基本信息**
日期\t2026-05-28
供应商\tZhejiang Synthetic Materials Export Co Ltd
采购商\tViet Synthetic Travel Trade Company Limited
**产品信息**
数量\t1763 Pieces
产品\tPVC Foam Board
**其它信息**
O R I G I N A L_ U N I T_ P R I C E\t14.50
O R I G I N A L_ A M O U N T\t25,563.50
V N D_ E X C H A N G E_ R A T E\t25,900.00
I M P O R T E R_ R E G I S T E R_ N A M E_ V N\tCÔNG TY TNHH
"""


def assert_close(observed: float, expected: float, tolerance: float = 0.01) -> None:
    assert abs(observed - expected) <= tolerance, (observed, expected)


def run() -> dict[str, object]:
    assert first_number(".65") == 0.65
    assert first_number("-.65") == -0.65
    assert first_number("+.65") == 0.65
    assert extract_hs("H.S. CODE: 3921.12.90") == "39211290"
    assert extract_hs("HS CODE 3921 12 90") == "39211290"
    assert extract_hs("HS: 3921129000") == "3921129000"
    assert extract_hs("invoice 3921129000") is None
    assert extract_hs_candidates("392190 / 392112") == ["392190", "392112"]
    assert parse_date_info("2026-06-18T00:00:00Z")["normalized"] == "2026-06-18"
    assert parse_date_info("2026-99-99")["valid"] is False
    assert parse_date_info("01/02/2026")["ambiguous"] is True

    ph_raw = parse_text(PHILIPPINES_SAMPLE)
    ph = normalize(ph_raw, input_encoding="utf-8")
    record = ph["record"]
    assert ph["parse_quality"]["strict_pass"] is True
    assert ph["parse_quality"]["shipment_ready"] is True
    assert ph["parse_quality"]["recognized_coverage"] >= 0.98
    assert record["buyer"] == "Metro Synthetic Concepts Corp"
    assert record["quantity_count"] is None
    assert record["quantity_source"] is None
    assert record["package_count"] == 6
    assert record["package_type"] == "BG"
    assert record["package_count_is_product_quantity"] is False
    assert record["quantity_scope"] == "not_declared"
    assert record["package_scope"] == "shipment_or_packaging_level"
    assert_close(record["weight_kg"], 394.0)
    assert_close(record["gross_weight_kg"], 395.92)
    assert record["currency"] == "USD"
    assert record["preference_code"] == "ACFTA"
    assert record["yellow_lane_flag"] == "1"
    assert record["procedure_code"] == "4000"
    assert record["total_assessment"] == 0
    assert record["national_code"] == "000"
    assert record["entry_serial_secondary"] == "C"
    assert record["port_code_secondary"] == "P12"
    assert record["country_origin_code_secondary"] == "CN"
    assert record["dates"]["assessment_date"] == "2026-06-18"
    assert record["dates"]["collection_date"] == "2026-06-18"
    assert ph["unmapped_fields"] == {}
    assert all(item["status"] == "matched" for item in ph["reconciliations"])
    assert len(ph["reconciliations"]) == 5
    tolerance_check: list[dict[str, object]] = []
    add_reconciliation(
        tolerance_check,
        "cent_precision",
        19126.22,
        19126.19,
        "regression tolerance check",
    )
    assert tolerance_check[0]["status"] == "mismatch"
    assert_close(ph["derived_metrics"]["packaging_or_tare_kg"], 1.92)
    assert_close(ph["derived_metrics"]["inferred_vat_rate_percent"], 12.0)
    assert ph["pvc_sheet_inference"]["nearest_full_sheet_count"] == 12
    assert ph["pvc_sheet_inference"]["inferred_sheets_per_package"] == 2
    assert ph["pvc_sheet_inference"]["density_source"] == "ambiguous_shorthand"
    assert ph["pvc_sheet_inference"]["verification_required"] is True

    mismatched_raw = dict(ph_raw)
    mismatched_raw["dutiable_value_local"] = "19126.23"
    mismatched = normalize(mismatched_raw, input_encoding="utf-8")
    foreign_check = next(
        item
        for item in mismatched["reconciliations"]
        if item["check"] == "foreign_value_times_exchange_rate"
    )
    assert foreign_check["status"] == "mismatch"
    assert "financial_reconciliation_mismatch" in {
        item["code"] for item in mismatched["anomalies"]
    }

    physical_raw = dict(ph_raw)
    physical_raw["gross_weight_kg"] = "393"
    physical_raw["containers"] = "TCNU8403029"
    physical_raw["declared_container_count"] = "2"
    physical_raw["port_code_secondary"] = "P13"
    physical_raw["country_origin_code_secondary"] = "US"
    physical_raw["entry_serial_secondary"] = "D"
    physical = normalize(physical_raw, input_encoding="utf-8")
    physical_codes = {item["code"] for item in physical["anomalies"]}
    assert "gross_weight_below_net_weight" in physical_codes
    assert "declared_container_count_conflict" in physical_codes
    assert "primary_secondary_port_conflict" in physical_codes
    assert "primary_secondary_origin_conflict" in physical_codes
    assert "primary_secondary_serial_conflict" in physical_codes

    vn_raw = parse_text(VIETNAM_SAMPLE)
    vn_raw["vat_base"] = "100"
    vn_raw["vat_paid"] = "10"
    vn = normalize(vn_raw, input_encoding="utf-8")
    assert vn["parse_quality"]["strict_pass"] is True
    assert vn["record"]["quantity_count"] == 1763
    assert_close(vn["record"]["unit_price"], 14.5)
    assert_close(vn["record"]["original_amount"], 25563.5)
    assert_close(vn["record"]["vnd_exchange_rate"], 25900.0)
    assert "displayed_unit_price_times_quantity" in {
        item["check"] for item in vn["reconciliations"]
    }
    assert "vat_base_times_inferred_12_percent" not in {
        item["check"] for item in vn["reconciliations"]
    }

    invalid_raw = parse_text(
        "采购商\tN/A\n产品\tN/A\n日期\t2026-99-99\n主单号\tABC123"
    )
    invalid = normalize(invalid_raw, input_encoding="utf-8")
    assert invalid["parse_quality"]["research_ready"] is False
    assert invalid["parse_quality"]["shipment_ready"] is False
    assert "invalid_date" in {item["code"] for item in invalid["anomalies"]}

    explicit_spec = extract_pvc_sheet_inference(
        "PVC foam board 1220mm x 2440mm x 17mm 650 kg/m3", 394, 6
    )
    assert explicit_spec is not None
    assert explicit_spec["density_source"] == "explicit_kg_m3"
    assert explicit_spec["nearest_full_sheet_count"] == 12
    implausible_spec = extract_pvc_sheet_inference(
        "PVC foam board 1220mm x 2440mm x 170mm 6.5 g/cm3", 394, 6
    )
    assert implausible_spec is not None
    assert implausible_spec["plausible_for_sheet_count"] is False
    assert "implausible_density" in implausible_spec["plausibility_warnings"]
    assert "implausible_thickness" in implausible_spec["plausibility_warnings"]

    policy_path = (
        Path(__file__).resolve().parent.parent
        / "references"
        / "runtime-policy.json"
    )
    policy = json.loads(policy_path.read_text(encoding="utf-8"))
    plan = build_plan(ph, policy, "quick")
    assert plan["policy"]["fixed_seconds_are_completion"] is False
    assert plan["policy"]["fixed_query_count_is_completion"] is False
    assert plan["policy"]["fixed_page_count_is_completion"] is False
    assert plan["policy"]["first_positive_is_completion"] is False
    assert plan["policy"]["max_online_concurrency"] == 2
    assert plan["circuit_breaker"]["global_consecutive_transport_failures"] == 2
    assert plan["circuit_breaker"]["global_total_transport_failures"] == 3
    assert all(len(batch) <= 4 for batch in plan["web_search_batches"])
    assert plan["open_page_policy"]["maximum_total_as_completion"] is None
    assert "Only the unified Runtime" in plan["completion_rule"]
    canonical = [row["canonical_query"] for row in plan["query_ledger"]]
    assert len(canonical) == len(set(canonical))
    assert government_domain("United States Carolina PR Puerto Rico") == "pr.gov"
    assert product_phrase("PVC foam board 1220x2440") == "PVC foam board"
    assert product_phrase("Structural PVC foam core 80 kg/m3") != "PVC foam board"
    assert product_phrase("PVC square tube with foam packing") != "PVC foam board"
    assert product_matches("PVC foam board 17 mm", "PVC foam board") is True
    assert product_matches("PVC cosmetic display stand", "PVC foam board") is False
    assert product_matches("Structural PVC foam core", "PVC foam board") is False

    aggregate = summarize(
        [
            {
                "buyer": "Harborline Ventures",
                "product": "PVC foam board",
                "quantity": 10,
                "quantity_unit": "PCE",
                "master_bill": "M1",
                "house_bill": "H1",
                "item_number": "1",
            },
            {
                "buyer": "Harborline Ventures Meridian Global",
                "product": "PVC foam board",
                "quantity": 20,
                "quantity_unit": "PCE",
                "master_bill": "M2",
                "house_bill": "H2",
                "item_number": "1",
            },
            {
                "buyer": "Harborline Ventures",
                "product": "PVC foam board",
                "quantity": 2,
                "quantity_unit": "PKG",
                "master_bill": "M3",
                "house_bill": "H3",
                "item_number": "1",
            },
        ],
        "Harborline Ventures",
        "PVC foam board",
        None,
    )
    assert aggregate["observed_unique_shipments"] == 2
    assert aggregate["mixed_quantity_units"] is True
    assert aggregate["total_observed_quantity"] is None
    assert aggregate["observed_quantity_totals_by_unit"] == {
        "PCE": 10.0,
        "PKG": 2.0,
    }

    with tempfile.TemporaryDirectory() as directory:
        temp_root = Path(directory)
        for encoding in ("utf-8-sig", "utf-16", "gb18030"):
            encoded_input = temp_root / f"sample-{encoding}.txt"
            encoded_input.write_bytes(PHILIPPINES_SAMPLE.encode(encoding))
            decoded, detected = read_text_safely(encoded_input)
            decoded_result = normalize(
                parse_text(decoded), input_encoding=detected
            )
            assert decoded_result["record"]["buyer"] == record["buyer"]
            assert decoded_result["record"]["product"] == record["product"]
            assert decoded_result["record"]["data_source"] == "菲律宾(进口)"
            assert decoded_result["unmapped_fields"] == {}

        output = temp_root / "result.json"
        output.write_text(
            json.dumps(ph, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        assert json.loads(output.read_text(encoding="utf-8"))["record"]["buyer"] == record["buyer"]

    return {
        "status": "passed",
        "philippines_parse_coverage": ph["parse_quality"][
            "recognized_coverage"
        ],
        "philippines_reconciliations": len(ph["reconciliations"]),
        "inferred_sheet_count": ph["pvc_sheet_inference"][
            "nearest_full_sheet_count"
        ],
        "quick_queries": len(plan["query_ledger"]),
        "completion_basis": plan["policy"]["completion_basis"],
    }


if __name__ == "__main__":
    print(json.dumps(run(), ensure_ascii=True, indent=2))
