import sys
import unittest
from pathlib import Path


API_SERVER = Path(__file__).resolve().parents[1] / "artifacts" / "api-server"
sys.path.insert(0, str(API_SERVER))

from applicability import applicability_check, classify_text  # noqa: E402
from app import (  # noqa: E402
    RetrievedSource,
    augment_extracted_party_capacities,
    candidate_admitted,
    enumerate_guarantor_rows_from_inputs,
    evaluate_source_gate,
    internal_conditions_check,
    validate_candidate_citations,
)


def empty_facts():
    return {
        "transaction_types": [],
        "entity_structures": [],
        "party_roles": [],
        "program_scopes": [],
        "product_lines": [],
        "loan_size_bands": [],
    }


class ApplicabilityRegressionTests(unittest.TestCase):
    def test_missing_fact_dimension_does_not_exclude(self):
        source = {
            "transaction_types": ["change_of_ownership"],
            "entity_structures": [],
            "party_roles": [],
            "program_scopes": [],
            "product_lines": ["standard_7a"],
            "loan_size_bands": ["over_350k"],
        }

        applicable, reason = applicability_check(source, empty_facts())

        self.assertTrue(applicable)
        self.assertIsNone(reason)

    def test_affirmative_conflict_still_excludes(self):
        source = {
            "transaction_types": [],
            "entity_structures": [],
            "party_roles": [],
            "program_scopes": [],
            "product_lines": ["standard_7a"],
            "loan_size_bands": [],
        }
        facts = {**empty_facts(), "product_lines": ["7a_small"]}

        applicable, reason = applicability_check(source, facts)

        self.assertFalse(applicable)
        self.assertIn("Standard 7(a)", reason or "")

    def test_universal_core_section_has_no_narrow_product_gate(self):
        tags = classify_text(
            "The lender must comply with the applicable requirements.",
            "Section A > Core Requirements for all 7(a) and 504 Loans",
        )

        self.assertEqual(tags["product_lines"], [])
        self.assertEqual(tags["loan_size_bands"], [])

    def test_unparsed_startup_condition_fails_open(self):
        source = RetrievedSource(
            db_id=1,
            source_id=1,
            sop_version="SOP 50 10 8.1",
            effective_date="2025-06-01",
            page_number=47,
            section_ref="Section A",
            chunk_text="For a start-up business, the lender must document the injection.",
            similarity=1.0,
        )

        applicable, reason = internal_conditions_check(
            source,
            "The question does not state whether this is a start-up.",
            empty_facts(),
        )

        self.assertTrue(applicable)
        self.assertIsNone(reason)

    def test_affirmative_existing_business_conflict_excludes(self):
        source = RetrievedSource(
            db_id=1,
            source_id=1,
            sop_version="SOP 50 10 8.1",
            effective_date="2025-06-01",
            page_number=47,
            section_ref="Section A",
            chunk_text="For a start-up business, the lender must document the injection.",
            similarity=1.0,
        )

        applicable, reason = internal_conditions_check(
            source,
            "This is an existing operating business.",
            empty_facts(),
        )

        self.assertFalse(applicable)
        self.assertIn("existing business", reason or "")

    def test_gate_evaluates_conditions_even_when_applicability_excludes(self):
        source = RetrievedSource(
            db_id=1,
            source_id=9,
            sop_version="SOP 50 10 8.1",
            effective_date="2025-06-01",
            page_number=47,
            section_ref="Section A",
            chunk_text="For a start-up business, the lender must document the injection.",
            similarity=1.0,
            product_lines=("standard_7a",),
        )

        gate = evaluate_source_gate(
            source,
            "This is an existing operating business.",
            {**empty_facts(), "product_lines": ["7a_small"]},
        )

        self.assertFalse(gate["applicable"])
        self.assertEqual(gate["condition_result"], "failed")
        self.assertFalse(gate["admitted"])
        self.assertTrue(gate["conditions"])

    def test_candidate_validation_rechecks_recorded_gate(self):
        source = RetrievedSource(
            db_id=1,
            source_id=10,
            sop_version="SOP 50 10 8.1",
            effective_date="2025-06-01",
            page_number=47,
            section_ref="Section A",
            chunk_text="The lender must document the injection.",
            similarity=1.0,
        )

        candidates = validate_candidate_citations(
            [
                {
                    "kind": "proposition",
                    "text": "The lender must document the injection.",
                    "citations": [{"source_id": 10, "quote": source.chunk_text}],
                    "applicable_source_ids": [10],
                    "gate_by_source_id": {
                        10: {
                            "admitted": False,
                            "condition_result": "failed",
                            "conditions": [],
                        }
                    },
                }
            ],
            {10: source},
        )

        self.assertEqual(candidates, [])

    def test_guarantor_enumeration_preserves_unmatched_capacity_rows(self):
        parties = [
            {
                "party": "individual",
                "ownership_percentage": 60,
                "capacities": [
                    {"name": "direct owner", "evidence": "owns directly"},
                    {"name": "plan sponsor", "evidence": "sponsors the plan"},
                ],
            },
            {
                "party": "plan",
                "ownership_percentage": 40,
                "capacities": [{"name": "entity owner", "evidence": "holds ownership"}],
            },
        ]
        provisions = [
            {
                "source_id": 20,
                "quote": "The direct owner must provide a full guaranty.",
                "subject_terms": ["individual"],
                "capacity_terms": ["direct owner"],
                "applies_to_all": False,
                "obligation_text": "The direct owner must provide a full guaranty.",
                "guaranty_type": "full",
                "conditions": "",
            },
            {
                "source_id": 21,
                "quote": "The plan must provide a guaranty as entity owner.",
                "subject_terms": ["plan"],
                "capacity_terms": ["entity owner"],
                "applies_to_all": False,
                "obligation_text": "The plan must provide a guaranty as entity owner.",
                "guaranty_type": "full",
                "conditions": "",
            },
        ]

        rows = enumerate_guarantor_rows_from_inputs(parties, provisions)

        self.assertEqual(len(rows), 3)
        self.assertEqual(
            {
                (row["party"], row["capacity"], row["status"])
                for row in rows
            },
            {
                ("individual", "direct owner", "required"),
                ("individual", "plan sponsor", "unresolved"),
                ("plan", "entity owner", "required"),
            },
        )

    def test_relevance_is_required_for_candidate_admission(self):
        self.assertFalse(
            candidate_admitted(
                {
                    "entailment_supported": True,
                    "relevant_to_subquestion": False,
                    "admitted_for_render": False,
                }
            )
        )

    def test_direct_ownership_fact_adds_a_generic_capacity(self):
        parties = [
            {
                "party": "Individual",
                "ownership_percentage": None,
                "capacities": [{"name": "Trustee", "evidence": "trustee"}],
            }
        ]

        augmented = augment_extracted_party_capacities(
            "The individual holds 32 percent directly.", parties
        )

        self.assertEqual(augmented[0]["ownership_percentage"], 32)
        self.assertEqual(
            [capacity["name"] for capacity in augmented[0]["capacities"]],
            ["Trustee", "direct owner"],
        )

    def test_cardinality_constraint_does_not_become_every_party_obligation(self):
        rows = enumerate_guarantor_rows_from_inputs(
            [
                {
                    "party": "entity",
                    "ownership_percentage": 17,
                    "capacities": [{"name": "entity owner", "evidence": ""}],
                }
            ],
            [
                {
                    "source_id": 30,
                    "quote": "At least one individual or entity must guarantee the loan.",
                    "subject_terms": ["entity"],
                    "capacity_terms": [],
                    "applies_to_all": False,
                    "cardinality_constraint": True,
                    "obligation_text": "At least one individual or entity must guarantee the loan.",
                    "guaranty_type": "full",
                    "conditions": "",
                }
            ],
        )

        self.assertEqual(rows[0]["status"], "unresolved")
        self.assertEqual(rows[0]["citations"], [])


if __name__ == "__main__":
    unittest.main()