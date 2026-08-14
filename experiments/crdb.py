"""A psql stand-in, because this project does not actually require psql.

WHY THIS EXISTS
verify_live.sh was written to shell out to `psql`. On the machine that owns the
credentials, psql is not installed and libpq is not in Homebrew's Cellar, so
three of the script's steps -- including step 6, the ledger read that is the
whole Day-2 claim -- exited 127 and were counted as failures of the product.
A missing client binary is not evidence about the cluster.

psycopg is already a dependency (retract/engine.py imports it), so the driver
was present the whole time. This wraps it in the two flags verify_live.sh
actually used: -c for a statement, -f for a file.

    uv run python experiments/crdb.py -c "SELECT 1"
    uv run python experiments/crdb.py -f schema_v3.sql

Rows print tab-separated with no header, matching the `psql -tAc` form the
script's callers already parse. Exit status is 0 on success, 1 on a database
error, so `run` in verify_live.sh keeps working unchanged.

WHY EXIT STATUS ALONE WAS NOT ENOUGH
`run` in verify_live.sh grades a step by its exit status, and this file
originally exited 0 whenever the statements executed -- with no assertion about
what came back. A SELECT that matches nothing executes perfectly. That made two
of the eleven checks incapable of failing on a wrong answer:

  step 2  "compensated_by column exists"        passes if the column does not
  step 6  "reversal rows exist and are distinct"  passes against an empty ledger

Step 6 is the one the script's own comment calls the whole Day-2 claim, and it
returned PASS when that claim was false. Verified rather than reasoned: a query
for a column that does not exist, and a query for an idempotency key that was
never written, both exited 0 before this change.

--expect-rows N and --min-rows N close that. A check whose failure mode is
"returns nothing" needs a row count, or it is testing that the network is up.

    crdb.py -c "SELECT ..." --expect-rows 1   # exactly one row, or exit 1
    crdb.py -c "SELECT ..." --min-rows 1      # at least one row, or exit 1
"""

import os
import sys

import psycopg


def statements(sql: str) -> list[str]:
    """Split a file into statements, dropping whole-line comments first.

    Every statement in this project's migrations is a single-line DDL, so a
    naive split on ';' is correct here and stays readable. It would not be
    correct for a file containing a function body or a string with a semicolon
    in it; if one ever appears, this is the line that has to change.
    """
    body = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    return [s.strip() for s in body.split(";") if s.strip()]


def main() -> int:
    args = sys.argv[1:]
    expect_rows: int | None = None
    min_rows: int | None = None
    for flag in ("--expect-rows", "--min-rows"):
        if flag in args:
            i = args.index(flag)
            try:
                value = int(args[i + 1])
            except (IndexError, ValueError):
                print(f"{flag} needs an integer", file=sys.stderr)
                return 2
            if flag == "--expect-rows":
                expect_rows = value
            else:
                min_rows = value
            del args[i:i + 2]

    if len(args) < 2 or args[0] not in ("-c", "-f"):
        print("usage: crdb.py -c <statement> | -f <file> "
              "[--expect-rows N] [--min-rows N]", file=sys.stderr)
        return 2

    url = os.environ.get("CRDB_URL")
    if not url:
        print("CRDB_URL is unset", file=sys.stderr)
        return 1

    flag, arg = args[0], args[1]
    sql = open(arg).read() if flag == "-f" else arg

    # Counted across every statement that returned a result set, so a caller
    # passing one SELECT gets exactly what it expects and a caller passing a
    # file gets the total. Assertions are for the one-statement form.
    returned = 0

    # Autocommit: DDL in CockroachDB is transactional but a failed statement
    # inside an explicit transaction poisons every statement after it, which
    # would report one broken ALTER as eight.
    with psycopg.connect(url, autocommit=True) as conn:
        cur = conn.cursor()
        for stmt in statements(sql):
            try:
                cur.execute(stmt)
            except psycopg.Error as exc:
                print(f"{type(exc).__name__}: {exc}", file=sys.stderr)
                return 1
            if cur.description is not None:
                rows = cur.fetchall()
                returned += len(rows)
                for row in rows:
                    print("\t".join("" if v is None else str(v) for v in row))

    if expect_rows is not None and returned != expect_rows:
        print(f"expected exactly {expect_rows} row(s), got {returned}",
              file=sys.stderr)
        return 1
    if min_rows is not None and returned < min_rows:
        print(f"expected at least {min_rows} row(s), got {returned}",
              file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
