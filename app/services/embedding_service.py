from __future__ import annotations

import hashlib
import logging
import math

import httpx

from app.core.config import Settings, settings


logger = logging.getLogger(__name__)


class EmbeddingService:
    def __init__(self, config: Settings = settings) -> None:
        self.settings = config

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        clean_texts = [text.strip() for text in texts if text and text.strip()]
        if len(clean_texts) != len(texts):
            raise ValueError("Embedding input tidak boleh kosong.")

        if (
            self.settings.embedding_provider.lower() == "openrouter"
            and self.settings.openrouter_api_key
        ):
            try:
                return await self._embed_openrouter(clean_texts)
            except Exception as exc:
                logger.warning("OpenRouter embedding failed, using local fallback: %s", exc)

        return [self._embed_local(text) for text in clean_texts]

    async def embed_text(self, text: str) -> list[float]:
        return (await self.embed_texts([text]))[0]

    async def _embed_openrouter(self, texts: list[str]) -> list[list[float]]:
        headers = {
            "Authorization": f"Bearer {self.settings.openrouter_api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.settings.embedding_model_name,
            "input": texts if len(texts) > 1 else texts[0],
        }

        async with httpx.AsyncClient(
            timeout=self.settings.request_timeout_seconds
        ) as client:
            response = await client.post(
                self.settings.openrouter_embeddings_url,
                headers=headers,
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        rows = data.get("data") or []
        embeddings = [row.get("embedding") for row in rows if isinstance(row, dict)]
        if len(embeddings) != len(texts):
            raise ValueError("Jumlah embedding OpenRouter tidak sesuai.")
        return [
            self._normalize(self._fit_dimensions([float(value) for value in embedding]))
            for embedding in embeddings
        ]

    def _embed_local(self, text: str) -> list[float]:
        dimensions = self.settings.embedding_dimension
        vector = [0.0 for _ in range(dimensions)]
        tokens = text.lower().split()
        if not tokens:
            return vector

        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % dimensions
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vector[index] += sign

        return self._normalize(vector)

    def _normalize(self, vector: list[float]) -> list[float]:
        norm = math.sqrt(sum(value * value for value in vector))
        if norm == 0:
            return vector
        return [value / norm for value in vector]

    def _fit_dimensions(self, vector: list[float]) -> list[float]:
        dimensions = self.settings.embedding_dimension
        if len(vector) == dimensions:
            return vector
        if len(vector) > dimensions:
            return vector[:dimensions]
        return vector + [0.0 for _ in range(dimensions - len(vector))]
