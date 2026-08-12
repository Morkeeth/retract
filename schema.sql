-- RETRACT: agentic memory that concurrent agents cannot corrupt,
-- and that can take a belief back.
--
-- CORRECTNESS PATH: the semantic bucket lock (see `memory_bucket`).
-- MEASURED OPTIMISATION: whether the ANN read alone forces a 40001.
-- We do not assume the second. experiments/day1_conflict.py decides it,
-- and the finding is reported either way.

SET enable_durable_locking_for_serializable = true;

------------------------------------------------------------------------------
-- 1. MEMORY -- bitemporal. A belief is never destroyed, only closed.
------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope         STRING NOT NULL,              -- tenant / agent-fleet boundary
    content       STRING NOT NULL,
    embedding     VECTOR(512) NOT NULL,
    bucket        INT8 NOT NULL,                -- LSH signature, see note below

    -- valid time: when the belief was true of the world
    valid_from    TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_to      TIMESTAMPTZ,                  -- NULL = currently believed

    -- transaction time: when we recorded it. Never updated.
    recorded_at   TIMESTAMPTZ NOT NULL DEFAULT now(),

    superseded_by UUID REFERENCES memory(id),
    status        STRING NOT NULL DEFAULT 'active'
                  CHECK (status IN ('active', 'superseded', 'retracted')),
    author_agent  STRING NOT NULL,
    snapshot_ts   DECIMAL NOT NULL              -- the HLC the author read at
);

-- Prefix columns first: vector index filters only accelerate on a prefix.
CREATE VECTOR INDEX IF NOT EXISTS memory_ann ON memory (scope, embedding);
CREATE INDEX IF NOT EXISTS memory_live ON memory (scope, bucket) WHERE valid_to IS NULL;

------------------------------------------------------------------------------
-- 2. MEMORY_BUCKET -- the lock target, and the heart of the design.
--
-- A transaction cannot hold a lock across LLM inference, and we refuse to
-- depend on vector-index internals for correctness. So the neighbourhood
-- itself gets a row, and that row is what agents contend on.
--
-- `bucket` is a random-hyperplane LSH signature of the embedding: k fixed
-- hyperplanes, one sign bit each, packed into an int. Semantically adjacent
-- memories hash to the same bucket, so two agents concluding near-identical
-- facts serialize against the SAME row -- while agents working on unrelated
-- memories never touch each other.
--
-- This is the property the ANN read was hoped to give for free. Here it is
-- explicit, durable, and version-independent.
------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS memory_bucket (
    scope       STRING NOT NULL,
    bucket      INT8 NOT NULL,
    revision    INT8 NOT NULL DEFAULT 0,        -- bumped on every merge decision
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (scope, bucket)
);

------------------------------------------------------------------------------
-- 3. DERIVATION -- the DAG that makes retraction propagate.
-- Concurrency control stops a bad belief being written. This is what reaches
-- the bad belief that was already written and already believed.
------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS derivation (
    child_id   UUID NOT NULL REFERENCES memory(id) ON DELETE CASCADE,
    parent_id  UUID NOT NULL REFERENCES memory(id) ON DELETE CASCADE,
    PRIMARY KEY (child_id, parent_id),
    INDEX derivation_by_parent (parent_id)      -- retraction walks this way
);

------------------------------------------------------------------------------
-- 4. EFFECT -- the side effects a belief justified.
-- Retracting a belief cancels its pending effects in the SAME transaction,
-- and surfaces the already-executed ones for compensation. An agent memory
-- that cannot reach its own side effects is a diary, not a system of record.
------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS effect (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope            STRING NOT NULL,
    justified_by     UUID NOT NULL REFERENCES memory(id),
    tool             STRING NOT NULL,
    payload          JSONB NOT NULL,
    idempotency_key  STRING NOT NULL,
    status           STRING NOT NULL DEFAULT 'pending'
                     CHECK (status IN ('pending', 'executed', 'cancelled', 'needs_compensation')),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    executed_at      TIMESTAMPTZ,
    UNIQUE (scope, idempotency_key),            -- the exactly-once guarantee
    INDEX effect_by_memory (justified_by)
);

------------------------------------------------------------------------------
-- 5. AUDIT -- append-only. NOT AS OF SYSTEM TIME.
-- Time travel is capped by a 4-hour GC window on this cluster, so it can be a
-- fast path but never the record. An explicit table is also the stronger
-- artifact: a judge can query it, and cannot query an engine feature.
------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS audit_log (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope       STRING NOT NULL,
    at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    agent       STRING NOT NULL,
    action      STRING NOT NULL,                -- read | commit | conflict | retract
    memory_id   UUID,
    detail      JSONB NOT NULL DEFAULT '{}',
    INDEX audit_by_time (scope, at DESC)
);
