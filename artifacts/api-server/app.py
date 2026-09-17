import json
import os
from typing import Any

from anthropic import Anthropic
from flask import Flask, jsonify, request
from openai import OpenAI

from db import connection

app = Flask(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
CLAUDE_MODEL = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
TOP_K = 6


def require_env() -> None:
    missing = [
        key
        for key in ("DATABASE_URL", "OPENAI_API_KEY", "ANTHROPIC_API_KEY")
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
        with connection() as conn:
            rows = conn.execute(
                """
                SELECT section_ref, chunk_text, 1 - (embedding <=> %s) AS similarity
                FROM sop_chunks
                ORDER BY embedding <=> %s
                LIMIT %s
                """,
                (embedding, embedding, TOP_K),
            ).fetchall()
        if not rows:
            return jsonify({"error": "No SOP content has been ingested yet."}), 503

        context = "\n\n".join(
            f'<SOURCE id="{index}" section_ref="{row[0]}">\n{row[1]}\n</SOURCE>'
            for index, row in enumerate(rows, 1)
        )
        response = Anthropic().messages.create(
            model=CLAUDE_MODEL,
            max_tokens=1800,
            system=(
                "Answer only from the supplied SOP context. Do not invent, extend, or "
                "infer policy beyond the text. Clearly state when the context is "
                "insufficient or uncertain. Return only JSON with keys answer and "
                "citations. citations must be an array of objects with source_id, "
                "section_ref, and quote. Every quote must be copied verbatim from one "
                "source and should be the shortest passage that directly supports the answer."
            ),
            messages=[
                {
                    "role": "user",
                    "content": f"QUESTION:\n{question}\n\nCONTEXT:\n{context}",
                }
            ],
        )
        text = "".join(block.text for block in response.content if block.type == "text")
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
        verified.append(
            {
                "section_ref": section_ref,
                "quote": quote,
                "source_chunk": chunk_text,
                "verified": bool(quote) and quote in chunk_text,
            }
        )
    return verified


if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    app.run(host="0.0.0.0", port=port)