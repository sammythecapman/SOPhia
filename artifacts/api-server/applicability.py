"""Structured applicability tags for SOP chunks and user fact patterns."""

from __future__ import annotations

import re
from typing import Any

APPLICABILITY_DIMENSIONS = (
    "transaction_types",
    "entity_structures",
    "party_roles",
    "program_scopes",
)

DIMENSION_LABELS = {
    "transaction_types": {
        "esop": "ESOP transactions",
        "504": "504 transactions",
        "7a": "7(a) transactions",
        "change_of_ownership": "change-of-ownership transactions",
        "partial_change_of_ownership": "partial change-of-ownership transactions",
        "multi_step_change_of_ownership": "multi-step change-of-ownership transactions",
        "startup": "startup transactions",
        "refinance": "refinance transactions",
        "franchise": "franchise transactions",
        "expansion": "expansion transactions",
    },
    "entity_structures": {
        "c_corp": "C corporations",
        "llc": "LLCs",
        "trust": "trusts",
        "retirement_plan": "retirement-plan or ROBS ownership",
        "co_borrower": "Co-Borrower structures",
        "epc_oc": "EPC/OC structures",
        "entity_owner": "entity ownership",
    },
    "party_roles": {
        "seller_retaining_ownership": "a seller retaining ownership",
        "exiting_seller": "an exiting seller",
        "plan_sponsor": "a plan sponsor",
        "plan_participant": "a plan participant",
        "trustee": "a trustee",
        "guarantor": "a guarantor",
        "selling_owner_under_20": "a selling owner below 20% ownership",
    },
    "program_scopes": {
        "esop": "ESOP authority",
        "504": "504 authority",
        "7a": "7(a) authority",
    },
}


def _add(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def classify_text(text: str, section_ref: str = "") -> dict[str, list[str]]:
    """Classify a chunk or fact pattern without using an LLM."""

    lower = f"{section_ref}\n{text}".casefold()
    section_lower = section_ref.casefold()
    local_section = " > ".join(section_ref.split(" > ")[-2:]).casefold()
    scope_text = f"{local_section}\n{text}".casefold()
    tags = {dimension: [] for dimension in APPLICABILITY_DIMENSIONS}

    is_esop = bool(re.search(r"\besop\b|employee stock ownership", scope_text))
    is_broad_program_heading = bool(
        re.search(r"7\s*\(\s*a\s*\).{0,20}504|504.{0,20}7\s*\(\s*a\s*\)", local_section)
    )
    is_504 = bool(
        re.search(r"\b504\b|development company", scope_text)
        and not is_broad_program_heading
    )
    is_7a = bool(
        re.search(r"\b7\s*\(\s*a\s*\)|\b7a\b", scope_text)
        and not is_broad_program_heading
    )
    is_partial = bool(
        re.search(r"partial\s+change\s+of\s+ownership|partial\s+change", lower)
    )
    is_multi_step = bool(
        re.search(r"multi[-\s]?step\s+change\s+of\s+ownership|multi[-\s]?step", lower)
    )
    is_change = bool(
        re.search(
            r"change\s+of\s+ownership|acquisition|purchase\s+of\s+(?:a\s+)?business|"
            r"buyer|seller" if not section_ref else r"$^",
            scope_text,
        )
    )
    is_startup = bool(re.search(r"\bstart[-\s]?up\b|new\s+(?:c\s+)?corp(?:oration)?", lower))
    is_refinance = bool(re.search(r"refinanc", lower))
    is_franchise = bool(re.search(r"\bfranchise\b", lower))
    is_expansion = bool(re.search(r"\bexpansion\b", lower))

    if is_esop:
        _add(tags["transaction_types"], "esop")
    if is_504:
        _add(tags["transaction_types"], "504")
    if is_7a:
        _add(tags["transaction_types"], "7a")
    if is_partial:
        _add(tags["transaction_types"], "partial_change_of_ownership")
    elif is_multi_step:
        _add(tags["transaction_types"], "multi_step_change_of_ownership")
    elif is_change:
        _add(tags["transaction_types"], "change_of_ownership")
    if is_startup:
        _add(tags["transaction_types"], "startup")
    if is_refinance:
        _add(tags["transaction_types"], "refinance")
    if is_franchise:
        _add(tags["transaction_types"], "franchise")
    if is_expansion:
        _add(tags["transaction_types"], "expansion")

    if re.search(r"\bc\s*corp(?:oration)?\b", local_section):
        _add(tags["entity_structures"], "c_corp")
    if re.search(r"\bllc\b|limited liability company", local_section):
        _add(tags["entity_structures"], "llc")
    if re.search(
        r"\btrust\b|trust guarant|trustee",
        local_section,
    ) or re.search(r"(?:if|when|where)\s+(?:a\s+)?trust\b.{0,90}guarant", lower):
        _add(tags["entity_structures"], "trust")
    if re.search(r"401\s*\(\s*k\s*\)|retirement|robs|profit[-\s]?sharing plan", lower):
        _add(tags["entity_structures"], "retirement_plan")
    if re.search(r"co[-\s]?borrower", local_section):
        _add(tags["entity_structures"], "co_borrower")
    if re.search(
        r"\bepc\b.*\boc\b|\boc\b.*\bepc\b|eligible passive companies",
        local_section,
    ):
        _add(tags["entity_structures"], "epc_oc")
    if re.search(r"entity owner|entity ownership", local_section):
        _add(tags["entity_structures"], "entity_owner")

    if re.search(
        r"seller\s+(?:remains|retains?|continu(?:es|ing)).{0,50}(?:ownership|owner)|"
        r"seller.{0,30}partial\s+owner|retained\s+seller\s+ownership",
        scope_text,
    ):
        _add(tags["party_roles"], "seller_retaining_ownership")
    if re.search(r"exiting seller|seller does not retain|no retained seller ownership", scope_text):
        _add(tags["party_roles"], "exiting_seller")
    if re.search(r"plan sponsor", local_section) or (
        "robs" in local_section and re.search(r"plan sponsor", scope_text)
    ):
        _add(tags["party_roles"], "plan_sponsor")
    if re.search(r"plan participant|participant", local_section) or (
        "robs" in local_section and re.search(r"plan participant|participant", scope_text)
    ):
        _add(tags["party_roles"], "plan_participant")
    if re.search(r"trustee|plan trustee", local_section) or (
        "robs" in local_section and re.search(r"trustee|plan trustee", scope_text)
    ):
        _add(tags["party_roles"], "trustee")
    if re.search(r"guarant(?:y|ee|ies|or)|personal guarant", lower):
        _add(tags["party_roles"], "guarantor")
    if re.search(
        r"selling owner.{0,30}(?:less than|under|below)\s*(?:20\s*%|20 percent)|"
        r"selling owner.{0,30}\b(?:1[0-9]|[0-9])\s*(?:%|percent)",
        lower,
    ):
        _add(tags["party_roles"], "selling_owner_under_20")

    if is_esop:
        _add(tags["program_scopes"], "esop")
    if is_504 and not is_esop:
        _add(tags["program_scopes"], "504")
    if is_7a and not is_esop:
        _add(tags["program_scopes"], "7a")

    return tags


def classify_question(text: str) -> dict[str, list[str]]:
    return classify_text(text)


def merge_tags(*tag_sets: dict[str, list[str]]) -> dict[str, list[str]]:
    merged = {dimension: [] for dimension in APPLICABILITY_DIMENSIONS}
    for tag_set in tag_sets:
        for dimension in APPLICABILITY_DIMENSIONS:
            for value in tag_set.get(dimension, []):
                _add(merged[dimension], value)
    return merged


def applicability_check(
    source_tags: dict[str, list[str]],
    fact_tags: dict[str, list[str]],
) -> tuple[bool, str | None]:
    """Return whether a scoped source can apply to the supplied fact pattern."""

    for dimension in APPLICABILITY_DIMENSIONS:
        source_values = set(source_tags.get(dimension, []))
        fact_values = set(fact_tags.get(dimension, []))
        if not source_values:
            continue
        if source_values.intersection(fact_values):
            continue
        labels = DIMENSION_LABELS[dimension]
        source_label = ", ".join(labels.get(value, value) for value in source_values)
        if fact_values:
            fact_label = ", ".join(labels.get(value, value) for value in fact_values)
            return (
                False,
                f"provision governs {source_label}; the facts indicate {fact_label}",
            )
        return False, f"provision requires {source_label}, which is not stated in the facts"
    return True, None


def source_metadata_from_row(row: Any) -> dict[str, list[str]]:
    """Read arrays from PostgreSQL rows, tolerating legacy NULL/empty metadata."""

    return {
        dimension: [
            str(value)
            for value in (row or [])
            if isinstance(value, str) and value
        ]
        for dimension, row in zip(
            APPLICABILITY_DIMENSIONS,
            (
                row[7] if len(row) > 7 else None,
                row[8] if len(row) > 8 else None,
                row[9] if len(row) > 9 else None,
                row[10] if len(row) > 10 else None,
            ),
        )
    }