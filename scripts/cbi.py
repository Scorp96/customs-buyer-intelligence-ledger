#!/usr/bin/env python3
"""Operator and orchestration CLI for Customs Buyer Intelligence v6.1.

The CLI has two deliberately separate responsibilities:

1. operator commands for an existing Runtime (status/resume/claims/etc.);
2. Git-controlled customs-input orchestration that can normalize a user-supplied
   shipment record, preview an ANSWER_FIRST host request, or explicitly
   bootstrap a durable FULL_AUDIT investigation.

The CLI never performs public-web research by itself.  The Runtime is a
governance/evidence engine; actual web/browser/registry/maps research remains a
Host responsibility.  `audit-file --commit` therefore persists only the
user-supplied customs record with D1 authority and emits the next EIV-ranked
research objectives for a Host to execute.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


PLUGIN_ROOT = Path(__file__).resolve().parents[1]
if str(PLUGIN_ROOT) not in sys.path:
    sys.path.insert(0, str(PLUGIN_ROOT))

from unified_runtime import UnifiedRuntime, ValidationError  # noqa: E402
from unified_runtime.backup_recovery_hardened import ProductionBackupRecoveryManager  # noqa: E402
from unified_runtime.resilience import canonical_json, digest  # noqa: E402


class ProductionMcpClient:
    """Minimal local stdio client for the v6.1 production adapter.

    Mutating orchestration must pass through the production MCP adapter so it
    inherits the write-ahead idempotency/recovery layer instead of bypassing it
    with direct Runtime method calls.
    """

    def __init__(self, session_root: str | None) -> None:
        if not session_root:
            raise ValueError(
                "audit commit requires an explicit/discoverable V6 session root; "
                "pass --session-root or set CBI_SESSION_ROOT"
            )
        server = PLUGIN_ROOT / "mcp" / "server_v61_backup_recovery.py"
        if not server.is_file():
            raise RuntimeError(f"production MCP entrypoint not found: {server}")
        env = dict(os.environ)
        env["CBI_SESSION_ROOT"] = str(Path(session_root).expanduser().resolve())
        env.setdefault("PYTHONDONTWRITEBYTECODE", "1")
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-B",
                "-Xutf8",
                str(server),
                "--stdio",
            ],
            cwd=str(PLUGIN_ROOT),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env=env,
        )
        self.request_id = 0
        self._rpc("initialize", {"protocolVersion": "2025-06-18"})

    def _rpc(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("production MCP stdio is unavailable")
        self.request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self.request_id,
            "method": method,
            "params": params or {},
        }
        self.process.stdin.write(json.dumps(request, ensure_ascii=True) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            stderr = (
                self.process.stderr.read()
                if self.process.stderr is not None
                else ""
            )
            raise RuntimeError(
                "production MCP ended before returning a response"
                + (f": {stderr[-2000:]}" if stderr else "")
            )
        response = json.loads(line)
        if "error" in response:
            error = response["error"]
            message = (
                str(error.get("message") or error)
                if isinstance(error, dict)
                else str(error)
            )
            raise RuntimeError(f"MCP {method} failed: {message}")
        return response

    def tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        response = self._rpc(
            "tools/call",
            {"name": name, "arguments": arguments},
        )
        result = response.get("result") or {}
        structured = (
            result.get("structuredContent")
            if isinstance(result, dict)
            else None
        )
        if not isinstance(structured, dict):
            raise RuntimeError(
                f"MCP tool {name} returned no structuredContent"
            )
        return structured

    def close(self) -> None:
        process = self.process
        if process.poll() is None:
            if process.stdin is not None and not process.stdin.closed:
                process.stdin.close()
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
        for stream in (process.stdout, process.stderr):
            if stream is not None and not stream.closed:
                stream.close()

    def __enter__(self) -> "ProductionMcpClient":
        return self

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        self.close()


CUSTOMS_FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "data_source": ("data_source", "source_dataset", "数据源"),
    "date": ("date", "shipment_date", "日期"),
    "master_bill": ("master_bill", "mbl", "主单号"),
    "house_bill": ("house_bill", "hbl", "分单号"),
    "supplier": ("supplier", "shipper", "供应商"),
    "supplier_address": ("supplier_address", "shipper_address", "供应商地址"),
    "buyer": ("buyer", "purchaser", "consignee", "采购商"),
    "buyer_address": ("buyer_address", "purchaser_address", "consignee_address", "采购商地址"),
    "buyer_country": ("buyer_country", "country", "采购商国家"),
    "quantity": ("quantity", "qty", "数量"),
    "weight_kg": ("weight_kg", "weight", "重量_kg", "重量（kg）", "重量"),
    "teu": ("teu", "TEU"),
    "product": ("product", "product_description", "产品"),
    "logistics_shipper": ("logistics_shipper", "物流发货人"),
    "logistics_consignee": ("logistics_consignee", "物流收货人"),
    "origin": ("origin", "origin_country", "原产地"),
    "origin_port": ("origin_port", "port_of_loading", "起运港"),
    "place_of_receipt": ("place_of_receipt", "Place Of Receipt"),
    "destination": ("destination", "destination_country", "目的地"),
    "destination_port": ("destination_port", "port_of_discharge", "目的港"),
    "carrier": ("carrier", "承运人"),
    "vessel": ("vessel", "vessel_name", "船名"),
    "vessel_country": ("vessel_country", "Vessel Country"),
    "transport_mode": ("transport_mode", "运输方式"),
    "container": ("container", "container_number", "集装箱"),
    "containers": ("containers", "Containers"),
    "voyage_number": ("voyage_number", "Voyage Number"),
    "notify": ("notify", "Notify"),
    "notify_address": ("notify_address", "notify_addr", "Notify_addr"),
    "secondary_notify": ("secondary_notify", "Secondary Notify"),
    "estimated_arrival_date": (
        "estimated_arrival_date",
        "eta",
        "Estimated Arrival Date",
    ),
    "update_date": ("update_date", "Update Date"),
    "run_date": ("run_date", "Run Date"),
    "hidden": ("hidden", "Hidden"),
    "bill_type": ("bill_type", "Bill Type"),
    "manifest_number": ("manifest_number", "Manifest Number"),
    "record_status": ("record_status", "Record Status"),
    "conveyance": ("conveyance", "Conveyance"),
}


def emit(value: object) -> int:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))
    return 0


def backup_public(value: dict) -> dict:
    return {
        "snapshot_id": value.get("snapshot_id"),
        "created_at": value.get("created_at"),
        "reasons": list(value.get("reasons") or []),
        "path": value.get("path"),
        "deduplicated": value.get("deduplicated") is True,
        "warnings": list(value.get("warnings") or []),
    }


def production_session_root() -> str | None:
    """Return the explicit production V6 session root when discoverable.

    The production MCP already binds CBI_SESSION_ROOT explicitly.  The CLI
    mirrors that behavior on Windows so an operator command cannot silently
    fall back to the historical pre-V6 root merely because it was launched
    outside the MCP host.
    """

    configured = str(os.environ.get("CBI_SESSION_ROOT") or "").strip()
    if configured:
        return configured
    local_app_data = str(os.environ.get("LOCALAPPDATA") or "").strip()
    if local_app_data:
        return str(
            Path(local_app_data)
            / "XingHuai"
            / "CustomsBuyerIntelligenceV6"
            / "sessions"
        )
    return None


def _first_present(source: dict[str, Any], aliases: tuple[str, ...]) -> Any:
    for key in aliases:
        if key in source and source[key] not in (None, ""):
            return source[key]
    return None


def _flatten_customs_payload(value: dict[str, Any]) -> dict[str, Any]:
    """Flatten common table-shaped JSON without destroying the original input."""

    flattened: dict[str, Any] = dict(value)
    for section_key in (
        "basic",
        "basic_info",
        "基本信息",
        "product_info",
        "产品信息",
        "shipping_info",
        "货运信息",
        "other_info",
        "其它信息",
        "其他信息",
    ):
        section = value.get(section_key)
        if isinstance(section, dict):
            for key, item in section.items():
                flattened.setdefault(str(key), item)
    return flattened


def _normalized_customs_view(record: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in record.items()
        if not key.startswith("_")
    }


def _raw_customs_input(record: dict[str, Any]) -> dict[str, Any]:
    raw = record.get("_raw_input")
    if not isinstance(raw, dict):
        raise ValueError("normalized customs record is missing preserved raw input")
    return raw


def normalize_customs_record(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("customs input must be one JSON object")

    raw_input = json.loads(canonical_json(value))
    flattened = _flatten_customs_payload(raw_input)
    normalized: dict[str, Any] = {}
    for canonical, aliases in CUSTOMS_FIELD_ALIASES.items():
        found = _first_present(flattened, aliases)
        if found not in (None, ""):
            normalized[canonical] = found

    buyer = str(normalized.get("buyer") or "").strip()
    if not buyer:
        raise ValueError("customs input requires buyer / purchaser / 采购商")
    normalized["buyer"] = buyer

    buyer_address = str(normalized.get("buyer_address") or "").strip()
    if buyer_address:
        normalized["buyer_address"] = buyer_address

    explicit_country = str(normalized.get("buyer_country") or "").strip()
    destination = str(normalized.get("destination") or "").strip()
    if not explicit_country and destination.casefold() in {
        "united states",
        "united states of america",
        "usa",
        "u.s.a.",
        "us",
        "u.s.",
    }:
        explicit_country = "United States"
    if not explicit_country:
        raise ValueError(
            "customs input requires buyer_country/country, or an explicit "
            "destination equal to United States"
        )
    normalized["buyer_country"] = explicit_country

    for numeric_key in ("weight_kg", "teu"):
        if numeric_key not in normalized:
            continue
        raw = normalized[numeric_key]
        try:
            number = float(raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{numeric_key} must be numeric") from exc
        if number < 0:
            raise ValueError(f"{numeric_key} must not be negative")
        normalized[numeric_key] = int(number) if number.is_integer() else number

    normalized["_input_schema"] = "cbi.customs-input.v1"
    normalized["_input_sha256"] = hashlib.sha256(
        canonical_json(raw_input).encode("utf-8")
    ).hexdigest()
    normalized["_raw_input"] = raw_input
    normalized["_raw_flattened_field_count"] = len(flattened)
    normalized["_normalized_field_count"] = len(
        [key for key in normalized if not key.startswith("_")]
    )
    return normalized


def _shipment_observed_at(record: dict[str, Any]) -> str:
    value = str(record.get("date") or "").strip()
    parsed: datetime | None = None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        if not value:
            break
        try:
            parsed = datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            break
        except ValueError:
            continue
    if parsed is None:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return parsed.isoformat().replace("+00:00", "Z")


def _customs_freshness(record: dict[str, Any]) -> str:
    value = str(record.get("date") or "").strip()
    parsed: datetime | None = None
    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        if not value:
            break
        try:
            parsed = datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
            break
        except ValueError:
            continue
    if parsed is None:
        return "UNKNOWN"
    age_days = (datetime.now(timezone.utc) - parsed).days
    if age_days < 0:
        return "UNKNOWN"
    if age_days <= 365:
        return "RECENT"
    if age_days <= 365 * 3:
        return "HISTORICAL"
    return "STALE"


def candidate_from_customs(record: dict[str, Any]) -> dict[str, Any]:
    candidate = {
        "name": record["buyer"],
        "country": record["buyer_country"],
    }
    if record.get("buyer_address"):
        candidate["address"] = record["buyer_address"]
    return candidate


def customs_observations(
    record: dict[str, Any],
    *,
    account_id: str,
) -> list[dict[str, Any]]:
    input_hash = str(record["_input_sha256"])
    locator = f"user-input://customs-record/{input_hash}"
    raw_input = _raw_customs_input(record)
    normalized_view = _normalized_customs_view(record)
    source = {
        "source_family": "user_customs_record",
        "source_type": "USER_INPUT",
        "reference_type": "USER_INPUT",
        "url": "",
        "locator": locator,
        "raw_content": {
            "schema": "cbi.customs-source-preserved.v1",
            "raw_input": raw_input,
            "normalized": normalized_view,
        },
        "authority_level": "D1_USER_SUPPLIED_UNVERIFIED",
        "freshness": _customs_freshness(record),
        "observed_at": _shipment_observed_at(record),
    }
    observations = [
        {
            "claim_key": "trade.import_activity",
            "result": "POSITIVE",
            "owner_type": "ACCOUNT",
            "owner_id": account_id,
            "value": {
                "customs_record": {
                    "normalized": normalized_view,
                    "raw_input": raw_input,
                },
                "verification_status": "USER_SUPPLIED_UNVERIFIED",
            },
            "source": dict(source),
            "boundary": (
                "User-supplied customs/shipment record only. It supports the "
                "declared shipment fact for research triage, but does not by "
                "itself prove Ultimate Buyer, repeat demand, annual volume, "
                "warehouse/channel capability, specifications, end use or "
                "commercial grade."
            ),
        }
    ]
    if record.get("supplier"):
        observations.append(
            {
                "claim_key": "relationship.supply_chain",
                "result": "POSITIVE",
                "owner_type": "ACCOUNT",
                "owner_id": account_id,
                "value": {
                    "declared_buyer": record["buyer"],
                    "declared_supplier": record["supplier"],
                    "master_bill": record.get("master_bill"),
                    "house_bill": record.get("house_bill"),
                    "customs_input_sha256": input_hash,
                    "verification_status": "USER_SUPPLIED_UNVERIFIED",
                },
                "source": dict(source),
                "boundary": (
                    "The relationship is only the party relationship declared "
                    "in the user-supplied shipment record. It does not prove "
                    "exclusive supply, manufacturer identity, payment control "
                    "or continuing procurement."
                ),
            }
        )
    return observations


def host_lookup_request(record: dict[str, Any]) -> dict[str, Any]:
    normalized_view = _normalized_customs_view(record)
    raw_input = _raw_customs_input(record)
    return {
        "schema": "cbi.cli-host-handoff.v1",
        "mode": "ANSWER_FIRST",
        "runtime_persistence_requested": False,
        "buyer": record["buyer"],
        "country": record["buyer_country"],
        "customs_record": normalized_view,
        "normalized_customs_record": normalized_view,
        "raw_customs_record": raw_input,
        "raw_input_preserved": True,
        "host_execution_required": True,
        "reason": (
            "The Git-controlled CLI has no public web/browser/registry/maps "
            "tools. ANSWER_FIRST research must be executed by a Host that has "
            "those tools."
        ),
        "instruction": (
            "Use $investigate-customs-buyers in ANSWER_FIRST mode. Treat the "
            "attached customs record as user-provided evidence to verify, not "
            "final truth. Verify the company/legal entity, Ultimate Buyer, "
            "product/trade context, current contacts and routes with concrete "
            "public sources; report conflicts and boundaries; then produce the "
            "tailored development email and instant-chat drafts. Do not create "
            "Runtime history, CRM writeback, Closure or executable send action."
        ),
    }


def audit_preview(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema": "cbi.cli-audit-preview.v1",
        "status": "PREVIEW",
        "mode": "FULL_AUDIT",
        "runtime_mutation_performed": False,
        "candidate": candidate_from_customs(record),
        "customs_input_sha256": record["_input_sha256"],
        "raw_input_preserved": True,
        "raw_flattened_field_count": record["_raw_flattened_field_count"],
        "normalized_field_count": record["_normalized_field_count"],
        "normalized_customs_record": _normalized_customs_view(record),
        "raw_customs_record": _raw_customs_input(record),
        "proposed_initial_claims": [
            row["claim_key"]
            for row in customs_observations(record, account_id="PREVIEW-ACCOUNT")
        ],
        "boundary": (
            "Preview validates and normalizes input while preserving the exact "
            "raw JSON object. No canonical account, Investigation, Evidence, "
            "Pivot, Peer, CRM or outreach state is written."
        ),
        "next_command": "repeat with --commit to bootstrap the durable FULL_AUDIT",
    }


def bootstrap_audit(
    session_root: str | None,
    record: dict[str, Any],
    *,
    objective_limit: int,
    priority_grade: str,
    budget_units: float | None,
) -> dict[str, Any]:
    candidate = candidate_from_customs(record)
    input_hash = str(record["_input_sha256"])
    candidate_hash = digest(candidate)
    normalized_view = _normalized_customs_view(record)
    raw_input = _raw_customs_input(record)

    with ProductionMcpClient(session_root) as client:
        resolution = client.tool(
            "resolve_or_create_account",
            {
                "candidate": candidate,
                "create_if_missing": True,
                "idempotency_key": f"cli-resolve-{candidate_hash[:32]}",
            },
        )
        match = resolution.get("match")
        if (
            not isinstance(match, dict)
            or not str(match.get("account_id") or "").strip()
        ):
            raise RuntimeError(
                "canonical resolution did not return a usable account_id; "
                "manual identity review is required"
            )
        account_id = str(match["account_id"])

        start_arguments: dict[str, Any] = {
            "account": {
                "account_id": account_id,
                "country": candidate["country"],
                "name": candidate["name"],
            },
            "input": {
                "schema": "cbi.cli-customs-audit-start.v1",
                "customs_input_sha256": input_hash,
                "customs_record": normalized_view,
                "normalized_customs_record": normalized_view,
                "raw_customs_record": raw_input,
                "raw_input_preserved": True,
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "authority_claims": [],
            "provider_policy": {"mode": "PUBLIC_ONLY"},
            "network_policy": {
                "closure_strategy": "DECISION_SATURATION",
            },
            "priority_grade": priority_grade,
            "idempotency_key": (
                f"cli-start-{account_id.casefold()}-{input_hash[:20]}"
            )[:150],
        }
        if budget_units is not None:
            start_arguments["budget_units"] = budget_units
        start = client.tool("start_investigation", start_arguments)
        investigation_id = str(start["investigation_id"])

        bundle_id = f"BUNDLE-CUSTOMS-{input_hash[:24]}"
        compiled = client.tool(
            "compile_and_append_research_bundle",
            {
                "investigation_id": investigation_id,
                "bundle": {
                    "bundle_id": bundle_id,
                    "observations": customs_observations(
                        record,
                        account_id=account_id,
                    ),
                },
                "idempotency_key": f"cli-compile-{input_hash[:32]}",
            },
        )

        objectives = client.tool(
            "get_next_research_objectives",
            {
                "investigation_id": investigation_id,
                "limit": objective_limit,
            },
        )
        commercial = client.tool(
            "evaluate_commercial_value",
            {"investigation_id": investigation_id},
        )
        confidence = client.tool(
            "evaluate_research_confidence",
            {"investigation_id": investigation_id},
        )
        saturation = client.tool(
            "evaluate_decision_saturation",
            {"investigation_id": investigation_id},
        )
        health = client.tool(
            "get_investigation_health",
            {"investigation_id": investigation_id},
        )

    return {
        "schema": "cbi.cli-audit-bootstrap.v1",
        "status": "AUDIT_BOOTSTRAPPED",
        "mode": "FULL_AUDIT",
        "runtime_mutation_performed": True,
        "mutation_path": "V6_1_PRODUCTION_MCP_WAL",
        "account_resolution": resolution,
        "account_id": account_id,
        "investigation_id": investigation_id,
        "investigation_start": start,
        "investigation_resumed_existing": start.get("resumed_existing") is True,
        "research_priority_grade": priority_grade,
        "customs_input_sha256": input_hash,
        "raw_input_preserved": True,
        "raw_flattened_field_count": record["_raw_flattened_field_count"],
        "normalized_field_count": record["_normalized_field_count"],
        "customs_bundle_id": bundle_id,
        "customs_evidence_compilation": compiled,
        "initial_commercial_value": commercial,
        "initial_research_confidence": confidence,
        "decision_saturation": saturation,
        "investigation_health": health,
        "next_research_objectives": objectives,
        "host_execution_required": True,
        "host_instruction": (
            f"Use $investigate-customs-buyers to resume Investigation "
            f"{investigation_id} in FULL_AUDIT mode. The Git-controlled CLI "
            "has already persisted the complete raw user-supplied customs JSON "
            "plus its normalized view as D1 evidence through the v6.1 "
            "production WAL adapter. Execute the EIV-ranked next research "
            "objectives with real public web/browser/registry/maps sources; "
            "compile real host results into Evidence; run all six network "
            "branches for every Anchor; preserve conflicts; and continue until "
            "Decision Saturation or a truthful PAUSED_RESOURCE_LIMIT. Do not "
            "treat the input shipment as proof of Ultimate Buyer, repeat demand "
            "or product specifications."
        ),
        "crm_writeback_performed": False,
        "outreach_send_performed": False,
    }


def _load_json_file(path: str) -> Any:
    source = Path(path).expanduser().resolve()
    if not source.is_file():
        raise ValueError(f"input file not found: {source}")
    raw = source.read_text(encoding="utf-8-sig")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON input: {source}: {exc}") from exc


def _add_customs_file_arguments(
    parser: argparse.ArgumentParser,
    *,
    allow_commit: bool,
) -> None:
    parser.add_argument("input_file")
    if allow_commit:
        parser.add_argument(
            "--objective-limit",
            type=int,
            default=20,
            help="Maximum EIV-ranked next objectives to return after bootstrap.",
        )
        parser.add_argument(
            "--priority-grade",
            choices=("A+", "A", "A-", "B+", "B", "B-", "C", "D", "NQ"),
            default="A",
            help=(
                "Research-budget priority only; it is NOT the buyer's "
                "Commercial Value grade. FULL_AUDIT defaults to A."
            ),
        )
        parser.add_argument(
            "--budget-units",
            type=float,
            default=None,
            help=(
                "Optional explicit research budget. Resource exhaustion may "
                "pause but never falsely close research."
            ),
        )
        parser.add_argument(
            "--commit",
            action="store_true",
            help=(
                "Explicitly persist canonical account / Investigation / initial "
                "D1 customs Evidence. Without this flag the command is read-only."
            ),
        )


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="cbi",
        description="Customs Buyer Intelligence v6.1 operator/orchestration CLI",
    )
    parser.add_argument(
        "--session-root",
        default=production_session_root(),
        help=(
            "Runtime sessions root. On Windows defaults to "
            "%LOCALAPPDATA%\\XingHuai\\CustomsBuyerIntelligenceV6\\sessions; "
            "CBI_SESSION_ROOT overrides it."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    for command in ("status", "resume", "claims", "pivots", "peers"):
        child = sub.add_parser(command)
        child.add_argument("investigation_id")

    health = sub.add_parser("health")
    health.add_argument("--investigation-id", default="")

    pending = sub.add_parser("pending")
    pending.add_argument("--limit", type=int, default=100)

    migrate = sub.add_parser("migrate")
    migrate.add_argument("target_root")
    migrate.add_argument("--source-session-root", default="")

    verify = sub.add_parser("verify")
    verify.add_argument("--investigation-id", default="")

    backup = sub.add_parser("backup")
    backup.add_argument("--reason", default="MANUAL_OPERATOR")
    backup.add_argument(
        "--daily",
        action="store_true",
        help="Create or reuse the UTC-day automatic snapshot.",
    )

    sub.add_parser("backups")

    restore = sub.add_parser("restore")
    restore.add_argument("target_root")
    restore.add_argument("--snapshot-id", default="")
    restore.add_argument(
        "--no-replay-live-tail",
        action="store_true",
        help="Restore the validated snapshot without replaying later proven live events.",
    )

    lookup = sub.add_parser(
        "lookup",
        help=(
            "Normalize one customs JSON record and emit a read-only "
            "ANSWER_FIRST Host research request."
        ),
    )
    _add_customs_file_arguments(lookup, allow_commit=False)

    audit = sub.add_parser(
        "audit-file",
        aliases=["audit"],
        help=(
            "Preview or explicitly bootstrap a durable FULL_AUDIT from one "
            "customs JSON record."
        ),
    )
    _add_customs_file_arguments(audit, allow_commit=True)

    batch = sub.add_parser(
        "batch-audit",
        help=(
            "Preview or explicitly bootstrap multiple customs records from a "
            "JSON array. Persistence requires --commit."
        ),
    )
    _add_customs_file_arguments(batch, allow_commit=True)

    args = parser.parse_args()

    try:
        if args.command == "lookup":
            record = normalize_customs_record(_load_json_file(args.input_file))
            return emit(host_lookup_request(record))

        if args.command in {"audit-file", "audit"}:
            record = normalize_customs_record(_load_json_file(args.input_file))
            if not args.commit:
                return emit(audit_preview(record))
            return emit(
                bootstrap_audit(
                    args.session_root,
                    record,
                    objective_limit=args.objective_limit,
                    priority_grade=args.priority_grade,
                    budget_units=args.budget_units,
                )
            )

        if args.command == "batch-audit":
            raw = _load_json_file(args.input_file)
            if not isinstance(raw, list) or not raw:
                raise ValueError("batch-audit input must be a non-empty JSON array")
            normalized = [normalize_customs_record(row) for row in raw]
            if not args.commit:
                return emit(
                    {
                        "schema": "cbi.cli-batch-audit-preview.v1",
                        "status": "PREVIEW",
                        "runtime_mutation_performed": False,
                        "record_count": len(normalized),
                        "records": [audit_preview(row) for row in normalized],
                    }
                )
            results = [
                bootstrap_audit(
                    args.session_root,
                    row,
                    objective_limit=args.objective_limit,
                    priority_grade=args.priority_grade,
                    budget_units=args.budget_units,
                )
                for row in normalized
            ]
            return emit(
                {
                    "schema": "cbi.cli-batch-audit-bootstrap.v1",
                    "status": "AUDITS_BOOTSTRAPPED",
                    "runtime_mutation_performed": True,
                    "record_count": len(results),
                    "results": results,
                    "crm_writeback_performed": False,
                    "outreach_send_performed": False,
                }
            )

        runtime = UnifiedRuntime(args.session_root)

        if args.command == "status":
            return emit(
                runtime.get_account_state(
                    {"investigation_id": args.investigation_id}
                )
            )
        if args.command == "health":
            payload = (
                {"investigation_id": args.investigation_id}
                if args.investigation_id
                else {}
            )
            return emit(runtime.get_runtime_health(payload))
        if args.command == "resume":
            return emit(
                runtime.resume_investigation(
                    {"investigation_id": args.investigation_id}
                )
            )
        if args.command == "claims":
            return emit(
                runtime.get_claims({"investigation_id": args.investigation_id})
            )
        if args.command == "pivots":
            return emit(
                runtime.get_material_pivots(
                    {"investigation_id": args.investigation_id}
                )
            )
        if args.command == "peers":
            state = runtime._v6_state(args.investigation_id)
            return emit(
                {
                    "investigation_id": args.investigation_id,
                    "peers": list(state["peers"].values()),
                }
            )
        if args.command == "pending":
            rows = runtime._v6_queue().entries()[: args.limit]
            return emit({"count": len(rows), "entries": rows})
        if args.command == "migrate":
            payload = {"target_root": args.target_root}
            if args.source_session_root:
                payload["source_session_root"] = args.source_session_root
            source_root = Path(
                payload.get("source_session_root") or runtime.store.root
            ).expanduser().resolve()
            if source_root == Path(runtime.store.root).resolve():
                manager = ProductionBackupRecoveryManager.from_runtime(runtime)
            else:
                manager = ProductionBackupRecoveryManager.for_session_root(
                    source_root
                )
            guard = manager.ensure_guard_snapshot(
                ["BEFORE_MIGRATION", "BEFORE_SCHEMA_UPGRADE"],
                digest(payload),
            )
            result = runtime.migrate_v5_4_1_to_v6(payload)
            return emit(
                {
                    **result,
                    "pre_migration_backup": backup_public(guard),
                }
            )
        if args.command == "verify":
            if args.investigation_id:
                return emit(
                    runtime.get_investigation_health(
                        {"investigation_id": args.investigation_id}
                    )
                )
            return emit(runtime.get_runtime_health({}))
        if args.command == "backup":
            manager = ProductionBackupRecoveryManager.from_runtime(runtime)
            result = (
                manager.ensure_daily_snapshot()
                if args.daily
                else manager.create_snapshot(args.reason)
            )
            return emit(backup_public(result))
        if args.command == "backups":
            manager = ProductionBackupRecoveryManager.from_runtime(runtime)
            return emit(manager.status(validate_latest=True))
        if args.command == "restore":
            manager = ProductionBackupRecoveryManager.from_runtime(runtime)
            return emit(
                manager.restore_latest_valid_snapshot(
                    args.target_root,
                    snapshot_id=args.snapshot_id,
                    replay_live_tail=not args.no_replay_live_tail,
                )
            )
        raise AssertionError("unreachable")
    except (ValueError, RuntimeError, ValidationError) as exc:
        return emit(
            {
                "schema": "cbi.cli-error.v1",
                "status": "ERROR",
                "error_type": type(exc).__name__,
                "error": str(exc),
                "runtime_mutation_may_have_started": bool(
                    getattr(args, "commit", False)
                ),
            }
        ) or 2


if __name__ == "__main__":
    raise SystemExit(main())
