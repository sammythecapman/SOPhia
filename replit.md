# sop-query-tool

A grounded question-answering tool for SBA SOP 50 10 8.

## Run & Operate

- `pnpm --filter @workspace/api-server run dev` — run the Flask API
- `pnpm --filter @workspace/sop-query-tool run dev` — run the React frontend
- `pnpm run typecheck` — full typecheck across all packages
- `pnpm run build` — typecheck + build all packages
- `pnpm --filter @workspace/api-spec run codegen` — regenerate API hooks and Zod schemas from the OpenAPI spec
- `pnpm --filter @workspace/db run push` — push DB schema changes (dev only)
- Required env: `DATABASE_URL` — Postgres connection string

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
- `scripts/ingest_sop.py` — guarded DOCX ingestion

## Architecture decisions

_Populate as you build — non-obvious choices a reader couldn't infer from the code (3-5 bullets)._

## Product

_Describe the high-level user-facing capabilities of this app once they exist._

## User preferences

_Populate as you build — explicit user instructions worth remembering across sessions._

## Gotchas

_Populate as you build — sharp edges, "always run X before Y" rules._

## Pointers

- See the `pnpm-workspace` skill for workspace structure, TypeScript setup, and package details
