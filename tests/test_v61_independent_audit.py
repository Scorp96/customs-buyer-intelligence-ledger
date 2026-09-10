from __future__ import annotations

import hashlib
import math
import os
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

from unified_runtime import UnifiedRuntime, ValidationError
from unified_runtime.resilience import PendingReceiptJournal, exclusive_file_lock
from unified_runtime.v6 import DEFAULT_CLAIM_CATALOG


class V61IndependentAuditTests(unittest.TestCase):
    """Adversarial tests created independently of the v6 release tests."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="cbi-v61-independent-audit-")
        self.addCleanup(self.temp.cleanup)
        self.session_root = Path(self.temp.name) / "sessions"
        self.runtime = UnifiedRuntime(self.session_root)
        self.start = self.runtime.start_investigation({
            "account": {
                "account_id": "C-V61-AUDIT",
                "country": "Synthetic",
                "name": "Synthetic Audit Buyer",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "priority_grade": "A",
        })
        self.investigation_id = self.start["investigation_id"]

    def observation(
        self,
        claim_key: str,
        *,
        suffix: str,
        result: str = "POSITIVE",
        owner_type: str = "ACCOUNT",
        owner_id: str = "C-V61-AUDIT",
        value: object | None = None,
        network_branch: str = "",
        raw_content: str | None = None,
    ) -> dict:
        source: dict[str, object] = {
            "source_family": "synthetic_official",
            "source_type": "OFFICIAL",
            "reference_type": "PUBLIC_URL",
            "url": f"https://evidence.example.invalid/{suffix}",
            "locator": f"https://evidence.example.invalid/{suffix}#fact",
            "raw_excerpt": f"Independent audit fixture {suffix}",
            "authority_level": "A1_OFFICIAL_PRIMARY",
            "freshness": "CURRENT",
            "observed_at": "2026-08-28T00:00:00Z",
        }
        if raw_content is not None:
            source["raw_content"] = raw_content
        return {
            "claim_key": claim_key,
            "result": result,
            "owner_type": owner_type,
            "owner_id": owner_id,
            "value": value if value is not None else {"fixture": suffix},
            "network_branch": network_branch,
            "source": source,
            "boundary": "Synthetic independent-audit fixture only.",
        }

    def compile(self, rows: list[dict], bundle_id: str = "") -> dict:
        bundle: dict[str, object] = {"observations": rows}
        if bundle_id:
            bundle["bundle_id"] = bundle_id
        return self.runtime.compile_and_append_research_bundle({
            "investigation_id": self.investigation_id,
            "bundle": bundle,
        })

    def support_root_identity_for_promotion(self) -> None:
        result = self.compile([
            self.observation("identity.legal_entity", suffix="root-legal-entity-for-promotion", value={"legal_name": "Synthetic Audit Buyer"}),
            self.observation("identity.ultimate_buyer", suffix="root-ultimate-buyer-for-promotion", value={"ultimate_buyer": "Synthetic Audit Buyer"}),
        ], "BUNDLE-V64-ROOT-IDENTITY-FOR-PROMOTION")
        self.assertEqual(result["rejected_count"], 0)

    def resolve_every_claim(self) -> tuple[dict, dict]:
        rows: list[dict] = []
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
            rows.append(self.observation(claim_key, suffix=f"all-{index}", value=value))
        compiled = self.compile(rows, "BUNDLE-V61-ALL-CLAIMS")
        named_index = list(DEFAULT_CLAIM_CATALOG).index("contact.named_route")
        named = next(row for row in compiled["outcomes"] if row["index"] == named_index)
        closure = self.runtime.evaluate_investigation_closure({"investigation_id": self.investigation_id})
        self.assertTrue(closure["closed"])
        return named, closure

    def discover_peer_with_evidence(self) -> tuple[dict, dict[str, list[str]]]:
        discovery_bundle = self.compile([
            {
                **self.observation(
                    "relationship.supply_chain",
                    suffix="peer-discovery",
                    network_branch="INDUSTRY_PEERS",
                ),
                "relationship_to_account": "INDUSTRY_PEER",
            }
        ], "BUNDLE-V61-PEER-DISCOVERY")
        discovery = discovery_bundle["outcomes"][0]
        peer = self.runtime.append_peer_discovery({
            "investigation_id": self.investigation_id,
            "peer": {
                "name": "Synthetic Evidence Peer",
                "country": "Synthetic",
                "network_branch": "INDUSTRY_PEERS",
                "discovered_by_observation_id": discovery["observation_id"],
                "relationship_evidence_ids": [discovery["evidence_id"]],
            },
        })
        peer_rows = [
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
        ]
        peer_bundle = self.compile(peer_rows, "BUNDLE-V61-PEER-FACTS")
        evidence = {
            "entity_verified": [peer_bundle["outcomes"][0]["evidence_id"]],
            "product_fit_verified": [peer_bundle["outcomes"][1]["evidence_id"]],
            "business_or_trade_verified": [peer_bundle["outcomes"][2]["evidence_id"]],
            "relationship_verified": [discovery["evidence_id"]],
            "commercial_novelty": [
                peer_bundle["outcomes"][1]["evidence_id"],
                peer_bundle["outcomes"][2]["evidence_id"],
            ],
        }
        return peer, evidence

    def eligible_assessment(self, evidence: dict[str, list[str]]) -> dict:
        return {
            "entity_verified": True,
            "product_fit_verified": True,
            "business_or_trade_verified": True,
            "relationship_verified": True,
            "commercial_novelty": True,
            "canonical_new": True,
            "fact_evidence_ids": evidence,
            "commercial_novelty_basis": (
                "Independent product and trade evidence shows a commercially distinct candidate "
                "that is useful for a new anchor decision."
            ),
        }

    def test_declared_hash_must_match_raw_material(self) -> None:
        row = self.observation("product.fit", suffix="hash-mismatch", raw_content="actual bytes")
        row["source"]["content_sha256"] = hashlib.sha256(b"different bytes").hexdigest()
        result = self.compile([row])
        self.assertEqual(result["status"], "REJECTED")
        self.assertIn("does not match", result["outcomes"][0]["error"])

    def test_secret_query_parameters_and_nonfinite_numbers_are_rejected(self) -> None:
        secret = self.observation("product.fit", suffix="secret-url")
        secret["source"]["url"] = "https://evidence.example.invalid/fact?api_key=never-persist-this"
        secret["source"]["locator"] = secret["source"]["url"]
        secret_result = self.compile([secret])
        self.assertEqual(secret_result["status"], "REJECTED")

        nonfinite = self.observation("product.fit", suffix="nan")
        nonfinite["value"] = {"confidence": math.nan}
        nonfinite_result = self.compile([nonfinite])
        self.assertEqual(nonfinite_result["status"], "REJECTED")

        legitimate = self.observation("buying_group.decision_chain", suffix="secretary-role")
        legitimate["value"] = {"secretary_name": "Synthetic Public Role"}
        legitimate_result = self.compile([legitimate])
        self.assertEqual(legitimate_result["status"], "ACCEPTED")

    def test_peer_owned_observation_requires_prior_discovery(self) -> None:
        result = self.compile([
            self.observation(
                "identity.legal_entity",
                suffix="phantom-peer",
                owner_type="PEER",
                owner_id="PEER-NOT-DISCOVERED",
            )
        ])
        self.assertEqual(result["status"], "REJECTED")
        self.assertIn("discovered", result["outcomes"][0]["error"].casefold())

    def test_peer_cannot_be_promoted_by_bare_booleans(self) -> None:
        peer, _ = self.discover_peer_with_evidence()
        with self.assertRaises(ValidationError):
            self.runtime.evaluate_peer({
                "investigation_id": self.investigation_id,
                "peer_id": peer["peer_id"],
                "assessment": {
                    "entity_verified": True,
                    "product_fit_verified": True,
                    "business_or_trade_verified": True,
                    "relationship_verified": True,
                    "commercial_novelty": True,
                    "canonical_new": True,
                },
            })

    def test_peer_lifecycle_is_monotonic(self) -> None:
        peer, evidence = self.discover_peer_with_evidence()
        eligible = self.runtime.evaluate_peer({
            "investigation_id": self.investigation_id,
            "peer_id": peer["peer_id"],
            "assessment": self.eligible_assessment(evidence),
        })
        self.assertEqual(eligible["stage"], "ANCHOR_ELIGIBLE")
        self.support_root_identity_for_promotion()
        promoted = self.runtime.promote_anchor({
            "investigation_id": self.investigation_id,
            "peer_id": peer["peer_id"],
            "promotion_reason": "Independent audit promotion fixture.",
        })
        self.assertEqual(promoted["stage"], "PROMOTED_ANCHOR")
        reassessed = self.runtime.evaluate_peer({
            "investigation_id": self.investigation_id,
            "peer_id": peer["peer_id"],
            "assessment": {
                "entity_verified": False,
                "product_fit_verified": False,
                "business_or_trade_verified": False,
                "relationship_verified": False,
                "commercial_novelty": False,
            },
        })
        self.assertEqual(reassessed["stage"], "PROMOTED_ANCHOR")

    def test_same_controlling_website_is_not_two_independent_sources(self) -> None:
        result = self.compile([
            self.observation("product.fit", suffix="same-host-one"),
            self.observation("product.fit", suffix="same-host-two"),
        ])
        self.assertEqual(result["status"], "ACCEPTED")
        claim = self.runtime.get_claims({"investigation_id": self.investigation_id})["claims"]["product.fit"]
        self.assertEqual(claim["state"], "SUPPORTED")
        self.assertEqual(claim["independent_source_count"], 1)

    def test_subdomains_of_one_registrable_domain_are_not_independent(self) -> None:
        first = self.observation("product.fit", suffix="subdomain-one")
        second = self.observation("product.fit", suffix="subdomain-two")
        first["source"]["url"] = "https://catalog.company.example/product"
        first["source"]["locator"] = "https://catalog.company.example/product#fact"
        second["source"]["url"] = "https://news.company.example/product"
        second["source"]["locator"] = "https://news.company.example/product#fact"
        self.compile([first, second])
        claim = self.runtime.get_claims({"investigation_id": self.investigation_id})["claims"]["product.fit"]
        self.assertEqual(claim["state"], "SUPPORTED")
        self.assertEqual(claim["independent_source_count"], 1)

    def test_negative_exhaustion_strategies_must_bind_to_actual_attempt_queries(self) -> None:
        row = self.observation("contact.named_route", suffix="negative-binding", result="NEGATIVE_EXHAUSTED")
        row["search_exhaustion"] = {
            "exhausted": True,
            "independent_queries": ["official team page", "company domain role search"],
            "independent_attempts": [
                {
                    "query_or_navigation": "same repeated query",
                    "raw_result_locator": "https://evidence.example.invalid/negative/one",
                    "content_sha256": hashlib.sha256(b"one").hexdigest(),
                },
                {
                    "query_or_navigation": "same repeated query",
                    "raw_result_locator": "https://evidence.example.invalid/negative/two",
                    "content_sha256": hashlib.sha256(b"two").hexdigest(),
                },
            ],
        }
        result = self.compile([row])
        self.assertEqual(result["status"], "REJECTED")

    def test_critical_claim_cannot_be_not_applicable_and_blocked_is_not_na(self) -> None:
        critical = self.observation("identity.legal_entity", suffix="critical-na", result="NOT_APPLICABLE")
        critical["not_applicable_reason"] = "The operator declared this critical identity claim not applicable."
        result = self.compile([critical])
        self.assertEqual(result["status"], "REJECTED")

        blocked_as_na = self.observation("contact.named_route", suffix="blocked-na", result="NOT_APPLICABLE")
        blocked_as_na["not_applicable_reason"] = "The page returned HTTP 403 and required a login wall."
        result = self.compile([blocked_as_na])
        self.assertEqual(result["status"], "REJECTED")

    def test_material_pivot_cannot_be_dismissed_without_low_eiv_and_terminal_is_final(self) -> None:
        row = self.observation("identity.legal_entity", suffix="pivot-not-material")
        row["pivots"] = [{
            "type": "ALIAS",
            "value": "Synthetic Material Alias",
            "materiality": "MATERIAL",
            "estimated_eiv": 9.0,
        }]
        self.compile([row])
        pivot = self.runtime.get_material_pivots({"investigation_id": self.investigation_id})["material_pivots"][0]
        with self.assertRaises(ValidationError):
            self.runtime.close_pivot({
                "investigation_id": self.investigation_id,
                "pivot_id": pivot["pivot_id"],
                "status": "NOT_MATERIAL",
                "reason": "Dismissed without a measured remaining EIV.",
            })
        objective = self.runtime.submit_research_objective({
            "investigation_id": self.investigation_id,
            "objective": {
                "claim_key": "identity.legal_entity",
                "query_or_navigation": "Synthetic Material Alias official registry",
                "source_family": "official_registry",
            },
        })
        self.runtime.close_pivot({
            "investigation_id": self.investigation_id,
            "pivot_id": pivot["pivot_id"],
            "status": "CONSUMED",
            "reason": "Consumed by a later independent objective with this exact alias.",
            "consumed_by_objective_id": objective["objective_id"],
        })
        with self.assertRaises(ValidationError):
            self.runtime.close_pivot({
                "investigation_id": self.investigation_id,
                "pivot_id": pivot["pivot_id"],
                "status": "BLOCKED",
                "reason": "Attempted terminal-state regression.",
            })

    def test_unevaluated_discovered_peer_blocks_decision_saturation(self) -> None:
        self.resolve_every_claim()
        peer, _ = self.discover_peer_with_evidence()
        saturation = self.runtime.evaluate_decision_saturation({"investigation_id": self.investigation_id})
        self.assertFalse(saturation["decision_saturated"])
        self.assertIn(f"DISCOVERED_PEER_UNRESOLVED:{peer['peer_id']}", saturation["blockers"])

    def test_expired_unused_closure_is_never_reused(self) -> None:
        self.compile([
            self.observation(claim_key, suffix=f"expired-{index}")
            for index, claim_key in enumerate(DEFAULT_CLAIM_CATALOG)
        ], "BUNDLE-V61-EXPIRED-CLOSURE")
        basis_hash = self.runtime.store.read(self.investigation_id)[-1]["event_hash"]
        expired_id = "CLOS-00000000000000000000000000000000"
        self.runtime.store.append(self.investigation_id, "CLOSURE_ISSUED", {
            "schema": "cbi.closure.v6",
            "closure_id": expired_id,
            "investigation_id": self.investigation_id,
            "account_id": "C-V61-AUDIT",
            "status": "COMPLETE_POSITIVE",
            "issued_at": (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat(),
            "expires_at": (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat(),
            "basis_hash": basis_hash,
            "state_dimensions": {},
            "decision_saturation_sha256": "0" * 64,
            "used": False,
        })
        closure = self.runtime.evaluate_investigation_closure({"investigation_id": self.investigation_id})
        self.assertNotEqual(closure["closure_id"], expired_id)
        self.assertGreater(
            datetime.fromisoformat(closure["closure_expires_at"].replace("Z", "+00:00")),
            datetime.now(timezone.utc),
        )

    def test_schema_less_legacy_closure_is_history_not_v61_authority(self) -> None:
        self.compile([
            self.observation(claim_key, suffix=f"legacy-closure-{index}")
            for index, claim_key in enumerate(DEFAULT_CLAIM_CATALOG)
        ], "BUNDLE-V61-LEGACY-CLOSURE")
        legacy_id = "CLOS-11111111111111111111111111111111"
        self.runtime.store.append(self.investigation_id, "CLOSURE_ISSUED", {
            "closure_id": legacy_id,
            "investigation_id": self.investigation_id,
            "account_id": "C-V61-AUDIT",
            "status": "COMPLETE_POSITIVE",
            "issued_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": (datetime.now(timezone.utc) + timedelta(minutes=20)).isoformat(),
            "basis_hash": self.runtime.store.read(self.investigation_id)[-1]["event_hash"],
            "used": False,
        })
        closure = self.runtime.evaluate_investigation_closure({"investigation_id": self.investigation_id})
        self.assertTrue(closure["closed"])
        self.assertNotEqual(closure["closure_id"], legacy_id)

    def test_information_change_stales_a_closure(self) -> None:
        named, closure = self.resolve_every_claim()
        self.runtime.store.append(self.investigation_id, "INFORMATION_RECORD_APPENDED", {
            "record": {"information_id": "INFO-SYNTHETIC-AFTER-CLOSURE"},
        })
        body = (
            "Hello, I am reaching out because your public company profile suggests a possible fit with our product range. "
            "We support buyers who need consistent specifications, practical order planning, and clear production communication. "
            "If this category is relevant to your current sourcing work, I can share a concise overview for your review. "
            "Please let me know which product requirements or applications matter most, and I will tailor the information accordingly. "
            "There is no obligation, and this message is only an invitation to compare potential options when convenient for you."
        )
        prepared = self.runtime.prepare_outreach({
            "investigation_id": self.investigation_id,
            "closure_id": closure["closure_id"],
            "route": {
                "kind": "EMAIL",
                "value": "buyer@example.invalid",
                "verified": True,
                "current": True,
                "owned_by_account": True,
                "owner_entity_id": "C-V61-AUDIT",
                "evidence_ids": [named["evidence_id"]],
            },
            "history_digest": self.start["history_digest"],
            "authority_digest": self.start["authority_digest"],
            "subject": "Possible product fit discussion",
            "body": body,
            "stage": "FIRST_TOUCH",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        })
        self.assertEqual(prepared["status"], "DRAFT_BLOCKED")
        self.assertIn("CLOSURE_STALE_AFTER_NEW_RESEARCH", prepared["block_reasons"])

    def test_first_touch_rejects_short_body_and_unverified_concrete_claim(self) -> None:
        named, closure = self.resolve_every_claim()
        prepared = self.runtime.prepare_outreach({
            "investigation_id": self.investigation_id,
            "closure_id": closure["closure_id"],
            "route": {
                "kind": "EMAIL",
                "value": "buyer@example.invalid",
                "verified": True,
                "current": True,
                "owned_by_account": True,
                "owner_entity_id": "C-V61-AUDIT",
                "evidence_ids": [named["evidence_id"]],
            },
            "history_digest": self.start["history_digest"],
            "authority_digest": self.start["authority_digest"],
            "subject": "Material option",
            "body": "Our board density is 0.55 g/cm3 and it is certified for every application.",
            "stage": "FIRST_TOUCH",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        })
        self.assertEqual(prepared["status"], "DRAFT_BLOCKED")
        self.assertIn("FIRST_TOUCH_WORD_COUNT_OUTSIDE_80_110", prepared["block_reasons"])
        self.assertTrue(any(reason.startswith("UNAUTHORIZED_CONCRETE_") for reason in prepared["block_reasons"]))

    def test_guessed_route_and_negative_closure_cannot_prepare_outreach(self) -> None:
        rows: list[dict] = []
        for index, (claim_key, config) in enumerate(DEFAULT_CLAIM_CATALOG.items()):
            result = "REFUTED" if config["commercial_weight"] > 0 else "POSITIVE"
            value: object = {"fixture": claim_key}
            if claim_key == "contact.named_route":
                value = {
                    "channel": "EMAIL",
                    "value": "guessed@example.invalid",
                    "person_name": "Synthetic Guessed Person",
                    "verified": True,
                    "current": True,
                    "owned_by_account": True,
                    "masked": False,
                    "guessed": True,
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
            rows.append(self.observation(
                claim_key,
                suffix=f"negative-outreach-{index}",
                result=result,
                value=value,
            ))
        compiled = self.compile(rows, "BUNDLE-V61-NEGATIVE-OUTREACH")
        named_index = list(DEFAULT_CLAIM_CATALOG).index("contact.named_route")
        named = next(row for row in compiled["outcomes"] if row["index"] == named_index)
        closure = self.runtime.evaluate_investigation_closure({"investigation_id": self.investigation_id})
        self.assertEqual(closure["status"], "COMPLETE_NEGATIVE_ENTITLED")
        body = (
            "Hello, I am reaching out to ask whether this product category is relevant to your current sourcing work. "
            "Our team supports practical specification review, order planning, and clear production communication for international buyers. "
            "If you handle this area, I can share a concise overview for comparison. If another colleague is responsible, "
            "could you please point me to the right person? I will keep any follow-up brief and focused only on the requirements "
            "that matter to your team. Thank you for considering this simple introduction when convenient."
        )
        prepared = self.runtime.prepare_outreach({
            "investigation_id": self.investigation_id,
            "closure_id": closure["closure_id"],
            "route": {
                "kind": "EMAIL",
                "value": "guessed@example.invalid",
                "verified": True,
                "current": True,
                "owned_by_account": True,
                "owner_entity_id": "C-V61-AUDIT",
                "evidence_ids": [named["evidence_id"]],
            },
            "history_digest": self.start["history_digest"],
            "authority_digest": self.start["authority_digest"],
            "subject": "Product category question",
            "body": body,
            "stage": "FIRST_TOUCH",
            "expires_at": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        })
        self.assertEqual(prepared["status"], "DRAFT_BLOCKED")
        self.assertIn("NEGATIVE_CLOSURE_NOT_OUTREACH_ELIGIBLE", prepared["block_reasons"])
        self.assertIn("ROUTE_VALUE_OR_CHANNEL_NOT_BOUND_TO_EVIDENCE", prepared["block_reasons"])

    def test_empty_or_overlapping_migration_source_is_rejected(self) -> None:
        empty = Path(self.temp.name) / "empty-source"
        empty.mkdir()
        with self.assertRaises(ValidationError):
            self.runtime.migrate_v5_4_1_to_v6({
                "source_session_root": str(empty),
                "target_root": str(Path(self.temp.name) / "empty-target"),
            })
        with self.assertRaises(ValidationError):
            self.runtime.migrate_v5_4_1_to_v6({
                "source_session_root": str(self.session_root),
                "target_root": str(self.session_root / "nested-target"),
            })

    def test_migration_uses_canonical_data_owned_by_supplied_source_root(self) -> None:
        source_sessions = Path(self.temp.name) / "foreign-runtime" / "sessions"
        source_runtime = UnifiedRuntime(source_sessions)
        source_runtime.resolve_or_create_account({
            "candidate": {
                "country": "Synthetic",
                "name": "Foreign Source Canonical Buyer",
                "tax_id": "SYNTH-FOREIGN-001",
            },
            "requested_account_id": "C-FOREIGN-001",
        })
        foreign = source_runtime.start_investigation({
            "account": {
                "account_id": "C-FOREIGN-001",
                "country": "Synthetic",
                "name": "Foreign Source Canonical Buyer",
                "tax_id": "SYNTH-FOREIGN-001",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
        })
        target = Path(self.temp.name) / "foreign-migrated"
        report = self.runtime.migrate_v5_4_1_to_v6({
            "source_session_root": str(source_sessions),
            "target_root": str(target),
        })
        self.assertTrue(report["verified"])
        self.assertTrue(report["source_unchanged"])
        migrated = UnifiedRuntime(target / "sessions")
        account_ids = {row["account_id"] for row in migrated.canonical_registry.entries()}
        self.assertIn("C-FOREIGN-001", account_ids)
        self.assertEqual(
            migrated.get_investigation_health({"investigation_id": foreign["investigation_id"]})["status"],
            "READY",
        )

    def test_dead_process_lock_is_recovered(self) -> None:
        lock = Path(self.temp.name) / "dead-owner.lock"
        lock.write_text("pid=999999999 created=2020-01-01T00:00:00Z token=dead", encoding="utf-8")
        with exclusive_file_lock(lock, timeout_seconds=0.5):
            self.assertTrue(lock.exists())
        self.assertFalse(lock.exists())

    def test_live_process_lock_is_never_stolen(self) -> None:
        lock = Path(self.temp.name) / "live-owner.lock"
        lock.write_text(
            f"pid={os.getpid()} created=2026-08-28T00:00:00Z token=live",
            encoding="utf-8",
        )
        with self.assertRaises(ValidationError):
            with exclusive_file_lock(lock, timeout_seconds=0.2):
                pass
        self.assertTrue(lock.exists())

    def test_nonfinite_objective_and_oversized_observation_fail_closed(self) -> None:
        with self.assertRaises(ValidationError):
            self.runtime.submit_research_objective({
                "investigation_id": self.investigation_id,
                "objective": {
                    "claim_key": "product.fit",
                    "query_or_navigation": "Synthetic objective",
                    "source_family": "official_site",
                    "probability": math.inf,
                },
            })
        oversized = self.observation(
            "product.fit",
            suffix="oversized",
            raw_content="x" * (2 * 1024 * 1024 + 1),
        )
        result = self.compile([oversized], "BUNDLE-V61-OVERSIZED")
        self.assertEqual(result["status"], "REJECTED")
        self.assertIn("2 MiB", result["outcomes"][0]["error"])

    def test_pre_promotion_branch_evidence_cannot_close_promoted_anchor(self) -> None:
        from unified_runtime.v6 import NETWORK_BRANCHES_V6

        peer, evidence = self.discover_peer_with_evidence()
        eligible = self.runtime.evaluate_peer({
            "investigation_id": self.investigation_id,
            "peer_id": peer["peer_id"],
            "assessment": self.eligible_assessment(evidence),
        })
        self.assertEqual(eligible["stage"], "ANCHOR_ELIGIBLE")
        premature = self.compile([
            self.observation(
                "relationship.supply_chain",
                suffix=f"premature-{index}",
                owner_type="PEER",
                owner_id=peer["peer_id"],
                network_branch=branch,
            )
            for index, branch in enumerate(NETWORK_BRANCHES_V6)
        ], "BUNDLE-V61-PREMATURE-BRANCHES")
        self.support_root_identity_for_promotion()
        self.runtime.promote_anchor({
            "investigation_id": self.investigation_id,
            "peer_id": peer["peer_id"],
            "promotion_reason": "Synthetic lifecycle ordering test.",
        })
        with self.assertRaises(ValidationError):
            self.runtime.evaluate_peer({
                "investigation_id": self.investigation_id,
                "peer_id": peer["peer_id"],
                "assessment": {
                    "full_audit_complete": True,
                    "network_branch_states": {
                        branch: {
                            "status": "SATURATED",
                            "decision_basis": "This premature Evidence must not satisfy post-promotion work.",
                            "evidence_ids": [premature["outcomes"][index]["evidence_id"]],
                            "max_remaining_eiv": 0.0,
                        }
                        for index, branch in enumerate(NETWORK_BRANCHES_V6)
                    },
                },
            })

    def test_closure_issuance_fails_if_tail_changes_after_evaluation(self) -> None:
        self.compile([
            self.observation(claim_key, suffix=f"tail-race-{index}")
            for index, claim_key in enumerate(DEFAULT_CLAIM_CATALOG)
        ], "BUNDLE-V61-CLOSURE-RACE")
        original = self.runtime.store.append_if_tail

        def racing_append(
            investigation_id: str,
            expected_tail_hash: str,
            event_type: str,
            payload: dict,
        ) -> dict:
            self.runtime.store.append(investigation_id, "INFORMATION_RECORD_APPENDED", {
                "record": {"information_id": "INFO-CONCURRENT-CHANGE"},
            })
            return original(investigation_id, expected_tail_hash, event_type, payload)

        self.runtime.store.append_if_tail = racing_append  # type: ignore[method-assign]
        try:
            with self.assertRaises(ValidationError):
                self.runtime.evaluate_investigation_closure({"investigation_id": self.investigation_id})
        finally:
            self.runtime.store.append_if_tail = original  # type: ignore[method-assign]

    def test_concurrent_bundle_replay_is_exactly_once(self) -> None:
        row = self.observation(
            "product.fit",
            suffix="concurrent-bundle",
            raw_content="x" * 262_144,
        )
        payload = {
            "investigation_id": self.investigation_id,
            "bundle": {"bundle_id": "BUNDLE-V61-CONCURRENT", "observations": [row]},
        }
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda _: self.runtime.compile_and_append_research_bundle(payload), range(32)))
        self.assertTrue(all(result["status"] == "ACCEPTED" for result in results))
        events = self.runtime.store.read(self.investigation_id)
        observations = [event for event in events if event["event_type"] == "V6_OBSERVATION_COMPILED"]
        bundles = [
            event for event in events
            if event["event_type"] == "V6_RESEARCH_BUNDLE_COMPILED"
            and event["payload"].get("bundle_id") == "BUNDLE-V61-CONCURRENT"
        ]
        self.assertEqual(len(observations), 1)
        self.assertEqual(len(bundles), 1)

    def test_concurrent_identical_start_reuses_one_investigation(self) -> None:
        root = Path(self.temp.name) / "concurrent-start-sessions"
        runtime = UnifiedRuntime(root)
        arguments = {
            "account": {
                "account_id": "C-CONCURRENT-START",
                "country": "Synthetic",
                "name": "Concurrent Start Buyer",
            },
            "mode": "EXHAUSTIVE",
            "history": {"events": []},
            "idempotency_key": "CONCURRENT-START-FIXTURE-001",
        }
        with ThreadPoolExecutor(max_workers=16) as pool:
            results = list(pool.map(lambda _: runtime.start_investigation(arguments), range(32)))
        investigation_ids = {result["investigation_id"] for result in results}
        self.assertEqual(len(investigation_ids), 1)
        self.assertEqual(len(list(root.glob("INV-*.jsonl"))), 1)

    def test_concurrent_pending_receipt_sync_invokes_handler_once(self) -> None:
        journal = PendingReceiptJournal(Path(self.temp.name) / "pending-concurrency")
        journal.queue(
            "append_information_record",
            {
                "investigation_id": self.investigation_id,
                "record": {"information_id": "INFO-PENDING-CONCURRENT"},
            },
        )
        count = 0
        count_lock = threading.Lock()

        def handler(payload: dict) -> dict:
            nonlocal count
            with count_lock:
                count += 1
            time.sleep(0.05)
            return {"accepted": True, "information_id": payload["record"]["information_id"]}

        def sync_once(_: int) -> dict:
            return journal.sync({"append_information_record": handler})

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(sync_once, range(8)))
        self.assertEqual(count, 1)
        self.assertEqual(sum(result["counts"].get("SYNCED", 0) for result in results), 1)
        sync_events = [
            event for event in journal.events.read()
            if event["event_type"] == "PENDING_RECEIPT_SYNC_RESULT"
            and event["payload"].get("status") == "SYNCED"
        ]
        self.assertEqual(len(sync_events), 1)

    def test_concurrent_host_bundle_sync_records_one_terminal_result(self) -> None:
        queued = self.runtime.queue_host_bundle({
            "payload": {
                "investigation_id": self.investigation_id,
                "bundle": {
                    "bundle_id": "BUNDLE-V61-HOST-QUEUE-CONCURRENT",
                    "observations": [self.observation("product.fit", suffix="host-queue-concurrent")],
                },
            },
        })
        self.assertTrue(queued["queued"])

        with ThreadPoolExecutor(max_workers=8) as pool:
            results = list(pool.map(
                lambda _: self.runtime.sync_pending_bundles({"investigation_id": self.investigation_id}),
                range(8),
            ))
        self.assertEqual(sum(result["counts"].get("SYNCED", 0) for result in results), 1)
        queue = self.runtime._v6_queue()
        sync_events = [
            event for event in queue.events.read()
            if event["event_type"] == "HOST_BUNDLE_SYNC_RESULT"
            and event["payload"].get("status") == "SYNCED"
        ]
        self.assertEqual(len(sync_events), 1)


if __name__ == "__main__":
    unittest.main()
