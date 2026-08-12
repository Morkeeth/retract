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

COPY retract/ ./retract/
COPY app/ ./app/
COPY schema.sql schema_v2.sql ./

# Non-root. The container holds a live database connection and a Bedrock path;
# there is no reason for it to be able to write to its own filesystem either.
RUN useradd --system --uid 10001 retract \
 && chown -R retract:retract /app
USER retract

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://localhost:8080/healthz || exit 1

CMD ["uv", "run", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
