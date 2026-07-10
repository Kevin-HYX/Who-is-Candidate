import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from src.retrieval import OpenAICompatibleModelClient
from src.schemas import RuntimeConfig


class ModelClientTests(unittest.TestCase):
    def test_openai_sdk_retries_are_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            captured = {}

            def create_client(**kwargs):
                captured.update(kwargs)
                return SimpleNamespace(
                    embeddings=SimpleNamespace(
                        create=lambda **_: SimpleNamespace(
                            data=[SimpleNamespace(index=0, embedding=[1.0, 0.0])]
                        )
                    )
                )

            config = RuntimeConfig(
                config_path=root / "candidate-search.toml",
                api_key="sk-test",
                base_url="https://example.test/compatible-mode/v1",
                preprocess_model="qwen3.7-max",
                embedding_model="text-embedding-v4",
                raw_profiles_path=root / "raw.jsonl",
                processed_dir=root / "processed",
            )
            openai_module = SimpleNamespace(OpenAI=create_client)

            with patch("src.retrieval._load_openai", return_value=openai_module):
                OpenAICompatibleModelClient(config).embed_texts(["finance"])

            self.assertEqual(captured["max_retries"], 0)


if __name__ == "__main__":
    unittest.main()
