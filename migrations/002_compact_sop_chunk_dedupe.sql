ALTER TABLE sop_chunks
    ADD COLUMN IF NOT EXISTS chunk_hash TEXT GENERATED ALWAYS AS (
        md5(sop_version || chr(31) || section_ref || chr(31) || chunk_text)
    ) STORED;

ALTER TABLE sop_chunks
    DROP CONSTRAINT IF EXISTS sop_chunks_sop_version_section_ref_chunk_text_key;

ALTER TABLE sop_chunks
    DROP CONSTRAINT IF EXISTS sop_chunks_sop_version_section_ref_chunk_hash_key;

ALTER TABLE sop_chunks
    ADD CONSTRAINT sop_chunks_sop_version_section_ref_chunk_hash_key
    UNIQUE (sop_version, section_ref, chunk_hash);