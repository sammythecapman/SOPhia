#!/usr/bin/env python3
"""SOPhia answer-quality evals; no production auth bypass or credential capture."""

import argparse
import json
import re
import sys
import hashlib
import time
from datetime import datetime, timezone
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
    for expectation in case.get("fact_expectations", []):
        found = [
            item for item in subanswers
            if re.search(expectation["issue_pattern"], item.get("requested_question") or "", re.I)
        ]
        # Inspect the actual visible answer, not the fixture, debug telemetry,
        # source chunk, or a rejected citation's unused application.
        text = " ".join(
            " ".join(str(part or "") for part in [
                item.get("answer"), item.get("support_note"),
                (item.get("applied_conclusion") or {}).get("text"),
                *[c.get("application") for c in
                  (item.get("applied_conclusion") or {}).get("citations", [])],
            ]) for item in found
        )
        for pattern in expectation.get("present_patterns", []):
            checks[f"visible fact: {pattern}"] = bool(found) and bool(re.search(pattern, text, re.I))
        for pattern in expectation.get("absent_patterns", []):
            checks[f"no factual contradiction: {pattern}"] = bool(found) and not bool(
                re.search(pattern, text, re.I)
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
    for forbidden in case.get("forbidden_claims", []):
        visible_answers = " ".join(
            item.get("answer") or "" for item in subanswers
        )
        checks[f"no unsupported claim: {forbidden['label']}"] = not bool(
            re.search(forbidden["pattern"], visible_answers, re.I | re.S)
        )
    return checks


def saved_responses(saved: dict, cases: list[dict]) -> dict:
    if "cases" in saved:
        expected_questions = {case["id"]: case["question"] for case in cases}
        for captured in saved["cases"]:
            if captured["id"] in expected_questions and (
                captured.get("question") != expected_questions[captured["id"]]
            ):
                raise ValueError(f"Saved question is missing or changed for {captured['id']}. Capture a new answer.")
        return {case["id"]: case["response"] for case in saved["cases"] if case.get("response")}
    if "subanswers" in saved:
        if len(cases) != 1:
            raise ValueError("A single saved response cannot be reused for multiple fixtures.")
        return {cases[0]["id"]: saved}
    return saved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, default=ROOT / "tests/fixtures/sophia_issue_evals.json")
    parser.add_argument("--base-url", default="http://localhost:80", help="Development preview proxy; production still requires genuine sign-in.")
    parser.add_argument("--response", type=Path, help="Evaluate saved response JSON without network or model calls.")
    parser.add_argument("--output", type=Path, default=ROOT / "outputs/sophia-issue-eval-results.json")
    args = parser.parse_args()
    cases = json.loads(args.cases.read_text())["cases"]
    saved_file = json.loads(args.response.read_text()) if args.response else None
    saved = saved_responses(saved_file, cases) if saved_file is not None else None
    reports = []
    def health():
        with urlopen(args.base_url.rstrip("/") + "/api/healthz", timeout=15) as response:
            return json.load(response)
    initial_health = saved_file.get("health_before") if saved_file is not None else health()
    report = {
        "format": "sophia-issue-evals-v2",
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
        "mode": "rescore" if saved is not None else "live-development",
        "base_url": args.base_url,
        "fixture_sha256": hashlib.sha256(args.cases.read_bytes()).hexdigest(),
        "evaluator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "health_before": initial_health,
        "planned_case_count": len(cases),
        "completed": False,
        "legal_accuracy_note": "Automated checks are not a hand-reviewed legal accuracy pass.",
        "source_capture": ({
            "path": str(args.response),
            "recorded_at_utc": saved_file.get("recorded_at_utc"),
            "mode": saved_file.get("mode"),
            "base_url": saved_file.get("base_url"),
            "fixture_sha256": saved_file.get("fixture_sha256"),
            "evaluator_sha256": saved_file.get("evaluator_sha256"),
        } if saved_file is not None else None),
        "cases": reports,
    }
    def save():
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + "\n")
    save()  # Replace any stale report before sending requests.
    for case in cases:
        print(f"\n{case['id']}", flush=True)
        error = None
        started = time.monotonic()
        try:
            if saved is not None:
                result = saved[case["id"]]
            else:
                req = Request(
                    args.base_url.rstrip("/") + "/api/sop/query",
                    data=json.dumps({"question": case["question"]}).encode(),
                    headers={"Content-Type": "application/json"}, method="POST",
                )
                with urlopen(req, timeout=300) as response:
                    result = json.load(response)
            checks = evaluate(case, result)
        except (HTTPError, URLError, TimeoutError, ValueError, KeyError, TypeError) as exc:
            error = str(exc)
            result = {}
            checks = {"request and response": False}
        for name, passed in checks.items():
            print(f"{'PASS' if passed else 'FAIL'}  {name}", flush=True)
        if error:
            print(f"ERROR {error}", flush=True)
        reports.append({
            "id": case["id"], "question": case["question"],
            "recorded_at_utc": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(time.monotonic() - started, 2),
            "checks": checks, "error": error, "response": result,
            "response_sha256": hashlib.sha256(json.dumps(result, sort_keys=True).encode()).hexdigest(),
        })
        save()
    report["health_after"] = saved_file.get("health_after") if saved_file is not None else health()
    report["completed"] = all(not item["error"] and item["response"] for item in reports)
    report["build_unchanged"] = (
        bool(initial_health and initial_health.get("build_sha"))
        and initial_health.get("build_sha") == (report["health_after"] or {}).get("build_sha")
    )
    save()
    print(
        f"\nSaved {len(reports)}/{len(cases)} responses; "
        f"build unchanged={report['build_unchanged']}. Legal review is separate.",
        flush=True,
    )
    return 0 if (
        report["completed"] and report["build_unchanged"]
        and all(all(item["checks"].values()) for item in reports)
    ) else 1


if __name__ == "__main__":
    raise SystemExit(main())
