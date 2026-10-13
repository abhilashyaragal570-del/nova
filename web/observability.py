"""Request IDs and one JSON log line per request.

RequestLogMiddleware wraps the whole app, including the mounted Flask pages.
It gives every response an X-Request-ID header (a safe ID from the caller is
kept, otherwise a new one is made) and writes one JSON line to stdout when the
response has finished, so a streamed reply is timed to its last byte.

A line holds only: time, request_id, method, path, status and duration_ms. It
never holds headers, the password, query strings or message text. The page's
own polling of /approvals and /workflows/current is skipped unless it fails.
"""
import json
import logging
import re
import sys
import time
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone

HEADER = "x-request-id"
_SAFE_ID = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

# Routes the web page calls every second or so. Logging them would bury
# everything else, so they are only logged when they fail.
QUIET_ROUTES = {("GET", "/approvals"), ("GET", "/workflows/current")}

# The ID of the request being handled, for code that wants to include it.
request_id_var: ContextVar = ContextVar("request_id", default=None)

access_logger = logging.getLogger("nova.access")


class _StdoutHandler(logging.Handler):
    """Print each line to whatever sys.stdout is when the line is written."""

    def emit(self, record):
        try:
            print(self.format(record), file=sys.stdout, flush=True)
        except Exception:
            self.handleError(record)


def setup_access_log() -> None:
    """Send the access log to stdout, once. Safe to call again."""
    if any(isinstance(h, _StdoutHandler) for h in access_logger.handlers):
        return
    handler = _StdoutHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    access_logger.addHandler(handler)
    access_logger.setLevel(logging.INFO)
    access_logger.propagate = False


def _incoming_id(scope) -> str | None:
    for name, value in scope.get("headers", []):
        if name.lower() == HEADER.encode():
            try:
                text = value.decode("ascii")
            except UnicodeDecodeError:
                return None
            return text if _SAFE_ID.match(text) else None
    return None


class RequestLogMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request_id = _incoming_id(scope) or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        started = time.perf_counter()
        status = {"code": 500}

        async def send_with_id(message):
            if message["type"] == "http.response.start":
                status["code"] = message["status"]
                headers = [
                    h
                    for h in message.get("headers", [])
                    if h[0].lower() != HEADER.encode()
                ]
                headers.append((HEADER.encode(), request_id.encode()))
                message = {**message, "headers": headers}
            await send(message)

        try:
            await self.app(scope, receive, send_with_id)
        finally:
            method = scope.get("method", "")
            path = scope.get("path", "")
            code = status["code"]
            if (method, path) not in QUIET_ROUTES or code >= 400:
                access_logger.info(
                    json.dumps(
                        {
                            "time": datetime.now(timezone.utc).isoformat(
                                timespec="seconds"
                            ),
                            "request_id": request_id,
                            "method": method,
                            "path": path,
                            "status": code,
                            "duration_ms": round(
                                (time.perf_counter() - started) * 1000, 1
                            ),
                        }
                    )
                )
            request_id_var.reset(token)