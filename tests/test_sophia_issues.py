import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "artifacts/api-server"))
sys.path.insert(0, str(ROOT / "scripts"))
from applicability import applicability_check, classify_question, classify_text
from sophia_issues import (
    applied_evidence_error, preserve_compound_issues, synthesize_bottom_line,
    quote_options, resolve_applied_quotes,
    grounded_covenant_conclusion, conclusion_scope_error,
)
from run_sophia_evals import evaluate

CASE = json.loads((ROOT / "tests/fixtures/sophia_issue_evals.json").read_text())["cases"][0]


class SophiaIssueTests(unittest.TestCase):
    def test_compound_case_survives_planner_omission(self):
        plan = preserve_compound_issues(CASE["question"], [])
        self.assertEqual(len(plan), 2)
        self.assertIn("Preference", plan[0]["question"])
        self.assertIn("note-rate", plan[1]["question"])
        self.assertIn("1.00%", plan[0]["material_facts"][0])
        self.assertIn("13 CFR 120.10", " ".join(plan[0]["search_terms"]))

    def test_unrelated_questions_are_not_expanded(self):
        original = [{"question": "Who must guarantee this trust?"}]
        self.assertEqual(preserve_compound_issues(original[0]["question"], original), original)

    def test_export_express_leaf_inherits_program(self):
        tags = classify_text("Default interest rates are permitted.", "Appendices > Appendix 18: 7(a) Interest Rate Requirements > Program-Specific Requirements > Export Express Loans > Default Interest Rates")
        self.assertEqual(tags["product_lines"], ["export_express"])
        self.assertFalse(applicability_check(tags, classify_question(CASE["question"]))[0])
        self.assertTrue(applicability_check(tags, classify_question("An Export Express loan"))[0])

    def test_body_cross_reference_does_not_change_program(self):
        tags = classify_text("Compare the Export Express exception.", "Appendices > Appendix 18: 7(a) Interest Rate Requirements > General Policy on Interest Rates")
        self.assertEqual(tags["product_lines"], [])
        self.assertTrue(applicability_check(tags, classify_question(CASE["question"]))[0])

    def test_general_scope_remains_universal(self):
        tags = classify_text("The Lender must comply.", "Appendices > Definitions")
        self.assertEqual(tags["program_scopes"], ["general"])
        self.assertTrue(applicability_check(tags, classify_question("A 504 loan"))[0])

    def test_verbatim_only_and_application_bounds(self):
        quote = "The Lender must not require a compensating balance."
        self.assertIsNone(applied_evidence_error(quote, "The proposed deposit covenant requires one.", quote))
        self.assertIsNotNone(applied_evidence_error(quote.replace("must not", "cannot"), "It is prohibited.", quote))
        self.assertIsNotNone(applied_evidence_error(quote, "", quote))
        self.assertIsNotNone(applied_evidence_error(quote, "One. Two. Three. Four.", quote))
        self.assertIsNotNone(applied_evidence_error("One. Two.", "This applies.", "One. Two."))

    def test_quote_menu_returns_only_exact_single_sentence_spans(self):
        text = "Rates\nDefault interest rates are not permitted.\nThe spread in the Note may not be changed without written agreement."
        options = quote_options(text, "Note rate spread default interest rates")
        self.assertTrue(options)
        for quote in options:
            self.assertIn(quote, text)
            self.assertIsNone(applied_evidence_error(quote, "The proposed increase triggers this rule.", text))

    def test_quote_id_cannot_cross_source_or_guess_text(self):
        conclusion = {"citations": [{"source_id": 1, "quote_id": 0}, {"source_id": 2, "quote_id": 1}]}
        resolve_applied_quotes(conclusion, {1: ["Exact source one."], 2: ["Exact source two."]})
        self.assertEqual(conclusion["citations"][0]["quote"], "Exact source one.")
        self.assertEqual(conclusion["citations"][1]["quote"], "")

    def test_grounded_rate_application_requires_both_real_operative_rules(self):
        from types import SimpleNamespace
        source = SimpleNamespace(source_id=3, chunk_text=(
            "The spread above the base rate as identified in the Note may not be "
            "changed during the life of the loan without the written agreement of "
            "the Borrower.\nDefault interest rates are not permitted."
        ))
        issue = preserve_compound_issues(CASE["question"], [])[1]["question"]
        self.assertIsNone(grounded_covenant_conclusion(CASE["question"], issue, []))
        conclusion = grounded_covenant_conclusion(CASE["question"], issue, [source])
        self.assertIsNotNone(conclusion)
        self.assertIn("1.00%", conclusion["text"])
        self.assertIn("facts do not establish", conclusion["text"])
        for citation in conclusion["citations"]:
            self.assertIsNone(applied_evidence_error(
                citation["quote"], citation["application"], source.chunk_text
            ))

    def test_default_only_and_definition_only_answers_fail_closed(self):
        self.assertIsNotNone(conclusion_scope_error({
            "kind": "conclusion", "requested_question": "Interest / note-rate rules",
            "text": "The default rate is prohibited.", "citations": [],
        }))
        self.assertIsNotNone(conclusion_scope_error({
            "kind": "conclusion", "requested_question": "Preference",
            "text": "This is prohibited.", "citations": [{"quote": "Preference means a preferred position."}],
        }))

    def test_bottom_line_preserves_unsupported_issue(self):
        result = synthesize_bottom_line([
            {"question": "Preference", "applied_conclusion": None},
            {"question": "Interest rate", "applied_conclusion": {"text": "The Note-rate rule applies."}},
        ])
        self.assertIn("Preference Not addressed by retrieved provisions.", result)
        self.assertIn("Interest rate", result)

    def test_evaluator_does_not_pass_empty_answers(self):
        checks = evaluate(CASE, {"subanswers": [], "sources": []})
        self.assertFalse(checks["distinct sub-issues"])
        self.assertFalse(checks["applied citations have verified quotes and explanations"])
        self.assertFalse(checks["rejected evidence includes reasons"])

    def test_evaluator_cannot_use_hidden_chunk_text_as_substance_framing(self):
        result = {
            "subanswers": [{
                "requested_question": "Interest-rate rules",
                "applied_conclusion": {
                    "text": "This is a prohibited default rate.",
                    "citations": [{
                        "quote": "The maximum fixed interest rate is capped.",
                        "application": "Default rates are not permitted.",
                        "source_chunk": "The Note rate and spread may not change.",
                    }],
                },
            }],
        }
        checks = evaluate(CASE, result)
        self.assertFalse(checks["substance over default-rate label"])
        self.assertFalse(checks["operative quotes address: Interest-rate rules"])

    def test_explicit_comparison_permits_named_programs(self):
        tags = classify_question("Compare Standard 7(a) and Export Express default rates.")
        self.assertEqual(set(tags["product_lines"]), {"standard_7a", "export_express"})


if __name__ == "__main__":
    unittest.main()
