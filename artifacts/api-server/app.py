import json
import os
import re
from typing import Any

from flask import Flask, jsonify, request
from openai import OpenAI
from pgvector import Vector

from db import connection

app = Flask(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
ANSWER_MODEL = os.getenv("OPENAI_CHAT_MODEL", "gpt-4o-mini")
TOP_K = 6


def require_env() -> None:
    missing = [
        key
        for key in ("DATABASE_URL", "OPENAI_API_KEY")
        if not os.getenv(key)
    ]
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
        embedding = (
            OpenAI()
            .embeddings.create(model=EMBEDDING_MODEL, input=question)
            .data[0]
            .embedding
        )
        query_vector = Vector(embedding)
        with connection() as conn:
            rows = conn.execute(
                """
                SELECT section_ref, chunk_text, 1 - (embedding <=> %s) AS similarity
                FROM sop_chunks
                ORDER BY embedding <=> %s
                LIMIT %s
                """,
                (query_vector, query_vector, TOP_K),
            ).fetchall()
        if not rows:
            return jsonify({"error": "No SOP content has been ingested yet."}), 503

        context = "\n\n".join(
            f'<SOURCE id="{index}" section_ref="{row[0]}">\n{row[1]}\n</SOURCE>'
            for index, row in enumerate(rows, 1)
        )
        response = OpenAI().chat.completions.create(
            model=ANSWER_MODEL,
            max_tokens=1800,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Answer only from the supplied SOP context. Do not invent, extend, "
                        "or infer policy beyond the text. Clearly state when the context is "
                        "insufficient or uncertain. Return only JSON with keys answer and "
                        "citations. citations must be an array of objects with source_id, "
                        "section_ref, and quote. Every quote must be copied verbatim from one "
                        "source and should be the shortest passage that directly supports "
                        "the answer. For an answer supported by the context, include at "
                        "least one citation. If the context is insufficient, say so in "
                        "answer and return an empty citations array."
                    ),
                },
                {
                    "role": "user",
                    "content": f"QUESTION:\n{question}\n\nCONTEXT:\n{context}",
                },
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "sop_answer",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {
                            "answer": {"type": "string"},
                            "citations": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "source_id": {"type": "integer"},
                                        "section_ref": {"type": "string"},
                                        "quote": {"type": "string"},
                                    },
                                    "required": ["source_id", "section_ref", "quote"],
                                    "additionalProperties": False,
                                },
                            },
                        },
                        "required": ["answer", "citations"],
                        "additionalProperties": False,
                    },
                },
            },
        )
        text = response.choices[0].message.content or ""
        result = parse_json(text)
        sources = verify_citations(result.get("citations", []), rows)
        return jsonify({"answer": str(result.get("answer", "")).strip(), "sources": sources})
    except RuntimeError as exc:
        app.logger.error("Configuration error: %s", exc)
        return jsonify({"error": str(exc)}), 503
    except Exception:
        app.logger.exception("SOP query failed")
        return jsonify({"error": "The SOP query could not be completed. Please try again."}), 502


def parse_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0]
    value = json.loads(cleaned)
    if not isinstance(value, dict):
        raise ValueError("Claude returned an invalid response shape.")
    return value


def verify_citations(citations: Any, rows: list[tuple]) -> list[dict[str, Any]]:
    if not isinstance(citations, list):
        return []
    verified = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        source_id = citation.get("source_id")
        quote = citation.get("quote")
        if not isinstance(source_id, int) or not isinstance(quote, str):
            continue
        if source_id < 1 or source_id > len(rows):
            continue
        section_ref, chunk_text, _ = rows[source_id - 1]
        verified_quote = find_verbatim_quote(quote, chunk_text)
        if verified_quote is None:
            continue
        verified.append(
            {
                "section_ref": section_ref,
                "quote": verified_quote,
                "source_chunk": chunk_text,
                "verified": True,
            }
        )
    return verified


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

    # Models sometimes stop immediately before the source sentence's final
    # punctuation. If the quoted text is an exact source prefix, return the
    # complete sentence from the source rather than displaying an altered quote.
    prefix = quote.strip().rstrip(".!?").rstrip()
    if len(prefix) < 40:
        return None
    start = source.find(prefix)
    if start < 0:
        return None
    end_match = re.search(r"[.!?](?=\s|$)", source[start + len(prefix) :])
    if not end_match:
        return None
    end = start + len(prefix) + end_match.end()
    return source[start:end]


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)