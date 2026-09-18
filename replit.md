# sop-query-tool

A grounded question-answering tool for SBA SOP 50 10 8.

## Run & Operate

- `pnpm --filter @workspace/api-server run dev` — run the Flask API
- `pnpm --filter @workspace/sop-query-tool run dev` — run the React frontend
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required env: `DATABASE_URL`, `OPENAI_API_KEY`, and `SESSION_SECRET`
- Production auth also requires `REPL_ID`; local development bypasses auth unless `NODE_ENV=production`

## Stack

- pnpm workspaces, Node.js 24, TypeScript 5.9
- API: Flask
- DB: PostgreSQL + pgvector
- Validation: Zod (`zod/v4`), `drizzle-zod`
- API codegen: Orval (from OpenAPI spec)
- Build: esbuild (CJS bundle)

## Where things live

- `artifacts/api-server/app.py` — Flask API and grounded answer pipeline
- `artifacts/sop-query-tool/` — React frontend
- `migrations/001_create_sop_chunks.sql` — pgvector schema
- `migrations/006_add_corpus_metadata.sql` — edition-bound corpus metadata and SHA-256
- `migrations/007_add_api_rate_limits.sql` — shared fixed-window rate-limit counters
- `scripts/ingest_sop.py` — guarded DOCX ingestion
- `scripts/run_sop_regression.py` — 28-case grounded-answer regression runner

## Architecture decisions

- Retrieval is bound to both the configured SOP edition and the corpus SHA-256; chunks from another edition are never mixed into an answer.
- Production startup fails if the selected corpus metadata or chunk set is missing or inconsistent.
- Raw stage telemetry is development-only unless `EXPOSE_DEBUG_TELEMETRY=true` is explicitly set.
- Rate limits use PostgreSQL counters so multiple production workers share one fixed-window budget.

## Product

SOP-hia answers SBA SOP 50 10 8.1 questions with source passages, section/page citations,
applicability checks, guarantor rows, numeric validation, effective-date warnings, and a
plain-language legal disclaimer. Users sign in with Replit OIDC before querying production.

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

- Production schema and corpus promotion happen through the Replit publish flow; do not apply production DDL or seed data ad hoc.
- Run API-spec codegen after changing `lib/api-spec/openapi.yaml`.
- A production regression run needs an authenticated `sophia_session` cookie; pass it through `SOP_REGRESSION_COOKIE` rather than weakening production auth.

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
