from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Literal, Optional, Protocol

import httpx

from app.config import settings
from app.core.logging import get_logger

log = get_logger(component="llm_client")


LLMProviderName = Literal["ollama", "openai", "gemini"]


@dataclass
class LLMResult:
    provider: str
    model: str
    content: str
    raw: Dict[str, Any]


class LLMClient(Protocol):
    provider: str
    model: str

    async def generate(self, prompt: str, system: Optional[str] = None) -> LLMResult: ...


class OllamaClient:
    provider = "ollama"

    def __init__(self, base_url: str, model: str):
        self.base_url = base_url.rstrip("/")
        self.model = model

    async def generate(self, prompt: str, system: Optional[str] = None) -> LLMResult:
        url = f"{self.base_url}/api/generate"
        payload: Dict[str, Any] = {"model": self.model, "prompt": prompt, "stream": False}
        if system:
            payload["system"] = system
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(url, json=payload)
            res.raise_for_status()
            data = res.json()
        content = data.get("response") or ""
        return LLMResult(provider=self.provider, model=self.model, content=content, raw=data)


class OpenAIClient:
    provider = "openai"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def generate(self, prompt: str, system: Optional[str] = None) -> LLMResult:
        # Uses OpenAI Chat Completions-compatible endpoint
        url = "https://api.openai.com/v1/chat/completions"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": self.model, "messages": messages, "temperature": 0.2}
        headers = {"Authorization": f"Bearer {self.api_key}"}
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(url, json=payload, headers=headers)
            res.raise_for_status()
            data = res.json()
        content = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
        return LLMResult(provider=self.provider, model=self.model, content=content, raw=data)


class GeminiClient:
    provider = "gemini"

    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model

    async def generate(self, prompt: str, system: Optional[str] = None) -> LLMResult:
        # Google Generative Language API (public REST)
        # Note: keep this minimal; production should handle safety settings and retries.
        model_path = self.model
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_path}:generateContent"
        parts = []
        if system:
            parts.append({"text": f"System: {system}"})
        parts.append({"text": prompt})
        payload = {"contents": [{"role": "user", "parts": parts}], "generationConfig": {"temperature": 0.2}}
        params = {"key": self.api_key}
        async with httpx.AsyncClient(timeout=60.0) as client:
            res = await client.post(url, params=params, json=payload)
            res.raise_for_status()
            data = res.json()
        candidates = data.get("candidates") or []
        content = ""
        if candidates:
            content = (candidates[0].get("content", {}).get("parts") or [{}])[0].get("text") or ""
        return LLMResult(provider=self.provider, model=self.model, content=content, raw=data)


def get_llm_client() -> LLMClient:
    provider: str = (settings.llm_provider or "ollama").lower()
    if provider == "openai":
        if not settings.openai_api_key:
            raise RuntimeError("OPENAI_API_KEY is required when llm_provider=openai")
        return OpenAIClient(api_key=settings.openai_api_key, model=settings.openai_model)
    if provider == "gemini":
        if not settings.gemini_api_key:
            raise RuntimeError("GEMINI_API_KEY is required when llm_provider=gemini")
        return GeminiClient(api_key=settings.gemini_api_key, model=settings.gemini_model)
    return OllamaClient(base_url=settings.ollama_base_url, model=settings.ollama_model)

