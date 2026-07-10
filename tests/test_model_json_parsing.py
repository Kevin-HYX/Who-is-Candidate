import unittest

from src.retrieval import _parse_json_content


class ModelJsonParsingTests(unittest.TestCase):
    def test_accepts_one_plain_json_object(self) -> None:
        self.assertEqual(_parse_json_content('  {"value": 1}  '), {"value": 1})

    def test_rejects_markdown_fences(self) -> None:
        with self.assertRaises(ValueError):
            _parse_json_content('```json\n{"value": 1}\n```')

    def test_rejects_comments_and_trailing_prose(self) -> None:
        for content in (
            '{"value": 1} explanation',
            '{"value": 1 // comment\n}',
        ):
            with self.subTest(content=content):
                with self.assertRaises(ValueError):
                    _parse_json_content(content)

    def test_rejects_duplicate_object_keys(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate JSON object key"):
            _parse_json_content('{"value": 1, "value": 2}')

    def test_rejects_nonstandard_numeric_constants(self) -> None:
        for content in (
            '{"value": NaN}',
            '{"value": Infinity}',
            '{"value": -Infinity}',
            '{"value": 1e309}',
        ):
            with self.subTest(content=content):
                with self.assertRaisesRegex(ValueError, "JSON.*finite|non-standard JSON constant"):
                    _parse_json_content(content)

    def test_rejects_nonobject_root(self) -> None:
        with self.assertRaisesRegex(ValueError, "JSON object"):
            _parse_json_content('[1, 2, 3]')


if __name__ == "__main__":
    unittest.main()
