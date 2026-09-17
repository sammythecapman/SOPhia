ALTER TABLE sop_chunks
    ADD COLUMN IF NOT EXISTS effective_date DATE;

ALTER TABLE sop_chunks
    ADD COLUMN IF NOT EXISTS page_number INTEGER;

UPDATE sop_chunks
SET effective_date = COALESCE(effective_date, DATE '2026-10-01')
WHERE effective_date IS NULL;