# sop-query-tool

A standalone retrieval-augmented question-answering app for SBA SOP 50 10 8.1.
It uses a React frontend, Flask API, Replit PostgreSQL with pgvector, and OpenAI
embeddings/chat completions for context-constrained answers.

## Required environment

- `DATABASE_URL` — provided by the Replit PostgreSQL database
- `OPENAI_API_KEY` — Replit Secret
- `OPENAI_CHAT_MODEL` — optional; defaults to `gpt-4o-mini`
- `SOP_ALLOWED_EMAILS` — production-only, comma-separated list of verified account emails; unset or empty denies production queries

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

The current source is the SBA SOP 50 10 8.1 Technical Policy Updates document,
effective October 1, 2026. Because the older edition is also retained in
`attached_assets`, pass the source path explicitly:

Preview only (guaranteed not to call the embedding API or write rows):

```bash
uv run python scripts/ingest_sop.py \
  attached_assets/SOP_50_10_8.1_Technical_Policy_Updates_effective_10.1.2026.docx
```

Review section references and chunk text. To proceed, rerun:

```bash
uv run python scripts/ingest_sop.py \
  attached_assets/SOP_50_10_8.1_Technical_Policy_Updates_effective_10.1.2026.docx \
  --ingest
```

The script then requires typing the exact displayed approval phrase. It batches
embeddings, retries transient failures with exponential backoff, reports
progress, derives the version and effective date from the document, and upserts
on `(sop_version, section_ref, chunk_hash)` so reruns are safe. Approval is
never implied by `--ingest`. The health endpoint reports the corpus SHA-256 so
the technical revision can be distinguished from the prior document with the
same SOP version label.

The development database contains the approved SOP 50 10 8.1 corpus. The
regression set in `tests/sop_regression.json` can be run with:

```bash
uv run python scripts/run_sop_regression.py
```
