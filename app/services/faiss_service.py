from __future__ import annotations

import json
import math
import importlib.util
from pathlib import Path
from typing import Any

from app.core.config import Settings, settings


class FaissService:
    def __init__(self, config: Settings = settings) -> None:
        self.settings = config
        self.index_path = Path(config.faiss_index_path)
        self.metadata_path = Path(config.faiss_metadata_path)
        self.index_path.parent.mkdir(parents=True, exist_ok=True)
        self.metadata_path.parent.mkdir(parents=True, exist_ok=True)

    def backend_name(self) -> str:
        return "faiss" if self._faiss_available() else "exact_fallback"

    def is_ready(self) -> bool:
        return self.metadata_path.exists()

    def add_records(self, records: list[dict[str, Any]]) -> None:
        if not records:
            return

        metadata = self._load_metadata()
        metadata.extend(records)
        self._save_metadata(metadata)
        if self._faiss_available():
            self._rebuild_faiss_index(metadata)

    def replace_records(
        self,
        records: list[dict[str, Any]],
        *,
        file_hash: str,
        source_title: str,
        document_type: str,
    ) -> None:
        metadata = [
            item
            for item in self._load_metadata()
            if not (
                (item.get("metadata") or {}).get("fileHash") == file_hash
                and item.get("sourceTitle") == source_title
                and item.get("documentType") == document_type
            )
        ]
        metadata.extend(records)
        self._save_metadata(metadata)
        if self._faiss_available():
            self._rebuild_faiss_index(metadata)

    def search(
        self,
        query_embedding: list[float],
        *,
        top_k: int,
        filters: dict[str, str | None] | None = None,
    ) -> list[dict[str, Any]]:
        metadata = self._load_metadata()
        if not metadata:
            return []

        if self._faiss_available() and self.index_path.exists():
            faiss_matches = self._search_faiss(
                query_embedding=query_embedding,
                metadata=metadata,
                top_k=top_k,
                filters=filters or {},
            )
            if faiss_matches:
                return faiss_matches

        candidates = [
            item for item in metadata if self._matches_filters(item, filters or {})
        ]
        if not candidates:
            return []

        scored = []
        for item in candidates:
            score = self._cosine_similarity(query_embedding, item.get("embedding") or [])
            scored.append({**item, "similarityScore": score})

        scored.sort(key=lambda item: item["similarityScore"], reverse=True)
        return scored[:top_k]

    def list_references(
        self,
        *,
        subject: str | None = None,
        phase: str | None = None,
        document_type: str | None = None,
    ) -> list[dict[str, Any]]:
        filters = {
            "subject": subject,
            "phase": phase,
            "documentType": document_type,
        }
        seen: set[str] = set()
        items = []
        for item in self._load_metadata():
            if not self._matches_filters(item, filters):
                continue
            key = str(item.get("cpReferenceId"))
            if key in seen:
                continue
            seen.add(key)
            items.append(item)
        return items

    def _load_metadata(self) -> list[dict[str, Any]]:
        if not self.metadata_path.exists():
            return []
        data = json.loads(self.metadata_path.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []

    def _save_metadata(self, metadata: list[dict[str, Any]]) -> None:
        tmp_path = self.metadata_path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(self.metadata_path)

    def _rebuild_faiss_index(self, metadata: list[dict[str, Any]]) -> None:
        import faiss
        import numpy as np

        dimensions = self.settings.embedding_dimension
        index = faiss.IndexFlatIP(dimensions)
        embeddings = [item.get("embedding") for item in metadata if item.get("embedding")]
        if embeddings:
            matrix = np.asarray(embeddings, dtype="float32")
            index.add(matrix)
        faiss.write_index(index, str(self.index_path))

    def _search_faiss(
        self,
        *,
        query_embedding: list[float],
        metadata: list[dict[str, Any]],
        top_k: int,
        filters: dict[str, str | None],
    ) -> list[dict[str, Any]]:
        import faiss
        import numpy as np

        index = faiss.read_index(str(self.index_path))
        if index.ntotal != len(metadata) or index.d != len(query_embedding):
            self._rebuild_faiss_index(metadata)
            index = faiss.read_index(str(self.index_path))

        query = np.asarray([query_embedding], dtype="float32")
        search_k = len(metadata)
        scores, indices = index.search(query, search_k)

        matches = []
        for score, idx in zip(scores[0], indices[0], strict=True):
            if idx < 0:
                continue
            item = metadata[int(idx)]
            if not self._matches_filters(item, filters):
                continue
            matches.append({**item, "similarityScore": float(score)})
            if len(matches) >= top_k:
                break
        return matches

    def _faiss_available(self) -> bool:
        return importlib.util.find_spec("faiss") is not None

    def _matches_filters(
        self,
        item: dict[str, Any],
        filters: dict[str, str | None],
    ) -> bool:
        for key, expected in filters.items():
            if not expected:
                continue
            actual = item.get(key)
            if actual is None:
                return False
            if key == "phase":
                if self._normalize_phase(str(actual)) != self._normalize_phase(expected):
                    return False
                continue
            if key == "subject":
                expected_keys = self._subject_keys(expected)
                subject_keys = item.get("subjectSearchKeys") or []
                actual_keys = {*self._subject_keys(str(actual)), *subject_keys}
                if not expected_keys.intersection(actual_keys):
                    return False
                continue
            if str(actual).strip().casefold() != expected.strip().casefold():
                return False
        return True

    def _normalize_phase(self, value: str) -> str:
        cleaned = value.strip()
        lowered = cleaned.casefold()
        if "fondasi" in lowered:
            return "fondasi"
        if lowered.startswith("fase "):
            cleaned = cleaned[5:].strip()
        return cleaned.casefold()

    def _subject_keys(self, value: str) -> set[str]:
        key = "_".join("".join(char.lower() if char.isalnum() else " " for char in value).split())
        keys = {key}
        is_special_education = key.startswith("pendidikan_khusus_")
        if not is_special_education and ("ilmu_pengetahuan_alam_dan_sosial" in key or key == "ipas"):
            keys.update({"ipa", "ipas", "ilmu_pengetahuan_alam_dan_sosial"})
        elif not is_special_education and ("ilmu_pengetahuan_alam" in key or key == "ipa"):
            keys.update({"ipa", "ilmu_pengetahuan_alam"})
        if not is_special_education and ("ilmu_pengetahuan_sosial" in key or key == "ips"):
            keys.update({"ips", "ilmu_pengetahuan_sosial"})
        if key in {"pkn", "ppkn"} or "pendidikan_pancasila" in key:
            keys.update({"pkn", "ppkn", "pendidikan_pancasila"})
        if key == "paibp" or "pendidikan_agama_islam_dan_budi_pekerti" in key:
            keys.update({"paibp", "pendidikan_agama_islam_dan_budi_pekerti"})
        return keys

    def _cosine_similarity(self, left: list[float], right: list[float]) -> float:
        if not left or not right or len(left) != len(right):
            return 0.0
        dot = sum(a * b for a, b in zip(left, right, strict=True))
        left_norm = math.sqrt(sum(value * value for value in left))
        right_norm = math.sqrt(sum(value * value for value in right))
        if left_norm == 0 or right_norm == 0:
            return 0.0
        return dot / (left_norm * right_norm)
