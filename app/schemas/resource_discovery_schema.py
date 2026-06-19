from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ResourceType = Literal[
    "official_textbook",
    "youtube_video",
    "interactive_media",
]


class LearningResourceSchema(BaseModel):
    resourceType: ResourceType
    title: str
    url: str
    provider: str
    description: str = ""
    subject: str = ""
    phase: str = ""
    gradeLevel: str = ""
    durationMinutes: int | None = None
    usage: str = ""
    selectionReason: str = ""
    confidence: float = Field(default=0, ge=0, le=1)
    verifiedAt: str

