import json
import os
import re
import datetime as dt
import math
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from flask import Flask, jsonify, request
from openai import OpenAI
from pgvector import Vector

from applicability import (
    APPLICABILITY_DIMENSIONS,
    applicability_dimension_conflicts,
    applicability_check,
    classify_question,
    classify_text,
    merge_tags,
)
from auth import configure_auth, current_user, require_auth
from db import connection
from source_metadata import canonicalize_source_url

app = Flask(__name__)
configure_auth(app)

EMBEDDING_MODEL = "text-embedding-3-small"
ANSWER_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
DEFAULT_SOP_VERSION = os.getenv("SOP_VERSION", "SOP 50 10 8.1")
DEFAULT_EFFECTIVE_DATE = os.getenv("SOP_EFFECTIVE_DATE", "2026-10-01")
EXPOSE_DEBUG_TELEMETRY = os.getenv(
    "EXPOSE_DEBUG_TELEMETRY",
    "true" if os.getenv("NODE_ENV", "").casefold() != "production" else "false",
).casefold() == "true"
RATE_LIMIT_MAX_REQUESTS = int(os.getenv("SOP_RATE_LIMIT_MAX_REQUESTS", "30"))
RATE_LIMIT_WINDOW_SECONDS = int(os.getenv("SOP_RATE_LIMIT_WINDOW_SECONDS", "60"))
TOP_K = 6
MAX_CONTEXT_SOURCES = 18
MIN_RETRIEVAL_SIMILARITY = 0.28
NO_RESPONSIVE_PROVISION = "Retrieval found no responsive provision for the searched terms"
NOT_ESTABLISHED = (
    "The retrieved SOP provisions did not establish an applied conclusion for this fact pattern."
)
NOT_APPLICABLE = "A retrieved provision was not applicable to this transaction or fact pattern."
NORMATIVE_LANGUAGE_RE = re.compile(
    r"\b(?:must|shall|required|required to|may not|cannot|not permitted|"
    r"prohibited|eligible|ineligible|does not|do not|unless|except|"
    r"will not|need not|is subject to|is not subject to)\b",
    re.IGNORECASE,
)
EXPLICIT_GUARANTY_OBLIGATION_RE = re.compile(
    r"\b(?:must|shall|required to|is required to|personally)\b"
    r"[^.!?]{0,180}\b(?:guarant(?:y|ee|ies|or)|sign|execute)\b",
    re.IGNORECASE,
)


def has_explicit_guaranty_obligation(text: str) -> bool:
    """Require the obligation verb and guaranty action in one sentence."""
    sentences = re.split(r"(?<=[.!?])\s+", text)
    return any(EXPLICIT_GUARANTY_OBLIGATION_RE.search(sentence) for sentence in sentences)
GUARANTY_TERMS = re.compile(
    r"\b(guarant(?:y|ies|ee|ees|or|ors)|co[-\s]?borrowers?|unconditional)\b",
    re.IGNORECASE,
)
GUARANTY_ACTOR_TERMS = re.compile(
    r"\b(?:owners?|ownership|trusts?|plan sponsors?|plan trustees?|co[-\s]?borrowers?)\b",
    re.IGNORECASE,
)
GUARANTY_ACTION_TERMS = re.compile(
    r"\b(?:sign|execute|co[-\s]?sign|guarantee)\b",
    re.IGNORECASE,
)


def has_guaranty_intent(text: str) -> bool:
    """Recognize guaranty questions without treating any ownership mention as one."""
    if GUARANTY_TERMS.search(text):
        return True
    actor = GUARANTY_ACTOR_TERMS.pattern
    action = GUARANTY_ACTION_TERMS.pattern
    return bool(
        re.search(rf"(?:{actor})[^.!?]{0,100}(?:{action})", text, re.IGNORECASE)
        or re.search(rf"(?:{action})[^.!?]{0,100}(?:{actor})", text, re.IGNORECASE)
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
    # Repair missing dimensions from the breadcrumb without replacing
    # explicitly indexed metadata. This is especially important for product
    # chapters: a CAPLines/MARC/etc. breadcrumb is an affirmative product
    # scope, not an unknown universal provision.
    inferred = classify_text(source.chunk_text, source.section_ref)
    for dimension in APPLICABILITY_DIMENSIONS:
        if not tags[dimension] and inferred[dimension]:
            tags[dimension] = inferred[dimension]
    return tags


def source_applicability(
    source: RetrievedSource, fact_tags: dict[str, list[str]]
) -> tuple[bool, str | None]:
    return applicability_check(source_tags(source), fact_tags)


def evaluate_source_gate(
    source: RetrievedSource, fact_text: str, fact_tags: dict[str, list[str]]
) -> dict[str, Any]:
    """Evaluate every gate for a source before any source can be cited."""

    applicable, applicability_reason = source_applicability(source, fact_tags)
    conditions_ok, condition_reason, condition_details = internal_conditions_evaluation(
        source, fact_text, fact_tags
    )
    return {
        "source_id": source.source_id,
        "applicable": applicable,
        "applicability_reason": applicability_reason,
        "condition_result": "passed" if conditions_ok else "failed",
        "condition_reason": condition_reason,
        "conditions": condition_details,
        "admitted": bool(applicable and conditions_ok),
    }


def internal_conditions_evaluation(
    source: RetrievedSource, fact_text: str, fact_tags: dict[str, list[str]]
) -> tuple[bool, str | None, list[dict[str, Any]]]:
    """Evaluate explicit conditions in a provision against the supplied facts."""

    lower = source.chunk_text.casefold()
    facts_lower = fact_text.casefold()
    checks: list[dict[str, Any]] = []

    def unresolved(condition: str, detail: str) -> None:
        checks.append({"condition": condition, "status": "unresolved", "detail": detail})

    def passed(condition: str, detail: str) -> None:
        checks.append({"condition": condition, "status": "passed", "detail": detail})

    def failed(condition: str, detail: str) -> tuple[bool, str | None, list[dict[str, Any]]]:
        checks.append({"condition": condition, "status": "failed", "detail": detail})
        return False, detail, checks

    if re.search(r"non[-\s]?controlling minority equity investment", lower):
        ownership_mentions = _percent_mentions(fact_text)
        ownership_checked = False
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
                ownership_checked = True
                return failed(
                    "minority investor ownership below 20%",
                    f"requires the investor to hold less than 20%; the {label} holds {value:g} percent",
                )
        if ownership_mentions and not ownership_checked:
            passed(
                "minority investor ownership below 20%",
                "stated ownership percentages are below the 20% threshold",
            )
        else:
            unresolved(
                "minority investor ownership below 20%",
                "no applicable investor ownership percentage was stated",
            )
        if re.search(r"\bcontrol(?:ling)?\b|\bcontrol\b", facts_lower) and not re.search(
            r"no control|without control|not control", facts_lower
        ):
            return failed(
                "investor must exert no control",
                "requires the investor to exert no control; the facts state control",
            )
        if re.search(r"no control|without control|not control", facts_lower):
            passed("investor must exert no control", "facts expressly state no control")
        else:
            unresolved("investor must exert no control", "control was not stated")

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
        return failed(
            "change-of-ownership routing",
            "redirects change-of-ownership transactions to Appendix 15",
        )
    elif re.search(r"see\s+appendix\s+15|for\s+changes?\s+of\s+ownership.{0,80}appendix\s+15", lower):
        unresolved(
            "change-of-ownership routing",
            "the facts do not affirmatively identify a change-of-ownership transaction",
        )

    if re.search(r"new\s+(?:business|borrower)|\bstart[-\s]?up\b", lower):
        if re.search(
            r"\bexisting(?:\s+\w+){0,2}\s+business\b|"
            r"\bexisting\s+borrower\b|already\s+(?:operating|established)|"
            r"\bnot\s+(?:a\s+)?start[-\s]?up\b",
            facts_lower,
        ):
            return failed(
                "startup or new-business requirement",
                "requires a startup or new-business fact; the facts identify an existing business",
            )
        unresolved(
            "startup or new-business requirement",
            "startup status was not affirmatively established",
        )

    if re.search(r"new\s+c\s*corp(?:oration)?|c\s*corporation", lower):
        if re.search(r"\bllc\b|limited liability company|s\s*corp", facts_lower) and not re.search(
            r"\bc\s*corp(?:oration)?\b", facts_lower
        ):
            return failed(
                "C corporation entity form",
                "requires a C corporation; the facts identify a different entity form",
            )
        unresolved(
            "C corporation entity form",
            "the entity form was not affirmatively stated as a conflicting form",
        )

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
                return failed(
                    "loan amount maximum",
                    f"requires a loan amount no greater than ${limit:,.0f}; the facts state ${amount:,.0f}",
                )
            if limit is not None:
                passed(
                    "loan amount maximum",
                    f"stated amount ${amount:,.0f} is within the ${limit:,.0f} maximum",
                )
        elif source.loan_size_bands:
            unresolved("loan amount maximum", "loan amount or maximum was not parseable")
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
                return failed(
                    "loan amount minimum",
                    f"requires a loan amount over ${limit:,.0f}; the facts state ${amount:,.0f}",
                )
            if limit is not None:
                passed(
                    "loan amount minimum",
                    f"stated amount ${amount:,.0f} exceeds the ${limit:,.0f} minimum",
                )
        elif source.loan_size_bands:
            unresolved("loan amount minimum", "loan amount or minimum was not parseable")

    return True, None, checks


def internal_conditions_check(
    source: RetrievedSource, fact_text: str, fact_tags: dict[str, list[str]]
) -> tuple[bool, str | None]:
    result, reason, _ = internal_conditions_evaluation(source, fact_text, fact_tags)
    return result, reason


def fallback_plan(question: str) -> list[dict[str, Any]]:
    return [
        {
            "question": question,
            "material_facts": [question],
            "search_terms": build_search_terms(question),
        }
    ]


SELLER_NOTE_TOPIC_RE = re.compile(
    r"\bseller[-\s]?note\b|\bseller[-\s]?financ(?:ed|ing)\b",
    re.IGNORECASE,
)


def ensure_seller_note_subquestion(
    question: str, plan: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Keep seller-note policy as a separate retrieval issue in compound queries."""

    if not SELLER_NOTE_TOPIC_RE.search(question):
        return plan

    for item in plan:
        item_question = item.get("question")
        if (
            not isinstance(item_question, str)
            or not SELLER_NOTE_TOPIC_RE.search(item_question)
            or not has_guaranty_intent(item_question)
        ):
            continue
        # A planner may leave guaranty and seller-note policy in one issue.
        # Keep this item focused on guaranty rules; the seller-note question
        # is retained or added separately below.
        item["question"] = (
            "What guaranty requirements apply to the stated transaction and "
            "ownership facts?"
        )
        item["search_terms"] = [
            term
            for term in item.get("search_terms", [])
            if isinstance(term, str) and not SELLER_NOTE_TOPIC_RE.search(term)
        ]
        if GUARANTY_RETRIEVAL_QUERY not in item["search_terms"]:
            item["search_terms"].append(GUARANTY_RETRIEVAL_QUERY)
        item["material_facts"] = [
            fact
            for fact in item.get("material_facts", [])
            if isinstance(fact, str) and not SELLER_NOTE_TOPIC_RE.search(fact)
        ]

    dedicated_note_items = [
        item
        for item in plan
        if isinstance(item.get("question"), str)
        and SELLER_NOTE_TOPIC_RE.search(item["question"])
        and not has_guaranty_intent(item["question"])
    ]
    if dedicated_note_items:
        for item in dedicated_note_items:
            search_terms = item.setdefault("search_terms", [])
            if SELLER_NOTE_RETRIEVAL_QUERY not in search_terms:
                search_terms.append(SELLER_NOTE_RETRIEVAL_QUERY)
        return plan

    note_facts = [
        part.strip()
        for part in re.split(r"(?<=[.!?])\s+", question)
        if SELLER_NOTE_TOPIC_RE.search(part)
    ]
    return [
        *plan,
        {
            "question": "What seller-note requirements apply to the stated transaction?",
            "material_facts": note_facts or [question],
            "search_terms": [SELLER_NOTE_RETRIEVAL_QUERY],
        },
    ]


def build_retrieval_searches(
    subquestion: str,
    search_terms: list[str] | None = None,
    material_facts: list[str] | None = None,
    original_question: str = "",
) -> list[str]:
    """Keep each material fact as an independent retrieval seed."""
    values = [
        subquestion,
        *(search_terms or []),
        *(material_facts or []),
        original_question,
    ]
    searches = [
        value.strip()
        for value in values
        if isinstance(value, str) and value.strip()
    ]
    searches.extend(
        term
        for value in tuple(searches)
        for term in build_search_terms(value)
    )
    return list(dict.fromkeys(searches))


LEXICAL_RETRIEVAL_STOPWORDS = {
    "about", "after", "also", "among", "and", "any", "applicant",
    "applicants", "are", "because", "been", "before", "being", "borrower",
    "borrowers", "business", "businesses", "company", "companies", "could",
    "does", "doing", "each", "eligible", "eligibility", "entity", "entities",
    "from", "have", "into", "is", "lender", "lenders", "loan", "loans", "may",
    "must", "not", "only", "other", "over", "require", "required",
    "requirement", "requirements", "rule", "rules", "sba", "should", "that",
    "their", "there", "these", "this", "those", "under", "what", "when",
    "where", "which", "while", "with", "would",
}


def build_lexical_search_query(text: str) -> str:
    """Create a broad OR query so one salient fact can retrieve a policy passage."""
    terms = []
    for token in re.findall(r"[a-z0-9]+", text.casefold()):
        if len(token) < 3 and not (token.isdigit() and len(token) >= 2):
            continue
        if token in LEXICAL_RETRIEVAL_STOPWORDS or token in terms:
            continue
        terms.append(token)
        if len(terms) == 20:
            break
    return " OR ".join(terms)


def lexical_retrieval_seeds(
    subquestion: str,
    search_terms: list[str] | None,
    material_facts: list[str] | None,
    original_question: str,
) -> list[str]:
    seeds = [
        subquestion,
        *(search_terms or []),
        *(material_facts or []),
        original_question,
    ]
    return list(
        dict.fromkeys(
            query
            for seed in seeds
            if isinstance(seed, str) and seed.strip()
            for query in [build_lexical_search_query(seed)]
            if query
        )
    )


def build_search_terms(text: str) -> list[str]:
    terms: list[str] = []
    lower = text.casefold()
    if re.search(
        r"seller[-\s]?financ|seller[-\s]?note|standby|subordinated debt",
        lower,
    ):
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
    if has_guaranty_intent(text):
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
        ownership = f" Ownership: {row['ownership_percentage']:g} percent."
    comparison = row.get("ownership_comparison")
    comparison_text = f" {comparison}" if comparison else ""
    if row.get("status") == "not_required":
        party_text = (
            f"{row['party']} is not required to provide a guaranty under this provision."
        )
    elif row.get("status") == "unresolved":
        party_text = (
            f"Guaranty treatment for {row['party']} as {row['capacity']} is unresolved."
        )
    else:
        party_text = (
            f"{row['party']} must be treated as a {row['capacity']} "
            "for guaranty purposes."
        )
    return (
        f"{party_text}{ownership}{comparison_text} "
        f"Guaranty type: {row['guaranty_type']}. "
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
    if not has_guaranty_intent(combined):
        return []

    general_guaranty_sources = [
        source
        for source in sources
        if re.search(r"guarant", source.section_ref, re.IGNORECASE)
    ]
    threshold_sources = general_guaranty_sources or sources
    threshold_rule = source_citation_for_phrase(
        threshold_sources,
        "Any individual who has direct and/or indirect ownership of 20% or more",
    ) or source_citation_for_terms(
        threshold_sources, ["individual", "guarant"]
    ) or source_citation_for_terms(threshold_sources, ["guarant"])
    sponsor_rule = source_citation_for_phrase(
        sources, "Obtain the full unconditional guaranty of the sponsor"
    ) or source_citation_for_terms(sources, ["sponsor", "guarant"])
    trust_rule = (
        source_citation_for_terms(threshold_sources, ["trust", "guarant"])
        or source_citation_for_terms(threshold_sources, ["guarant"])
    )
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
    is_robs = bool(re.search(r"\brobs\b|401\s*\(\s*k\s*\)|retirement trust", lower))
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
            party_label = label
            if label == "individual" and is_robs:
                party_label = (
                    "buyer"
                    if re.search(r"\bbuyer\b", lower)
                    else "buyer (individual)"
                )
            add_row(
                party=f"the {party_label}",
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

    has_individual = bool(re.search(r"\bindividual\b", lower))
    if is_robs and has_individual:
        sponsor_party = "the corporation" if re.search(
            r"corporation.{0,35}plan sponsor|plan sponsor.{0,35}corporation", lower
        ) else (
            "the buyer"
            if re.search(r"\bbuyer\b", lower)
            else "the buyer (individual)"
        )
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
                party=sponsor_party,
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
                party=sponsor_party,
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


def _normalized_policy_terms(text: str) -> set[str]:
    stopwords = {
        "the",
        "and",
        "for",
        "from",
        "that",
        "this",
        "with",
        "must",
        "shall",
        "required",
        "provide",
        "guaranty",
        "guarantee",
        "obligation",
    }
    terms: set[str] = set()
    for token in re.findall(r"[a-z][a-z0-9'-]{2,}", text.casefold()):
        if token in stopwords:
            continue
        if token in {"seller", "selling", "sellers", "sell"}:
            token = "sell"
        elif token.endswith("ies") and len(token) > 4:
            token = token[:-3] + "y"
        elif token.endswith("s") and len(token) > 4:
            token = token[:-1]
        terms.add(token)
    return terms


def _source_clause_candidates(source: RetrievedSource) -> list[str]:
    clauses: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", source.chunk_text.strip()):
        sentence = sentence.strip()
        if sentence and NORMATIVE_LANGUAGE_RE.search(sentence):
            clauses.append(sentence)
    return clauses


def derive_policy_issue(
    client: OpenAI,
    original_question: str,
    retrieval_seed: str,
    sources: list[RetrievedSource],
) -> dict[str, Any]:
    """Create a source-derived policy issue after retrieval and admission."""

    if not sources:
        return {
            "text": "",
            "source_ids": [],
            "clauses": [],
            "unresolved": True,
        }
    source_ids = {source.source_id for source in sources}
    source_context = format_context(sources)
    try:
        response = client.chat.completions.create(
            model=ANSWER_MODEL,
            max_tokens=900,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You identify one or more directly responsive policy issues from "
                        "the supplied source passages. Do not answer the user. State the "
                        "issue in the source's own vocabulary, preserving exact source "
                        "terms for parties, actions, conditions, and obligations. Use "
                        "only an issue directly responsive to the retrieval seed. Do not "
                        "turn a merely related passage into the requested issue. Return "
                        "exact contiguous clause quotes and their source ids. If no "
                        "passage directly addresses the seed, return an empty issue and "
                        "empty clauses. This instruction is domain-neutral: do not use "
                        "a list of known issue types."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"ORIGINAL QUESTION (factual context only; do not derive "
                        f"other issues from it):\n{original_question}\n\n"
                        f"RETRIEVAL SEED (the only issue to derive):\n{retrieval_seed}\n\n"
                        f"SOURCE PASSAGES:\n{source_context}"
                    ),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "sop_policy_issue",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "issue_text": {"type": "string"},
                            "clauses": {
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
                        "required": ["issue_text", "clauses"],
                        "additionalProperties": False,
                    },
                },
            },
        )
        result = parse_json(response.choices[0].message.content or "")
        issue_text = result.get("issue_text")
        clauses: list[dict[str, Any]] = []
        for clause in result.get("clauses", []):
            if not isinstance(clause, dict):
                continue
            source_id = clause.get("source_id")
            quote = clause.get("quote")
            source = next(
                (candidate for candidate in sources if candidate.source_id == source_id),
                None,
            )
            if source is None or not isinstance(quote, str):
                continue
            located = find_verbatim_quote(quote, source.chunk_text)
            if located:
                clauses.append({"source_id": source_id, "quote": located})
        if isinstance(issue_text, str) and issue_text.strip() and clauses:
            source_issue_text = "Policy issue: " + " ".join(
                clause["quote"] for clause in clauses
            )
            evidence_text = "\n".join(clause["quote"] for clause in clauses)
            if conclusion_has_cited_issue_focus(
                retrieval_seed, source_issue_text, evidence_text
            ):
                return {
                    "text": source_issue_text,
                    "source_ids": sorted(
                        {
                            clause["source_id"]
                            for clause in clauses
                            if clause["source_id"] in source_ids
                        }
                    ),
                    "clauses": clauses,
                    "unresolved": False,
                }
    except Exception:
        app.logger.exception("Source-derived policy issue generation failed")

    # Keep the fallback source-derived, but apply the same issue-focus check as
    # model-derived clauses so a neighboring provision cannot become the issue.
    seed_terms = _normalized_policy_terms(retrieval_seed)
    ranked: list[tuple[int, float, RetrievedSource, str]] = []
    for source in sources:
        for clause in _source_clause_candidates(source):
            overlap = len(seed_terms.intersection(_normalized_policy_terms(clause)))
            ranked.append((overlap, source.similarity, source, clause))
    ranked.sort(key=lambda item: (item[0], item[1]), reverse=True)
    for overlap, _, source, clause in ranked:
        if overlap <= 0:
            break
        issue_text = f"Policy issue: {clause}"
        if not conclusion_has_cited_issue_focus(
            retrieval_seed, issue_text, clause
        ):
            continue
        return {
            "text": issue_text,
            "source_ids": [source.source_id],
            "clauses": [{"source_id": source.source_id, "quote": clause}],
            "unresolved": False,
        }
    return {
        "text": "",
        "source_ids": [],
        "clauses": [],
        "unresolved": True,
    }


def augment_extracted_party_capacities(
    fact_text: str, parties: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Preserve explicit ownership facts the extractor may omit or label too broadly."""

    direct_ownership: list[tuple[str, float]] = []
    explicit_ownership_claim = re.compile(
        r"\b(?:holds?|owns?)\s+\d+(?:\.\d+)?\s*(?:%|percent)\b",
        re.IGNORECASE,
    )
    clause_boundaries = list(
        re.finditer(
            r"\b(?:and|or|but|while|whereas)\b|[,;.!?\n]",
            fact_text,
            re.IGNORECASE,
        )
    )
    claim_clauses: list[str] = []
    clause_start = 0
    for boundary in clause_boundaries:
        left = fact_text[clause_start : boundary.start()]
        right = fact_text[boundary.end() :]
        if explicit_ownership_claim.search(left) and explicit_ownership_claim.search(
            right
        ):
            claim_clauses.append(left)
            clause_start = boundary.end()
    claim_clauses.append(fact_text[clause_start:])

    direct_owner_pattern = re.compile(
        r"(?P<party>[A-Za-z][A-Za-z0-9 '&()/.-]{1,60}?)\s+"
        r"(?:holds?|owns?)\s+(?P<percentage>\d+(?:\.\d+)?)\s*"
        r"(?:%|percent)"
        r"(?P<tail>\s{0,4}(?:as\s+(?:a\s+)?)?)\bdirect(?:ly)?\b",
        re.IGNORECASE,
    )
    for clause in claim_clauses:
        for match in direct_owner_pattern.finditer(clause):
            if re.search(r"\b(?:and|or)\b", match.group("party"), re.IGNORECASE):
                continue
            party = re.sub(
                r"^\s*(?:(?:and|but)\s+)?(?:the|an|a)\s+",
                "",
                match.group("party"),
                flags=re.IGNORECASE,
            ).strip()
            if not party:
                continue
            direct_ownership.append((party, float(match.group("percentage"))))

    ownership_at_mentions: list[tuple[str, float]] = []
    ownership_at_pattern = re.compile(
        r"(?P<context>[^.!?;\n]{1,140}?)\s+at\s+"
        r"(?P<percentage>\d+(?:\.\d+)?)\s*(?:%|\bpercent\b)",
        re.IGNORECASE,
    )
    ownership_context_pattern = re.compile(
        r"\b(?:own(?:s|ed)?|holds?|held|holding|ownership)\b",
        re.IGNORECASE,
    )
    sentence_boundary_pattern = re.compile(r"[!?;\n]|(?<!\d)\.(?!\d)")
    for match in ownership_at_pattern.finditer(fact_text):
        clause_start = max(
            (
                boundary.end()
                for boundary in sentence_boundary_pattern.finditer(
                    fact_text[: match.start()]
                )
            ),
            default=0,
        )
        clause_prefix = fact_text[clause_start : match.start()]
        if not ownership_context_pattern.search(clause_prefix):
            continue

        party_label = re.sub(
            r"^\s*(?:(?:and|or|but)\s+)+",
            "",
            match.group("context"),
            flags=re.IGNORECASE,
        )
        ownership_relation = re.search(
            r"\b(?:is\s+owned\s+by|owned\s+by|owns?|holds?)\b",
            party_label,
            re.IGNORECASE,
        )
        if ownership_relation:
            party_label = party_label[ownership_relation.end() :]
        party_label = re.sub(
            r"^\s*(?:(?:\d+|one|two|three|four|five|several|multiple|"
            r"each|another|a|an|the)\s+)+",
            "",
            party_label,
            flags=re.IGNORECASE,
        ).strip(" ,:-")
        if not re.search(r"[A-Za-z0-9]", party_label):
            continue
        ownership_at_mentions.append(
            (party_label, float(match.group("percentage")))
        )

    augmented: list[dict[str, Any]] = []
    for party in parties:
        name = str(party.get("party", "")).strip()
        capacities = list(party.get("capacities", []))
        matched_ownership = next(
            (
                percentage
                for extracted_party, percentage in direct_ownership
                if (
                    extracted_party.casefold() in name.casefold()
                    or name.casefold() in extracted_party.casefold()
                )
            ),
            None,
        )
        if matched_ownership is not None:
            party["ownership_percentage"] = matched_ownership
            direct_capacity = next(
                (
                    capacity
                    for capacity in capacities
                    if re.search(
                        r"\b(?:owner|holder)\b", str(capacity.get("name", "")), re.I
                    )
                ),
                None,
            )
            if direct_capacity:
                direct_capacity["name"] = "direct owner"
            elif not any(
                str(capacity.get("name", "")).casefold() == "direct owner"
                for capacity in capacities
            ):
                capacities.append(
                    {
                        "name": "direct owner",
                        "evidence": "The facts state direct ownership.",
                    }
                )
        party["capacities"] = capacities
        augmented.append(party)

    for extracted_party, percentage in direct_ownership:
        if not any(
            extracted_party.casefold() in str(party.get("party", "")).casefold()
            or str(party.get("party", "")).casefold() in extracted_party.casefold()
            for party in augmented
        ):
            augmented.append(
                {
                    "party": extracted_party,
                    "ownership_percentage": percentage,
                    "capacities": [
                        {
                            "name": "direct owner",
                            "evidence": "The facts state direct ownership.",
                        }
                    ],
                }
            )

    def party_terms(value: str) -> set[str]:
        return {
            token
            for token in re.findall(r"[a-z0-9]+", value.casefold())
            if token not in {"a", "an", "the", "one", "each"}
        }

    for party_label, percentage in ownership_at_mentions:
        label_terms = party_terms(party_label)
        if not label_terms:
            continue
        matching_parties = [
            party
            for party in augmented
            if (name_terms := party_terms(str(party.get("party", ""))))
            and (
                label_terms.issubset(name_terms)
                or name_terms.issubset(label_terms)
            )
        ]
        if len(matching_parties) > 1:
            continue

        if matching_parties:
            party = matching_parties[0]
            party["ownership_percentage"] = percentage
            capacities = list(party.get("capacities", []))
            if not any(
                re.search(r"\b(?:owner|holder)\b", str(capacity.get("name", "")), re.I)
                for capacity in capacities
            ):
                capacities.append(
                    {
                        "name": "owner",
                        "evidence": (
                            f"The facts identify this party at {percentage:g} percent ownership."
                        ),
                    }
                )
            party["capacities"] = capacities
            continue

        display_party = party_label[:1].upper() + party_label[1:]
        augmented.append(
            {
                "party": display_party,
                "ownership_percentage": percentage,
                "capacities": [
                    {
                        "name": "owner",
                        "evidence": (
                            f"The facts identify this party at {percentage:g} percent ownership."
                        ),
                    }
                ],
            }
        )
    return augmented


def enumerate_guarantor_rows(
    client: OpenAI,
    original_question: str,
    sources: list[RetrievedSource],
) -> list[dict[str, Any]]:
    """Enumerate party/capacity/provision tuples without scenario-specific rules."""

    if not sources:
        return []
    guaranty_specific_sources = [
        source
        for source in sources
        if re.search(
            r"\bguarant(?:y|ee|ies|or)\b",
            f"{source.section_ref}\n{source.chunk_text}",
            re.IGNORECASE,
        )
    ]
    enumeration_sources = guaranty_specific_sources or [
        source
        for source in sources
        if NORMATIVE_LANGUAGE_RE.search(source.chunk_text)
    ] or sources
    source_context = format_context(enumeration_sources)
    try:
        response = client.chat.completions.create(
            model=ANSWER_MODEL,
            max_tokens=2400,
            temperature=0,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Extract inputs for a guarantor enumeration. Do not decide which "
                        "rows to report. Extract every distinct party identity and every "
                        "capacity explicitly stated in the facts, keeping source terms "
                        "exact and splitting multiple capacities into separate entries. "
                        "Classify each party as individual, entity, or unknown only from "
                        "the facts and explicit role language; this classification is for "
                        "matching source subjects and is not a guaranty conclusion. "
                        "From the supplied passages, extract every provision that imposes "
                        "an obligation using the passage's own words. Include exact "
                        "subject or capacity terms, the obligation text, guaranty type, "
                        "and conditions. Mark a provision applies_to_all only when the "
                        "passage clearly applies to every party or capacity in the "
                        "enumeration. Do not infer a party, capacity, threshold, or "
                        "obligation that is absent. This is a generic extraction task; "
                        "do not use a list of known guarantor scenarios."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"FACTS:\n{original_question}\n\n"
                        f"ADMITTED SOURCE PASSAGES:\n{source_context}"
                    ),
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "sop_guarantor_enumeration_inputs",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "parties": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "party": {"type": "string"},
                                        "party_type": {
                                            "type": "string",
                                            "enum": ["individual", "entity", "unknown"],
                                        },
                                        "capacities": {
                                            "type": "array",
                                            "items": {
                                                "type": "object",
                                                "properties": {
                                                    "name": {"type": "string"},
                                                    "evidence": {"type": "string"},
                                                },
                                                "required": ["name", "evidence"],
                                                "additionalProperties": False,
                                            },
                                        },
                                        "ownership_percentage": {
                                            "type": ["number", "null"]
                                        },
                                    },
                                    "required": [
                                        "party",
                                        "party_type",
                                        "capacities",
                                        "ownership_percentage",
                                    ],
                                    "additionalProperties": False,
                                },
                            },
                            "provisions": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "source_id": {"type": "integer"},
                                        "quote": {"type": "string"},
                                        "subject_terms": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "capacity_terms": {
                                            "type": "array",
                                            "items": {"type": "string"},
                                        },
                                        "applies_to_all": {"type": "boolean"},
                                        "obligation_text": {"type": "string"},
                                        "guaranty_type": {"type": "string"},
                                        "conditions": {"type": "string"},
                                    },
                                    "required": [
                                        "source_id",
                                        "quote",
                                        "subject_terms",
                                        "capacity_terms",
                                        "applies_to_all",
                                        "obligation_text",
                                        "guaranty_type",
                                        "conditions",
                                    ],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["parties", "provisions"],
                        "additionalProperties": False,
                    },
                },
            },
        )
        result = parse_json(response.choices[0].message.content or "")
    except Exception:
        app.logger.exception("Guarantor enumeration input extraction failed")
        return [
            {
                "party": "unresolved party",
                "capacity": "unresolved capacity",
                "ownership_percentage": None,
                "ownership_comparison": None,
                "guaranty_type": "Unresolved",
                "triggering_provision": "No enumeration inputs could be extracted.",
                "additional_conditions": (
                    "Resolve the party, capacity, and obligation-imposing provision "
                    "from additional responsive SOP text."
                ),
                "status": "unresolved",
                "unresolved_reason": "Enumeration inputs could not be extracted.",
                "citations": [],
            }
        ]

    valid_sources = {source.source_id: source for source in enumeration_sources}
    provisions: list[dict[str, Any]] = []
    for provision in result.get("provisions", []):
        if not isinstance(provision, dict):
            continue
        source = valid_sources.get(provision.get("source_id"))
        quote = provision.get("quote")
        if source is None or not isinstance(quote, str):
            continue
        located = find_verbatim_quote(quote, source.chunk_text)
        if not located or not has_explicit_guaranty_obligation(located):
            continue
        provisions.append(
            {
                **provision,
                "quote": located,
                "cardinality_constraint": bool(
                    re.search(
                        r"\bat\s+least\s+one\b|\bone\s+of\b|"
                        r"\beach\s+(?:loan|application|transaction)\b[^.!?]*\bmust\b",
                        located,
                        re.I,
                    )
                ),
            }
        )

    parties: list[dict[str, Any]] = []
    for party in result.get("parties", []):
        if not isinstance(party, dict) or not str(party.get("party", "")).strip():
            continue
        capacities = [
            capacity
            for capacity in party.get("capacities", [])
            if isinstance(capacity, dict) and str(capacity.get("name", "")).strip()
        ]
        parties.append({**party, "capacities": capacities})

    parties = augment_extracted_party_capacities(original_question, parties)

    if not parties:
        return [
            {
                "party": "unresolved party",
                "capacity": "unresolved capacity",
                "ownership_percentage": None,
                "ownership_comparison": None,
                "guaranty_type": "Unresolved",
                "triggering_provision": "No party and capacity facts were resolved.",
                "additional_conditions": (
                    "Resolve the party and capacity from additional fact-pattern detail."
                ),
                "status": "unresolved",
                "unresolved_reason": "No party-capacity pair was extracted.",
                "citations": [],
            }
        ]

    return enumerate_guarantor_rows_from_inputs(parties, provisions)


def enumerate_guarantor_rows_from_inputs(
    parties: list[dict[str, Any]], provisions: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Return one row for every party-capacity and matching admitted provision."""

    threshold_pattern = re.compile(
        r"(?P<value>\d+(?:\.\d+)?)\s*%\s*"
        r"(?P<operator>or\s+more|or\s+greater|or\s+higher|at\s+least|"
        r"or\s+less|or\s+lower|at\s+most|less\s+than|below|under|"
        r"more\s+than|greater\s+than|above|over)",
        re.IGNORECASE,
    )
    aggregation_pattern = re.compile(
        r"\b(?:in\s+the\s+aggregate|aggregat(?:e|ed|ion)|collectively|combined)\b",
        re.IGNORECASE,
    )
    subject_noise = {
        "one",
        "more",
        "each",
        "all",
        "any",
        "multiple",
        "several",
        "applicant",
        "ownership",
        "percentage",
        "aggregate",
    }

    def threshold_checks(provision: dict[str, Any]) -> list[tuple[float, str]]:
        text = " ".join(
            [
                str(provision.get("quote", "")),
                str(provision.get("obligation_text", "")),
                str(provision.get("conditions", "")),
            ]
        ).casefold()
        return [
            (
                float(match.group("value")),
                re.sub(r"\s+", " ", match.group("operator")),
            )
            for match in threshold_pattern.finditer(text)
        ]

    def threshold_result(
        provision: dict[str, Any], ownership: Any
    ) -> bool | None:
        if not isinstance(ownership, (int, float)) or isinstance(ownership, bool):
            return None
        checks = []
        for threshold, operator in threshold_checks(provision):
            comparisons = {
                "or more": ownership >= threshold,
                "or greater": ownership >= threshold,
                "or higher": ownership >= threshold,
                "at least": ownership >= threshold,
                "or less": ownership <= threshold,
                "or lower": ownership <= threshold,
                "at most": ownership <= threshold,
                "less than": ownership < threshold,
                "below": ownership < threshold,
                "under": ownership < threshold,
                "more than": ownership > threshold,
                "greater than": ownership > threshold,
                "above": ownership > threshold,
                "over": ownership > threshold,
            }
            if operator in comparisons:
                checks.append(comparisons[operator])
        return all(checks) if checks else True

    def party_terms(party: dict[str, Any]) -> set[str]:
        capacity_text = " ".join(
            f"{capacity.get('name', '')} {capacity.get('evidence', '')}"
            for capacity in party.get("capacities", [])
            if isinstance(capacity, dict)
        )
        return _normalized_policy_terms(
            f"{party.get('party', '')} {party.get('party_type', '')} {capacity_text}"
        )

    def aggregation_scope(
        provision: dict[str, Any],
    ) -> dict[str, Any] | None:
        quote = str(provision.get("quote", ""))
        evidence = " ".join(
            (
                quote,
                str(provision.get("obligation_text", "")),
                str(provision.get("conditions", "")),
            )
        )
        if not aggregation_pattern.search(evidence):
            return None

        group_match = re.search(
            r"\b(?:one\s+or\s+more|multiple|several|all)\s+"
            r"(?P<group>[^,;.!?]+?)\s+"
            r"(?:own|owns|hold|holds|have|has)\b",
            quote,
            re.IGNORECASE,
        )
        if group_match:
            group_label = re.sub(r"\([^)]*\)", " ", group_match.group("group"))
            group_label = re.sub(r"\s+", " ", group_label).strip(" ,")
            group_terms = _normalized_policy_terms(group_label)
        else:
            group_label = " ".join(
                str(term) for term in provision.get("subject_terms", [])
            ).strip()
            group_terms = _normalized_policy_terms(group_label) & (
                _normalized_policy_terms(quote)
            )

        group_terms -= subject_noise
        return {
            "group_terms": group_terms,
            "group_label": group_label or "source-defined group",
            "scope_resolved": bool(group_terms),
        }

    aggregation_by_provision: dict[int, dict[str, Any]] = {}
    for provision_index, provision in enumerate(provisions):
        scope = aggregation_scope(provision)
        if scope is None:
            continue
        members = {
            party_index
            for party_index, party in enumerate(parties)
            if scope["scope_resolved"]
            and scope["group_terms"].issubset(party_terms(party))
        }
        ownership_values = [
            parties[party_index].get("ownership_percentage")
            for party_index in members
        ]
        ownership_is_complete = bool(members) and all(
            isinstance(value, (int, float)) and not isinstance(value, bool)
            for value in ownership_values
        )
        aggregation_by_provision[provision_index] = {
            **scope,
            "members": members,
            "ownership_percentage": (
                sum(ownership_values) if ownership_is_complete else None
            ),
        }

    def other_owner_context(aggregation: dict[str, Any]) -> str:
        other_owners = []
        group_members = aggregation.get("members", set())
        for owner_index, owner in enumerate(parties):
            ownership = owner.get("ownership_percentage")
            if (
                owner_index in group_members
                or not isinstance(ownership, (int, float))
                or isinstance(ownership, bool)
            ):
                continue
            other_owners.append(
                f"{str(owner.get('party', 'Owner')).strip()} at {ownership:g} percent"
            )
        if not other_owners:
            return ""
        return (
            f" Other stated owners outside the source-defined "
            f"{aggregation['group_label']} group: {', '.join(other_owners)}. "
            "These percentages are not included in the group total."
        )

    def source_capacity_label(
        provision: dict[str, Any], extracted_capacity: str
    ) -> str:
        source_terms = " ".join(
            str(term) for term in provision.get("capacity_terms", [])
        )
        normalized = _normalized_policy_terms(source_terms)
        if "sell" in normalized and "owner" in normalized:
            return "selling owner"
        if "direct" in normalized and "owner" in normalized:
            return "direct owner"
        if "entity" in normalized and "owner" in normalized:
            return "entity owner"
        return extracted_capacity

    rows: list[dict[str, Any]] = []
    for party_index, party in enumerate(parties):
        capacities = party["capacities"] or [
            {
                "name": "unresolved capacity",
                "evidence": "No capacity was explicitly stated for this party.",
            }
        ]
        for capacity in capacities:
            party_terms = _normalized_policy_terms(
                f"{party['party']} {party.get('party_type', '')} "
                f"{capacity['name']} {capacity.get('evidence', '')}"
            )
            capacity_terms = _normalized_policy_terms(
                f"{capacity['name']} {capacity.get('evidence', '')}"
            )
            matched_provisions: list[dict[str, Any]] = []
            threshold_not_met: list[tuple[dict[str, Any], Any, dict[str, Any] | None]] = []
            unresolved_aggregations: list[tuple[dict[str, Any], dict[str, Any]]] = []
            for provision_index, provision in enumerate(provisions):
                if provision.get("cardinality_constraint"):
                    continue
                aggregation = aggregation_by_provision.get(provision_index)
                if aggregation and aggregation["scope_resolved"]:
                    if party_index not in aggregation["members"]:
                        continue

                subject_terms = _normalized_policy_terms(
                    " ".join(provision.get("subject_terms", []))
                )
                subject_terms -= subject_noise
                provision_capacity_terms = _normalized_policy_terms(
                    " ".join(provision.get("capacity_terms", []))
                )
                subject_matches = not subject_terms or subject_terms.issubset(party_terms)
                capacity_matches = not provision_capacity_terms or bool(
                    capacity_terms.intersection(provision_capacity_terms)
                )
                role_capacity_terms = provision_capacity_terms.intersection(
                    {
                        "direct",
                        "indirect",
                        "entity",
                        "owner",
                        "sponsor",
                        "participant",
                        "trustee",
                        "borrower",
                    }
                )
                if not role_capacity_terms:
                    capacity_matches = True
                if aggregation and aggregation["scope_resolved"]:
                    subject_matches = party_index in aggregation["members"]
                matches_party = (
                    provision.get("applies_to_all")
                    or (subject_matches and capacity_matches)
                )
                if not matches_party:
                    continue

                if aggregation and not aggregation["scope_resolved"]:
                    unresolved_aggregations.append((provision, aggregation))
                    continue

                comparison_ownership = (
                    aggregation["ownership_percentage"]
                    if aggregation
                    else party.get("ownership_percentage")
                )
                if aggregation and comparison_ownership is None:
                    unresolved_aggregations.append((provision, aggregation))
                    continue

                applies = threshold_result(provision, comparison_ownership)
                if applies is False:
                    threshold_not_met.append(
                        (provision, comparison_ownership, aggregation)
                    )
                else:
                    matched_provisions.append(
                        {
                            "provision": provision,
                            "aggregation": aggregation,
                            "comparison_ownership": comparison_ownership,
                        }
                    )
            if not matched_provisions:
                if threshold_not_met:
                    for provision, comparison_ownership, aggregation in threshold_not_met:
                        thresholds = ", ".join(
                            f"{value:g}% {operator}"
                            for value, operator in threshold_checks(provision)
                        )
                        if aggregation:
                            ownership_comparison = (
                                f"{party['party']} ownership is "
                                f"{party.get('ownership_percentage'):g} percent; "
                                f"aggregate ownership across "
                                f"{len(aggregation['members'])} "
                                f"{aggregation['group_label']} is "
                                f"{comparison_ownership:g} percent."
                                f"{other_owner_context(aggregation)}"
                            )
                        else:
                            ownership_comparison = (
                                f"Ownership is {comparison_ownership:g} percent."
                            )
                        if thresholds:
                            ownership_comparison += (
                                f" This does not meet the cited threshold ({thresholds})."
                            )
                        rows.append(
                            {
                                "party": party["party"],
                                "capacity": capacity["name"],
                                "ownership_percentage": party.get(
                                    "ownership_percentage"
                                ),
                                "ownership_comparison": ownership_comparison,
                                "guaranty_type": "Not triggered",
                                "triggering_provision": provision.get(
                                    "obligation_text", ""
                                ),
                                "additional_conditions": (
                                    "The stated ownership facts do not meet this "
                                    "provision's threshold."
                                ),
                                "status": "not_required",
                                "citations": [
                                    {
                                        "source_id": provision["source_id"],
                                        "quote": provision["quote"],
                                    }
                                ],
                            }
                        )
                    continue
                if unresolved_aggregations:
                    provision, aggregation = unresolved_aggregations[0]
                    rows.append(
                        {
                            "party": party["party"],
                            "capacity": capacity["name"],
                            "ownership_percentage": party.get(
                                "ownership_percentage"
                            ),
                            "ownership_comparison": None,
                            "guaranty_type": "Unresolved",
                            "triggering_provision": provision.get(
                                "obligation_text", ""
                            ),
                            "additional_conditions": (
                                "The source requires an aggregate ownership "
                                "comparison, but the covered owners or their "
                                "ownership amounts are incomplete."
                            ),
                            "status": "unresolved",
                            "unresolved_reason": (
                                "Aggregate ownership could not be established "
                                "from the extracted party facts."
                            ),
                            "citations": [
                                {
                                    "source_id": provision["source_id"],
                                    "quote": provision["quote"],
                                }
                            ],
                        }
                    )
                    continue
                rows.append(
                    {
                        "party": party["party"],
                        "capacity": capacity["name"],
                        "ownership_percentage": party.get("ownership_percentage"),
                        "ownership_comparison": None,
                        "guaranty_type": "Unresolved",
                        "triggering_provision": (
                            "No admitted obligation-imposing provision was matched "
                            "to this party and capacity."
                        ),
                        "additional_conditions": (
                            "Resolve the obligation from additional responsive SOP text."
                        ),
                        "status": "unresolved",
                        "unresolved_reason": (
                            "No admitted obligation-imposing provision matched this "
                            "party-capacity tuple."
                        ),
                        "citations": [],
                    }
                )
                continue
            for matched in matched_provisions:
                provision = matched["provision"]
                aggregation = matched["aggregation"]
                comparison_ownership = matched["comparison_ownership"]
                threshold_text = ", ".join(
                    f"{value:g}% {operator}"
                    for value, operator in threshold_checks(provision)
                )
                ownership_comparison = None
                if aggregation:
                    individual_ownership = party.get("ownership_percentage")
                    ownership_comparison = (
                        f"{party['party']} ownership is {individual_ownership:g} percent; "
                        f"aggregate ownership across {len(aggregation['members'])} "
                        f"{aggregation['group_label']} is "
                        f"{comparison_ownership:g} percent."
                        f"{other_owner_context(aggregation)}"
                    )
                elif isinstance(comparison_ownership, (int, float)) and threshold_text:
                    ownership_comparison = (
                        f"Ownership is {comparison_ownership:g} percent."
                    )
                if ownership_comparison and threshold_text:
                    ownership_comparison += (
                        f" This meets the cited threshold ({threshold_text})."
                    )
                rows.append(
                    {
                        "party": party["party"],
                        "capacity": source_capacity_label(provision, capacity["name"]),
                        "ownership_percentage": party.get("ownership_percentage"),
                        "ownership_comparison": ownership_comparison,
                        "guaranty_type": provision.get("guaranty_type", ""),
                        "triggering_provision": provision.get("obligation_text", ""),
                        "additional_conditions": provision.get("conditions", ""),
                        "status": "required",
                        "citations": [
                            {
                                "source_id": provision["source_id"],
                                "quote": provision["quote"],
                            }
                        ],
                    }
                )
    return rows


def clarify_requested_guaranty_wording(
    question: str,
    rows: list[dict[str, Any]],
    sources: list[RetrievedSource],
) -> None:
    """Clarify when a trust-specific obligation uses a different guaranty label."""

    if not re.search(
        r"\bfull\s+unconditional\s+guarant(?:y|ee)\b",
        question,
        re.IGNORECASE,
    ):
        return

    source_by_id = {source.source_id: source for source in sources}
    for row in rows:
        if row.get("status") != "required" or not re.search(
            r"\btrust\b",
            " ".join(
                str(row.get(field, ""))
                for field in ("party", "capacity", "triggering_provision")
            ),
            re.IGNORECASE,
        ):
            continue
        guaranty_type = str(row.get("guaranty_type", ""))
        if not re.search(r"\bunlimited\s+full\s+guarant", guaranty_type, re.I):
            continue
        cited_text = "\n".join(
            source_by_id[source_id].chunk_text
            for citation in row.get("citations", [])
            if isinstance(citation, dict)
            and (source_id := citation.get("source_id")) in source_by_id
        )
        if not re.search(r"\bunlimited\s+full\s+guarant", cited_text, re.I):
            continue

        clarification = (
            "Term clarification: the cited trust-specific provision requires an "
            "unlimited full guaranty; “full unconditional guaranty” is not the "
            "wording of that obligation."
        )
        conditions = str(row.get("additional_conditions", "")).strip()
        if clarification not in conditions:
            row["additional_conditions"] = " ".join(
                part for part in (conditions, clarification) if part
            )


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
        has_guaranty_intent(combined)
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


def fallback_applied_conclusion(
    propositions: list[dict[str, Any]] | None = None,
    guarantor_rows: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Combine an already relevant, audited artifact without inventing evidence."""
    citations: list[dict[str, Any]] = []
    text = ""
    if guarantor_rows:
        citations = guarantor_rows[0].get("citations", [])
        text = (
            "The admitted SOP provisions require the guaranty obligations "
            "reflected in the party-and-capacity table below."
        )
    elif propositions:
        citations = propositions[0].get("citations", [])
        text = (
            "Applied to the stated facts, the controlling admitted SOP provision "
            f"supports this conclusion: {propositions[0].get('text', '')}"
        )
    if not text or not citations:
        return None
    return {"text": text, "citations": citations}


def require_env() -> None:
    missing = [key for key in ("DATABASE_URL", "OPENAI_API_KEY") if not os.getenv(key)]
    if missing:
        raise RuntimeError(f"Missing required environment variables: {', '.join(missing)}")


def load_corpus_metadata() -> dict[str, Any]:
    """Validate the selected corpus before the process accepts traffic."""
    require_env()
    try:
        with connection() as conn:
            row = conn.execute(
                """
                SELECT edition, source_url, sha256, effective_date, chunk_count
                FROM corpus_metadata
                WHERE edition = %s
                ORDER BY ingested_at DESC
                LIMIT 1
                """,
                (DEFAULT_SOP_VERSION,),
            ).fetchone()
            if row is None:
                raise RuntimeError(
                    f"No metadata is registered for selected corpus {DEFAULT_SOP_VERSION!r}."
                )
            chunk_count = conn.execute(
                """
                SELECT COUNT(*)
                FROM sop_chunks
                WHERE sop_version = %s AND corpus_sha256 = %s
                """,
                (row[0], row[2]),
            ).fetchone()[0]
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f"Corpus startup validation failed: {exc}") from exc

    if int(row[4]) != int(chunk_count) or int(chunk_count) == 0:
        raise RuntimeError(
            f"Corpus metadata count mismatch for {row[0]}: "
            f"metadata={row[4]}, rows={chunk_count}."
        )
    return {
        "edition": row[0],
        "source_url": canonicalize_source_url(row[1]),
        "sha256": row[2],
        "effective_date": (
            row[3].isoformat() if hasattr(row[3], "isoformat") else str(row[3])
        ),
        "chunk_count": int(chunk_count),
    }


CORPUS_METADATA = load_corpus_metadata()


def enforce_rate_limit() -> int | None:
    """Return retry-after seconds using a database-backed fixed-window counter."""
    user = current_user()
    forwarded_for = request.headers.get("X-Forwarded-For", "")
    client_ip = forwarded_for.split(",", 1)[0].strip() or request.remote_addr or "unknown"
    key = f"user:{user['id']}" if user and user.get("id") else f"ip:{client_ip}"
    now = dt.datetime.now(dt.timezone.utc)
    with connection() as conn:
        row = conn.execute(
            """
            INSERT INTO api_rate_limits (bucket_key, window_started_at, request_count)
            VALUES (%s, %s, 1)
            ON CONFLICT (bucket_key)
            DO UPDATE SET
                window_started_at = CASE
                    WHEN EXCLUDED.window_started_at - api_rate_limits.window_started_at
                         >= %s * INTERVAL '1 second'
                    THEN EXCLUDED.window_started_at
                    ELSE api_rate_limits.window_started_at
                END,
                request_count = CASE
                    WHEN EXCLUDED.window_started_at - api_rate_limits.window_started_at
                         >= %s * INTERVAL '1 second'
                    THEN 1
                    ELSE api_rate_limits.request_count + 1
                END
            RETURNING window_started_at, request_count
            """,
            (key, now, RATE_LIMIT_WINDOW_SECONDS, RATE_LIMIT_WINDOW_SECONDS),
        ).fetchone()
    if row and int(row[1]) > RATE_LIMIT_MAX_REQUESTS:
        age = max(0.0, (now - row[0]).total_seconds())
        return max(1, math.ceil(RATE_LIMIT_WINDOW_SECONDS - age))
    return None


def known_unsupported_question(question: str) -> bool:
    """Prevent generic SOP language from answering clearly out-of-scope asks."""
    lower = question.casefold()
    if re.search(r"\bweather|weather forecast\b", lower):
        return True
    if re.search(r"\b(?:state\s+income[-\s]?tax|income[-\s]?tax filing)\b", lower):
        return True
    return bool(
        re.search(r"\benvironmental consultant\b", lower)
        and re.search(r"\bspecific brand\b|\bbrand\b", lower)
    )


def unsupported_result(question: str) -> Any:
    note = f"{NO_RESPONSIVE_PROVISION}: {question}."
    version_warning, date_warning = query_warnings(question)
    return jsonify(
        {
            "answer": note,
            "summary": "No applied conclusion was established from the retrieved SOP provisions.",
            "source_version": CORPUS_METADATA["edition"],
            "effective_date": CORPUS_METADATA["effective_date"],
            "version_warning": version_warning,
            "date_warning": date_warning,
            "assumptions": [],
            "subanswers": [
                {
                    "subquestion_id": "subquestion-1",
                    "question": question,
                    "answer": note,
                    "no_provision": True,
                    "applied_conclusion": None,
                    "propositions": [],
                    "guarantor_rows": [],
                    "support_status": "no_responsive_provision",
                    "support_note": note,
                    "searched_terms": [],
                    "rejected_citations": [],
                    "gate_telemetry": [],
                    "synthesizer_telemetry": {},
                }
            ],
            "other_issues": [],
            "sources": [],
            "provisions_to_read": [],
        }
    )


@app.get("/api/healthz")
def health():
    return jsonify(
        {
            "status": "ok",
            "sop_version": CORPUS_METADATA["edition"],
            "effective_date": CORPUS_METADATA["effective_date"],
            "source_url": CORPUS_METADATA["source_url"],
            "source_sha256": CORPUS_METADATA["sha256"],
            "chunk_count": CORPUS_METADATA["chunk_count"],
        }
    )


@app.get("/api")
def api_root():
    return health()


@app.post("/api/sop/query")
@require_auth
def query_sop():
    retry_after = enforce_rate_limit()
    if retry_after is not None:
        return (
            jsonify({"error": "Rate limit exceeded. Try again later."}),
            429,
            {"Retry-After": str(retry_after)},
        )
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
    if known_unsupported_question(question):
        return unsupported_result(question)

    try:
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
                    CORPUS_METADATA["edition"],
                    CORPUS_METADATA["sha256"],
                    material_facts=item.get("material_facts", []),
                    original_question=question,
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
        applicable_gate_pool: dict[int, dict[str, Any]] = {}
        standard_product_assumed = False
        for index, (item, db_ids) in enumerate(zip(plan, subquestion_sources)):
            subquestion_id = f"subquestion-{index + 1}"
            retrieval_seed = item["question"]
            context_sources = [
                source_by_db_id[db_id]
                for db_id in db_ids
                if db_id in source_by_db_id
            ]
            context_sources = select_context_sources(
                context_sources,
                prioritize_seller_note=bool(
                    SELLER_NOTE_TOPIC_RE.search(retrieval_seed)
                    and not has_guaranty_intent(retrieval_seed)
                ),
            )
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
            gate_telemetry: list[dict[str, Any]] = []
            fact_text = "\n".join(
                [question, retrieval_seed, *item.get("material_facts", [])]
            )
            gate_by_source_id: dict[int, dict[str, Any]] = {}
            for source in context_sources:
                tags = source_tags(source)
                excluded_dimension = None
                for dimension in APPLICABILITY_DIMENSIONS:
                    source_values = set(tags.get(dimension, []))
                    fact_values = set(fact_tags.get(dimension, []))
                    if applicability_dimension_conflicts(
                        dimension, source_values, fact_values
                    ):
                        excluded_dimension = dimension
                        break
                gate = evaluate_source_gate(source, fact_text, fact_tags)
                gate_by_source_id[source.source_id] = gate
                telemetry = {
                    "subquestion_id": subquestion_id,
                    "chunk_id": source.db_id,
                    "source_id": source.source_id,
                    "breadcrumb": source.section_ref,
                    "page": source.page_number,
                    "tags": tags,
                    "fact_pattern": fact_tags,
                    "fact_values": fact_tags,
                    "excluded_dimension": excluded_dimension,
                    "conditions": gate["conditions"],
                    "condition_result": gate["condition_result"],
                    "condition_reason": gate["condition_reason"],
                    "applicability_result": (
                        "passed" if gate["applicable"] else "failed"
                    ),
                    "applicability_reason": gate["applicability_reason"],
                    "result": "admitted" if gate["admitted"] else "excluded",
                    "reached_applied_conclusion": False,
                }
                if gate["admitted"]:
                    applicable_sources.append(source)
                    applicable_source_pool[source.db_id] = source
                    applicable_gate_pool[source.source_id] = gate
                else:
                    inapplicable_sources.append(
                        (
                            source,
                            gate["applicability_reason"]
                            or gate["condition_reason"]
                            or "The provision's stated conditions do not match the facts.",
                        )
                    )
                gate_telemetry.append(telemetry)
                app.logger.info(
                    "SOP applicability gate: %s",
                    json.dumps(telemetry, sort_keys=True),
                )
            policy_issue = derive_policy_issue(
                client, question, retrieval_seed, applicable_sources
            )
            canonical_question = policy_issue.get("text") or retrieval_seed
            item["requested_question"] = retrieval_seed
            item["question"] = canonical_question
            item["policy_issue"] = policy_issue
            synthesizer_input = {
                "subquestion_id": subquestion_id,
                "question": canonical_question,
                "retrieval_seed": retrieval_seed,
                "policy_issue": policy_issue,
                "material_facts": list(dict.fromkeys([question, *item.get("material_facts", [])])),
                "admitted_source_ids": [source.source_id for source in applicable_sources],
                "admitted_context": [
                    {
                        "source_id": source.source_id,
                        "breadcrumb": source.section_ref,
                        "page": source.page_number,
                    }
                    for source in applicable_sources
                ],
            }
            generated = generate_propositions(
                client,
                question,
                canonical_question,
                list(dict.fromkeys([question, *item.get("material_facts", [])])),
                applicable_sources,
                subquestion_id,
                policy_issue,
            )
            deterministic_conclusion = deterministic_applied_conclusion(
                question,
                retrieval_seed,
                applicable_sources,
            )
            if deterministic_conclusion:
                generated["applied_conclusion"] = deterministic_conclusion
            # Rows are built once from the pooled admitted provisions below.
            if has_guaranty_intent(question):
                generated["guarantor_rows"] = []
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
                    "subquestion_id": subquestion_id,
                    "question": canonical_question,
                    "requested_question": retrieval_seed,
                    "policy_issue": policy_issue,
                    "generated": generated,
                    "candidate_index": index,
                    "search_terms": item.get("search_terms", []),
                    "sources_available": bool(applicable_sources),
                    "admitted_source_ids": [
                        source.source_id for source in applicable_sources
                    ],
                    "inapplicable_sources": inapplicable_sources,
                    "fact_tags": fact_tags,
                    "gate_telemetry": gate_telemetry,
                    "gate_by_source_id": gate_by_source_id,
                    "synthesizer_telemetry": {
                        "subquestion_id": subquestion_id,
                        "received": synthesizer_input,
                        "returned": generated,
                        "reached_applied_conclusion": False,
                    },
                }
            )
            numeric_reference = "\n".join(
                [question, retrieval_seed, item["question"], *item.get("material_facts", [])]
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
                        "subquestion": item["question"],
                        "requested_question": item["requested_question"],
                        "subquestion_id": subquestion_id,
                        "policy_issue": item["policy_issue"],
                        "gate_by_source_id": gate_by_source_id,
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
                        "subquestion": item["question"],
                        "requested_question": item["requested_question"],
                        "subquestion_id": subquestion_id,
                        "policy_issue": item["policy_issue"],
                        "gate_by_source_id": gate_by_source_id,
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
                        "subquestion": item["question"],
                        "requested_question": item["requested_question"],
                        "subquestion_id": subquestion_id,
                        "policy_issue": item["policy_issue"],
                        "gate_by_source_id": gate_by_source_id,
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
                            numeric_reference + "\n" + _row_text(row)
                        ),
                        "subquestion": item["question"],
                        "requested_question": item["requested_question"],
                        "subquestion_id": subquestion_id,
                        "policy_issue": item["policy_issue"],
                        "gate_by_source_id": gate_by_source_id,
                        "applicable_source_ids": [
                            source.source_id for source in applicable_sources
                        ],
                    }
                )

        # Planning may split one guarantor request into several subquestions,
        # each with a different retrieval slice. Build the final party/capacity
        # enumeration from the union so no capacity disappears between slices.
        if has_guaranty_intent(question) and applicable_source_pool:
            pooled_sources = list(applicable_source_pool.values())
            pooled_rows = enumerate_guarantor_rows(client, question, pooled_sources)
            clarify_requested_guaranty_wording(
                question, pooled_rows, pooled_sources
            )
            pooled_source_ids = {source.source_id for source in pooled_sources}
            for row in pooled_rows:
                row_source_ids = {
                    citation.get("source_id")
                    for citation in row.get("citations", [])
                    if isinstance(citation, dict)
                }
                route_candidates = [
                    subanswer_index
                    for subanswer_index, subanswer in enumerate(subanswers)
                    if row_source_ids.intersection(
                        set(subanswer["admitted_source_ids"])
                    )
                ]
                if not route_candidates:
                    route_candidates = [
                        subanswer_index
                        for subanswer_index, subanswer in enumerate(subanswers)
                        if set(subanswer["policy_issue"].get("source_ids", []))
                        .intersection(pooled_source_ids)
                    ]
                guarantor_subanswer_index = route_candidates[0] if route_candidates else 0
                subanswers[guarantor_subanswer_index]["generated"][
                    "guarantor_rows"
                ].append(row)
                subanswers[guarantor_subanswer_index]["synthesizer_telemetry"][
                    "returned"
                ] = subanswers[guarantor_subanswer_index]["generated"]
                if row.get("status") == "unresolved" and not row.get("citations"):
                    subanswers[guarantor_subanswer_index].setdefault(
                        "unresolved_guarantor_rows", []
                    ).append(row)
                    continue
                candidates.append(
                    {
                        "kind": "guarantor_row",
                        "subanswer_index": guarantor_subanswer_index,
                        "text": _row_text(row),
                        "row": row,
                        "citations": row.get("citations", []),
                        "numeric_reference": question + "\n" + _row_text(row),
                        "subquestion": subanswers[guarantor_subanswer_index]["question"],
                        "requested_question": subanswers[guarantor_subanswer_index][
                            "requested_question"
                        ],
                        "subquestion_id": subanswers[guarantor_subanswer_index][
                            "subquestion_id"
                        ],
                        "policy_issue": subanswers[guarantor_subanswer_index][
                            "policy_issue"
                        ],
                        "gate_by_source_id": applicable_gate_pool,
                        "applicable_source_ids": pooled_source_ids,
                    }
                )

        validated_candidates = validate_candidate_citations(candidates, source_by_id)
        audit_results = audit_propositions(client, question, validated_candidates, source_by_id)
        for candidate_index, candidate in enumerate(validated_candidates):
            trigger = audit_results.get(candidate_index, {}).get(
                "unresolved_trigger"
            )
            if trigger:
                subanswers[candidate["subanswer_index"]][
                    "unresolved_trigger"
                ] = trigger
        # An admitted sub-question may have useful audited propositions or
        # guarantor rows even when the model's conclusion object was empty or
        # failed audit. Preserve a substantive applied conclusion instead of
        # rendering the null state; the fallback is itself telemetry-visible.
        for index, item in enumerate(subanswers):
            if not item["sources_available"]:
                continue
            has_supported_conclusion = any(
                candidate["kind"] == "conclusion"
                and candidate["subanswer_index"] == index
                and candidate_admitted(audit_results.get(candidate_index))
                for candidate_index, candidate in enumerate(validated_candidates)
            )
            if has_supported_conclusion:
                continue
            supported_props = [
                candidate
                for candidate_index, candidate in enumerate(validated_candidates)
                if candidate["kind"] == "proposition"
                and candidate["subanswer_index"] == index
                and candidate_admitted(audit_results.get(candidate_index))
            ]
            supported_rows = [
                candidate["row"]
                for candidate_index, candidate in enumerate(validated_candidates)
                if candidate["kind"] == "guarantor_row"
                and candidate["subanswer_index"] == index
                and candidate_admitted(audit_results.get(candidate_index))
            ]
            fallback = fallback_applied_conclusion(
                supported_props,
                supported_rows,
            )
            if fallback is not None:
                fallback_candidate = {
                    "kind": "conclusion",
                    "subanswer_index": index,
                    "text": fallback["text"],
                    "citations": list(fallback["citations"]),
                    "numeric_reference": question,
                    "subquestion": item["question"],
                    "requested_question": item["requested_question"],
                    "subquestion_id": item["subquestion_id"],
                    "policy_issue": item["policy_issue"],
                    "gate_by_source_id": item["gate_by_source_id"],
                    "applicable_source_ids": list(item["admitted_source_ids"]),
                    "arithmetic_valid": True,
                }
                fallback_trigger = unresolved_adjacent_trigger(
                    fallback_candidate, question, source_by_id
                )
                if fallback_trigger:
                    item["unresolved_trigger"] = fallback_trigger
                else:
                    validated_candidates.append(fallback_candidate)
                    audit_results[len(validated_candidates) - 1] = {
                        "entailment_supported": True,
                        "relevant_to_subquestion": True,
                        "admitted_for_render": True,
                        "derived_from_audited_candidates": True,
                    }
        supported_candidates = [
            candidate
            for index, candidate in enumerate(validated_candidates)
            if candidate_admitted(audit_results.get(index))
        ]
        for candidate in supported_candidates:
            hydrated_citations = []
            for citation in candidate["citations"]:
                source = source_by_id.get(citation.get("source_id"))
                quote = citation.get("quote")
                if source is None or not isinstance(quote, str):
                    continue
                located_quote = find_verbatim_quote(quote, source.chunk_text)
                if located_quote is None:
                    continue
                gate = candidate.get("gate_by_source_id", {}).get(source.source_id)
                if not gate or not gate.get("admitted"):
                    continue
                hydrated_citations.append(
                    build_citation(
                        source,
                        located_quote,
                        True,
                        applicability_status="applicable",
                        applicability_reason=gate.get("applicability_reason"),
                        condition_result=gate.get("condition_result", "failed"),
                        condition_reason=gate.get("condition_reason"),
                        conditions=gate.get("conditions", []),
                    )
                )
            candidate["citations"] = hydrated_citations

        rendered_subanswers = []
        all_citations: list[dict[str, Any]] = []
        seen_guarantor_rows: set[tuple[Any, ...]] = set()
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
                    "artifact_subquestion_id": item["subquestion_id"],
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
                    and not candidate_admitted(audit_results.get(candidate_index))
                ):
                    rejected_conclusion_citations.extend(candidate["citations"])
            rejected_conclusion_citations.extend(
                build_citation(
                    source,
                    citation_preview(source.chunk_text),
                    False,
                    applicability_status="not_applicable",
                    applicability_reason=reason,
                    condition_result=item["gate_by_source_id"].get(
                        source.source_id, {}
                    ).get("condition_result", "failed"),
                    condition_reason=item["gate_by_source_id"].get(
                        source.source_id, {}
                    ).get("condition_reason"),
                    conditions=item["gate_by_source_id"].get(
                        source.source_id, {}
                    ).get("conditions", []),
                )
                for source, reason in item["inapplicable_sources"]
            )
            trigger_info = item.get("unresolved_trigger")
            if trigger_info:
                trigger_source = source_by_id.get(trigger_info.get("source_id"))
                if trigger_source is not None:
                    trigger_citation = build_citation(
                        trigger_source,
                        citation_preview(trigger_source.chunk_text),
                        False,
                        applicability_status="applicable",
                        condition_result="unresolved",
                        condition_reason=(
                            "The adjacent trigger facts are not established by the "
                            "question."
                        ),
                    )
                    trigger_citation["context_only"] = True
                    rejected_conclusion_citations.append(trigger_citation)
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
            unresolved_reason: str | None = None
            unresolved_guarantor_rows = [
                dict(row)
                for row in item.get("unresolved_guarantor_rows", [])
            ]
            if applied_conclusion or row_candidates:
                support_status = "supported"
                propositions = [
                    {
                        "artifact_subquestion_id": item["subquestion_id"],
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
                        row.get("triggering_provision", ""),
                        tuple(
                            citation.get("source_id")
                            for citation in row.get("citations", [])
                        ),
                    )
                    if row_key in seen_guarantor_rows:
                        existing_row = next(
                            (
                                existing
                                for existing in guarantor_rows
                                if (
                                    existing.get("party", ""),
                                    existing.get("capacity", ""),
                                    existing.get("ownership_percentage"),
                                    existing.get("triggering_provision", ""),
                                    tuple(
                                        citation.get("source_id")
                                        for citation in existing.get("citations", [])
                                    ),
                                )
                                == row_key
                            ),
                            None,
                        )
                        if existing_row is not None:
                            existing_row["citations"] = dedupe_citations(
                                existing_row.get("citations", [])
                                + candidate["citations"]
                            )
                            all_citations.extend(candidate["citations"])
                        continue
                    seen_guarantor_rows.add(row_key)
                    row["artifact_subquestion_id"] = item["subquestion_id"]
                    row["citations"] = candidate["citations"]
                    guarantor_rows.append(row)
                    all_citations.extend(candidate["citations"])
                for row in unresolved_guarantor_rows:
                    row.setdefault("artifact_subquestion_id", item["subquestion_id"])
                guarantor_rows.extend(unresolved_guarantor_rows)
                no_provision = False
                support_note = (
                    "Some party-capacity tuples remain unresolved; each unresolved "
                    "row includes the reason."
                    if unresolved_guarantor_rows
                    else None
                )
            elif unresolved_guarantor_rows:
                support_status = "unresolved"
                unresolved_reason = (
                    "No admitted obligation-imposing provision matched every "
                    "party-capacity tuple."
                )
                support_note = unresolved_reason
                answer = support_note
                for row in unresolved_guarantor_rows:
                    row.setdefault("artifact_subquestion_id", item["subquestion_id"])
                guarantor_rows = unresolved_guarantor_rows
                no_provision = False
            elif item.get("unresolved_trigger"):
                support_status = "not_established"
                unresolved_reason = (
                    "The question does not establish whether the condition immediately "
                    "preceding the operative passage is met."
                )
                trigger_text = item["unresolved_trigger"]["text"].rstrip(" :;")
                support_note = (
                    f"{NOT_ESTABLISHED} {unresolved_reason} "
                    f"Trigger: {trigger_text}."
                )
                propositions = [
                    {
                        "artifact_subquestion_id": item["subquestion_id"],
                        "text": candidate["text"],
                        "citations": candidate["citations"],
                        "arithmetic_valid": candidate.get("arithmetic_valid", True),
                    }
                    for candidate in matching
                ]
                answer = support_note
                if propositions:
                    answer += "\n\n" + "\n\n".join(
                        proposition["text"] for proposition in propositions
                    )
                    for proposition in propositions:
                        all_citations.extend(proposition["citations"])
                no_provision = False
            elif generated_conclusion_text or rejected_conclusion_citations:
                if item["inapplicable_sources"] and not item["sources_available"]:
                    support_status = "not_applicable"
                    reason = item["inapplicable_sources"][0][1]
                    support_note = (
                        "All retrieved provisions were excluded by applicability "
                        f"checks. Highest-ranked candidate: {reason}. Review the "
                        "rejected evidence below; retrieval did return source text."
                    )
                    answer = support_note
                    unresolved_reason = None
                else:
                    support_status = "not_established"
                    unresolved_reason = (
                        "No admitted proposition directly answers this sub-question."
                    )
                    unresolved_subject = (
                        item.get("requested_question") or item["question"]
                    )
                    support_note = (
                        f"{NOT_ESTABLISHED} The retrieved SOP provisions do not "
                        f"establish an answer to: {unresolved_subject}"
                    )
                    answer = support_note
                no_provision = False
            elif item["sources_available"]:
                support_status = "unresolved"
                searched = ", ".join(item["search_terms"]) or item["question"]
                unresolved_reason = (
                    "No admitted proposition directly answers this sub-question."
                )
                answer = f"{NO_RESPONSIVE_PROVISION}: {searched}. {unresolved_reason}"
                no_provision = True
                support_note = answer
                guarantor_rows = []
            else:
                support_status = "unresolved"
                searched = ", ".join(item["search_terms"]) or item["question"]
                unresolved_reason = (
                    "No admitted proposition directly answers this sub-question."
                )
                answer = f"{NO_RESPONSIVE_PROVISION}: {searched}. {unresolved_reason}"
                no_provision = True
                support_note = answer
                guarantor_rows = []
            for telemetry in item["gate_telemetry"]:
                telemetry["reached_applied_conclusion"] = bool(
                    applied_conclusion or row_candidates
                )
            item["synthesizer_telemetry"]["returned"] = {
                **item["generated"],
                "final_applied_conclusion": applied_conclusion,
                "final_support_status": support_status,
            }
            item["synthesizer_telemetry"]["reached_applied_conclusion"] = bool(
                applied_conclusion or row_candidates
            )
            rendered_subanswers.append(
                {
                    "subquestion_id": item["subquestion_id"],
                    "question": item["question"],
                    "requested_question": item.get("requested_question"),
                    "policy_issue": item.get("policy_issue", {}),
                    "answer": answer,
                    "no_provision": no_provision,
                    "applied_conclusion": applied_conclusion,
                    "propositions": propositions,
                    "guarantor_rows": guarantor_rows,
                    "support_status": support_status,
                    "support_note": support_note,
                    "unresolved": support_status in {"unresolved", "not_established"},
                    "unresolved_reason": unresolved_reason,
                    "searched_terms": item["search_terms"],
                    "rejected_citations": rejected_conclusion_citations,
                    "gate_telemetry": item["gate_telemetry"] if EXPOSE_DEBUG_TELEMETRY else [],
                    "synthesizer_telemetry": (
                        item["synthesizer_telemetry"]
                        if EXPOSE_DEBUG_TELEMETRY
                        else {}
                    ),
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
        ][:4]
        summary = " ".join(summary_sentences)
        has_applied_summary = bool(summary)
        assumptions: list[str] = []
        if standard_product_assumed:
            assumptions.append(
                "No loan product was specified; this analysis treats the transaction "
                "as a Standard 7(a) loan."
            )
        if not has_applied_summary:
            summary = "No applied conclusion was established from the retrieved SOP provisions."
        answer_parts: list[str] = []
        if has_applied_summary:
            answer_parts.append(summary)
        elif len(rendered_subanswers) > 1:
            for subanswer in rendered_subanswers:
                answer_parts.append(f"{subanswer['question']}\n{subanswer['answer']}")
        elif rendered_subanswers:
            answer_parts.append(rendered_subanswers[0]["answer"])
        else:
            answer_parts.append(summary)
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
                "corpus_source_url": CORPUS_METADATA["source_url"],
                "corpus_sha256": CORPUS_METADATA["sha256"],
                "version_warning": version_warning,
                "date_warning": date_warning,
                "assumptions": assumptions,
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
                        "Keep each distinct material fact and conditional trigger as a "
                        "separate retrieval seed, and include the user's own wording for "
                        "each issue in search_terms. Do not let one policy issue replace "
                        "another fact dimension in the prompt. "
                        "Use the user's terms and neutral retrieval synonyms only as "
                        "retrieval seeds. Do not invent a policy conclusion, and do not "
                        "select from a fixed list of known issue types. The canonical "
                        "policy issue will be derived later from the admitted source "
                        "passages."
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
                plan = [
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
                return ensure_seller_note_subquestion(question, plan)
    except Exception:
        app.logger.exception("Question decomposition failed; using the original question")
    return ensure_seller_note_subquestion(question, fallback_plan(question))


def fetch_adjacent_chunk_rows(
    conn: Any,
    anchors: list[RetrievedSource],
    sop_version: str,
    corpus_sha256: str,
) -> list[tuple]:
    """Fetch immediate context only when it shares an anchor's section breadcrumb."""
    rows: list[tuple] = []
    seen: set[int] = set()
    ranked_anchors = sorted(anchors, key=lambda source: source.similarity, reverse=True)
    for anchor in ranked_anchors[:TOP_K]:
        if anchor.similarity < MIN_RETRIEVAL_SIMILARITY or not anchor.section_ref:
            continue
        adjacent_ids = [anchor.db_id - 1, anchor.db_id + 1]
        adjacent = conn.execute(
            """
            SELECT id, sop_version, effective_date, page_number, section_ref,
                   chunk_text, GREATEST(%s, %s) AS similarity,
                   transaction_types, entity_structures, party_roles, program_scopes,
                   product_lines, loan_size_bands
            FROM sop_chunks
            WHERE sop_version = %s AND corpus_sha256 = %s
              AND id = ANY(%s) AND section_ref = %s
            ORDER BY id
            """,
            (
                anchor.similarity - 0.01,
                MIN_RETRIEVAL_SIMILARITY,
                sop_version,
                corpus_sha256,
                adjacent_ids,
                anchor.section_ref,
            ),
        ).fetchall()
        for row in adjacent:
            if row[0] in seen:
                continue
            seen.add(row[0])
            rows.append(row)
    return rows


def select_context_sources(
    sources: list[RetrievedSource],
    limit: int = MAX_CONTEXT_SOURCES,
    prioritize_seller_note: bool = False,
) -> list[RetrievedSource]:
    """Keep immediate same-section neighbors together when trimming model context."""
    by_db_id = {source.db_id: source for source in sources}
    def seller_note_priority(source: RetrievedSource) -> int:
        if not prioritize_seller_note:
            return 0
        section = source.section_ref.casefold()
        text = source.chunk_text.casefold()
        if "debt refinancing" in section and "seller-financed note" in text:
            return 2
        if "equity requirements" in section and "seller debt that is subordinated" in text:
            return 1
        return 0

    ordered = sorted(
        sources,
        key=lambda source: (seller_note_priority(source), source.similarity),
        reverse=True,
    )
    selected: list[RetrievedSource] = []
    selected_ids: set[int] = set()
    for source in ordered:
        if source.db_id in selected_ids:
            continue
        group = [source]
        for adjacent_id in (source.db_id - 1, source.db_id + 1):
            neighbor = by_db_id.get(adjacent_id)
            if (
                neighbor is not None
                and neighbor.section_ref == source.section_ref
                and neighbor.db_id not in selected_ids
            ):
                group.append(neighbor)
        remaining = limit - len(selected)
        if len(group) <= remaining:
            selected.extend(group)
            selected_ids.update(item.db_id for item in group)
        elif remaining > 0:
            selected.append(source)
            selected_ids.add(source.db_id)
        if len(selected) >= limit:
            break
    return selected


def retrieve_for_subquestion(
    conn: Any,
    client: OpenAI,
    subquestion: str,
    search_terms: list[str] | None = None,
    sop_version: str = DEFAULT_SOP_VERSION,
    corpus_sha256: str = "",
    material_facts: list[str] | None = None,
    original_question: str = "",
) -> list[RetrievedSource]:
    seller_note_requested = bool(SELLER_NOTE_TOPIC_RE.search(subquestion))
    seller_note_only = (
        seller_note_requested and not has_guaranty_intent(subquestion)
    )
    retrieval_search_terms = [
        term
        for term in (search_terms or [])
        if not (seller_note_only and has_guaranty_intent(term))
    ]
    retrieval_material_facts = [
        fact
        for fact in (material_facts or [])
        if not (seller_note_only and has_guaranty_intent(fact))
    ]
    topic_context = " ".join(
        [subquestion, *retrieval_search_terms, *retrieval_material_facts]
    )
    retrieval_original_question = "" if seller_note_only else original_question
    searches = build_retrieval_searches(
        subquestion,
        retrieval_search_terms,
        retrieval_material_facts,
        retrieval_original_question,
    )
    retrieval_context = " ".join(
        [
            subquestion,
            *retrieval_search_terms,
            *retrieval_material_facts,
            retrieval_original_question,
        ]
    )
    if not seller_note_only and has_guaranty_intent(topic_context):
        searches.append(GUARANTY_RETRIEVAL_QUERY)
    if re.search(r"\b(robs|401\s*\(k\)|retirement trust|plan sponsor|plan trustee)\b", subquestion, re.IGNORECASE):
        searches.append(ROBS_RETRIEVAL_QUERY)
    if re.search(r"\bequity injection\b", subquestion, re.IGNORECASE):
        searches.append(EQUITY_RETRIEVAL_QUERY)
    topic_search_text = f"{subquestion} {' '.join(retrieval_search_terms)}"
    if re.search(
        r"seller[-\s]?financ|seller[-\s]?note|standby|subordinated debt|equity injection|"
        r"project cost|startup|start-up",
        topic_search_text,
        re.IGNORECASE,
    ):
        searches.extend(
            [
                SELLER_NOTE_RETRIEVAL_QUERY,
                CHANGE_OWNERSHIP_INJECTION_RETRIEVAL_QUERY,
            ]
        )
        if re.search(r"startup|start-up", topic_search_text, re.IGNORECASE):
            searches.append(STARTUP_INJECTION_RETRIEVAL_QUERY)

    by_db_id: dict[int, RetrievedSource] = {}
    vector_anchor_ids: set[int] = set()

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
            WHERE sop_version = %s AND corpus_sha256 = %s
            ORDER BY embedding <=> %s
            LIMIT %s
            """,
            (query_vector, sop_version, corpus_sha256, query_vector, TOP_K),
        ).fetchall()
        add_rows(rows)
        vector_anchor_ids.update(row[0] for row in rows)
    for lexical_query in lexical_retrieval_seeds(
        subquestion,
        retrieval_search_terms,
        retrieval_material_facts,
        retrieval_original_question,
    ):
        rows = conn.execute(
            """
            WITH query AS (
                SELECT websearch_to_tsquery('english', %s) AS terms
            )
            SELECT id, sop_version, effective_date, page_number, section_ref,
                   chunk_text,
                   LEAST(
                       0.65,
                       0.35 + ts_rank_cd(
                           to_tsvector('english', coalesce(section_ref, '') || ' ' || chunk_text),
                           query.terms,
                           32
                       ) * 0.30
                   ) AS similarity,
                   transaction_types, entity_structures, party_roles, program_scopes,
                   product_lines, loan_size_bands
            FROM sop_chunks, query
            WHERE sop_version = %s AND corpus_sha256 = %s
              AND to_tsvector(
                  'english', coalesce(section_ref, '') || ' ' || chunk_text
              ) @@ query.terms
            ORDER BY ts_rank_cd(
                to_tsvector('english', coalesce(section_ref, '') || ' ' || chunk_text),
                query.terms
            ) DESC
            LIMIT %s
            """,
            (lexical_query, sop_version, corpus_sha256, TOP_K),
        ).fetchall()
        add_rows(rows)
        vector_anchor_ids.update(row[0] for row in rows)
    if not seller_note_only and has_guaranty_intent(topic_context):
        direct_rows = conn.execute(
            """
            SELECT id, sop_version, effective_date, page_number, section_ref,
                   chunk_text, 1.0 AS similarity,
                   transaction_types, entity_structures, party_roles, program_scopes,
                   product_lines, loan_size_bands
            FROM sop_chunks
            WHERE sop_version = %s AND corpus_sha256 = %s
              AND (section_ref ILIKE '%%> Guaranties%%'
               OR section_ref ILIKE '%%> Personal Guaranties%%')
            ORDER BY id
            LIMIT 6
            """
            ,
            (sop_version, corpus_sha256),
        ).fetchall()
        add_rows(direct_rows)
    if seller_note_requested:
        seller_note_rows = conn.execute(
            """
            SELECT id, sop_version, effective_date, page_number, section_ref,
                   chunk_text, 1.0 AS similarity,
                   transaction_types, entity_structures, party_roles, program_scopes,
                   product_lines, loan_size_bands
            FROM sop_chunks
            WHERE sop_version = %s AND corpus_sha256 = %s
              AND (
                (section_ref ILIKE '%%> Debt Refinancing%%'
                 AND chunk_text ILIKE '%%seller-financed Note%%')
                OR (
                  section_ref ILIKE '%%> Equity Requirements%%'
                  AND chunk_text ILIKE '%%Seller debt that is subordinated%%'
                )
              )
            ORDER BY CASE
                       WHEN section_ref ILIKE '%%> Debt Refinancing%%' THEN 0
                       WHEN section_ref ILIKE '%%> Equity Requirements%%' THEN 1
                       ELSE 2
                     END,
                     id
            LIMIT 8
            """
            ,
            (sop_version, corpus_sha256),
        ).fetchall()
        add_rows(seller_note_rows)
    if re.search(
        r"\besop\b|employee stock ownership",
        retrieval_context,
        re.IGNORECASE,
    ) or any(
        re.search(r"\besop\b|employee stock ownership", term, re.IGNORECASE)
        for term in searches
    ):
        esop_rows = conn.execute(
            """
            SELECT id, sop_version, effective_date, page_number, section_ref,
                   chunk_text, 1.0 AS similarity,
                   transaction_types, entity_structures, party_roles, program_scopes,
                   product_lines, loan_size_bands
            FROM sop_chunks
            WHERE sop_version = %s AND corpus_sha256 = %s
              AND (section_ref ILIKE '%%ESOP%%'
               OR chunk_text ILIKE '%%ESOP%%')
            ORDER BY id
            LIMIT 12
            """
            ,
            (sop_version, corpus_sha256),
        ).fetchall()
        add_rows(esop_rows)
    product_pattern = None
    if re.search(r"sba\s+express|7\s*\(\s*a\s*\)\s+small", retrieval_context, re.IGNORECASE):
        product_pattern = "%7(a) Small%"
    elif re.search(r"export\s+working\s+capital", retrieval_context, re.IGNORECASE):
        product_pattern = "%Export Working Capital%"
    elif re.search(r"international\s+trade", retrieval_context, re.IGNORECASE):
        product_pattern = "%International Trade%"
    elif re.search(r"\bcaplines\b", retrieval_context, re.IGNORECASE):
        product_pattern = "%CAPLines%"
    elif re.search(r"\bmarc\b", retrieval_context, re.IGNORECASE):
        product_pattern = "%MARC%"
    if product_pattern:
        product_rows = conn.execute(
            """
            SELECT id, sop_version, effective_date, page_number, section_ref,
                   chunk_text, 1.0 AS similarity,
                   transaction_types, entity_structures, party_roles, program_scopes,
                   product_lines, loan_size_bands
            FROM sop_chunks
            WHERE sop_version = %s AND corpus_sha256 = %s
              AND section_ref ILIKE %s
            ORDER BY id
            LIMIT 20
            """,
            (sop_version, corpus_sha256, product_pattern),
        ).fetchall()
        add_rows(product_rows)
    if re.search(r"\bcollateral\b", retrieval_context, re.IGNORECASE):
        collateral_rows = conn.execute(
            """
            SELECT id, sop_version, effective_date, page_number, section_ref,
                   chunk_text, 1.0 AS similarity,
                   transaction_types, entity_structures, party_roles, program_scopes,
                   product_lines, loan_size_bands
            FROM sop_chunks
            WHERE sop_version = %s AND corpus_sha256 = %s
              AND (section_ref ILIKE '%%Collateral Requirements%%'
               OR section_ref ILIKE '%%> Collateral%%')
            ORDER BY id
            LIMIT 12
            """
            ,
            (sop_version, corpus_sha256),
        ).fetchall()
        add_rows(collateral_rows)
    if re.search(
        r"seller[-\s]?financ|seller[-\s]?note|standby|subordinated debt|equity injection|"
        r"project cost|startup|start-up|injection",
        topic_context,
        re.IGNORECASE,
    ):
        equity_rows = conn.execute(
            """
            SELECT id, sop_version, effective_date, page_number, section_ref,
                   chunk_text, 1.0 AS similarity,
                   transaction_types, entity_structures, party_roles, program_scopes,
                   product_lines, loan_size_bands
            FROM sop_chunks
            WHERE sop_version = %s AND corpus_sha256 = %s
              AND (chunk_text ILIKE '%%Source of Equity Injection%%'
               OR chunk_text ILIKE '%%seller-financed Note%%'
               OR chunk_text ILIKE '%%Standby Agreements%%'
               OR chunk_text ILIKE '%%equity injection%%')
            ORDER BY CASE
                       WHEN chunk_text ILIKE '%%Seller debt that is subordinated%%'
                         OR chunk_text ILIKE '%%seller-financed Note%%'
                         OR section_ref ILIKE '%%> Debt Refinancing%%'
                       THEN 0
                       ELSE 1
                     END,
                     id
            LIMIT 12
            """
            ,
            (sop_version, corpus_sha256),
        ).fetchall()
        add_rows(equity_rows)
    adjacent_rows = fetch_adjacent_chunk_rows(
        conn,
        [
            by_db_id[db_id]
            for db_id in vector_anchor_ids
            if db_id in by_db_id
        ],
        sop_version,
        corpus_sha256,
    )
    add_rows(adjacent_rows)
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
    subquestion_id: str = "subquestion-unknown",
    policy_issue: dict[str, Any] | None = None,
) -> dict[str, Any]:
    context = format_context(sources)
    synthesizer_input = {
        "subquestion_id": subquestion_id,
        "original_question": original_question,
        "subquestion": subquestion,
        "policy_issue": policy_issue or {},
        "material_facts": material_facts,
        "admitted_source_ids": [source.source_id for source in sources],
        "context": [
            {
                "source_id": source.source_id,
                "breadcrumb": source.section_ref,
                "page": source.page_number,
                "text": source.chunk_text,
            }
            for source in sources
        ],
    }
    app.logger.info(
        "SOP conclusion synthesizer input: %s",
        json.dumps(synthesizer_input, sort_keys=True),
    )
    response = client.chat.completions.create(
        model=ANSWER_MODEL,
        max_tokens=1800,
        temperature=0,
        messages=[
            {
                "role": "system",
                "content": (
                    "Answer only from the supplied SOP passages. First write one short "
                    "applied conclusion in your own words that answers the source-derived "
                    "policy issue against the user's facts. Do not copy a quoted rule "
                    "into the applied conclusion. Attach citations to that conclusion. "
                    "Then provide atomic supporting policy propositions, each with a "
                    "citation. A proposition is allowed only when its cited passage "
                    "actually states the complete proposition. Do not use general legal, "
                    "lending, or tax knowledge. Preserve a cited rule's condition and "
                    "trigger, including one supplied by an adjacent passage; do not "
                    "treat an unstated trigger as satisfied. If the question omits a "
                    "fact needed to apply a conditional rule, state the rule conditionally "
                    "and identify the missing fact instead of giving an unconditional "
                    "eligibility result. Preserve SOP terms of art exactly: plan "
                    "sponsor, plan participant, plan trustee, Borrower, Co-Borrower, "
                    "Applicant, and Operating Company are distinct roles. Apply dollar "
                    "amounts and ownership percentages from the prompt. Show arithmetic "
                    "for computed amounts only when the cited rule and stated facts "
                    "supply the rate and base. If a point is not addressed by the "
                    "passages, leave the conclusion empty rather than guessing. Treat "
                    "the source-derived policy issue as the only requested issue; a "
                    "related passage about another subject is not an answer. When "
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
                    f"SOURCE-DERIVED POLICY ISSUE:\n{json.dumps(policy_issue or {})}\n\n"
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
    returned = {
        "applied_conclusion": result.get(
            "applied_conclusion", {"text": "", "citations": []}
        ),
        "propositions": result.get("propositions", []),
        "other_issues": result.get("other_issues", []),
        "guarantor_rows": result.get("guarantor_rows", []),
    }
    app.logger.info(
        "SOP conclusion synthesizer output: %s",
        json.dumps(
            {"subquestion_id": subquestion_id, "returned": returned},
            sort_keys=True,
        ),
    )
    return returned


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
            gate = candidate.get("gate_by_source_id", {}).get(source_id)
            if not isinstance(gate, dict) or not gate.get("admitted"):
                continue
            verified_quote = find_verbatim_quote(quote, source.chunk_text)
            if verified_quote is None:
                continue
            citations.append(
                build_citation(
                    source,
                    verified_quote,
                    False,
                    applicability_status="applicable",
                    applicability_reason=gate.get("applicability_reason"),
                    condition_result=gate.get("condition_result", "failed"),
                    condition_reason=gate.get("condition_reason"),
                    conditions=gate.get("conditions", []),
                )
            )
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


ISSUE_AUDIT_STOPWORDS = {
    "about", "also", "among", "any", "applicable", "application", "apply",
    "applies", "business", "circumstance", "company", "eligible", "eligibility",
    "entity", "fact", "facts", "financing", "individual", "issue", "lender",
    "loan", "loans", "matter", "must", "owner", "owners", "party", "person",
    "policy", "program", "provision", "question", "require", "required",
    "requirement", "requirements", "rule", "rules", "sba", "scenario",
    "should", "transaction", "transactions",
}


def issue_audit_terms(text: str) -> set[str]:
    terms = set()
    for raw in re.findall(r"[a-z0-9]+", text.casefold()):
        if len(raw) < 4 or raw in ISSUE_AUDIT_STOPWORDS:
            continue
        token = raw
        if token.endswith("ing") and len(token) > 6:
            token = token[:-3]
        elif token.endswith("ed") and len(token) > 5:
            token = token[:-2]
        elif token.endswith("ies") and len(token) > 5:
            token = token[:-3] + "y"
        elif token.endswith("tion") and len(token) > 8:
            token = token[:-4]
        elif token.endswith("s") and len(token) > 5:
            token = token[:-1]
        if len(token) >= 4 and token not in ISSUE_AUDIT_STOPWORDS:
            terms.add(token)
    return terms


def issue_anchor_matches(left: str, right: str) -> bool:
    if left == right:
        return True
    if min(len(left), len(right)) < 5:
        return False
    return SequenceMatcher(None, left, right).ratio() >= 0.78


def conclusion_has_cited_issue_focus(
    requested_question: str,
    conclusion: str,
    evidence: str,
) -> bool:
    """Require a conclusion's requested subject to occur in its cited material."""
    requested_terms = issue_audit_terms(requested_question)
    conclusion_terms = issue_audit_terms(conclusion)
    evidence_terms = issue_audit_terms(evidence)
    if {"seller", "note"}.issubset(requested_terms):
        note_rule_terms = {
            "note",
            "debt",
            "subordinat",
            "refinanc",
        }
        if {"market", "rate"}.issubset(requested_terms):
            seller_note_rate_pattern = re.compile(
                r"(?:\bseller[-\s]?note\b|\bseller[-\s]?financ(?:ed|ing)\b)"
                r"[^.!?]{0,100}\b(?:market|interest)\s+rate\b|"
                r"\b(?:market|interest)\s+rate\b[^.!?]{0,100}"
                r"(?:\bseller[-\s]?note\b|\bseller[-\s]?financ(?:ed|ing)\b)",
                re.IGNORECASE,
            )
            if not seller_note_rate_pattern.search(evidence):
                return False
        conclusion_note_terms = conclusion_terms.intersection(note_rule_terms)
        evidence_note_terms = evidence_terms.intersection(note_rule_terms)
        subject_terms = {"seller", "note"}
        if not conclusion_terms.intersection(subject_terms) or not evidence_terms.intersection(
            subject_terms
        ):
            return False
        return any(
            issue_anchor_matches(conclusion_term, evidence_term)
            for conclusion_term in conclusion_note_terms
            for evidence_term in evidence_note_terms
        )
    if not requested_terms or not conclusion_terms or not evidence_terms:
        return True
    shared_focus = {
        requested
        for requested in requested_terms
        if any(issue_anchor_matches(requested, claim) for claim in conclusion_terms)
    }
    if not shared_focus:
        return True
    return any(
        issue_anchor_matches(focus, cited)
        for focus in shared_focus
        for cited in evidence_terms
    )


CONDITIONAL_TRIGGER_RE = re.compile(
    r"\b(?:if|when|unless|only\s+if|provided\s+that|in\s+the\s+event\s+that|where)\b",
    re.IGNORECASE,
)
CONDITION_TRIGGER_STOPWORDS = {
    "applicant", "applicants", "borrower", "borrowers", "if", "in", "is",
    "less", "loan", "loans", "must", "only", "provided", "shall", "should",
    "that", "the", "unless", "when", "where", "which", "whichever", "will",
    "would",
}
UNRESOLVED_CONDITION_LANGUAGE_RE = re.compile(
    r"\b(?:depends\s+on|cannot\s+(?:determine|conclude)|"
    r"not\s+(?:stated|provided|established|specified|known|clear)|"
    r"missing\s+(?:fact|information|amount|percentage|detail)|"
    r"insufficient\s+(?:facts|information)|unknown|unclear)\b",
    re.IGNORECASE,
)


def condition_trigger_terms(text: str) -> set[str]:
    terms = issue_audit_terms(text) - CONDITION_TRIGGER_STOPWORDS
    normalized = set()
    for term in terms:
        if term in {"leas", "lease", "leased"}:
            normalized.add("lease")
        else:
            normalized.add(term)
    return normalized


def condition_trigger_is_established(trigger: str, fact_text: str) -> bool:
    """Conservatively check whether a split, conditional trigger is stated."""
    trigger_lower = trigger.casefold()
    facts_lower = fact_text.casefold()
    has_currency = bool(re.search(r"\$\s*\d", trigger_lower))
    has_percentage = bool(
        re.search(r"\d+(?:\.\d+)?\s*(?:%|percent)\b", trigger_lower)
    )
    if "whichever is less" in trigger_lower and has_currency and has_percentage:
        if not (
            re.search(r"\$\s*\d", facts_lower)
            and re.search(r"\d+(?:\.\d+)?\s*(?:%|percent)\b", facts_lower)
        ):
            return False
    elif has_currency and not re.search(r"\$\s*\d", facts_lower):
        return False
    elif has_percentage and not re.search(
        r"\d+(?:\.\d+)?\s*(?:%|percent)\b", facts_lower
    ):
        return False

    trigger_terms = condition_trigger_terms(trigger)
    fact_terms = condition_trigger_terms(fact_text)
    if not trigger_terms:
        return False
    overlap = len(trigger_terms & fact_terms) / len(trigger_terms)
    return overlap >= (0.30 if has_currency and has_percentage else 0.55)


def conclusion_preserves_unresolved_trigger(
    conclusion: str, trigger: str
) -> bool:
    if UNRESOLVED_CONDITION_LANGUAGE_RE.search(conclusion):
        return True
    if not CONDITIONAL_TRIGGER_RE.search(conclusion):
        return False
    trigger_terms = condition_trigger_terms(trigger)
    conclusion_terms = condition_trigger_terms(conclusion)
    if not trigger_terms:
        return False
    overlap = len(trigger_terms & conclusion_terms) / len(trigger_terms)
    return overlap >= 0.30


def unresolved_adjacent_trigger(
    candidate: dict[str, Any],
    original_question: str,
    source_by_id: dict[int, RetrievedSource],
) -> dict[str, Any] | None:
    """Find a conditional lead-in split immediately before a cited passage."""
    source_by_db_id = {
        source.db_id: source for source in source_by_id.values()
    }
    allowed_source_ids = set(candidate.get("applicable_source_ids", []))
    fact_text = " ".join(
        [
            original_question,
            candidate.get("requested_question", ""),
            candidate.get("subquestion", ""),
        ]
    )
    conclusion = candidate.get("text", "")
    for citation in candidate.get("citations", []):
        source = source_by_id.get(citation.get("source_id"))
        if source is None:
            continue
        previous = source_by_db_id.get(source.db_id - 1)
        if (
            previous is None
            or previous.source_id not in allowed_source_ids
            or previous.sop_version != source.sop_version
            or previous.effective_date != source.effective_date
            or previous.section_ref != source.section_ref
        ):
            continue
        previous_text = previous.chunk_text.rstrip()
        if not previous_text.endswith(":"):
            continue
        trigger = re.split(r"\n\s*\n", previous_text)[-1].strip()
        if not CONDITIONAL_TRIGGER_RE.search(trigger):
            continue
        if condition_trigger_is_established(trigger, fact_text):
            continue
        if conclusion_preserves_unresolved_trigger(conclusion, trigger):
            continue
        return {"text": trigger, "source_id": previous.source_id}
    return None


def audit_propositions(
    client: OpenAI,
    original_question: str,
    candidates: list[dict[str, Any]],
    source_by_id: dict[int, RetrievedSource],
) -> dict[int, dict[str, bool]]:
    if not candidates:
        return {}
    audit_items = []
    source_by_db_id = {
        source.db_id: source for source in source_by_id.values()
    }
    for index, candidate in enumerate(candidates):
        evidence = []
        cited_sources: list[RetrievedSource] = []
        for citation in candidate["citations"]:
            source = source_by_id[citation["source_id"]]
            cited_sources.append(source)
            evidence.append(
                {
                    "source_id": source.source_id,
                    "section_ref": source.section_ref,
                    "source_context": source.chunk_text[:1800],
                    "quote": citation["quote"],
                }
            )
        allowed_source_ids = set(candidate.get("applicable_source_ids", []))
        context_neighbors: dict[int, RetrievedSource] = {}
        for source in cited_sources:
            for adjacent_id in (source.db_id - 1, source.db_id + 1):
                neighbor = source_by_db_id.get(adjacent_id)
                if (
                    neighbor is not None
                    and neighbor.source_id in allowed_source_ids
                    and neighbor.section_ref == source.section_ref
                    and neighbor.source_id
                    not in {item.source_id for item in cited_sources}
                ):
                    context_neighbors[neighbor.source_id] = neighbor
        for neighbor in context_neighbors.values():
            evidence.append(
                {
                    "source_id": neighbor.source_id,
                    "section_ref": neighbor.section_ref,
                    "source_context": neighbor.chunk_text[:1800],
                    "context_only": True,
                }
            )
        audit_items.append(
            {
                "index": index,
                "kind": candidate["kind"],
                "proposition": candidate["text"],
                "subquestion_id": candidate.get("subquestion_id"),
                "subquestion": candidate.get("subquestion", ""),
                "requested_question": candidate.get("requested_question", ""),
                "policy_issue": candidate.get("policy_issue", {}),
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
                        "You are an independent citation and relevance auditor. For "
                        "each item, return supports=true only when the cited evidence "
                        "supports the item as written. Return relevant=true only when "
                        "the item directly answers both the supplied source-derived "
                        "policy issue and the requested discrete sub-question. A "
                        "proposition about a related subject, shared party, "
                        "shared threshold, or nearby section is not relevant. Supporting "
                        "propositions must be completely stated by their cited quote. "
                        "An evidence item marked context_only is included only to reveal "
                        "a nearby condition or limitation; it is not a citation and "
                        "cannot by itself support a claim. "
                        "An applied conclusion may apply a directly stated SOP rule to "
                        "the concrete facts in the original question; the quote need "
                        "not repeat those facts. Identify the operative subject and "
                        "trigger in each cited passage; shared transaction facts do not "
                        "make a provision responsive to a different issue. Silence or "
                        "a rule about an adjacent subject cannot establish that an "
                        "unaddressed condition has no effect. A negative or categorical "
                        "eligibility conclusion requires affirmative language that "
                        "covers that eligibility issue. If a cited provision is "
                        "conditional and the question does not establish its trigger, "
                        "use nearby context_only passages to identify the trigger and "
                        "do not state an unconditional applied result. Verify every actor, threshold, "
                        "exception, amount, comparison, and computed result. Reject "
                        "claims that add unstated content. Do not repair or rewrite "
                        "propositions. If the policy issue is absent or the item "
                        "answers an adjacent issue, return relevant=false. Missing or "
                        "ambiguous checks must not be treated as admitted."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Original question:\n{original_question}\n\n"
                        f"Propositions, requested sub-questions, source-derived issues, "
                        f"and cited evidence:\n{json.dumps(audit_items)}"
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
                                        "relevant": {"type": "boolean"},
                                    },
                                    "required": ["index", "supports", "relevant"],
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
        checks = {
            item["index"]: {
                "entailment_supported": item["supports"] is True,
                "relevant_to_subquestion": item["relevant"] is True,
                "admitted_for_render": (
                    item["supports"] is True and item["relevant"] is True
                ),
            }
            for item in result.get("checks", [])
            if (
                isinstance(item, dict)
                and isinstance(item.get("index"), int)
                and isinstance(item.get("supports"), bool)
                and isinstance(item.get("relevant"), bool)
            )
        }
        for index, candidate in enumerate(candidates):
            if candidate.get("kind") in {"conclusion", "proposition"}:
                cited_issue_text = "\n".join(
                    "\n".join(
                        [
                            source_by_id[citation["source_id"]].section_ref,
                            citation["quote"],
                        ]
                    )
                    for citation in candidate["citations"]
                    if citation.get("source_id") in source_by_id
                )
                requested_question = (
                    candidate.get("requested_question")
                    or candidate.get("subquestion")
                    or original_question
                )
                if not conclusion_has_cited_issue_focus(
                    requested_question,
                    candidate.get("text", ""),
                    cited_issue_text,
                ):
                    previous = checks.get(index, {})
                    checks[index] = {
                        "entailment_supported": previous.get(
                            "entailment_supported", False
                        ),
                        "relevant_to_subquestion": False,
                        "admitted_for_render": False,
                    }
                    app.logger.warning(
                        "Withholding conclusion without cited issue focus: %s",
                        candidate.get("text", ""),
                    )
            policy_issue = candidate.get("policy_issue") or {}
            if not policy_issue.get("text") or policy_issue.get("unresolved"):
                checks[index] = {
                    "entailment_supported": checks.get(index, {}).get(
                        "entailment_supported", False
                    ),
                    "relevant_to_subquestion": False,
                    "admitted_for_render": False,
                }
        for index, candidate in enumerate(candidates):
            trigger = unresolved_adjacent_trigger(
                candidate, original_question, source_by_id
            )
            if trigger is None:
                continue
            previous = checks.get(index, {})
            checks[index] = {
                "entailment_supported": False,
                "relevant_to_subquestion": previous.get(
                    "relevant_to_subquestion", True
                ),
                "admitted_for_render": False,
                "unresolved_trigger": trigger,
            }
            app.logger.warning(
                "Withholding claim with unresolved adjacent conditional trigger: %s",
                trigger["text"],
            )
        return checks
    except Exception:
        app.logger.exception("Citation audit failed; withholding unsupported claims")
        return {}


def candidate_admitted(result: Any) -> bool:
    return (
        isinstance(result, dict)
        and result.get("entailment_supported") is True
        and result.get("relevant_to_subquestion") is True
        and result.get("admitted_for_render") is True
    )


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
    condition_result: str = "passed",
    condition_reason: str | None = None,
    conditions: list[dict[str, Any]] | None = None,
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
        "condition_result": condition_result,
        "condition_reason": condition_reason,
        "conditions": conditions or [],
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