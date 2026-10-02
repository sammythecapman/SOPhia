import unittest

from scripts.run_sop_regression import handcheck_details, select_cases


class RegressionOptionTests(unittest.TestCase):
    def test_case_selection_uses_requested_order(self):
        cases = [{"id": "trust-aggregate"}, {"id": "robs"}, {"id": "threshold"}]
        self.assertEqual(
            select_cases(cases, ["trust-aggregate", "robs"]),
            [cases[0], cases[1]],
        )

    def test_unknown_case_id_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            select_cases([{"id": "trust-aggregate"}], ["missing"])

    def test_handcheck_report_includes_answer_and_compact_citations(self):
        details = handcheck_details(
            {
                "answer": "The interests aggregate to 20 percent.",
                "sources": [
                    {
                        "source_id": "sop-93",
                        "section_ref": "Guaranties",
                        "page_number": 93,
                        "quote": "Ownership held by trusts is aggregated.",
                        "applicability_status": "applicable",
                        "verified": True,
                        "quote_located": True,
                        "source_chunk": "Do not copy full source chunks into the report.",
                    }
                ],
                "subanswers": [
                    {
                        "guarantor_rows": [
                            {
                                "party": "Trust A",
                                "ownership_percentage": 12,
                                "ownership_comparison": (
                                    "Aggregate ownership across 2 trusts is 20 percent."
                                ),
                                "status": "required",
                                "citations": [{"source_id": "sop-93"}],
                            }
                        ]
                    }
                ],
            }
        )
        self.assertIn("20 percent", details["sample_answer"])
        self.assertEqual(details["guarantor_rows"][0]["party"], "Trust A")
        self.assertEqual(
            details["guarantor_rows"][0]["ownership_percentage"],
            12,
        )
        self.assertEqual(details["source_citations"][0]["page_number"], 93)
        self.assertNotIn("source_chunk", details["source_citations"][0])


if __name__ == "__main__":
    unittest.main()