from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common_schema import (
    ProjectSchema,
    SchoolSchema,
    StageSchema,
    TeacherClassSchema,
    TeacherProfileSchema,
)
from app.schemas.rag_schema import RagReference


class RecommendStageRequest(BaseModel):
    project: ProjectSchema
    teacherProfile: TeacherProfileSchema | None = None
    school: SchoolSchema | None = None
    teacherClass: TeacherClassSchema | None = None
    previousStages: list[StageSchema] = Field(default_factory=list)
    targetStage: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)


class RecommendStageResponse(BaseModel):
    rppType: str | None = None
    recommendationType: str
    targetStageNumber: int | None = None
    ragReferences: list[RagReference] = Field(default_factory=list)
    recommendations: dict[str, Any]
