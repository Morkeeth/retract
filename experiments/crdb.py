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
    if len(sys.argv) < 3 or sys.argv[1] not in ("-c", "-f"):
        print("usage: crdb.py -c <statement> | -f <file>", file=sys.stderr)
        return 2

    url = os.environ.get("CRDB_URL")
    if not url:
        print("CRDB_URL is unset", file=sys.stderr)
        return 1

    flag, arg = sys.argv[1], sys.argv[2]
    sql = open(arg).read() if flag == "-f" else arg

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
                for row in cur.fetchall():
                    print("\t".join("" if v is None else str(v) for v in row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
