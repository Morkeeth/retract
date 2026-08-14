# RETRACT demo surface.
#
# A container rather than a function: the app holds a warm psycopg pool and a
# long-lived connection to CockroachDB, and Lambda cold starts would make a
# judge's first click feel like a broken page.

FROM python:3.13-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    RETRACT_EMBEDDER=bedrock \
    RETRACT_ADJUDICATOR=bedrock \
    AWS_REGION=us-east-1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Dependencies first, so editing app code does not reinstall them.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# No local embedder in the image. sentence-transformers pulls torch -- ~2GB and
# minutes of build for a fallback the deployed demo never uses, because it runs
# on Bedrock. The tradeoff is explicit: if Bedrock is unavailable the deployed
# demo fails loudly rather than silently degrading to a different vector space,
# which would make every distance in the table incomparable.

# The cluster's CA. Public, not a secret -- the same file the README tells a
# reader to fetch. Baked in because libpq's verify-full otherwise looks for
# ~/.postgresql/root.crt, and sslrootcert=system does NOT work against this
# cluster (measured: certificate verify failed on all three endpoints).
ARG CRDB_CLUSTER_ID
RUN mkdir -p /app/certs \
 && curl -fsS -o /app/certs/root.crt \
    "https://cockroachlabs.cloud/clusters/${CRDB_CLUSTER_ID}/cert" \
 && chmod 644 /app/certs/root.crt

COPY retract/ ./retract/
COPY app/ ./app/
COPY schema.sql schema_v2.sql ./

# Non-root. The container holds a live database connection and a Bedrock path;
# there is no reason for it to be able to write to its own filesystem either.
# --create-home matters: a system user without one makes uv fail at startup
# trying to build a cache in a directory it cannot create.
RUN useradd --system --uid 10001 --create-home retract \
 && chown -R retract:retract /app

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://localhost:8080/healthz || exit 1

USER retract

# Call the venv binary directly rather than going through `uv run`. uv wants a
# writable cache on every invocation, which is pointless for an image whose
# dependencies are already frozen in /app/.venv.
#
# --no-access-log is a security fix, not tidiness. EventSource cannot set a
# header, so the demo token travels as `?token=` -- and uvicorn's access logger
# prints the whole request line, query string included. Probed against the
# deployed container on 14 Aug with a canary value:
#
#   INFO: 100.64.0.3:60452 - "GET /api/run/story?token=CANARY-73baafb7 HTTP/1.1" 401
#
# So every scenario run, including every run a judge makes and every take of
# the video, wrote the live DEMO_TOKEN into Railway's log retention. Nothing is
# lost by removing it: app/middleware.py already emits a structured line per
# write path and per rejection, and it logs `request.url.path`, which excludes
# the query string. That logger is the one SECURITY.md documents; this one was
# shadowing it with an unredacted copy.
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", \
     "--no-access-log"]
