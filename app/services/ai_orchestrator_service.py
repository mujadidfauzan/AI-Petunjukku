from __future__ import annotations

from app.schemas.environment_schema import (
    SchoolEnvironmentCurationRequest,
    SchoolEnvironmentCurationResponse,
)
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
from app.services.environment_curation_service import EnvironmentCurationService
from app.services.intrakurikuler.intra_generation_service import (
    IntraGenerationService,
)
from app.services.intrakurikuler.intra_kina_service import IntraKinaService
from app.services.intrakurikuler.intra_lintas_disiplin_service import (
    IntraLintasDisiplinService,
)
from app.services.intrakurikuler.intra_recommendation_service import (
    IntraRecommendationService,
)
from app.services.intrakurikuler.intra_stage3_diagram_service import (
    IntraStage3DiagramService,
)
from app.services.intrakurikuler.intra_summary_service import IntraSummaryService
from app.services.pjbl.pjbl_generation_service import PjblGenerationService
from app.services.pjbl.pjbl_kina_service import PjblKinaService
from app.services.pjbl.pjbl_recommendation_service import PjblRecommendationService
from app.services.pjbl.pjbl_summary_service import PjblSummaryService
from fastapi import HTTPException, status


class AIOrchestratorService:
    async def curate_school_environment(
        self, payload: SchoolEnvironmentCurationRequest
    ) -> SchoolEnvironmentCurationResponse:
        return await EnvironmentCurationService().curate(payload)

    async def recommend_lintas_disiplin(
        self, payload: RecommendLintasDisiplinRequest
    ) -> RecommendLintasDisiplinResponse:
        if payload.project.rppType == "intrakurikuler":
            return await IntraLintasDisiplinService().recommend(payload)
        raise self._unsupported_rpp_type(payload.project.rppType)

    async def recommend_stage(
        self, payload: RecommendStageRequest
    ) -> RecommendStageResponse:
        stage_number = payload.targetStage.get("stageNumber")
        if stage_number != 2:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Recommendation hanya tersedia untuk Stage 2.",
            )

        if payload.project.rppType == "intrakurikuler":
            return await IntraRecommendationService().recommend(payload)
        if payload.project.rppType == "pjbl_kokurikuler":
            return await PjblRecommendationService().recommend(payload)
        raise self._unsupported_rpp_type(payload.project.rppType)

    async def kina_chat(self, payload: KinaChatRequest) -> KinaChatResponse:
        if payload.project.rppType == "intrakurikuler":
            return await IntraKinaService().chat(payload)
        if payload.project.rppType == "pjbl_kokurikuler":
            return await PjblKinaService().chat(payload)
        raise self._unsupported_rpp_type(payload.project.rppType)

    async def summarize_kina_chat(
        self, payload: KinaSummaryRequest
    ) -> KinaSummaryResponse:
        if payload.project.rppType == "intrakurikuler":
            return await IntraSummaryService().summarize(payload)
        if payload.project.rppType == "pjbl_kokurikuler":
            return await PjblSummaryService().summarize(payload)
        raise self._unsupported_rpp_type(payload.project.rppType)

    async def generate_rpp(self, payload: GenerateRppRequest) -> GenerateRppResponse:
        if payload.project.rppType == "intrakurikuler":
            return await IntraGenerationService().generate(payload)
        if payload.project.rppType == "pjbl_kokurikuler":
            return await PjblGenerationService().generate(payload)
        raise self._unsupported_rpp_type(payload.project.rppType)

    async def generate_stage3_diagrams(
        self, payload: Stage3DiagramRequest
    ) -> Stage3DiagramResponse:
        if payload.project.rppType == "intrakurikuler":
            return await IntraStage3DiagramService().generate(payload)
        raise self._unsupported_rpp_type(payload.project.rppType)

    def _unsupported_rpp_type(self, rpp_type: str | None) -> HTTPException:
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"rppType tidak didukung: {rpp_type}",
        )
