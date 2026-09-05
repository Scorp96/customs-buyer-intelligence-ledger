import unittest

from unified_runtime.local_context_resolution import plan_local_context_resolution


class V63LocalContextResolutionTests(unittest.TestCase):
    def test_missing_timezone_creates_exact_resolution_task(self):
        result = plan_local_context_resolution({
            "account_id": "C500",
            "country_code": "US",
            "city": "Boston",
            "market_locale": "en-US",
            "holiday_calendar_status": "UNKNOWN",
        })
        kinds = [task["task_type"] for task in result["tasks"]]
        self.assertIn("RESOLVE_IANA_TIMEZONE", kinds)
        self.assertTrue(all(task["execution_required"] for task in result["tasks"]))
        self.assertTrue(all(task["receipt_required"] for task in result["tasks"]))
        self.assertFalse(result["planning_is_execution_proof"])

    def test_verified_timezone_but_unknown_holiday_creates_holiday_task(self):
        result = plan_local_context_resolution({
            "account_id": "C500",
            "timezone_name": "America/New_York",
            "timezone_confidence": "VERIFIED",
            "timezone_source": "OFFICIAL_ADDRESS_GEOCODE",
            "market_locale": "en-US",
            "holiday_calendar_status": "UNKNOWN",
        })
        kinds = [task["task_type"] for task in result["tasks"]]
        self.assertNotIn("RESOLVE_IANA_TIMEZONE", kinds)
        self.assertIn("VERIFY_LOCAL_BUSINESS_HOLIDAY", kinds)

    def test_curated_market_locale_is_enough_for_medium_language_strategy(self):
        result = plan_local_context_resolution({
            "account_id": "C500",
            "timezone_name": "Asia/Ho_Chi_Minh",
            "timezone_confidence": "HIGH",
            "timezone_source": "REGISTRY_ADDRESS_GEOCODE",
            "market_locale": "vi-VN",
            "holiday_calendar_status": "VERIFIED",
        })
        self.assertEqual(result["language_resolution_status"], "MEDIUM_LOCAL_WITH_ENGLISH_FALLBACK")
        self.assertNotIn("VERIFY_OUTREACH_LANGUAGE", [task["task_type"] for task in result["tasks"]])

    def test_missing_language_evidence_creates_language_resolution_task(self):
        result = plan_local_context_resolution({
            "account_id": "C500",
            "timezone_name": "Asia/Singapore",
            "timezone_confidence": "HIGH",
            "timezone_source": "OFFICIAL_ADDRESS_GEOCODE",
            "holiday_calendar_status": "VERIFIED",
        })
        self.assertIn("VERIFY_OUTREACH_LANGUAGE", [task["task_type"] for task in result["tasks"]])
        self.assertEqual(result["language_resolution_status"], "LANGUAGE_EVIDENCE_REQUIRED")

    def test_fully_resolved_context_has_no_tasks(self):
        result = plan_local_context_resolution({
            "account_id": "C500",
            "timezone_name": "America/Mexico_City",
            "timezone_confidence": "VERIFIED",
            "timezone_source": "OFFICIAL_ADDRESS_GEOCODE",
            "holiday_calendar_status": "VERIFIED",
            "market_locale": "es-MX",
            "recipient_reply_language": "es",
        })
        self.assertEqual(result["tasks"], [])
        self.assertEqual(result["context_resolution_state"], "RESOLVED_FOR_OUTREACH_PLANNING")


if __name__ == "__main__":
    unittest.main()

class V63WorkweekResolutionTests(unittest.TestCase):
    def test_curated_nonstandard_market_workweek_resolves_without_manual_company_lookup(self):
        result = plan_local_context_resolution({
            "account_id": "C-SA",
            "timezone_name": "Asia/Riyadh",
            "timezone_confidence": "VERIFIED",
            "holiday_calendar_status": "VERIFIED",
            "market_locale": "ar-SA",
        })
        self.assertEqual(result["workweek_resolution_status"], "CURATED_MARKET_POLICY")
        self.assertEqual(result["workweek_days"], [1, 2, 3, 4, 7])
        self.assertNotIn("VERIFY_LOCAL_BUSINESS_WORKWEEK", [task["task_type"] for task in result["tasks"]])

    def test_unknown_market_workweek_creates_resolution_task(self):
        result = plan_local_context_resolution({
            "account_id": "C-X",
            "timezone_name": "Etc/UTC",
            "timezone_confidence": "VERIFIED",
            "holiday_calendar_status": "VERIFIED",
            "market_locale": "xx-ZZ",
            "recipient_reply_language": "en",
        })
        self.assertIn("VERIFY_LOCAL_BUSINESS_WORKWEEK", [task["task_type"] for task in result["tasks"]])
        self.assertEqual(result["workweek_resolution_status"], "REQUIRED")
