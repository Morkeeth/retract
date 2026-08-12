-- RETRACT schema v2 -- the deterministic claim key.
--
-- WHY v2 EXISTS
-- v1 locked an LSH bucket of the embedding and deduplicated by L2 distance.
-- Measured against real embeddings (all-MiniLM-L6-v2), that design is unsound:
--
--   "Customer 4471 verified"  vs  "Customer 4472 verified"   L2 0.172
--   "9902 lives in Berlin"    vs  "9902 USED TO live in Berlin"  L2 0.296
--   paraphrases of one fact                                  L2 0.323 - 0.843
--
-- Different facts are closer together than paraphrases of the same fact. No
-- threshold separates them, so a distance cutoff would silently merge two
-- customers' identity checks, or a fact with its own negation.
--
-- v2 therefore takes identity away from the embedding and gives it to a
-- canonical (subject, predicate) key. The lock is exact, not probabilistic.
-- Vectors keep the job they are genuinely good at: retrieval in the READ phase.

------------------------------------------------------------------------------
ALTER TABLE memory ADD COLUMN IF NOT EXISTS subject   STRING NOT NULL DEFAULT '';
ALTER TABLE memory ADD COLUMN IF NOT EXISTS predicate STRING NOT NULL DEFAULT '';
ALTER TABLE memory ADD COLUMN IF NOT EXISTS embedder  STRING NOT NULL DEFAULT 'unknown';

-- Embeddings from different models are not comparable. Mixing them silently
-- corrupts every distance in the table, so provenance is recorded per row.

CREATE INDEX IF NOT EXISTS memory_claim
    ON memory (scope, subject, predicate) WHERE valid_to IS NULL;

------------------------------------------------------------------------------
-- claim_key -- the lock target. One row per (scope, subject, predicate).
-- This is what makes "exactly one agent decides this claim at a time" a
-- guarantee rather than a 99% measurement.
------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS claim_key (
    scope      STRING NOT NULL,
    subject    STRING NOT NULL,
    predicate  STRING NOT NULL,
    revision   INT8 NOT NULL DEFAULT 0,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (scope, subject, predicate)
);

------------------------------------------------------------------------------
-- contradiction -- two agents, one claim key, incompatible claims.
--
-- This is not an error table. It is the product. Embedding distance cannot
-- tell a paraphrase from a negation, so RETRACT does not ask it to: any second
-- claim on a held key is surfaced for adjudication rather than merged. The
-- database's guarantee is that exactly one agent adjudicates at a time and the
-- outcome is recorded atomically with the memory it affects.
------------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS contradiction (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    scope         STRING NOT NULL,
    subject       STRING NOT NULL,
    predicate     STRING NOT NULL,
    incumbent_id  UUID NOT NULL REFERENCES memory(id),
    challenger    STRING NOT NULL,          -- the claim that was not written
    challenger_by STRING NOT NULL,          -- which agent proposed it
    distance      FLOAT8 NOT NULL,          -- a hint for the adjudicator, never a decision
    resolution    STRING NOT NULL DEFAULT 'open'
                  CHECK (resolution IN ('open', 'duplicate', 'superseded', 'rejected')),
    detected_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at   TIMESTAMPTZ,
    INDEX contradiction_open (scope, resolution, detected_at DESC)
);
