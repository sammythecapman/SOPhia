CREATE TABLE IF NOT EXISTS corpus_metadata (
    edition TEXT PRIMARY KEY,
    source_url TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    effective_date DATE NOT NULL,
    chunk_count INTEGER NOT NULL DEFAULT 0,
    ingested_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE sop_chunks
    ADD COLUMN IF NOT EXISTS corpus_sha256 TEXT;

CREATE INDEX IF NOT EXISTS sop_chunks_corpus_edition_idx
    ON sop_chunks (sop_version, corpus_sha256);