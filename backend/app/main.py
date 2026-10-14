"""FastAPI application factory."""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from sqlalchemy.orm import Session, sessionmaker

from app.api.v1.router import api_router
from app.config import Settings, get_settings
from app.db.session import make_engine, make_session_factory
from app.llm.factory import build_gateway
from app.security.http import (
    BodyLimitMiddleware,
    DefaultRateLimitMiddleware,
    SecurityHeadersMiddleware,
    limiter,
    security_headers,
)
from app.security.redaction import install_log_redaction

logger = logging.getLogger("priorart")


async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    """422 without echoing the submitted values, which can contain passwords or disclosure text."""
    errors = [
        {"loc": list(e.get("loc", [])), "msg": e.get("msg", ""), "type": e.get("type", "")}
        for e in exc.errors()
    ]
    return JSONResponse({"detail": errors}, status_code=422)


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.error(
        "unhandled error on %s %s: %s", request.method, request.url.path, type(exc).__name__
    )
    return JSONResponse(
        {"detail": "Internal server error"},
        status_code=500,
        headers=security_headers(request.url.path),
    )


def create_app(
    settings: Settings | None = None,
    session_factory: sessionmaker[Session] | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    settings.validate_runtime()
    install_log_redaction()

    app = FastAPI(
        title="PriorArt Atlas API",
        version="0.3.0",
        docs_url="/docs" if settings.docs_enabled else None,
        redoc_url="/redoc" if settings.docs_enabled else None,
        openapi_url="/openapi.json" if settings.docs_enabled else None,
    )
    app.state.settings = settings
    app.state.session_factory = session_factory or make_session_factory(
        make_engine(settings.database_url)
    )
    app.state.limiter = limiter
    app.state.llm_gateway = build_gateway(settings, app.state.session_factory)

    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    # Last added runs first: headers wrap everything, including CORS preflight and 4xx/5xx.
    app.add_middleware(DefaultRateLimitMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
        max_age=600,
    )
    app.add_middleware(BodyLimitMiddleware, max_bytes=settings.max_body_bytes)
    app.add_middleware(SecurityHeadersMiddleware)

    app.include_router(api_router)
    return app
