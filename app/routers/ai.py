from __future__ import annotations

from fastapi import APIRouter

from app.schemas.generate_rpp_schema import GenerateRppRequest, GenerateRppResponse
from app.schemas.kina_schema import (
    KinaChatRequest,
    KinaChatResponse,
    KinaSummaryRequest,
    KinaSummaryResponse,
)
from app.schemas.lintas_disiplin_schema import (
    RecommendLintasDisiplinRequest,
    RecommendLintasDisiplinResponse,
)
from app.schemas.recommendation_schema import (
    RecommendStageRequest,
    RecommendStageResponse,
)
from app.schemas.stage3_diagram_schema import (
    Stage3DiagramRequest,
    Stage3DiagramResponse,
)
from app.services.ai_orchestrator_service import AIOrchestratorService


router = APIRouter(prefix="/ai", tags=["ai"])


@router.post("/recommend-stage", response_model=RecommendStageResponse)
async def recommend_stage(payload: RecommendStageRequest) -> RecommendStageResponse:
    return await AIOrchestratorService().recommend_stage(payload)


@router.post(
    "/recommend-lintas-disiplin",
    response_model=RecommendLintasDisiplinResponse,
)
async def recommend_lintas_disiplin(
    payload: RecommendLintasDisiplinRequest,
) -> RecommendLintasDisiplinResponse:
    return await AIOrchestratorService().recommend_lintas_disiplin(payload)


@router.post("/kina-chat", response_model=KinaChatResponse)
async def kina_chat(payload: KinaChatRequest) -> KinaChatResponse:
    return await AIOrchestratorService().kina_chat(payload)


@router.post("/summarize-kina-chat", response_model=KinaSummaryResponse)
async def summarize_kina_chat(payload: KinaSummaryRequest) -> KinaSummaryResponse:
    return await AIOrchestratorService().summarize_kina_chat(payload)


@router.post("/generate-rpp", response_model=GenerateRppResponse)
async def generate_rpp(payload: GenerateRppRequest) -> GenerateRppResponse:
    return await AIOrchestratorService().generate_rpp(payload)


@router.post("/generate-stage3-diagrams", response_model=Stage3DiagramResponse)
async def generate_stage3_diagrams(
    payload: Stage3DiagramRequest,
) -> Stage3DiagramResponse:
    return await AIOrchestratorService().generate_stage3_diagrams(payload)
