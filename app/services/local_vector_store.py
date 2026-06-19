from __future__ import annotations

import json
import math
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import Settings, settings
from app.services.text_chunker import TextChunk
from app.utils.vector_utils import validate_embedding


class LocalVectorStore:
    def __init__(
        self,
        config: Settings = settings,
        index_path: Path | None = None,
    ) -> None:
        self.settings = config
        self.index_path = index_path or Path(config.local_vector_index_path)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)

    def backend_name(self) -> str:
        return "local_json"

    def create_document(
        self,
        *,
        title: str | None,
        file_name: str,
        file_path: str | None,
        mime_type: str | None,
        source_type: str = "upload",
        file_hash: str | None = None,
    ) -> dict[str, Any]:
        data = self._load()
        now = self._now()
        document = {
            "id": str(uuid.uuid4()),
            "title": title,
            "file_name": file_name,
            "file_path": file_path,
            "mime_type": mime_type,
            "source_type": source_type,
            "file_hash": file_hash,
            "created_at": now,
            "updated_at": now,
        }
        data["documents"].append(document)
        self._save(data)
        return document

    def save_document_chunks_batch(
        self,
        *,
        document_id: str,
        chunks: list[TextChunk],
        embeddings: list[list[float]],
    ) -> list[dict[str, Any]]:
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"Jumlah chunk dan embedding tidak sama. chunks={len(chunks)}, embeddings={len(embeddings)}."
            )

        data = self._load()
        if not any(document["id"] == document_id for document in data["documents"]):
            raise ValueError(f"document_id tidak ditemukan: {document_id}")

        rows = []
        for chunk, embedding in zip(chunks, embeddings, strict=True):
            vector = validate_embedding(embedding, self.settings.embedding_dimension)
            row = {
                "chunk_id": str(uuid.uuid4()),
                "id": str(uuid.uuid4()),
                "document_id": document_id,
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "metadata": chunk.metadata,
                "embedding": vector,
                "token_count": chunk.token_count,
                "created_at": self._now(),
            }
            rows.append(row)

        data["chunks"].extend(rows)
        self._save(data)
        return rows

    def match_document_chunks(
        self,
        *,
        query_embedding: list[float],
        match_count: int = 5,
        similarity_threshold: float | None = 0.2,
        metadata_filters: dict[str, str] | None = None,
    ) -> list[dict[str, Any]]:
        query_vector = validate_embedding(
            query_embedding,
            self.settings.embedding_dimension,
        )
        data = self._load()
        results = []
        for chunk in data["chunks"]:
            metadata = chunk.get("metadata") or {}
            if metadata_filters and not self._metadata_matches(metadata, metadata_filters):
                continue
            similarity = self._cosine_similarity(query_vector, chunk["embedding"])
            if similarity_threshold is not None and similarity < similarity_threshold:
                continue
            results.append(
                {
                    "chunk_id": chunk.get("chunk_id") or chunk.get("id"),
                    "document_id": chunk["document_id"],
                    "content": chunk["content"],
                    "metadata": metadata,
                    "similarity": similarity,
                }
            )

        results.sort(key=lambda item: item["similarity"], reverse=True)
        return results[:match_count]

    def find_indexed_document(
        self,
        *,
        file_hash: str,
        file_name: str,
    ) -> dict[str, Any] | None:
        data = self._load()
        for document in data["documents"]:
            if (
                document.get("file_hash") == file_hash
                and self.count_chunks_for_document(document["id"]) > 0
            ):
                return document

        for document in data["documents"]:
            if (
                document.get("file_name") == file_name
                and self.count_chunks_for_document(document["id"]) > 0
            ):
                document["file_hash"] = file_hash
                document["updated_at"] = self._now()
                self._save(data)
                return document
        return None

    def count_chunks_for_document(self, document_id: str) -> int:
        data = self._load()
        return sum(1 for chunk in data["chunks"] if chunk.get("document_id") == document_id)

    def list_references(
        self,
        *,
        subject: str | None = None,
        phase: str | None = None,
        document_type: str | None = None,
    ) -> list[dict[str, Any]]:
        filters = {
            "subject_normalized": self._normalize_subject_key(subject) if subject else None,
            "phase": self._normalize_phase(phase) if phase else None,
            "content_type": "cp_record" if document_type == "capaian_pembelajaran" else None,
        }
        seen: set[str] = set()
        items = []
        for chunk in self._load()["chunks"]:
            metadata = chunk.get("metadata") or {}
            if not self._metadata_matches(metadata, {key: value for key, value in filters.items() if value}):
                continue
            key = str(metadata.get("cp_record_id") or chunk.get("chunk_id"))
            if key in seen:
                continue
            seen.add(key)
            items.append(
                {
                    "cpReferenceId": key,
                    "sourceTitle": metadata.get("source") or metadata.get("file_name"),
                    "subject": metadata.get("subject"),
                    "phase": f"Fase {metadata.get('phase')}" if metadata.get("phase") else None,
                    "element": metadata.get("element"),
                    "chunkText": chunk.get("content"),
                    "metadata": metadata,
                }
            )
        return items

    def _load(self) -> dict[str, Any]:
        if not self.index_path.exists():
            return {"documents": [], "chunks": []}
        data = json.loads(self.index_path.read_text(encoding="utf-8"))
        data.setdefault("documents", [])
        data.setdefault("chunks", [])
        return data

    def _save(self, data: dict[str, Any]) -> None:
        tmp_path = self.index_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        tmp_path.replace(self.index_path)

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        dot = 0.0
        left_norm = 0.0
        right_norm = 0.0
        for a, b in zip(left, right, strict=True):
            dot += a * b
            left_norm += a * a
            right_norm += b * b
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (math.sqrt(left_norm) * math.sqrt(right_norm))

    def _metadata_matches(self, metadata: dict[str, Any], filters: dict[str, str]) -> bool:
        for key, expected in filters.items():
            actual = metadata.get(key)
            if actual is None:
                return False
            if str(actual).strip().casefold() != expected.strip().casefold():
                return False
        return True

    def _normalize_subject_key(self, value: str | None) -> str:
        return "_".join(
            "".join(char.lower() if char.isalnum() else " " for char in str(value or "")).split()
        )

    def _normalize_phase(self, value: str | None) -> str:
        cleaned = str(value or "").strip()
        lowered = cleaned.casefold()
        if "fondasi" in lowered:
            return "Fondasi"
        if lowered.startswith("fase "):
            cleaned = cleaned[5:].strip()
        return cleaned.upper()

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()
