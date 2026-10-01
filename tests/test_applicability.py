import os
import sys
import unittest
from contextlib import contextmanager
from pathlib import Path


API_SERVER = Path(__file__).resolve().parents[1] / "artifacts" / "api-server"
sys.path.insert(0, str(API_SERVER))

# Importing app.py validates corpus metadata at startup. Keep these unit tests
# independent of Replit secrets and databases by supplying a small in-memory DB.
os.environ.setdefault("DATABASE_URL", "postgresql://unit-test.invalid/sop")
os.environ.setdefault("OPENAI_API_KEY", "unit-test-placeholder")
os.environ.setdefault("SESSION_SECRET", "unit-test-session-secret")

import db  # noqa: E402


class _StartupCursor:
    def __init__(self, row):
        self.row = row

    def fetchone(self):
        return self.row


class _StartupConnection:
    def execute(self, statement, parameters=()):
        if "FROM corpus_metadata" in statement:
            return _StartupCursor(
                (
                    "SOP 50 10 8.1",
                    "https://www.sba.gov/document/sop-50-10-lender-development-company-loan-programs",
                    "unit-test-sha256",
                    "2026-10-01",
                    1,
                )
            )
        if "SELECT COUNT(*)" in statement:
            return _StartupCursor((1,))
        raise AssertionError(f"Unexpected startup SQL: {statement}")


@contextmanager
def _startup_connection():
    yield _StartupConnection()


db.connection = _startup_connection

from applicability import applicability_check, classify_text  # noqa: E402
from app import (  # noqa: E402
    RetrievedSource,
    augment_extracted_party_capacities,
    build_lexical_search_query,
    build_retrieval_searches,
    candidate_admitted,
    conclusion_has_cited_issue_focus,
    condition_trigger_is_established,
    enumerate_guarantor_rows_from_inputs,
    evaluate_source_gate,
    fetch_adjacent_chunk_rows,
    has_guaranty_intent,
    internal_conditions_check,
    select_context_sources,
    unresolved_adjacent_trigger,
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
    def test_retrieval_keeps_material_facts_as_separate_searches(self):
        fact = "The borrower leases premises month-to-month."
        searches = build_retrieval_searches(
            "Which guaranty rules apply?",
            ["SBA guaranty policy"],
            [fact],
            "The borrower leases premises month-to-month. Which guaranty rules apply?",
        )

        self.assertIn(fact, searches)
        self.assertIn(
            "The borrower leases premises month-to-month. Which guaranty rules apply?",
            searches,
        )
        lexical_query = build_lexical_search_query(
            "The borrower leases premises month-to-month."
        )
        self.assertIn("lease", lexical_query)
        self.assertIn("premises", lexical_query)
        self.assertIn(" OR ", lexical_query)

    def test_generic_ownership_does_not_trigger_guaranty_flow(self):
        self.assertFalse(
            has_guaranty_intent(
                "Does ownership of leased premises affect business eligibility?"
            )
        )
        self.assertTrue(
            has_guaranty_intent("Which owners must sign the guaranty?")
        )

    def test_adjacent_context_is_limited_to_same_section_and_corpus(self):
        source = RetrievedSource(
            db_id=48,
            source_id=1,
            sop_version="SOP 50 10 8.1",
            effective_date="2026-10-01",
            page_number=54,
            section_ref="Section A > Occupancy and Leasing Requirements",
            chunk_text="Trigger passage.",
            similarity=0.8,
        )
        neighbor_row = (
            49,
            "SOP 50 10 8.1",
            "2026-10-01",
            54,
            source.section_ref,
            "Operative lease-term passage.",
            0.79,
            [],
            [],
            [],
            [],
            [],
            [],
        )

        class Cursor:
            def fetchall(self):
                return [neighbor_row]

        class Connection:
            def __init__(self):
                self.sql = ""
                self.params = ()

            def execute(self, sql, params):
                self.sql = sql
                self.params = params
                return Cursor()

        conn = Connection()
        rows = fetch_adjacent_chunk_rows(
            conn,
            [source],
            "SOP 50 10 8.1",
            "corpus-hash",
        )

        self.assertEqual([row[0] for row in rows], [49])
        self.assertIn("id = ANY(%s) AND section_ref = %s", conn.sql)
        self.assertEqual(conn.params[-1], source.section_ref)
        self.assertEqual(conn.params[2:4], ("SOP 50 10 8.1", "corpus-hash"))

    def test_context_trimming_keeps_same_section_neighbors_together(self):
        section = "Section A > Occupancy and Leasing Requirements"
        anchor = RetrievedSource(
            db_id=48,
            source_id=1,
            sop_version="SOP 50 10 8.1",
            effective_date="2026-10-01",
            page_number=54,
            section_ref=section,
            chunk_text="Trigger.",
            similarity=0.8,
        )
        neighbor = RetrievedSource(
            db_id=49,
            source_id=2,
            sop_version="SOP 50 10 8.1",
            effective_date="2026-10-01",
            page_number=54,
            section_ref=section,
            chunk_text="Operative rule.",
            similarity=0.6,
        )
        unrelated = RetrievedSource(
            db_id=90,
            source_id=3,
            sop_version="SOP 50 10 8.1",
            effective_date="2026-10-01",
            page_number=342,
            section_ref="Section A > Changes of Ownership",
            chunk_text="Unrelated issue.",
            similarity=0.7,
        )

        selected = select_context_sources([anchor, neighbor, unrelated], limit=2)

        self.assertEqual([source.db_id for source in selected], [48, 49])

    def test_conclusion_must_overlap_requested_issue_and_citation(self):
        self.assertFalse(
            conclusion_has_cited_issue_focus(
                "Does a month-to-month premises lease affect eligibility?",
                "A month-to-month lease does not make the purchaser ineligible.",
                "Section A > Changes of Ownership\nThe purchaser may use proceeds to acquire the business.",
            )
        )
        supported_cases = [
            (
                "Does collateral secure the shortfall?",
                "The collateral rules address the shortfall.",
                "Collateral requirements for a shortfall are stated here.",
            ),
            (
                "Does affiliation affect eligibility?",
                "Affiliation affects the eligibility analysis.",
                "Affiliated businesses are treated together for eligibility.",
            ),
            (
                "May loan proceeds fund this use?",
                "The proceeds may fund this use.",
                "Use of proceeds includes this expense.",
            ),
            (
                "Does the 504 debenture rule apply?",
                "The 504 debenture rule applies.",
                "For a 504 debenture, this requirement applies.",
            ),
        ]
        for requested, conclusion, evidence in supported_cases:
            with self.subTest(requested=requested):
                self.assertTrue(
                    conclusion_has_cited_issue_focus(
                        requested,
                        conclusion,
                        evidence,
                    )
                )

    def test_unstated_split_trigger_blocks_unqualified_claims(self):
        section = "Section A > Occupancy and Leasing Requirements"
        previous = RetrievedSource(
            db_id=48,
            source_id=1,
            sop_version="SOP 50 10 8.1",
            effective_date="2026-10-01",
            page_number=54,
            section_ref=section,
            chunk_text=(
                "When the borrower funds leasehold improvements with proceeds "
                "above the program threshold:"
            ),
            similarity=0.8,
        )
        operative = RetrievedSource(
            db_id=49,
            source_id=2,
            sop_version="SOP 50 10 8.1",
            effective_date="2026-10-01",
            page_number=54,
            section_ref=section,
            chunk_text="The lender must obtain the written lease.",
            similarity=0.79,
        )
        candidate = {
            "kind": "conclusion",
            "text": "A month-to-month lease does not satisfy the lease-term rule.",
            "citations": [{"source_id": 2, "quote": operative.chunk_text}],
            "applicable_source_ids": [1, 2],
        }

        trigger = unresolved_adjacent_trigger(
            candidate,
            "The borrower operates from premises under a month-to-month lease.",
            {1: previous, 2: operative},
        )

        self.assertEqual(trigger["source_id"], 1)
        self.assertIn("leasehold improvements", trigger["text"])

    def test_qualified_claim_or_established_trigger_is_not_blocked(self):
        section = "Section A > Occupancy and Leasing Requirements"
        previous = RetrievedSource(
            db_id=48,
            source_id=1,
            sop_version="SOP 50 10 8.1",
            effective_date="2026-10-01",
            page_number=54,
            section_ref=section,
            chunk_text=(
                "When the borrower funds leasehold improvements with proceeds "
                "above the program threshold:"
            ),
            similarity=0.8,
        )
        operative = RetrievedSource(
            db_id=49,
            source_id=2,
            sop_version="SOP 50 10 8.1",
            effective_date="2026-10-01",
            page_number=54,
            section_ref=section,
            chunk_text="The lender must obtain the written lease.",
            similarity=0.79,
        )
        sources = {1: previous, 2: operative}
        facts = "The borrower operates under a month-to-month lease."
        qualified = {
            "kind": "conclusion",
            "text": (
                "The rule applies if proceeds fund leasehold improvements above "
                "the threshold; the question does not state the use of proceeds."
            ),
            "citations": [{"source_id": 2, "quote": operative.chunk_text}],
            "applicable_source_ids": [1, 2],
        }
        established = {
            **qualified,
            "text": "The borrower funds leasehold improvements with loan proceeds.",
        }

        self.assertIsNone(unresolved_adjacent_trigger(qualified, facts, sources))
        self.assertTrue(
            condition_trigger_is_established(
                previous.chunk_text,
                "The borrower will fund leasehold improvements with loan proceeds "
                "above the program threshold.",
            )
        )
        self.assertIsNone(
            unresolved_adjacent_trigger(
                established,
                "The borrower will fund leasehold improvements with loan proceeds "
                "above the program threshold.",
                sources,
            )
        )

    def test_split_numeric_trigger_requires_both_threshold_dimensions(self):
        trigger = (
            "When the applicant uses $500,000 or 30 percent of proceeds, "
            "whichever is less, for equipment:"
        )

        self.assertFalse(
            condition_trigger_is_established(
                trigger,
                "The applicant uses proceeds for equipment.",
            )
        )
        self.assertTrue(
            condition_trigger_is_established(
                trigger,
                "The applicant will use $700,000 and 35 percent of proceeds for equipment.",
            )
        )

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

    def test_direct_ownership_does_not_leak_across_adjacent_owner_clauses(self):
        parties = [
            {
                "party": "Retirement Plan",
                "ownership_percentage": 68,
                "capacities": [{"name": "entity owner", "evidence": "plan owner"}],
            }
        ]

        augmented = augment_extracted_party_capacities(
            "The retirement plan holds 68 percent and the individual holds "
            "32 percent directly.",
            parties,
        )

        self.assertEqual(augmented[0]["party"], "Retirement Plan")
        self.assertEqual(augmented[0]["ownership_percentage"], 68)
        self.assertEqual(
            [capacity["name"] for capacity in augmented[0]["capacities"]],
            ["entity owner"],
        )
        self.assertEqual(augmented[1]["party"], "individual")
        self.assertEqual(augmented[1]["ownership_percentage"], 32)
        self.assertEqual(
            [capacity["name"] for capacity in augmented[1]["capacities"]],
            ["direct owner"],
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