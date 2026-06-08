from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common_schema import (
    ProjectSchema,
    SchoolSchema,
    StageSchema,
    TeacherClassSchema,
    TeacherProfileSchema,
    TeacherSubjectSchema,
    UsedReferenceSchema,
)


class GenerateRppRequest(BaseModel):
    project: ProjectSchema
    teacherProfile: TeacherProfileSchema | dict[str, Any] | None = Field(
        default_factory=dict
    )
    school: SchoolSchema | dict[str, Any] | None = Field(default_factory=dict)
    teacherSubject: TeacherSubjectSchema | dict[str, Any] | None = Field(
        default_factory=dict
    )
    teacherClass: TeacherClassSchema | dict[str, Any] | None = Field(
        default_factory=dict
    )
    stages: list[StageSchema] = Field(default_factory=list)
    kinaChatSummary: dict[str, Any] = Field(default_factory=dict)
    options: dict[str, Any] = Field(default_factory=dict)


class GenerateRppResponse(BaseModel):
    status: str
    model: str
    rppType: str | None = None
    usedReferences: list[UsedReferenceSchema] = Field(default_factory=list)
    contentJson: dict[str, Any]
    contentMarkdown: str
