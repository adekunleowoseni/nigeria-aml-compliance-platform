"""Compatibility shim: audit DDL lives in ``audit_events_schema``."""

from __future__ import annotations

from app.services.audit_events_schema import ensure_audit_events_schema

# Legacy name used by older deployments
ensure_aml_audit_trail_table = ensure_audit_events_schema
