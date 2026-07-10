import json
import tempfile
import unittest
from contextlib import redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from src.main import main


class SearchCliTests(unittest.TestCase):
    def test_top_k_flag_overrides_invalid_file_value_before_validation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            query_path = root / "query.json"
            query_path.write_text(
                json.dumps(
                    {
                        "query_plan": {
                            "hard_constraints": [],
                            "weighted_soft_preferences": [
                                {
                                    "dimension": "domain_search_text",
                                    "text": "Healthcare finance and revenue-cycle operations.",
                                    "weight": 1.0,
                                }
                            ],
                        },
                        "options": {"top_k": 76},
                    }
                ),
                encoding="utf-8",
            )
            with patch("src.main.search_candidates", return_value={"results": []}) as search:
                output = StringIO()
                with redirect_stdout(output):
                    code = main(
                        [
                            "search",
                            "--config",
                            str(config_path),
                            "--query",
                            str(query_path),
                            "--top-k",
                            "10",
                        ]
                    )

            self.assertEqual(code, 0)
            self.assertEqual(search.call_args.args[2]["top_k"], 10)

    def test_invalid_query_json_returns_structured_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config_path = _write_config(root)
            query_path = root / "query.json"
            query_path.write_text('{"query_plan":', encoding="utf-8")
            output = StringIO()

            with redirect_stdout(output):
                code = main(
                    [
                        "search",
                        "--config",
                        str(config_path),
                        "--query",
                        str(query_path),
                    ]
                )

            self.assertEqual(code, 1)
            self.assertEqual(json.loads(output.getvalue())["error"]["code"], "INVALID_JSON")


def _write_config(root: Path) -> Path:
    raw_path = root / "raw.jsonl"
    raw_path.write_text(json.dumps({"user_id": 1}) + "\n", encoding="utf-8")
    config_path = root / "candidate-search.toml"
    config_path.write_text(
        f"""
[openai]
api_key = "sk-test"
base_url = "https://example.test/compatible-mode/v1"

[models]
preprocess = "qwen3.7-max"
embedding = "text-embedding-v4"

[paths]
raw_profiles = "{raw_path.as_posix()}"
processed_dir = "{(root / 'processed').as_posix()}"
""".strip(),
        encoding="utf-8",
    )
    return config_path


if __name__ == "__main__":
    unittest.main()
