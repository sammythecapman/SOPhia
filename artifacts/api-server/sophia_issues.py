"""Issue-specific retrieval safeguards and applied-evidence validation for SOPhia."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

PREFERENCE_SEARCHES = [
    "Preference compensating balance preferred position compared to SBA 13 CFR 120.10",
    "Lender deposit account requirement prohibited Preference compensating balances",
    "13 CFR 120.411 collateral adequacy a Lender may not take any action that establishes a preference in favor of the Lender",
    "General 7(a) collateral requirements prohibition on establishing a preference in favor of the Lender",
]
RATE_SEARCHES = [
    "General Policy on Interest Rates post-disbursement changes Note rate spread",
    "increase interest rate failure loan agreement conditions default interest rate",
]
DEPOSIT_RE = re.compile(r"deposit accounts?|compensating balances?", re.I)
RATE_RE = re.compile(r"interest rate|note[- ](?:rate|spread)|rate (?:increase|step[- ]?up)|default rate", re.I)
PREFERENCE_RE = re.compile(r"\bpreference\b|compensating balances?", re.I)
PREFERENCE_AUTHORITY_RE = re.compile(
    r"\bmay not take any action\b.*\bestablish(?:es)? a preference in favor of the lender\b",
    re.I,
)


def preference_issue_requested(text: str) -> bool:
    return bool(PREFERENCE_RE.search(text))


def preserve_compound_issues(
    question: str, plan: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Do not let a planner silently collapse this independently triggered pair."""
    if not (DEPOSIT_RE.search(question) and RATE_RE.search(question)):
        return plan
    # Keep the factual wording (including the exact percentage), not a presumed
    # legal characterization or outcome. Other requested issues remain intact.
    facts = question.split("Under SBA", 1)[0].strip()
    issues = [
        {
            "question": "Preference / compensating balance: Is the requirement to "
            "maintain deposit accounts with the lender a prohibited Preference "
            "or compensating balance arrangement?",
            "search_terms": PREFERENCE_SEARCHES,
            "material_facts": [facts],
            "focused_retrieval": True,
        },
        {
            "question": "Interest-rate step-up / note-rate rules: Is the proposed "
            "covenant-triggered interest-rate increase permissible under the "
            "note-rate change rules, including any applicable default-rate rule?",
            "search_terms": RATE_SEARCHES,
            "material_facts": [facts],
            "focused_retrieval": True,
        },
    ]
    unrelated = [
        item for item in plan
        if not DEPOSIT_RE.search(item["question"])
        and not RATE_RE.search(item["question"])
        and not re.search(r"\bpreference\b", item["question"], re.I)
    ]
    return [*issues, *unrelated]


def expanded_search_terms(text: str) -> list[str]:
    result = []
    if DEPOSIT_RE.search(text) or re.search(r"\bpreference\b", text, re.I):
        result.extend(PREFERENCE_SEARCHES)
    if RATE_RE.search(text):
        result.extend(RATE_SEARCHES)
    return result


def sentences(text: str) -> list[str]:
    """Count prose sentences without treating decimals/CFR references as stops."""
    return [
        part.strip()
        for part in re.split(
            r"(?<!Para\.)(?<!Ch\.)(?<!Sec\.)(?<!U\.S\.)(?<=[.!?])\s+(?=[A-Z\"“])",
            text.strip(),
        )
        if part.strip()
    ]


def preference_authority_clause(text: str) -> str | None:
    """Return only the standalone collateral prohibition, if this source has it."""
    for line in text.splitlines():
        for sentence in sentences(line):
            if PREFERENCE_AUTHORITY_RE.search(sentence):
                return sentence
    return None


def applied_evidence_error(quote: str, application: str, source: str) -> str | None:
    if not quote.strip() or quote.strip() not in source:
        return "Unverified quote: operative language is not verbatim in the cited chunk."
    if len(sentences(quote)) > 1:
        return "Applied quote exceeds one sentence; support was withheld."
    if not 1 <= len(sentences(application)) <= 3:
        return "Applied explanation must contain one to three sentences."
    quote_words = re.sub(r"\W+", " ", quote.casefold()).strip()
    application_words = re.sub(r"\W+", " ", application.casefold()).strip()
    if len(application_words) >= 30 and (
        application_words in quote_words or quote_words in application_words
    ):
        return "Applied explanation recites the operative quote instead of applying facts."
    return None


def quote_options(source: str, issue: str, limit: int = 12) -> list[str]:
    """Offer exact single-sentence spans, never repaired or paraphrased text."""
    anchors = set(re.findall(r"[a-z]{4,}", issue.casefold())) - {
        "that", "this", "with", "from", "loan", "lender", "borrower",
        "provision", "question", "policy", "under", "requirements",
    }
    options = list(dict.fromkeys(
        sentence for line in source.splitlines() for sentence in sentences(line)
        if len(sentence) >= 20 and sentence in source
    ))
    execution_requested = bool(re.search(r"\bsign(?:s|ing|er)?\b|\bexecut(?:e|ion)\b", issue, re.I))
    return sorted(
        options,
        key=lambda sentence: (
            len(anchors.intersection(re.findall(r"[a-z]{4,}", sentence.casefold())))
            + (10 if execution_requested and re.search(r"\bexecut(?:e|es|ed|ion)\b", sentence, re.I) else 0)
        ),
        reverse=True,
    )[:limit]


def resolve_applied_quotes(conclusion: dict[str, Any], menu: dict[int, list[str]]) -> None:
    """Resolve a model-selected ID only in its own cited source's exact menu."""
    for citation in conclusion.get("citations", []):
        options = menu.get(citation.get("source_id"), [])
        quote_id = citation.get("quote_id")
        citation["quote"] = (
            options[quote_id]
            if isinstance(quote_id, int) and not isinstance(quote_id, bool)
            and 0 <= quote_id < len(options)
            else ""
        )


def validated_stated_facts(question: str, facts: Any) -> list[str]:
    """Preserve only exact user-supplied spans, never inferred legal conclusions."""
    if not isinstance(facts, list):
        facts = []
    declarative_spans = [
        span.strip() for span in re.split(r"(?<=[.!?])\s+|[;\n]+", question)
        if "?" not in span and 5 <= len(span.strip()) <= 240
    ]
    return list(dict.fromkeys(
        fact.strip() for fact in [*declarative_spans, *facts]
        if isinstance(fact, str) and 5 <= len(fact.strip()) <= 240
        and any(fact.strip() in span for span in declarative_spans)
    ))[:6]


def trust_ownership_arithmetic(question: str) -> dict[str, Any] | None:
    """Arithmetic for an explicitly described two-trust pair, not a guaranty rule."""
    if not re.search(r"owned by (?:two|2)\s+(?:(?:ir)?revocable\s+)?trusts", question, re.I):
        return None
    if not re.search(r"aggregat", question, re.I):
        return None
    values = re.findall(r"(\d+(?:\.\d+)?)\s*%", question)
    if len(values) != 2:
        return None  # Do not sum ambiguously attributed rates, owners, or other percentages.
    return {
        "percentages": values,
        "sum_percent": str(sum(Decimal(value) for value in values)),
        "note": "Arithmetic only. The cited SOP must establish whether legal aggregation applies.",
    }


def percentage_comparison_error(question: str, text: str) -> str | None:
    arithmetic = trust_ownership_arithmetic(question)
    if arithmetic is None:
        return None
    comparison = re.search(
        r"(?:combined|aggregate(?:d)?|total)\s+ownership\s+"
        r"(exceeds|(?:is\s+)?(?:greater|more|less)\s+than|(?:is\s+)?(?:above|below|over|under))"
        r"\s+(\d+(?:\.\d+)?)\s*%", text, re.I,
    )
    if comparison:
        total = Decimal(arithmetic["sum_percent"])
        threshold = Decimal(comparison.group(2))
        less = bool(re.search(r"less|below|under", comparison.group(1), re.I))
        if (less and total >= threshold) or (not less and total <= threshold):
            return f"Percentage comparison contradicts supplied arithmetic: the two shares sum to exactly {total}%."
    return None


def conclusion_scope_error(candidate: dict[str, Any]) -> str | None:
    """Prevent a narrower rule or definition from masquerading as a full answer."""
    if candidate.get("kind") != "conclusion":
        return None
    requested = candidate.get("requested_question", "")
    prose = candidate.get("text", "") + " " + " ".join(
        citation.get("application") or "" for citation in candidate.get("citations", [])
    )
    if "note-rate" in requested.casefold() and not re.search(r"note[- ]rate|spread", prose, re.I):
        return "Only a default-rate label was addressed; Note-rate/spread authorization remains unresolved."
    quotes = " ".join(citation.get("quote", "") for citation in candidate.get("citations", []))
    if (
        re.search(r"\bpreference\b", requested, re.I)
        and re.search(r"\bprohibited\b|\bimpermissible\b", prose, re.I)
        and not re.search(r"may not.*preference|preference.*prohibited", quotes, re.I)
    ):
        return "A Preference definition alone does not establish a prohibition; separate operative authority is required."
    if (
        re.search(r"\bpreference\b", requested, re.I)
        and re.search(r"\bprohibited\b|\bimpermissible\b", prose, re.I)
        and not re.search(r"preferred position", quotes, re.I)
    ):
        return "A Preference prohibition alone does not establish that the facts meet its operative definition."
    return None


def synthesize_bottom_line(subanswers: list[dict[str, Any]]) -> str:
    parts = []
    for item in subanswers:
        label = item.get("requested_question") or item["question"]
        conclusion = item.get("applied_conclusion")
        if conclusion:
            parts.append(f"{label} {conclusion['text']}")
        else:
            parts.append(f"{label} Not addressed by retrieved provisions.")
    return " ".join(parts) or "Not addressed by retrieved provisions."
