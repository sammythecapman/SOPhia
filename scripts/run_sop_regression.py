#!/usr/bin/env python3
"""Run the SOP regression set against the local API and score grounding safety."""

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def query(base_url: str, question: str, cookie: str | None = None) -> dict:
    headers = {"Content-Type": "application/json"}
    if cookie:
        headers["Cookie"] = cookie
    request = Request(
        f"{base_url.rstrip('/')}/api/sop/query",
        data=json.dumps({"question": question}).encode(),
        headers=headers,
        method="POST",
    )
    with urlopen(request, timeout=180) as response:
        return json.load(response)


def baseline_regression_failures(result: dict) -> list[str]:
    """Check grounded ROBS output without requiring unsupported guarantor rows."""
    failures: list[str] = []

    subanswers = result.get("subanswers", [])
    for subanswer in subanswers:
        telemetry = subanswer.get("gate_telemetry", [])
        admitted = any(entry.get("result") == "admitted" for entry in telemetry)
        conclusion = subanswer.get("applied_conclusion") or {}
        if admitted and not (
            conclusion.get("text", "").strip()
            or subanswer.get("propositions")
            or subanswer.get("guarantor_rows")
        ):
            failures.append(
                f"{subanswer.get('subquestion_id', subanswer.get('question'))}: "
                "no substantive answer or guarantor rows"
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
        ("individual", "direct owner"),
        ("individual", "plan sponsor"),
    ]:
        if not any(
            party in row.get("party", "").casefold()
            and capacity in row.get("capacity", "").casefold()
            and row.get("status") == "required"
            for row in rows
        ):
            failures.append(f"missing guarantor row: {party}/{capacity}")
    forbidden_required_rows = [
        ("plan", "direct owner"),
        ("plan", "entity owner"),
        ("individual", "plan participant"),
        ("individual", "trustee"),
    ]
    for party, capacity in forbidden_required_rows:
        if any(
            party in row.get("party", "").casefold()
            and capacity in row.get("capacity", "").casefold()
            and row.get("status") == "required"
            for row in rows
        ):
            failures.append(f"unsupported required guarantor row: {party}/{capacity}")
    if any(
        row.get("status") == "required" and not row.get("citations")
        for row in rows
    ):
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
    if not {47, 93}.issubset(
        {
            source.get("page_number")
            for source in result.get("sources", [])
            if source.get("source_id") in row_citation_ids
        }
    ):
        failures.append("required guarantor rows lack the ROBS and ownership citations")
    return failures


def _visible_answer_text(result: dict) -> str:
    """Collect answer text and structured answer rows, excluding source evidence."""
    parts: list[str] = []
    excluded = {
        "citations",
        "gate_telemetry",
        "retrieval_telemetry",
        "rejected_citations",
        "source_chunk",
        "chunk_text",
        "quote",
    }

    def add(value, depth: int = 0) -> None:
        if depth > 5 or value is None or isinstance(value, bool):
            return
        if isinstance(value, str):
            parts.append(value)
        elif isinstance(value, (int, float)):
            parts.append(str(value))
        elif isinstance(value, dict):
            for key, child in value.items():
                if key not in excluded and not key.endswith("_id"):
                    add(child, depth + 1)
        elif isinstance(value, list):
            for child in value:
                add(child, depth + 1)

    for key in ("answer", "summary", "support_note", "date_warning"):
        add(result.get(key))
    add(result.get("other_issues", []))
    for subanswer in result.get("subanswers", []):
        for key in ("answer", "support_note", "applied_conclusion", "propositions", "guarantor_rows"):
            add(subanswer.get(key))
    return "\n".join(parts)


def select_cases(cases: list[dict], case_ids: list[str] | None = None) -> list[dict]:
    """Select requested regression cases in the order supplied."""
    if not case_ids:
        return cases
    by_id = {case["id"]: case for case in cases}
    requested = list(dict.fromkeys(case_ids))
    missing = [case_id for case_id in requested if case_id not in by_id]
    if missing:
        raise ValueError(f"Unknown regression case ID(s): {', '.join(missing)}")
    return [by_id[case_id] for case_id in requested]


def handcheck_details(result: dict) -> dict:
    """Capture a concise answer and source citations without internal telemetry."""
    citation_fields = (
        "source_id",
        "section_ref",
        "page_number",
        "quote",
        "applicability_status",
        "verified",
        "quote_located",
    )
    return {
        "sample_answer": _visible_answer_text(result),
        "source_citations": [
            {
                field: source.get(field)
                for field in citation_fields
                if source.get(field) is not None
            }
            for source in result.get("sources", [])
        ],
    }


def _fact_tokens(text: str) -> list[str]:
    normalized = text.casefold()
    normalized = re.sub(
        r"(\d+(?:,\d{3})*(?:\.\d+)?)\s*%",
        lambda match: f"{match.group(1).replace(',', '')} percent",
        normalized,
    )
    normalized = normalized.replace("$", "").replace(",", "")
    normalized = re.sub(r"\bguarantee(?:s|d)?\b", "guaranty", normalized)
    normalized = re.sub(r"\bguarant(?:y|ies)\b", "guaranty", normalized)
    return re.findall(r"[a-z]+|\d+(?:\.\d+)?", normalized)


_FACT_STOP_WORDS = {"a", "an", "and", "for", "in", "of", "the", "to", "with"}


def expected_fact_is_present(expected: str, answer_text: str) -> bool:
    """Match expected fact terms within a sentence-sized answer window."""
    required = [
        token for token in _fact_tokens(expected) if token not in _FACT_STOP_WORDS
    ]
    if not required:
        return True
    sentences = re.split(r"[\n.!?;]+", answer_text)
    window_size = max(8, len(required) * 3)
    for sentence in sentences:
        tokens = _fact_tokens(sentence)
        for start in range(len(tokens)):
            window = set(tokens[start : start + window_size])
            if all(token in window for token in required):
                return True
    return False


def fetch_healthz(base_url: str) -> tuple[dict | None, str | None]:
    request = Request(
        f"{base_url.rstrip('/')}/api/healthz",
        headers={"Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response), None
    except HTTPError as exc:
        return None, f"HTTP {exc.code} {exc.reason}"
    except (URLError, OSError, TimeoutError) as exc:
        return None, str(exc)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path("tests/sop_regression.json"),
    )
    parser.add_argument(
        "--case-id",
        action="append",
        help="Run only this case; repeat to select several. Use this for a focused first hand-check.",
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:8080")
    parser.add_argument(
        "--cookie",
        default=os.getenv("SOP_REGRESSION_COOKIE"),
        help="Authenticated Cookie header value; defaults to SOP_REGRESSION_COOKIE.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        help="Write a JSON case-by-case report to this path.",
    )
    parser.add_argument(
        "--expected-source-sha256",
        help="Fail if /api/healthz does not report this exact corpus hash.",
    )
    parser.add_argument(
        "--delay-seconds",
        type=float,
        default=0,
        help="Pause between cases to stay below a deployment's rate limit.",
    )
    args = parser.parse_args()
    try:
        cases = select_cases(json.loads(args.cases.read_text()), args.case_id)
    except ValueError as exc:
        parser.error(str(exc))
    health, health_error = fetch_healthz(args.base_url)
    corpus_hash_failure = bool(
        args.expected_source_sha256
        and (
            not health
            or health.get("source_sha256") != args.expected_source_sha256
        )
    )

    phantom_citations = 0
    unsupported_failures = 0
    unqualified_condition_failures = 0
    trigger_note_failures = 0
    section_failures = 0
    support_signal_failures = 0
    citation_failures = 0
    arithmetic_failures = 0
    negative_audit_failures = 0
    date_warning_failures = 0
    applicability_failures = 0
    guarantor_row_failures = 0
    baseline_failures = 0
    expected_fact_failures = 0
    case_results: list[dict[str, object]] = []

    for case in cases:
        try:
            result = query(args.base_url, case["question"], args.cookie)
        except HTTPError as exc:
            error = f"HTTP {exc.code} {exc.reason}"
            print(f"ERROR {case['id']}: {error}", file=sys.stderr)
            case_results.append(
                {"id": case["id"], "status": "ERROR", "error": error}
            )
            for remaining in cases[len(case_results) :]:
                case_results.append(
                    {
                        "id": remaining["id"],
                        "status": "NOT_RUN",
                        "reason": "Stopped after the first request error.",
                    }
                )
            break
        except (URLError, OSError, TimeoutError) as exc:
            error = str(exc)
            print(f"ERROR {case['id']}: {error}", file=sys.stderr)
            case_results.append(
                {"id": case["id"], "status": "ERROR", "error": error}
            )
            for remaining in cases[len(case_results) :]:
                case_results.append(
                    {
                        "id": remaining["id"],
                        "status": "NOT_RUN",
                        "reason": "Stopped after the first request error.",
                    }
                )
            break
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
        unqualified_condition_failure = case.get(
            "expect_no_unqualified_applied_conclusion", False
        ) and any(
            (conclusion := subanswer.get("applied_conclusion") or {}).get("text")
            and not re.search(
                r"\b(?:if|when|unless|only\s+if|provided\s+that|depends\s+on|"
                r"not\s+established|not\s+stated|missing|cannot\s+determine|"
                r"unknown|unclear)\b",
                conclusion["text"],
                re.IGNORECASE,
            )
            for subanswer in result.get("subanswers", [])
        )
        trigger_note_failure = case.get(
            "expect_unresolved_trigger_note", False
        ) and not any(
            subanswer.get("support_status") == "not_established"
            and "trigger:" in (
                subanswer.get("support_note") or subanswer.get("answer") or ""
            ).casefold()
            and "leasehold improvements" in (
                subanswer.get("support_note") or subanswer.get("answer") or ""
            ).casefold()
            and any(
                citation.get("context_only")
                and citation.get("condition_result") == "unresolved"
                for citation in subanswer.get("rejected_citations", [])
            )
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
        forbidden_required_rows = case.get("expect_no_required_guarantor_rows", [])
        forbidden_row_failure = any(
            any(
                expected.get("party", "").casefold() in row.get("party", "").casefold()
                and expected.get("capacity", "").casefold()
                in row.get("capacity", "").casefold()
                and row.get("status") == "required"
                for row in all_rows
            )
            for expected in forbidden_required_rows
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
        missing_expected_facts = [
            fact
            for fact in case.get("expected_facts", [])
            if not expected_fact_is_present(
                fact, _visible_answer_text(result)
            )
        ]
        expected_fact_failure = bool(missing_expected_facts)

        phantom_citations += int(phantom)
        citation_failures += int(citation_failure)
        support_signal_failures += int(signal_failure)
        section_failures += int(section_failure)
        unsupported_failures += int(unsupported_failure)
        unqualified_condition_failures += int(unqualified_condition_failure)
        trigger_note_failures += int(trigger_note_failure)
        arithmetic_failures += int(arithmetic_failure)
        negative_audit_failures += int(negative_audit_failure or forbidden_section_failure)
        date_warning_failures += int(date_warning_failure)
        applicability_failures += int(applicability_failure)
        guarantor_row_failures += int(
            row_failure or forbidden_row_failure or unresolved_failure
        )
        baseline_failures += int(baseline_failure)
        expected_fact_failures += int(expected_fact_failure)
        status = "PASS" if not any(
            (
                phantom,
                citation_failure,
                signal_failure,
                section_failure,
                unsupported_failure,
                unqualified_condition_failure,
                trigger_note_failure,
                arithmetic_failure,
                negative_audit_failure,
                forbidden_section_failure,
                date_warning_failure,
                applicability_failure,
                row_failure,
                forbidden_row_failure,
                unresolved_failure,
                baseline_failure,
                expected_fact_failure,
            )
        ) else "FAIL"
        print(
            f"{status} {case['id']}: sources={len(sources)} "
            f"phantom={phantom} citations={citation_failure} "
            f"support_signal={signal_failure} section={section_failure} "
            f"unsupported={unsupported_failure} arithmetic={arithmetic_failure} "
            f"unqualified_condition={unqualified_condition_failure} "
            f"trigger_note={trigger_note_failure} "
            f"negative_audit={negative_audit_failure or forbidden_section_failure} "
            f"date_warning={date_warning_failure} applicability={applicability_failure} "
            f"guarantor_rows={row_failure or forbidden_row_failure or unresolved_failure} "
            f"expected_facts={missing_expected_facts or 'ok'}"
            + (
                f" baseline={'; '.join(baseline_failure_details)}"
                if baseline_failure
                else ""
            )
        )
        case_results.append(
            {
                "id": case["id"],
                "status": status,
                "source_count": len(sources),
                "phantom": phantom,
                "citation_failure": citation_failure,
                "support_signal_failure": signal_failure,
                "section_failure": section_failure,
                "unsupported_failure": unsupported_failure,
                "unqualified_condition_failure": unqualified_condition_failure,
                "trigger_note_failure": trigger_note_failure,
                "arithmetic_failure": arithmetic_failure,
                "negative_audit_failure": negative_audit_failure
                or forbidden_section_failure,
                "date_warning_failure": date_warning_failure,
                "applicability_failure": applicability_failure,
                "guarantor_row_failure": (
                    row_failure or forbidden_row_failure or unresolved_failure
                ),
                "baseline_failure": baseline_failure,
                "expected_fact_failure": expected_fact_failure,
                "missing_expected_facts": missing_expected_facts,
                **handcheck_details(result),
            }
        )
        if args.delay_seconds > 0 and case is not cases[-1]:
            time.sleep(args.delay_seconds)

    summary = {
        "cases": len(cases),
        "passed": sum(item["status"] == "PASS" for item in case_results),
        "failed": sum(item["status"] != "PASS" for item in case_results)
        + int(corpus_hash_failure),
        "not_run": sum(item["status"] == "NOT_RUN" for item in case_results),
        "request_errors": sum(item["status"] == "ERROR" for item in case_results),
        "corpus_hash_failure": corpus_hash_failure,
        "phantom_citation_rate": phantom_citations / max(1, len(cases)),
        "citation_failures": citation_failures,
        "support_signal_failures": support_signal_failures,
        "section_failures": section_failures,
        "unsupported_failures": unsupported_failures,
        "unqualified_condition_failures": unqualified_condition_failures,
        "trigger_note_failures": trigger_note_failures,
        "arithmetic_failures": arithmetic_failures,
        "negative_audit_failures": negative_audit_failures,
        "date_warning_failures": date_warning_failures,
        "applicability_failures": applicability_failures,
        "guarantor_row_failures": guarantor_row_failures,
        "baseline_failures": baseline_failures,
        "expected_fact_failures": expected_fact_failures,
    }
    report = {
        "target": args.base_url,
        "suite": str(args.cases),
        "recorded_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "authenticated_requests": bool(args.cookie),
        "expected_source_sha256": args.expected_source_sha256,
        "corpus": health,
        "health_error": health_error,
        "summary": summary,
        "cases": case_results,
    }
    print(json.dumps(summary, indent=2))
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, indent=2) + "\n")
        print(f"Report written to {args.report}")
    return int(summary["failed"] > 0 or corpus_hash_failure)


if __name__ == "__main__":
    sys.exit(main())