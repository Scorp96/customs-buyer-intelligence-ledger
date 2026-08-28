#!/usr/bin/env python3
"""Fault-tolerant batch runner for customs-buyer-intelligence v4.2."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from analyze_customs_buyer import emergency_result
from intelligence_pipeline import IntelligencePipeline, load_rules
from normalize_customs_record import flatten_json, normalize, parse_text, read_text_safely
from v3_engine import V3Assembler, render_crm_csv_row, render_v3_report, stable_hash


def read_xlsx(path: Path) -> list[dict[str, Any]]:
    """Read the first XLSX worksheet using only the standard library."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main", "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    with zipfile.ZipFile(path) as archive:
        shared: list[str] = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            for item in root.findall("m:si", ns):
                shared.append("".join(node.text or "" for node in item.iterfind(".//m:t", ns)))
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
        rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
        relationships = {node.attrib["Id"]: node.attrib["Target"] for node in rels}
        sheet = workbook.find("m:sheets/m:sheet", ns)
        if sheet is None:
            return []
        target = relationships[sheet.attrib[f"{{{ns['r']}}}id"]].replace("\\", "/")
        sheet_path = target.lstrip("/") if target.startswith("/xl/") else f"xl/{target.lstrip('/')}"
        root = ET.fromstring(archive.read(sheet_path))
        matrix: list[list[Any]] = []
        for row in root.findall(".//m:sheetData/m:row", ns):
            values: dict[int, Any] = {}
            for cell in row.findall("m:c", ns):
                reference = cell.attrib.get("r", "A1")
                letters = re.match(r"[A-Z]+", reference)
                index = 0
                for char in (letters.group(0) if letters else "A"):
                    index = index * 26 + ord(char) - 64
                node = cell.find("m:v", ns)
                raw = node.text if node is not None else ""
                if cell.attrib.get("t") == "s" and raw:
                    raw = shared[int(raw)]
                elif cell.attrib.get("t") == "inlineStr":
                    raw = "".join(item.text or "" for item in cell.iterfind(".//m:t", ns))
                values[index - 1] = raw
            width = max(values, default=-1) + 1
            matrix.append([values.get(i, "") for i in range(width)])
    if not matrix:
        return []
    headers = [str(item).strip() or f"column_{index + 1}" for index, item in enumerate(matrix[0])]
    return [{headers[index]: row[index] if index < len(row) else "" for index in range(len(headers))} for row in matrix[1:] if any(str(item).strip() for item in row)]


def split_text_records(text: str) -> list[str]:
    markers = list(re.finditer(r"(?m)^\s*(?:\*\*)?基本信息(?:\*\*)?\s*$", text))
    if len(markers) <= 1:
        chunks = re.split(r"(?m)^\s*-{3,}\s*$", text)
        return [item.strip() for item in chunks if item.strip()]
    return [text[marker.start():(markers[index + 1].start() if index + 1 < len(markers) else len(text))].strip() for index, marker in enumerate(markers)]


def load_rows(path: Path) -> list[tuple[dict[str, Any], str, str]]:
    suffix = path.suffix.casefold()
    if suffix == ".xlsx":
        return [(row, json.dumps(row, ensure_ascii=False, sort_keys=True), "xlsx") for row in read_xlsx(path)]
    text, encoding = read_text_safely(path)
    if suffix == ".csv":
        rows = list(csv.DictReader(text.splitlines()))
        return [(row, json.dumps(row, ensure_ascii=False, sort_keys=True), encoding) for row in rows]
    if suffix == ".json":
        payload = json.loads(text)
        if isinstance(payload, dict):
            payload = payload.get("records") or payload.get("shipments") or [payload]
        if not isinstance(payload, list):
            raise ValueError("JSON batch input must be an object or list.")
        return [(row, json.dumps(row, ensure_ascii=False, sort_keys=True), encoding) for row in payload if isinstance(row, dict)]
    return [(parse_text(chunk), chunk, encoding) for chunk in split_text_records(text)]


def record_key(normalized: dict[str, Any], index: int) -> str:
    record = normalized.get("record") or {}
    identity = record.get("house_bill") or record.get("master_bill") or record.get("declaration_no") or record.get("buyer") or f"record-{index:04d}"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", str(identity)).strip("-._")[:55]
    return f"{index:04d}-{slug or 'record'}"


def write_jsonl(path: Path, rows: list[Any]) -> None:
    path.write_text("".join(json.dumps(item, ensure_ascii=False, default=str) + "\n" for item in rows), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--mode", choices=("fast-scan", "deep-dive"), default="fast-scan")
    parser.add_argument("--rules", type=Path)
    parser.add_argument("--enrichment", type=Path)
    parser.add_argument("--evidence-bundle", type=Path)
    parser.add_argument("--source-image", action="append", default=[])
    parser.add_argument("--contamination-db", type=Path)
    parser.add_argument("--feedback-db", type=Path)
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args(argv)
    output = args.output_dir
    records_dir = output / "records"
    records_dir.mkdir(parents=True, exist_ok=True)
    contamination_db = args.contamination_db or output / "cross-record-index.sqlite3"
    feedback_db = args.feedback_db or output / "learning-feedback.sqlite3"
    rules = load_rules(args.rules)
    enrichment = json.loads(args.enrichment.read_text(encoding="utf-8-sig")) if args.enrichment else {}
    evidence_bundle = json.loads(args.evidence_bundle.read_text(encoding="utf-8-sig")) if args.evidence_bundle else {}
    source_rows = load_rows(args.input)
    normalized_rows: list[tuple[dict[str, Any], str, str]] = []
    load_errors: list[dict[str, Any]] = []
    for index, (raw, raw_text, encoding) in enumerate(source_rows, 1):
        try:
            if isinstance(raw.get("record"), dict):
                normalized_rows.append((raw, raw_text, encoding))
            else:
                normalized_rows.append((normalize(flatten_json(raw), input_encoding=encoding), raw_text, encoding))
        except Exception as exc:
            load_errors.append({"record_index": index, "stage": "normalize", "error": str(exc)})

    manifest_path = output / "batch-manifest.json"
    prior = {}
    if args.resume and manifest_path.exists():
        try:
            prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            prior = {}
    prior_hashes = {item.get("input_sha256"): item for item in prior.get("records", []) if item.get("status") in {"complete", "partial"}}

    results: list[dict[str, Any]] = []
    manifest_records: list[dict[str, Any]] = []
    pipeline = IntelligencePipeline(rules)
    assembler = V3Assembler(rules)
    for index, (normalized, raw_text, _encoding) in enumerate(normalized_rows, 1):
        digest = hashlib.sha256(raw_text.encode("utf-8")).hexdigest()
        key = record_key(normalized, index)
        json_path = records_dir / f"{key}.json"
        report_path = records_dir / f"{key}.md"
        if args.resume and digest in prior_hashes and json_path.exists():
            try:
                result = json.loads(json_path.read_text(encoding="utf-8"))
                results.append(result)
                manifest_records.append({"record_key": key, "input_sha256": digest, "status": result.get("status"), "research_status": result.get("research_status"), "resumed": True, "json": str(json_path), "report": str(report_path)})
                continue
            except Exception:
                pass
        try:
            related = [item[0] for position, item in enumerate(normalized_rows) if position != index - 1]
            result = pipeline.run(normalized, raw_text, enrichment=enrichment, related_records=related, mode=args.mode.replace("-", "_"))
            result = assembler.assemble(result, normalized, raw_text, mode=args.mode, enrichment=enrichment, related_records=related, evidence_bundle=evidence_bundle, source_images=args.source_image, contamination_db=contamination_db, feedback_db=feedback_db)
        except Exception as exc:
            result = emergency_result(args.mode, raw_text, rules_version=rules.get("version"), errors=[{"stage": "batch_record", "code": "record_failed", "message": str(exc), "retry_count": 0, "retryable": True}], missing_sections=["record_analysis"])
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
        report_path.write_text(render_v3_report(result), encoding="utf-8")
        results.append(result)
        manifest_records.append({"record_key": key, "input_sha256": digest, "status": result.get("status"), "research_status": result.get("research_status"), "resumed": False, "json": str(json_path), "report": str(report_path)})

    crm_rows = [render_crm_csv_row(item) for item in results]
    if crm_rows:
        with (output / "crm-import.csv").open("w", encoding="utf-8-sig", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=list(crm_rows[0]))
            writer.writeheader()
            writer.writerows(crm_rows)
    write_jsonl(output / "field-audit.jsonl", [{"record_key": manifest_records[i]["record_key"], "fields": item.get("field_audit") or []} for i, item in enumerate(results)])
    write_jsonl(output / "contact-ledger.jsonl", [{"record_key": manifest_records[i]["record_key"], "contacts": item.get("contact_evidence_ledger") or []} for i, item in enumerate(results)])
    write_jsonl(output / "review-ledger.jsonl", [{"record_key": manifest_records[i]["record_key"], "reviews": item.get("review_ledger") or []} for i, item in enumerate(results)])
    write_jsonl(output / "trade-history-audit.jsonl", [{"record_key": manifest_records[i]["record_key"], "summary": item.get("trade_history_summary") or {}, "rows": item.get("trade_history") or []} for i, item in enumerate(results)])
    write_jsonl(output / "competition-matrix.jsonl", [{"record_key": manifest_records[i]["record_key"], "matrix": item.get("competition_matrix") or {}} for i, item in enumerate(results)])
    write_jsonl(output / "research-coverage.jsonl", [{"record_key": manifest_records[i]["record_key"], "coverage": item.get("research_coverage") or [], "manual_checks": item.get("manual_checks") or []} for i, item in enumerate(results)])
    write_jsonl(output / "unresolved.jsonl", [{"record_key": manifest_records[i]["record_key"], "items": item.get("unresolved") or []} for i, item in enumerate(results)])
    write_jsonl(output / "outreach-preview.jsonl", [{"record_key": manifest_records[i]["record_key"], "outreach": item.get("outreach") or {}} for i, item in enumerate(results)])
    write_jsonl(output / "strategic-intelligence.jsonl", [{"record_key": manifest_records[i]["record_key"], "strategic": item.get("strategic_intelligence") or {}} for i, item in enumerate(results)])
    write_jsonl(output / "decision-layers.jsonl", [{"record_key": manifest_records[i]["record_key"], "layers": item.get("decision_layers") or {}} for i, item in enumerate(results)])
    write_jsonl(output / "learning-ledger.jsonl", [{"record_key": manifest_records[i]["record_key"], "learning": item.get("learning_ledger") or {}} for i, item in enumerate(results)])
    (output / "entity-aliases.json").write_text(json.dumps([item.get("entities") or {} for item in results], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "contamination-flags.json").write_text(json.dumps([item.get("cross_record_contamination") or {} for item in results], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = {"schema_version": "4.2.0", "input": str(args.input), "mode": args.mode, "record_count": len(source_rows), "processed_count": len(results), "failed_to_normalize": load_errors, "records": manifest_records, "outputs": {"crm": str(output / "crm-import.csv"), "field_audit": str(output / "field-audit.jsonl"), "contact_ledger": str(output / "contact-ledger.jsonl"), "review_ledger": str(output / "review-ledger.jsonl"), "trade_history_audit": str(output / "trade-history-audit.jsonl"), "competition_matrix": str(output / "competition-matrix.jsonl"), "research_coverage": str(output / "research-coverage.jsonl"), "unresolved": str(output / "unresolved.jsonl"), "outreach_preview": str(output / "outreach-preview.jsonl"), "strategic_intelligence": str(output / "strategic-intelligence.jsonl"), "decision_layers": str(output / "decision-layers.jsonl"), "learning_ledger": str(output / "learning-ledger.jsonl"), "aliases": str(output / "entity-aliases.json"), "contamination": str(output / "contamination-flags.json"), "collision_index": str(contamination_db), "feedback_ledger": str(feedback_db)}, "batch_sha256": stable_hash([item[1] for item in source_rows])}
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest, ensure_ascii=True, indent=2))
    return 0 if not load_errors else 2


if __name__ == "__main__":
    sys.exit(main())
