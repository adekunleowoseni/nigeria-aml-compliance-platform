from __future__ import annotations

from typing import Any, Dict, List, Tuple

from app.core.logging import get_logger

log = get_logger(component="gnn_service")


class GNNInferenceService:
    """
    Placeholder service.

    The full GNN + Neo4j feature extraction is intentionally stubbed here so the API
    can run even before ML dependencies/models are wired.
    """

    def __init__(self, model_path: str, neo4j_uri: str, neo4j_auth: tuple[str, str]):
        self.model_path = model_path
        self.neo4j_uri = neo4j_uri
        self.neo4j_auth = neo4j_auth

    async def analyze_transaction(self, transaction_id: str, subgraph_depth: int = 2) -> Dict[str, Any]:
        log.info("analyze_transaction", transaction_id=transaction_id, depth=subgraph_depth)
        # Return a deterministic stub until real model is integrated.
        return {
            "risk_score": 0.42,
            "is_suspicious": False,
            "confidence": 0.55,
            "motifs_detected": [],
            "related_entities": [],
        }

    def _fetch_subgraph(self, transaction_id: str, depth: int) -> Tuple[Any, ...]:
        raise NotImplementedError

    def _preprocess_features(self, nodes, edges) -> Tuple[Any, ...]:
        raise NotImplementedError

    def batch_analyze(self, transaction_ids: List[str]) -> List[Dict[str, Any]]:
        return [{"transaction_id": tid, "risk_score": 0.42} for tid in transaction_ids]

