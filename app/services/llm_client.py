from __future__ import annotations

import logging
from typing import Any

import httpx

from app.core.config import Settings, settings
from app.utils.json_parser import parse_json_object


logger = logging.getLogger(__name__)


class LLMClient:
    def __init__(self, config: Settings = settings) -> None:
        self.settings = config

    @property
    def model_name(self) -> str:
        return self.settings.llm_model

    async def generate_text(
        self,
        messages: list[dict[str, str]],
        fallback: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if not self.settings.llm_configured:
            return fallback

        try:
            content = await self._chat_completion(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            return content.strip() or fallback
        except Exception as exc:
            logger.warning("LLM text generation failed: %s", exc)
            return fallback

    async def generate_json(
        self,
        messages: list[dict[str, str]],
        fallback: dict[str, Any],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        if not self.settings.llm_configured:
            return fallback

        try:
            content = await self._chat_completion(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            return parse_json_object(content)
        except Exception as exc:
            logger.warning("LLM JSON generation failed: %s", exc)
            return fallback

    async def _chat_completion(
        self,
        *,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        response_format: dict[str, str] | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model or self.settings.llm_model,
            "messages": messages,
            "temperature": (
                self.settings.llm_temperature if temperature is None else temperature
            ),
            "max_tokens": max_tokens or self.settings.llm_max_tokens,
        }
        if response_format:
            payload["response_format"] = response_format

        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:8000",
            "X-Title": self.settings.app_name,
        }

        async with httpx.AsyncClient(
            timeout=self.settings.request_timeout_seconds
        ) as client:
            response = await client.post(
                self.settings.openrouter_chat_url,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        choices = data.get("choices") or []
        content = choices[0].get("message", {}).get("content") if choices else None
        if not content:
            raise ValueError("LLM response kosong.")
        return str(content)
