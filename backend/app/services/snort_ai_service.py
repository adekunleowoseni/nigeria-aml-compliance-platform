from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.logging import get_logger
from app.services.llm.client import get_llm_client

log = get_logger(component="snort_ai")


class SnortAISecurityService:
    """
    Cognitive security layer:
    - Snort emits alerts/log lines (static rules)
    - LLM summarizes sequences to detect "low and slow" exfiltration or insider threat narratives
    """

    async def summarize_logs(
        self,
        log_lines: List[str],
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        llm = get_llm_client()
        prompt = (
            "You are a SOC analyst assistant. Given Snort alerts/log lines, infer if there is:\n"
            "- data exfiltration (low-and-slow)\n"
            "- credential stuffing / lateral movement\n"
            "- command-and-control beacons\n"
            "Return: risk level (low/medium/high), likely scenario, and recommended response steps.\n\n"
            f"Context: {context}\n"
            "Logs:\n"
            + "\n".join(log_lines[-200:])
        )
        result = await llm.generate(prompt)
        return {"provider": result.provider, "model": result.model, "summary": result.content, "raw": result.raw}

