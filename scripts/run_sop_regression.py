#!/usr/bin/env python3
"""Run the SOP regression set against the local API and score grounding safety."""

import argparse
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen


def query(base_url: str, question: str) -> dict:
    request = Request(
        f"{base_url.rstrip('/')}/api/sop/query",
        data=json.dumps({"question": question}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=180) as response:
        return json.load(response)


def baseline_regression_failures(result: dict) -> list[str]:
    """Blocking assertions for the baseline ROBS fact pattern."""
    failures: list[str] = []
    summary = (result.get("summary") or "").strip()
    if not summary or "no applied conclusion was established" in summary.casefold():
        failures.append("empty or generic bottom line")

    subanswers = result.get("subanswers", [])
    for subanswer in subanswers:
        telemetry = subanswer.get("gate_telemetry", [])
        admitted = any(entry.get("result") == "admitted" for entry in telemetry)
        conclusion = subanswer.get("applied_conclusion") or {}
        if admitted and not conclusion.get("text", "").strip():
            failures.append(
                f"{subanswer.get('subquestion_id', subanswer.get('question'))}: empty applied conclusion"
            )
        subquestion_id = subanswer.get("subquestion_id")
        artifacts = []
        if conclusion:
            artifacts.append(conclusion)
        artifacts.extend(subanswer.get("propositions", []))
        artifacts.extend(subanswer.get("guarantor_rows", []))
        for artifact in artifacts:
            if artifact.get("artifact_subquestion_id") != subquestion_id:
                failures.append(
                    f"artifact routed outside {subquestion_id or subanswer.get('question')}"
                )
        for entry in telemetry:
            required = {
                "chunk_id",
                "breadcrumb",
                "page",
                "tags",
                "fact_values",
                "excluded_dimension",
                "conditions",
                "condition_result",
                "subquestion_id",
                "reached_applied_conclusion",
            }
            if not required.issubset(entry):
                failures.append("incomplete per-chunk telemetry")
                break

    admitted_pages = {
        source.get("page_number")
        for source in result.get("sources", [])
        if source.get("applicability_status") == "applicable"
    }
    if 47 not in admitted_pages:
        failures.append("page 47 was not admitted")
    if 93 not in admitted_pages:
        failures.append("page 93 was not admitted")

    rejected_page_150 = [
        source
        for subanswer in subanswers
        for source in subanswer.get("rejected_citations", [])
        if source.get("page_number") == 150
    ]
    if not rejected_page_150:
        failures.append("page 150 CAPLines provision was not excluded")
    elif not any(
        "product" in (source.get("applicability_reason") or "").casefold()
        for source in rejected_page_150
    ):
        failures.append("page 150 exclusion did not identify product mismatch")

    rows = [
        row
        for subanswer in subanswers
        for row in subanswer.get("guarantor_rows", [])
    ]
    for party, capacity in [
        ("buyer", "direct owner"),
        ("buyer", "plan sponsor"),
        ("buyer", "trustee"),
        ("plan", "entity owner"),
    ]:
        if not any(
            party in row.get("party", "").casefold()
            and capacity in row.get("capacity", "").casefold()
            for row in rows
        ):
            failures.append(f"missing guarantor row: {party}/{capacity}")
    if len(rows) < 4:
        failures.append(f"only {len(rows)} guarantor rows were produced")
    if any(not row.get("citations") for row in rows):
        failures.append("guarantor row lacks a triggering citation")
    row_citation_ids = {
        citation.get("source_id")
        for row in rows
        for citation in row.get("citations", [])
    }
    admitted_guaranty_ids = {
        source.get("source_id")
        for source in result.get("sources", [])
        if source.get("applicability_status") == "applicable"
        and (
            source.get("page_number") in {47, 93}
        )
    }
    if not admitted_guaranty_ids.issubset(row_citation_ids):
        failures.append("an admitted guaranty provision lacks a triggering row citation")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("tests/sop_regression.json"),
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text())

    phantom_citations = 0
    unsupported_failures = 0
    section_failures = 0
    support_signal_failures = 0
    citation_failures = 0
    arithmetic_failures = 0
    negative_audit_failures = 0
    date_warning_failures = 0
    applicability_failures = 0
    guarantor_row_failures = 0
    baseline_failures = 0

    for case in cases:
        result = query(args.base_url, case["question"])
        sources = result.get("sources", [])
        supported_propositions = []
        for subanswer in result.get("subanswers", []):
            if subanswer.get("applied_conclusion"):
                supported_propositions.append(subanswer["applied_conclusion"])
            supported_propositions.extend(subanswer.get("propositions", []))
        supported_propositions.extend(result.get("other_issues", []))
        citation_failure = any(
            not proposition.get("citations")
            or any(
                not citation.get("quote_located")
                or not citation.get("verified")
                for citation in proposition.get("citations", [])
            )
            for proposition in supported_propositions
        )
        phantom = any(
            not source.get("quote_located")
            or " ".join(source.get("quote", "").split()).casefold()
            not in " ".join(source.get("source_chunk", "").split()).casefold()
            for source in sources
        )
        signal_failure = any(
            not citation.get("quote_located")
            or not citation.get("supports_conclusion")
            for proposition in supported_propositions
            for citation in proposition.get("citations", [])
        )
        section_text = " ".join(source.get("section_ref", "") for source in sources)
        section_failure = bool(case["expected_sections"]) and not any(
            expected.casefold() in section_text.casefold()
            for expected in case["expected_sections"]
        )
        unsupported_failure = case["unsupported"] and any(
            subanswer.get("applied_conclusion")
            or subanswer.get("support_status") == "supported"
            for subanswer in result.get("subanswers", [])
        )
        arithmetic_failure = case.get("expect_arithmetic", False) and any(
            not proposition.get("arithmetic_valid", False)
            for proposition in supported_propositions
        )
        negative_audit_failure = case.get("expect_not_established", False) and not any(
            subanswer.get("support_status") == "not_established"
            for subanswer in result.get("subanswers", [])
        )
        forbidden_supported_sections = case.get("forbidden_supported_sections", [])
        supported_section_text = " ".join(
            citation.get("section_ref", "")
            for proposition in supported_propositions
            for citation in proposition.get("citations", [])
        )
        forbidden_section_failure = any(
            forbidden.casefold() in supported_section_text.casefold()
            for forbidden in forbidden_supported_sections
        )
        date_warning_failure = case.get("expect_date_warning", False) and not result.get(
            "date_warning"
        )
        all_rows = [
            row
            for subanswer in result.get("subanswers", [])
            for row in subanswer.get("guarantor_rows", [])
        ]
        expected_rows = case.get("expect_guarantor_rows", [])
        row_failure = any(
            not any(
                expected.get("party", "").casefold() in row.get("party", "").casefold()
                and expected.get("capacity", "").casefold()
                in row.get("capacity", "").casefold()
                and (
                    not expected.get("status")
                    or expected["status"] == row.get("status")
                )
                for row in all_rows
            )
            for expected in expected_rows
        )
        unresolved_failure = case.get("expect_unresolved_guarantor", False) and not any(
            row.get("status") == "unresolved" for row in all_rows
        )
        applicability_failure = case.get("expect_not_applicable", False) and not (
            any(
                subanswer.get("support_status") == "not_applicable"
                for subanswer in result.get("subanswers", [])
            )
            or any(
                citation.get("applicability_status") == "not_applicable"
                for subanswer in result.get("subanswers", [])
                for citation in subanswer.get("rejected_citations", [])
            )
        )
        baseline_failure_details = (
            baseline_regression_failures(result)
            if case["id"] == "guarantor-enumeration-robs"
            else []
        )
        baseline_failure = bool(baseline_failure_details)

        phantom_citations += int(phantom)
        citation_failures += int(citation_failure)
        support_signal_failures += int(signal_failure)
        section_failures += int(section_failure)
        unsupported_failures += int(unsupported_failure)
        arithmetic_failures += int(arithmetic_failure)
        negative_audit_failures += int(negative_audit_failure or forbidden_section_failure)
        date_warning_failures += int(date_warning_failure)
        applicability_failures += int(applicability_failure)
        guarantor_row_failures += int(row_failure or unresolved_failure)
        baseline_failures += int(baseline_failure)
        status = "PASS" if not any(
            (
                phantom,
                citation_failure,
                signal_failure,
                section_failure,
                unsupported_failure,
                arithmetic_failure,
                negative_audit_failure,
                forbidden_section_failure,
                date_warning_failure,
                applicability_failure,
                row_failure,
                unresolved_failure,
                baseline_failure,
            )
        ) else "FAIL"
        print(
            f"{status} {case['id']}: sources={len(sources)} "
            f"phantom={phantom} citations={citation_failure} "
            f"support_signal={signal_failure} section={section_failure} "
            f"unsupported={unsupported_failure} arithmetic={arithmetic_failure} "
            f"negative_audit={negative_audit_failure or forbidden_section_failure} "
            f"date_warning={date_warning_failure} applicability={applicability_failure} "
            f"guarantor_rows={row_failure or unresolved_failure}"
            + (
                f" baseline={'; '.join(baseline_failure_details)}"
                if baseline_failure
                else ""
            )
        )

    print(
        json.dumps(
            {
                "cases": len(cases),
                "phantom_citation_rate": phantom_citations / len(cases),
                "citation_failures": citation_failures,
                "support_signal_failures": support_signal_failures,
                "section_failures": section_failures,
                "unsupported_failures": unsupported_failures,
                "arithmetic_failures": arithmetic_failures,
                "negative_audit_failures": negative_audit_failures,
                "date_warning_failures": date_warning_failures,
                "applicability_failures": applicability_failures,
                "guarantor_row_failures": guarantor_row_failures,
                "baseline_failures": baseline_failures,
            },
            indent=2,
        )
    )
    return int(
        any(
            (
                phantom_citations,
                citation_failures,
                support_signal_failures,
                section_failures,
                unsupported_failures,
                arithmetic_failures,
                negative_audit_failures,
                date_warning_failures,
                applicability_failures,
                guarantor_row_failures,
                baseline_failures,
            )
        )
    )


if __name__ == "__main__":
    sys.exit(main())