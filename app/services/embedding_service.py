from __future__ import annotations

import hashlib
import math

import httpx

from app.core.config import Settings, settings
from app.utils.vector_utils import validate_embedding


class EmbeddingService:
    def __init__(self, config: Settings = settings) -> None:
        self.settings = config

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        clean_texts = [text.strip() for text in texts if text and text.strip()]
        if len(clean_texts) != len(texts):
            raise ValueError("Embedding input tidak boleh kosong.")

        if (
            self.settings.embedding_provider.lower() == "openrouter"
        ):
            if not self.settings.openrouter_api_key:
                raise ValueError("OPENROUTER_API_KEY belum diisi untuk embedding OpenRouter.")
            return await self._embed_openrouter(clean_texts)

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
            "dimensions": self.settings.embedding_dimension,
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
            validate_embedding(embedding, self.settings.embedding_dimension)
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
