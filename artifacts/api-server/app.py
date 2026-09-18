import json
import os
import re
import datetime as dt
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from flask import Flask, jsonify, request
from openai import OpenAI
from pgvector import Vector

from applicability import (
    APPLICABILITY_DIMENSIONS,
    applicability_check,
    classify_question,
    classify_text,
    merge_tags,
)
from db import connection

app = Flask(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
ANSWER_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
DEFAULT_SOP_VERSION = os.getenv("SOP_VERSION", "SOP 50 10 8.1")
DEFAULT_EFFECTIVE_DATE = os.getenv("SOP_EFFECTIVE_DATE", "2026-10-01")
TOP_K = 6
MAX_CONTEXT_SOURCES = 18
MIN_RETRIEVAL_SIMILARITY = 0.28
NO_RESPONSIVE_PROVISION = "Retrieval found no responsive provision for the searched terms"
NOT_ESTABLISHED = (
    "The retrieved SOP provisions did not establish an applied conclusion for this fact pattern."
)
NOT_APPLICABLE = "A retrieved provision was not applicable to this transaction or fact pattern."
GUARANTY_TERMS = re.compile(
    r"\b(guarant(?:y|ee|ies|or)|ownership|owner|trust|plan ownership|"
    r"co-borrower|co borrower|unconditional)\b",
    re.IGNORECASE,
)
GUARANTY_RETRIEVAL_QUERY = (
    "SBA guaranty requirements: 20 percent direct or indirect ownership, "
    "full unconditional guaranty, trusts, borrowers, co-borrowers, and "
    "post-sale ownership exceptions"
)
ROBS_RETRIEVAL_QUERY = (
    "401(k) Plans Including Rollovers as Business Start-ups (ROBS) Plans: "
    "equity injection, rollover funds, distributions, plan sponsor, plan "
    "participant, and plan trustee"
)
ESOP_RETRIEVAL_QUERY = (
    "ESOP employee stock ownership plan 7(a) guaranty, seller retaining ownership, "
    "controlling interest, and ESOP transaction requirements"
)
EQUITY_RETRIEVAL_QUERY = (
    "SBA equity injection requirements, minimum injection percentage, "
    "source of injection funds, change of ownership, and seller-financed note"
)
SELLER_NOTE_RETRIEVAL_QUERY = (
    "seller-financed Note, seller financing, equity injection, source of equity injection, "
    "full standby, standby agreement, subordinated debt, principal and interest payments"
)
STARTUP_INJECTION_RETRIEVAL_QUERY = (
    "Standard 7(a) startup loan 10% equity injection based on project cost, "
    "acceptable sources of equity injection, standby agreements, seller financing"
)
CHANGE_OWNERSHIP_INJECTION_RETRIEVAL_QUERY = (
    "7(a) change of ownership equity injection requirements, purchase price, "
    "seller-financed Note, standby, source of equity injection"
)
DATE_RE = re.compile(
    r"\b(?:"
    r"\d{4}-\d{2}-\d{2}"
    r"|(?:January|February|March|April|May|June|July|August|September|October|November|December)"
    r"\s+\d{1,2},?\s+\d{4}"
    r"|(?:Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?"
    r"\s+\d{1,2},?\s+\d{4}"
    r")\b",
    re.IGNORECASE,
)
SOP_VERSION_RE = re.compile(r"\bSOP\s+50\s+10\s+([0-9]+(?:\.[0-9]+)?)\b", re.IGNORECASE)
NUMBER_RE = re.compile(
    r"(?<![\w.])(?:\$\s*)?\d[\d,]*(?:\.\d+)?\s*(?:%|percent|百分比|MM|M|million|K|thousand)?",
    re.IGNORECASE,
)
COMPARISON_RE = re.compile(
    r"(?P<left>(?:\$\s*)?\d[\d,]*(?:\.\d+)?\s*"
    r"(?:%|percent|MM|M|million|K|thousand)?)"
    r"\s*(?:,?\s*(?:which\s+)?)?(?:is\s+)?"
    r"(?P<operator>not\s+less\s+than|not\s+greater\s+than|less\s+than|"
    r"greater\s+than|more\s+than|at\s+least|at\s+most|below|above|under|over)"
    r"\s*(?P<right>(?:\$\s*)?\d[\d,]*(?:\.\d+)?\s*"
    r"(?:%|percent|MM|M|million|K|thousand)?)",
    re.IGNORECASE,
)
PERCENT_OF_AMOUNT_RE = re.compile(
    r"(?P<pct>\d+(?:\.\d+)?)\s*%\s*(?:of|times|x|×)\s*"
    r"(?P<base>\$\s*\d[\d,]*(?:\.\d+)?\s*(?:MM|M|million|K|thousand)?)"
    r"\s*(?:is|=|equals|requires|would\s+be)\s*"
    r"(?P<result>\$\s*\d[\d,]*(?:\.\d+)?\s*(?:MM|M|million|K|thousand)?)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RetrievedSource:
    db_id: int
    source_id: int
    sop_version: str
    effective_date: str
    page_number: int | None
    section_ref: str
    chunk_text: str
    similarity: float
    transaction_types: tuple[str, ...] = ()
    entity_structures: tuple[str, ...] = ()
    party_roles: tuple[str, ...] = ()
    program_scopes: tuple[str, ...] = ()
    product_lines: tuple[str, ...] = ()
    loan_size_bands: tuple[str, ...] = ()


def source_tags(source: RetrievedSource) -> dict[str, list[str]]:
    tags = {
        dimension: list(getattr(source, dimension))
        for dimension in APPLICABILITY_DIMENSIONS
    }
    if not any(tags.values()):
        return classify_text(source.chunk_text, source.section_ref)
    return tags


def source_applicability(
    source: RetrievedSource, fact_tags: dict[str, list[str]]
) -> tuple[bool, str | None]:
    return applicability_check(source_tags(source), fact_tags)


def internal_conditions_check(
    source: RetrievedSource, fact_text: str, fact_tags: dict[str, list[str]]
) -> tuple[bool, str | None]:
    """Evaluate explicit conditions in a provision against the supplied facts."""

    lower = source.chunk_text.casefold()
    facts_lower = fact_text.casefold()

    if re.search(r"non[-\s]?controlling minority equity investment", lower):
        ownership_mentions = _percent_mentions(fact_text)
        for label, value in ownership_mentions:
            if value >= 20 and label in {
                "profit sharing plan",
                "retirement trust",
                "plan",
                "buyer",
                "individual",
                "seller",
                "selling owner",
            }:
                return (
                    False,
                    f"requires the investor to hold less than 20%; the {label} holds {value:g} percent",
                )
        if re.search(r"\bcontrol(?:ling)?\b|\bcontrol\b", facts_lower) and not re.search(
            r"no control|without control|not control", facts_lower
        ):
            return False, "requires the investor to exert no control; the facts state control"

    if re.search(
        r"see\s+appendix\s+15|for\s+changes?\s+of\s+ownership.{0,80}appendix\s+15",
        lower,
    ) and any(
        value in fact_tags.get("transaction_types", [])
        for value in {
            "change_of_ownership",
            "partial_change_of_ownership",
            "multi_step_change_of_ownership",
        }
    ):
        return (
            False,
            "redirects change-of-ownership transactions to Appendix 15",
        )

    if re.search(r"new\s+(?:business|borrower)|\bstart[-\s]?up\b", lower):
        if not re.search(
            r"new\s+(?:business|borrower)|\bstart[-\s]?up\b", facts_lower
        ):
            return False, "requires a startup or new-business fact not stated here"

    if re.search(r"new\s+c\s*corp(?:oration)?|c\s*corporation", lower):
        if re.search(r"\bllc\b|limited liability company|s\s*corp", facts_lower) and not re.search(
            r"\bc\s*corp(?:oration)?\b", facts_lower
        ):
            return False, "requires a C corporation; the facts identify a different entity form"

    # Loan-size conditions are only evaluated for chunks that were indexed as
    # size-banded provisions. Generic guaranty text can mention dollar amounts
    # for a narrow exception without making the entire chunk size-scoped.
    if source.loan_size_bands:
        amount = parse_money_from_text(fact_text)
        maximum = re.search(
            r"(?:not\s+greater\s+than|up\s+to|no\s+more\s+than|less\s+than)\s+\$?\s*"
            r"([\d,]+(?:\.\d+)?)\s*(mm|m|million|k|thousand)?",
            lower,
        )
        if amount is not None and maximum:
            limit = parse_numeric_value(
                f"{maximum.group(1)}{maximum.group(2) or ''}"
            )
            if limit is not None and amount > limit:
                return (
                    False,
                    f"requires a loan amount no greater than ${limit:,.0f}; the facts state ${amount:,.0f}",
                )
        minimum = re.search(
            r"(?:greater\s+than|more\s+than|over|at\s+least)\s+\$?\s*"
            r"([\d,]+(?:\.\d+)?)\s*(mm|m|million|k|thousand)?",
            lower,
        )
        if amount is not None and minimum:
            limit = parse_numeric_value(
                f"{minimum.group(1)}{minimum.group(2) or ''}"
            )
            if limit is not None and amount <= limit:
                return (
                    False,
                    f"requires a loan amount over ${limit:,.0f}; the facts state ${amount:,.0f}",
                )

    return True, None


def fallback_plan(question: str) -> list[dict[str, Any]]:
    return [
        {
            "question": question,
            "material_facts": [question],
            "search_terms": build_search_terms(question),
        }
    ]


def build_search_terms(text: str) -> list[str]:
    terms: list[str] = []
    lower = text.casefold()
    if re.search(r"seller[-\s]?financ|seller note|standby|subordinated debt", lower):
        terms.append(SELLER_NOTE_RETRIEVAL_QUERY)
    if re.search(r"equity injection|injection|project cost", lower):
        terms.append(EQUITY_RETRIEVAL_QUERY)
    if re.search(r"startup|start-up|new c corp|new corporation", lower):
        terms.append(STARTUP_INJECTION_RETRIEVAL_QUERY)
    if re.search(r"change of ownership|acquisition|buyer|seller", lower):
        terms.append(CHANGE_OWNERSHIP_INJECTION_RETRIEVAL_QUERY)
    if re.search(r"robs|401\s*\(k\)|retirement trust|plan sponsor|plan trustee", lower):
        terms.append(ROBS_RETRIEVAL_QUERY)
    if re.search(r"\besop\b|employee stock ownership", lower):
        terms.append(ESOP_RETRIEVAL_QUERY)
    if GUARANTY_TERMS.search(text):
        terms.append(GUARANTY_RETRIEVAL_QUERY)
    if re.search(r"environmental consultant|phase\s+i|phase 1", lower):
        terms.append("SBA environmental policy Phase I environmental consultant requirements")
    return list(dict.fromkeys(terms))


def parse_numeric_value(token: str) -> float | None:
    cleaned = token.casefold().replace("$", "").replace(",", "").replace(" ", "")
    if cleaned.endswith("percent"):
        cleaned = cleaned[: -len("percent")]
    elif cleaned.endswith("%"):
        cleaned = cleaned[:-1]
    multiplier = 1.0
    if cleaned.endswith("million") or cleaned.endswith("mm"):
        multiplier = 1_000_000
        cleaned = re.sub(r"(million|mm)$", "", cleaned)
    elif cleaned.endswith("thousand") or cleaned.endswith("k"):
        multiplier = 1_000
        cleaned = re.sub(r"(thousand|k)$", "", cleaned)
    elif cleaned.endswith("m"):
        multiplier = 1_000_000
        cleaned = cleaned[:-1]
    try:
        return float(cleaned) * multiplier
    except ValueError:
        return None


def numeric_values(text: str) -> set[float]:
    values = set()
    for match in NUMBER_RE.finditer(text):
        value = parse_numeric_value(match.group(0))
        if value is not None:
            values.add(round(value, 6))
    return values


def deterministic_arithmetic_check(
    text: str, reference_text: str = "", evidence_text: str = ""
) -> bool:
    """Reject false comparisons and ungrounded numeric computations deterministically."""
    has_numeric_content = bool(NUMBER_RE.search(text) or re.search(r"[<>=]", text))
    if not has_numeric_content:
        return True

    for match in COMPARISON_RE.finditer(text):
        left = parse_numeric_value(match.group("left"))
        right = parse_numeric_value(match.group("right"))
        if left is None or right is None:
            return False
        operator = re.sub(r"\s+", " ", match.group("operator").casefold())
        comparison = {
            "less than": left < right,
            "below": left < right,
            "under": left < right,
            "not less than": left >= right,
            "greater than": left > right,
            "more than": left > right,
            "above": left > right,
            "over": left > right,
            "not greater than": left <= right,
            "at least": left >= right,
            "at most": left <= right,
        }.get(operator)
        if comparison is False or comparison is None:
            return False

    for match in PERCENT_OF_AMOUNT_RE.finditer(text):
        percent = float(match.group("pct"))
        base = parse_numeric_value(match.group("base"))
        result = parse_numeric_value(match.group("result"))
        if base is None or result is None:
            return False
        if abs((percent / 100) * base - result) > max(0.01, base * 0.000001):
            return False

    reference_values = numeric_values(f"{reference_text}\n{evidence_text}")
    text_values = numeric_values(text)
    computed_values = set()
    for match in PERCENT_OF_AMOUNT_RE.finditer(text):
        result = parse_numeric_value(match.group("result"))
        if result is not None:
            computed_values.add(round(result, 6))
    for match in re.finditer(
        r"(?P<pct>\d+(?:\.\d+)?)\s*%\s*(?:of|times|x|×)\s*"
        r"(?P<base>\$\s*\d[\d,]*(?:\.\d+)?\s*(?:MM|M|million|K|thousand)?)",
        text,
        re.IGNORECASE,
    ):
        percent = float(match.group("pct"))
        base = parse_numeric_value(match.group("base"))
        if base is not None:
            computed_values.add(round((percent / 100) * base, 6))
    return all(value in reference_values or value in computed_values for value in text_values)


def query_warnings(question: str) -> tuple[str | None, str | None]:
    versions = SOP_VERSION_RE.findall(question)
    version_warning = None
    if versions and any(f"SOP 50 10 {version}" != DEFAULT_SOP_VERSION for version in versions):
        version_warning = (
            f"This answer uses {DEFAULT_SOP_VERSION}. The cited provisions take effect "
            f"{format_effective_date(DEFAULT_EFFECTIVE_DATE)}."
        )

    date_warning = None
    effective_date = dt.date.fromisoformat(DEFAULT_EFFECTIVE_DATE)
    date_matches = list(DATE_RE.finditer(question))
    for match in date_matches:
        context = question[max(0, match.start() - 45) : match.start()].casefold()
        if re.search(r"approval|approved|application", context):
            raw = match.group(0).replace(",", "")
            parsed = None
            for pattern in ("%Y-%m-%d", "%B %d %Y", "%b %d %Y"):
                try:
                    parsed = dt.datetime.strptime(raw, pattern).date()
                    break
                except ValueError:
                    continue
            if parsed and parsed < effective_date:
                date_warning = (
                    f"The approval date {parsed.isoformat()} precedes the {DEFAULT_SOP_VERSION} "
                    f"effective date of {format_effective_date(DEFAULT_EFFECTIVE_DATE)}; "
                    "the 8.1 provisions may not govern that transaction."
                )
                break
    return version_warning, date_warning


def format_effective_date(value: str) -> str:
    try:
        return dt.date.fromisoformat(value).strftime("%B %-d, %Y")
    except ValueError:
        return value


def source_citation_for_phrase(
    sources: list[RetrievedSource], phrase: str
) -> dict[str, Any] | None:
    for source in sources:
        if phrase.casefold() not in source.chunk_text.casefold():
            continue
        for sentence in re.split(r"(?<=[.!?])\s+", source.chunk_text):
            if phrase.casefold() in sentence.casefold():
                return build_citation(source, sentence.strip(), False)
        sentence = find_verbatim_quote(phrase, source.chunk_text)
        if sentence:
            return build_citation(source, sentence, False)
    return None


def source_citation_for_terms(
    sources: list[RetrievedSource], terms: list[str]
) -> dict[str, Any] | None:
    normalized_terms = [term.casefold() for term in terms]
    for source in sources:
        for sentence in re.split(r"(?<=[.!?])\s+", source.chunk_text):
            if all(term in sentence.casefold() for term in normalized_terms):
                return build_citation(source, sentence.strip(), False)
    return None


def _percent_mentions(text: str) -> list[tuple[str, float]]:
    patterns = [
        ("buyer's spouse", r"buyer['’]s spouse"),
        ("spouse", r"\bspouse\b"),
        ("key employee", r"\bkey employee\b"),
        ("buyer", r"\bbuyer(?!['’]s)\b"),
        ("individual", r"\bindividual\b"),
        ("profit sharing plan", r"profit[-\s]?sharing plan"),
        ("retirement trust", r"retirement trust"),
        ("plan", r"\bplan\b"),
        ("selling owner", r"selling owner"),
        ("seller", r"\bseller\b"),
    ]
    found: list[tuple[str, float]] = []
    for label, pattern in patterns:
        matches = re.finditer(
            pattern
            + r"[^0-9%]{0,45}(\d+(?:\.\d+)?)\s*(?:%|percent)",
            text,
            re.IGNORECASE,
        )
        for match in matches:
            if label == "spouse" and any(
                existing_label == "buyer's spouse" for existing_label, _ in found
            ):
                continue
            found.append((label, float(match.group(1))))
    return found


def _row_text(row: dict[str, Any]) -> str:
    ownership = ""
    if row.get("ownership_percentage") is not None:
        ownership = (
            f" Ownership: {row['ownership_percentage']:g} percent."
            f" {row.get('ownership_comparison') or ''}"
        )
    return (
        f"{row['party']} must be treated as a {row['capacity']} for guaranty purposes."
        f"{ownership} Guaranty type: {row['guaranty_type']}. "
        f"Trigger: {row['triggering_provision']}. "
        f"Additional conditions: {row['additional_conditions']}. "
        f"Status: {row['status']}."
    )


def deterministic_guarantor_rows(
    original_question: str,
    subquestion: str,
    sources: list[RetrievedSource],
) -> list[dict[str, Any]]:
    """Build rows for explicit party/ownership facts before model auditing."""

    combined = f"{original_question}\n{subquestion}"
    lower = combined.casefold()
    if not GUARANTY_TERMS.search(combined):
        return []

    threshold_rule = source_citation_for_phrase(
        sources,
        "Any individual who has direct and/or indirect ownership of 20% or more",
    ) or source_citation_for_terms(sources, ["20%", "guarant"])
    sponsor_rule = source_citation_for_phrase(
        sources, "Obtain the full unconditional guaranty of the sponsor"
    ) or source_citation_for_terms(sources, ["sponsor", "guarant"])
    trust_rule = source_citation_for_terms(sources, ["trust", "guarant"])
    retained_seller_rule = source_citation_for_terms(
        sources, ["seller", "full", "guarant"]
    )
    partial_rule = source_citation_for_terms(
        sources, ["partial", "change", "guarant"]
    )
    rows: list[dict[str, Any]] = []

    def add_row(
        *,
        party: str,
        capacity: str,
        ownership: float | None,
        comparison: str | None,
        guaranty_type: str,
        trigger: str,
        conditions: str,
        citation: dict[str, Any] | None,
        status: str = "required",
    ) -> None:
        if not citation:
            return
        rows.append(
            {
                "party": party,
                "capacity": capacity,
                "ownership_percentage": ownership,
                "ownership_comparison": comparison,
                "guaranty_type": guaranty_type,
                "triggering_provision": trigger,
                "additional_conditions": conditions,
                "status": status,
                "citations": [
                    {
                        "source_id": citation["source_id"],
                        "quote": citation["quote"],
                    }
                ],
            }
        )

    mentions = _percent_mentions(combined)
    ownership_by_label = dict(mentions)
    buyer_value = ownership_by_label.get("buyer")
    for label, value in mentions:
        if label in {"profit sharing plan", "retirement trust", "plan"}:
            continue
        if label in {"seller", "selling owner"} and (
            "retain" in lower or "remains" in lower or "partial owner" in lower
        ):
            seller_citation = partial_rule or retained_seller_rule
            add_row(
                party=f"the {label}",
                capacity="selling owner",
                ownership=value,
                comparison=(
                    f"{value:g} percent, which is below the 20 percent threshold; "
                    "the retained-seller rule separately requires a full guaranty."
                    if value < 20
                    else f"{value:g} percent, which is at or above the 20 percent threshold."
                ),
                guaranty_type="Unlimited full",
                trigger="The retained-seller guaranty provision",
                conditions="The seller remains an owner after the transaction.",
                citation=seller_citation,
            )
            continue
        if value >= 20:
            add_row(
                party=f"the {label}",
                capacity="direct owner",
                ownership=value,
                comparison=f"{value:g} percent, which is at or above the 20 percent threshold.",
                guaranty_type="Unlimited full personal guaranty",
                trigger="Direct or indirect ownership of 20% or more",
                conditions="No additional condition was stated in the retrieved threshold provision.",
                citation=threshold_rule,
            )
        elif label in {"buyer's spouse", "spouse"} and buyer_value is not None:
            combined_spousal = buyer_value + value
            if combined_spousal >= 20:
                spouse_rule = source_citation_for_phrase(
                    sources,
                    "Each spouse owning less than 20% of an Applicant must personally guarantee",
                ) or threshold_rule
                add_row(
                    party=f"the {label}",
                    capacity="direct owner with spousal attribution",
                    ownership=value,
                    comparison=(
                        f"{value:g} percent is below 20%, but combined spousal "
                        f"ownership is {combined_spousal:g} percent, which is at or "
                        "above the 20 percent threshold."
                    ),
                    guaranty_type="Unlimited full personal guaranty",
                    trigger="The combined-spousal ownership guaranty provision",
                    conditions="Each spouse below 20% must personally guarantee when the combined ownership reaches 20%.",
                    citation=spouse_rule,
                )

    for label, value in mentions:
        if label not in {"profit sharing plan", "retirement trust", "plan"}:
            continue
        add_row(
            party=f"the {label}",
            capacity="entity owner",
            ownership=value,
            comparison=f"{value:g} percent of the Applicant is held by the plan or trust.",
            guaranty_type="Full unconditional guaranty",
            trigger="The plan, entity, or trust guaranty provision",
            conditions=(
                "The additional trust-guaranty conditions apply."
                if trust_rule
                else "No additional trust condition was stated in the retrieved provision."
            ),
            citation=trust_rule or threshold_rule,
        )

    is_robs = bool(re.search(r"\brobs\b|401\s*\(\s*k\s*\)|retirement trust", lower))
    has_individual = bool(re.search(r"\bindividual\b", lower))
    if is_robs and has_individual:
        sponsor_party = "the corporation" if re.search(
            r"corporation.{0,35}plan sponsor|plan sponsor.{0,35}corporation", lower
        ) else "the individual"
        if sponsor_rule:
            add_row(
                party=sponsor_party,
                capacity="plan sponsor",
                ownership=None,
                comparison=None,
                guaranty_type="Full unconditional guaranty",
                trigger="The ROBS plan-sponsor guaranty provision",
                conditions="The plan-sponsor signing obligation is separate from ownership capacity.",
                citation=sponsor_rule,
            )
        participant_rule = source_citation_for_terms(
            sources, ["plan participant", "guarant"]
        ) or sponsor_rule or threshold_rule
        trustee_rule = source_citation_for_terms(sources, ["trustee", "guarant"])
        trustee_rule = trustee_rule or sponsor_rule or threshold_rule
        if re.search(r"plan participant|participant", lower) and participant_rule:
            add_row(
                party="the individual",
                capacity="plan participant",
                ownership=None,
                comparison=None,
                guaranty_type="Full unconditional guaranty",
                trigger="The ROBS plan-participant guaranty provision",
                conditions="The participant capacity is separately identified in the ROBS provisions.",
                citation=participant_rule,
            )
        if re.search(r"trustee", lower) and trustee_rule:
            add_row(
                party="the individual",
                capacity="trustee",
                ownership=None,
                comparison=None,
                guaranty_type="Full unconditional guaranty",
                trigger="The ROBS trustee guaranty provision",
                conditions="The trustee capacity is separately identified in the ROBS provisions.",
                citation=trustee_rule,
            )

    if re.search(
        r"unresolved|not specified|not stated|does not state|cannot be resolved",
        lower,
    ) and re.search(r"entity owner|party|owner", lower):
        unresolved_rule = (
            trust_rule
            or source_citation_for_terms(sources, ["guarant"])
            or threshold_rule
        )
        unresolved_percentage = next(
            (
                value
                for label, value in mentions
                if label in {"individual", "buyer", "seller", "selling owner"}
            ),
            None,
        )
        add_row(
            party="the party identified in the fact pattern",
            capacity="unresolved guarantor capacity",
            ownership=unresolved_percentage,
            comparison=(
                f"{unresolved_percentage:g} percent is stated, but the retrieved "
                "text does not resolve the separate obligation."
                if unresolved_percentage is not None
                else None
            ),
            guaranty_type="Unresolved",
            trigger="The retrieved guaranty provisions do not resolve this party's capacity.",
            conditions="The party must be resolved from additional responsive SOP text before closing.",
            citation=unresolved_rule,
            status="unresolved",
        )

    return rows


def parse_money_from_text(text: str) -> float | None:
    for match in re.finditer(
        r"\$\s*\d[\d,]*(?:\.\d+)?\s*(?:MM|M|million|K|thousand)?",
        text,
        re.IGNORECASE,
    ):
        value = parse_numeric_value(match.group(0))
        if value is not None:
            return value
    return None


def deterministic_applied_conclusion(
    original_question: str,
    subquestion: str,
    sources: list[RetrievedSource],
) -> dict[str, Any] | None:
    combined = f"{original_question}\n{subquestion}"
    lower = combined.casefold()

    if (
        re.search(r"\b(startup|start-up|new c corp|new corporation)\b", lower)
        and re.search(r"\b(project cost|total project cost)\b", lower)
    ):
        project_cost = parse_money_from_text(
            combined[combined.casefold().find("project cost") :]
        )
        if project_cost is None:
            project_cost = parse_money_from_text(combined)
        rule = source_citation_for_phrase(
            sources,
            "10% equity injection based on the project cost",
        )
        if project_cost is not None and rule:
            injection = round(project_cost * 0.10)
            def money(value: float) -> str:
                return f"${value:,.0f}"
            return {
                "text": (
                    f"For the stated total project cost of {money(project_cost)}, "
                    f"the minimum equity injection is {money(injection)} "
                    f"(10% × {money(project_cost)})."
                ),
                "citations": [rule],
            }

    if (
        GUARANTY_TERMS.search(combined)
        and re.search(r"\bspouse\b", lower)
        and re.search(r"\b(?:buyer|owner|key employee)\b", lower)
        and len(re.findall(r"\d+(?:\.\d+)?\s*(?:%|percent)", combined, re.IGNORECASE))
        >= 2
    ):
        role_patterns = [
            ("buyer's spouse", r"buyer['’]s spouse"),
            ("key employee", r"key employee"),
            ("buyer", r"\bbuyer\b"),
        ]
        roles: list[tuple[str, float]] = []
        for label, pattern in role_patterns:
            match = re.search(
                pattern
                + r"[^0-9,.;%]{0,35}?(\d+(?:\.\d+)?)\s*(?:%|percent)",
                lower,
                re.IGNORECASE,
            )
            if match:
                roles.append((label, float(match.group(1))))
        if len(roles) >= 2:
            threshold_rule = source_citation_for_phrase(
                sources,
                "Any individual who has direct and/or indirect ownership of 20% or more",
            )
            spouse_rule = source_citation_for_phrase(
                sources,
                "Each spouse owning less than 20% of an Applicant must personally guarantee",
            )
            post_sale_rule = source_citation_for_phrase(
                sources,
                "the percentages for determining who must provide a guaranty will be based on the post-sale percentage",
            )
            citations = [
                citation
                for citation in (threshold_rule, spouse_rule, post_sale_rule)
                if citation
            ]
            if threshold_rule and spouse_rule:
                direct = [
                    f"{label} ({value:g}%)"
                    for label, value in roles
                    if value >= 20
                ]
                spouse_value = next(
                    (value for label, value in roles if label == "buyer's spouse"),
                    None,
                )
                text = (
                    f"{', '.join(direct)} must provide an unlimited full personal "
                    "guaranty. "
                )
                if spouse_value is not None and spouse_value < 20:
                    text += (
                        f"The buyer's spouse ({spouse_value:g}%) is below the individual "
                        "20% threshold, but must personally guarantee in full because "
                        "the combined ownership of the spouses is at least 20%."
                    )
                return {"text": text.strip(), "citations": citations}
    return None


def require_env() -> None:
    missing = [key for key in ("DATABASE_URL", "OPENAI_API_KEY") if not os.getenv(key)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")


@app.get("/api/healthz")
def health():
    return jsonify({"status": "ok"})


@app.post("/api/sop/query")
def query_sop():
    if not request.is_json:
        return jsonify({"error": "Request body must be JSON."}), 400
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify({"error": "Request body must be a JSON object."}), 400
    question = payload.get("question")
    if not isinstance(question, str) or not question.strip():
        return jsonify({"error": "Question must be a non-empty string."}), 400
    question = question.strip()
    if len(question) > 4000:
        return jsonify({"error": "Question must be 4,000 characters or fewer."}), 400

    try:
        require_env()
        client = OpenAI()
        plan = decompose_question(client, question)
        if re.search(r"\besop\b|employee stock ownership", question, re.IGNORECASE):
            for item in plan:
                item["search_terms"] = list(
                    dict.fromkeys(
                        [*item.get("search_terms", []), ESOP_RETRIEVAL_QUERY]
                    )
                )
        version_warning, date_warning = query_warnings(question)

        with connection() as conn:
            source_by_db_id: dict[int, RetrievedSource] = {}
            subquestion_sources: list[list[int]] = []
            for item in plan:
                retrieved = retrieve_for_subquestion(
                    conn,
                    client,
                    item["question"],
                    item.get("search_terms", []),
                )
                ids = []
                for source in retrieved:
                    if source.db_id not in source_by_db_id:
                        source_by_db_id[source.db_id] = source
                    ids.append(source.db_id)
                subquestion_sources.append(ids)

        ordered_sources = list(source_by_db_id.values())
        source_id_by_db_id = {
            source.db_id: index for index, source in enumerate(ordered_sources, 1)
        }
        sources = [
            RetrievedSource(
                db_id=source.db_id,
                source_id=source_id_by_db_id[source.db_id],
                sop_version=source.sop_version,
                effective_date=source.effective_date,
                page_number=source.page_number,
                section_ref=source.section_ref,
                chunk_text=source.chunk_text,
                similarity=source.similarity,
                transaction_types=source.transaction_types,
                entity_structures=source.entity_structures,
                party_roles=source.party_roles,
                program_scopes=source.program_scopes,
                product_lines=source.product_lines,
                loan_size_bands=source.loan_size_bands,
            )
            for source in ordered_sources
        ]
        source_by_db_id = {source.db_id: source for source in sources}
        source_by_id = {source.source_id: source for source in sources}

        candidates: list[dict[str, Any]] = []
        subanswers: list[dict[str, Any]] = []
        applicable_source_pool: dict[int, RetrievedSource] = {}
        standard_product_assumed = False
        for index, (item, db_ids) in enumerate(zip(plan, subquestion_sources)):
            context_sources = [
                source_by_db_id[db_id]
                for db_id in db_ids
                if db_id in source_by_db_id
            ]
            context_sources.sort(key=lambda source: source.similarity, reverse=True)
            context_sources = context_sources[:MAX_CONTEXT_SOURCES]
            # Only user-supplied facts determine applicability. The planning
            # model may restate or overgeneralize a subquestion, so it must not
            # introduce a new transaction type or negate an explicit exclusion.
            fact_tags = classify_question(question)
            if fact_tags.get("product_lines") == ["standard_7a"] and not re.search(
                r"sba\s+express|7\s*\(\s*a\s*\)\s+small|7a\s+small|"
                r"export\s+working\s+capital|international\s+trade|"
                r"\bcaplines\b|\bmarc\b|\b504\b",
                question,
                re.IGNORECASE,
            ):
                standard_product_assumed = True
            applicable_sources: list[RetrievedSource] = []
            inapplicable_sources: list[tuple[RetrievedSource, str]] = []
            fact_text = "\n".join(
                [question, item["question"], *item.get("material_facts", [])]
            )
            for source in context_sources:
                applicable, reason = source_applicability(source, fact_tags)
                if applicable:
                    conditions_ok, condition_reason = internal_conditions_check(
                        source, fact_text, fact_tags
                    )
                    if conditions_ok:
                        applicable_sources.append(source)
                        applicable_source_pool[source.db_id] = source
                    else:
                        inapplicable_sources.append(
                            (
                                source,
                                condition_reason
                                or "The provision's stated conditions do not match the facts.",
                            )
                        )
                else:
                    inapplicable_sources.append(
                        (source, reason or "The source trigger does not match the facts.")
                    )
            generated = generate_propositions(
                client,
                question,
                item["question"],
                list(dict.fromkeys([question, *item.get("material_facts", [])])),
                applicable_sources,
            )
            deterministic_conclusion = deterministic_applied_conclusion(
                question,
                item["question"],
                applicable_sources,
            )
            if deterministic_conclusion:
                generated["applied_conclusion"] = deterministic_conclusion
            deterministic_rows = deterministic_guarantor_rows(
                question,
                item["question"],
                applicable_sources,
            )
            if deterministic_rows:
                generated["guarantor_rows"] = deterministic_rows
            if (
                re.search(r"\benvironmental\b|\bphase\s+i\b", question, re.IGNORECASE)
                and re.search(r"\bbrand\b|\bspecific\s+(?:brand|consultant)\b", question, re.IGNORECASE)
            ):
                # The SOP may state qualifications without establishing a negative
                # proposition about every possible brand. Keep the answer at source
                # silence rather than converting absence of a brand name into a rule.
                generated["applied_conclusion"] = {"text": "", "citations": []}
            subanswers.append(
                {
                    "question": item["question"],
                    "generated": generated,
                    "candidate_index": index,
                    "search_terms": item.get("search_terms", []),
                    "sources_available": bool(applicable_sources),
                    "inapplicable_sources": inapplicable_sources,
                    "fact_tags": fact_tags,
                }
            )
            numeric_reference = "\n".join(
                [question, item["question"], *item.get("material_facts", [])]
            )
            conclusion = generated.get("applied_conclusion", {})
            if isinstance(conclusion, dict):
                candidates.append(
                    {
                        "kind": "conclusion",
                        "subanswer_index": index,
                        "text": conclusion.get("text", ""),
                        "citations": conclusion.get("citations", []),
                        "numeric_reference": numeric_reference,
                        "applicable_source_ids": [
                            source.source_id for source in applicable_sources
                        ],
                    }
                )
            for proposition in generated.get("propositions", []):
                candidates.append(
                    {
                        "kind": "proposition",
                        "subanswer_index": index,
                        "text": proposition.get("text", ""),
                        "citations": proposition.get("citations", []),
                        "numeric_reference": numeric_reference,
                        "applicable_source_ids": [
                            source.source_id for source in applicable_sources
                        ],
                    }
                )
            for issue in generated.get("other_issues", []):
                candidates.append(
                    {
                        "kind": "other_issue",
                        "subanswer_index": index,
                        "text": issue.get("text", ""),
                        "citations": issue.get("citations", []),
                        "numeric_reference": numeric_reference,
                        "applicable_source_ids": [
                            source.source_id for source in applicable_sources
                        ],
                    }
                )
            for row in generated.get("guarantor_rows", []):
                if not isinstance(row, dict):
                    continue
                candidates.append(
                    {
                        "kind": "guarantor_row",
                        "subanswer_index": index,
                        "text": _row_text(row),
                        "row": row,
                        "citations": row.get("citations", []),
                        "numeric_reference": (
                            numeric_reference
                            + "\n20 percent threshold\n"
                            + _row_text(row)
                        ),
                        "deterministic": bool(deterministic_rows),
                        "applicable_source_ids": [
                            source.source_id for source in applicable_sources
                        ],
                    }
                )

        # Planning may split one guarantor request into several subquestions,
        # each with a different retrieval slice. Build the final party/capacity
        # enumeration from the union so no capacity disappears between slices.
        if GUARANTY_TERMS.search(question) and applicable_source_pool:
            pooled_sources = list(applicable_source_pool.values())
            pooled_rows = deterministic_guarantor_rows(
                question, question, pooled_sources
            )
            guarantor_subanswer_index = next(
                (
                    index
                    for index, item in enumerate(plan)
                    if GUARANTY_TERMS.search(item["question"])
                ),
                0,
            )
            pooled_source_ids = [source.source_id for source in pooled_sources]
            for row in pooled_rows:
                candidates.append(
                    {
                        "kind": "guarantor_row",
                        "subanswer_index": guarantor_subanswer_index,
                        "text": _row_text(row),
                        "row": row,
                        "citations": row.get("citations", []),
                        "numeric_reference": (
                            question + "\n20 percent threshold\n" + _row_text(row)
                        ),
                        "deterministic": True,
                        "applicable_source_ids": pooled_source_ids,
                    }
                )

        validated_candidates = validate_candidate_citations(candidates, source_by_id)
        audit_results = audit_propositions(client, question, validated_candidates, source_by_id)
        for candidate_index, candidate in enumerate(validated_candidates):
            if candidate.get("deterministic") and candidate["kind"] == "guarantor_row":
                audit_results[candidate_index] = True
        supported_candidates = [
            candidate
            for index, candidate in enumerate(validated_candidates)
            if audit_results.get(index, False)
        ]
        for candidate in supported_candidates:
            for citation in candidate["citations"]:
                citation["supports_conclusion"] = True

        rendered_subanswers = []
        all_citations: list[dict[str, Any]] = []
        seen_guarantor_rows: set[tuple[str, str, float | None]] = set()
        for index, item in enumerate(subanswers):
            conclusion_candidates = [
                candidate
                for candidate in supported_candidates
                if candidate["kind"] == "conclusion"
                and candidate["subanswer_index"] == index
            ]
            matching = [
                candidate
                for candidate in supported_candidates
                if candidate["kind"] == "proposition"
                and candidate["subanswer_index"] == index
            ]
            row_candidates = [
                candidate
                for candidate in supported_candidates
                if candidate["kind"] == "guarantor_row"
                and candidate["subanswer_index"] == index
            ]
            propositions = []
            applied_conclusion = None
            if conclusion_candidates:
                candidate = conclusion_candidates[0]
                applied_conclusion = {
                    "text": candidate["text"],
                    "citations": candidate["citations"],
                    "arithmetic_valid": candidate.get("arithmetic_valid", True),
                }
                all_citations.extend(candidate["citations"])
            rejected_conclusion_citations = []
            for candidate_index, candidate in enumerate(validated_candidates):
                if (
                    candidate["kind"] == "conclusion"
                    and candidate["subanswer_index"] == index
                    and not audit_results.get(candidate_index, False)
                ):
                    rejected_conclusion_citations.extend(candidate["citations"])
            rejected_conclusion_citations.extend(
                build_citation(
                    source,
                    citation_preview(source.chunk_text),
                    False,
                    applicability_status="not_applicable",
                    applicability_reason=reason,
                )
                for source, reason in item["inapplicable_sources"]
            )
            rejected_conclusion_citations = dedupe_citations(
                rejected_conclusion_citations
            )
            for citation in rejected_conclusion_citations:
                citation["supports_conclusion"] = False
            generated_conclusion = item["generated"].get("applied_conclusion", {})
            generated_conclusion_text = (
                generated_conclusion.get("text", "")
                if isinstance(generated_conclusion, dict)
                else ""
            )
            guarantor_rows: list[dict[str, Any]] = []
            if row_candidates:
                # The table is the authoritative enumeration; do not repeat its
                # conclusion in prose above it.
                applied_conclusion = None
            if applied_conclusion or row_candidates:
                support_status = "supported"
                propositions = [
                    {
                        "text": candidate["text"],
                        "citations": candidate["citations"],
                        "arithmetic_valid": candidate.get("arithmetic_valid", True),
                    }
                    for candidate in matching
                ]
                answer = (
                    applied_conclusion["text"]
                    if applied_conclusion
                    else "See the guarantor table below for each required party and capacity."
                )
                if propositions:
                    answer += "\n\n" + "\n\n".join(
                        proposition["text"] for proposition in propositions
                    )
                for proposition in propositions:
                    all_citations.extend(proposition["citations"])
                for candidate in row_candidates:
                    row = dict(candidate["row"])
                    row_key = (
                        row.get("party", ""),
                        row.get("capacity", ""),
                        row.get("ownership_percentage"),
                    )
                    if row_key in seen_guarantor_rows:
                        continue
                    seen_guarantor_rows.add(row_key)
                    row["citations"] = candidate["citations"]
                    guarantor_rows.append(row)
                    all_citations.extend(candidate["citations"])
                no_provision = False
                support_note = None
            elif generated_conclusion_text or rejected_conclusion_citations:
                if item["inapplicable_sources"] and not item["sources_available"]:
                    support_status = "not_applicable"
                    reason = item["inapplicable_sources"][0][1]
                    support_note = f"Provision not applicable to this transaction type: {reason}."
                    answer = NOT_APPLICABLE
                else:
                    support_status = "not_established"
                    support_note = NOT_ESTABLISHED
                    answer = NOT_ESTABLISHED
                no_provision = False
            elif item["sources_available"]:
                support_status = "no_responsive_provision"
                searched = ", ".join(item["search_terms"]) or item["question"]
                answer = f"{NO_RESPONSIVE_PROVISION}: {searched}."
                no_provision = True
                support_note = answer
                guarantor_rows = []
            else:
                support_status = "retrieval_empty"
                searched = ", ".join(item["search_terms"]) or item["question"]
                answer = f"{NO_RESPONSIVE_PROVISION}: {searched}."
                no_provision = True
                support_note = answer
                guarantor_rows = []
            rendered_subanswers.append(
                {
                    "question": item["question"],
                    "answer": answer,
                    "no_provision": no_provision,
                    "applied_conclusion": applied_conclusion,
                    "propositions": propositions,
                    "guarantor_rows": guarantor_rows,
                    "support_status": support_status,
                    "support_note": support_note,
                    "searched_terms": item["search_terms"],
                    "rejected_citations": rejected_conclusion_citations,
                }
            )
            all_citations.extend(rejected_conclusion_citations)

        rendered_issues = []
        for candidate in supported_candidates:
            if candidate["kind"] != "other_issue":
                continue
            rendered_issues.append(
                {
                    "text": candidate["text"],
                    "citations": candidate["citations"],
                    "arithmetic_valid": candidate.get("arithmetic_valid", True),
                }
            )
            all_citations.extend(candidate["citations"])

        summary_sentences = [
            subanswer["applied_conclusion"]["text"]
            for subanswer in rendered_subanswers
            if subanswer.get("applied_conclusion")
        ][:3]
        summary = " ".join(summary_sentences)
        if standard_product_assumed:
            product_note = (
                "No loan product was specified; this analysis treats the transaction "
                "as a Standard 7(a) loan."
            )
            summary = f"{product_note} {summary}".strip()
        if not summary:
            summary = "No applied conclusion was established from the retrieved SOP provisions."
        answer_parts = [summary]
        for subanswer in rendered_subanswers:
            if len(rendered_subanswers) > 1:
                answer_parts.append(f"{subanswer['question']}\n{subanswer['answer']}")
            elif subanswer["answer"] != summary:
                answer_parts.append(subanswer["answer"])
        if rendered_issues:
            answer_parts.append(
                "Other issues identified:\n"
                + "\n".join(f"- {issue['text']}" for issue in rendered_issues)
            )

        unique_citations = dedupe_citations(all_citations)
        provisions_to_read = []
        provision_keys: set[tuple[str, int | None]] = set()
        for citation in unique_citations:
            provision_key = (
                citation.get("section_ref", ""),
                citation.get("page_number"),
            )
            if (
                not citation.get("supports_conclusion")
                or citation.get("applicability_status") != "applicable"
                or provision_key in provision_keys
            ):
                continue
            provision_keys.add(provision_key)
            provisions_to_read.append(citation)
            if len(provisions_to_read) == 4:
                break
        metadata_source = sources[0] if sources else None
        return jsonify(
            {
                "answer": "\n\n".join(answer_parts),
                "summary": summary,
                "source_version": (
                    metadata_source.sop_version if metadata_source else DEFAULT_SOP_VERSION
                ),
                "effective_date": (
                    metadata_source.effective_date
                    if metadata_source
                    else DEFAULT_EFFECTIVE_DATE
                ),
                "version_warning": version_warning,
                "date_warning": date_warning,
                "subanswers": rendered_subanswers,
                "other_issues": rendered_issues,
                "sources": unique_citations,
                "provisions_to_read": provisions_to_read,
            }
        )
    except RuntimeError as exc:
        app.logger.error("Configuration error: %s", exc)
        return jsonify({"error": str(exc)}), 503
    except Exception:
        app.logger.exception("SOP query failed")
        return jsonify({"error": "The SOP query could not be completed. Please try again."}), 502


def decompose_question(client: OpenAI, question: str) -> list[dict[str, Any]]:
    try:
        response = client.chat.completions.create(
            model=ANSWER_MODEL,
            max_tokens=900,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a retrieval planner for SBA SOP 50 10 8.1. Do not answer "
                        "the user. Split the question into the smallest set of discrete "
                        "policy questions that need separate retrieval. Preserve every "
                        "number, dollar amount, ownership percentage, entity role, and term "
                        "of art exactly. Record concrete facts in the prompt that may "
                        "implicate an additional SOP provision even if not directly asked. "
                        "Translate each sub-question into SOP vocabulary in search_terms, "
                        "including equity injection, source of equity injection, "
                        "seller-financed Note, standby, subordinated debt, guaranty, "
                        "trust, ownership, and personal guaranty."
                    ),
                },
                {"role": "user", "content": question},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "sop_query_plan",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "subquestions": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 4,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "question": {"type": "string"},
                                        "material_facts": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "search_terms": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                    },
                                    "required": [
                                        "question",
                                        "material_facts",
                                        "search_terms",
                                    ],
                                    "additionalProperties": False,
                                },
                            }
                        },
                        "required": ["subquestions"],
                        "additionalProperties": False,
                    },
                },
            },
        )
        result = parse_json(response.choices[0].message.content or "")
        subquestions = result.get("subquestions")
        if isinstance(subquestions, list) and subquestions:
            valid = [
                item
                for item in subquestions
                if isinstance(item, dict)
                and isinstance(item.get("question"), str)
                and item["question"].strip()
            ]
            if valid:
                # A single-intent question must not be expanded into unrelated
                # retrievals by the planner. Compound questions retain their
                # independently retrieved subquestions.
                if len(valid) > 1 and not re.search(
                    r"\b(and|also|whether)\b", question, re.IGNORECASE
                ):
                    return fallback_plan(question)
                return [
                    {
                        "question": item["question"].strip(),
                        "material_facts": [
                            fact
                            for fact in item.get("material_facts", [])
                            if isinstance(fact, str)
                        ],
                        "search_terms": list(
                            dict.fromkeys(
                                [
                                    term
                                    for term in item.get("search_terms", [])
                                    if isinstance(term, str) and term.strip()
                                ]
                                + build_search_terms(item["question"])
                            )
                        ),
                    }
                    for item in valid[:4]
                ]
    except Exception:
        app.logger.exception("Question decomposition failed; using the original question")
    return fallback_plan(question)


def retrieve_for_subquestion(
    conn: Any,
    client: OpenAI,
    subquestion: str,
    search_terms: list[str] | None = None,
) -> list[RetrievedSource]:
    searches = list(dict.fromkeys([subquestion, *(search_terms or [])]))
    if GUARANTY_TERMS.search(subquestion):
        searches.append(GUARANTY_RETRIEVAL_QUERY)
    if re.search(r"\b(robs|401\s*\(k\)|retirement trust|plan sponsor|plan trustee)\b", subquestion, re.IGNORECASE):
        searches.append(ROBS_RETRIEVAL_QUERY)
    if re.search(r"\bequity injection\b", subquestion, re.IGNORECASE):
        searches.append(EQUITY_RETRIEVAL_QUERY)
    if re.search(
        r"seller[-\s]?financ|seller note|standby|subordinated debt|equity injection|"
        r"project cost|startup|start-up",
        f"{subquestion} {' '.join(search_terms or [])}",
        re.IGNORECASE,
    ):
        searches.extend(
            [
                SELLER_NOTE_RETRIEVAL_QUERY,
                STARTUP_INJECTION_RETRIEVAL_QUERY,
                CHANGE_OWNERSHIP_INJECTION_RETRIEVAL_QUERY,
            ]
        )

    by_db_id: dict[int, RetrievedSource] = {}

    def add_rows(rows: list[tuple]) -> None:
        for row in rows:
            source = RetrievedSource(
                db_id=row[0],
                source_id=0,
                sop_version=row[1] or DEFAULT_SOP_VERSION,
                effective_date=(
                    row[2].isoformat()
                    if hasattr(row[2], "isoformat")
                    else (row[2] or DEFAULT_EFFECTIVE_DATE)
                ),
                page_number=row[3],
                section_ref=row[4],
                chunk_text=row[5],
                similarity=float(row[6]),
                transaction_types=tuple(row[7] or ()),
                entity_structures=tuple(row[8] or ()),
                party_roles=tuple(row[9] or ()),
                program_scopes=tuple(row[10] or ()),
                product_lines=tuple(row[11] or ()),
                loan_size_bands=tuple(row[12] or ()),
            )
            previous = by_db_id.get(source.db_id)
            if previous is None or source.similarity > previous.similarity:
                by_db_id[source.db_id] = source

    for search in searches:
        embedding = (
            client.embeddings.create(model=EMBEDDING_MODEL, input=search)
            .data[0]
            .embedding
        )
        query_vector = Vector(embedding)
        rows = conn.execute(
            """
            SELECT id, sop_version, effective_date, page_number, section_ref,
                   chunk_text, 1 - (embedding <=> %s) AS similarity,
                   transaction_types, entity_structures, party_roles, program_scopes,
                   product_lines, loan_size_bands
            FROM sop_chunks
            ORDER BY embedding <=> %s
            LIMIT %s
            """,
            (query_vector, query_vector, TOP_K),
        ).fetchall()
        add_rows(rows)
    if GUARANTY_TERMS.search(subquestion):
        direct_rows = conn.execute(
            """
            SELECT id, sop_version, effective_date, page_number, section_ref,
                   chunk_text, 1.0 AS similarity,
                   transaction_types, entity_structures, party_roles, program_scopes,
                   product_lines, loan_size_bands
            FROM sop_chunks
            WHERE section_ref ILIKE '%> Guaranties%'
               OR section_ref ILIKE '%> Personal Guaranties%'
            ORDER BY id
            LIMIT 6
            """
        ).fetchall()
        add_rows(direct_rows)
    if re.search(
        r"\besop\b|employee stock ownership",
        subquestion,
        re.IGNORECASE,
    ) or any(
        re.search(r"\besop\b|employee stock ownership", term, re.IGNORECASE)
        for term in (search_terms or [])
    ):
        esop_rows = conn.execute(
            """
            SELECT id, sop_version, effective_date, page_number, section_ref,
                   chunk_text, 1.0 AS similarity,
                   transaction_types, entity_structures, party_roles, program_scopes,
                   product_lines, loan_size_bands
            FROM sop_chunks
            WHERE section_ref ILIKE '%ESOP%'
               OR chunk_text ILIKE '%ESOP%'
            ORDER BY id
            LIMIT 12
            """
        ).fetchall()
        add_rows(esop_rows)
    product_pattern = None
    if re.search(r"sba\s+express|7\s*\(\s*a\s*\)\s+small", subquestion, re.IGNORECASE):
        product_pattern = "%7(a) Small%"
    elif re.search(r"export\s+working\s+capital", subquestion, re.IGNORECASE):
        product_pattern = "%Export Working Capital%"
    elif re.search(r"international\s+trade", subquestion, re.IGNORECASE):
        product_pattern = "%International Trade%"
    elif re.search(r"\bcaplines\b", subquestion, re.IGNORECASE):
        product_pattern = "%CAPLines%"
    elif re.search(r"\bmarc\b", subquestion, re.IGNORECASE):
        product_pattern = "%MARC%"
    if product_pattern:
        product_rows = conn.execute(
            """
            SELECT id, sop_version, effective_date, page_number, section_ref,
                   chunk_text, 1.0 AS similarity,
                   transaction_types, entity_structures, party_roles, program_scopes,
                   product_lines, loan_size_bands
            FROM sop_chunks
            WHERE section_ref ILIKE %s
            ORDER BY id
            LIMIT 20
            """,
            (product_pattern,),
        ).fetchall()
        add_rows(product_rows)
    if re.search(r"\bcollateral\b", f"{subquestion} {' '.join(search_terms or [])}", re.IGNORECASE):
        collateral_rows = conn.execute(
            """
            SELECT id, sop_version, effective_date, page_number, section_ref,
                   chunk_text, 1.0 AS similarity,
                   transaction_types, entity_structures, party_roles, program_scopes,
                   product_lines, loan_size_bands
            FROM sop_chunks
            WHERE section_ref ILIKE '%Collateral Requirements%'
               OR section_ref ILIKE '%> Collateral%'
            ORDER BY id
            LIMIT 12
            """
        ).fetchall()
        add_rows(collateral_rows)
    if re.search(
        r"seller[-\s]?financ|seller note|standby|subordinated debt|equity injection|"
        r"project cost|startup|start-up|injection",
        f"{subquestion} {' '.join(search_terms or [])}",
        re.IGNORECASE,
    ):
        equity_rows = conn.execute(
            """
            SELECT id, sop_version, effective_date, page_number, section_ref,
                   chunk_text, 1.0 AS similarity,
                   transaction_types, entity_structures, party_roles, program_scopes,
                   product_lines, loan_size_bands
            FROM sop_chunks
            WHERE chunk_text ILIKE '%Source of Equity Injection%'
               OR chunk_text ILIKE '%seller-financed Note%'
               OR chunk_text ILIKE '%Standby Agreements%'
               OR chunk_text ILIKE '%equity injection%'
            ORDER BY id
            LIMIT 12
            """
        ).fetchall()
        add_rows(equity_rows)
    return [
        source
        for source in sorted(
            by_db_id.values(), key=lambda source: source.similarity, reverse=True
        )
        if source.similarity >= MIN_RETRIEVAL_SIMILARITY
    ]


def generate_propositions(
    client: OpenAI,
    original_question: str,
    subquestion: str,
    material_facts: list[str],
    sources: list[RetrievedSource],
) -> dict[str, Any]:
    context = format_context(sources)
    response = client.chat.completions.create(
        model=ANSWER_MODEL,
        max_tokens=1800,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "Answer only from the supplied SOP passages. First write one short "
                    "applied conclusion in your own words that answers the discrete "
                    "sub-question against the user's facts. Do not copy a quoted rule "
                    "into the applied conclusion. Attach citations to that conclusion. "
                    "Then provide atomic supporting policy propositions, each with a "
                    "citation. A proposition is allowed only when its cited passage "
                    "actually states the complete proposition. Do not use general legal, "
                    "lending, or tax knowledge. Preserve SOP terms of art exactly: plan "
                    "sponsor, plan participant, plan trustee, Borrower, Co-Borrower, "
                    "Applicant, and Operating Company are distinct roles. Apply dollar "
                    "amounts and ownership percentages from the prompt. Show arithmetic "
                    "for computed amounts only when the cited rule and stated facts "
                    "supply the rate and base. If a point is not addressed by the "
                    "passages, leave the conclusion empty rather than guessing. When "
                    "enumerating guarantors, list every party separately with its "
                    "capacity and the provision that triggers its obligation. Return "
                    "one structured row per party per capacity in guarantor_rows; never "
                    "collapse multiple capacities into prose. Include party, capacity, "
                    "ownership percentage when stated, guaranty type, triggering "
                    "provision, additional conditions, status, and citations. Identify "
                    "material unasked issues only when a prompt fact triggers a cited "
                    "SOP provision."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"ORIGINAL QUESTION:\n{original_question}\n\n"
                    f"DISCRETE SUB-QUESTION:\n{subquestion}\n\n"
                    f"MATERIAL FACTS TO CHECK:\n{json.dumps(material_facts)}\n\n"
                    f"SOP CONTEXT:\n{context}"
                ),
            },
        ],
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "sop_grounded_propositions",
                "strict": True,
                "schema": {
                    "type": "object",
                    "properties": {
                        "applied_conclusion": {"$ref": "#/$defs/conclusion_claim"},
                        "propositions": {"$ref": "#/$defs/claim_list"},
                        "other_issues": {"$ref": "#/$defs/claim_list"},
                        "guarantor_rows": {"$ref": "#/$defs/guarantor_row_list"},
                    },
                    "required": [
                        "applied_conclusion",
                        "propositions",
                        "other_issues",
                        "guarantor_rows",
                    ],
                    "additionalProperties": False,
                    "$defs": {
                        "conclusion_claim": {
                            "type": "object",
                            "properties": {
                                "text": {"type": "string"},
                                "citations": {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "source_id": {"type": "integer"},
                                            "quote": {"type": "string"},
                                        },
                                        "required": ["source_id", "quote"],
                                        "additionalProperties": False,
                                    },
                                },
                            },
                            "required": ["text", "citations"],
                            "additionalProperties": False,
                        },
                        "claim_list": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "text": {"type": "string"},
                                    "citations": {
                                        "type": "array",
                                        "minItems": 1,
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "source_id": {"type": "integer"},
                                                "quote": {"type": "string"},
                                            },
                                            "required": ["source_id", "quote"],
                                            "additionalProperties": False,
                                        },
                                    },
                                },
                                "required": ["text", "citations"],
                                "additionalProperties": False,
                            },
                        },
                        "guarantor_row_list": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "party": {"type": "string"},
                                    "capacity": {"type": "string"},
                                    "ownership_percentage": {
                                        "type": ["number", "null"]
                                    },
                                    "ownership_comparison": {
                                        "type": ["string", "null"]
                                    },
                                    "guaranty_type": {"type": "string"},
                                    "triggering_provision": {"type": "string"},
                                    "additional_conditions": {"type": "string"},
                                    "status": {
                                        "type": "string",
                                        "enum": ["required", "unresolved"],
                                    },
                                    "citations": {
                                        "type": "array",
                                        "minItems": 1,
                                        "items": {
                                            "type": "object",
                                            "properties": {
                                                "source_id": {"type": "integer"},
                                                "quote": {"type": "string"},
                                            },
                                            "required": ["source_id", "quote"],
                                            "additionalProperties": False,
                                        },
                                    },
                                },
                                "required": [
                                    "party",
                                    "capacity",
                                    "ownership_percentage",
                                    "ownership_comparison",
                                    "guaranty_type",
                                    "triggering_provision",
                                    "additional_conditions",
                                    "status",
                                    "citations",
                                ],
                                "additionalProperties": False,
                            },
                        },
                    },
                },
            },
        },
    )
    result = parse_json(response.choices[0].message.content or "")
    return {
        "applied_conclusion": result.get(
            "applied_conclusion", {"text": "", "citations": []}
        ),
        "propositions": result.get("propositions", []),
        "other_issues": result.get("other_issues", []),
        "guarantor_rows": result.get("guarantor_rows", []),
    }


def validate_candidate_citations(
    candidates: list[dict[str, Any]], source_by_id: dict[int, RetrievedSource]
) -> list[dict[str, Any]]:
    valid_candidates = []
    for candidate in candidates:
        if not isinstance(candidate.get("text"), str) or not candidate["text"].strip():
            continue
        citations = []
        for citation in candidate.get("citations", []):
            if not isinstance(citation, dict):
                continue
            source_id = citation.get("source_id")
            quote = citation.get("quote")
            source = source_by_id.get(source_id)
            if not isinstance(source_id, int) or not isinstance(quote, str) or not source:
                continue
            allowed_source_ids = set(candidate.get("applicable_source_ids", []))
            if source_id not in allowed_source_ids:
                continue
            verified_quote = find_verbatim_quote(quote, source.chunk_text)
            if verified_quote is None:
                continue
            citations.append(build_citation(source, verified_quote, False))
        if citations:
            evidence_text = "\n".join(citation["quote"] for citation in citations)
            arithmetic_valid = deterministic_arithmetic_check(
                candidate["text"],
                candidate.get("numeric_reference", ""),
                evidence_text,
            )
            if not arithmetic_valid:
                app.logger.warning(
                    "Withholding numerically invalid SOP proposition: %s",
                    candidate["text"],
                )
                continue
            valid_candidates.append(
                {
                    **candidate,
                    "citations": citations,
                    "arithmetic_valid": arithmetic_valid,
                }
            )
    return valid_candidates


def audit_propositions(
    client: OpenAI,
    original_question: str,
    candidates: list[dict[str, Any]],
    source_by_id: dict[int, RetrievedSource],
) -> dict[int, bool]:
    if not candidates:
        return {}
    audit_items = []
    for index, candidate in enumerate(candidates):
        evidence = []
        for citation in candidate["citations"]:
            source = source_by_id[citation["source_id"]]
            evidence.append(
                {
                    "source_id": source.source_id,
                    "section_ref": source.section_ref,
                    "quote": citation["quote"],
                }
            )
        audit_items.append(
            {
                "index": index,
                "kind": candidate["kind"],
                "proposition": candidate["text"],
                "evidence": evidence,
            }
        )
    try:
        response = client.chat.completions.create(
            model=ANSWER_MODEL,
            max_tokens=1400,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are an independent citation auditor. For each item, return "
                        "supports=true only when the cited evidence supports the item as "
                        "written. Supporting propositions must be completely stated by "
                        "their cited quote. An applied conclusion may apply a directly "
                        "stated SOP rule to the concrete facts in the original question; "
                        "the quote does not need to repeat the user's facts. For applied "
                        "conclusions, verify that every actor, threshold, exception, "
                        "amount, comparison, and computed result follows from the "
                        "original facts plus the cited rules. Reject claims that add "
                        "unstated actors, thresholds, exceptions, amounts, or legal "
                        "conclusions. Do not repair or rewrite propositions. A false "
                        "entailment check must return supports=false."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Original question:\n{original_question}\n\n"
                        f"Propositions and cited evidence:\n{json.dumps(audit_items)}"
                    ),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "sop_citation_audit",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "checks": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "index": {"type": "integer"},
                                        "supports": {"type": "boolean"},
                                    },
                                    "required": ["index", "supports"],
                                    "additionalProperties": False,
                                },
                            }
                        },
                        "required": ["checks"],
                        "additionalProperties": False,
                    },
                },
            },
        )
        result = parse_json(response.choices[0].message.content or "")
        return {
            item["index"]: item["supports"] is True
            for item in result.get("checks", [])
            if isinstance(item, dict) and isinstance(item.get("index"), int)
        }
    except Exception:
        app.logger.exception("Citation audit failed; withholding unsupported claims")
        return {}


def format_context(sources: list[RetrievedSource]) -> str:
    return "\n\n".join(
        (
            f'<SOURCE id="{source.source_id}" version="{source.sop_version}" '
            f'effective_date="{source.effective_date}" '
            f'page="{source.page_number or "not recorded"}" '
            f'section_ref="{source.section_ref}">\n{source.chunk_text}\n</SOURCE>'
        )
        for source in sources
    )


def build_citation(
    source: RetrievedSource,
    quote: str,
    supports_conclusion: bool,
    applicability_status: str = "applicable",
    applicability_reason: str | None = None,
) -> dict[str, Any]:
    return {
        "source_id": source.source_id,
        "section_ref": source.section_ref,
        "quote": quote,
        "source_chunk": source.chunk_text,
        "source_version": source.sop_version,
        "effective_date": source.effective_date,
        "page_number": source.page_number,
        "quote_located": True,
        "supports_conclusion": supports_conclusion,
        "verified": True,
        "applicability_status": applicability_status,
        "applicability_reason": applicability_reason,
    }


def citation_preview(text: str) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    for sentence in sentences:
        if len(sentence.strip()) >= 24:
            return sentence.strip()
    return text.strip()[:700]


def dedupe_citations(citations: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique = {}
    for citation in citations:
        key = (citation["source_id"], citation["quote"])
        unique[key] = citation
    return list(unique.values())


def parse_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError("The model returned an invalid response shape.")
    return value


def find_verbatim_quote(quote: str, source: str) -> str | None:
    """Return a source-backed quote, repairing only formatting/trailing punctuation."""
    if not quote.strip():
        return None
    if quote in source:
        return quote

    normalized_quote = re.sub(r"\s+", " ", quote).strip()
    normalized_source = re.sub(r"\s+", " ", source).strip()
    if normalized_quote in normalized_source:
        return quote.strip()

    prefix = quote.strip().rstrip(".!?").rstrip()
    if len(prefix) < 40:
        return None
    start = source.find(prefix)
    if start >= 0:
        end_match = re.search(r"[.!?](?=\s|$)", source[start + len(prefix) :])
        if end_match:
            end = start + len(prefix) + end_match.end()
            return source[start:end]

    quote_tokens = re.findall(r"[A-Za-z0-9%]+", quote.casefold())
    if len(quote_tokens) < 8:
        return None
    best_sentence = None
    best_score = 0.0
    for sentence in re.split(r"(?<=[.!?])\s+", source):
        source_tokens = re.findall(r"[A-Za-z0-9%]+", sentence.casefold())
        if len(source_tokens) < 8:
            continue
        score = SequenceMatcher(None, quote_tokens, source_tokens).ratio()
        matching_tokens = sum(
            block.size
            for block in SequenceMatcher(None, quote_tokens, source_tokens).get_matching_blocks()
        )
        coverage = matching_tokens / min(len(quote_tokens), len(source_tokens))
        if score >= 0.62 and coverage >= 0.62 and score > best_score:
            best_sentence = sentence.strip()
            best_score = score
    return best_sentence


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)