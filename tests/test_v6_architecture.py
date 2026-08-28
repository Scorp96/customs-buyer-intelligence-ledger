from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from unified_runtime import CBI_MCP_TOOL_NAMES, UnifiedRuntime, ValidationError
from unified_runtime.v6 import DEFAULT_CLAIM_CATALOG, NETWORK_BRANCHES_V6


class V6ArchitectureTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v6-test-")
        self.addCleanup(self.temp.cleanup)
        self.session_root = Path(self.temp.name) / "sessions"
        self.host_root = Path(self.temp.name) / "host-pending"
        self.previous_host_root = os.environ.get("CBI_HOST_PENDING_ROOT")
        os.environ["CBI_HOST_PENDING_ROOT"] = str(self.host_root)
        self.addCleanup(self._restore_environment)
        self.runtime = UnifiedRuntime(self.session_root)
        self.start = self.runtime.start_investigation({
            "account": {"account_id": "C-V6-SYNTH", "country": "Synthetic", "name": "Synthetic Buyer"},
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "priority_grade": "A",
        })
        self.investigation_id = self.start["investigation_id"]

    def _restore_environment(self) -> None:
        if self.previous_host_root is None:
            os.environ.pop("CBI_HOST_PENDING_ROOT", None)
        else:
            os.environ["CBI_HOST_PENDING_ROOT"] = self.previous_host_root

    def observation(
        self,
        claim_key: str,
        *,
        result: str = "POSITIVE",
        suffix: str = "1",
        owner_type: str = "ACCOUNT",
        owner_id: str = "C-V6-SYNTH",
        value: object | None = None,
        pivots: list[dict] | None = None,
        extra: dict | None = None,
    ) -> dict:
        row = {
            "claim_key": claim_key,
            "result": result,
            "owner_type": owner_type,
            "owner_id": owner_id,
            "value": value if value is not None else {"fixture": suffix},
            "source": {
                "source_family": "synthetic_official",
                "source_type": "OFFICIAL",
                "reference_type": "PUBLIC_URL",
                "url": f"https://example.invalid/v6/{suffix}",
                "locator": f"https://example.invalid/v6/{suffix}#record",
                "raw_excerpt": f"Synthetic fixture evidence {suffix}",
                "authority_level": "A1_OFFICIAL_PRIMARY",
                "freshness": "CURRENT",
                "observed_at": "2026-08-28T00:00:00Z",
            },
            "boundary": "Synthetic test fixture only; no live-company fact is asserted.",
            "pivots": pivots or [],
        }
        if extra:
            row.update(extra)
        return row

    def compile(self, rows: list[dict], bundle_id: str = "") -> dict:
        bundle = {"observations": rows}
        if bundle_id:
            bundle["bundle_id"] = bundle_id
        return self.runtime.compile_and_append_research_bundle({
            "investigation_id": self.investigation_id,
            "bundle": bundle,
        })

    def test_contract_and_tool_surface(self) -> None:
        contract = self.runtime.get_runtime_contract({})
        self.assertEqual(contract["runtime_version"], "6.1.0")
        self.assertEqual(len(CBI_MCP_TOOL_NAMES), 42)
        self.assertEqual(contract["claim_driven_research"]["closure_strategy"], "DECISION_SATURATION")
        self.assertFalse(contract["claim_driven_research"]["source_profile_is_mandatory_checklist"])
        self.assertFalse(contract["commercial_dimensions"]["contact_or_crm_caps_commercial_value"])
        self.assertFalse(contract["peer_policy_v6"]["contact_coverage_required_for_anchor_eligibility"])

    def test_bundle_partial_success_and_idempotent_replay(self) -> None:
        valid = self.observation("identity.legal_entity", suffix="partial-good")
        invalid = self.observation("product.fit", suffix="partial-bad")
        invalid["source"]["locator"] = "AUDIT_QUERY:self proof"
        result = self.compile([valid, invalid], "BUNDLE-PARTIAL-V6")
        self.assertEqual(result["status"], "PARTIAL_SUCCESS")
        self.assertEqual((result["accepted_count"], result["rejected_count"]), (1, 1))
        replay = self.runtime.compile_and_append_research_bundle({
            "investigation_id": self.investigation_id,
            "bundle": {"bundle_id": "BUNDLE-PARTIAL-V6", "observations": [valid, invalid]},
        })
        self.assertTrue(replay["idempotent_replay"])
        self.assertEqual(len(self.runtime._v6_state(self.investigation_id)["observations"]), 1)

    def test_first_positive_never_closes_unresolved_critical_claims(self) -> None:
        self.compile([self.observation("identity.legal_entity")])
        saturation = self.runtime.evaluate_decision_saturation({"investigation_id": self.investigation_id})
        self.assertFalse(saturation["decision_saturated"])
        self.assertIn("product.fit", saturation["unresolved_critical_claims"])

    def test_negative_exhausted_requires_real_independent_strategies(self) -> None:
        row = self.observation("contact.named_route", result="NEGATIVE_EXHAUSTED", suffix="negative")
        rejected = self.compile([row])
        self.assertEqual(rejected["status"], "REJECTED")
        row["search_exhaustion"] = {
            "exhausted": True,
            "independent_queries": ["official team and contact", "named role plus company domain"],
            "independent_attempts": [
                {
                    "query_or_navigation": "official team and contact",
                    "raw_result_locator": "https://example.invalid/v6/negative?query=official",
                    "content_sha256": hashlib.sha256(b"negative official fixture").hexdigest(),
                },
                {
                    "query_or_navigation": "named role plus company domain",
                    "raw_result_locator": "https://example.invalid/v6/negative?query=named",
                    "content_sha256": hashlib.sha256(b"negative named fixture").hexdigest(),
                },
            ],
        }
        accepted = self.compile([row], "BUNDLE-NEGATIVE-EXHAUSTED")
        self.assertEqual(accepted["status"], "ACCEPTED")
        claim = self.runtime.get_claims({"investigation_id": self.investigation_id})["claims"]["contact.named_route"]
        self.assertEqual(claim["state"], "NEGATIVE_EXHAUSTED")

    def test_commercial_value_is_not_capped_by_contact_or_crm(self) -> None:
        rows = []
        for index, (claim_key, config) in enumerate(DEFAULT_CLAIM_CATALOG.items()):
            if config["commercial_weight"] > 0:
                independent = self.observation(claim_key, suffix=f"commercial-{index}-b")
                independent["source"]["url"] = f"https://independent.invalid/commercial/{index}"
                independent["source"]["locator"] = f"https://independent.invalid/commercial/{index}#fact"
                rows.extend([
                    self.observation(claim_key, suffix=f"commercial-{index}-a"),
                    independent,
                ])
        self.compile(rows, "BUNDLE-COMMERCIAL-VALUE")
        value = self.runtime.evaluate_commercial_value({"investigation_id": self.investigation_id})
        account = self.runtime.get_account_state({"investigation_id": self.investigation_id})
        self.assertEqual(value["commercial_value_grade"], "A+")
        self.assertEqual(account["crm_state"]["status"], "NOT_SYNCED")
        self.assertIn(account["outreach_readiness"]["outreach_readiness"], {"BLOCKED", "IDENTITY_ONLY"})
        self.assertFalse(value["contact_or_crm_caps_grade"])

    def test_claim_conflict_is_preserved(self) -> None:
        rows = [
            self.observation("company.operating_status", suffix="conflict-positive"),
            self.observation("company.operating_status", result="REFUTED", suffix="conflict-refute"),
        ]
        self.compile(rows)
        claim = self.runtime.get_claims({"investigation_id": self.investigation_id})["claims"]["company.operating_status"]
        self.assertEqual(claim["state"], "CONFLICTED")
        self.assertEqual(len(claim["observation_ids"]), 2)

    def test_full_claim_resolution_issues_closure_and_one_time_draft_only(self) -> None:
        rows = []
        for index, claim_key in enumerate(DEFAULT_CLAIM_CATALOG):
            value: object = {"fixture": claim_key}
            if claim_key == "contact.named_route":
                value = {
                    "channel": "EMAIL",
                    "value": "buyer@example.invalid",
                    "person_name": "Synthetic Decision Maker",
                    "verified": True,
                    "current": True,
                    "owned_by_account": True,
                    "masked": False,
                    "guessed": False,
                }
            elif claim_key == "contact.company_route":
                value = {
                    "channel": "EMAIL",
                    "value": "info@example.invalid",
                    "verified": True,
                    "current": True,
                    "owned_by_account": True,
                    "masked": False,
                    "guessed": False,
                }
            rows.append(self.observation(claim_key, suffix=f"closure-{index}", value=value))
        compiled = self.compile(rows, "BUNDLE-FULL-CLOSURE")
        named = next(row for row in compiled["outcomes"] if row["index"] == list(DEFAULT_CLAIM_CATALOG).index("contact.named_route"))
        saturation = self.runtime.evaluate_decision_saturation({"investigation_id": self.investigation_id})
        self.assertTrue(saturation["decision_saturated"])
        closure = self.runtime.evaluate_investigation_closure({"investigation_id": self.investigation_id})
        self.assertTrue(closure["closed"])
        self.assertFalse(closure["state_dimensions"]["crm_sync_complete"])
        prepared = self.runtime.prepare_outreach({
            "investigation_id": self.investigation_id,
            "closure_id": closure["closure_id"],
            "route": {
                "kind": "EMAIL",
                "value": "buyer@example.invalid",
                "verified": True,
                "current": True,
                "owned_by_account": True,
                "owner_entity_id": "C-V6-SYNTH",
                "evidence_ids": [named["evidence_id"]],
            },
            "history_digest": self.start["history_digest"],
            "authority_digest": self.start["authority_digest"],
            "subject": "Synthetic product discussion",
            "body": (
                "Hello, I am reaching out because your public company profile suggests a possible fit with our product range. "
                "We support buyers who need consistent specifications, practical order planning, and clear production communication. "
                "If this category is relevant to your current sourcing work, I can share a concise overview for your review. "
                "Please let me know which product requirements or applications matter most, and I will tailor the information accordingly. "
                "There is no obligation, and this message is only an invitation to compare potential options when convenient for you."
            ),
            "stage": "FIRST_TOUCH",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        })
        self.assertEqual(prepared["status"], "PREPARED_FOR_RENDER")
        rendered = self.runtime.render_outreach_action_card({
            "investigation_id": self.investigation_id,
            "prepared_id": prepared["prepared_id"],
            "render_token": prepared["render_token"],
        })
        self.assertEqual(rendered["terminal_state"], "SENDABLE_DRAFT")
        self.assertFalse(rendered["action"]["sends_message"])
        replay = self.runtime.render_outreach_action_card({
            "investigation_id": self.investigation_id,
            "prepared_id": prepared["prepared_id"],
            "render_token": prepared["render_token"],
        })
        self.assertEqual(replay["terminal_state"], "DRAFT_BLOCKED")

    def test_peer_anchor_eligibility_does_not_require_contact(self) -> None:
        compiled = self.compile([self.observation(
            "relationship.supply_chain",
            suffix="peer-rel",
            extra={"network_branch": "INDUSTRY_PEERS"},
        )])
        outcome = compiled["outcomes"][0]
        peer = self.runtime.append_peer_discovery({
            "investigation_id": self.investigation_id,
            "peer": {
                "name": "Synthetic Peer",
                "country": "Synthetic",
                "network_branch": "INDUSTRY_PEERS",
                "discovered_by_observation_id": outcome["observation_id"],
                "relationship_evidence_ids": [outcome["evidence_id"]],
            },
        })
        peer_facts = self.compile([
            self.observation(
                "identity.legal_entity",
                suffix="peer-entity",
                owner_type="PEER",
                owner_id=peer["peer_id"],
            ),
            self.observation(
                "product.fit",
                suffix="peer-product",
                owner_type="PEER",
                owner_id=peer["peer_id"],
            ),
            self.observation(
                "trade.import_activity",
                suffix="peer-trade",
                owner_type="PEER",
                owner_id=peer["peer_id"],
            ),
        ], "BUNDLE-PEER-FACTS")
        evaluated = self.runtime.evaluate_peer({
            "investigation_id": self.investigation_id,
            "peer_id": peer["peer_id"],
            "assessment": {
                "entity_verified": True,
                "product_fit_verified": True,
                "business_or_trade_verified": True,
                "relationship_verified": True,
                "commercial_novelty": True,
                "canonical_new": True,
                "fact_evidence_ids": {
                    "entity_verified": [peer_facts["outcomes"][0]["evidence_id"]],
                    "product_fit_verified": [peer_facts["outcomes"][1]["evidence_id"]],
                    "business_or_trade_verified": [peer_facts["outcomes"][2]["evidence_id"]],
                    "relationship_verified": [outcome["evidence_id"]],
                    "commercial_novelty": [
                        peer_facts["outcomes"][1]["evidence_id"],
                        peer_facts["outcomes"][2]["evidence_id"],
                    ],
                },
                "commercial_novelty_basis": (
                    "Independent Peer product and trade Evidence supports a distinct, commercially useful anchor decision."
                ),
            },
        })
        self.assertEqual(evaluated["stage"], "ANCHOR_ELIGIBLE")
        self.assertEqual(evaluated["contact_coverage"], {})
        promoted = self.runtime.promote_anchor({
            "investigation_id": self.investigation_id,
            "peer_id": peer["peer_id"],
            "promotion_reason": "Synthetic high-value relationship fixture.",
        })
        self.assertEqual(promoted["stage"], "PROMOTED_ANCHOR")
        saturation = self.runtime.evaluate_decision_saturation({"investigation_id": self.investigation_id})
        self.assertIn(peer["peer_id"], saturation["promoted_anchors_pending_full_audit"])
        branch_bundle = self.compile([
            self.observation(
                "relationship.supply_chain",
                suffix=f"peer-branch-{index}",
                owner_type="PEER",
                owner_id=peer["peer_id"],
                extra={"network_branch": branch},
            )
            for index, branch in enumerate(NETWORK_BRANCHES_V6)
        ], "BUNDLE-PEER-SIX-BRANCH")
        branch_states = {
            branch: {
                "status": "SATURATED",
                "decision_basis": "Synthetic Peer-owned branch Evidence was compiled for this test.",
                "evidence_ids": [branch_bundle["outcomes"][index]["evidence_id"]],
                "max_remaining_eiv": 0.0,
            }
            for index, branch in enumerate(NETWORK_BRANCHES_V6)
        }
        audited = self.runtime.evaluate_peer({
            "investigation_id": self.investigation_id,
            "peer_id": peer["peer_id"],
            "assessment": {
                "full_audit_complete": True,
                "network_branch_states": branch_states,
            },
        })
        self.assertEqual(audited["stage"], "FULLY_AUDITED")

    def test_material_pivot_requires_later_objective(self) -> None:
        self.compile([self.observation(
            "identity.legal_entity",
            suffix="pivot",
            pivots=[{"type": "ALIAS", "value": "Synthetic Alternate", "materiality": "MATERIAL", "estimated_eiv": 3.0}],
        )])
        pivot = self.runtime.get_material_pivots({"investigation_id": self.investigation_id})["material_pivots"][0]
        with self.assertRaises(ValidationError):
            self.runtime.close_pivot({
                "investigation_id": self.investigation_id,
                "pivot_id": pivot["pivot_id"],
                "status": "CONSUMED",
                "reason": "No later objective supplied.",
            })
        objective = self.runtime.submit_research_objective({
            "investigation_id": self.investigation_id,
            "objective": {
                "claim_key": "identity.legal_entity",
                "query_or_navigation": "Synthetic Alternate official registry",
                "source_family": "official_registry",
            },
        })
        closed = self.runtime.close_pivot({
            "investigation_id": self.investigation_id,
            "pivot_id": pivot["pivot_id"],
            "status": "CONSUMED",
            "reason": "Consumed by a later independent objective.",
            "consumed_by_objective_id": objective["objective_id"],
        })
        self.assertEqual(closed["status"], "CONSUMED")

    def test_budget_exhaustion_pauses_and_never_closes(self) -> None:
        second = UnifiedRuntime(Path(self.temp.name) / "budget-sessions")
        started = second.start_investigation({
            "account": {"account_id": "C-BUDGET-SYNTH", "country": "Synthetic", "name": "Budget Fixture"},
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "priority_grade": "NQ",
        })
        next_work = second.get_next_research_objectives({"investigation_id": started["investigation_id"]})
        saturation = second.evaluate_decision_saturation({"investigation_id": started["investigation_id"]})
        self.assertEqual(next_work["status"], "PAUSED_RESOURCE_LIMIT")
        self.assertEqual(saturation["status"], "PAUSED_RESOURCE_LIMIT")
        self.assertFalse(saturation["decision_saturated"])

    def test_host_queue_survives_runtime_recreation_and_syncs(self) -> None:
        payload = {
            "investigation_id": self.investigation_id,
            "bundle": {"bundle_id": "BUNDLE-HOST-QUEUE", "observations": [self.observation("product.fit", suffix="host-queue")]},
        }
        queued = self.runtime.queue_host_bundle({"payload": payload})
        self.assertTrue(queued["queued"])
        recreated = UnifiedRuntime(self.session_root)
        synced = recreated.sync_pending_bundles({"investigation_id": self.investigation_id})
        self.assertEqual(synced["counts"], {"SYNCED": 1})
        status = recreated.get_runtime_health({})["host_pending_bundles"]
        self.assertEqual(status["SYNCED"], 1)

    def test_credentials_are_never_persisted(self) -> None:
        row = self.observation("product.fit", suffix="credential")
        row["provider_api_key"] = "sk-syntheticshouldneverpersist12345"
        result = self.compile([row])
        self.assertEqual(result["status"], "REJECTED")
        session_text = self.runtime.store.path(self.investigation_id).read_text(encoding="utf-8")
        self.assertNotIn("sk-syntheticshouldneverpersist", session_text)

    def test_copy_migration_does_not_mutate_source(self) -> None:
        source_hash = hashlib.sha256(self.runtime.store.path(self.investigation_id).read_bytes()).hexdigest()
        target = Path(self.temp.name) / "migrated-v6"
        report = self.runtime.migrate_v5_4_1_to_v6({"target_root": str(target)})
        self.assertTrue(report["verified"])
        self.assertFalse(report["source_mutated"])
        self.assertFalse(report["switched"])
        self.assertEqual(source_hash, hashlib.sha256(self.runtime.store.path(self.investigation_id).read_bytes()).hexdigest())
        migrated_runtime = UnifiedRuntime(target / "sessions")
        self.assertEqual(migrated_runtime.get_investigation_health({"investigation_id": self.investigation_id})["status"], "READY")

    def test_concurrent_session_writers_preserve_hash_chain(self) -> None:
        def append(index: int) -> None:
            self.runtime.store.append(self.investigation_id, "V6_CONCURRENCY_PROBE", {"index": index})

        with ThreadPoolExecutor(max_workers=20) as pool:
            list(pool.map(append, range(100)))
        events = self.runtime.store.read(self.investigation_id)
        probes = [event for event in events if event["event_type"] == "V6_CONCURRENCY_PROBE"]
        self.assertEqual(len(probes), 100)

    def test_thousand_observation_load_and_deterministic_dedup(self) -> None:
        rows = [self.observation("product.fit", suffix=f"load-{index}") for index in range(1000)]
        result = self.compile(rows, "BUNDLE-LOAD-1000")
        self.assertEqual(result["status"], "ACCEPTED")
        self.assertEqual(result["accepted_count"], 1000)
        replay = self.runtime.compile_and_append_research_bundle({
            "investigation_id": self.investigation_id,
            "bundle": {"bundle_id": "BUNDLE-LOAD-1000", "observations": rows},
        })
        self.assertTrue(replay["idempotent_replay"])

    def test_golden_fixture_names_are_synthetic_metadata_only(self) -> None:
        fixture = Path(__file__).with_name("fixtures") / "v6_golden_accounts.json"
        rows = json.loads(fixture.read_text(encoding="utf-8"))
        self.assertEqual(len(rows), 8)
        self.assertTrue(all(row["fixture_role"].startswith("synthetic_") for row in rows))


if __name__ == "__main__":
    unittest.main()
