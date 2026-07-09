import unittest

from src.constants import QUERY_GUIDE_FILE
from src.main import MinimalMcpServer, help_text
from src.schemas import search_tool_schema


class McpSchemaTests(unittest.TestCase):
    def test_search_tool_does_not_expose_config_parameter(self) -> None:
        schema = search_tool_schema()["inputSchema"]
        self.assertNotIn("config", schema["properties"])

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
        self.assertIn("Return only JSON", text)

    def test_mcp_resources_expose_help_not_query_guide(self) -> None:
        resources = MinimalMcpServer(config=object()).dispatch("resources/list", {})["resources"]
        uris = {resource["uri"] for resource in resources}
        self.assertIn("candidate://help", uris)
        self.assertNotIn("candidate://query-guide", uris)


if __name__ == "__main__":
    unittest.main()
