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

    for case in cases:
        result = query(args.base_url, case["question"])
        sources = result.get("sources", [])
        phantom = any(
            not source.get("quote_located")
            or source.get("quote", "") not in source.get("source_chunk", "")
            for source in sources
        )
        signal_failure = any(
            not source.get("quote_located")
            or not source.get("supports_conclusion")
            for source in sources
        )
        section_text = " ".join(source.get("section_ref", "") for source in sources)
        section_failure = bool(case["expected_sections"]) and not any(
            expected.casefold() in section_text.casefold()
            for expected in case["expected_sections"]
        )
        unsupported_failure = case["unsupported"] and (
            bool(sources)
            or any(not subanswer.get("no_provision") for subanswer in result.get("subanswers", []))
        )

        phantom_citations += int(phantom)
        support_signal_failures += int(signal_failure)
        section_failures += int(section_failure)
        unsupported_failures += int(unsupported_failure)
        status = "PASS" if not any(
            (phantom, signal_failure, section_failure, unsupported_failure)
        ) else "FAIL"
        print(
            f"{status} {case['id']}: sources={len(sources)} "
            f"phantom={phantom} support_signal={signal_failure} "
            f"section={section_failure} unsupported={unsupported_failure}"
        )

    print(
        json.dumps(
            {
                "cases": len(cases),
                "phantom_citation_rate": phantom_citations / len(cases),
                "support_signal_failures": support_signal_failures,
                "section_failures": section_failures,
                "unsupported_failures": unsupported_failures,
            },
            indent=2,
        )
    )
    return int(
        any(
            (
                phantom_citations,
                support_signal_failures,
                section_failures,
                unsupported_failures,
            )
        )
    )


if __name__ == "__main__":
    sys.exit(main())