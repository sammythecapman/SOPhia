import json
import os
import re
from dataclasses import dataclass
from difflib import SequenceMatcher
from typing import Any

from flask import Flask, jsonify, request
from openai import OpenAI
from pgvector import Vector

from db import connection

app = Flask(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
ANSWER_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
DEFAULT_SOP_VERSION = os.getenv("SOP_VERSION", "SOP 50 10 8.1")
DEFAULT_EFFECTIVE_DATE = os.getenv("SOP_EFFECTIVE_DATE", "2026-10-01")
TOP_K = 6
MAX_CONTEXT_SOURCES = 18
NO_PROVISION = f"No provision located in {DEFAULT_SOP_VERSION} addressing this point."
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
EQUITY_RETRIEVAL_QUERY = (
    "SBA equity injection requirements, minimum injection percentage, "
    "source of injection funds, change of ownership, and seller-financed note"
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

        with connection() as conn:
            source_by_db_id: dict[int, RetrievedSource] = {}
            subquestion_sources: list[list[int]] = []
            for item in plan:
                retrieved = retrieve_for_subquestion(conn, client, item["question"])
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
            )
            for source in ordered_sources
        ]
        source_by_db_id = {source.db_id: source for source in sources}
        source_by_id = {source.source_id: source for source in sources}

        candidates: list[dict[str, Any]] = []
        subanswers: list[dict[str, Any]] = []
        for index, (item, db_ids) in enumerate(zip(plan, subquestion_sources)):
            context_sources = [
                source_by_db_id[db_id]
                for db_id in db_ids
                if db_id in source_by_db_id
            ]
            context_sources.sort(key=lambda source: source.similarity, reverse=True)
            context_sources = context_sources[:MAX_CONTEXT_SOURCES]
            generated = generate_propositions(
                client,
                question,
                item["question"],
                list(dict.fromkeys([question, *item.get("material_facts", [])])),
                context_sources,
            )
            subanswers.append(
                {
                    "question": item["question"],
                    "generated": generated,
                    "candidate_index": index,
                }
            )
            for proposition in generated.get("propositions", []):
                candidates.append(
                    {
                        "kind": "proposition",
                        "subanswer_index": index,
                        "text": proposition.get("text", ""),
                        "citations": proposition.get("citations", []),
                    }
                )
            for issue in generated.get("other_issues", []):
                candidates.append(
                    {
                        "kind": "other_issue",
                        "subanswer_index": index,
                        "text": issue.get("text", ""),
                        "citations": issue.get("citations", []),
                    }
                )

        validated_candidates = validate_candidate_citations(candidates, source_by_id)
        audit_results = audit_propositions(client, question, validated_candidates, source_by_id)
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
        for index, item in enumerate(subanswers):
            matching = [
                candidate
                for candidate in supported_candidates
                if candidate["kind"] == "proposition"
                and candidate["subanswer_index"] == index
            ]
            propositions = [
                {
                    "text": candidate["text"],
                    "citations": candidate["citations"],
                }
                for candidate in matching
            ]
            for proposition in propositions:
                all_citations.extend(proposition["citations"])
            rendered_subanswers.append(
                {
                    "question": item["question"],
                    "answer": (
                        "\n\n".join(proposition["text"] for proposition in propositions)
                        if propositions
                        else NO_PROVISION
                    ),
                    "no_provision": not bool(propositions),
                    "propositions": propositions,
                }
            )

        rendered_issues = []
        for candidate in supported_candidates:
            if candidate["kind"] != "other_issue":
                continue
            rendered_issues.append(
                {"text": candidate["text"], "citations": candidate["citations"]}
            )
            all_citations.extend(candidate["citations"])

        answer_parts = []
        for subanswer in rendered_subanswers:
            if len(rendered_subanswers) > 1:
                answer_parts.append(f"{subanswer['question']}\n{subanswer['answer']}")
            else:
                answer_parts.append(subanswer["answer"])
        if rendered_issues:
            answer_parts.append(
                "Other issues identified:\n"
                + "\n".join(f"- {issue['text']}" for issue in rendered_issues)
            )

        unique_citations = dedupe_citations(all_citations)
        metadata_source = sources[0] if sources else None
        return jsonify(
            {
                "answer": "\n\n".join(answer_parts),
                "source_version": (
                    metadata_source.sop_version if metadata_source else DEFAULT_SOP_VERSION
                ),
                "effective_date": (
                    metadata_source.effective_date
                    if metadata_source
                    else DEFAULT_EFFECTIVE_DATE
                ),
                "subanswers": rendered_subanswers,
                "other_issues": rendered_issues,
                "sources": unique_citations,
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
                        "implicate an additional SOP provision even if not directly asked."
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
                                    },
                                    "required": ["question", "material_facts"],
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
                    return [{"question": question, "material_facts": [question]}]
                return valid[:4]
    except Exception:
        app.logger.exception("Question decomposition failed; using the original question")
    return [{"question": question, "material_facts": [question]}]


def retrieve_for_subquestion(
    conn: Any, client: OpenAI, subquestion: str
) -> list[RetrievedSource]:
    searches = [subquestion]
    if GUARANTY_TERMS.search(subquestion):
        searches.append(GUARANTY_RETRIEVAL_QUERY)
    if re.search(r"\b(robs|401\s*\(k\)|retirement trust|plan sponsor|plan trustee)\b", subquestion, re.IGNORECASE):
        searches.append(ROBS_RETRIEVAL_QUERY)
    if re.search(r"\bequity injection\b", subquestion, re.IGNORECASE):
        searches.append(EQUITY_RETRIEVAL_QUERY)

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
                   chunk_text, 1 - (embedding <=> %s) AS similarity
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
                   chunk_text, 1.0 AS similarity
            FROM sop_chunks
            WHERE section_ref ILIKE '%> Guaranties%'
               OR section_ref ILIKE '%> Personal Guaranties%'
            ORDER BY id
            LIMIT 6
            """
        ).fetchall()
        add_rows(direct_rows)
    return sorted(by_db_id.values(), key=lambda source: source.similarity, reverse=True)


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
                    "Answer only from the supplied SOP passages. Produce atomic factual "
                    "propositions, and attach at least one citation to every proposition. "
                    "A proposition is allowed only when its cited passage actually states "
                    "the complete proposition. Do not use general legal, lending, or tax "
                    "knowledge. Preserve SOP terms of art exactly: plan sponsor, plan "
                    "participant, plan trustee, Borrower, Co-Borrower, Applicant, and "
                    "Operating Company are distinct roles. Apply dollar amounts and "
                    "ownership percentages from the prompt. If a point is not addressed "
                    "by the passages, put no proposition for it. Identify material "
                    "unasked issues only when the prompt contains a fact that triggers a "
                    "cited SOP provision. Return no uncited summary."
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
                        "propositions": {"$ref": "#/$defs/claim_list"},
                        "other_issues": {"$ref": "#/$defs/claim_list"},
                    },
                    "required": ["propositions", "other_issues"],
                    "additionalProperties": False,
                    "$defs": {
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
                        }
                    },
                },
            },
        },
    )
    result = parse_json(response.choices[0].message.content or "")
    return {
        "propositions": result.get("propositions", []),
        "other_issues": result.get("other_issues", []),
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
            verified_quote = find_verbatim_quote(quote, source.chunk_text)
            if verified_quote is None:
                continue
            citations.append(build_citation(source, verified_quote, False))
        if citations:
            valid_candidates.append({**candidate, "citations": citations})
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
                        "You are an independent citation auditor. For each proposition, "
                        "return supports=true only if the cited quote entails the complete "
                        "proposition as written. Exact word overlap is not enough. Reject "
                        "claims that add unstated actors, thresholds, exceptions, amounts, "
                        "or legal conclusions. Do not repair or rewrite propositions."
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
    source: RetrievedSource, quote: str, supports_conclusion: bool
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
    }


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