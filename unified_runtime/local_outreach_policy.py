from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


OUTREACH_POLICY_VERSION = "1"

# Conservative B2B windows in the recipient's local civil time. They are
# scheduling defaults, not evidence about a specific company's office hours.
CHANNEL_WINDOWS: dict[str, tuple[tuple[str, str], ...]] = {
    "EMAIL": (("09:00", "11:30"), ("13:30", "16:30")),
    "CONTACT_FORM": (("09:00", "11:30"), ("13:30", "16:30")),
    "LINKEDIN": (("08:30", "11:30"), ("13:30", "17:00")),
    "PHONE": (("09:30", "11:30"), ("14:00", "16:30")),
    "WHATSAPP": (("09:30", "11:30"), ("14:00", "17:30")),
    "ZALO": (("09:30", "11:30"), ("14:00", "17:30")),
}

DEFAULT_WORKWEEK = (1, 2, 3, 4, 5)  # ISO Monday-Friday
USABLE_TIMEZONE_CONFIDENCE = frozenset({"HIGH", "VERIFIED"})
VERIFIED_HOLIDAY_STATES = frozenset({"VERIFIED", "CURRENT_VERIFIED"})
VERIFIED_WORKWEEK_STATES = frozenset({"VERIFIED", "CURRENT_VERIFIED"})

# Versioned scheduling priors for markets with a known standard B2B workweek.
# These are policy defaults, not company-office-hours evidence. Markets absent
# from this registry fail closed for execution until the Host resolves the
# current local business workweek.
CURATED_MARKET_WORKWEEKS: dict[str, tuple[int, ...]] = {
    "en-US": (1, 2, 3, 4, 5),
    "en-CA": (1, 2, 3, 4, 5),
    "es-MX": (1, 2, 3, 4, 5),
    "pt-BR": (1, 2, 3, 4, 5),
    "vi-VN": (1, 2, 3, 4, 5),
    "id-ID": (1, 2, 3, 4, 5),
    "en-PH": (1, 2, 3, 4, 5),
    "es-CR": (1, 2, 3, 4, 5),
    "en-PR": (1, 2, 3, 4, 5),
    "en-SG": (1, 2, 3, 4, 5),
    "ar-SA": (1, 2, 3, 4, 7),
}

# Outreach language defaults are deliberately narrower than search terms.
# Search vocabulary can be broad; client-facing language should be selected
# conservatively and fall back to English when the signal is ambiguous.
MARKET_LANGUAGE_DEFAULTS = {
    "vi-VN": "vi",
    "es-MX": "es",
    "pt-BR": "pt",
}

SAME_ROUTE_DISABLED_RESULTS = frozenset({
    "HARD_BOUNCE",
    "INVALID_ROUTE",
    "UNSUBSCRIBED",
    "SPAM_COMPLAINT",
})

FOLLOWUP_BUSINESS_DAYS = {
    "ACTUAL_SENT_NO_RECEIPT": 3,
    "READ_NO_REPLY": 3,
    "MAILBOX_FULL_TEMP": 2,
}


def _parse_aware(value: str, field: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid {field}") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


def _normalize_language(value: Any) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    return raw.replace("_", "-").split("-", 1)[0].lower()


def _normalize_locale(value: Any) -> str:
    raw = str(value or "").strip().replace("_", "-")
    if not raw:
        return ""
    parts = raw.split("-")
    if len(parts) == 1:
        return parts[0].lower()
    return f"{parts[0].lower()}-{parts[1].upper()}"


def _select_language(context: dict[str, Any]) -> dict[str, Any]:
    explicit = _normalize_language(context.get("recipient_preferred_language"))
    if explicit:
        return {
            "outreach_language": explicit,
            "secondary_language": None,
            "language_basis": "RECIPIENT_PREFERENCE",
            "language_confidence": "VERIFIED",
        }

    reply = _normalize_language(context.get("recipient_reply_language"))
    if reply:
        return {
            "outreach_language": reply,
            "secondary_language": None,
            "language_basis": "RECIPIENT_REPLY",
            "language_confidence": "VERIFIED",
        }

    site_languages = []
    for raw in context.get("official_site_languages") or []:
        lang = _normalize_language(raw)
        if lang and lang not in site_languages:
            site_languages.append(lang)

    locale = _normalize_locale(context.get("market_locale"))
    market_language = MARKET_LANGUAGE_DEFAULTS.get(locale)

    if len(site_languages) == 1:
        lang = site_languages[0]
        return {
            "outreach_language": lang,
            "secondary_language": None if lang == "en" else "en",
            "language_basis": "OFFICIAL_SITE",
            "language_confidence": "HIGH",
        }

    if market_language and market_language in site_languages:
        return {
            "outreach_language": market_language,
            "secondary_language": None if market_language == "en" else "en",
            "language_basis": "OFFICIAL_SITE_MARKET_MATCH",
            "language_confidence": "HIGH",
        }

    if market_language:
        return {
            "outreach_language": market_language,
            "secondary_language": None if market_language == "en" else "en",
            "language_basis": "MARKET_LOCALE",
            "language_confidence": "MEDIUM",
        }

    return {
        "outreach_language": "en",
        "secondary_language": None,
        "language_basis": "ENGLISH_FALLBACK",
        "language_confidence": "LOW",
    }


def _minutes(value: str) -> int:
    hh, mm = value.split(":", 1)
    return int(hh) * 60 + int(mm)


def _time_in_windows(local_dt: datetime, windows: tuple[tuple[str, str], ...]) -> bool:
    current = local_dt.hour * 60 + local_dt.minute
    return any(_minutes(start) <= current < _minutes(end) for start, end in windows)


def _normalize_holiday_dates(value: Any) -> set[date]:
    dates: set[date] = set()
    for raw in value or []:
        try:
            dates.add(date.fromisoformat(str(raw)))
        except ValueError as exc:
            raise ValueError("holiday_dates_local must contain YYYY-MM-DD dates") from exc
    return dates


def _normalize_workweek(value: Any) -> tuple[int, ...]:
    if value is None:
        return DEFAULT_WORKWEEK
    days = tuple(sorted({int(v) for v in value}))
    if not days or any(day < 1 or day > 7 for day in days):
        raise ValueError("workweek_days must contain ISO weekday numbers 1..7")
    return days


def resolve_workweek_policy(context: dict[str, Any]) -> dict[str, Any]:
    explicit = context.get("workweek_days")
    status = str(context.get("workweek_calendar_status") or "UNKNOWN").strip().upper()
    if explicit is not None:
        days = _normalize_workweek(explicit)
        verified = status in VERIFIED_WORKWEEK_STATES
        return {
            "workweek_days": list(days),
            "workweek_basis": "EXPLICIT_VERIFIED" if verified else "EXPLICIT_UNVERIFIED",
            "workweek_calendar_status": status,
            "workweek_verification_required": not verified,
        }

    locale = _normalize_locale(context.get("market_locale"))
    curated = CURATED_MARKET_WORKWEEKS.get(locale)
    if curated is not None:
        return {
            "workweek_days": list(curated),
            "workweek_basis": "CURATED_MARKET_POLICY",
            "workweek_calendar_status": "CURATED_VERIFIED",
            "workweek_verification_required": False,
        }

    return {
        "workweek_days": list(DEFAULT_WORKWEEK),
        "workweek_basis": "DEFAULT_MON_FRI_UNVERIFIED",
        "workweek_calendar_status": status,
        "workweek_verification_required": True,
    }


def _next_window(
    local_now: datetime,
    windows: tuple[tuple[str, str], ...],
    workweek: tuple[int, ...],
    holiday_dates: set[date],
) -> datetime | None:
    for day_offset in range(0, 22):
        target_date = local_now.date() + timedelta(days=day_offset)
        if target_date.isoweekday() not in workweek or target_date in holiday_dates:
            continue
        for start, _end in windows:
            hh, mm = [int(v) for v in start.split(":", 1)]
            candidate = datetime.combine(target_date, time(hh, mm), tzinfo=local_now.tzinfo)
            if candidate > local_now:
                return candidate
    return None


def _business_days_elapsed(
    start_local: datetime,
    end_local: datetime,
    workweek: tuple[int, ...],
    holiday_dates: set[date],
) -> int:
    if end_local <= start_local:
        return 0
    cursor = start_local.date() + timedelta(days=1)
    end_date = end_local.date()
    count = 0
    while cursor <= end_date:
        if cursor.isoweekday() in workweek and cursor not in holiday_dates:
            count += 1
        cursor += timedelta(days=1)
    return count


def _format_offset(local_dt: datetime) -> str:
    raw = local_dt.strftime("%z")
    if not raw:
        return ""
    return f"{raw[:3]}:{raw[3:]}"


def plan_local_outreach(context: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(context, dict):
        raise ValueError("local outreach context must be an object")

    channel = str(context.get("channel") or "EMAIL").strip().upper()
    if channel not in CHANNEL_WINDOWS:
        raise ValueError(f"unsupported outreach channel: {channel}")
    windows = CHANNEL_WINDOWS[channel]
    workweek_policy = resolve_workweek_policy(context)
    workweek = tuple(workweek_policy["workweek_days"])
    holidays = _normalize_holiday_dates(context.get("holiday_dates_local"))
    holiday_status = str(context.get("holiday_calendar_status") or "UNKNOWN").strip().upper()

    language = _select_language(context)
    blockers: list[str] = []
    execution_blockers: list[str] = []

    timezone_name = str(context.get("timezone_name") or "").strip()
    timezone_confidence = str(context.get("timezone_confidence") or "UNKNOWN").strip().upper()
    timezone_source = str(context.get("timezone_source") or "UNKNOWN").strip().upper()

    local_now: datetime | None = None
    zone: ZoneInfo | None = None
    if not timezone_name or timezone_confidence not in USABLE_TIMEZONE_CONFIDENCE:
        blockers.append("TIMEZONE_RESOLUTION_REQUIRED")
    else:
        try:
            zone = ZoneInfo(timezone_name)
        except ZoneInfoNotFoundError:
            blockers.append("TIMEZONE_RESOLUTION_REQUIRED")

    if zone is not None and not blockers:
        now_utc = _parse_aware(context.get("now_utc") or datetime.now(timezone.utc).isoformat(), "now_utc")
        local_now = now_utc.astimezone(zone)
        if local_now.isoweekday() not in workweek:
            blockers.append("NON_WORKING_DAY")
        if local_now.date() in holidays:
            blockers.append("LOCAL_HOLIDAY")
        if not blockers and not _time_in_windows(local_now, windows):
            blockers.append("OUTSIDE_CHANNEL_WINDOW")

    contact_window_open = local_now is not None and not blockers

    holiday_verification_required = holiday_status not in VERIFIED_HOLIDAY_STATES
    if holiday_verification_required:
        execution_blockers.append("HOLIDAY_CALENDAR_UNVERIFIED")
    if workweek_policy["workweek_verification_required"]:
        execution_blockers.append("WORKWEEK_UNVERIFIED")

    last_result = str(context.get("last_route_result") or "").strip().upper()
    next_action = "CONTACT_IN_RECOMMENDED_WINDOW"
    min_followup_business_days = FOLLOWUP_BUSINESS_DAYS.get(last_result, 0)

    if last_result in SAME_ROUTE_DISABLED_RESULTS:
        execution_blockers.append("SAME_ROUTE_DISABLED")
        next_action = "USE_ALTERNATE_ROUTE"
    elif last_result == "REPLY":
        execution_blockers.append("GENERIC_FOLLOWUP_BLOCKED_BY_ACTIVE_CONVERSATION")
        next_action = "CONTINUE_CONTEXTUAL_CONVERSATION"
    elif min_followup_business_days and local_now is not None:
        raw_last = context.get("last_outreach_at_utc")
        if raw_last:
            last_local = _parse_aware(str(raw_last), "last_outreach_at_utc").astimezone(local_now.tzinfo)
            elapsed = _business_days_elapsed(last_local, local_now, workweek, holidays)
            if elapsed < min_followup_business_days:
                execution_blockers.append("FOLLOWUP_COOLDOWN")
                next_action = "WAIT_FOR_FOLLOWUP_WINDOW"

    if blockers:
        execution_blockers.extend(b for b in blockers if b not in execution_blockers)

    execution_ready = contact_window_open and not execution_blockers
    next_window = None
    if local_now is not None and not contact_window_open:
        next_window = _next_window(local_now, windows, workweek, holidays)

    result = {
        "status": "READY" if local_now is not None else "TIMEZONE_RESOLUTION_REQUIRED",
        "policy_version": OUTREACH_POLICY_VERSION,
        "channel": channel,
        "timezone_name": timezone_name or None,
        "timezone_confidence": timezone_confidence,
        "timezone_source": timezone_source,
        "local_datetime": local_now.isoformat(timespec="seconds") if local_now else None,
        "local_weekday": local_now.strftime("%A").upper() if local_now else None,
        "timezone_utc_offset": _format_offset(local_now) if local_now else None,
        "workweek_days": list(workweek),
        "workweek_basis": workweek_policy["workweek_basis"],
        "workweek_calendar_status": workweek_policy["workweek_calendar_status"],
        "workweek_verification_required": workweek_policy["workweek_verification_required"],
        "channel_windows_local": [list(item) for item in windows],
        "holiday_calendar_status": holiday_status,
        "holiday_verification_required": holiday_verification_required,
        "contact_window_open": contact_window_open,
        "execution_ready": execution_ready,
        "blockers": blockers,
        "execution_blockers": execution_blockers,
        "next_window_local": next_window.isoformat(timespec="seconds") if next_window else None,
        "next_window_utc": next_window.astimezone(timezone.utc).isoformat(timespec="seconds") if next_window else None,
        "minimum_followup_business_days": min_followup_business_days,
        "last_route_result": last_result or None,
        "next_action": next_action,
        "research_language_is_separate": True,
        "outreach_language_terms_are_not_evidence": True,
        "technical_claims_must_remain_evidence_bound": True,
        "sends_message": False,
        "server_side_draft_created": False,
        "advisory_only": True,
        **language,
    }
    return result
