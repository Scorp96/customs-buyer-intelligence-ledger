from __future__ import annotations

import copy
import hashlib
import tempfile
import unittest
import zipfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from unified_runtime.core import (
    CONTACT_SOURCE_PROFILE,
    NETWORK_BRANCHES,
    REQUIRED_MODULES,
    SOURCE_PROFILE_BY_BRANCH,
    UnifiedRuntime,
    ValidationError,
)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def write_synthetic_workbook(path: Path, marker: str = "baseline") -> None:
    content_types = '<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/></Types>'
    workbook = f'<?xml version="1.0"?><workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheets/><definedNames><definedName name="SyntheticMarker">"{marker}"</definedName></definedNames></workbook>'
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("xl/workbook.xml", workbook)


class RuntimeHarness:
    def __init__(self, root: Path, *, mode: str = "EXHAUSTIVE", priority: str = "A+", provider_policy: dict | None = None, network_policy: dict | None = None):
        self.runtime = UnifiedRuntime(root)
        self.counter = 0
        self.provider_counter = 0
        self.crm_counter = 0
        self.base_time = datetime(2026, 8, 22, 1, 0, tzinfo=timezone.utc)
        self.crm_path = root / "synthetic-main-crm.xlsx"
        write_synthetic_workbook(self.crm_path)
        self.start = self.runtime.start_investigation({
            "account": {"account_id": "ACCT-SYNTH-001", "country": "United States", "priority": priority, "name": "Synthetic Buyer One"},
            "input": {"synthetic": True},
            "mode": mode,
            "history": {"events": [], "opt_out": False},
            "authority_claims": [],
            "provider_policy": provider_policy or {"mode": "PUBLIC_ONLY"},
            "crm_path": str(self.crm_path),
            "network_policy": network_policy or {},
        })
        self.investigation_id = self.start["investigation_id"]

    def add_attempt(
        self,
        module: str,
        family: str,
        *,
        owner_id: str = "ACCT-SYNTH-001",
        result: str = "NEGATIVE_EXHAUSTED",
        query: str | None = None,
        pivot_specs: list[tuple[str, str, str]] | None = None,
        consume: list[dict] | None = None,
        discovered_peers: list[str] | None = None,
        relationship_bindings: dict[str, list[str]] | None = None,
        blocked_reason: str = "",
        evidence_overrides: dict | None = None,
        attempt_overrides: dict | None = None,
    ) -> tuple[str, str | None, dict]:
        self.counter += 1
        attempt_id = f"ATT-{self.counter:04d}"
        execution_id = f"EXEC-{self.counter:04d}"
        started = self.base_time + timedelta(seconds=self.counter * 10)
        completed = started + timedelta(seconds=3)
        query = query or f"Synthetic Buyer One {module} {family}"
        raw_hash = sha(f"raw:{attempt_id}:{query}")
        evidence: list[dict] = []
        evidence_id: str | None = None
        evidence_ids: list[str] = []
        normalized_result = result.upper()
        if normalized_result == "POSITIVE":
            evidence_id = f"E-{attempt_id}"
            evidence_ids = [evidence_id]
            item = {
                "evidence_id": evidence_id,
                "owner_type": "ACCOUNT" if owner_id == "ACCT-SYNTH-001" else "PEER",
                "owner_id": owner_id,
                "claim_key": f"{module}.{family}.verified",
                "module_or_branch": module,
                "source_type": family,
                "source_family": family,
                "reference_type": "PUBLIC_URL",
                "url": f"https://evidence.example/{attempt_id}",
                "locator": f"https://evidence.example/{attempt_id}",
                "observed_at": completed.isoformat(),
                "content_sha256": raw_hash,
                "snapshot_locator": f"snapshot://{attempt_id}",
                "claim_type": "FACT",
                "freshness": "CURRENT",
                "evidence_grade": "A2",
                "boundary": "Synthetic test fact; no production identity or contact data.",
                "conflict": "",
            }
            if evidence_overrides:
                item.update(evidence_overrides)
            evidence = [item]
        pivots = []
        pivot_ids = []
        for pivot_id, pivot_type, pivot_value in pivot_specs or []:
            pivot_ids.append(pivot_id)
            pivots.append({
                "pivot_id": pivot_id,
                "pivot_type": pivot_type,
                "pivot_value": pivot_value,
                "generated_by_attempt_id": attempt_id,
                "generated_at": completed.isoformat(),
                "consumed_by_attempt_id": "",
                "consumed_at": "",
                "consumption_result": "",
                "status": "OPEN",
            })
        attempt = {
            "attempt_id": attempt_id,
            "investigation_id": self.investigation_id,
            "owner_type": "ACCOUNT" if owner_id == "ACCT-SYNTH-001" else "PEER",
            "owner_id": owner_id,
            "module_or_branch": module,
            "source_family": family,
            "query": query,
            "started_at": started.isoformat(),
            "completed_at": completed.isoformat(),
            "checked_at": completed.isoformat(),
            "tool_or_operator": "synthetic-test-operator",
            "execution_id": execution_id,
            "result": normalized_result,
            "result_count": 1 if normalized_result == "POSITIVE" else 0,
            "raw_result_locator": f"snapshot://raw-{attempt_id}",
            "content_sha256": raw_hash,
            "evidence_ids": evidence_ids,
            "pivots_generated": pivot_ids,
            "blocked_reason": blocked_reason,
            "discovered_peer_ids": discovered_peers or [],
            "relationship_evidence_ids": relationship_bindings or {},
        }
        if attempt_overrides:
            attempt.update(attempt_overrides)
        result_payload = self.runtime.append_execution_receipt({
            "investigation_id": self.investigation_id,
            "attempt": attempt,
            "evidence": evidence,
            "pivots": pivots,
            "pivots_consumed": consume or [],
        })
        return attempt_id, evidence_id, result_payload

    def plan_provider(
        self,
        *,
        provider: str = "Synthetic Enrichment",
        provider_class: str = "CONTACT_ENRICHMENT",
        capability: str = "email_enrichment",
        status: str = "CONNECTED",
        requires_paid_credit: bool = False,
        cost_consent: bool = False,
    ) -> dict:
        return self.runtime.plan_provider_calls({
            "investigation_id": self.investigation_id,
            "requested_capabilities": [capability],
            "provider_inventory": [{
                "provider": provider,
                "provider_class": provider_class,
                "status": status,
                "capability_tools": {capability: "synthetic_provider_search"},
                "requires_paid_credit": requires_paid_credit,
                "permissions": ["read synthetic company and contact data"],
            }],
            "cost_consent": cost_consent,
        })

    def append_provider(
        self,
        plan: dict,
        *,
        result: str = "POSITIVE",
        target_module: str = "contact_coverage",
        contact_overrides: dict | None = None,
        receipt_overrides: dict | None = None,
        evidence_overrides: dict | None = None,
        pivot_specs: list[tuple[str, str, str]] | None = None,
        consume: list[dict] | None = None,
    ) -> dict:
        self.provider_counter += 1
        planned = plan["calls"][0]
        receipt_id = f"PR-{self.provider_counter:03d}"
        now = datetime.now(timezone.utc) + timedelta(seconds=self.provider_counter)
        completed = now + timedelta(seconds=2)
        raw_hash = sha(f"provider:{receipt_id}:{planned['provider']}")
        normalized_result = result.upper()
        evidence_id = f"PE-{self.provider_counter:03d}"
        evidence = []
        evidence_ids = []
        contacts = []
        if normalized_result == "POSITIVE":
            evidence_ids = [evidence_id]
            evidence_item = {
                "evidence_id": evidence_id,
                "owner_type": "ACCOUNT",
                "owner_id": "ACCT-SYNTH-001",
                "claim_key": "contact.email.provider_current",
                "module_or_branch": target_module,
                "source_type": planned["provider_class"],
                "source_family": planned["provider"],
                "reference_type": "PROVIDER_RECEIPT",
                "url": "",
                "locator": f"provider-receipt://synthetic/{receipt_id}/evidence",
                "observed_at": completed.isoformat(),
                "content_sha256": raw_hash,
                "snapshot_locator": f"provider-receipt://synthetic/{receipt_id}/evidence",
                "claim_type": "PROVIDER_ASSERTION",
                "freshness": "CURRENT",
                "evidence_grade": "A2",
                "boundary": "Synthetic provider test result; public-source coverage remains mandatory.",
                "conflict": "",
            }
            if evidence_overrides:
                evidence_item.update(evidence_overrides)
            evidence = [evidence_item]
            contact = {
                "contact_id": f"PC-{self.provider_counter:03d}",
                "kind": "EMAIL",
                "value": "verified@synth-buyer.example",
                "owner_entity_id": "ACCT-SYNTH-001",
                "masked": False,
                "guessed": False,
                "provider_verified": True,
                "route_eligible": True,
                "evidence_id": evidence_id,
                "channel_proof": False,
            }
            if contact_overrides:
                contact.update(contact_overrides)
            contacts = [contact]
        pivots = []
        pivot_ids = []
        for pivot_id, pivot_type, pivot_value in pivot_specs or []:
            pivot_ids.append(pivot_id)
            pivots.append({
                "pivot_id": pivot_id,
                "pivot_type": pivot_type,
                "pivot_value": pivot_value,
                "generated_by_attempt_id": f"PROVIDER::{receipt_id}",
                "generated_at": completed.isoformat(),
                "consumed_by_attempt_id": "",
                "consumed_at": "",
                "consumption_result": "",
                "status": "OPEN",
            })
        receipt = {
            "provider_receipt_id": receipt_id,
            "investigation_id": self.investigation_id,
            "account_id": "ACCT-SYNTH-001",
            "provider": planned["provider"],
            "provider_class": planned["provider_class"],
            "requested_capability": planned["requested_capability"],
            "target_module": target_module,
            "plan_id": plan["plan_id"],
            "planned_call_id": planned["planned_call_id"],
            "tool_name": planned["tool_name"],
            "tool_call_id": f"TOOL-CALL-{self.provider_counter:03d}",
            "query": "Synthetic Buyer One email enrichment",
            "requested_at": now.isoformat(),
            "completed_at": completed.isoformat(),
            "result": normalized_result,
            "result_count": 1 if normalized_result == "POSITIVE" else 0,
            "raw_result_locator": f"provider-receipt://synthetic/{receipt_id}/raw",
            "content_sha256": raw_hash,
            "evidence_ids": evidence_ids,
            "pivots_generated": pivot_ids,
            "contacts_returned": contacts,
            "companies_returned": [],
            "billing_or_credit_notice": "Synthetic free test; no credit consumed.",
            "blocked_reason": "Synthetic provider unavailable" if normalized_result == "BLOCKED" else "",
            "permissions": {"user_authorized": normalized_result != "BLOCKED", "scopes": ["read synthetic company and contact data"]},
            "freshness": "CURRENT",
            "conflicts": [],
            "status": "BLOCKED" if normalized_result == "BLOCKED" else "SUCCESS",
        }
        if receipt_overrides:
            receipt.update(receipt_overrides)
        return self.runtime.append_provider_receipt({
            "investigation_id": self.investigation_id,
            "receipt": receipt,
            "evidence": evidence,
            "pivots": pivots,
            "pivots_consumed": consume or [],
        })

    def append_crm_no_change(self) -> dict:
        self.crm_counter += 1
        workbook_hash = hashlib.sha256(self.crm_path.read_bytes()).hexdigest()
        audit_path = self.crm_path.with_name(f"crm-audit-{self.crm_counter:03d}.json")
        audit_path.write_text('{"synthetic":true,"status":"NO_CHANGE_VERIFIED"}\n', encoding="utf-8")
        audit_hash = hashlib.sha256(audit_path.read_bytes()).hexdigest()
        return self.runtime.append_crm_writeback_receipt({
            "investigation_id": self.investigation_id,
            "receipt": {
                "writeback_id": f"CRM-WB-{self.crm_counter:03d}",
                "investigation_id": self.investigation_id,
                "account_id": "ACCT-SYNTH-001",
                "transaction_id": f"CRM-TX-{self.crm_counter:03d}",
                "writer": "ARTIFACT_TOOL",
                "target_workbook_path": str(self.crm_path),
                "workbook_sha256_before": workbook_hash,
                "workbook_sha256_after": workbook_hash,
                "committed_at": datetime.now(timezone.utc).isoformat(),
                "status": "NO_CHANGE_VERIFIED",
                "atomic_commit": True,
                "sparse_patch": True,
                "history_guard_passed": True,
                "post_commit_reimport_verified": True,
                "unintended_diff_count": 0,
                "touched_sheets": [],
                "row_assertions": [],
                "cell_assertions": [],
                "previous_current_diff": [],
                "audit_artifact_locator": str(audit_path),
                "audit_artifact_sha256": audit_hash,
            },
        })

    def complete_account(
        self,
        *,
        email: str = "public@synth-buyer.example",
        expect_closed: bool = True,
        operational_positive: bool = True,
    ) -> tuple[dict, str]:
        route_evidence = ""
        for module in REQUIRED_MODULES:
            if module == "network_fission":
                continue
            for family in self.start["source_profile"][module]:
                if module == "contact_coverage" and family == "official_contact":
                    _, route_evidence, _ = self.add_attempt(
                        module,
                        family,
                        result="POSITIVE",
                        evidence_overrides={"claim_key": "contact.email.official_current"},
                    )
                elif module == "sales_crm_outreach_readiness" and operational_positive:
                    self.add_attempt(module, family, result="POSITIVE")
                else:
                    self.add_attempt(module, family)
        for branch in NETWORK_BRANCHES:
            for family in SOURCE_PROFILE_BY_BRANCH[branch]:
                self.add_attempt(branch, family)
        self.runtime.append_peer_receipt({
            "investigation_id": self.investigation_id,
            "receipt_type": "ANCHOR_EXPANSION",
            "anchor_id": "ACCT-SYNTH-001",
            "cycle_dedup_checked": True,
        })
        if operational_positive:
            self.append_crm_no_change()
        closure = self.runtime.evaluate_investigation_closure({"investigation_id": self.investigation_id})
        if expect_closed and not closure["closed"]:
            raise AssertionError(closure["blockers"])
        return closure, route_evidence

    def outreach_args(self, closure: dict, route_evidence: str, **overrides) -> dict:
        body = (
            "Dear Purchasing Team, I am Mark Zhou from Guangzhou XingHuai New Materials Co., Ltd. "
            "We manufacture PVC board materials for distributors and fabricators serving interior and display applications. "
            "I would like to understand whether your team currently evaluates additional manufacturing partners for future projects. "
            "We can first share a concise company introduction and relevant product overview for your review. "
            "Could you please advise who is the appropriate person to discuss material sourcing? "
            "Best regards, Mark Zhou, Guangzhou XingHuai New Materials Co., Ltd., Mobile / WhatsApp: +86 180 2710 1852, Website: www.xinghuai.com"
        )
        args = {
            "investigation_id": self.investigation_id,
            "closure_id": closure["closure_id"],
            "route": {
                "kind": "EMAIL",
                "value": "public@synth-buyer.example",
                "verified": True,
                "current": True,
                "owned_by_account": True,
                "owner_entity_id": "ACCT-SYNTH-001",
                "evidence_ids": [route_evidence],
            },
            "history_digest": self.start["history_digest"],
            "authority_digest": self.start["authority_digest"],
            "subject": "PVC Board Material Introduction",
            "body": body,
            "chinese_translation": "合成测试审核译文。",
            "stage": "FIRST_TOUCH",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat(),
        }
        for key, value in overrides.items():
            if key.startswith("route_"):
                args["route"][key[6:]] = value
            else:
                args[key] = value
        return args


class UnifiedRuntimeTests(unittest.TestCase):
    def harness(self, **kwargs) -> RuntimeHarness:
        temporary = tempfile.TemporaryDirectory(prefix="cbi_v5_test_")
        self.addCleanup(temporary.cleanup)
        return RuntimeHarness(Path(temporary.name), **kwargs)

    def assert_rejected(self, callback, contains: str = "") -> None:
        with self.assertRaises(ValidationError) as caught:
            callback()
        if contains:
            self.assertIn(contains, str(caught.exception))

    @staticmethod
    def information_record(h: RuntimeHarness, information_id: str, **overrides) -> dict:
        claim_key = f"information.{information_id}"
        payload = {
            "information_id": information_id,
            "investigation_id": h.investigation_id,
            "related_account_id": "ACCT-SYNTH-001",
            "subject_type": "ACCOUNT",
            "subject_owner_id": "ACCT-SYNTH-001",
            "relationship_to_account": "SELF",
            "information_type": "CONTACT",
            "claim_key": claim_key,
            "value": {"channel": "EMAIL", "value": "buyer@synth-buyer.example", "verified": True, "masked": False, "guessed": False},
            "source_type": "OFFICIAL_CONTACT",
            "source_reference_type": "PUBLIC_URL",
            "source_url": "https://synth-buyer.example/contact",
            "source_locator": f"snapshot://information/{information_id}",
            "observed_at": "2026-08-22T03:00:00Z",
            "content_sha256": sha(f"information:{information_id}"),
            "confidence": "HIGH",
            "temporal_status": "CURRENT",
            "route_scope": "BUYER_DIRECT",
            "outreach_eligible_claimed": True,
            "supersedes_information_ids": [],
            "conflicts_with_information_ids": [],
            "evidence_ids": [],
            "notes": "Synthetic information-retention test.",
        }
        payload.update(overrides)
        if payload["source_reference_type"] == "PUBLIC_URL" and payload["information_type"] in {"FACT", "CONTACT", "ROUTE", "PARTY_ROLE"}:
            _, evidence_id, _ = h.add_attempt(
                "contact_coverage",
                "official_contact",
                result="POSITIVE",
                evidence_overrides={"claim_key": payload["claim_key"]},
            )
            payload["evidence_ids"] = [evidence_id]
        return payload

    def test_01_default_profile_cannot_be_shrunk(self):
        h = self.harness()
        self.assertGreaterEqual(len(h.start["source_profile"]["contact_coverage"]), 21)
        self.assertTrue(set(CONTACT_SOURCE_PROFILE) <= set(h.start["source_profile"]["contact_coverage"]))

    def test_02_fast_scan_cannot_close(self):
        h = self.harness(mode="FAST_SCAN")
        result = h.runtime.evaluate_investigation_closure({"investigation_id": h.investigation_id})
        self.assertFalse(result["closed"])
        self.assertIn("FAST_SCAN_CANNOT_SIGN_RESEARCH_COMPLETE", result["blockers"])

    def test_03_first_email_does_not_end_research(self):
        h = self.harness()
        h.add_attempt("contact_coverage", "official_contact", result="POSITIVE")
        result = h.runtime.evaluate_investigation_closure({"investigation_id": h.investigation_id})
        self.assertFalse(result["closed"])
        self.assertTrue(result["modules"]["contact_coverage"]["missing"])

    def test_04_first_phone_does_not_end_research(self):
        h = self.harness()
        h.add_attempt("contact_coverage", "official_contact", result="POSITIVE", evidence_overrides={"claim_key": "contact.phone.current"})
        self.assertFalse(h.runtime.evaluate_investigation_closure({"investigation_id": h.investigation_id})["closed"])

    def test_05_first_manager_does_not_end_research(self):
        h = self.harness()
        h.add_attempt("buying_group", "linkedin_people", result="POSITIVE", evidence_overrides={"claim_key": "buying_group.manager"})
        self.assertFalse(h.runtime.evaluate_investigation_closure({"investigation_id": h.investigation_id})["closed"])

    def test_06_a_plus_priority_does_not_reduce_depth(self):
        h = self.harness(priority="A+")
        result = h.runtime.evaluate_investigation_closure({"investigation_id": h.investigation_id})
        self.assertFalse(result["closed"])
        self.assertEqual(len(result["modules"]["contact_coverage"]["required"]), len(CONTACT_SOURCE_PROFILE))

    def test_07_fixed_time_or_page_count_never_completes(self):
        h = self.harness()
        result = h.runtime.evaluate_investigation_closure({"investigation_id": h.investigation_id, "elapsed_seconds": 600, "pages_opened": 999})
        self.assertFalse(result["closed"])

    def test_08_not_checked_is_not_a_valid_attempt_result(self):
        h = self.harness()
        self.assert_rejected(lambda: h.add_attempt("contact_coverage", "official_home", result="NOT_CHECKED"), "attempt.result invalid")

    def test_09_positive_requires_raw_proof(self):
        h = self.harness()
        self.assert_rejected(lambda: h.add_attempt("contact_coverage", "official_home", result="POSITIVE", attempt_overrides={"raw_result_locator": ""}), "raw_result_locator")

    def test_10_negative_self_certification_is_rejected(self):
        h = self.harness()
        self.assert_rejected(lambda: h.add_attempt("contact_coverage", "official_home", attempt_overrides={"raw_result_locator": "AUDIT_QUERY:no result"}), "self-authored")

    def test_11_evidence_owner_mismatch_is_rejected(self):
        h = self.harness()
        self.assert_rejected(lambda: h.add_attempt("contact_coverage", "official_home", result="POSITIVE", evidence_overrides={"owner_id": "OTHER"}), "owner mismatch")

    def test_12_evidence_claim_is_mandatory(self):
        h = self.harness()
        self.assert_rejected(lambda: h.add_attempt("contact_coverage", "official_home", result="POSITIVE", evidence_overrides={"claim_key": ""}), "claim_key")

    def test_13_evidence_module_mismatch_is_rejected(self):
        h = self.harness()
        self.assert_rejected(lambda: h.add_attempt("contact_coverage", "official_home", result="POSITIVE", evidence_overrides={"module_or_branch": "company_profile"}), "module/branch mismatch")

    def test_14_evidence_source_type_mismatch_is_rejected(self):
        h = self.harness()
        self.assert_rejected(lambda: h.add_attempt("contact_coverage", "official_home", result="POSITIVE", evidence_overrides={"source_type": "trade_history"}), "incompatible source type")

    def test_15_pivot_cannot_self_consume(self):
        h = self.harness()
        attempt_id, _, _ = h.add_attempt("contact_coverage", "official_home", pivot_specs=[("PIV-1", "DOMAIN", "synth.example")])
        state = h.runtime._state(h.investigation_id)
        attempt = copy.deepcopy(state["attempts"][attempt_id])
        attempt["attempt_id"] = "ATT-SELF"
        attempt["execution_id"] = "EXEC-SELF"
        attempt["query"] = "synth.example"
        attempt["started_at"] = attempt["completed_at"]
        attempt["pivots_generated"] = []
        # Directly forge the same generator ID to exercise the exact guard.
        state["pivots"]["PIV-1"]["generated_by_attempt_id"] = "ATT-SELF"
        original = h.runtime._state
        h.runtime._state = lambda _: state
        self.addCleanup(setattr, h.runtime, "_state", original)
        self.assert_rejected(lambda: h.runtime.append_execution_receipt({"investigation_id": h.investigation_id, "attempt": attempt, "evidence": [], "pivots": [], "pivots_consumed": [{"pivot_id": "PIV-1", "consumption_result": "NO_RESULT"}]}), "cannot consume its own")

    def test_16_pivot_requires_later_query_bound_consumption(self):
        h = self.harness()
        h.add_attempt("contact_coverage", "official_home", pivot_specs=[("PIV-2", "DOMAIN", "synth.example")])
        self.assert_rejected(lambda: h.add_attempt("contact_coverage", "official_home", query="unrelated query", consume=[{"pivot_id": "PIV-2", "consumption_result": "NO_RESULT"}]), "does not contain Pivot value")

    def test_17_open_pivot_prevents_closure(self):
        h = self.harness()
        h.add_attempt("contact_coverage", "official_home", pivot_specs=[("PIV-OPEN", "ALIAS", "Synthetic Alias")])
        result = h.runtime.evaluate_investigation_closure({"investigation_id": h.investigation_id})
        self.assertIn("PIV-OPEN", result["open_pivots"])

    def test_18_login_wall_cannot_be_not_applicable(self):
        h = self.harness()
        self.assert_rejected(lambda: h.add_attempt("contact_coverage", "linkedin_people", result="NOT_APPLICABLE", blocked_reason="United States: login wall 403"), "cannot be marked NOT_APPLICABLE")

    def test_19_blocked_source_prevents_closure(self):
        h = self.harness()
        h.add_attempt("contact_coverage", "official_home", result="BLOCKED", blocked_reason="403 anti-bot")
        result = h.runtime.evaluate_investigation_closure({"investigation_id": h.investigation_id})
        self.assertEqual(result["modules"]["contact_coverage"]["status"], "INCOMPLETE_BLOCKED")

    def _discovered_peer_harness(self, **kwargs) -> tuple[RuntimeHarness, str, str]:
        h = self.harness(**kwargs)
        aid, eid, _ = h.add_attempt(
            "regional_peer", "maps_region", result="POSITIVE", discovered_peers=["PEER-SYNTH-1"],
            relationship_bindings={"PEER-SYNTH-1": ["E-ATT-0001"]},
            evidence_overrides={"claim_key": "network.regional_peer.relationship"},
        )
        return h, aid, eid or ""

    def _peer_section(self, attempt_id: str, evidence_id: str | None) -> dict:
        return {"passed": True, "attempt_ids": [attempt_id], "evidence_ids": [evidence_id] if evidence_id else []}

    def test_20_peer_requires_independent_contact_coverage(self):
        h, discovery_id, relationship_eid = self._discovered_peer_harness()
        entity_a, entity_e, _ = h.add_attempt("buyer_entity_resolution", "government_registry", owner_id="PEER-SYNTH-1", result="POSITIVE")
        product_a, product_e, _ = h.add_attempt("product_identity_boundary", "hs_authority", owner_id="PEER-SYNTH-1", result="POSITIVE")
        trade_a, trade_e, _ = h.add_attempt("trade_supplier_continuity", "trade_history", owner_id="PEER-SYNTH-1", result="POSITIVE")
        company_a, company_e, _ = h.add_attempt("company_profile", "official_home", owner_id="PEER-SYNTH-1", result="POSITIVE")
        contact_a, _, _ = h.add_attempt("contact_coverage", "official_home", owner_id="PEER-SYNTH-1")
        receipt = {
            "peer_id": "PEER-SYNTH-1", "canonical_key": "synthetic-peer-one-us", "discovered_by_attempt_id": discovery_id,
            "branch": "regional_peer", "inherited_anchor_facts": False, "canonical_dedup_checked": True,
            "entity": self._peer_section(entity_a, entity_e), "product": self._peer_section(product_a, product_e),
            "trade_business": self._peer_section(trade_a, trade_e),
            "relationship": {"passed": True, "evidence_ids": [relationship_eid]},
            "company_profile": self._peer_section(company_a, company_e),
            "contact_coverage": self._peer_section(contact_a, None),
            "promotion_decision": "DO_NOT_PROMOTE", "promotion_reason": "Synthetic no-promotion decision",
        }
        self.assert_rejected(lambda: h.runtime.append_peer_receipt({"investigation_id": h.investigation_id, "receipt_type": "PEER_VALIDATION", "receipt": receipt}), "contact_coverage")

    def test_21_branch_relationship_must_come_from_discovery_attempt(self):
        h, discovery_id, _ = self._discovered_peer_harness()
        receipt = {
            "peer_id": "PEER-SYNTH-1", "canonical_key": "synthetic-peer-one-us", "discovered_by_attempt_id": discovery_id,
            "branch": "regional_peer", "inherited_anchor_facts": False, "canonical_dedup_checked": True,
            "entity": {}, "product": {}, "trade_business": {}, "relationship": {"passed": True, "evidence_ids": ["E-FUTURE"]},
            "company_profile": {}, "contact_coverage": {}, "promotion_decision": "DO_NOT_PROMOTE", "promotion_reason": "Synthetic",
        }
        self.assert_rejected(lambda: h.runtime.append_peer_receipt({"investigation_id": h.investigation_id, "receipt_type": "PEER_VALIDATION", "receipt": receipt}), "did not come from")

    def test_22_anchor_queue_cannot_be_skipped(self):
        h = self.harness()
        result = h.runtime.evaluate_investigation_closure({"investigation_id": h.investigation_id})
        self.assertIn("ACCT-SYNTH-001", result["anchor_queue"])

    def test_23_full_negative_and_positive_coverage_can_close(self):
        h = self.harness()
        closure, route_evidence = h.complete_account()
        self.assertTrue(closure["closed"])
        self.assertEqual(closure["status"], "COMPLETE_POSITIVE")
        self.assertTrue(route_evidence)

    def test_24_incomplete_research_cannot_prepare_action(self):
        h = self.harness()
        result = h.runtime.prepare_outreach({
            "investigation_id": h.investigation_id, "closure_id": "CLOS-fake", "route": {},
            "history_digest": h.start["history_digest"], "authority_digest": h.start["authority_digest"],
            "subject": "Hello", "body": "Hello", "stage": "FIRST_TOUCH", "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        })
        self.assertEqual(result["status"], "DRAFT_BLOCKED")
        self.assertIn("INVALID_CLOSURE_ID", result["block_reasons"])

    def test_25_masked_email_is_not_a_route(self):
        h = self.harness(); closure, eid = h.complete_account()
        result = h.runtime.prepare_outreach(h.outreach_args(closure, eid, route_value="pu***@synth-buyer.example"))
        self.assertIn("INVALID_EMAIL_ROUTE", result["block_reasons"])

    def test_26_phone_cannot_auto_promote_to_whatsapp(self):
        h = self.harness(); closure, eid = h.complete_account()
        result = h.runtime.prepare_outreach(h.outreach_args(closure, eid, route_kind="WHATSAPP", route_value="+15551234567"))
        self.assertIn("PHONE_CANNOT_AUTO_PROMOTE_TO_WHATSAPP", result["block_reasons"])

    def test_27_third_party_route_cannot_be_buyer_direct(self):
        h = self.harness(); closure, eid = h.complete_account()
        result = h.runtime.prepare_outreach(h.outreach_args(closure, eid, route_owner_entity_id="SUPPLIER-1", route_owned_by_account=False))
        self.assertIn("ROUTE_NOT_CURRENT_VERIFIED_ACCOUNT_OWNED", result["block_reasons"])

    def test_28_history_digest_and_stage_regression_block(self):
        h = self.harness(); closure, eid = h.complete_account()
        result = h.runtime.prepare_outreach(h.outreach_args(closure, eid, history_digest="0" * 64, stage="FIRST_TOUCH"))
        self.assertIn("HISTORY_DIGEST_MISMATCH", result["block_reasons"])

    def test_29_concrete_claim_scan_catches_omission(self):
        h = self.harness(); closure, eid = h.complete_account()
        body = h.outreach_args(closure, eid)["body"] + " Our certified waterproof performance is guaranteed."
        result = h.runtime.prepare_outreach(h.outreach_args(closure, eid, body=body))
        self.assertTrue(any(item.startswith("UNAUTHORIZED_CONCRETE_") for item in result["block_reasons"]))

    def test_30_two_urls_in_body_are_blocked(self):
        h = self.harness(); closure, eid = h.complete_account()
        body = h.outreach_args(closure, eid)["body"] + " https://one.example https://two.example"
        result = h.runtime.prepare_outreach(h.outreach_args(closure, eid, body=body))
        self.assertIn("FIRST_TOUCH_MULTIPLE_URLS", result["block_reasons"])

    def test_31_subject_mutation_and_render_replay_are_blocked(self):
        h = self.harness(); closure, eid = h.complete_account()
        prepared = h.runtime.prepare_outreach(h.outreach_args(closure, eid))
        self.assertTrue(prepared["prepared"])
        mutated = h.runtime.render_outreach_action_card({
            "investigation_id": h.investigation_id, "prepared_id": prepared["prepared_id"],
            "render_token": prepared["render_token"], "subject": "Changed subject",
        })
        self.assertEqual(mutated["terminal_state"], "DRAFT_BLOCKED")
        rendered = h.runtime.render_outreach_action_card({"investigation_id": h.investigation_id, "prepared_id": prepared["prepared_id"], "render_token": prepared["render_token"]})
        self.assertEqual(rendered["terminal_state"], "SENDABLE_DRAFT")
        replay = h.runtime.render_outreach_action_card({"investigation_id": h.investigation_id, "prepared_id": prepared["prepared_id"], "render_token": prepared["render_token"]})
        self.assertIn("RENDER_TOKEN_REPLAY", replay["block_reasons"])

    def test_32_closure_token_cannot_be_reused(self):
        h = self.harness(); closure, eid = h.complete_account()
        first = h.runtime.prepare_outreach(h.outreach_args(closure, eid))
        self.assertTrue(first["prepared"])
        second = h.runtime.prepare_outreach(h.outreach_args(closure, eid, stage="FOLLOW_UP"))
        self.assertIn("CLOSURE_TOKEN_REPLAY", second["block_reasons"])

    def test_33_append_only_chain_detects_tampering(self):
        h = self.harness()
        h.add_attempt("contact_coverage", "official_home")
        path = Path(h.start["session_log"])
        lines = path.read_text(encoding="utf-8").splitlines()
        lines[-1] = lines[-1].replace("NEGATIVE", "POSITIVE")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.assert_rejected(lambda: h.runtime.evaluate_investigation_closure({"investigation_id": h.investigation_id}), "hash mismatch")

    def test_34_promoted_peer_must_reexpand_all_six_branches(self):
        h, discovery_id, relationship_eid = self._discovered_peer_harness(
            network_policy={"max_anchor_depth": 0, "max_promoted_anchors": 0}
        )
        entity_a, entity_e, _ = h.add_attempt("buyer_entity_resolution", "government_registry", owner_id="PEER-SYNTH-1", result="POSITIVE")
        product_a, product_e, _ = h.add_attempt("product_identity_boundary", "hs_authority", owner_id="PEER-SYNTH-1", result="POSITIVE")
        trade_a, trade_e, _ = h.add_attempt("trade_supplier_continuity", "trade_history", owner_id="PEER-SYNTH-1", result="POSITIVE")
        company_a, company_e, _ = h.add_attempt("company_profile", "official_home", owner_id="PEER-SYNTH-1", result="POSITIVE")
        contact_attempts = []
        for family in h.start["source_profile"]["contact_coverage"]:
            attempt_id, _, _ = h.add_attempt("contact_coverage", family, owner_id="PEER-SYNTH-1")
            contact_attempts.append(attempt_id)
        receipt = {
            "peer_id": "PEER-SYNTH-1", "canonical_key": "synthetic-peer-one-us", "discovered_by_attempt_id": discovery_id,
            "branch": "regional_peer", "inherited_anchor_facts": False, "canonical_dedup_checked": True,
            "entity": self._peer_section(entity_a, entity_e), "product": self._peer_section(product_a, product_e),
            "trade_business": self._peer_section(trade_a, trade_e),
            "relationship": {"passed": True, "evidence_ids": [relationship_eid]},
            "company_profile": self._peer_section(company_a, company_e),
            "contact_coverage": {"passed": True, "attempt_ids": contact_attempts, "evidence_ids": []},
            "promotion_decision": "PROMOTE", "promotion_reason": "Synthetic promotion requires a new six-branch cycle",
            "target_fit_grade": "A",
            "promotion_evidence_grade": "B",
            "commercial_novelty": True,
            "canonical_status": "NEW",
        }
        legacy_promotion = copy.deepcopy(receipt)
        for field in ("target_fit_grade", "promotion_evidence_grade", "commercial_novelty", "canonical_status"):
            legacy_promotion.pop(field)
        self.assert_rejected(
            lambda: h.runtime.append_peer_receipt({
                "investigation_id": h.investigation_id,
                "receipt_type": "PEER_VALIDATION",
                "receipt": legacy_promotion,
            }),
            "receipt promotion gate: missing fields",
        )
        low_fit = copy.deepcopy(receipt)
        low_fit["target_fit_grade"] = "B+"
        self.assert_rejected(
            lambda: h.runtime.append_peer_receipt({
                "investigation_id": h.investigation_id,
                "receipt_type": "PEER_VALIDATION",
                "receipt": low_fit,
            }),
            "target fit below network policy",
        )
        accepted = h.runtime.append_peer_receipt({"investigation_id": h.investigation_id, "receipt_type": "PEER_VALIDATION", "receipt": receipt})
        self.assertEqual(accepted["promotion_decision"], "PROMOTE")
        self.assertFalse(accepted.get("fixed_depth_or_anchor_cap_applied", False))
        closure = h.runtime.evaluate_investigation_closure({"investigation_id": h.investigation_id})
        self.assertIn("PEER-SYNTH-1", closure["anchor_queue"])
        self.assertIn("PROMOTED_PEER_NOT_REEXPANDED:PEER-SYNTH-1", closure["blockers"])

    def test_35_public_only_cannot_plan_provider_use(self):
        h = self.harness()
        plan = h.plan_provider()
        self.assertEqual(plan["status"], "PROVIDER_USE_DISABLED")
        self.assertFalse(plan["external_execution_required"])

    def test_36_connected_optional_provider_plan_is_exact_and_auditable(self):
        h = self.harness(provider_policy={
            "mode": "CONNECTED_PROVIDERS_OPTIONAL",
            "allowed_providers": ["Synthetic Enrichment"],
            "required_capabilities": [],
            "cost_consent": False,
        })
        plan = h.plan_provider()
        self.assertEqual(plan["status"], "READY")
        self.assertEqual(len(plan["calls"]), 1)
        self.assertFalse(plan["runtime_invokes_other_plugins"])
        self.assertEqual(plan["calls"][0]["tool_name"], "synthetic_provider_search")

    def test_37_not_connected_provider_is_reported_not_fabricated(self):
        h = self.harness(provider_policy={
            "mode": "CONNECTED_PROVIDERS_OPTIONAL",
            "allowed_providers": ["Synthetic Enrichment"],
            "cost_consent": False,
        })
        plan = h.plan_provider(status="INSTALLED_NOT_CONNECTED")
        self.assertEqual(plan["status"], "BLOCKED")
        self.assertFalse(plan["calls"])
        self.assertTrue(any("PROVIDER_NOT_CONNECTED" in item for item in plan["blocked"]))

    def test_38_paid_credit_requires_double_consent(self):
        h = self.harness(provider_policy={
            "mode": "CONNECTED_PROVIDERS_OPTIONAL",
            "allowed_providers": ["Synthetic Enrichment"],
            "cost_consent": False,
        })
        plan = h.plan_provider(requires_paid_credit=True, cost_consent=True)
        self.assertFalse(plan["calls"])
        self.assertTrue(any("PAID_CREDIT_CONSENT_REQUIRED" in item for item in plan["blocked"]))

    def test_39_provider_result_never_replaces_public_source_coverage(self):
        h = self.harness(provider_policy={
            "mode": "CONNECTED_PROVIDERS_OPTIONAL",
            "allowed_providers": ["Synthetic Enrichment"],
            "cost_consent": False,
        })
        plan = h.plan_provider()
        appended = h.append_provider(plan)
        self.assertFalse(appended["closes_public_source_families"])
        closure = h.runtime.evaluate_investigation_closure({"investigation_id": h.investigation_id})
        self.assertFalse(closure["closed"])
        self.assertIn("official_home", closure["modules"]["contact_coverage"]["missing"])
        self.assertEqual(closure["provider_lanes"]["receipt_count"], 1)

    def test_40_required_provider_capability_is_fail_closed_until_receipted(self):
        h = self.harness(provider_policy={
            "mode": "CONNECTED_PROVIDERS_REQUIRED",
            "allowed_providers": ["Synthetic Enrichment"],
            "required_capabilities": ["email_enrichment"],
            "cost_consent": False,
        })
        closure, _ = h.complete_account(expect_closed=False)
        self.assertFalse(closure["closed"])
        self.assertIn("PROVIDER_CAPABILITY:email_enrichment:PENDING", closure["blockers"])
        plan = h.plan_provider()
        h.append_provider(plan)
        closed = h.runtime.evaluate_investigation_closure({"investigation_id": h.investigation_id})
        self.assertTrue(closed["closed"])
        self.assertEqual(closed["provider_lanes"]["status"], "COMPLETE")

    def test_41_unplanned_or_mismatched_provider_call_is_rejected(self):
        h = self.harness(provider_policy={
            "mode": "CONNECTED_PROVIDERS_OPTIONAL",
            "allowed_providers": ["Synthetic Enrichment"],
            "cost_consent": False,
        })
        plan = h.plan_provider()
        self.assert_rejected(
            lambda: h.append_provider(plan, receipt_overrides={"tool_name": "invented_unplanned_tool"}),
            "exact planned call",
        )

    def test_42_provider_owner_mismatch_is_rejected(self):
        h = self.harness(provider_policy={
            "mode": "CONNECTED_PROVIDERS_OPTIONAL",
            "allowed_providers": ["Synthetic Enrichment"],
            "cost_consent": False,
        })
        plan = h.plan_provider()
        self.assert_rejected(lambda: h.append_provider(plan, receipt_overrides={"account_id": "OTHER"}), "owner mismatch")

    def test_43_masked_provider_contact_cannot_be_route_eligible(self):
        h = self.harness(provider_policy={
            "mode": "CONNECTED_PROVIDERS_OPTIONAL",
            "allowed_providers": ["Synthetic Enrichment"],
            "cost_consent": False,
        })
        plan = h.plan_provider()
        self.assert_rejected(
            lambda: h.append_provider(plan, contact_overrides={"value": "pu***@synth-buyer.example", "masked": True}),
            "cannot become a Route",
        )

    def test_44_provider_phone_cannot_auto_promote_to_whatsapp(self):
        h = self.harness(provider_policy={
            "mode": "CONNECTED_PROVIDERS_OPTIONAL",
            "allowed_providers": ["Synthetic Enrichment"],
            "cost_consent": False,
        })
        plan = h.plan_provider()
        self.assert_rejected(
            lambda: h.append_provider(plan, contact_overrides={"kind": "WHATSAPP", "value": "+15551234567", "channel_proof": False}),
            "cannot auto-promote",
        )

    def test_45_provider_pivot_enters_global_exhaustion_queue(self):
        h = self.harness(provider_policy={
            "mode": "CONNECTED_PROVIDERS_OPTIONAL",
            "allowed_providers": ["Synthetic Enrichment"],
            "cost_consent": False,
        })
        plan = h.plan_provider()
        h.append_provider(plan, pivot_specs=[("PIV-PROVIDER-1", "PERSON", "Synthetic Director")])
        closure = h.runtime.evaluate_investigation_closure({"investigation_id": h.investigation_id})
        self.assertIn("PIV-PROVIDER-1", closure["open_pivots"])

    def test_46_logistics_provider_cannot_supply_decision_maker_evidence(self):
        h = self.harness(provider_policy={
            "mode": "CONNECTED_PROVIDERS_OPTIONAL",
            "allowed_providers": ["Synthetic Logistics"],
            "cost_consent": False,
        })
        plan = h.plan_provider(
            provider="Synthetic Logistics",
            provider_class="LOGISTICS_TRACKING",
            capability="logistics_tracking",
        )
        self.assert_rejected(lambda: h.append_provider(plan, target_module="buying_group"), "cannot supply Evidence")

    def test_47_blocked_required_provider_reports_incomplete_blocked(self):
        h = self.harness(provider_policy={
            "mode": "CONNECTED_PROVIDERS_REQUIRED",
            "allowed_providers": ["Synthetic Enrichment"],
            "required_capabilities": ["email_enrichment"],
            "cost_consent": False,
        })
        plan = h.plan_provider()
        h.append_provider(plan, result="BLOCKED")
        closure = h.runtime.evaluate_investigation_closure({"investigation_id": h.investigation_id})
        self.assertEqual(closure["provider_lanes"]["status"], "INCOMPLETE_BLOCKED")
        self.assertEqual(closure["status"], "INCOMPLETE_BLOCKED")

    def test_48_planned_provider_call_cannot_be_receipted_twice(self):
        h = self.harness(provider_policy={
            "mode": "CONNECTED_PROVIDERS_OPTIONAL",
            "allowed_providers": ["Synthetic Enrichment"],
            "cost_consent": False,
        })
        plan = h.plan_provider()
        h.append_provider(plan, result="NEGATIVE")
        self.assert_rejected(lambda: h.append_provider(plan, result="NEGATIVE"), "already receipted")

    def test_49_unplanned_provider_permission_scope_is_rejected(self):
        h = self.harness(provider_policy={
            "mode": "CONNECTED_PROVIDERS_OPTIONAL",
            "allowed_providers": ["Synthetic Enrichment"],
            "cost_consent": False,
        })
        plan = h.plan_provider()
        self.assert_rejected(
            lambda: h.append_provider(plan, receipt_overrides={"permissions": {"user_authorized": True, "scopes": ["export entire database"]}}),
            "unplanned permission scope",
        )

    def test_50_historical_cross_owner_contact_is_retained_not_discarded(self):
        h = self.harness()
        record = self.information_record(
            h,
            "INFO-HIST-001",
            subject_type="SUPPLIER",
            subject_owner_id="SUPPLIER-SYNTH-001",
            relationship_to_account="SUPPLIER_OF_ACCOUNT",
            temporal_status="HISTORICAL",
            route_scope="SUPPLIER_REFERRAL",
            source_url="",
            source_type="LEGACY_CRM",
            source_reference_type="LEGACY_CRM",
            source_locator="legacy-crm://synthetic/history/1",
        )
        result = h.runtime.append_information_record({"investigation_id": h.investigation_id, "record": record})
        self.assertTrue(result["accepted"])
        self.assertFalse(result["effective_outreach_eligible"])
        self.assertIn("SUBJECT_OWNER_IS_NOT_THE_BUYER_ACCOUNT", result["usage_warnings"])
        self.assertEqual(result["historical_records_preserved"], 1)

    def test_51_supplier_route_claim_is_downgraded_without_losing_record(self):
        h = self.harness()
        record = self.information_record(
            h,
            "INFO-SUPPLIER-001",
            subject_type="SUPPLIER",
            subject_owner_id="SUPPLIER-SYNTH-001",
            relationship_to_account="SUPPLIER_OF_ACCOUNT",
            route_scope="SUPPLIER_REFERRAL",
        )
        result = h.runtime.append_information_record({"investigation_id": h.investigation_id, "record": record})
        history = h.runtime.get_information_history({"investigation_id": h.investigation_id})
        self.assertTrue(result["accepted"])
        self.assertFalse(result["effective_outreach_eligible"])
        self.assertEqual(history["summary"]["total_records"], 1)
        self.assertEqual(history["records"][0]["subject_owner_id"], "SUPPLIER-SYNTH-001")

    def test_52_verified_current_buyer_direct_route_remains_eligible(self):
        h = self.harness()
        record = self.information_record(h, "INFO-DIRECT-001")
        result = h.runtime.append_information_record({"investigation_id": h.investigation_id, "record": record})
        self.assertTrue(result["effective_outreach_eligible"])
        self.assertEqual(result["usage_warnings"], [])

    def test_53_new_record_supersedes_but_does_not_delete_history(self):
        h = self.harness()
        old = self.information_record(
            h,
            "INFO-OLD-001",
            value={"channel": "EMAIL", "value": "old@synth-buyer.example", "verified": True},
            temporal_status="HISTORICAL",
            outreach_eligible_claimed=False,
            source_type="LEGACY_CRM",
            source_reference_type="LEGACY_CRM",
            source_url="",
            source_locator="legacy-crm://synthetic/contact/old",
        )
        h.runtime.append_information_record({"investigation_id": h.investigation_id, "record": old})
        new = self.information_record(h, "INFO-NEW-001", supersedes_information_ids=["INFO-OLD-001"])
        h.runtime.append_information_record({"investigation_id": h.investigation_id, "record": new})
        history = h.runtime.get_information_history({"investigation_id": h.investigation_id})
        self.assertEqual(history["summary"]["total_records"], 2)
        self.assertEqual(history["summary"]["superseded_but_preserved"], 1)
        self.assertEqual({item["information_id"] for item in history["records"]}, {"INFO-OLD-001", "INFO-NEW-001"})
        self.assertEqual([item["information_id"] for item in history["merged_current_view"]], ["INFO-NEW-001"])

    def test_54_conflicting_records_coexist(self):
        h = self.harness()
        first = self.information_record(h, "INFO-CONFLICT-A", information_type="FACT", route_scope="NOT_A_ROUTE", outreach_eligible_claimed=False)
        h.runtime.append_information_record({"investigation_id": h.investigation_id, "record": first})
        second = self.information_record(
            h,
            "INFO-CONFLICT-B",
            information_type="CONFLICT",
            route_scope="NOT_A_ROUTE",
            outreach_eligible_claimed=False,
            conflicts_with_information_ids=["INFO-CONFLICT-A"],
        )
        h.runtime.append_information_record({"investigation_id": h.investigation_id, "record": second})
        history = h.runtime.get_information_history({"investigation_id": h.investigation_id})
        self.assertEqual(history["summary"]["total_records"], 2)
        self.assertEqual(history["summary"]["conflict_records"], 1)

    def test_55_duplicate_information_id_is_rejected_append_only(self):
        h = self.harness()
        record = self.information_record(h, "INFO-DUP-001")
        h.runtime.append_information_record({"investigation_id": h.investigation_id, "record": record})
        self.assert_rejected(
            lambda: h.runtime.append_information_record({"investigation_id": h.investigation_id, "record": record}),
            "duplicate information_id",
        )

    def test_56_isolated_surrogates_are_rejected_before_hash_and_persistence(self):
        temporary = tempfile.TemporaryDirectory(prefix="cbi_unicode_guard_")
        self.addCleanup(temporary.cleanup)
        runtime = UnifiedRuntime(Path(temporary.name))
        self.assert_rejected(
            lambda: runtime.start_investigation({
                "account": {
                    "account_id": "UNICODE-SYNTH-001",
                    "country": "Việt Nam",
                    "name": "Synthetic Buyer\udcb6 Việt Nam 📦",
                },
                "input": {"note": "中文\ud800/tiếng Việt/emoji ✅"},
                "mode": "EXHAUSTIVE",
                "history": {"events": []},
            }),
            "INVALID_UNICODE_SURROGATE",
        )
        self.assertEqual(list(Path(temporary.name).glob("INV-*.jsonl")), [])

    def test_57_surrogate_guard_applies_to_later_append_tools(self):
        h = self.harness()
        record = self.information_record(
            h,
            "INFO-UNICODE-001",
            notes="Decision maker\udfff / 中文 / Việt Nam / 📞",
        )
        self.assert_rejected(
            lambda: h.runtime.append_information_record({"investigation_id": h.investigation_id, "record": record}),
            "INVALID_UNICODE_SURROGATE",
        )
        history = h.runtime.get_information_history({"investigation_id": h.investigation_id})
        self.assertEqual(history["records"], [])

    def test_58_public_evidence_requires_concrete_url(self):
        h = self.harness()
        self.assert_rejected(
            lambda: h.add_attempt(
                "contact_coverage",
                "official_contact",
                result="POSITIVE",
                evidence_overrides={"reference_type": "PUBLIC_URL", "url": ""},
            ),
            "PUBLIC_URL requires a concrete",
        )

    def test_59_non_public_reference_rejects_fabricated_url(self):
        h = self.harness()
        self.assert_rejected(
            lambda: h.add_attempt(
                "customs_integrity",
                "user_customs_record",
                result="POSITIVE",
                evidence_overrides={
                    "reference_type": "USER_INPUT",
                    "url": "https://fabricated.example/not-real",
                    "locator": "user-input://synthetic/customs/1",
                },
            ),
            "must not carry a fabricated URL",
        )

    def test_60_evidence_grade_freshness_and_claim_type_are_enums(self):
        h = self.harness()
        for overrides, fragment in (
            ({"evidence_grade": "VERY_GOOD"}, "evidence_grade invalid"),
            ({"freshness": "SUPER_FRESH"}, "evidence freshness invalid"),
            ({"claim_type": "WHATEVER"}, "evidence claim_type invalid"),
        ):
            self.assert_rejected(
                lambda overrides=overrides: h.add_attempt(
                    "contact_coverage", "official_contact", result="POSITIVE", evidence_overrides=overrides
                ),
                fragment,
            )

    def test_61_public_information_requires_existing_claim_bound_evidence(self):
        h = self.harness()
        record = self.information_record(h, "INFO-PUBLIC-NO-EVIDENCE")
        record["evidence_ids"] = []
        self.assert_rejected(
            lambda: h.runtime.append_information_record({"investigation_id": h.investigation_id, "record": record}),
            "public positive information requires",
        )

    def test_62_information_claim_key_must_match_evidence(self):
        h = self.harness()
        record = self.information_record(h, "INFO-CLAIM-MISMATCH")
        record["claim_key"] = "different.claim"
        self.assert_rejected(
            lambda: h.runtime.append_information_record({"investigation_id": h.investigation_id, "record": record}),
            "Evidence claim_key mismatch",
        )

    def test_63_public_source_planner_does_not_fabricate_execution(self):
        h = self.harness()
        before = len(h.runtime.store.read(h.investigation_id))
        plan = h.runtime.plan_public_source_calls({"investigation_id": h.investigation_id, "limit": 12})
        after = len(h.runtime.store.read(h.investigation_id))
        self.assertEqual(before, after)
        self.assertFalse(plan["runtime_executed_public_search"])
        self.assertTrue(plan["host_execution_required"])
        self.assertTrue(all(item["search_execution_performed"] is False for item in plan["calls"]))

    def test_64_structured_crm_commit_validates_actual_workbook_and_diff(self):
        h = self.harness()
        before_hash = hashlib.sha256(h.crm_path.read_bytes()).hexdigest()
        write_synthetic_workbook(h.crm_path, marker="after-commit")
        after_hash = hashlib.sha256(h.crm_path.read_bytes()).hexdigest()
        audit_path = h.crm_path.with_name("crm-commit-audit.json")
        audit_path.write_text('{"synthetic":true,"transaction":"CRM-TX-COMMIT-001"}\n', encoding="utf-8")
        audit_hash = hashlib.sha256(audit_path.read_bytes()).hexdigest()
        receipt = {
            "writeback_id": "CRM-WB-COMMIT-001",
            "investigation_id": h.investigation_id,
            "account_id": "ACCT-SYNTH-001",
            "transaction_id": "CRM-TX-COMMIT-001",
            "writer": "ARTIFACT_TOOL",
            "target_workbook_path": str(h.crm_path),
            "workbook_sha256_before": before_hash,
            "workbook_sha256_after": after_hash,
            "committed_at": datetime.now(timezone.utc).isoformat(),
            "status": "COMMITTED",
            "atomic_commit": True,
            "sparse_patch": True,
            "history_guard_passed": True,
            "post_commit_reimport_verified": True,
            "unintended_diff_count": 0,
            "touched_sheets": ["Evidence Ledger"],
            "row_assertions": [{"sheet": "Evidence Ledger", "record_key": "E-SYNTH-001", "exists": True}],
            "cell_assertions": [{"sheet": "Evidence Ledger", "cell": "A2", "expected": "E-SYNTH-001"}],
            "previous_current_diff": [{"sheet": "Evidence Ledger", "record_key": "E-SYNTH-001", "column": "Status", "previous": "PENDING", "current": "VERIFIED"}],
            "audit_artifact_locator": str(audit_path),
            "audit_artifact_sha256": audit_hash,
        }
        result = h.runtime.append_crm_writeback_receipt({"investigation_id": h.investigation_id, "receipt": receipt})
        self.assertTrue(result["crm_sync_complete"])
        self.assertEqual(result["workbook_sha256_after"], after_hash)

    def test_65_crm_receipt_rejects_wrong_writer_and_hash(self):
        h = self.harness()
        workbook_hash = hashlib.sha256(h.crm_path.read_bytes()).hexdigest()
        audit_path = h.crm_path.with_name("crm-invalid-audit.json")
        audit_path.write_text('{"synthetic":true}\n', encoding="utf-8")
        audit_hash = hashlib.sha256(audit_path.read_bytes()).hexdigest()
        receipt = {
            "writeback_id": "CRM-WB-BAD-001", "investigation_id": h.investigation_id,
            "account_id": "ACCT-SYNTH-001", "transaction_id": "CRM-TX-BAD-001",
            "writer": "UNVERIFIED_WRITER", "target_workbook_path": str(h.crm_path),
            "workbook_sha256_before": workbook_hash, "workbook_sha256_after": "0" * 64,
            "committed_at": datetime.now(timezone.utc).isoformat(), "status": "NO_CHANGE_VERIFIED",
            "atomic_commit": True, "sparse_patch": True, "history_guard_passed": True,
            "post_commit_reimport_verified": True, "unintended_diff_count": 0,
            "touched_sheets": [], "row_assertions": [], "cell_assertions": [], "previous_current_diff": [],
            "audit_artifact_locator": str(audit_path), "audit_artifact_sha256": audit_hash,
        }
        self.assert_rejected(
            lambda: h.runtime.append_crm_writeback_receipt({"investigation_id": h.investigation_id, "receipt": receipt}),
            "writer must be ARTIFACT_TOOL",
        )

    def test_66_missing_commercial_gates_cap_grade_at_b_plus(self):
        h = self.harness()
        result = h.runtime.evaluate_commercial_readiness({"investigation_id": h.investigation_id})
        self.assertFalse(result["commercial_result_ready"])
        self.assertFalse(result["may_enter_a_or_above"])
        self.assertEqual(result["maximum_allowed_grade"], "B+")
        self.assertEqual(result["status_counts"], {"PASS": 0, "MISSING": 10, "CONFLICT": 0})
        self.assertEqual(result["runtime_assigned_sales_grade"], None)

    def test_67_commercial_tag_must_match_module_and_claim(self):
        h = self.harness()
        self.assert_rejected(
            lambda: h.add_attempt(
                "contact_coverage",
                "official_home",
                result="POSITIVE",
                evidence_overrides={
                    "claim_type": "CUSTOMS",
                    "commercial_gate_tags": ["CUSTOMS_IMPORT_FACT"],
                },
            ),
            "incompatible with module contact_coverage",
        )

    def test_68_conflicted_commercial_evidence_never_passes_gate(self):
        h = self.harness()
        h.add_attempt(
            "customs_integrity",
            "user_customs_record",
            result="POSITIVE",
            evidence_overrides={
                "claim_type": "CUSTOMS",
                "commercial_gate_tags": ["CUSTOMS_IMPORT_FACT"],
                "conflict": "Importer identity remains disputed.",
            },
        )
        result = h.runtime.evaluate_commercial_readiness({"investigation_id": h.investigation_id})
        customs_gate = next(item for item in result["gates"] if item["gate"] == "CUSTOMS_IMPORT_FACT")
        self.assertEqual(customs_gate["status"], "CONFLICT")
        self.assertFalse(result["may_enter_a_or_above"])
        self.assertEqual(result["maximum_allowed_grade"], "B+")

    def test_69_ten_commercial_gates_allow_but_do_not_assign_a_grade(self):
        h = self.harness()
        h.add_attempt(
            "customs_integrity",
            "user_customs_record",
            result="POSITIVE",
            evidence_overrides={
                "claim_key": "commercial.customs.import_fact",
                "claim_type": "CUSTOMS",
                "commercial_gate_tags": ["CUSTOMS_IMPORT_FACT"],
            },
        )
        h.add_attempt(
            "product_identity_boundary",
            "official_product_material",
            result="POSITIVE",
            evidence_overrides={
                "claim_key": "commercial.product.pvc_relationship",
                "claim_type": "PRODUCT",
                "commercial_gate_tags": ["PRODUCT_MATCH", "PVC_BUSINESS_RELATIONSHIP"],
            },
        )
        h.add_attempt(
            "buyer_entity_resolution",
            "government_registry",
            result="POSITIVE",
            evidence_overrides={
                "claim_key": "commercial.legal.existence",
                "claim_type": "LEGAL_STATUS",
                "commercial_gate_tags": ["LEGAL_EXISTENCE"],
            },
        )
        h.add_attempt(
            "company_profile",
            "official_home",
            result="POSITIVE",
            evidence_overrides={
                "claim_key": "commercial.official.presence",
                "claim_type": "BUSINESS_PROFILE",
                "commercial_gate_tags": ["OFFICIAL_PRESENCE"],
            },
        )
        _, contact_evidence, _ = h.add_attempt(
            "contact_coverage",
            "official_contact",
            result="POSITIVE",
            evidence_overrides={
                "claim_key": "commercial.contact.official_route",
                "claim_type": "CONTACT",
                "commercial_gate_tags": ["OFFICIAL_CONTACT", "CONTACT_SOURCE", "DEVELOPMENT_ROUTE"],
            },
        )
        contact_record = self.information_record(
            h,
            "INFO-COMMERCIAL-CONTACT",
            claim_key="commercial.contact.official_route",
        )
        contact_record["evidence_ids"] = [contact_evidence]
        h.runtime.append_information_record({"investigation_id": h.investigation_id, "record": contact_record})

        _, decision_evidence, _ = h.add_attempt(
            "buying_group",
            "official_team",
            result="POSITIVE",
            evidence_overrides={
                "claim_key": "commercial.decision_chain.procurement",
                "claim_type": "AUTHORITY",
                "commercial_gate_tags": ["DECISION_CHAIN"],
            },
        )
        decision_record = self.information_record(
            h,
            "INFO-COMMERCIAL-PERSON",
            subject_type="PERSON",
            subject_owner_id="PERSON-SYNTH-001",
            relationship_to_account="CURRENT PROCUREMENT MANAGER",
            information_type="FACT",
            claim_key="commercial.decision_chain.procurement",
            value={"name": "Synthetic Person", "title": "Procurement Manager"},
            route_scope="IDENTITY_ONLY",
            outreach_eligible_claimed=False,
        )
        decision_record["evidence_ids"] = [decision_evidence]
        h.runtime.append_information_record({"investigation_id": h.investigation_id, "record": decision_record})
        h.append_crm_no_change()

        result = h.runtime.evaluate_commercial_readiness({"investigation_id": h.investigation_id})
        self.assertTrue(result["commercial_result_ready"])
        self.assertTrue(result["may_enter_a_or_above"])
        self.assertEqual(result["maximum_allowed_grade"], "A+")
        self.assertEqual(result["status_counts"], {"PASS": 10, "MISSING": 0, "CONFLICT": 0})
        self.assertIsNone(result["runtime_assigned_sales_grade"])
        research = h.runtime.evaluate_investigation_closure({"investigation_id": h.investigation_id})
        self.assertFalse(research["closed"], "commercial A-readiness must remain independent from exhaustive research closure")


if __name__ == "__main__":
    unittest.main(verbosity=2)
