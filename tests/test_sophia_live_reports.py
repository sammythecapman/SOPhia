"""Check the provenance and reproducibility of real saved answers, not legal truth."""

import hashlib
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "artifacts/api-server"))
from run_sophia_evals import evaluate, saved_responses
from build_info import read_build_info


class SavedLiveReportTests(unittest.TestCase):
    def test_saved_report_has_all_current_cases_and_reproducible_scores(self):
        fixture_path = ROOT / "tests/fixtures/sophia_issue_evals.json"
        fixtures = {c["id"]: c for c in json.loads(fixture_path.read_text())["cases"]}
        report = json.loads((ROOT / "outputs/sophia-issue-eval-results.json").read_text())
        self.assertEqual(set(fixtures), {c["id"] for c in report["cases"]})
        self.assertTrue(report["completed"])
        self.assertTrue(report["build_unchanged"])
        self.assertEqual(report["health_before"]["build_sha"], read_build_info()["build_sha"])
        self.assertEqual(report["fixture_sha256"], hashlib.sha256(fixture_path.read_bytes()).hexdigest())
        self.assertEqual(report["evaluator_sha256"], hashlib.sha256(
            (ROOT / "scripts/run_sophia_evals.py").read_bytes()
        ).hexdigest())
        for case in report["cases"]:
            self.assertEqual(case["question"], fixtures[case["id"]]["question"])
            self.assertTrue(case["response"].get("subanswers"))
            self.assertEqual(case["checks"], evaluate(fixtures[case["id"]], case["response"]))
            self.assertEqual(case["response_sha256"], hashlib.sha256(
                json.dumps(case["response"], sort_keys=True).encode()
            ).hexdigest())

    def test_single_response_cannot_be_reused_across_fixtures(self):
        with self.assertRaisesRegex(ValueError, "multiple fixtures"):
            saved_responses({"subanswers": []}, [{"id": "one"}, {"id": "two"}])
