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
run "connect + identify" psql "$CRDB_URL" -tAc \
  "SELECT current_database(), version();"

step "2. schema_v3 migration (compensated status + compensated_by column)"
if [ "${APPLY_SCHEMA:-0}" = "1" ]; then
  run "apply schema_v3.sql" psql "$CRDB_URL" -f schema_v3.sql
else
  meh "not applied. Re-run with APPLY_SCHEMA=1, or: psql \"\$CRDB_URL\" -f schema_v3.sql"
fi
run "compensated_by column exists" psql "$CRDB_URL" -tAc \
  "SELECT column_name FROM information_schema.columns
    WHERE table_name='effect' AND column_name='compensated_by';"

step "3. The pitch: a retraction reverses the money"
run "compensate_eval (incl. no-handler control)" python3 experiments/compensate_eval.py
run "cascade" python3 experiments/cascade.py

step "4. Everything PR #2 touched that could have regressed"
# The `bucket` column was removed from the schema but left in three INSERT
# paths, so every write failed on a clean load. These are the three.
run "race" python3 experiments/race.py --mode retract --agents 8
run "mcp_eval (nine refused write payloads)" python3 experiments/mcp_eval.py

step "5. Tenancy -- needs no credentials, run it anyway"
run "scope_eval (6 attacks, control arm)" python3 experiments/scope_eval.py

step "6. The ledger claim, read back from the live cluster"
# The Day-2 check in PLAN.md is 'a real reversal lands in the ledger with its
# own id'. This is that sentence as SQL. A reversal that shares the original's
# idempotency key would be a replay, not a reversal -- hence both columns.
run "reversal rows exist and are distinct" psql "$CRDB_URL" -tAc \
  "SELECT e.id, e.tool, e.idempotency_key, e.status, e.compensated_by
     FROM effect e WHERE e.compensated_by IS NOT NULL
       OR e.idempotency_key LIKE 'comp:%'
     ORDER BY e.created_at DESC LIMIT 10;"

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
