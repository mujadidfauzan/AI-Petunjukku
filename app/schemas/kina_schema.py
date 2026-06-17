from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common_schema import ChatMessageSchema, ProjectSchema, StageSchema
from app.schemas.common_schema import UsedReferenceSchema


class KinaChatRequest(BaseModel):
    project: ProjectSchema
    stages: list[StageSchema] = Field(default_factory=list)
    chatHistory: list[ChatMessageSchema] = Field(default_factory=list)
    message: str = Field(..., min_length=1)


class KinaInformationPoint(BaseModel):
    key: str
    label: str
    completed: bool


class KinaInformationProgress(BaseModel):
    completedCount: int
    totalCount: int
    percent: int
    activeStage: str | None = None
    activeLabel: str | None = None
    completed: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    points: list[KinaInformationPoint] = Field(default_factory=list)


class KinaChatResponse(BaseModel):
    reply: str
    usedReferences: list[UsedReferenceSchema] = Field(default_factory=list)
    suggestedFollowUpQuestions: list[str] = Field(default_factory=list)
    informationProgress: KinaInformationProgress | None = None


class KinaSummaryRequest(BaseModel):
    project: ProjectSchema
    chatHistory: list[ChatMessageSchema] = Field(default_factory=list)
    summaryType: str = "intrakurikuler_stage_3"


class KinaSummaryResponse(BaseModel):
    summary: dict[str, Any]
