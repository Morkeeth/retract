-- RETRACT schema v3 -- close the compensation loop.
--
-- Adds the `compensated` status and a `compensated_by` pointer from an
-- original effect to the reversal that undid it. Fresh installs get this from
-- schema.sql; this file is the ALTER path for clusters that already loaded
-- schema.sql + schema_v2.sql.
--
-- Do not touch schema_v2.sql (night-run brief). Apply after v2:
--   schema.sql -> schema_v2.sql -> schema_v3.sql

ALTER TABLE effect ADD COLUMN IF NOT EXISTS compensated_by UUID REFERENCES effect(id);

-- Replace the status check so `compensated` is a legal value. The auto-name
-- CockroachDB gave the inline CHECK in schema.sql is `check_status` (verified
-- on v25.4 / v26.2). Dropping by name is deliberate: silently leaving the old
-- check in place would make every compensation fail at write time.
ALTER TABLE effect DROP CONSTRAINT IF EXISTS check_status;
ALTER TABLE effect ADD CONSTRAINT check_status
    CHECK (status IN ('pending', 'executed', 'cancelled',
                      'needs_compensation', 'compensated'));
