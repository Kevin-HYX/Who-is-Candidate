import io
import json
import unittest

from src.main import MinimalMcpServer, read_mcp_message, write_mcp_message


class McpTransportTests(unittest.TestCase):
    def test_newline_delimited_initialize_and_tools_list_round_trip(self) -> None:
        incoming = io.BytesIO(
            _message_bytes(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {},
                }
            )
            + _message_bytes(
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/list",
                    "params": {},
                }
            )
        )
        outgoing = io.BytesIO()

        MinimalMcpServer(config=object()).serve(incoming, outgoing)

        outgoing.seek(0)
        initialized = read_mcp_message(outgoing)
        tools = read_mcp_message(outgoing)
        self.assertEqual(initialized["id"], 1)
        self.assertEqual(tools["id"], 2)
        self.assertEqual(tools["result"]["tools"][0]["name"], "search_candidates")
        self.assertIsNone(read_mcp_message(outgoing))

    def test_invalid_json_message_returns_parse_error_and_server_continues(self) -> None:
        invalid_body = b'{"jsonrpc":"2.0","id":1,'
        incoming = io.BytesIO(invalid_body + b"\n")
        outgoing = io.BytesIO()

        MinimalMcpServer(config=object()).serve(incoming, outgoing)

        outgoing.seek(0)
        response = read_mcp_message(outgoing)
        self.assertEqual(response["jsonrpc"], "2.0")
        self.assertIsNone(response["id"])
        self.assertEqual(response["error"]["code"], -32700)
        self.assertIsNone(read_mcp_message(outgoing))

    def test_mcp_writer_never_emits_nonstandard_numeric_values(self) -> None:
        outgoing = io.BytesIO()
        with self.assertRaises(ValueError):
            write_mcp_message(
                outgoing,
                {
                    "jsonrpc": "2.0",
                    "id": float("inf"),
                    "result": {},
                },
            )


def _message_bytes(message: dict) -> bytes:
    return json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n"


if __name__ == "__main__":
    unittest.main()
