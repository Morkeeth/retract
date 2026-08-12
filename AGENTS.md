# AGENTS.md

## Cursor Cloud specific instructions

RETRACT is a single Python 3.13 product managed with `uv`: a FastAPI demo surface
(`app/main.py`) over a memory engine (`retract/`) backed by **CockroachDB**. See
`README.md` for the product overview and `DEMO.md` for the intended demo flow.

### Provided by the update script + VM snapshot
- `uv` and the project venv. The update script runs `uv sync` (base deps only).
  For the offline `local` embedder run `uv sync --extra local` (pulls torch; large).
- CockroachDB **v25.4.0** is installed at `/usr/local/bin/cockroach`. Its `VECTOR`
  column + vector-index support is **required** — plain PostgreSQL will not work.
  It is **not** started automatically.

### Start the database (required; do this every fresh boot)
The app and every eval read `CRDB_URL` **at import time**, so it must be exported
before running them:
```
cockroach start-single-node --insecure --listen-addr=localhost:26257 \
  --http-addr=localhost:8080 --store="$HOME/crdb-data" --background
export CRDB_URL='postgresql://root@localhost:26257/defaultdb?sslmode=disable'
```
Vector indexing works out of the box — no cluster setting needed. The
`$HOME/crdb-data` store persists in the snapshot with the schema already loaded.
On a genuinely fresh store, load it once with the loader shown in `README.md`
(`schema.sql` then `schema_v2.sql`).

### Run the app / evals (dev mode)
- App: `uv run uvicorn app.main:app --port 8117` (set `RETRACT_EMBEDDER` /
  `RETRACT_ADJUDICATOR`). `/healthz` is liveness only; `/status` and `/api/health`
  report DB + live backends. First page load warms the embedder (~seconds).
- Evals: `uv run python experiments/race.py --mode retract|naive`,
  `experiments/cascade.py`, etc. (see `README.md`).

### Backends — no AWS needed for local dev
- `RETRACT_ADJUDICATOR=heuristic` — offline stand-in, zero deps.
- The embedder used for **any DB write** MUST be 512-dim to match
  `memory.embedding VECTOR(512)`: use `RETRACT_EMBEDDER=hash` (offline,
  semantics-free — fine for exercising the engine/plumbing) or `bedrock` (needs
  AWS creds). `RETRACT_EMBEDDER=local` is all-MiniLM at **384 dims** and is only
  safe for non-DB paths such as `/api/distances`; it cannot be inserted into the
  512-dim schema.
- AWS Bedrock (Titan + Claude) is the "real" production path and is optional
  (needs AWS credentials + `AWS_REGION`). The Cloud Managed MCP eval
  (`experiments/mcp_eval.py`) needs a CockroachDB Cloud service account and is
  optional.

### KNOWN pre-existing repo bug (blocks the DB write path on a clean schema)
`schema.sql` no longer defines a `bucket` column on `memory` (removed together
with the v1 LSH design), but `retract/engine.py`, `app/main.py`, and
`experiments/race.py` still run `INSERT INTO memory (... bucket ...)`. On a
freshly loaded schema every write therefore raises
`column "bucket" does not exist`. `PLAN.md` lists this — plus a stale 384-dim
import in `experiments/cascade.py` — as pending Day-1 cleanup. Until the code and
schema are reconciled, the write path (race / story / naive) only runs if the DB
has a `bucket` column. The snapshot's `crdb-data` store already has a
`bucket INT8 DEFAULT 0` column added at setup time so the demo runs, but the
repo is unchanged, so a `git`-tracked schema reload reproduces the bug. The read
premise (`/api/distances`, embedding-distance evals) is unaffected.
