from __future__ import annotations

from typing import Any


_QUALIFIED_GRADES = {"B+", "A-", "A", "A+"}
_COMPANY_READY = {"COMPANY_ROUTE_READY", "NAMED_ROUTE_READY", "FOLLOW_UP_READY", "SEND_READY"}
_NAMED_READY = {"NAMED_ROUTE_READY", "FOLLOW_UP_READY", "SEND_READY"}


def compute_portfolio_metrics(opportunities: list[dict[str, Any]]) -> dict[str, Any]:
    rows = [row for row in opportunities if isinstance(row, dict)]
    unique_accounts = {str(row.get("account_id") or "").strip() for row in rows if str(row.get("account_id") or "").strip()}
    unique_opportunities = {str(row.get("opportunity_id") or "").strip() for row in rows if str(row.get("opportunity_id") or "").strip()}

    qualified = [row for row in rows if str(row.get("commercial_value_grade") or "").strip().upper() in _QUALIFIED_GRADES]
    company_ready = [row for row in rows if str(row.get("outreach_readiness") or "").strip().upper() in _COMPANY_READY]
    named_ready = [row for row in rows if str(row.get("outreach_readiness") or "").strip().upper() in _NAMED_READY]
    sales_ready_qualified = [row for row in qualified if str(row.get("outreach_readiness") or "").strip().upper() in _COMPANY_READY]
    anchors = [row for row in rows if str(row.get("stage") or row.get("lifecycle_stage") or "").strip().upper() == "PROMOTED_ANCHOR"]
    cross_sell = [row for row in rows if str(row.get("state") or "").strip().upper() == "CROSS_SELL_HYPOTHESIS"]

    return {
        "unique_account_count": len(unique_accounts),
        "product_opportunity_count": len(unique_opportunities),
        "bplus_or_above_opportunity_count": len(qualified),
        "company_route_ready_opportunity_count": len(company_ready),
        "named_route_ready_opportunity_count": len(named_ready),
        "sales_ready_qualified_opportunity_count": len(sales_ready_qualified),
        "promoted_anchor_opportunity_count": len(anchors),
        "cross_sell_hypothesis_count": len(cross_sell),
        "account_count_is_not_opportunity_count": True,
        "metrics_are_projection_only": True,
    }
