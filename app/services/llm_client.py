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
        _unused_default: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if not self.settings.llm_configured:
            raise RuntimeError("LLM belum dikonfigurasi.")

        try:
            content = await self._chat_completion(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
        except Exception as exc:
            logger.warning("LLM text generation failed: %s", exc)
            raise RuntimeError("LLM text generation failed.") from exc

        cleaned = content.strip()
        if not cleaned:
            raise RuntimeError("LLM mengembalikan respons kosong.")
        return cleaned

    async def generate_text_strict(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        if not self.settings.llm_configured:
            raise RuntimeError("LLM belum dikonfigurasi.")

        content = await self._chat_completion(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        cleaned = content.strip()
        if not cleaned:
            raise RuntimeError("LLM mengembalikan respons kosong.")
        return cleaned

    async def generate_json(
        self,
        messages: list[dict[str, str]],
        _unused_shape: dict[str, Any],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        if not self.settings.llm_configured:
            raise RuntimeError("LLM belum dikonfigurasi.")

        try:
            content = await self._chat_completion(
                messages=messages,
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                response_format={"type": "json_object"},
            )
            try:
                return parse_json_object(content)
            except Exception as parse_exc:
                logger.warning(
                    "LLM JSON parse failed, trying repair: %s", parse_exc
                )
                repaired = await self._repair_json_content(
                    content,
                    model=model,
                    temperature=0,
                    max_tokens=max_tokens,
                )
                return parse_json_object(repaired)
        except Exception as exc:
            logger.warning("LLM JSON generation failed: %s", exc)
            raise RuntimeError("LLM JSON generation failed.") from exc

    async def generate_json_strict(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        if not self.settings.llm_configured:
            raise RuntimeError("LLM belum dikonfigurasi.")

        content = await self._chat_completion(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        try:
            return parse_json_object(content)
        except Exception:
            repaired = await self._repair_json_content(
                content,
                model=model,
                temperature=0,
                max_tokens=max_tokens,
            )
            return parse_json_object(repaired)

    async def generate_json_once(
        self,
        messages: list[dict[str, str]],
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> dict[str, Any]:
        if not self.settings.llm_configured:
            raise RuntimeError("LLM belum dikonfigurasi.")

        content = await self._chat_completion(
            messages=messages,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        return parse_json_object(content)

    async def _repair_json_content(
        self,
        content: str,
        *,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        return await self._chat_completion(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Perbaiki teks berikut menjadi satu JSON object valid. "
                        "Jangan menambah data baru, jangan menulis markdown, dan return hanya JSON."
                    ),
                },
                {"role": "user", "content": content},
            ],
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )

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
            try:
                response = await client.post(
                    self.settings.openrouter_chat_url,
                    headers=headers,
                    json=payload,
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                detail = ""
                try:
                    detail = exc.response.text.strip()
                except Exception:
                    detail = ""
                if detail:
                    logger.warning("LLM provider returned %s: %s", exc.response.status_code, detail)
                raise
            data = response.json()

        choices = data.get("choices") or []
        content = choices[0].get("message", {}).get("content") if choices else None
        if not content:
            raise ValueError("LLM response kosong.")
        return str(content)
