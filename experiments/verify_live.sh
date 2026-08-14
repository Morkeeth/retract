#!/usr/bin/env bash
# Verify PR #2 against the live cluster, in one shot, in dependency order.
#
# WHY THIS EXISTS
# PR #2 was written overnight by an agent with no credentials. Everything in it
# is verified against a LOCAL single-node store and explicitly unrun against
# CockroachDB Cloud -- the PR says so itself. That gap is the whole of Day 2:
# the compensation handler is the pitch, and it has never touched the cluster
# the judges will see. This script is what closes it without a fresh
# investigation at the moment the credentials appear.
#
# ORDER MATTERS AND IS NOT OBVIOUS
# schema_v3.sql adds the `compensated` status and the `compensated_by` column.
# compensate_eval.py cannot pass without them, and the failure it produces is a
# column error that reads like a bug in the handler. Migration first, or the
# morning is spent debugging the wrong file.
#
# WHAT IT WILL NOT DO
# Apply the migration. That is a live schema change on the demo cluster, so it
# needs a human saying so: re-run with APPLY_SCHEMA=1. Everything else is a
# read or a scoped test write.
#
#   ./experiments/verify_live.sh                # checks + evals, no migration
#   APPLY_SCHEMA=1 ./experiments/verify_live.sh # includes the v3 migration

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

pass=0; fail=0; skip=0
step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }
ok()   { printf '   PASS  %s\n' "$1"; pass=$((pass+1)); }
bad()  { printf '   FAIL  %s\n' "$1"; fail=$((fail+1)); }
meh()  { printf '   SKIP  %s\n' "$1"; skip=$((skip+1)); }

run() { # run <label> <cmd...>  -- a non-zero exit is a real failure, not noise
  local label="$1"; shift
  if "$@" > /tmp/retract-verify.$$ 2>&1; then
    ok "$label"; tail -3 /tmp/retract-verify.$$ | sed 's/^/         /'
  else
    bad "$label (exit $?)"; tail -15 /tmp/retract-verify.$$ | sed 's/^/         /'
  fi
  rm -f /tmp/retract-verify.$$
}

# The .env names the Bedrock key pair RUNTIME_AWS_* so that loading it cannot
# clobber a shell's real AWS credentials. boto3 only reads the unprefixed names,
# so map them here rather than making every caller remember to.
: "${AWS_ACCESS_KEY_ID:=${RUNTIME_AWS_ACCESS_KEY_ID:-}}"
: "${AWS_SECRET_ACCESS_KEY:=${RUNTIME_AWS_SECRET_ACCESS_KEY:-}}"
export AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY
export AWS_REGION="${AWS_REGION:-us-east-1}"

# Pin the embedder. Left unset, get_embedder() resolves to "auto", which prints
# one line about Bedrock being unavailable and then quietly uses the 384-dim
# local model -- against a VECTOR(512) column, so every write fails with a
# dimension error that reads like a bug in the engine. "bedrock" raises instead,
# which is the answer this script exists to get.
export RETRACT_EMBEDDER="${RETRACT_EMBEDDER:-bedrock}"

step "0. Credentials present"
missing=()
for v in CRDB_URL AWS_ACCESS_KEY_ID AWS_SECRET_ACCESS_KEY; do
  [ -n "${!v:-}" ] || missing+=("$v")
done
if [ ${#missing[@]} -gt 0 ]; then
  echo "   missing: ${missing[*]}"
  echo "   Everything below needs these. Load the .env and re-run."
  exit 1
fi
ok "CRDB_URL + AWS set"
[ -n "${CRDB_API_KEY:-}" ] && [ -n "${CRDB_CLUSTER_ID:-}" ] \
  && ok "MCP credentials set" || meh "CRDB_API_KEY / CRDB_CLUSTER_ID unset -- mcp_eval will skip"

step "1. Cluster reachable, and is it the Cloud one"
run "connect + identify" uv run python experiments/crdb.py -c \
  "SELECT current_database(), version();"

step "2. schema_v3 migration (compensated status + compensated_by column)"
if [ "${APPLY_SCHEMA:-0}" = "1" ]; then
  run "apply schema_v3.sql" uv run python experiments/crdb.py -f schema_v3.sql
else
  meh "not applied. Re-run with APPLY_SCHEMA=1, or: uv run python experiments/crdb.py -f schema_v3.sql"
fi
# --expect-rows 1 is what makes this a check. Without it the step passed when
# the column was absent: information_schema returns nothing, the query executes
# fine, and exit status says nothing about the answer.
run "compensated_by column exists" uv run python experiments/crdb.py --expect-rows 1 -c \
  "SELECT column_name FROM information_schema.columns
    WHERE table_name='effect' AND column_name='compensated_by';"

step "3. The pitch: a retraction reverses the money"
run "compensate_eval (incl. no-handler control)" uv run python experiments/compensate_eval.py
run "cascade" uv run python experiments/cascade.py

step "4. Everything PR #2 touched that could have regressed"
# The `bucket` column was removed from the schema but left in three INSERT
# paths, so every write failed on a clean load. These are the three.
run "race" uv run python experiments/race.py --mode retract --agents 8
run "mcp_eval (nine refused write payloads)" uv run python experiments/mcp_eval.py

step "5. Tenancy -- needs no credentials, run it anyway"
run "scope_eval (6 attacks, control arm)" uv run python experiments/scope_eval.py

step "6. The ledger claim, read back from the live cluster"
# The Day-2 check in PLAN.md is 'a real reversal lands in the ledger with its
# own id'. This is that sentence as SQL.
#
# The previous form listed anything with a compensated_by or a `comp:` key and
# exited 0 whatever came back -- including nothing at all. It printed the right
# rows on a cluster that had them and passed identically on one that did not,
# which is the definition of a check that is not one.
#
# This form returns a row only when the whole claim holds, so an empty result
# is a failure rather than a quiet pass:
#   - the original is `compensated` and points at a reversal that exists
#   - the reversal executed
#   - the two idempotency keys DIFFER: sharing one would make it a replay of
#     the original effect, not a reversal of it
#   - the reversal's key is derived as `comp:<original>`, which is the UNIQUE
#     constraint doing the exactly-once work
run "reversal rows exist and are distinct" uv run python experiments/crdb.py --min-rows 1 -c \
  "SELECT orig.id, orig.idempotency_key, orig.status,
          rev.id,  rev.idempotency_key,  rev.status
     FROM effect orig JOIN effect rev ON orig.compensated_by = rev.id
    WHERE orig.status = 'compensated'
      AND rev.status  = 'executed'
      AND rev.idempotency_key <> orig.idempotency_key
      AND rev.idempotency_key = 'comp:' || orig.idempotency_key
    ORDER BY rev.created_at DESC LIMIT 10;"

printf '\n\033[1m%d passed · %d failed · %d skipped\033[0m\n' "$pass" "$fail" "$skip"
if [ "$fail" -gt 0 ]; then
  echo "Do not merge #2 on this result."
  exit 1
fi
if [ "${APPLY_SCHEMA:-0}" != "1" ]; then
  echo "Green, but the migration was skipped -- so step 3 ran against whatever"
  echo "schema was already live. Re-run with APPLY_SCHEMA=1 before merging."
  exit 2
fi
echo "PR #2 verified against the live cluster. Merge is defensible."
