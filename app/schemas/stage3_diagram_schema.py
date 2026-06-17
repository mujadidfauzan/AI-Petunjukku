from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.common_schema import ChatMessageSchema, FlexibleModel, ProjectSchema, StageSchema


class Stage3DiagramRequest(BaseModel):
    project: ProjectSchema
    stages: list[StageSchema] = Field(default_factory=list)
    chatHistory: list[ChatMessageSchema] = Field(default_factory=list)
    stage3Inputs: dict[str, Any] = Field(default_factory=dict)


class FlowStepSchema(FlexibleModel):
    id: str
    type: Literal["start", "process", "decision", "end"]
    label: str
    yes: str | None = None
    no: str | None = None


class FlowLaneSchema(FlexibleModel):
    id: str
    title: str
    steps: list[FlowStepSchema]


class FlowDiagramSchema(FlexibleModel):
    title: str
    lanes: list[FlowLaneSchema]


class Stage3GeneratedDesignSchema(FlexibleModel):
    summary: str
    praktikPedagogis: str
    alasanPraktikPedagogis: str
    pemanfaatanDigital: str
    fungsiTeknologiDigital: str
    produkKinerjaAkhirNarasi: str
    langkahPenting: list[str]
    diagrams: dict[str, FlowDiagramSchema]
    source: Literal["ai"] = "ai"


class Stage3DiagramResponse(BaseModel):
    generatedDesign: Stage3GeneratedDesignSchema
    model: str
    source: Literal["ai_service"] = "ai_service"
