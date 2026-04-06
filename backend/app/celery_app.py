"""Celery application (optional). Beat schedules retention HTTP callback to the API process."""

from __future__ import annotations

import os

from celery import Celery
from celery.schedules import crontab

broker = os.getenv("CELERY_BROKER_URL") or os.getenv("REDIS_URL", "redis://localhost:6379/1")

celery_app = Celery(
    "aml_platform",
    broker=broker,
    include=["app.celery_tasks"],
)

celery_app.conf.timezone = "UTC"
celery_app.conf.beat_schedule = {
    "retention-daily-utc": {
        "task": "app.celery_tasks.retention_run_now_http",
        "schedule": crontab(hour=2, minute=30),
    },
    "reference-lists-daily-utc": {
        "task": "app.celery_tasks.reference_lists_run_now_http",
        "schedule": crontab(hour=3, minute=15),
    },
    "mi-schedules-every-minute": {
        "task": "app.celery_tasks.mi_schedules_tick_http",
        "schedule": crontab(minute="*"),
    },
}
