"""Celery tasks — retention job triggers in-process API via HTTP (in-memory stores)."""

from __future__ import annotations

import os

import httpx

from app.celery_app import celery_app


@celery_app.task(name="app.celery_tasks.retention_run_now_http")
def retention_run_now_http() -> dict:
    """
    POST /api/v1/admin/retention/run-now with ``X-Retention-Internal-Key``.
    Set ``RETENTION_RUN_NOW_URL`` and ``RETENTION_INTERNAL_API_KEY`` in the worker environment.
    """
    url = (os.getenv("RETENTION_RUN_NOW_URL") or "").strip()
    key = (os.getenv("RETENTION_INTERNAL_API_KEY") or "").strip()
    if not url or not key:
        return {"skipped": True, "reason": "RETENTION_RUN_NOW_URL or RETENTION_INTERNAL_API_KEY unset"}
    with httpx.Client(timeout=120.0) as client:
        r = client.post(url, headers={"X-Retention-Internal-Key": key})
        r.raise_for_status()
        return r.json()


@celery_app.task(name="app.celery_tasks.reference_lists_run_now_http")
def reference_lists_run_now_http() -> dict:
    """
    POST /api/v1/admin/reference-lists/screening/run-now with ``X-Reference-Lists-Internal-Key``.
    Set ``REFERENCE_LISTS_RUN_NOW_URL`` and ``REFERENCE_LISTS_INTERNAL_API_KEY`` (or ``RETENTION_INTERNAL_API_KEY``).
    """
    url = (os.getenv("REFERENCE_LISTS_RUN_NOW_URL") or "").strip()
    key = (os.getenv("REFERENCE_LISTS_INTERNAL_API_KEY") or os.getenv("RETENTION_INTERNAL_API_KEY") or "").strip()
    if not url or not key:
        return {"skipped": True, "reason": "REFERENCE_LISTS_RUN_NOW_URL or internal API key unset"}
    with httpx.Client(timeout=600.0) as client:
        r = client.post(url, headers={"X-Reference-Lists-Internal-Key": key})
        r.raise_for_status()
        return r.json()


@celery_app.task(name="app.celery_tasks.mi_schedules_tick_http")
def mi_schedules_tick_http() -> dict:
    """
    POST /api/v1/reports/mi/tick-schedules with ``X-MI-Internal-Key``.
    Set ``MI_TICK_URL`` (or ``RETENTION_RUN_NOW_URL`` base + path) and ``MI_SCHEDULE_INTERNAL_API_KEY``
    or ``RETENTION_INTERNAL_API_KEY``.
    """
    url = (os.getenv("MI_TICK_URL") or "").strip()
    if not url:
        base = (os.getenv("RETENTION_RUN_NOW_URL") or "").strip()
        if base and "/admin/retention/run-now" in base:
            url = base.replace("/admin/retention/run-now", "/reports/mi/tick-schedules")
    key = (os.getenv("MI_SCHEDULE_INTERNAL_API_KEY") or os.getenv("RETENTION_INTERNAL_API_KEY") or "").strip()
    if not url or not key:
        return {"skipped": True, "reason": "MI_TICK_URL or internal API key unset"}
    with httpx.Client(timeout=120.0) as client:
        r = client.post(url, headers={"X-MI-Internal-Key": key})
        r.raise_for_status()
        return r.json()
