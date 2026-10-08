"""Source-only admission checks. These withhold claims; they never write legal answers."""
import re
from typing import Any

from sophia_issues import sentences, resolve_applied_quotes


PERMISSION_CLAIM = re.compile(
    r"\b(?:valid\s+under|legally\s+valid|permissible|authoriz(?:ed|es)|"
    r"allow(?:ed|s)|permit(?:ted|s)|lawful|sufficient\s+(?:authority|permission))\b", re.I
)
AFFIRMATIVE_AUTHORITY = re.compile(
    r"\bmay\s+(?!not\b)|\b(?:is|are)\s+(?:expressly\s+)?"
    r"(?:permitted|allowed|authorized)\b|\b(?:authorizes|allows|permits)\b", re.I
)


def permission_scope_error(candidate: dict[str, Any]) -> str | None:
    """A prerequisite is not a grant of authority, regardless of supplied consent."""
    if candidate.get("kind") not in {"conclusion", "proposition"}:
        return None
    text = candidate.get("text") or ""
    positive_claims = [
        match for match in PERMISSION_CLAIM.finditer(text)
        if not re.search(r"\b(?:not|never|isn't|aren't)\s*$", text[:match.start()], re.I)
    ]
    if not positive_claims:
        return None
    quotes = [citation.get("quote") or "" for citation in candidate.get("citations", [])]
    if not any(AFFIRMATIVE_AUTHORITY.search(quote) for quote in quotes):
        return (
            "The selected quotes state prerequisites or restrictions, not affirmative "
            "authority for the claimed permission. Meeting a necessary condition does "
            "not establish overall permissibility."
        )
    return None


def signer_obligations(policy_issue: dict[str, Any], requested: str) -> list[dict[str, Any]]:
    """Enumerate obligations from the validated issue, not a list of known scenarios."""
    if not re.search(
        r"\bsign(?:s|ing|ers?)?\b|\bexecut(?:e|es|ion)\b|\bguarantors?\b", requested, re.I
    ):
        return []
    result = []
    seen = set()
    for clause in policy_issue.get("clauses", []):
        if not isinstance(clause.get("quote"), str):
            continue
        for quote in sentences(clause["quote"]):
            modal = re.search(r"\b(?:must|shall)\b", quote, re.I)
            if not modal or not re.search(r"\b(?:sign|execut|guarant)", quote[modal.end():], re.I):
                continue
            prefix = re.split(r"[,;:]", quote[:modal.start()])[-1].strip()
            subject = re.sub(r"^(?:the|each|any|all|both|every)\s+", "", prefix, flags=re.I)
            if not subject or len(subject) > 80:
                continue
            key = (clause.get("source_id"), quote)
            if key in seen:
                continue
            seen.add(key)
            result.append({"source_id": clause.get("source_id"), "quote": quote, "subject": subject})
    return result


def missing_signer_obligations(candidate: dict[str, Any]) -> list[dict[str, Any]]:
    if candidate.get("kind") != "conclusion":
        return []
    targets = signer_obligations(
        candidate.get("policy_issue") or {}, candidate.get("requested_question") or ""
    )
    prose = candidate.get("text") or ""
    missing = []
    for target in targets:
        # Singular/plural is grammatical; distinct role words remain distinct.
        subject = target["subject"]
        singular = subject[:-1] if subject.lower().endswith("s") and not subject.lower().endswith("ss") else subject
        pattern = r"\b" + re.escape(singular) + r"s?\b"
        actor_present = bool(re.search(pattern, prose, re.I))
        quoted = any(
            citation.get("source_id") == target["source_id"]
            and re.sub(r"\s+", " ", target["quote"]).casefold()
            in re.sub(r"\s+", " ", citation.get("quote") or "").casefold()
            for citation in candidate.get("citations", [])
        )
        if not actor_present or not quoted:
            missing.append(target)
    return missing


def unresolved_obligation_row(target: dict[str, Any]) -> dict[str, Any]:
    """Expose a missing source-role tuple without asserting an individual's duty."""
    return {
        "party": f"{target['subject']} (application unresolved)",
        "capacity": target["subject"],
        "ownership_percentage": None,
        "ownership_comparison": None,
        "guaranty_type": "Unresolved",
        "triggering_provision": target["quote"],
        "additional_conditions": "Resolve this source obligation and its trigger against the stated facts.",
        "status": "unresolved",
        "unresolved_reason": "The answer did not establish this source role with its own operative citation.",
        "citations": [],
    }


def source_role_schema(targets: list[dict[str, Any]], menu: dict[int, list[str]]) -> dict[str, Any]:
    """Required per-source slots make omission structurally detectable."""
    properties = {}
    for index, target in enumerate(targets):
        options = menu.get(target["source_id"], [])
        if target["quote"] not in options:
            continue
        properties[f"role_{index}"] = {
            "type": "object",
            "description": (
                f"Apply the obligation for the source role '{target['subject']}'. "
                "Include that role in your applied prose. Preserve its condition, "
                "use supplied identities only, and do not invent missing identities. "
                "Leave text and citations empty if no application can be supported."
            ),
            "properties": {
                "text": {
                    "type": "string",
                    "description": (
                        "One to three sentences APPLYING this role's own quote to "
                        "concrete facts in the question, not reciting the quote. "
                        "Identify the supplied parties or holdings this capacity "
                        "concerns. Keep source conditions explicit when their trigger "
                        "is not established. Missing personal names do not erase a "
                        "source-imposed role. This text is also its own-quote application."
                    ),
                },
                "citations": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source_id": {"type": "integer", "enum": [target["source_id"]]},
                            "quote_id": {"type": "integer", "enum": [options.index(target["quote"])]},
                        },
                        "required": ["source_id", "quote_id"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["text", "citations"],
            "additionalProperties": False,
        }
    return {
        "type": "object", "properties": properties,
        "required": list(properties), "additionalProperties": False,
    }


def assemble_source_role_claims(
    applications: dict[str, Any], targets: list[dict[str, Any]], menu: dict[int, list[str]],
) -> dict[str, Any]:
    """Assemble model-written claims before auditing; never manufacture prose or support."""
    texts, citations = [], []
    for index, target in enumerate(targets):
        application = applications.get(f"role_{index}")
        if not isinstance(application, dict) or not str(application.get("text", "")).strip():
            continue
        resolve_applied_quotes(application, menu)
        own_citations = [
            citation for citation in application.get("citations", [])
            if citation.get("source_id") == target["source_id"]
            and citation.get("quote") == target["quote"]
        ]
        if not own_citations:
            continue
        for citation in own_citations:
            # The model's one atomic application is audited against its own quote.
            # Do not ask for a second copy that can silently diverge or recite it.
            citation["application"] = application["text"]
        texts.append(application["text"])
        citations.extend(own_citations)
    return {"text": " ".join(texts), "citations": citations}
