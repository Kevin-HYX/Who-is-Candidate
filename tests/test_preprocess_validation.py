import copy
import json
import tempfile
import unittest
from pathlib import Path

from src.constants import (
    EMBEDDINGS_FILE,
    PREPROCESS_ERRORS_FILE,
    PROCESSED_PROFILES_FILE,
    SEARCHABLE_DIMENSIONS,
)
from src.preprocess import preprocess_profiles, validate_preprocess_model_output
from src.retrieval import get_index_status
from src.schemas import CandidateSearchError, RuntimeConfig


def valid_model_output() -> dict:
    return {
        "hard_fields": {
            "role_family": {
                "value": "Finance & Accounting",
                "confidence": "high",
                "source_field": "experience[0].role",
                "evidence": "Finance & Accounting",
            },
            "seniority_level": {
                "value": "Associate",
                "confidence": "medium",
                "source_field": "experience[0].title",
                "evidence": "Financial Analyst",
            },
            "management_scope": {
                "value": "unknown",
                "confidence": "low",
                "source_field": "experience[].description",
                "evidence": "insufficient_evidence",
            },
            "industries": {
                "value": ["Financial Services"],
                "confidence": "high",
                "source_field": "experience[0].industry",
                "evidence": "Financial Services",
            },
        },
        "embedding_search_texts": {
            dimension: f"Evidence-backed English search text for {dimension}."
            for dimension in SEARCHABLE_DIMENSIONS
        },
        "derived_fields": {},
        "keyword_signals": {},
        "risk": {},
    }


class PreprocessValidationTests(unittest.TestCase):
    def test_accepts_exact_canonical_model_output(self) -> None:
        validate_preprocess_model_output(valid_model_output())

    def test_rejects_noncanonical_classifications(self) -> None:
        invalid_outputs = []

        invalid_role = valid_model_output()
        invalid_role["hard_fields"]["role_family"]["value"] = "Finance"
        invalid_outputs.append(invalid_role)

        invalid_industry = valid_model_output()
        invalid_industry["hard_fields"]["industries"]["value"] = ["Higher Education"]
        invalid_outputs.append(invalid_industry)

        legacy_seniority = valid_model_output()
        legacy_seniority["hard_fields"]["seniority_level"]["value"] = "Specialist"
        invalid_outputs.append(legacy_seniority)

        duplicate_industry = valid_model_output()
        duplicate_industry["hard_fields"]["industries"]["value"] = [
            "Financial Services",
            "Financial Services",
        ]
        invalid_outputs.append(duplicate_industry)

        for output in invalid_outputs:
            with self.subTest(output=output["hard_fields"]):
                with self.assertRaises(ValueError):
                    validate_preprocess_model_output(output)

    def test_rejects_extra_missing_and_inconsistent_fields(self) -> None:
        invalid_outputs = []

        extra_top_level = valid_model_output()
        extra_top_level["explanation"] = "unsupported"
        invalid_outputs.append(extra_top_level)

        extra_hard_field = valid_model_output()
        extra_hard_field["hard_fields"]["years_of_experience"] = {
            "value": 5,
            "confidence": "high",
            "source_field": "invented",
            "evidence": "invented",
        }
        invalid_outputs.append(extra_hard_field)

        missing_evidence = valid_model_output()
        del missing_evidence["hard_fields"]["role_family"]["evidence"]
        invalid_outputs.append(missing_evidence)

        inconsistent_unknown = valid_model_output()
        inconsistent_unknown["hard_fields"]["management_scope"]["confidence"] = "high"
        invalid_outputs.append(inconsistent_unknown)

        legacy_unknown_confidence = valid_model_output()
        legacy_unknown_confidence["hard_fields"]["management_scope"]["confidence"] = (
            "unknown"
        )
        invalid_outputs.append(legacy_unknown_confidence)

        empty_search_text = valid_model_output()
        empty_search_text["embedding_search_texts"]["domain_search_text"] = ""
        invalid_outputs.append(empty_search_text)

        absence_sentence = valid_model_output()
        absence_sentence["embedding_search_texts"]["achievements_search_text"] = (
            "No specific achievements were provided in the profile."
        )
        invalid_outputs.append(absence_sentence)

        legacy_absence_state = valid_model_output()
        legacy_absence_state["embedding_search_texts"][
            "achievements_search_text"
        ] = "insufficient_evidence"
        invalid_outputs.append(legacy_absence_state)

        for output in invalid_outputs:
            with self.subTest(output=output):
                with self.assertRaises(ValueError):
                    validate_preprocess_model_output(output)

    def test_rejects_non_english_generated_text(self) -> None:
        invalid_outputs = []

        chinese_evidence = valid_model_output()
        chinese_evidence["hard_fields"]["role_family"]["evidence"] = "财务与会计"
        invalid_outputs.append(chinese_evidence)

        chinese_search_text = valid_model_output()
        chinese_search_text["embedding_search_texts"]["domain_search_text"] = (
            "医疗财务与收入周期管理"
        )
        invalid_outputs.append(chinese_search_text)

        for output in invalid_outputs:
            with self.subTest(output=output):
                with self.assertRaisesRegex(ValueError, "English"):
                    validate_preprocess_model_output(output)

    def test_missing_current_work_evidence_stays_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_path = root / "raw.jsonl"
            raw_path.write_text(
                json.dumps(
                    {
                        "user_id": 1,
                        "headline": "Financial Analyst",
                        "experience": [{"title": "Financial Analyst"}],
                    }
                )
                + "\n",
                encoding="utf-8",
            )
            prompt_path = root / "preprosess.md"
            prompt_path.write_text("Return valid JSON.", encoding="utf-8")
            config = RuntimeConfig(
                config_path=root / "candidate-search.toml",
                api_key="sk-test",
                base_url="https://example.test/compatible-mode/v1",
                preprocess_model="test-model",
                embedding_model="test-embedding",
                raw_profiles_path=raw_path,
                processed_dir=root / "processed",
            )

            preprocess_profiles(
                config,
                concurrency=1,
                model_client=StaticPreprocessClient(),
                prompt_path=prompt_path,
            )

            record = json.loads(
                (config.processed_dir / PROCESSED_PROFILES_FILE)
                .read_text(encoding="utf-8")
                .strip()
            )
            current_work = record["preprocessed_profile"]["hard_fields"][
                "is_currently_working"
            ]
            self.assertEqual(current_work["value"], "unknown")
            self.assertEqual(current_work["confidence"], "low")
            self.assertEqual(
                record["preprocessed_profile"]["hard_fields"][
                    "years_of_experience"
                ]["confidence"],
                "low",
            )
            self.assertEqual(
                record["preprocessed_profile"]["hard_fields"][
                    "highest_degree_level"
                ]["confidence"],
                "low",
            )

    def test_unknown_inferred_value_accepts_medium_or_low_but_not_high(self) -> None:
        medium_output = valid_model_output()
        medium_output["hard_fields"]["management_scope"].update(
            {
                "confidence": "medium",
                "source_field": "experience[].title, experience[].description",
                "evidence": "Manager title conflicts with the absence of direct-report evidence.",
            }
        )
        validate_preprocess_model_output(medium_output)

        low_output = valid_model_output()
        low_output["hard_fields"]["management_scope"]["evidence"] = (
            "No explicit management-scope evidence is present in the profile."
        )
        validate_preprocess_model_output(low_output)

        output = valid_model_output()
        output["hard_fields"]["management_scope"]["confidence"] = "high"
        with self.assertRaisesRegex(ValueError, "cannot be high"):
            validate_preprocess_model_output(output)

        medium_without_conflict = valid_model_output()
        medium_without_conflict["hard_fields"]["management_scope"]["confidence"] = (
            "medium"
        )
        with self.assertRaisesRegex(ValueError, "conflicting or ambiguous"):
            validate_preprocess_model_output(medium_without_conflict)

    def test_invalid_model_output_is_retried_then_reported(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_path = root / "raw.jsonl"
            raw_path.write_text(
                json.dumps({"user_id": 1, "headline": "Financial Analyst"}) + "\n",
                encoding="utf-8",
            )
            prompt_path = root / "preprosess.md"
            prompt_path.write_text("Return valid JSON.", encoding="utf-8")
            config = RuntimeConfig(
                config_path=root / "candidate-search.toml",
                api_key="sk-test",
                base_url="https://example.test/compatible-mode/v1",
                preprocess_model="test-model",
                embedding_model="test-embedding",
                raw_profiles_path=raw_path,
                processed_dir=root / "processed",
            )
            client = InvalidPreprocessClient()

            with self.assertRaises(CandidateSearchError) as ctx:
                preprocess_profiles(
                    config,
                    concurrency=1,
                    model_client=client,
                    prompt_path=prompt_path,
                )

            self.assertEqual(ctx.exception.code, "PREPROCESS_FAILED")
            self.assertEqual(client.calls, 3)
            errors = [
                json.loads(line)
                for line in (config.processed_dir / PREPROCESS_ERRORS_FILE)
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            ]
            self.assertEqual(len(errors), 1)
            self.assertIn("hard_fields.role_family.value", errors[0]["message"])
            processed_path = config.processed_dir / PROCESSED_PROFILES_FILE
            self.assertTrue(processed_path.exists())
            self.assertEqual(processed_path.read_text(encoding="utf-8"), "")

    def test_discard_cache_failure_removes_previous_preprocess_and_index_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            raw_path = root / "raw.jsonl"
            raw_path.write_text(
                json.dumps({"user_id": 1, "headline": "Financial Analyst"}) + "\n",
                encoding="utf-8",
            )
            prompt_path = root / "preprosess.md"
            prompt_path.write_text("Return valid JSON.", encoding="utf-8")
            config = RuntimeConfig(
                config_path=root / "candidate-search.toml",
                api_key="sk-test",
                base_url="https://example.test/compatible-mode/v1",
                preprocess_model="test-model",
                embedding_model="test-embedding",
                raw_profiles_path=raw_path,
                processed_dir=root / "processed",
            )
            preprocess_profiles(
                config,
                concurrency=1,
                model_client=StaticPreprocessClient(),
                prompt_path=prompt_path,
            )
            (config.processed_dir / EMBEDDINGS_FILE).write_text(
                json.dumps({"user_id": 1, "source_row_index": 0}) + "\n",
                encoding="utf-8",
            )

            with self.assertRaises(CandidateSearchError):
                preprocess_profiles(
                    config,
                    concurrency=1,
                    model_client=InvalidPreprocessClient(),
                    prompt_path=prompt_path,
                    discard_cache=True,
                )

            self.assertEqual(
                (config.processed_dir / PROCESSED_PROFILES_FILE)
                .read_text(encoding="utf-8"),
                "",
            )
            self.assertEqual(
                (config.processed_dir / EMBEDDINGS_FILE).read_text(encoding="utf-8"),
                "",
            )
            status = get_index_status(config)
            self.assertEqual(status["preprocess_status"], "missing")
            self.assertEqual(status["index_status"], "missing")
            self.assertFalse((config.processed_dir / "status.json").exists())


class InvalidPreprocessClient:
    def __init__(self) -> None:
        self.calls = 0

    def preprocess_profile(self, prompt: str, raw_profile: dict) -> dict:
        self.calls += 1
        output = copy.deepcopy(valid_model_output())
        output["hard_fields"]["role_family"]["value"] = "Finance"
        return output


class StaticPreprocessClient:
    def preprocess_profile(self, prompt: str, raw_profile: dict) -> dict:
        return copy.deepcopy(valid_model_output())


if __name__ == "__main__":
    unittest.main()
