from __future__ import annotations

from typing import Any

from pydantic import AliasChoices, BaseModel, Field


class RagSearchRequest(BaseModel):
    query: str = Field(..., min_length=1)
    subject: str | None = None
    phase: str | None = None
    topK: int = Field(default=5, ge=1, le=20)
    similarityThreshold: float = Field(
        default=0.2,
        ge=-1,
        le=1,
        validation_alias=AliasChoices("similarityThreshold", "similarity_threshold"),
    )
    documentType: str | None = "capaian_pembelajaran"


class RagReference(BaseModel):
    cpReferenceId: str
    sourceTitle: str
    documentType: str
    phase: str | None = None
    subject: str | None = None
    element: str | None = None
    chunkText: str
    similarityScore: float
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceChunk(BaseModel):
    document_id: str
    chunk_id: str
    similarity: float
    metadata: dict[str, Any] = Field(default_factory=dict)
    preview: str


class ModelInfo(BaseModel):
    embedding: str
    llm: str


class RagSearchResponse(BaseModel):
    cpText: str
    selectedRecordId: str | None = None
    confidence: float
    query: str
    sources: list[SourceChunk]
    models: ModelInfo


class RagIndexDocumentsRequest(BaseModel):
    documentPath: str = Field(..., min_length=1)
    sourceTitle: str = Field(..., min_length=1)
    documentType: str = "capaian_pembelajaran"
    subject: str | None = None
    phase: str | None = None


class RagIndexDocumentsResponse(BaseModel):
    message: str
    sourceTitle: str
    chunksCreated: int
    faissIndexPath: str


class RagReferenceItem(BaseModel):
    id: str
    sourceTitle: str
    subject: str | None = None
    phase: str | None = None
    element: str | None = None


class RagReferencesResponse(BaseModel):
    items: list[RagReferenceItem]
