from __future__ import annotations

import time
from contextlib import asynccontextmanager
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
try:
    from slowapi import Limiter
    from slowapi.errors import RateLimitExceeded
    from slowapi.middleware import SlowAPIMiddleware
    from slowapi.util import get_remote_address
except Exception:  # pragma: no cover
    Limiter = None  # type: ignore
    RateLimitExceeded = Exception  # type: ignore
    SlowAPIMiddleware = None  # type: ignore
    get_remote_address = None  # type: ignore

from app.api.v1 import ai, alerts, analytics, auth, demo, federated, reports, transactions
from app.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.neo4j_client import Neo4jClient
from app.db.postgres_client import PostgresClient

log = get_logger(component="app")


limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"]) if Limiter else None


async def startup_event(app: FastAPI) -> None:
    configure_logging(settings.log_level)
    log.info("startup", env=settings.app_env)

    app.state.pg = PostgresClient(settings.postgres_url)
    await app.state.pg.connect()

    app.state.neo4j = Neo4jClient(settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password)
    try:
        await app.state.neo4j.initialize_schema()
    except Exception:
        # schema initialization may fail if db isn't ready yet; app still runs
        log.exception("neo4j_schema_init_failed")

    try:
        import redis.asyncio as redis  # type: ignore

        app.state.redis = redis.from_url(settings.redis_url, decode_responses=True)
        await app.state.redis.ping()
    except Exception:
        app.state.redis = None
        log.exception("redis_init_failed")

    app.state.model = None


async def shutdown_event(app: FastAPI) -> None:
    log.info("shutdown")
    if getattr(app.state, "redis", None) is not None:
        await app.state.redis.close()
    if getattr(app.state, "neo4j", None) is not None:
        await app.state.neo4j.close()
    if getattr(app.state, "pg", None) is not None:
        await app.state.pg.close()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await startup_event(app)
    yield
    await shutdown_event(app)


app = FastAPI(
    title="Nigeria AML Compliance Platform",
    description="AI-driven anti-money laundering system for Nigerian public sector",
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs" if settings.enable_swagger else None,
    redoc_url="/redoc" if settings.enable_swagger else None,
    openapi_url="/openapi.json" if settings.enable_swagger else None,
)

app.state.limiter = limiter
if SlowAPIMiddleware:
    app.add_middleware(SlowAPIMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


if limiter:
    @app.exception_handler(RateLimitExceeded)  # type: ignore[misc]
    async def ratelimit_handler(request: Request, exc: RateLimitExceeded):  # type: ignore[valid-type]
        return JSONResponse(status_code=429, content={"detail": "Rate limit exceeded"})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    log.exception("unhandled_exception")
    return JSONResponse(status_code=500, content={"detail": "Internal server error"})


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next: Callable):
    start = time.time()
    response = await call_next(request)
    elapsed_ms = int((time.time() - start) * 1000)
    log.info(
        "request",
        method=request.method,
        path=str(request.url.path),
        status_code=response.status_code,
        elapsed_ms=elapsed_ms,
    )
    return response


@app.get("/health")
async def health(request: Request) -> dict[str, Any]:
    return {"status": "ok"}


if limiter:
    health = limiter.limit("60/minute")(health)  # type: ignore[assignment]


app.include_router(auth.router, prefix="/api/v1", tags=["auth"])
app.include_router(transactions.router, prefix="/api/v1", tags=["transactions"])
app.include_router(alerts.router, prefix="/api/v1", tags=["alerts"])
app.include_router(reports.router, prefix="/api/v1", tags=["reports"])
app.include_router(analytics.router, prefix="/api/v1", tags=["analytics"])
app.include_router(federated.router, prefix="/api/v1", tags=["federated"])
app.include_router(ai.router, prefix="/api/v1", tags=["ai"])
app.include_router(demo.router, prefix="/api/v1", tags=["demo"])

