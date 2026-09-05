import unittest

from unified_runtime.mcp_schema_v63 import (
    V63_MUTATION_TOOL_NAMES,
    V63_READ_ONLY_TOOL_NAMES,
    build_v63_tool_descriptors,
)


class V63MCPSchemaTests(unittest.TestCase):
    def setUp(self):
        self.tools = {row["name"]: row for row in build_v63_tool_descriptors()}

    def test_all_declared_tool_names_are_unique(self):
        self.assertEqual(len(self.tools), len(build_v63_tool_descriptors()))
        self.assertTrue(V63_READ_ONLY_TOOL_NAMES)
        self.assertTrue(V63_MUTATION_TOOL_NAMES)
        self.assertFalse(set(V63_READ_ONLY_TOOL_NAMES) & set(V63_MUTATION_TOOL_NAMES))

    def test_mutation_tools_require_idempotency_key(self):
        for name in V63_MUTATION_TOOL_NAMES:
            with self.subTest(name=name):
                schema = self.tools[name]["inputSchema"]
                self.assertIn("idempotency_key", schema["required"])
                self.assertIn("expected_state_version", schema["properties"])
                self.assertFalse(self.tools[name]["annotations"]["readOnlyHint"])

    def test_read_only_tools_do_not_require_idempotency_key(self):
        for name in V63_READ_ONLY_TOOL_NAMES:
            with self.subTest(name=name):
                schema = self.tools[name]["inputSchema"]
                self.assertNotIn("idempotency_key", schema.get("required", []))
                self.assertTrue(self.tools[name]["annotations"]["readOnlyHint"])

    def test_planner_descriptors_explicitly_deny_execution_proof(self):
        for name in (
            "preview_customs_seed_expansion",
            "plan_candidate_expansion",
            "plan_contact_exhaustion",
            "preview_recursive_anchor_expansion",
        ):
            with self.subTest(name=name):
                contract = self.tools[name]["contract"]
                self.assertFalse(contract["planning_is_execution_proof"])
                self.assertTrue(contract["host_execution_required"])

    def test_no_v63_tool_sends_outreach(self):
        for tool in self.tools.values():
            self.assertFalse(tool["contract"]["sends_message"])
            self.assertFalse(tool["contract"]["server_side_draft_created"])

    def test_mutation_tools_declare_existing_wal_binding(self):
        for name in V63_MUTATION_TOOL_NAMES:
            with self.subTest(name=name):
                self.assertEqual(
                    self.tools[name]["contract"]["mutation_boundary"],
                    "EXISTING_PRODUCTION_WAL_ONLY",
                )


if __name__ == "__main__":
    unittest.main()

class V63ExtendedReadOnlySchemaTests(unittest.TestCase):
    def test_route_reuse_and_portfolio_metrics_are_read_only_tools(self):
        from unified_runtime.mcp_schema_v63 import build_v63_tool_descriptors
        tools = {tool["name"]: tool for tool in build_v63_tool_descriptors()}
        for name in ("evaluate_route_reuse", "get_portfolio_metrics"):
            self.assertIn(name, tools)
            self.assertTrue(tools[name]["annotations"]["readOnlyHint"])
            self.assertEqual(tools[name]["inputSchema"]["required"], [])

class V63ResearchSchedulerSchemaTests(unittest.TestCase):
    def test_soft_budget_scheduler_is_read_only_tool(self):
        from unified_runtime.mcp_schema_v63 import build_v63_tool_descriptors
        tools = {tool["name"]: tool for tool in build_v63_tool_descriptors()}
        tool = tools["schedule_expansion_research"]
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        self.assertFalse(tool["contract"]["planning_is_execution_proof"])

class V63MutationControlFieldCompatibilityTests(unittest.TestCase):
    def test_v63_mutation_idempotency_key_matches_existing_production_contract(self):
        from unified_runtime.mcp_schema_v63 import build_v63_tool_descriptors, V63_MUTATION_TOOL_NAMES
        tools = {tool["name"]: tool for tool in build_v63_tool_descriptors()}
        for name in V63_MUTATION_TOOL_NAMES:
            schema = tools[name]["inputSchema"]["properties"]["idempotency_key"]
            self.assertEqual(schema["minLength"], 8)
            self.assertEqual(schema["maxLength"], 160)
            self.assertNotIn("pattern", schema)
            self.assertIn("idempotency_key", tools[name]["inputSchema"]["required"])

    def test_expected_state_version_remains_optional_nonnegative_integer(self):
        from unified_runtime.mcp_schema_v63 import build_v63_tool_descriptors, V63_MUTATION_TOOL_NAMES
        tools = {tool["name"]: tool for tool in build_v63_tool_descriptors()}
        for name in V63_MUTATION_TOOL_NAMES:
            schema = tools[name]["inputSchema"]["properties"]["expected_state_version"]
            self.assertEqual(schema["minimum"], 0)
            self.assertNotIn("expected_state_version", tools[name]["inputSchema"]["required"])

class V63LocalOutreachSchemaTests(unittest.TestCase):
    def test_local_outreach_planner_is_read_only_and_never_sends(self):
        tools = {tool["name"]: tool for tool in build_v63_tool_descriptors()}
        tool = tools["plan_local_outreach"]
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        self.assertFalse(tool["contract"]["sends_message"])
        self.assertFalse(tool["contract"]["server_side_draft_created"])
        self.assertFalse(tool["contract"]["planning_is_execution_proof"])

class V63LocalContextResolutionSchemaTests(unittest.TestCase):
    def test_local_context_resolution_is_read_only_planner(self):
        tools = {tool["name"]: tool for tool in build_v63_tool_descriptors()}
        tool = tools["plan_local_context_resolution"]
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        self.assertFalse(tool["contract"]["planning_is_execution_proof"])
        self.assertTrue(tool["contract"]["host_execution_required"])

class V63SalesReadinessSchemaTests(unittest.TestCase):
    def test_sales_readiness_is_read_only_and_never_sends(self):
        tools = {tool["name"]: tool for tool in build_v63_tool_descriptors()}
        tool = tools["evaluate_sales_readiness"]
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        self.assertFalse(tool["contract"]["sends_message"])
        self.assertFalse(tool["contract"]["server_side_draft_created"])

class V63ExactMutationPayloadSchemaTests(unittest.TestCase):
    def setUp(self):
        self.tools = {tool["name"]: tool for tool in build_v63_tool_descriptors()}

    def test_derive_demand_anchor_is_strict_read_only_evidence_bound_view(self):
        tool = self.tools["derive_demand_anchor"]
        schema = tool["inputSchema"]
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        self.assertEqual(schema["additionalProperties"], False)
        self.assertEqual(set(schema["required"]), {"account_id", "opportunity_id", "source_type", "source_evidence_ids", "product_profile_id", "geography"})
        self.assertNotIn("idempotency_key", schema["properties"])
        self.assertEqual(schema["properties"]["source_evidence_ids"]["minItems"], 1)

    def test_candidate_discovery_schema_requires_branch_bound_candidate(self):
        schema = self.tools["append_candidate_discovery"]["inputSchema"]
        self.assertEqual(set(schema["required"]), {"investigation_id", "candidate", "idempotency_key"})
        candidate = schema["properties"]["candidate"]
        self.assertTrue({
            "candidate_id", "discovered_from_anchor_id", "branch_group", "branch",
            "company_name", "product_profile_id",
        } <= set(candidate["required"]))
        self.assertEqual(
            set(candidate["properties"]["branch_group"]["enum"]),
            {"TRADE_GRAPH", "APPLICATION_GRAPH", "CHANNEL_GRAPH", "MARKET_GRAPH", "COMPETITIVE_GRAPH", "CROSS_SELL_GRAPH"},
        )

    def test_product_opportunity_creation_requires_production_canonical_proof(self):
        schema = self.tools["create_product_opportunity"]["inputSchema"]
        self.assertEqual(
            set(schema["required"]),
            {"investigation_id", "canonical_resolution", "opportunity", "idempotency_key"},
        )
        proof = schema["properties"]["canonical_resolution"]
        self.assertEqual(proof["properties"]["resolver_is_existing_production_authority"]["const"], True)
        self.assertEqual(proof["properties"]["address_only_match"]["const"], False)
        self.assertEqual(proof["properties"]["alias_only_match"]["const"], False)
        opp = schema["properties"]["opportunity"]
        self.assertTrue({
            "opportunity_id", "account_id", "product_profile_id",
            "product_profile_version", "product_profile_sha256",
        } <= set(opp["required"]))

    def test_product_opportunity_evaluation_is_strict_read_only_derived_view(self):
        tool = self.tools["evaluate_product_opportunity"]
        schema = tool["inputSchema"]
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        self.assertEqual(
            set(schema["required"]),
            {"investigation_id", "opportunity_id", "assessment"},
        )
        self.assertNotIn("idempotency_key", schema["properties"])
        assessment = schema["properties"]["assessment"]
        self.assertTrue({"commercial_value_grade", "commercial_value_score", "commercial_evidence_ids"} <= set(assessment["required"]))
        self.assertEqual(assessment["properties"]["commercial_evidence_ids"]["minItems"], 1)

    def test_anchor_promotion_requires_eligibility_cycle_dedup_and_reason(self):
        schema = self.tools["promote_opportunity_anchor"]["inputSchema"]
        self.assertEqual(
            set(schema["required"]),
            {"investigation_id", "opportunity_id", "promotion_reason", "anchor_eligibility", "cycle_dedup_complete", "idempotency_key"},
        )
        self.assertEqual(schema["properties"]["cycle_dedup_complete"]["const"], True)
        self.assertEqual(schema["properties"]["anchor_eligibility"]["properties"]["anchor_eligible"]["const"], True)

    def test_expected_state_version_matches_existing_production_optional_integer_shape(self):
        for name in V63_MUTATION_TOOL_NAMES:
            schema = self.tools[name]["inputSchema"]["properties"]["expected_state_version"]
            self.assertEqual(schema["type"], "integer")
            self.assertEqual(schema["minimum"], 0)

class V63CandidateResearchGateSchemaTests(unittest.TestCase):
    def test_candidate_research_assessment_is_read_only(self):
        tools = {tool["name"]: tool for tool in build_v63_tool_descriptors()}
        tool = tools["assess_candidate_researchability"]
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        self.assertFalse(tool["contract"]["sends_message"])
        self.assertNotIn("idempotency_key", tool["inputSchema"].get("required", []))

class V63CandidateResearchQueueSchemaTests(unittest.TestCase):
    def test_candidate_research_queue_is_read_only(self):
        tools = {tool["name"]: tool for tool in build_v63_tool_descriptors()}
        tool = tools["rank_candidate_research_queue"]
        self.assertTrue(tool["annotations"]["readOnlyHint"])
        self.assertNotIn("idempotency_key", tool["inputSchema"].get("required", []))
