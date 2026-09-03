from __future__ import annotations

from typing import Any

from .local_outreach_policy import (
    MARKET_LANGUAGE_DEFAULTS,
    USABLE_TIMEZONE_CONFIDENCE,
    VERIFIED_HOLIDAY_STATES,
    resolve_workweek_policy,
)


TIMEZONE_SOURCE_FAMILIES = (
    "official_address",
    "registry_address",
    "maps_business",
    "authoritative_geocode",
)
HOLIDAY_SOURCE_FAMILIES = (
    "official_government_calendar",
    "authoritative_business_calendar",
)
WORKWEEK_SOURCE_FAMILIES = (
    "official_government_business_calendar",
    "authoritative_business_calendar",
    "official_chamber_business_hours_guidance",
)
LANGUAGE_SOURCE_FAMILIES = (
    "recipient_reply",
    "recipient_preference",
    "official_site_language",
    "official_social_language",
)


def _normalize_locale(value: Any) -> str:
    raw = str(value or "").strip().replace("_", "-")
    if not raw:
        return ""
    parts = raw.split("-")
    if len(parts) == 1:
        return parts[0].lower()
    return f"{parts[0].lower()}-{parts[1].upper()}"


def _has_strong_language_evidence(context: dict[str, Any]) -> bool:
    if str(context.get("recipient_preferred_language") or "").strip():
        return True
    if str(context.get("recipient_reply_language") or "").strip():
        return True
    site = [str(v).strip() for v in (context.get("official_site_languages") or []) if str(v).strip()]
    return bool(site)


def _task(task_type: str, source_families: tuple[str, ...], reason: str) -> dict[str, Any]:
    return {
        "task_type": task_type,
        "recommended_source_families": list(source_families),
        "reason": reason,
        "execution_required": True,
        "receipt_required": True,
        "execution_performed": False,
        "planning_only": True,
    }


def plan_local_context_resolution(context: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(context, dict):
        raise ValueError("local context resolution input must be an object")

    tasks: list[dict[str, Any]] = []
    timezone_name = str(context.get("timezone_name") or "").strip()
    timezone_confidence = str(context.get("timezone_confidence") or "UNKNOWN").strip().upper()
    timezone_resolved = bool(timezone_name) and timezone_confidence in USABLE_TIMEZONE_CONFIDENCE
    if not timezone_resolved:
        tasks.append(_task(
            "RESOLVE_IANA_TIMEZONE",
            TIMEZONE_SOURCE_FAMILIES,
            "Recipient-local scheduling requires an exact IANA timezone with high/verified confidence; country-only assumptions are insufficient.",
        ))

    holiday_status = str(context.get("holiday_calendar_status") or "UNKNOWN").strip().upper()
    holiday_resolved = holiday_status in VERIFIED_HOLIDAY_STATES
    if not holiday_resolved:
        tasks.append(_task(
            "VERIFY_LOCAL_BUSINESS_HOLIDAY",
            HOLIDAY_SOURCE_FAMILIES,
            "Execution-ready outreach requires a current local holiday/business-day check.",
        ))

    workweek_policy = resolve_workweek_policy(context)
    workweek_resolved = not workweek_policy["workweek_verification_required"]
    if not workweek_resolved:
        tasks.append(_task(
            "VERIFY_LOCAL_BUSINESS_WORKWEEK",
            WORKWEEK_SOURCE_FAMILIES,
            "Recipient-local scheduling requires a current market/company business workweek; Mon-Fri must not be assumed for an unknown market.",
        ))

    locale = _normalize_locale(context.get("market_locale"))
    market_language = MARKET_LANGUAGE_DEFAULTS.get(locale)
    if _has_strong_language_evidence(context):
        language_status = "STRONG_LANGUAGE_EVIDENCE"
    elif market_language:
        language_status = "MEDIUM_LOCAL_WITH_ENGLISH_FALLBACK"
    else:
        language_status = "LANGUAGE_EVIDENCE_REQUIRED"
        tasks.append(_task(
            "VERIFY_OUTREACH_LANGUAGE",
            LANGUAGE_SOURCE_FAMILIES,
            "No recipient/site language evidence or curated market-language policy is available.",
        ))

    context_state = "RESOLVED_FOR_OUTREACH_PLANNING" if not tasks else "RESOLUTION_WORK_REQUIRED"
    return {
        "status": "PLANNED",
        "account_id": str(context.get("account_id") or "").strip() or None,
        "timezone_resolution_status": "RESOLVED" if timezone_resolved else "REQUIRED",
        "holiday_resolution_status": "RESOLVED" if holiday_resolved else "REQUIRED",
        "workweek_resolution_status": workweek_policy["workweek_basis"] if workweek_resolved else "REQUIRED",
        "workweek_days": workweek_policy["workweek_days"],
        "workweek_basis": workweek_policy["workweek_basis"],
        "language_resolution_status": language_status,
        "market_locale": locale or None,
        "market_language": market_language,
        "context_resolution_state": context_state,
        "tasks": tasks,
        "task_count": len(tasks),
        "planning_is_execution_proof": False,
        "host_execution_required": bool(tasks),
        "persistent_mutation_performed": False,
    }
