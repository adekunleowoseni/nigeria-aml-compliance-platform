from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field


class TransactionCreate(BaseModel):
    customer_id: str
    amount: float
    currency: str = "NGN"
    transaction_type: str = "transfer"
    counterparty_id: Optional[str] = None
    counterparty_name: Optional[str] = None
    narrative: Optional[str] = None
    channel: Optional[str] = None
    timestamp: Optional[datetime] = None
    metadata: Optional[Dict[str, Any]] = None


class TransactionResponse(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    customer_id: str
    amount: float
    currency: str
    transaction_type: str
    narrative: Optional[str] = None
    counterparty_id: Optional[str] = None
    counterparty_name: Optional[str] = None
    risk_score: Optional[float] = None
    alert_id: Optional[str] = None
    status: str = "received"
    metadata: Optional[Dict[str, Any]] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: Optional[datetime] = None
    deleted_at: Optional[datetime] = Field(
        default=None,
        description="Soft-delete timestamp (retention / NDPA workflow); hidden from default API lists.",
    )


class TransactionFilter(BaseModel):
    start_date: Optional[datetime] = None
    end_date: Optional[datetime] = None
    min_amount: Optional[float] = None
    max_amount: Optional[float] = None
    status: Optional[str] = None
    entity_id: Optional[str] = None


class GraphNode(BaseModel):
    id: str
    type: str
    label: Optional[str] = None
    properties: Dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    source: str
    target: str
    type: str
    properties: Dict[str, Any] = Field(default_factory=dict)


class GraphResponse(BaseModel):
    nodes: List[GraphNode]
    edges: List[GraphEdge]

