from __future__ import annotations

from typing import Any, Dict, List


class XAIExplanationService:
    def __init__(self, model: Any = None, background_data: Any = None):
        self.model = model
        self.background_data = background_data

    def explain_prediction(self, transaction_data: Dict, num_features: int = 10) -> Dict[str, Any]:
        # Stub: return a minimal explanation shape used by the UI/backoffice
        features = list((transaction_data.get("metadata") or {}).keys())[:num_features]
        top_features = [{"feature": f, "contribution": 0.01} for f in features]
        return {
            "base_value": 0.5,
            "prediction": float(transaction_data.get("risk_score") or 0.5),
            "shap_values": top_features,
            "top_features": top_features,
            "feature_importance_plot": None,
            "waterfall_plot": None,
        }

    def generate_narrative(self, explanation: Dict) -> str:
        tops = explanation.get("top_features") or []
        bits = ", ".join([t.get("feature", "?") for t in tops[:5]]) if tops else "no strong drivers"
        return f"Risk drivers: {bits}."

    def get_global_feature_importance(self) -> List[Dict]:
        return []

