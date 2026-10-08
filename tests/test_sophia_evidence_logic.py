import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "artifacts/api-server"))
from evidence_logic import (
    permission_scope_error, signer_obligations, missing_signer_obligations,
    source_role_schema, assemble_source_role_claims,
)
from sophia_issues import sentences

OBSERVED = json.loads((ROOT / "tests/fixtures/sophia_observed_failures.json").read_text())


class EvidenceLogicTests(unittest.TestCase):
    def test_observed_signed_consent_overclaim_is_rejected(self):
        self.assertIn("signed a written agreement", OBSERVED["permission"]["question"])
        self.assertIsNotNone(permission_scope_error(OBSERVED["permission"]["candidate"]))

    def test_a_prerequisite_result_is_not_itself_a_permission_claim(self):
        candidate = copy.deepcopy(OBSERVED["permission"]["candidate"])
        candidate["text"] = "The supplied written agreement meets the cited written-consent condition."
        self.assertIsNone(permission_scope_error(candidate))

    def test_negative_result_is_not_mistaken_for_positive_permission(self):
        candidate = {"kind": "conclusion", "text": "This action is not permitted.", "citations": []}
        self.assertIsNone(permission_scope_error(candidate))

    def test_affirmative_authority_is_distinct_from_without_condition(self):
        # Parser controls, not legal-answer fixtures.
        candidate = {"kind": "conclusion", "text": "The action is permitted.", "citations": [
            {"quote": "The operator may perform the action with the specified consent."}
        ]}
        self.assertIsNone(permission_scope_error(candidate))
        candidate["citations"][0]["quote"] = "The operator may not perform the action without consent."
        self.assertIsNotNone(permission_scope_error(candidate))

    def test_observed_signer_omission_is_detected_from_source(self):
        candidate = OBSERVED["signer"]["candidate"]
        targets = signer_obligations(candidate["policy_issue"], candidate["requested_question"])
        self.assertTrue(any(target["subject"].lower() == "trustor" for target in targets))
        missing = missing_signer_obligations(candidate)
        self.assertTrue(any(target["subject"].lower() == "trustor" for target in missing))

    def test_role_presence_in_fact_echo_cannot_fill_a_missing_conclusion(self):
        candidate = copy.deepcopy(OBSERVED["signer"]["candidate"])
        candidate["stated_facts"] = ["The Trustor is identified."]
        self.assertTrue(any(
            target["subject"].lower() == "trustor" for target in missing_signer_obligations(candidate)
        ))

    def test_role_ledger_is_not_a_hard_coded_list(self):
        issue = {"clauses": [{"source_id": 1, "quote": "The Custodian must sign the guaranty."}]}
        self.assertEqual(signer_obligations(issue, "Who must sign?")[0]["subject"], "Custodian")
        self.assertEqual(signer_obligations(issue, "Does ownership aggregate?"), [])

    def test_cross_reference_abbreviation_does_not_truncate_execution_clause(self):
        text = "The trustee must execute the guaranty as described in Para. A.2., Conditions for trusts. In addition, the Trustor must personally guarantee the loan."
        self.assertEqual(len(sentences(text)), 2)
        self.assertIn("Para. A.2.", sentences(text)[0])

    def test_each_observed_source_role_gets_a_required_own_quote_slot(self):
        candidate = OBSERVED["signer"]["candidate"]
        targets = signer_obligations(candidate["policy_issue"], candidate["requested_question"])
        menu = {1: [target["quote"] for target in targets]}
        schema = source_role_schema(targets, menu)
        self.assertEqual(len(schema["required"]), len(targets))
        for index, target in enumerate(targets):
            citation = schema["properties"][f"role_{index}"]["properties"]["citations"]["items"]
            self.assertEqual(citation["properties"]["quote_id"]["enum"], [index])
            self.assertEqual(citation["properties"]["source_id"]["enum"], [target["source_id"]])

    def test_assembly_does_not_invent_an_application_for_missing_role(self):
        candidate = OBSERVED["signer"]["candidate"]
        targets = signer_obligations(candidate["policy_issue"], candidate["requested_question"])
        menu = {1: [target["quote"] for target in targets]}
        observed = candidate["citations"][0]
        applications = {"role_0": {
            "text": observed["application"],
            "citations": [{"source_id": 1, "quote_id": 0, "application": observed["application"]}],
        }}
        assembled = assemble_source_role_claims(applications, targets, menu)
        self.assertEqual(assembled["text"], observed["application"])
        self.assertEqual(assembled["citations"][0]["application"], assembled["text"])
        self.assertNotIn("Trustor", assembled["text"])
        assembled.update(kind="conclusion", policy_issue=candidate["policy_issue"],
                         requested_question=candidate["requested_question"])
        self.assertTrue(any(target["subject"].lower() == "trustor"
                            for target in missing_signer_obligations(assembled)))


if __name__ == "__main__":
    unittest.main()
