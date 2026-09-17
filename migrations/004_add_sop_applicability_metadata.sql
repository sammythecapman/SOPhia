ALTER TABLE sop_chunks
    ADD COLUMN IF NOT EXISTS transaction_types TEXT[] NOT NULL DEFAULT '{}';

ALTER TABLE sop_chunks
    ADD COLUMN IF NOT EXISTS entity_structures TEXT[] NOT NULL DEFAULT '{}';

ALTER TABLE sop_chunks
    ADD COLUMN IF NOT EXISTS party_roles TEXT[] NOT NULL DEFAULT '{}';

ALTER TABLE sop_chunks
    ADD COLUMN IF NOT EXISTS program_scopes TEXT[] NOT NULL DEFAULT '{}';