CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS sop_chunks (
    id BIGSERIAL PRIMARY KEY,
    sop_version TEXT NOT NULL,
    section_ref TEXT NOT NULL,
    chunk_text TEXT NOT NULL,
    embedding vector(1536) NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (sop_version, section_ref, chunk_text)
);

-- lists=100 is a practical starting point for a corpus expected to contain
-- thousands to low tens of thousands of SOP chunks. Rebuild/tune after ingestion
-- if the actual corpus size or recall requirements differ materially.
CREATE INDEX IF NOT EXISTS sop_chunks_embedding_ivfflat_idx
ON sop_chunks USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);