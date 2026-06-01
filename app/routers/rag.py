from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, status

from app.schemas.rag_schema import (
    RagIndexDocumentsRequest,
    RagIndexDocumentsResponse,
    RagReferencesResponse,
    RagSearchRequest,
    RagSearchResponse,
)
from app.services.rag_service import RAGService


router = APIRouter(prefix="/rag", tags=["rag"])


@router.post("/search", response_model=RagSearchResponse)
async def search(payload: RagSearchRequest) -> RagSearchResponse:
    return await RAGService().search(payload)


@router.post("/index-documents", response_model=RagIndexDocumentsResponse)
async def index_documents(
    payload: RagIndexDocumentsRequest,
) -> RagIndexDocumentsResponse:
    try:
        return await RAGService().index_documents(payload)
    except (FileNotFoundError, RuntimeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc


@router.get("/references", response_model=RagReferencesResponse)
def references(
    subject: str | None = Query(default=None),
    phase: str | None = Query(default=None),
    documentType: str | None = Query(default="capaian_pembelajaran"),
) -> RagReferencesResponse:
    items = RAGService().list_references(
        subject=subject,
        phase=phase,
        document_type=documentType,
    )
    return RagReferencesResponse(items=items)
