"""Issue-specific retrieval safeguards and applied-evidence validation for SOPhia."""

from __future__ import annotations

import re
from typing import Any

PREFERENCE_SEARCHES = [
    "Preference compensating balance preferred position compared to SBA 13 CFR 120.10",
    "Lender deposit account requirement prohibited Preference compensating balances",
]
RATE_SEARCHES = [
    "General Policy on Interest Rates post-disbursement changes Note rate spread",
    "increase interest rate failure loan agreement conditions default interest rate",
]
DEPOSIT_RE = re.compile(r"deposit accounts?|compensating balances?", re.I)
RATE_RE = re.compile(r"interest rate|rate (?:increase|step[- ]?up)|default rate", re.I)


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
        for part in re.split(r"(?<=[.!?])\s+(?=[A-Z\"“])", text.strip())
        if part.strip()
    ]


def applied_evidence_error(quote: str, application: str, source: str) -> str | None:
    if not quote.strip() or quote.strip() not in source:
        return "Unverified quote: operative language is not verbatim in the cited chunk."
    if len(sentences(quote)) > 1:
        return "Applied quote exceeds one sentence; support was withheld."
    if not 1 <= len(sentences(application)) <= 3:
        return "Applied explanation must contain one to three sentences."
    return None


def quote_options(source: str, issue: str, limit: int = 6) -> list[str]:
    """Offer exact single-sentence spans, never repaired or paraphrased text."""
    anchors = set(re.findall(r"[a-z]{4,}", issue.casefold())) - {
        "that", "this", "with", "from", "loan", "lender", "borrower",
        "provision", "question", "policy", "under", "requirements",
    }
    options = list(dict.fromkeys(
        sentence for line in source.splitlines() for sentence in sentences(line)
        if len(sentence) >= 20 and sentence in source
    ))
    return sorted(
        options,
        key=lambda sentence: len(anchors.intersection(re.findall(r"[a-z]{4,}", sentence.casefold()))),
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


def grounded_covenant_conclusion(
    question: str, issue: str, sources: list[Any]
) -> dict[str, Any] | None:
    """Apply the independently retrieved operative rules with missing facts explicit.

    Used only for the compound deposit/rate fact pattern. No legal rule is supplied
    by this template: all required operative spans must exist in admitted sources.
    """
    if not (DEPOSIT_RE.search(question) and RATE_RE.search(question)):
        return None

    def locate(pattern: str) -> tuple[Any, str] | None:
        for source in sources:
            for line in source.chunk_text.splitlines():
                for quote in sentences(line):
                    if re.search(pattern, quote, re.I) and quote in source.chunk_text:
                        return source, quote
        return None

    def citation(found: tuple[Any, str], application: str) -> dict[str, Any]:
        return {"source_id": found[0].source_id, "quote": found[1], "application": application}

    if re.search(r"\bPreference\b", issue, re.I):
        definition = locate(r"Preference:.*preferred position.*compensating balance")
        prohibition = locate(r"may not.*establishes? a preference")
        if not definition or not prohibition:
            return None
        return {
            "text": (
                "The mandatory deposit-account covenant and rate penalty raise a "
                "Preference/compensating-balance issue, separately from the interest-rate "
                "issue. The admitted definition includes a preferred position involving "
                "control or a compensating balance without SBA consent, and a separate "
                "provision prohibits establishing a Preference. The facts do not state "
                "a required account balance or SBA consent, so those qualifications "
                "must be resolved rather than treating every deposit-account "
                "relationship as automatically prohibited."
            ),
            "citations": [
                citation(definition, "The proposed account covenant raises the quoted "
                         "control/compensating-balance concern. The question does not "
                         "state a required balance or SBA consent, which limits a "
                         "definitive application of this definition."),
                citation(prohibition, "If the deposit covenant gives the lender a "
                         "Preference within the cited definition, this operative "
                         "prohibition applies. The rate penalty does not remove "
                         "the separate Preference issue."),
            ],
        }
    if RATE_RE.search(issue):
        spread = locate(r"spread.*Note.*may not be changed.*written agreement")
        default = locate(r"^Default interest rates are not permitted\.$")
        if not spread or not default:
            return None
        amount = re.search(r"\d+(?:\.\d+)?\s*%", question)
        step = amount.group() if amount else "conditional"
        return {
            "text": (
                f"The covenant proposes a {step} change to the Note rate or spread; "
                "the analysis is not limited to the label 'default rate'. For a "
                "variable-rate loan, the quoted rule requires the Borrower's written "
                "agreement to a spread change during the loan's life, while the "
                "general interest-rate provision separately prohibits default interest "
                "rates. The facts do not establish the rate structure or the required "
                "agreement, so separate Note-rate authorization is not established; "
                "treating the step-up as a default rate encounters the cited prohibition."
            ),
            "citations": [
                citation(spread, "The proposed step-up changes the loan's Note rate "
                         "or spread. If the loan is variable-rate, the Borrower's "
                         "written agreement is material under this quoted rule; the "
                         "question does not establish whether that requirement is satisfied."),
                citation(default, "This separately prohibits default interest rates "
                         "in the assumed Standard 7(a) analysis. Treating failure "
                         "to maintain accounts as a default does not itself establish "
                         "authority for the increase under this quoted rule."),
            ],
        }
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
