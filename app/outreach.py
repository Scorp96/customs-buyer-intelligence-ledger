from __future__ import annotations

import re
from urllib.parse import quote

from .models import OutreachValidationRequest, RouteClass, VerificationStatus


SENDABLE_STATUSES = {
    VerificationStatus.OFFICIAL_CURRENT,
    VerificationStatus.USER_CONFIRMED_CURRENT,
}
SENDABLE_ROUTES = {
    RouteClass.DIRECT_PROCUREMENT,
    RouteClass.FORMAL_GENERAL,
    RouteClass.ALTERNATIVE_REFERRAL,
}

UNSAFE_CLAIM_PATTERNS = {
    r"\bguaranteed\b": "contains an unqualified guarantee",
    r"\blowest price\b": "contains an unsupported lowest-price claim",
    r"\bwe know (?:that )?you (?:buy|import|purchase)\b": "exposes or overstates procurement knowledge",
    r"\byour current supplier\b": "asserts a current supplier relationship without proof",
    r"\bcertified for all\b": "overgeneralizes certification coverage",
}


def _unique_routes(request: OutreachValidationRequest) -> dict[str, object]:
    unique: dict[str, object] = {}
    for route in request.recipient_routes:
        unique[route.recipient.casefold()] = route
    return unique


def validate_outreach(request: OutreachValidationRequest) -> dict[str, object]:
    reasons = list(request.block_reasons)
    unique_routes = _unique_routes(request)

    if not request.outreach_recommended:
        reasons.append("outreach is not currently recommended")
    if not request.firewall_passed:
        reasons.append("evidence firewall was not passed")
    if not request.human_style_passed:
        reasons.append("human-style review was not passed")
    if request.discovered_email_count != len(unique_routes):
        reasons.append(
            f"email union incomplete: declared {request.discovered_email_count}, supplied {len(unique_routes)}"
        )
    if not request.subject.strip():
        reasons.append("subject is missing")
    if not request.body.strip():
        reasons.append("email body is missing")
    if not request.chinese_translation.strip():
        reasons.append("Chinese translation is missing")

    primary = request.recipient.strip().casefold()
    primary_route = unique_routes.get(primary)
    if not primary:
        reasons.append("recipient is missing")
    elif primary_route is None:
        reasons.append("recipient is not present in the complete discovered-email route table")
    else:
        if primary_route.recipient_status not in SENDABLE_STATUSES:
            reasons.append("primary recipient is not officially or user-confirmed current")
        if primary_route.route_class not in SENDABLE_ROUTES:
            reasons.append("primary recipient route is not sendable")
        if request.recipient_status != primary_route.recipient_status:
            reasons.append("primary recipient status conflicts with the route table")

    sendable_addresses: list[str] = []
    for address, route in unique_routes.items():
        if route.recipient_status in SENDABLE_STATUSES and route.route_class in SENDABLE_ROUTES:
            sendable_addresses.append(address)
    if not sendable_addresses:
        reasons.append("no verified sendable email route is available")

    body_lower = request.body.casefold()
    for pattern, message in UNSAFE_CLAIM_PATTERNS.items():
        if re.search(pattern, body_lower):
            reasons.append(message)
    if len(request.body.split()) > 180:
        reasons.append("first-contact email exceeds the 180-word safety ceiling")
    question_count = request.body.count("?") + request.body.count("锛?)
    if question_count > 3:
        reasons.append("first-contact email asks more than three questions")
    bullet_lines = sum(1 for line in request.body.splitlines() if re.match(r"^\s*[-*鈥\s+", line))
    if bullet_lines > 3:
        reasons.append("first-contact email contains too many bullet points")

    reasons = list(dict.fromkeys(reason.strip() for reason in reasons if reason.strip()))
    if reasons:
        return {
            "status": "DRAFT_BLOCKED",
            "to": "",
            "sendable_recipient_union": [],
            "subject": request.subject,
            "body": request.body,
            "chinese_translation": request.chinese_translation,
            "mailto_url": None,
            "block_reasons": reasons,
            "time_plan": request.time_plan,
            "manual_rule": "Do not send or create a clickable draft until every block reason is resolved.",
        }

    ordered = [primary, *(address for address in sendable_addresses if address != primary)]
    to_value = ",".join(ordered)
    mailto = (
        f"mailto:{quote(to_value, safe=',@')}?subject={quote(request.subject)}"
        f"&body={quote(request.body)}"
    )
    return {
        "status": "SENDABLE_DRAFT",
        "to": to_value,
        "sendable_recipient_union": ordered,
        "subject": request.subject,
        "body": request.body,
        "chinese_translation": request.chinese_translation,
        "mailto_url": mailto,
        "block_reasons": [],
        "time_plan": request.time_plan,
        "manual_rule": "The link opens a draft only. The user must review and click Send manually.",
    }
