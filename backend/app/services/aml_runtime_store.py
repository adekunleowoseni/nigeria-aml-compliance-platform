"""
System-of-record for transactions and alerts: memory (dict) or Postgres.

Use get_aml_runtime_store() after init_aml_runtime_store() at application startup.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, List, Optional

from app.db.postgres_client import PostgresClient
from app.models.alert import AlertResponse
from app.models.transaction import TransactionResponse

_runtime_store: Optional["AmlRuntimeStore"] = None


def _normalize_ts(val: Any) -> Any:
    if val is None:
        return None
    if isinstance(val, datetime) and val.tzinfo is not None:
        return val.replace(tzinfo=None)
    return val


def _row_to_transaction(row: dict[str, Any]) -> TransactionResponse:
    md = row.get("metadata")
    if isinstance(md, str):
        md = json.loads(md) if md else None
    return TransactionResponse(
        id=str(row["id"]),
        customer_id=str(row["customer_id"]),
        amount=float(row["amount"]),
        currency=str(row.get("currency") or "NGN"),
        transaction_type=str(row["transaction_type"]),
        narrative=row.get("narrative"),
        counterparty_id=row.get("counterparty_id"),
        counterparty_name=row.get("counterparty_name"),
        risk_score=float(row["risk_score"]) if row.get("risk_score") is not None else None,
        alert_id=row.get("alert_id"),
        status=str(row.get("status") or "received"),
        metadata=md if isinstance(md, dict) else None,
        created_at=_normalize_ts(row["created_at"]) or datetime.utcnow(),
        updated_at=_normalize_ts(row.get("updated_at")),
        deleted_at=_normalize_ts(row.get("deleted_at")),
    )


def _row_to_alert(row: dict[str, Any]) -> AlertResponse:
    ih = row.get("investigation_history")
    if isinstance(ih, str):
        ih = json.loads(ih) if ih else []
    if not isinstance(ih, list):
        ih = []
    rule_ids = row.get("rule_ids")
    if rule_ids is None:
        rule_ids = []
    elif not isinstance(rule_ids, list):
        rule_ids = list(rule_ids)
    return AlertResponse(
        id=str(row["id"]),
        transaction_id=str(row["transaction_id"]),
        customer_id=str(row["customer_id"]),
        severity=float(row["severity"]),
        status=str(row["status"]),
        rule_ids=[str(x) for x in rule_ids],
        summary=row.get("summary"),
        last_resolution=row.get("last_resolution"),
        cco_str_approved=bool(row.get("cco_str_approved")),
        cco_str_rejected=bool(row.get("cco_str_rejected")),
        cco_str_rejection_reason=row.get("cco_str_rejection_reason"),
        escalated_to_cco=bool(row.get("escalated_to_cco")),
        escalation_classification=row.get("escalation_classification"),
        escalation_reason_notes=row.get("escalation_reason_notes"),
        investigation_history=[x for x in ih if isinstance(x, dict)],
        created_at=_normalize_ts(row["created_at"]) or datetime.utcnow(),
        updated_at=_normalize_ts(row.get("updated_at")),
        otc_filing_reason=row.get("otc_filing_reason"),
        otc_filing_reason_detail=row.get("otc_filing_reason_detail"),
        otc_outcome=row.get("otc_outcome"),
        otc_subject=row.get("otc_subject"),
        otc_officer_rationale=row.get("otc_officer_rationale"),
        otc_report_kind=row.get("otc_report_kind"),
        cco_otc_approved=bool(row.get("cco_otc_approved")),
        cco_estr_word_approved=bool(row.get("cco_estr_word_approved")),
        otc_submitted_at=_normalize_ts(row.get("otc_submitted_at")),
        linked_transaction_type=row.get("linked_transaction_type"),
        walk_in_otc=bool(row.get("walk_in_otc")),
        deleted_at=_normalize_ts(row.get("deleted_at")),
    )


class AmlRuntimeStore(ABC):
    """Abstract transaction + alert persistence (memory or Postgres)."""

    @abstractmethod
    async def transaction_get(self, transaction_id: str) -> Optional[TransactionResponse]: ...

    @abstractmethod
    async def transaction_put(self, txn: TransactionResponse) -> None: ...

    @abstractmethod
    async def transaction_delete_hard(self, transaction_id: str) -> None: ...

    @abstractmethod
    async def transactions_values(self) -> List[TransactionResponse]: ...

    @abstractmethod
    async def transactions_clear(self) -> None: ...

    @abstractmethod
    async def alert_get(self, alert_id: str) -> Optional[AlertResponse]: ...

    @abstractmethod
    async def alert_put(self, alert: AlertResponse) -> None: ...

    @abstractmethod
    async def alert_delete_hard(self, alert_id: str) -> None: ...

    @abstractmethod
    async def alerts_values(self) -> List[AlertResponse]: ...

    @abstractmethod
    async def alerts_clear(self) -> None: ...

    async def transaction_exists(self, transaction_id: str) -> bool:
        t = await self.transaction_get(transaction_id)
        return t is not None


class MemoryAmlRuntimeStore(AmlRuntimeStore):
    """Backs onto module-level dicts in in_memory_stores (backward compatible)."""

    async def transaction_get(self, transaction_id: str) -> Optional[TransactionResponse]:
        from app.api.v1.in_memory_stores import _TXNS

        return _TXNS.get(transaction_id)

    async def transaction_put(self, txn: TransactionResponse) -> None:
        from app.api.v1.in_memory_stores import _TXNS

        _TXNS[txn.id] = txn

    async def transaction_delete_hard(self, transaction_id: str) -> None:
        from app.api.v1.in_memory_stores import _TXNS

        _TXNS.pop(transaction_id, None)

    async def transactions_values(self) -> List[TransactionResponse]:
        from app.api.v1.in_memory_stores import _TXNS

        return list(_TXNS.values())

    async def transactions_clear(self) -> None:
        from app.api.v1.in_memory_stores import _TXNS

        _TXNS.clear()

    async def alert_get(self, alert_id: str) -> Optional[AlertResponse]:
        from app.api.v1.in_memory_stores import _ALERTS

        return _ALERTS.get(alert_id)

    async def alert_put(self, alert: AlertResponse) -> None:
        from app.api.v1.in_memory_stores import _ALERTS

        _ALERTS[alert.id] = alert

    async def alert_delete_hard(self, alert_id: str) -> None:
        from app.api.v1.in_memory_stores import _ALERTS

        _ALERTS.pop(alert_id, None)

    async def alerts_values(self) -> List[AlertResponse]:
        from app.api.v1.in_memory_stores import _ALERTS

        return list(_ALERTS.values())

    async def alerts_clear(self) -> None:
        from app.api.v1.in_memory_stores import _ALERTS

        _ALERTS.clear()


class PostgresAmlRuntimeStore(AmlRuntimeStore):
    def __init__(self, pg: PostgresClient) -> None:
        self._pg = pg

    def _cbs_ref(self, txn: TransactionResponse) -> Optional[str]:
        md = txn.metadata if isinstance(txn.metadata, dict) else None
        if not md:
            return None
        ref = md.get("cbs_reference") or md.get("cbs_ref") or md.get("core_reference")
        if ref is None:
            return None
        s = str(ref).strip()
        return s or None

    async def transaction_get(self, transaction_id: str) -> Optional[TransactionResponse]:
        row = await self._pg.fetchrow(
            "SELECT * FROM aml_transactions WHERE id = $1",
            transaction_id,
        )
        return _row_to_transaction(row) if row else None

    async def transaction_put(self, txn: TransactionResponse) -> None:
        md_val: Any = txn.metadata if isinstance(txn.metadata, dict) else None
        md_json = json.dumps(md_val) if md_val is not None else None
        cbs = self._cbs_ref(txn)
        ca = txn.created_at
        ua = txn.updated_at
        da = txn.deleted_at
        await self._pg.execute(
            """
            INSERT INTO aml_transactions (
                id, customer_id, amount, currency, transaction_type, narrative,
                counterparty_id, counterparty_name, risk_score, alert_id, status,
                metadata, created_at, updated_at, deleted_at, cbs_reference
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, $13, $14, $15, $16
            )
            ON CONFLICT (id) DO UPDATE SET
                customer_id = EXCLUDED.customer_id,
                amount = EXCLUDED.amount,
                currency = EXCLUDED.currency,
                transaction_type = EXCLUDED.transaction_type,
                narrative = EXCLUDED.narrative,
                counterparty_id = EXCLUDED.counterparty_id,
                counterparty_name = EXCLUDED.counterparty_name,
                risk_score = EXCLUDED.risk_score,
                alert_id = EXCLUDED.alert_id,
                status = EXCLUDED.status,
                metadata = EXCLUDED.metadata,
                created_at = EXCLUDED.created_at,
                updated_at = EXCLUDED.updated_at,
                deleted_at = EXCLUDED.deleted_at,
                cbs_reference = COALESCE(EXCLUDED.cbs_reference, aml_transactions.cbs_reference)
            """,
            txn.id,
            txn.customer_id,
            txn.amount,
            txn.currency,
            txn.transaction_type,
            txn.narrative,
            txn.counterparty_id,
            txn.counterparty_name,
            txn.risk_score,
            txn.alert_id,
            txn.status,
            md_json,
            ca,
            ua,
            da,
            cbs,
        )

    async def transaction_delete_hard(self, transaction_id: str) -> None:
        await self._pg.execute("DELETE FROM aml_transactions WHERE id = $1", transaction_id)

    async def transactions_values(self) -> List[TransactionResponse]:
        rows = await self._pg.fetch("SELECT * FROM aml_transactions")
        return [_row_to_transaction(dict(r)) for r in rows]

    async def transactions_clear(self) -> None:
        await self._pg.execute("DELETE FROM aml_transactions")

    async def alert_get(self, alert_id: str) -> Optional[AlertResponse]:
        row = await self._pg.fetchrow("SELECT * FROM aml_alerts WHERE id = $1", alert_id)
        return _row_to_alert(row) if row else None

    async def alert_put(self, alert: AlertResponse) -> None:
        a = alert
        ih_json = json.dumps(a.investigation_history or [])
        await self._pg.execute(
            """
            INSERT INTO aml_alerts (
                id, transaction_id, customer_id, severity, status, rule_ids, summary, last_resolution,
                cco_str_approved, cco_str_rejected, cco_str_rejection_reason, escalated_to_cco,
                escalation_classification, escalation_reason_notes, investigation_history,
                created_at, updated_at, otc_filing_reason, otc_filing_reason_detail, otc_outcome,
                otc_subject, otc_officer_rationale, otc_report_kind, cco_otc_approved,
                cco_estr_word_approved, otc_submitted_at, linked_transaction_type, walk_in_otc, deleted_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15::jsonb,
                $16, $17, $18, $19, $20, $21, $22, $23, $24, $25, $26, $27, $28, $29
            )
            ON CONFLICT (id) DO UPDATE SET
                transaction_id = EXCLUDED.transaction_id,
                customer_id = EXCLUDED.customer_id,
                severity = EXCLUDED.severity,
                status = EXCLUDED.status,
                rule_ids = EXCLUDED.rule_ids,
                summary = EXCLUDED.summary,
                last_resolution = EXCLUDED.last_resolution,
                cco_str_approved = EXCLUDED.cco_str_approved,
                cco_str_rejected = EXCLUDED.cco_str_rejected,
                cco_str_rejection_reason = EXCLUDED.cco_str_rejection_reason,
                escalated_to_cco = EXCLUDED.escalated_to_cco,
                escalation_classification = EXCLUDED.escalation_classification,
                escalation_reason_notes = EXCLUDED.escalation_reason_notes,
                investigation_history = EXCLUDED.investigation_history,
                created_at = EXCLUDED.created_at,
                updated_at = EXCLUDED.updated_at,
                otc_filing_reason = EXCLUDED.otc_filing_reason,
                otc_filing_reason_detail = EXCLUDED.otc_filing_reason_detail,
                otc_outcome = EXCLUDED.otc_outcome,
                otc_subject = EXCLUDED.otc_subject,
                otc_officer_rationale = EXCLUDED.otc_officer_rationale,
                otc_report_kind = EXCLUDED.otc_report_kind,
                cco_otc_approved = EXCLUDED.cco_otc_approved,
                cco_estr_word_approved = EXCLUDED.cco_estr_word_approved,
                otc_submitted_at = EXCLUDED.otc_submitted_at,
                linked_transaction_type = EXCLUDED.linked_transaction_type,
                walk_in_otc = EXCLUDED.walk_in_otc,
                deleted_at = EXCLUDED.deleted_at
            """,
            a.id,
            a.transaction_id,
            a.customer_id,
            a.severity,
            a.status,
            list(a.rule_ids or []),
            a.summary,
            a.last_resolution,
            a.cco_str_approved,
            a.cco_str_rejected,
            a.cco_str_rejection_reason,
            a.escalated_to_cco,
            a.escalation_classification,
            a.escalation_reason_notes,
            ih_json,
            a.created_at,
            a.updated_at,
            a.otc_filing_reason,
            a.otc_filing_reason_detail,
            a.otc_outcome,
            a.otc_subject,
            a.otc_officer_rationale,
            a.otc_report_kind,
            a.cco_otc_approved,
            a.cco_estr_word_approved,
            a.otc_submitted_at,
            a.linked_transaction_type,
            a.walk_in_otc,
            a.deleted_at,
        )

    async def alert_delete_hard(self, alert_id: str) -> None:
        await self._pg.execute("DELETE FROM aml_alerts WHERE id = $1", alert_id)

    async def alerts_values(self) -> List[AlertResponse]:
        rows = await self._pg.fetch("SELECT * FROM aml_alerts")
        return [_row_to_alert(dict(r)) for r in rows]

    async def alerts_clear(self) -> None:
        await self._pg.execute("DELETE FROM aml_alerts")


def init_aml_runtime_store(*, store_backend: str, pg: Optional[PostgresClient]) -> None:
    global _runtime_store
    b = (store_backend or "memory").lower().strip()
    if b == "postgres":
        if pg is None:
            raise RuntimeError("STORE_BACKEND=postgres requires a connected PostgresClient")
        _runtime_store = PostgresAmlRuntimeStore(pg)
    else:
        _runtime_store = MemoryAmlRuntimeStore()


def get_aml_runtime_store() -> AmlRuntimeStore:
    if _runtime_store is None:
        raise RuntimeError("AML runtime store not initialized; call init_aml_runtime_store at startup")
    return _runtime_store
