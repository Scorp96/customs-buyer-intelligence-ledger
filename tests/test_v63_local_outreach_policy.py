import unittest

from unified_runtime.local_outreach_policy import plan_local_outreach


class V63LocalOutreachTimingTests(unittest.TestCase):
    def test_iana_timezone_conversion_observes_dst_and_phone_window(self):
        result = plan_local_outreach({
            "now_utc": "2026-07-01T14:00:00+00:00",
            "timezone_name": "America/New_York",
            "timezone_confidence": "VERIFIED",
            "timezone_source": "OFFICIAL_ADDRESS_GEOCODE",
            "channel": "PHONE",
            "holiday_calendar_status": "VERIFIED",
            "holiday_dates_local": [],
            "market_locale": "en-US",
        })
        self.assertEqual(result["local_datetime"], "2026-07-01T10:00:00-04:00")
        self.assertTrue(result["contact_window_open"])
        self.assertTrue(result["execution_ready"])
        self.assertEqual(result["timezone_utc_offset"], "-04:00")

    def test_unknown_or_low_confidence_timezone_fails_closed(self):
        result = plan_local_outreach({
            "now_utc": "2026-09-02T01:00:00+00:00",
            "timezone_name": "Asia/Ho_Chi_Minh",
            "timezone_confidence": "LOW",
            "timezone_source": "COUNTRY_ONLY",
            "channel": "EMAIL",
            "holiday_calendar_status": "VERIFIED",
            "market_locale": "vi-VN",
        })
        self.assertFalse(result["contact_window_open"])
        self.assertFalse(result["execution_ready"])
        self.assertIn("TIMEZONE_RESOLUTION_REQUIRED", result["blockers"])

    def test_weekend_blocks_outreach(self):
        result = plan_local_outreach({
            "now_utc": "2026-09-05T03:00:00+00:00",
            "timezone_name": "Asia/Ho_Chi_Minh",
            "timezone_confidence": "HIGH",
            "timezone_source": "REGISTRY_ADDRESS_GEOCODE",
            "channel": "WHATSAPP",
            "holiday_calendar_status": "VERIFIED",
            "market_locale": "vi-VN",
        })
        self.assertEqual(result["local_weekday"], "SATURDAY")
        self.assertFalse(result["contact_window_open"])
        self.assertIn("NON_WORKING_DAY", result["blockers"])

    def test_verified_local_holiday_blocks_weekday(self):
        result = plan_local_outreach({
            "now_utc": "2026-09-02T03:00:00+00:00",
            "timezone_name": "Asia/Ho_Chi_Minh",
            "timezone_confidence": "VERIFIED",
            "timezone_source": "OFFICIAL_ADDRESS_GEOCODE",
            "channel": "EMAIL",
            "holiday_calendar_status": "VERIFIED",
            "holiday_dates_local": ["2026-09-02"],
            "market_locale": "vi-VN",
        })
        self.assertFalse(result["contact_window_open"])
        self.assertIn("LOCAL_HOLIDAY", result["blockers"])

    def test_lunch_gap_is_closed_and_next_window_is_same_day(self):
        result = plan_local_outreach({
            "now_utc": "2026-09-03T05:30:00+00:00",
            "timezone_name": "Asia/Ho_Chi_Minh",
            "timezone_confidence": "HIGH",
            "timezone_source": "REGISTRY_ADDRESS_GEOCODE",
            "channel": "WHATSAPP",
            "holiday_calendar_status": "VERIFIED",
            "holiday_dates_local": [],
            "market_locale": "vi-VN",
        })
        self.assertEqual(result["local_datetime"], "2026-09-03T12:30:00+07:00")
        self.assertFalse(result["contact_window_open"])
        self.assertEqual(result["next_window_local"], "2026-09-03T14:00:00+07:00")

    def test_unknown_holiday_calendar_keeps_candidate_window_but_blocks_execution_ready(self):
        result = plan_local_outreach({
            "now_utc": "2026-09-03T03:00:00+00:00",
            "timezone_name": "Asia/Ho_Chi_Minh",
            "timezone_confidence": "HIGH",
            "timezone_source": "REGISTRY_ADDRESS_GEOCODE",
            "channel": "EMAIL",
            "holiday_calendar_status": "UNKNOWN",
            "market_locale": "vi-VN",
        })
        self.assertTrue(result["contact_window_open"])
        self.assertFalse(result["execution_ready"])
        self.assertTrue(result["holiday_verification_required"])
        self.assertIn("HOLIDAY_CALENDAR_UNVERIFIED", result["execution_blockers"])


class V63OutreachLanguageTests(unittest.TestCase):
    def test_recipient_reply_language_overrides_market_default(self):
        result = plan_local_outreach({
            "now_utc": "2026-09-03T03:00:00+00:00",
            "timezone_name": "Asia/Ho_Chi_Minh",
            "timezone_confidence": "HIGH",
            "timezone_source": "REGISTRY_ADDRESS_GEOCODE",
            "channel": "EMAIL",
            "holiday_calendar_status": "VERIFIED",
            "market_locale": "vi-VN",
            "recipient_reply_language": "en-US",
            "official_site_languages": ["vi", "en"],
        })
        self.assertEqual(result["outreach_language"], "en")
        self.assertEqual(result["language_basis"], "RECIPIENT_REPLY")
        self.assertEqual(result["language_confidence"], "VERIFIED")
        self.assertIsNone(result["secondary_language"])

    def test_official_site_language_beats_market_default_when_single_language(self):
        result = plan_local_outreach({
            "now_utc": "2026-09-03T03:00:00+00:00",
            "timezone_name": "America/Mexico_City",
            "timezone_confidence": "HIGH",
            "timezone_source": "OFFICIAL_ADDRESS_GEOCODE",
            "channel": "EMAIL",
            "holiday_calendar_status": "VERIFIED",
            "market_locale": "es-MX",
            "official_site_languages": ["en"],
        })
        self.assertEqual(result["outreach_language"], "en")
        self.assertEqual(result["language_basis"], "OFFICIAL_SITE")
        self.assertEqual(result["language_confidence"], "HIGH")

    def test_curated_market_language_uses_english_fallback(self):
        result = plan_local_outreach({
            "now_utc": "2026-09-03T03:00:00+00:00",
            "timezone_name": "Asia/Ho_Chi_Minh",
            "timezone_confidence": "HIGH",
            "timezone_source": "REGISTRY_ADDRESS_GEOCODE",
            "channel": "EMAIL",
            "holiday_calendar_status": "VERIFIED",
            "market_locale": "vi-VN",
        })
        self.assertEqual(result["outreach_language"], "vi")
        self.assertEqual(result["secondary_language"], "en")
        self.assertEqual(result["language_basis"], "MARKET_LOCALE")
        self.assertEqual(result["language_confidence"], "MEDIUM")

    def test_unsupported_or_ambiguous_market_falls_back_to_english(self):
        result = plan_local_outreach({
            "now_utc": "2026-09-03T14:00:00+00:00",
            "timezone_name": "America/Toronto",
            "timezone_confidence": "HIGH",
            "timezone_source": "OFFICIAL_ADDRESS_GEOCODE",
            "channel": "EMAIL",
            "holiday_calendar_status": "VERIFIED",
            "market_locale": "fr-CA",
        })
        self.assertEqual(result["outreach_language"], "en")
        self.assertEqual(result["language_basis"], "ENGLISH_FALLBACK")
        self.assertEqual(result["language_confidence"], "LOW")


class V63OutreachCadenceTests(unittest.TestCase):
    def test_hard_bounce_blocks_same_route(self):
        result = plan_local_outreach({
            "now_utc": "2026-09-03T03:00:00+00:00",
            "timezone_name": "Asia/Ho_Chi_Minh",
            "timezone_confidence": "HIGH",
            "timezone_source": "REGISTRY_ADDRESS_GEOCODE",
            "channel": "EMAIL",
            "holiday_calendar_status": "VERIFIED",
            "market_locale": "vi-VN",
            "last_route_result": "HARD_BOUNCE",
        })
        self.assertFalse(result["execution_ready"])
        self.assertIn("SAME_ROUTE_DISABLED", result["execution_blockers"])
        self.assertEqual(result["next_action"], "USE_ALTERNATE_ROUTE")

    def test_no_receipt_enforces_minimum_business_day_cooldown(self):
        result = plan_local_outreach({
            "now_utc": "2026-09-01T03:00:00+00:00",
            "timezone_name": "Asia/Ho_Chi_Minh",
            "timezone_confidence": "HIGH",
            "timezone_source": "REGISTRY_ADDRESS_GEOCODE",
            "channel": "EMAIL",
            "holiday_calendar_status": "VERIFIED",
            "market_locale": "vi-VN",
            "last_route_result": "ACTUAL_SENT_NO_RECEIPT",
            "last_outreach_at_utc": "2026-08-28T03:00:00+00:00",
        })
        self.assertFalse(result["execution_ready"])
        self.assertIn("FOLLOWUP_COOLDOWN", result["execution_blockers"])
        self.assertEqual(result["minimum_followup_business_days"], 3)

    def test_policy_is_advisory_and_never_sends(self):
        result = plan_local_outreach({
            "now_utc": "2026-09-03T03:00:00+00:00",
            "timezone_name": "Asia/Ho_Chi_Minh",
            "timezone_confidence": "HIGH",
            "timezone_source": "REGISTRY_ADDRESS_GEOCODE",
            "channel": "EMAIL",
            "holiday_calendar_status": "VERIFIED",
            "market_locale": "vi-VN",
        })
        self.assertFalse(result["sends_message"])
        self.assertFalse(result["server_side_draft_created"])
        self.assertTrue(result["advisory_only"])


if __name__ == "__main__":
    unittest.main()

class V63MarketWorkweekTests(unittest.TestCase):
    def test_curated_sunday_thursday_market_blocks_friday(self):
        result = plan_local_outreach({
            "now_utc": "2026-09-04T07:00:00+00:00",
            "timezone_name": "Asia/Riyadh",
            "timezone_confidence": "VERIFIED",
            "timezone_source": "OFFICIAL_ADDRESS_GEOCODE",
            "channel": "PHONE",
            "holiday_calendar_status": "VERIFIED",
            "market_locale": "ar-SA",
        })
        self.assertEqual(result["local_weekday"], "FRIDAY")
        self.assertEqual(result["workweek_days"], [1, 2, 3, 4, 7])
        self.assertEqual(result["workweek_basis"], "CURATED_MARKET_POLICY")
        self.assertFalse(result["contact_window_open"])
        self.assertIn("NON_WORKING_DAY", result["blockers"])

    def test_curated_sunday_thursday_market_allows_sunday_window(self):
        result = plan_local_outreach({
            "now_utc": "2026-09-06T07:00:00+00:00",
            "timezone_name": "Asia/Riyadh",
            "timezone_confidence": "VERIFIED",
            "timezone_source": "OFFICIAL_ADDRESS_GEOCODE",
            "channel": "PHONE",
            "holiday_calendar_status": "VERIFIED",
            "market_locale": "ar-SA",
        })
        self.assertEqual(result["local_weekday"], "SUNDAY")
        self.assertTrue(result["execution_ready"])

    def test_unknown_market_without_verified_workweek_blocks_execution(self):
        result = plan_local_outreach({
            "now_utc": "2026-09-03T10:00:00+00:00",
            "timezone_name": "Etc/UTC",
            "timezone_confidence": "VERIFIED",
            "timezone_source": "OFFICIAL_ADDRESS_GEOCODE",
            "channel": "EMAIL",
            "holiday_calendar_status": "VERIFIED",
            "market_locale": "xx-ZZ",
        })
        self.assertFalse(result["execution_ready"])
        self.assertTrue(result["workweek_verification_required"])
        self.assertIn("WORKWEEK_UNVERIFIED", result["execution_blockers"])
