-- RETRACT schema v3 -- close the compensation loop, and finish the v1 removal.
--
-- Adds the `compensated` status and a `compensated_by` pointer from an
-- original effect to the reversal that undid it. Fresh installs get this from
-- schema.sql; this file is the ALTER path for clusters that already loaded
-- schema.sql + schema_v2.sql.
--
-- Do not touch schema_v2.sql (night-run brief). Apply after v2:
--   schema.sql -> schema_v2.sql -> schema_v3.sql
--
-- WHAT THIS FILE LEARNED FROM THE LIVE CLUSTER (14 Aug, first run against Cloud)
-- Two things were true of the demo cluster that no local test could have shown,
-- because a local store is created fresh from the current schema.sql every time:
--
--   1. `memory.bucket INT8 NOT NULL` is still there. It is the v1 LSH design
--      that commit 2614250 deleted from the code and from schema.sql. Deleting
--      it from the code without an ALTER path meant the deployed build and the
--      new build disagree about whether the column exists: origin/main's
--      engine.py still names `bucket` in its INSERT, the new engine.py does
--      not, and against this cluster the new one fails every write with
--      NotNullViolation. Deploying the new build without this file would take
--      the public demo from working to entirely write-dead.
--   2. Both tables carry `schema_locked = true`. Under that setting CockroachDB
--      refuses the ALTERs below outright, so the unlock/relock pair is not
--      ceremony -- without it this file does nothing but raise.
--
-- On `bucket` we drop the NOT NULL rather than the column. Dropping the column
-- would also require dropping the vestigial `memory_live (scope, bucket)` index
-- and would destroy the 18 existing rows' values, four days before a deadline,
-- to buy nothing: with the constraint gone the live cluster accepts exactly the
-- writes a fresh install accepts. The remaining divergence from schema.sql is a
-- nullable unread column and an index nothing queries. Dropping both is a
-- post-submission cleanup, recorded here so it is not rediscovered.

ALTER TABLE memory SET (schema_locked = false);
ALTER TABLE effect SET (schema_locked = false);

-- The v1 leftover. See note 1 above: this is what stands between the current
-- code and the live cluster, not anything to do with compensation.
ALTER TABLE memory ALTER COLUMN bucket DROP NOT NULL;

ALTER TABLE effect ADD COLUMN IF NOT EXISTS compensated_by UUID REFERENCES effect(id);

-- Replace the status check so `compensated` is a legal value. The auto-name
-- CockroachDB gave the inline CHECK in schema.sql is `check_status` (verified
-- on v25.4 / v26.2). Dropping by name is deliberate: silently leaving the old
-- check in place would make every compensation fail at write time.
ALTER TABLE effect DROP CONSTRAINT IF EXISTS check_status;
ALTER TABLE effect ADD CONSTRAINT check_status
    CHECK (status IN ('pending', 'executed', 'cancelled',
                      'needs_compensation', 'compensated'));

ALTER TABLE memory SET (schema_locked = true);
ALTER TABLE effect SET (schema_locked = true);
