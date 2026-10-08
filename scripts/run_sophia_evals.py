#!/usr/bin/env python3
"""SOPhia answer-quality evals; no production auth bypass or credential capture."""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "artifacts" / "api-server"))
from sophia_issues import applied_evidence_error  # noqa: E402


def evaluate(case: dict, result: dict) -> dict[str, bool]:
    subanswers = result.get("subanswers", [])
    checks = {}
    matches = []
    for issue in case["issues"]:
        found = [
            item for item in subanswers
            if re.search(issue["pattern"], item.get("requested_question") or item.get("question", ""), re.I)
        ]
        matches.append(found)
        checks[f"labeled issue: {issue['label']}"] = bool(found)
        checks[f"answer or explicit gap: {issue['label']}"] = bool(found) and all(
            item.get("applied_conclusion")
            or "Not addressed by retrieved provisions" in (item.get("support_note") or item.get("answer", ""))
            for item in found
        )
        checks[f"bottom line includes: {issue['label']}"] = bool(
            re.search(issue["pattern"], result.get("summary", ""), re.I)
        )
        if issue.get("operative_quote_pattern"):
            checks[f"operative quotes address: {issue['label']}"] = bool(found) and all(
                not item.get("applied_conclusion")
                or all(re.search(
                    issue["operative_quote_pattern"], citation.get("quote", ""), re.I
                ) for citation in item["applied_conclusion"].get("citations", []))
                for item in found
            )
    checks["distinct sub-issues"] = all(matches) and len({
        item.get("subquestion_id") or item.get("requested_question") or item.get("question")
        for group in matches for item in group
    }) >= len(case["issues"])
    supporting = [source for source in result.get("sources", []) if source.get("supports_conclusion")]
    allowed = set(case["allowed_support_programs"])
    checks["no other-program supporting authority"] = all(
        bool(source.get("program_scope"))
        and set(source["program_scope"]).issubset(allowed)
        for source in supporting
    )
    applied = [
        citation for item in subanswers
        for citation in (item.get("applied_conclusion") or {}).get("citations", [])
    ]
    applied_citations_verified = bool(applied) and all(
        citation.get("verified") and citation.get("quote_located")
        and citation.get("supports_conclusion")
        and not applied_evidence_error(
            citation.get("quote", ""), citation.get("application") or "",
            citation.get("source_chunk", ""),
        )
        for citation in applied
    )
    explicit_gap = bool(case.get("allow_explicit_gap")) and any(
        re.search(issue["pattern"], item.get("requested_question") or "", re.I)
        and "Not addressed by retrieved provisions" in (
            item.get("support_note") or item.get("answer", "")
        )
        for issue in case["issues"] for item in subanswers
    )
    checks["applied citations verified or permitted explicit gap"] = (
        applied_citations_verified if applied else explicit_gap
    )
    rejected = [citation for item in subanswers for citation in item.get("rejected_citations", [])]
    checks["rejected evidence includes reasons"] = (
        (bool(rejected) or explicit_gap)
        and all(citation.get("rejection_reason") and not citation.get("supports_conclusion")
                for citation in rejected)
    )
    terms = " ".join(term for item in subanswers for term in item.get("searched_terms", []))
    checks["Preference SBA query expansion"] = all(
        term.casefold() in terms.casefold() for term in case.get("required_expansions", [])
    )
    if case.get("expected_supplied_facts"):
        preference_answers = matches[0] if matches else []
        has_applied_answer = any(
            item.get("applied_conclusion") for item in preference_answers
        )
        answer_parts = [result.get("summary") or ""]
        for item in preference_answers:
            conclusion = item.get("applied_conclusion") or {}
            answer_parts.extend([
                item.get("answer") or "",
                item.get("support_note") or "",
                conclusion.get("text") or "",
                *[
                    citation.get("application") or ""
                    for citation in conclusion.get("citations", [])
                ],
                *[
                    citation.get("application") or ""
                    for citation in item.get("rejected_citations", [])
                ],
            ])
        answer_text = " ".join(str(part) for part in answer_parts)
        question_facts = case.get(
            "expected_question_facts", case["expected_supplied_facts"]
        )
        for fact_index, fact in enumerate(case["expected_supplied_facts"]):
            if has_applied_answer:
                checks[f"answer preserves supplied fact: {fact}"] = (
                    fact.casefold() in answer_text.casefold()
                )
            elif explicit_gap:
                question_fact = (
                    question_facts[fact_index]
                    if fact_index < len(question_facts) else fact
                )
                checks[f"case supplies contrast fact: {fact}"] = (
                    question_fact.casefold() in case["question"].casefold()
                )
        for pattern in case.get("not_missing_patterns", []):
            checks[f"supplied facts not called missing: {pattern}"] = not bool(
                re.search(pattern, answer_text, re.I)
            )
        outcome_pattern = case.get("forbidden_preference_outcome_pattern")
        if outcome_pattern:
            checks["avoids forcing a Preference outcome"] = not bool(
                re.search(outcome_pattern, answer_text, re.I)
            )
    if case.get("substance_pattern"):
        rate_answers = matches[-1] if matches else []
        checks["substance over default-rate label"] = bool(rate_answers) and all(
            not item.get("applied_conclusion")
            or re.search(
                case["substance_pattern"],
                item["applied_conclusion"]["text"] + " " + " ".join(
                    citation.get("application") or ""
                    for citation in item["applied_conclusion"].get("citations", [])
                ), re.I,
            )
            for item in rate_answers
        )
    return checks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "tests/fixtures/sophia_issue_evals.json")
    parser.add_argument("--base-url", default="http://localhost:80", help="Development preview proxy; production still requires genuine sign-in.")
    parser.add_argument("--response", type=Path, help="Evaluate saved response JSON without network or model calls.")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/sophia-issue-eval-results.json")
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text())["cases"]
    saved = json.loads(args.response.read_text()) if args.response else None
    reports = []
    for case in cases:
        print(f"\n{case['id']}", flush=True)
        error = None
        try:
            if saved is not None:
                result = saved if "subanswers" in saved else saved[case["id"]]
            else:
                req = Request(
                    args.base_url.rstrip("/") + "/api/sop/query",
                    data=json.dumps({"question": case["question"]}).encode(),
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                with urlopen(req, timeout=300) as response:
                    result = json.load(response)
            checks = evaluate(case, result)
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError) as exc:
            error = str(exc)
            result = {}
            checks = {"request and response": False}
        for name, passed in checks.items():
            print(f"{'PASS' if passed else 'FAIL'}  {name}", flush=True)
        if error:
            print(f"ERROR {error}", flush=True)
        reports.append({"id": case["id"], "checks": checks, "error": error, "response": result})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"cases": reports}, indent=2) + "\n")
    return 0 if all(all(report["checks"].values()) for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
