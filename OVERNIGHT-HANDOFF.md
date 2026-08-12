# Overnight handoff — 13/14 Aug 2026

GitHub API blocked updating the PR description after the repo rename
(`morkeeth` → `Morkeeth`). This file is the authoritative status for
https://github.com/Morkeeth/retract/pull/2. Paste into the PR body if useful.
**Do not merge until Cloud `compensate_eval` is green.**

---

## What I built

### Task 1 — Execute a compensation *(primary)*
- `retract/compensate.py`: registry (`refund_issued → refund_reversed`, etc.),
  writes a new reversal row with idempotency key `comp:<original>`, moves
  original `needs_compensation → compensated`, records `compensated_by` in the
  same transaction. Unregistered tools stay flagged (`no_handler`).
- `schema.sql` + `schema_v3.sql` (ALTER path). **Apply v3 on the live DB first.**
- `experiments/compensate_eval.py` with control arm.
- Removed stale `bucket` INSERTs (schema dropped the column; writers had not).
- Story scenario calls `compensate()` so a deployed URL can show the reversal.
  Day 3 still owns a dedicated act-5 UI.

### Task 2 — Harden the public demo
- `app/middleware.py`: `DEMO_TOKEN` fail-closed, rate limit, size cap, timeout,
  JSON logs. Preset scenarios `/api/run/{race_naive|race_retract|story}`.
  Legacy write paths return 410. `SECURITY.md`.

### Task 3 — Reframe README around the return arc
- Leads with the refund that already moved. Layout matches the tree. Heuristic
  stand-in labelled. No “production-ready”. `FINDINGS.md` / `RELATED-WORK.md`
  untouched.

### Task 4
Not started, per brief.

---

## What I verified (local CRDB + `hash`; NOT Cloud)

| Check | Result |
|---|---|
| `compensate_eval.py` | ALL PASS 8/8 |
| `cascade.py` | ALL PASS 8/8 |
| `/api/run/story?token=…` | `compensated=1` + reversal id |
| `race_retract` / `race_naive` | 1/7/1 vs 8/8 |
| no token / token unset / legacy | 401 / 503 / 410 |

## What is unrun, and why
Live Cloud evals, Railway deploy, Bedrock/Claude, MCP nine-payload re-verify,
AWS escalation re-verify. No secrets in this environment. Not stubbed green.

## Judgement calls
1. Ran `compensate_eval` against **local** CRDB; labelled Cloud as unrun.
2. Fixed `bucket` INSERT bug (unnamed in brief; blocked all writes).
3. `schema_v3.sql` rather than editing `schema_v2.sql`.
4. Wired compensate into story for Day-2 URL check; Day 3 owns act-5 UI.
5. Did not gate `/api/distances` (brief scoped token to write paths).
6. No new dependencies.

## What I think is wrong with the plan
- Hardening + compensation share one deploy gate — merge both with `DEMO_TOKEN`
  set, or the open wallet stays open.
- `scope` still caller-supplied (Day 3 cut-if-long) — don’t cut it.
- `/api/distances` still burns the embedder ungated on every page load.
- `RELATED-WORK.md` still says reversal “in progress” — brief forbade editing;
  update that sentence after merge.
- Fail-closed `DEMO_TOKEN` bricks current write buttons until Railway env +
  redeploy — intentional.

## Morning checklist
1. Apply `schema_v3.sql` on Cloud DB.
2. Set `DEMO_TOKEN` on Railway; redeploy this branch.
3. Run `compensate_eval.py` against Cloud; paste output into README.
4. Fix the underclaiming RELATED-WORK sentence.
5. Submit Anthropic use-case form.
6. Do not merge until (3) is green — local hash ≠ Cloud Titan.
