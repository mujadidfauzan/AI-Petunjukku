from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common_schema import (
    ChatMessageSchema,
    ProjectSchema,
    SchoolSchema,
    StageSchema,
    TeacherClassSchema,
    TeacherProfileSchema,
    TeacherSubjectSchema,
    UsedReferenceSchema,
)


class KinaChatRequest(BaseModel):
    project: ProjectSchema
    teacherProfile: TeacherProfileSchema | None = None
    school: SchoolSchema | None = None
    teacherSubject: TeacherSubjectSchema | None = None
    teacherClass: TeacherClassSchema | None = None
    stages: list[StageSchema] = Field(default_factory=list)
    chatHistory: list[ChatMessageSchema] = Field(default_factory=list)
    message: str = ""
    requireAi: bool = False
    stage3Memory: dict[str, Any] = Field(default_factory=dict)


class KinaChatResponse(BaseModel):
    reply: str
    model: str | None = None
    usedReferences: list[UsedReferenceSchema] = Field(default_factory=list)
    suggestedFollowUpQuestions: list[str] = Field(default_factory=list)
    progress: dict[str, Any] | None = None
    stage3Memory: dict[str, Any] | None = None


class KinaSummaryRequest(BaseModel):
    project: ProjectSchema
    chatHistory: list[ChatMessageSchema] = Field(default_factory=list)
    summaryType: str = "intrakurikuler_stage_3"


class KinaSummaryResponse(BaseModel):
    summary: dict[str, Any]
