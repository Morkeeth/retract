# Security posture

Honest in both directions. This is a hackathon demo with a live database behind
it, not a multi-tenant product. What follows is what is proven, what is demo
scaffolding, and what is still open.

## Proven

- **MCP writes refused across nine escalating payloads.**
  `experiments/mcp_eval.py` fires plain DML, stacked statements, a CTE-wrapped
  DELETE, and comment- / newline-obscured payloads at the CockroachDB Cloud
  Managed MCP `select_query` tool. All nine were refused, and the memory was
  re-read afterwards to confirm nothing changed. The true claim is precise: the
  endpoint's read tool validates the statement and rejects non-SELECT; the
  claim-key lock (`SELECT … FOR UPDATE` inside a multi-statement serializable
  transaction) cannot be expressed through MCP, so writes never route there.
  MCP does expose other tools (`create_table`, `insert_rows`); those are out of
  the agents' governed read path by construction, not by wishing.
  *Verified by the owner on Day 1 against the live Cloud endpoint. Not
  re-run in the overnight environment (no Cloud credentials).*

- **Serializable commit with a durable lock row.** The claim lock is taken
  inside the short COMMIT transaction with
  `enable_durable_locking_for_serializable = true`, because unreplicated
  `FOR UPDATE` locks are documented as best-effort. A crash mid-hold aborts the
  transaction and frees the key — there is no lease and no TTL wedge.
  `experiments/race.py` is the control: same cluster, same table, same
  embeddings, eight concurrent writers; naive (no lock) lands on 8 beliefs,
  RETRACT lands on 1.
  *Race numbers are the owner's against Cloud; overnight verified the same
  shape against a local single-node store with `RETRACT_EMBEDDER=hash`.*

- **Compensation ledger closes the loop.** An executed effect flagged
  `needs_compensation` can be reversed: a new effect row is written with
  idempotency key `comp:<original>`, the original moves to `compensated`, and
  `compensated_by` records the reversal id — all in one transaction. A tool
  with no registered handler stays `needs_compensation`. Replay produces one
  reversal, not two (`experiments/compensate_eval.py`).
  *Offline-verified against local CockroachDB. Unrun against the live Cloud
  cluster (no credentials overnight).*

- **AWS credential scoped to two model ARNs.** The host credential can call
  `bedrock:InvokeModel` on the Titan embeddings ARN and the Claude inference
  profile ARN, and nothing else. Five escalation paths were verified blocked
  on Day 1.
  *Owner's Day-1 result. Not re-verified overnight (no AWS credentials).*

## Demo scaffolding (not product security)

- **Single tenant.** `scope` is a caller-supplied string. Nothing enforces that
  one agent cannot pass another fleet's scope. For a pitch about *governed*
  shared memory this is the first Production Readiness question; it is a known
  gap, scheduled after the film ending, and cuttable if Friday runs long.
- **Disposable data.** Demo scenarios write into fresh random scopes and do not
  touch anyone's production records. The database is still a real Cloud
  cluster — disposable is about the data, not the blast radius of the
  credential.
- **Shared demo token, not real authn.** Write paths (`/api/run/{scenario}`)
  require `DEMO_TOKEN` via `Authorization: Bearer …` or `?token=`. When the
  env var is unset the write paths fail **closed**. This stops anonymous spend
  and anonymous writes; it is not user identity, MFA, or per-tenant auth.
- **Preset scenarios only.** Three server-side IDs — `race_naive`,
  `race_retract`, `story`. No request text reaches an embedding or a model
  call. That removes prompt injection into a paid path as a category and bounds
  write-path spend by construction.
- **In-process rate limit.** 20 write requests / 60s / IP, plus a 4 KiB body
  cap and a 60s per-request timeout. Adequate for one Railway instance; not a
  distributed limiter.

## Open / residual risk

- **`/api/distances` is ungated and invokes the embedder on every page load.**
  Pairs are server-side constants (no injection), but Bedrock spend is not
  zero. Caching or a soft gate belongs with the next hardening pass.
- **The static page holds the demo token in `sessionStorage`.** Anyone with
  the token can run the three scenarios. Rotate it if it leaks; do not reuse it
  as anything else.
- **Structured logs go to stdout as JSON.** Fields: request id, path, scenario,
  adjudication mode, lock outcome, cascade count, error class. Connection
  strings and raw prompts are never logged. Confirm the host's log drain does
  not retain them longer than needed. The `path` field is `request.url.path`,
  which excludes the query string — see the entry below for why that mattered
  and was not sufficient on its own.
- **The demo token was written to the host's logs on every run — fixed as of
  14 Aug.** This entry stays because the token that shipped before the fix has
  to be treated as exposed. EventSource cannot set a header, so the token
  travels as `?token=`, and uvicorn's own access logger prints the full request
  line. The structured logger above was clean; it was simply not the only
  logger. Probed against the deployed container with a canary value:

      INFO: 100.64.0.3:60452 - "GET /api/run/story?token=CANARY-73baafb7 HTTP/1.1" 401

  The container now starts with `--no-access-log` (Dockerfile), leaving the
  structured logger as the only request record. **Rotate `DEMO_TOKEN` before
  the demo URL is shared and again after any recording is published**: any
  token used before this fix is in the host's retention, and a token that
  appears in a video frame or a log line is spent.
