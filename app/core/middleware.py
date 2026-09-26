import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.core.config import settings

logger = logging.getLogger("dhandas.request")


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Adds a request-id, logs method/path/status/duration for every request.
    One place for access logs instead of scattering print()/logger calls
    through every endpoint."""

    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id", str(uuid.uuid4()))
        start = time.perf_counter()
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.exception(
                "request_failed method=%s path=%s duration_ms=%.1f request_id=%s",
                request.method, request.url.path, duration_ms, request_id,
            )
            raise
        duration_ms = (time.perf_counter() - start) * 1000
        response.headers["x-request-id"] = request_id
        logger.info(
            "request method=%s path=%s status=%s duration_ms=%.1f request_id=%s user_ip=%s",
            request.method, request.url.path, response.status_code, duration_ms,
            request_id, request.client.host if request.client else "-",
        )
        return response


class SimpleRateLimiter:
    """In-memory sliding-window limiter for sensitive auth endpoints
    (login/register/invite-accept). Good enough for a single-process
    deployment; swap for Redis in a multi-worker/multi-node deploy."""

    def __init__(self, max_attempts: int = 10, window_seconds: int = 60):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._hits: dict[str, list[float]] = {}

    def check(self, key: str) -> bool:
        now = time.time()
        bucket = [t for t in self._hits.get(key, []) if now - t < self.window_seconds]
        bucket.append(now)
        self._hits[key] = bucket
        return len(bucket) <= self.max_attempts


login_rate_limiter = SimpleRateLimiter(
    max_attempts=settings.login_rate_limit_attempts,
    window_seconds=settings.login_rate_limit_window_seconds,
)
