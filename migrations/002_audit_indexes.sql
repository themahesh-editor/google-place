-- Additive-only migration: supports durable event/review history queries.
-- Existing application records are retained.
CREATE INDEX IF NOT EXISTS event_kind_created_at
    ON attachai.event(kind, created_at DESC);
CREATE INDEX IF NOT EXISTS suppression_kind_created_at
    ON attachai.suppression(kind, created_at DESC);
INSERT INTO attachai.schema_version(version) VALUES (2);
