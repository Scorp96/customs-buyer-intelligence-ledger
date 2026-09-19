#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mcp.object_store_persistence import S3CompatibleClient, S3Config
from mcp.object_store_recovery_v63 import RecoveryObjectStoreStateManagerV63
from unified_runtime.exact_checkout_mcp_harness_v63 import ExactCheckoutMcpHarness

PRODUCTION_PREFIX = "cbi-v61"
CANARY_OPPORTUNITY_IDS = (
    "OPP-TESORO-PVC-CANARY-20260918",
    "OPP-VN-0107809749-PVC-CANARY-20260918",
)
REQUIRED_TOOLS = {
    "get_product_opportunities",
    "get_portfolio_metrics",
    "plan_contact_exhaustion",
}


class ReadOnlyObjectClient:
    """Expose only object-store GET to make R2 mutation impossible in this gate."""

    def __init__(self, delegate: S3CompatibleClient) -> None:
        self._delegate = delegate

    def get(self, key: str):
        return self._delegate.get(key)


def _required_env(name: str) -> str:
    value = str(os.environ.get(name) or "").strip()
    if not value:
        raise RuntimeError(f"MISSING_REQUIRED_ENV:{name}")
    return value


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def run(output: Path) -> dict[str, Any]:
    configured_prefix = str(
        os.environ.get("CBI_V63_PRODUCTION_R2_PREFIX") or PRODUCTION_PREFIX
    ).strip().strip("/")
    if configured_prefix != PRODUCTION_PREFIX:
        raise RuntimeError(
            f"PRODUCTION_R2_PREFIX_MISMATCH:{configured_prefix or '<empty>'}"
        )

    delegate = S3CompatibleClient(
        S3Config(
            endpoint=_required_env("CBI_V63_R2_ENDPOINT"),
            bucket=_required_env("CBI_V63_R2_BUCKET"),
            access_key_id=_required_env("CBI_V63_R2_ACCESS_KEY_ID"),
            secret_access_key=_required_env("CBI_V63_R2_SECRET_ACCESS_KEY"),
            region=str(os.environ.get("CBI_V63_R2_REGION") or "auto").strip() or "auto",
        )
    )
    read_only_client = ReadOnlyObjectClient(delegate)
    manager = RecoveryObjectStoreStateManagerV63(
        read_only_client,  # type: ignore[arg-type]
        prefix=PRODUCTION_PREFIX,
    )
    pointer = manager.read_pointer(required=True)
    if pointer is None or int(pointer.generation) <= 0:
        raise RuntimeError("PRODUCTION_R2_POINTER_INVALID")

    with tempfile.TemporaryDirectory(prefix="cbi-v63-prod-r2-readonly-") as tmp_name:
        live_root = Path(tmp_name) / "live"
        if not manager.restore_into(live_root):
            raise RuntimeError("PRODUCTION_R2_RESTORE_MISSING")
        sessions = live_root / "sessions"
        if not sessions.is_dir():
            raise RuntimeError("PRODUCTION_R2_SESSIONS_MISSING")

        harness = ExactCheckoutMcpHarness(ROOT, live_root)
        harness.start()
        try:
            tool_names = harness.list_tool_names(2)
            missing = sorted(REQUIRED_TOOLS - tool_names)
            if missing:
                raise RuntimeError(
                    "PRODUCTION_CANARY_REQUIRED_TOOLS_MISSING:" + ",".join(missing)
                )

            request_id = 10
            canaries: list[dict[str, Any]] = []
            account_ids: set[str] = set()
            for opportunity_id in CANARY_OPPORTUNITY_IDS:
                projected = harness.tool(
                    request_id,
                    "get_product_opportunities",
                    {"opportunity_id": opportunity_id},
                )
                request_id += 1
                rows = list(projected.get("opportunities") or [])
                if len(rows) != 1:
                    raise RuntimeError(
                        f"CANARY_OPPORTUNITY_NOT_UNIQUE:{opportunity_id}:{len(rows)}"
                    )
                row = dict(rows[0])
                investigation_id = str(row.get("investigation_id") or "").strip()
                account_id = str(row.get("account_id") or "").strip()
                product_profile_id = str(
                    row.get("product_profile_id") or ""
                ).strip().upper()
                if not investigation_id or not account_id:
                    raise RuntimeError(
                        f"CANARY_OPPORTUNITY_IDENTITY_MISSING:{opportunity_id}"
                    )
                if product_profile_id != "PVC":
                    raise RuntimeError(
                        f"CANARY_PRODUCT_PROFILE_MISMATCH:{opportunity_id}:{product_profile_id}"
                    )
                if projected.get("projection_source") != (
                    "EXISTING_APPEND_ONLY_INVESTIGATION_EVENT_CHAIN"
                ):
                    raise RuntimeError(
                        f"CANARY_PROJECTION_SOURCE_INVALID:{opportunity_id}"
                    )
                if projected.get("persistent_mutation_performed") is not False:
                    raise RuntimeError(
                        f"CANARY_PROJECTION_MUTATION_FLAG_INVALID:{opportunity_id}"
                    )

                contact = harness.tool(
                    request_id,
                    "plan_contact_exhaustion",
                    {
                        "investigation_id": investigation_id,
                        "opportunity_id": opportunity_id,
                    },
                )
                request_id += 1
                if str(contact.get("product_profile_id") or "").upper() != "PVC":
                    raise RuntimeError(
                        f"CANARY_ID_ONLY_CONTACT_PROFILE_MISMATCH:{opportunity_id}"
                    )
                if contact.get("commercial_grade_mutated") is not False:
                    raise RuntimeError(
                        f"CANARY_ID_ONLY_CONTACT_MUTATED_GRADE:{opportunity_id}"
                    )

                account_ids.add(account_id)
                canaries.append(
                    {
                        "opportunity_id": opportunity_id,
                        "investigation_id_present": True,
                        "account_id_present": True,
                        "product_profile_id": "PVC",
                        "lifecycle_stage": row.get("lifecycle_stage"),
                        "derived_state_joined": row.get("derived_state_joined"),
                        "derived_state_status": row.get("derived_state_status"),
                        "id_only_contact_plan_product_profile_id": contact.get(
                            "product_profile_id"
                        ),
                        "id_only_contact_plan_commercial_grade_mutated": contact.get(
                            "commercial_grade_mutated"
                        ),
                    }
                )

            if len(account_ids) != len(CANARY_OPPORTUNITY_IDS):
                raise RuntimeError("CANARY_ACCOUNTS_NOT_DISTINCT")

            metrics = harness.tool(
                request_id,
                "get_portfolio_metrics",
                {"product_profile_id": "PVC"},
            )
            if int(metrics.get("unique_account_count") or 0) < len(account_ids):
                raise RuntimeError("CANARY_PORTFOLIO_UNIQUE_ACCOUNT_COUNT_TOO_LOW")
            if int(metrics.get("product_opportunity_count") or 0) < len(
                CANARY_OPPORTUNITY_IDS
            ):
                raise RuntimeError("CANARY_PORTFOLIO_OPPORTUNITY_COUNT_TOO_LOW")
            if metrics.get("persistent_mutation_performed") is not False:
                raise RuntimeError("CANARY_PORTFOLIO_MUTATION_FLAG_INVALID")
        finally:
            harness.stop()

    receipt = {
        "schema": "cbi.v63-production-r2-readonly-canary.v1",
        "status": "VERIFIED",
        "verified": True,
        "read_only": True,
        "production_r2_prefix": PRODUCTION_PREFIX,
        "production_r2_generation": int(pointer.generation),
        "production_r2_archive_format": pointer.archive_format,
        "object_store_write_api_exposed": False,
        "production_render_mutation_performed": False,
        "production_r2_mutation_performed": False,
        "canary_count": len(canaries),
        "canaries": canaries,
        "portfolio_metrics": {
            "unique_account_count": metrics.get("unique_account_count"),
            "product_opportunity_count": metrics.get("product_opportunity_count"),
            "bplus_or_above_opportunity_count": metrics.get(
                "bplus_or_above_opportunity_count"
            ),
            "company_route_ready_opportunity_count": metrics.get(
                "company_route_ready_opportunity_count"
            ),
            "named_route_ready_opportunity_count": metrics.get(
                "named_route_ready_opportunity_count"
            ),
            "sales_ready_qualified_opportunity_count": metrics.get(
                "sales_ready_qualified_opportunity_count"
            ),
            "promoted_anchor_opportunity_count": metrics.get(
                "promoted_anchor_opportunity_count"
            ),
        },
    }
    _write_json(output, receipt)
    return receipt


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Restore the current production R2 state into a runner-local temporary "
            "directory and verify existing Tesoro/Van Nhan Product Opportunity "
            "events through the integration-head read models. No object-store write "
            "API is exposed to the restore manager."
        )
    )
    parser.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        result = run(Path(args.output).expanduser().resolve())
    except Exception as exc:
        print(
            json.dumps(
                {
                    "schema": "cbi.v63-production-r2-readonly-canary.v1",
                    "status": "BLOCKED",
                    "verified": False,
                    "read_only": True,
                    "error_code": str(exc).split(":", 1)[0],
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
