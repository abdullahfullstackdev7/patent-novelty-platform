"""HTTP hardening: security headers, request size limit and rate limiting."""

from __future__ import annotations

from limits import parse as parse_limit
from limits.storage import MemoryStorage
from limits.strategies import MovingWindowRateLimiter
from slowapi import Limiter
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.config import get_settings

API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"
# Swagger UI loads its assets from a CDN, so documentation paths get a wider policy.
DOCS_CSP = (
    "default-src 'none'; img-src 'self' data: https://fastapi.tiangolo.com; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; connect-src 'self'; "
    "frame-ancestors 'none'; base-uri 'none'"
)
DOCS_PATHS = ("/docs", "/redoc", "/openapi.json")

STATIC_HEADERS = {
    "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
}


def security_headers(path: str) -> dict[str, str]:
    """The header set for a response to `path`."""
    headers = {
        **STATIC_HEADERS,
        "Content-Security-Policy": DOCS_CSP if path.startswith(DOCS_PATHS) else API_CSP,
    }
    if path.startswith("/api"):
        headers["Cache-Control"] = "no-store"
    return headers


class SecurityHeadersMiddleware:
    """Adds the standard response headers to every response, including errors."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope["path"]
        extra = security_headers(path)

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                present = {name.lower() for name, _ in headers}
                for name, value in extra.items():
                    if name.lower().encode() not in present:
                        headers.append((name.lower().encode(), value.encode()))
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


class BodyLimitMiddleware:
    """Rejects requests whose declared Content-Length exceeds the limit with 413."""

    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            for name, value in scope["headers"]:
                if name == b"content-length":
                    try:
                        too_big = int(value) > self.max_bytes
                    except ValueError:
                        too_big = True
                    if too_big:
                        response = JSONResponse(
                            {"detail": "Request body too large"}, status_code=413
                        )
                        await response(scope, receive, send)
                        return
        await self.app(scope, receive, send)


def client_ip(request: Request) -> str:
    """Caller address. Forwarded headers are trusted only behind a configured proxy."""
    if get_settings().trust_proxy_headers:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


# Decorator-based limits for the stricter groups (auth, LLM). The default limit for every
# other route is DefaultRateLimitMiddleware, which does not depend on route introspection.
limiter = Limiter(key_func=client_ip)


class DefaultRateLimitMiddleware:
    """Per-client moving-window limit applied to every HTTP request (RATE_LIMIT_DEFAULT)."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app
        self._strategy = MovingWindowRateLimiter(MemoryStorage())

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        item = parse_limit(get_settings().rate_limit_default)
        key = client_ip(Request(scope))
        if not self._strategy.hit(item, "default", key):
            response = JSONResponse(
                {"detail": "Rate limit exceeded"},
                status_code=429,
                headers={"Retry-After": str(item.get_expiry())},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)


def auth_limit() -> str:
    return get_settings().rate_limit_auth


def llm_limit() -> str:
    return get_settings().rate_limit_llm
