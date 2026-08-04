from app.models import OutreachValidationRequest
from app.outreach import validate_outreach


def base_request() -> dict:
    return {
        "outreach_recommended": True,
        "recipient": "sales@example.com",
        "recipient_status": "official_current",
        "subject": "PVC foam board supply for your team",
        "body": "Hello, we manufacture rigid PVC foam boards for signage and interior applications. We can prepare a concise comparison based on your current board requirements. Would it be useful if I sent our core specification sheet?\n\nBest regards,\nMark Zhou\nGuangzhou XingHuai New Materials Co., Ltd.\nMobile / WhatsApp: +86 180 2710 1852\nwww.xinghuai.com",
        "chinese_translation": "您好，我们生产用于广告和室内应用的硬质PVC发泡板。请问发送核心规格表是否方便？",
        "firewall_passed": True,
        "human_style_passed": True,
        "discovered_email_count": 1,
        "recipient_routes": [
            {
                "recipient": "sales@example.com",
                "recipient_status": "official_current",
                "route_class": "FORMAL_GENERAL",
                "role": "Official general business mailbox",
                "source_reference": "https://example.com/contact",
            }
        ],
        "time_plan": {"iana_timezone": "America/Puerto_Rico"},
    }


def test_sendable_draft_returns_mailto():
    result = validate_outreach(OutreachValidationRequest.model_validate(base_request()))
    assert result["status"] == "SENDABLE_DRAFT"
    assert result["to"] == "sales@example.com"
    assert result["mailto_url"].startswith("mailto:sales@example.com")


def test_blocked_draft_always_blanks_to_and_mailto():
    payload = base_request()
    payload["recipient_status"] = "historical"
    payload["recipient_routes"][0]["recipient_status"] = "historical"
    payload["recipient_routes"][0]["route_class"] = "VERIFY_ONLY"
    result = validate_outreach(OutreachValidationRequest.model_validate(payload))
    assert result["status"] == "DRAFT_BLOCKED"
    assert result["to"] == ""
    assert result["mailto_url"] is None
    assert result["sendable_recipient_union"] == []


def test_incomplete_email_union_blocks():
    payload = base_request()
    payload["discovered_email_count"] = 2
    result = validate_outreach(OutreachValidationRequest.model_validate(payload))
    assert result["status"] == "DRAFT_BLOCKED"
    assert any("email union incomplete" in reason for reason in result["block_reasons"])


def test_multiple_verified_routes_are_not_silently_omitted():
    payload = base_request()
    payload["discovered_email_count"] = 2
    payload["recipient_routes"].append(
        {
            "recipient": "procurement@example.com",
            "recipient_status": "user_confirmed_current",
            "route_class": "DIRECT_PROCUREMENT",
            "role": "User-confirmed purchasing route",
            "source_reference": "User confirmation on 2026-08-03",
        }
    )
    result = validate_outreach(OutreachValidationRequest.model_validate(payload))
    assert result["status"] == "SENDABLE_DRAFT"
    assert result["sendable_recipient_union"] == ["sales@example.com", "procurement@example.com"]
    assert result["to"] == "sales@example.com,procurement@example.com"
