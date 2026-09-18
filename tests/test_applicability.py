import sys
import unittest
from pathlib import Path


API_SERVER = Path(__file__).resolve().parents[1] / "artifacts" / "api-server"
sys.path.insert(0, str(API_SERVER))

from applicability import applicability_check, classify_text  # noqa: E402
from app import RetrievedSource, internal_conditions_check  # noqa: E402


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


if __name__ == "__main__":
    unittest.main()