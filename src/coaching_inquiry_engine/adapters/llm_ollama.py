"""Ollama HTTP adapter. Vendor I/O stays here; domain never imports httpx."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from coaching_inquiry_engine.config import Settings, get_settings
from coaching_inquiry_engine.domain.config import INSTITUTE_NAME, PROMPT_VERSION
from coaching_inquiry_engine.domain.decisions import AgentDecision
from coaching_inquiry_engine.ports.llm import DecisionContext

_PROMPT_PATH = Path(__file__).resolve().parents[3] / "prompts" / f"{PROMPT_VERSION}.md"
_NUM_PREDICT = 400


def load_system_prompt(*, institute_name: str = INSTITUTE_NAME) -> str:
    raw = _PROMPT_PATH.read_text(encoding="utf-8")
    return raw.replace("{institute_name}", institute_name)


class OllamaLlmAdapter:
    def __init__(
        self,
        settings: Settings | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client
        self._prompt = load_system_prompt()

    async def decide(self, context: DecisionContext) -> AgentDecision:
        payload = {
            "model": self._settings.ollama_model,
            "messages": [
                {"role": "system", "content": self._prompt},
                {"role": "user", "content": context.model_dump_json()},
            ],
            "stream": False,
            "format": AgentDecision.model_json_schema(),
            "options": {
                "temperature": 0,
                "num_predict": _NUM_PREDICT,
            },
        }
        response = await self._post(payload)
        response.raise_for_status()
        content = response.json()["message"]["content"]
        if isinstance(content, dict):
            raw = json.dumps(content)
        else:
            raw = content
        decision = AgentDecision.model_validate_json(raw)
        return decision.model_copy(update={"prompt_version": PROMPT_VERSION})

    async def _post(self, payload: dict[str, object]) -> httpx.Response:
        timeout = httpx.Timeout(self._settings.llm_timeout_seconds)
        if self._client is not None:
            return await self._client.post(
                "/api/chat",
                json=payload,
                timeout=timeout,
            )
        async with httpx.AsyncClient(
            base_url=self._settings.ollama_base_url.rstrip("/"),
            timeout=timeout,
        ) as client:
            return await client.post("/api/chat", json=payload)
