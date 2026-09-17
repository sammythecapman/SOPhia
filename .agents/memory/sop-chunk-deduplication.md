---
name: SOP chunk deduplication
description: Durable constraint for storing long DOCX chunks in PostgreSQL.
---

Use a compact deterministic hash for SOP chunk deduplication rather than indexing the full chunk text in a unique B-tree key.

**Why:** PostgreSQL rejects oversized B-tree index entries when long chunk text is included directly in a unique constraint; this can abort ingestion after embedding work has started.

**How to apply:** Keep the dedupe key based on SOP version, section reference, and a generated content hash, and make ingest upserts target that compact key.