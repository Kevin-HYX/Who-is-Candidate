import tempfile
import unittest
from pathlib import Path

from src.schemas import ProcessConfigError, load_config


class ConfigTests(unittest.TestCase):
    def test_missing_config_file_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            missing = Path(tmp) / "candidate-search.toml"
            with self.assertRaises(ProcessConfigError):
                load_config(missing)

    def test_empty_required_config_value_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate-search.toml"
            path.write_text(
                """
[openai]
api_key = ""
base_url = "https://example.test/compatible-mode/v1"

[models]
preprocess = "qwen3.7-max"
embedding = "text-embedding-v4"

[paths]
raw_profiles = "data/raw.jsonl"
processed_dir = "data/processed"
""".strip(),
                encoding="utf-8",
            )
            with self.assertRaises(ProcessConfigError):
                load_config(path)

    def test_missing_base_url_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate-search.toml"
            path.write_text(
                """
[openai]
api_key = "sk-test"

[models]
preprocess = "qwen3.7-max"
embedding = "text-embedding-v4"

[paths]
raw_profiles = "data/raw.jsonl"
processed_dir = "data/processed"
""".strip(),
                encoding="utf-8",
            )
            with self.assertRaises(ProcessConfigError) as ctx:
                load_config(path)
            self.assertIn("openai.base_url", str(ctx.exception))

    def test_valid_config_resolves_paths_relative_to_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate-search.toml"
            path.write_text(
                """
[openai]
api_key = "sk-test"
base_url = "https://example.test/compatible-mode/v1"

[models]
preprocess = "qwen3.7-max"
embedding = "text-embedding-v4"

[paths]
raw_profiles = "data/raw.jsonl"
processed_dir = "data/processed"
""".strip(),
                encoding="utf-8",
            )
            config = load_config(path)
            self.assertEqual(config.api_key, "sk-test")
            self.assertEqual(config.base_url, "https://example.test/compatible-mode/v1")
            self.assertEqual(config.raw_profiles_path, Path(tmp, "data", "raw.jsonl").resolve())
            self.assertEqual(config.processed_dir, Path(tmp, "data", "processed").resolve())

    def test_config_accepts_utf8_bom(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "candidate-search.toml"
            path.write_text(
                """
[openai]
api_key = "sk-test"
base_url = "https://example.test/compatible-mode/v1"

[models]
preprocess = "qwen3.7-max"
embedding = "text-embedding-v4"

[paths]
raw_profiles = "data/raw.jsonl"
processed_dir = "data/processed"
""".strip(),
                encoding="utf-8-sig",
            )
            config = load_config(path)
            self.assertEqual(config.api_key, "sk-test")


if __name__ == "__main__":
    unittest.main()
