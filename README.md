# sop-query-tool

A standalone retrieval-augmented question-answering app for SBA SOP 50 10 8.
It uses a React frontend, Flask API, Replit PostgreSQL with pgvector, and OpenAI
embeddings/chat completions for context-constrained answers.

## Required environment

- `DATABASE_URL` — provided by the Replit PostgreSQL database
- `OPENAI_API_KEY` — Replit Secret
- `OPENAI_CHAT_MODEL` — optional; defaults to `gpt-4o-mini`

Never commit API keys. Add or update them through Replit Secrets.

## Database setup

`migrations/001_create_sop_chunks.sql` enables pgvector, creates `sop_chunks`,
and adds a cosine IVFFLAT index. The index uses `lists = 100`, a sensible
starting point for thousands to low tens of thousands of chunks. Tune and
rebuild it after ingestion if corpus size or recall measurements justify it.

Replit Publish promotes the development schema to its managed production
database. The checked-in SQL also documents the schema for independent setup.

## Run

The configured workflows run:

- API: `uv run python artifacts/api-server/app.py`
- Web: `pnpm --filter @workspace/sop-query-tool run dev`

The API is served under `/api`; `POST /api/sop/query` accepts:

```json
{ "question": "What does the SOP say about ...?" }
```

## SOP ingestion: preview first, then approve

Place one `.docx` in `attached_assets`, or pass its path explicitly.

Preview only (guaranteed not to call the embedding API or write rows):

```bash
uv run python scripts/ingest_sop.py
# or
uv run python scripts/ingest_sop.py path/to/SOP.docx
```

Review section references and chunk text. To proceed, rerun:

```bash
uv run python scripts/ingest_sop.py --ingest --version "SOP 50 10 8"
```

The script then requires typing the exact displayed approval phrase. It batches
embeddings, retries transient failures with exponential backoff, reports
progress, and upserts on `(sop_version, section_ref, chunk_text)` so reruns are
safe. Approval is never implied by `--ingest`.

No SOP has been ingested as part of project setup.