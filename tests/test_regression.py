import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

from scripts.run_sop_regression import (
    _visible_answer_text,
    expected_fact_is_present,
    main,
)
from scripts.ingest_sop import _is_retryable_embedding_error


class ExpectedFactScoringTests(unittest.TestCase):
    def test_percentage_format_and_guaranty_synonyms_are_normalized(self):
        answer = "The 19 percent owner is below the threshold; an unlimited full guaranty applies."
        self.assertTrue(expected_fact_is_present("19%", answer))
        self.assertTrue(
            expected_fact_is_present("full, unlimited guarantee", answer)
        )

    def test_expected_negation_is_not_satisfied_by_positive_claim(self):
        self.assertFalse(expected_fact_is_present("not required", "The trust is required."))
        self.assertTrue(
            expected_fact_is_present(
                "not required", "The 19% trust is not required under this threshold."
            )
        )

    def test_scoring_uses_answer_artifacts_but_not_source_quotes(self):
        text = _visible_answer_text(
            {
                "answer": "The individual must sign the guaranty.",
                "sources": [{"quote": "A hidden source-only fact"}],
                "subanswers": [
                    {
                        "applied_conclusion": {
                            "text": "The 81% owner must provide an unlimited full guaranty.",
                            "citations": [{"quote": "another hidden source-only fact"}],
                        }
                    }
                ],
            }
        )
        self.assertTrue(expected_fact_is_present("81%", text))
        self.assertFalse(expected_fact_is_present("hidden source-only fact", text))

    def test_embedding_quota_errors_fail_without_retry(self):
        error = RuntimeError("quota")
        error.code = "credit_balance_exhausted"
        error.body = {"error": {"type": "insufficient_quota"}}
        self.assertFalse(_is_retryable_embedding_error(error))

    def test_transient_embedding_rate_limit_is_retryable(self):
        error = RuntimeError("rate limited")
        error.status_code = 429
        error.body = {"error": {"type": "rate_limit_exceeded"}}
        self.assertTrue(_is_retryable_embedding_error(error))

    def test_http_failure_still_writes_a_partial_report(self):
        with tempfile.TemporaryDirectory() as directory:
            report_path = Path(directory) / "regression.json"
            error = HTTPError("https://example.invalid", 401, "Unauthorized", None, None)
            with (
                patch(
                    "scripts.run_sop_regression.fetch_healthz",
                    return_value=({"source_sha256": "expected"}, None),
                ),
                patch("scripts.run_sop_regression.query", side_effect=error),
                patch(
                    "sys.argv",
                    [
                        "run_sop_regression.py",
                        "--report",
                        str(report_path),
                        "--expected-source-sha256",
                        "expected",
                    ],
                ),
                contextlib.redirect_stdout(io.StringIO()),
                contextlib.redirect_stderr(io.StringIO()),
            ):
                self.assertEqual(main(), 1)

            report = json.loads(report_path.read_text())
            self.assertEqual(report["summary"]["request_errors"], 1)
            self.assertGreater(report["summary"]["not_run"], 0)
            self.assertEqual(report["cases"][0]["status"], "ERROR")


if __name__ == "__main__":
    unittest.main()