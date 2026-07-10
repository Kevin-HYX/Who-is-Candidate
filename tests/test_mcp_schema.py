import unittest

from src.constants import QUERY_GUIDE_FILE
from src.main import MinimalMcpServer, help_text
from src.schemas import search_tool_schema


class McpSchemaTests(unittest.TestCase):
    def test_search_tool_does_not_expose_config_parameter(self) -> None:
        schema = search_tool_schema()["inputSchema"]
        self.assertNotIn("config", schema["properties"])

    def test_search_tool_schema_exposes_strict_query_contract(self) -> None:
        schema = search_tool_schema()["inputSchema"]
        self.assertFalse(schema["additionalProperties"])
        query_plan = schema["properties"]["query_plan"]
        self.assertFalse(query_plan["additionalProperties"])
        self.assertEqual(
            set(query_plan["required"]),
            {"hard_constraints", "weighted_soft_preferences"},
        )
        hard_item = query_plan["properties"]["hard_constraints"]["items"]
        self.assertIn("role_family", hard_item["properties"]["field"]["enum"])
        soft_item = query_plan["properties"]["weighted_soft_preferences"]["items"]
        self.assertIn(
            "domain_search_text",
            soft_item["properties"]["dimension"]["enum"],
        )
        self.assertFalse(hard_item["additionalProperties"])
        self.assertFalse(soft_item["additionalProperties"])
        weight_schema = soft_item["properties"]["weight"]
        self.assertEqual(weight_schema["minimum"], -2.0)
        self.assertEqual(weight_schema["maximum"], 2.0)
        self.assertEqual(
            weight_schema["anyOf"],
            [
                {"minimum": -2.0, "maximum": -0.1},
                {"minimum": 0.1, "maximum": 2.0},
            ],
        )

    def test_management_scope_schema_couples_operator_and_value_shape(self) -> None:
        hard_item = (
            search_tool_schema()["inputSchema"]["properties"]["query_plan"]
            ["properties"]["hard_constraints"]["items"]
        )
        management_conditions = [
            condition
            for condition in hard_item["allOf"]
            if condition["if"]["properties"].get("field", {}).get("const")
            == "management_scope"
            and "op" in condition["if"]["properties"]
        ]

        self.assertEqual(len(management_conditions), 2)
        value_types_by_operators = {
            tuple(condition["if"]["properties"]["op"]["enum"]):
            condition["then"]["properties"]["value"]["type"]
            for condition in management_conditions
        }
        self.assertEqual(value_types_by_operators[("in", "not_in")], "array")
        self.assertEqual(value_types_by_operators[("<=", "=", ">=")], "string")

    def test_search_schema_exposes_six_position_levels(self) -> None:
        hard_item = (
            search_tool_schema()["inputSchema"]["properties"]["query_plan"]
            ["properties"]["hard_constraints"]["items"]
        )
        seniority_rule = next(
            condition
            for condition in hard_item["allOf"]
            if condition["if"]["properties"].get("field", {}).get("const")
            == "seniority_level"
        )
        self.assertEqual(
            seniority_rule["then"]["properties"]["value"]["enum"],
            [
                "Internship",
                "Entry level",
                "Associate",
                "Mid-Senior level",
                "Director",
                "Executive",
            ],
        )

    def test_help_is_loaded_from_markdown(self) -> None:
        text = help_text()
        self.assertIn("# Candidate Search Help", text)
        self.assertIn("# Candidate Query Guide", text)
        self.assertLess(
            text.index("# Candidate Search Help"),
            text.index("# Candidate Query Guide"),
        )

    def test_query_guide_is_separate_markdown(self) -> None:
        text = QUERY_GUIDE_FILE.read_text(encoding="utf-8")
        self.assertIn("# Candidate Query Guide", text)
        self.assertIn("Return exactly one standards-compliant JSON object", text)

    def test_mcp_resources_expose_help_not_query_guide(self) -> None:
        resources = MinimalMcpServer(config=object()).dispatch("resources/list", {})["resources"]
        uris = {resource["uri"] for resource in resources}
        self.assertIn("candidate://help", uris)
        self.assertNotIn("candidate://query-guide", uris)

    def test_invalid_tool_arguments_are_marked_as_tool_error(self) -> None:
        result = MinimalMcpServer(config=object()).call_tool(
            {"name": "search_candidates", "arguments": {}}
        )

        self.assertTrue(result["isError"])
        self.assertIn("INVALID_SEARCH_ARGUMENTS", result["content"][0]["text"])


if __name__ == "__main__":
    unittest.main()
