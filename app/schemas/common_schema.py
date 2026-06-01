from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class FlexibleModel(BaseModel):
    model_config = ConfigDict(extra="allow")


class ProjectSchema(FlexibleModel):
    id: str
    title: str | None = None
    rppType: str | None = None
    subject: str | None = None
    phase: str | None = None
    gradeLevel: str | None = None


class TeacherProfileSchema(FlexibleModel):
    fullName: str | None = None
    position: str | None = None
    educationLevel: str | None = None


class SchoolSchema(FlexibleModel):
    name: str | None = None
    province: str | None = None
    city: str | None = None
    schoolEnvironment: str | None = None
    availableFacilities: list[str] = Field(default_factory=list)
    localContext: str | None = None


class TeacherClassSchema(FlexibleModel):
    className: str | None = None
    gradeLevel: str | None = None
    studentCount: int | None = None
    studentCharacteristics: str | None = None
    learningChallenges: list[str] = Field(default_factory=list)
    dominantLearningStyle: str | None = None


class TeacherSubjectSchema(FlexibleModel):
    subjectName: str | None = None
    gradeLevel: str | None = None


class StageSchema(FlexibleModel):
    stageNumber: int
    stageName: str | None = None
    contentJson: dict[str, Any] = Field(default_factory=dict)


class ChatMessageSchema(FlexibleModel):
    role: Literal["user", "assistant", "system"]
    message: str


class UsedReferenceSchema(FlexibleModel):
    cpReferenceId: str
    sourceTitle: str
    similarityScore: float | None = None
