import unittest

from src.main import search_tool_schema


class McpSchemaTests(unittest.TestCase):
    def test_search_tool_does_not_expose_config_parameter(self) -> None:
        schema = search_tool_schema()["inputSchema"]
        self.assertNotIn("config", schema["properties"])


if __name__ == "__main__":
    unittest.main()

