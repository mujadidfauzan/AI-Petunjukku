from __future__ import annotations

from app.services.faiss_service import FaissService


class CpReferenceService:
    def __init__(self, vector_store: FaissService | None = None) -> None:
        self.vector_store = vector_store or FaissService()

    def list_references(
        self,
        *,
        subject: str | None = None,
        phase: str | None = None,
        document_type: str | None = None,
    ) -> list[dict[str, object]]:
        return self.vector_store.list_references(
            subject=subject,
            phase=phase,
            document_type=document_type,
        )
