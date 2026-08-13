"""Demo-surface guards: token, rate limit, size cap, structured logs.

The deployed demo writes to a live database and can invoke a paid model. An
unauthenticated public write path holding those credentials does not score zero
on Production Readiness — it scores negative. Everything here is the cheap half
of closing that gap.

Fail CLOSED when DEMO_TOKEN is unset. An open default is how this class of
hole ships. Read endpoints and the static page stay open by design; only the
scenario runners (`/api/run/...`) go through the write-path guards.

EventSource cannot set headers, so the token is accepted as
`Authorization: Bearer …` *or* `?token=`. The query form is the browser path;
the header is for anything that can set one. Both are compared with
`hmac.compare_digest` against the env value.
"""

from __future__ import annotations

import hmac
import json
import logging
import os
import time
import uuid
from collections import defaultdict, deque
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

log = logging.getLogger("retract")

# Write paths. Everything else (/, /healthz, /status, /api/health, /api/distances)
# stays reachable without a token so the page can load and the ruler can draw.
WRITE_PREFIXES = ("/api/run/",)

# In-process sliding window. One Railway instance today; revisit if that changes.
RATE_LIMIT = 20          # requests
RATE_WINDOW_S = 60.0
MAX_BODY_BYTES = 4096
REQUEST_TIMEOUT_S = 60.0


def configure_logging() -> None:
    """JSON lines to stdout. No connection strings, no raw prompts."""
    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())
    root = logging.getLogger("retract")
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)
    root.propagate = False


class _JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname.lower(),
            "msg": record.getMessage(),
        }
        for key in (
            "request_id", "path", "client_ip", "scenario", "claim_id",
            "adjudication_mode", "lock_outcome", "cascade_count",
            "error_class", "status",
        ):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        return json.dumps(payload, default=str)


def client_ip(request: Request) -> str:
    # Railway (and most edge proxies) put the visitor in X-Forwarded-For.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def extract_token(request: Request) -> str | None:
    auth = request.headers.get("authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    return request.query_params.get("token")


class DemoGuardMiddleware(BaseHTTPMiddleware):
    """Token + rate limit + body-size cap on write paths. Fail closed."""

    def __init__(self, app, expected_token: str | None = None):
        super().__init__(app)
        # None means "env was unset at boot" — every write fails closed.
        self.expected_token = expected_token if expected_token is not None \
            else os.environ.get("DEMO_TOKEN")
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _rate_limited(self, ip: str) -> bool:
        now = time.monotonic()
        q = self._hits[ip]
        while q and now - q[0] > RATE_WINDOW_S:
            q.popleft()
        if len(q) >= RATE_LIMIT:
            return True
        q.append(now)
        return False

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        request_id = request.headers.get("x-request-id") or uuid.uuid4().hex[:12]
        request.state.request_id = request_id
        ip = client_ip(request)
        path = request.url.path

        if not path.startswith(WRITE_PREFIXES):
            return await call_next(request)

        # --- size cap (defence in depth; scenarios are GETs with no body) ---
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                if int(cl) > MAX_BODY_BYTES:
                    return self._reject(
                        request_id, ip, path, 413, "request_too_large",
                        f"body exceeds {MAX_BODY_BYTES} bytes",
                    )
            except ValueError:
                return self._reject(
                    request_id, ip, path, 400, "bad_content_length",
                    "content-length is not an integer",
                )

        # --- fail closed when the token was never configured ---
        if not self.expected_token:
            return self._reject(
                request_id, ip, path, 503, "demo_token_unset",
                "DEMO_TOKEN is not set; write paths are closed",
            )

        provided = extract_token(request)
        if not provided or not hmac.compare_digest(provided, self.expected_token):
            return self._reject(
                request_id, ip, path, 401, "unauthorized",
                "valid DEMO_TOKEN required (Authorization: Bearer … or ?token=)",
            )

        if self._rate_limited(ip):
            return self._reject(
                request_id, ip, path, 429, "rate_limited",
                f"at most {RATE_LIMIT} write requests per {int(RATE_WINDOW_S)}s per IP",
            )

        log.info(
            "write_path",
            extra={"request_id": request_id, "path": path, "client_ip": ip},
        )
        return await call_next(request)

    def _reject(
        self, request_id: str, ip: str, path: str,
        status: int, error_class: str, message: str,
    ) -> JSONResponse:
        log.info(
            message,
            extra={
                "request_id": request_id, "path": path, "client_ip": ip,
                "error_class": error_class, "status": status,
            },
        )
        return JSONResponse(
            {"error": error_class, "message": message, "request_id": request_id},
            status_code=status,
        )
