from __future__ import annotations

from pydantic import BaseModel, Field

from app.schemas.common_schema import (
    ProjectSchema,
    SchoolSchema,
    StageSchema,
    TeacherClassSchema,
    TeacherProfileSchema,
)


class LintasDisiplinOptionSchema(BaseModel):
    id: str
    label: str


class RecommendLintasDisiplinRequest(BaseModel):
    project: ProjectSchema
    teacherProfile: TeacherProfileSchema | None = None
    school: SchoolSchema | None = None
    teacherClass: TeacherClassSchema | None = None
    previousStages: list[StageSchema] = Field(default_factory=list)
    profilLulusan: list[str] = Field(default_factory=list)
    options: dict[str, str | int | float | bool] = Field(default_factory=dict)


class RecommendLintasDisiplinResponse(BaseModel):
    subjects: list[LintasDisiplinOptionSchema] = Field(default_factory=list)
    model: str | None = None
    source: str = "ai_service"
