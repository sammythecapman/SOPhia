"""Structured applicability tags for SOP chunks and user fact patterns."""

from __future__ import annotations

import re
from typing import Any

APPLICABILITY_DIMENSIONS = (
    "transaction_types",
    "entity_structures",
    "party_roles",
    "program_scopes",
    "product_lines",
    "loan_size_bands",
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
    "product_lines": {
        "standard_7a": "Standard 7(a)",
        "7a_small": "7(a) Small Loans",
        "sba_express": "SBA Express",
        "export_working_capital": "Export Working Capital",
        "international_trade": "International Trade",
        "caplines": "CAPLines",
        "marc": "MARC",
        "504": "504",
    },
    "loan_size_bands": {
        "up_to_350k": "loans up to $350,000",
        "over_350k": "loans over $350,000",
    },
}


def _add(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def classify_text(text: str, section_ref: str = "") -> dict[str, list[str]]:
    """Classify a chunk or fact pattern without using an LLM."""

    lower = f"{section_ref}\n{text}".casefold()
    section_lower = section_ref.casefold()
    headings = [part.strip() for part in section_ref.split(" > ") if part.strip()]
    nearest_heading = headings[-1].casefold() if headings else ""
    local_section = nearest_heading
    scope_text = f"{nearest_heading}\n{text}".casefold()
    appendix_15 = bool(re.search(r"appendix\s+15\b", section_lower))
    tags = {dimension: [] for dimension in APPLICABILITY_DIMENSIONS}

    # ESOP scope is assigned to dedicated ESOP headings, not to neighboring
    # change-of-ownership or product provisions that merely mention an ESOP
    # exception or list ESOPs among several transaction categories.
    is_esop = bool(
        re.search(r"\besop\b|employee stock ownership", nearest_heading)
        or (not section_ref and re.search(r"\besop\b|employee stock ownership", text, re.I))
    )
    if re.search(r"\bnot\s+(?:an?\s+)?esop\b|without\s+esop", scope_text):
        is_esop = False
    is_broad_program_heading = bool(
        re.search(
            r"7\s*\(\s*a\s*\).{0,20}504|504.{0,20}7\s*\(\s*a\s*\)",
            nearest_heading,
        )
    )
    program_source = nearest_heading if section_ref else lower
    is_504 = bool(
        re.search(r"\b504\b|development company", program_source)
        and not is_broad_program_heading
    )
    is_7a = bool(
        re.search(r"\b7\s*\(\s*a\s*\)|\b7a\b", program_source)
        and not is_broad_program_heading
    )
    transaction_source = nearest_heading if section_ref else lower
    is_partial = bool(
        re.search(r"partial\s+change\s+of\s+ownership|partial\s+change", transaction_source)
    )
    is_multi_step = bool(
        re.search(r"multi[-\s]?step\s+change\s+of\s+ownership|multi[-\s]?step", transaction_source)
    )
    is_redirect_to_appendix_15 = bool(
        re.search(r"see\s+appendix\s+15|appendix\s+15\s+for\s+change", scope_text)
    )
    is_change = bool(
        re.search(
            r"change\s+of\s+ownership|acquisition|purchase\s+of\s+(?:a\s+)?business|"
            r"buyer|seller" if not section_ref else r"change\s+of\s+ownership|acquisition|purchase\s+of\s+(?:a\s+)?business",
            transaction_source,
        )
        and not is_redirect_to_appendix_15
    )
    is_startup = bool(
        re.search(
            r"\bstart[-\s]?up\b|new\s+(?:c\s+)?corp(?:oration)?",
            transaction_source,
        )
    )
    is_refinance = bool(re.search(r"refinanc", transaction_source))
    is_franchise = bool(re.search(r"\bfranchise\b", transaction_source))
    is_expansion = bool(re.search(r"\bexpansion\b", transaction_source))

    if is_esop:
        _add(tags["transaction_types"], "esop")
    if is_partial:
        _add(tags["transaction_types"], "partial_change_of_ownership")
    elif is_multi_step:
        _add(tags["transaction_types"], "multi_step_change_of_ownership")
    elif is_change or (appendix_15 and not is_startup):
        _add(tags["transaction_types"], "change_of_ownership")
    if is_startup:
        _add(tags["transaction_types"], "startup")
    if is_refinance:
        _add(tags["transaction_types"], "refinance")
    if is_franchise:
        _add(tags["transaction_types"], "franchise")
    if is_expansion:
        _add(tags["transaction_types"], "expansion")

    if re.search(r"\bc\s*corp(?:oration)?\b", nearest_heading):
        _add(tags["entity_structures"], "c_corp")
    if re.search(r"\bllc\b|limited liability company", nearest_heading):
        _add(tags["entity_structures"], "llc")
    if re.search(
        r"\btrust\b|trust guarant|trustee",
        nearest_heading,
    ) or re.search(r"(?:if|when|where)\s+(?:a\s+)?trust\b.{0,90}guarant", lower):
        if not (not section_ref and re.search(r"\bno\s+trust\b|not\s+(?:a\s+)?trust", lower)):
            _add(tags["entity_structures"], "trust")
    if re.search(r"401\s*\(\s*k\s*\)|retirement|robs|profit[-\s]?sharing plan", scope_text):
        if not (
            not section_ref
            and re.search(r"\bno\s+(?:retirement|plan)\b|not\s+(?:a\s+)?retirement", lower)
        ):
            _add(tags["entity_structures"], "retirement_plan")
    if re.search(r"co[-\s]?borrower", nearest_heading):
        _add(tags["entity_structures"], "co_borrower")
    if re.search(
        r"\bepc\b.*\boc\b|\boc\b.*\bepc\b|eligible passive companies",
        nearest_heading,
    ):
        _add(tags["entity_structures"], "epc_oc")
    if re.search(r"entity owner|entity ownership", nearest_heading):
        _add(tags["entity_structures"], "entity_owner")

    role_source = nearest_heading if section_ref else lower
    if re.search(
        r"seller\s+(?:remains|retains?|continu(?:es|ing)).{0,50}(?:ownership|owner)|"
        r"seller.{0,30}partial\s+owner|retained\s+seller\s+ownership",
        scope_text,
    ):
        _add(tags["party_roles"], "seller_retaining_ownership")
    if re.search(r"exiting seller|seller does not retain|no retained seller ownership", scope_text):
        _add(tags["party_roles"], "exiting_seller")
    if re.search(r"plan sponsor", role_source) or (
        "robs" in role_source and re.search(r"plan sponsor", scope_text)
    ):
        _add(tags["party_roles"], "plan_sponsor")
    if re.search(r"plan participant|participant", role_source) or (
        "robs" in role_source and re.search(r"plan participant|participant", scope_text)
    ):
        _add(tags["party_roles"], "plan_participant")
    if re.search(r"trustee|plan trustee", role_source) or (
        "robs" in role_source and re.search(r"trustee|plan trustee", scope_text)
    ):
        _add(tags["party_roles"], "trustee")
    if re.search(r"guarant(?:y|ee|ies|or)|personal guarant", role_source):
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

    # For indexed chunks, product and size scope comes from the nearest
    # heading. Body text may cross-reference other products without governing
    # them. Questions, by contrast, are classified from the full fact pattern.
    # Product-specific chapters are identified by their breadcrumb ancestry,
    # not only by the leaf heading. A CAPLines leaf such as "Underwriting"
    # must retain the CAPLines scope from its parent chapter.
    product_source = section_lower if section_ref else lower
    if re.search(r"sba\s+express", product_source):
        _add(tags["product_lines"], "sba_express")
    if re.search(r"7\s*\(\s*a\s*\)\s+small|7a\s+small", product_source):
        _add(tags["product_lines"], "7a_small")
    if re.search(r"export\s+working\s+capital", product_source):
        _add(tags["product_lines"], "export_working_capital")
    if re.search(r"international\s+trade", product_source):
        _add(tags["product_lines"], "international_trade")
    if re.search(r"\bcaplines\b", product_source):
        _add(tags["product_lines"], "caplines")
    if re.search(r"\bmarc\b", product_source):
        _add(tags["product_lines"], "marc")
    is_504_product = bool(
        re.search(
            r"section\s+c\.\s*504|chapter\s+\d+:\s*504\b|"
            r"program-specific requirements\s*>\s*504\b",
            product_source,
        )
    )
    if (is_504 or is_504_product) and not is_esop:
        _add(tags["product_lines"], "504")
    if (
        not section_ref
        and re.search(r"standard\s+7\s*\(\s*a\s*\)|\b7\s*\(\s*a\s*\)\b|\b7a\b", product_source)
        and not tags["product_lines"]
    ):
        _add(tags["product_lines"], "standard_7a")
    if section_ref and re.search(r"standard\s+7\s*\(\s*a\s*\)", product_source):
        _add(tags["product_lines"], "standard_7a")
    if appendix_15 and not is_esop:
        _add(tags["product_lines"], "standard_7a")

    if re.search(
        r"7\s*\(\s*a\s*\)\s+small|7a\s+small|small\s+(?:loan|loans)|"
        r"not\s+greater\s+than\s*\$?\s*350[,.]?000|up\s+to\s+\$?\s*350[,.]?000",
        product_source,
    ):
        _add(tags["loan_size_bands"], "up_to_350k")
    if re.search(
        r"standard\s+7\s*\(\s*a\s*\)|greater\s+than\s*\$?\s*350[,.]?000|"
        r"more\s+than\s+\$?\s*350[,.]?000",
        product_source,
    ):
        _add(tags["loan_size_bands"], "over_350k")

    return tags


def classify_question(text: str) -> dict[str, list[str]]:
    tags = classify_text(text)
    lower = text.casefold()
    products = tags["product_lines"]
    amount_match = re.search(
        r"\$\s*([\d,]+(?:\.\d+)?)\s*(mm|m|million|k|thousand)?", lower
    )
    amount = None
    if amount_match:
        number = float(amount_match.group(1).replace(",", ""))
        multiplier = {
            "mm": 1_000_000,
            "m": 1_000_000,
            "million": 1_000_000,
            "k": 1_000,
            "thousand": 1_000,
        }.get(amount_match.group(2) or "", 1)
        amount = number * multiplier
    if re.search(r"sba\s+express", lower):
        products[:] = ["sba_express"]
    elif re.search(r"7\s*\(\s*a\s*\)\s+small|7a\s+small", lower):
        products[:] = ["7a_small"]
    elif re.search(r"export\s+working\s+capital", lower):
        products[:] = ["export_working_capital"]
    elif re.search(r"international\s+trade", lower):
        products[:] = ["international_trade"]
    elif re.search(r"\bcaplines\b", lower):
        products[:] = ["caplines"]
    elif re.search(r"\bmarc\b", lower):
        products[:] = ["marc"]
    elif "504" in lower and not re.search(r"7\s*\(\s*a\s*\)", lower):
        products[:] = ["504"]
    elif amount is not None and amount <= 350_000 and (
        "7(a)" in lower or "7a" in lower or "sba" in lower
    ):
        products[:] = ["7a_small"]
    else:
        products[:] = ["standard_7a"]

    tags["loan_size_bands"] = []
    if amount is not None:
        _add(
            tags["loan_size_bands"],
            "up_to_350k" if amount <= 350_000 else "over_350k",
        )
    return tags


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
        # Missing metadata on either side is not an affirmative mismatch.
        # A provision remains admissible until both the provision and the
        # fact pattern state conflicting values for this dimension.
        if not source_values or not fact_values:
            continue
        if source_values.intersection(fact_values):
            continue
        labels = DIMENSION_LABELS[dimension]
        source_label = ", ".join(labels.get(value, value) for value in source_values)
        if fact_values:
            fact_label = ", ".join(labels.get(value, value) for value in fact_values)
            dimension_label = dimension.removesuffix("_types").replace("_", " ")
            return (
                False,
                f"{dimension_label} mismatch: provision governs {source_label}; "
                f"the facts indicate {fact_label}",
            )
        return (
            False,
            f"provision governs {source_label}; the facts indicate {fact_label}",
        )
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
                row[11] if len(row) > 11 else None,
                row[12] if len(row) > 12 else None,
            ),
        )
    }