from __future__ import annotations

import asyncio
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

from app.api.v1 import (
    admin_red_flags,
    admin_reference_lists,
    admin_reporting_config,
    admin_retention,
    ai,
    alerts,
    analytics,
    audit,
    auth,
    closed_case_reviews,
    compliance,
    customers,
    demo,
    federated,
    ftr_reports,
    lea,
    legal_hold_ndpa,
    mi_executive_reports,
    reports,
    transactions,
)
from app.config import settings
from app.core.logging import configure_logging, get_logger
from app.db.neo4j_client import Neo4jClient
from app.db.postgres_client import PostgresClient
from app.services.aop_upload_db import ensure_aml_customer_aop_upload_table
from app.services.audit_trail import configure_from_settings, shutdown_audit_storage
from app.services.audit_events_schema import ensure_audit_events_schema
from app.services.customer_kyc_db import ensure_aml_customer_kyc_table
from app.services.customer_risk_review_db import ensure_customer_risk_review_schema
from app.services.closed_case_reviews_db import ensure_closed_case_reviews_schema
from app.services.ftr_reports_db import ensure_ftr_reports_schema
from app.services.retention_policies_db import ensure_retention_schema
from app.services.mi_report_schedules_db import ensure_mi_schedule_schema
from app.services.reference_lists_db import ensure_reference_lists_schema
from app.services.red_flag_ai_observations_db import ensure_red_flag_ai_observations_schema
from app.services.red_flag_rules_db import ensure_red_flag_rules_schema
from app.services.reporting_profile_db import ensure_reporting_profile_schema

log = get_logger(component="app")


limiter = Limiter(key_func=get_remote_address, default_limits=["120/minute"]) if Limiter else None


async def startup_event(app: FastAPI) -> None:
    configure_logging(settings.log_level)
    log.info("startup", env=settings.app_env)

    app.state.pg = PostgresClient(settings.postgres_url)
    await app.state.pg.connect()
    try:
        await ensure_aml_customer_kyc_table(app.state.pg)
    except Exception:
        log.exception("aml_customer_kyc_schema_failed")
    try:
        await ensure_customer_risk_review_schema(app.state.pg)
    except Exception:
        log.exception("aml_customer_risk_review_schema_failed")
    try:
        await ensure_retention_schema(app.state.pg)
    except Exception:
        log.exception("retention_schema_failed")
    try:
        await ensure_aml_customer_aop_upload_table(app.state.pg)
    except Exception:
        log.exception("aml_customer_aop_upload_schema_failed")
    try:
        await ensure_audit_events_schema(app.state.pg)
    except Exception:
        log.exception("aml_audit_trail_schema_failed")
    try:
        await ensure_ftr_reports_schema(app.state.pg)
    except Exception:
        log.exception("ftr_reports_schema_failed")
    try:
        await ensure_closed_case_reviews_schema(app.state.pg)
    except Exception:
        log.exception("closed_case_reviews_schema_failed")
    try:
        await ensure_mi_schedule_schema(app.state.pg)
    except Exception:
        log.exception("mi_schedule_schema_failed")
    try:
        await ensure_reporting_profile_schema(app.state.pg)
    except Exception:
        log.exception("reporting_profile_schema_failed")
    try:
        await ensure_reference_lists_schema(app.state.pg)
    except Exception:
        log.exception("reference_lists_schema_failed")
    try:
        await ensure_red_flag_rules_schema(app.state.pg)
    except Exception:
        log.exception("red_flag_rules_schema_failed")
    try:
        await ensure_red_flag_ai_observations_schema(app.state.pg)
    except Exception:
        log.exception("red_flag_ai_observations_schema_failed")
    try:
        from app.services.reference_lists_service import load_from_database

        await load_from_database(app.state.pg)
    except Exception:
        log.exception("reference_lists_load_failed")

    configure_from_settings()

    app.state._audit_retention_task = None
    if settings.audit_retention_days is not None and int(settings.audit_retention_days) > 0:

        async def _audit_retention_loop() -> None:
            from app.services import audit_trail as _at

            interval = max(1, int(settings.audit_retention_interval_hours)) * 3600
            while True:
                await asyncio.sleep(interval)
                try:
                    _at.run_retention_purge()
                except Exception:
                    log.exception("audit_retention_purge_failed")

        app.state._audit_retention_task = asyncio.create_task(_audit_retention_loop())

    app.state._ftr_scan_task = None

    async def _ftr_scan_loop() -> None:
        from app.api.v1.ftr_reports import run_scheduled_ftr_scan

        await asyncio.sleep(120)
        while True:
            try:
                await run_scheduled_ftr_scan(app, force=False)
            except Exception:
                log.exception("ftr_scheduled_scan_failed")
            h = max(1, int(settings.ftr_auto_scan_interval_hours))
            await asyncio.sleep(h * 3600)

    app.state._ftr_scan_task = asyncio.create_task(_ftr_scan_loop())

    async def _closed_case_review_monthly_loop() -> None:
        from app.api.v1.closed_case_reviews import run_monthly_closed_case_review_if_due

        await asyncio.sleep(300)
        while True:
            try:
                await run_monthly_closed_case_review_if_due(app)
            except Exception:
                log.exception("closed_case_review_monthly_failed")
            await asyncio.sleep(6 * 3600)

    app.state._ccr_monthly_task = asyncio.create_task(_closed_case_review_monthly_loop())

    app.state._retention_embedded_task = None
    h = int(settings.retention_embedded_run_interval_hours or 0)
    if h > 0:

        async def _retention_embedded_loop() -> None:
            from app.services.retention_runner import run_retention_job

            interval = max(1, h) * 3600
            await asyncio.sleep(60)
            while True:
                try:
                    await run_retention_job(
                        app.state.pg,
                        include_memory=True,
                        grace_hard_purge_days=max(1, int(settings.retention_hard_purge_grace_days)),
                        actor_email="embedded@retention",
                    )
                except Exception:
                    log.exception("retention_embedded_run_failed")
                await asyncio.sleep(interval)

        app.state._retention_embedded_task = asyncio.create_task(_retention_embedded_loop())

    app.state._reference_lists_scan_task = None
    rl_h = int(settings.reference_lists_embedded_run_interval_hours or 0)
    if rl_h > 0:

        async def _reference_lists_scan_loop() -> None:
            from app.services.reference_lists_service import run_full_customer_screening_scan

            interval = max(1, rl_h) * 3600
            await asyncio.sleep(300)
            while True:
                try:
                    await run_full_customer_screening_scan(app.state.pg, persist=True)
                except Exception:
                    log.exception("reference_lists_scheduled_scan_failed")
                await asyncio.sleep(interval)

        app.state._reference_lists_scan_task = asyncio.create_task(_reference_lists_scan_loop())

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
    t = getattr(app.state, "_audit_retention_task", None)
    if t is not None:
        t.cancel()
        try:
            await t
        except asyncio.CancelledError:
            pass
        app.state._audit_retention_task = None
    ft = getattr(app.state, "_ftr_scan_task", None)
    if ft is not None:
        ft.cancel()
        try:
            await ft
        except asyncio.CancelledError:
            pass
        app.state._ftr_scan_task = None
    ccr = getattr(app.state, "_ccr_monthly_task", None)
    if ccr is not None:
        ccr.cancel()
        try:
            await ccr
        except asyncio.CancelledError:
            pass
        app.state._ccr_monthly_task = None
    rt = getattr(app.state, "_retention_embedded_task", None)
    if rt is not None:
        rt.cancel()
        try:
            await rt
        except asyncio.CancelledError:
            pass
        app.state._retention_embedded_task = None
    rls = getattr(app.state, "_reference_lists_scan_task", None)
    if rls is not None:
        rls.cancel()
        try:
            await rls
        except asyncio.CancelledError:
            pass
        app.state._reference_lists_scan_task = None
    shutdown_audit_storage()
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
app.include_router(customers.router, prefix="/api/v1", tags=["customers"])
app.include_router(compliance.router, prefix="/api/v1", tags=["compliance"])
app.include_router(legal_hold_ndpa.router, prefix="/api/v1", tags=["compliance"])
app.include_router(admin_retention.router, prefix="/api/v1", tags=["admin"])
app.include_router(admin_red_flags.router, prefix="/api/v1", tags=["admin"])
app.include_router(admin_reference_lists.router, prefix="/api/v1", tags=["admin"])
app.include_router(admin_reporting_config.router, prefix="/api/v1", tags=["admin"])
app.include_router(closed_case_reviews.router, prefix="/api/v1", tags=["compliance"])
app.include_router(alerts.router, prefix="/api/v1", tags=["alerts"])
app.include_router(lea.router, prefix="/api/v1", tags=["lea"])
app.include_router(reports.router, prefix="/api/v1", tags=["reports"])
app.include_router(mi_executive_reports.router, prefix="/api/v1", tags=["reports"])
app.include_router(ftr_reports.router, prefix="/api/v1", tags=["reports"])
app.include_router(analytics.router, prefix="/api/v1", tags=["analytics"])
app.include_router(federated.router, prefix="/api/v1", tags=["federated"])
app.include_router(ai.router, prefix="/api/v1", tags=["ai"])
app.include_router(demo.router, prefix="/api/v1", tags=["demo"])
app.include_router(audit.router, prefix="/api/v1", tags=["audit"])

