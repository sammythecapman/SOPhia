ALTER TABLE sop_chunks
    ADD COLUMN IF NOT EXISTS product_lines TEXT[] NOT NULL DEFAULT '{}';

ALTER TABLE sop_chunks
    ADD COLUMN IF NOT EXISTS loan_size_bands TEXT[] NOT NULL DEFAULT '{}';