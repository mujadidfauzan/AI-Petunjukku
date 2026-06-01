from __future__ import annotations

import json
from typing import Any

from app.schemas.recommendation_schema import (
    RecommendStageRequest,
    RecommendStageResponse,
)
from app.services.llm_client import LLMClient
from app.services.prompt_builder_service import PromptBuilderService
from app.services.rag_service import RAGService
from app.services.pjbl.pjbl_prompt_templates import PJBL_RECOMMENDATION_SYSTEM_PROMPT


class PjblRecommendationService:
    def __init__(
        self,
        rag_service: RAGService | None = None,
        llm_client: LLMClient | None = None,
        prompt_builder: PromptBuilderService | None = None,
    ) -> None:
        self.rag_service = rag_service or RAGService()
        self.llm_client = llm_client or LLMClient()
        self.prompt_builder = prompt_builder or PromptBuilderService()

    async def recommend(self, payload: RecommendStageRequest) -> RecommendStageResponse:
        target_stage = payload.targetStage
        recommendation_type = str(
            target_stage.get("recommendationType") or "stage_recommendation"
        )
        target_stage_number = target_stage.get("stageNumber")
        topic = str(target_stage.get("topic") or payload.project.title or "")
        references = []
        fallback = self._fallback_recommendations(payload, recommendation_type, references)
        messages = [
            {
                "role": "system",
                "content": PJBL_RECOMMENDATION_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "project": payload.project.model_dump(),
                        "teacherProfile": payload.teacherProfile.model_dump()
                        if payload.teacherProfile
                        else {},
                        "school": payload.school.model_dump() if payload.school else {},
                        "teacherClass": payload.teacherClass.model_dump()
                        if payload.teacherClass
                        else {},
                        "previousStages": [
                            stage.model_dump() for stage in payload.previousStages
                        ],
                        "targetStage": target_stage,
                        "ragReferences": [
                            reference.model_dump() for reference in references
                        ],
                        "requiredResponseShape": fallback,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        recommendations = await self.llm_client.generate_json(messages, fallback)
        return RecommendStageResponse(
            rppType=payload.project.rppType,
            recommendationType=recommendation_type,
            targetStageNumber=int(target_stage_number)
            if target_stage_number is not None
            else None,
            ragReferences=references,
            recommendations=recommendations,
        )

    def _fallback_recommendations(
        self,
        payload: RecommendStageRequest,
        recommendation_type: str,
        references: list[Any],
    ) -> dict[str, Any]:
        topic = payload.targetStage.get("topic") or payload.project.title or "topik pembelajaran"
        stage_one = next(
            (stage.contentJson for stage in payload.previousStages if stage.stageNumber == 1),
            {},
        )
        local_issue = stage_one.get("localIssue") or payload.targetStage.get("topic") or topic
        return {
            "recommendedProjectTitle": f"Proyek Kontekstual: {local_issue}",
            "projectTheme": str(local_issue),
            "projectBackground": (
                "Proyek disusun dari konteks Stage 1, kondisi sekolah, "
                "karakteristik siswa, fasilitas, dan batasan pelaksanaan."
            ),
            "projectObjectives": [
                f"Peserta didik mampu mengidentifikasi masalah terkait {local_issue}.",
                "Peserta didik mampu menganalisis penyebab dan dampak masalah.",
                "Peserta didik mampu merancang solusi sederhana secara kolaboratif.",
            ],
            "drivingQuestion": f"Bagaimana siswa dapat membuat aksi nyata untuk merespons {local_issue}?",
            "studentProduct": ["Laporan observasi", "Produk atau kampanye solusi", "Presentasi proyek"],
            "projectActivitiesOverview": [
                "Observasi masalah di lingkungan terdekat.",
                "Diskusi penyebab, dampak, dan alternatif solusi.",
                "Perancangan dan pembuatan produk proyek.",
                "Presentasi hasil dan refleksi.",
            ],
            "feasibilityNotes": "Proyek dibuat realistis berdasarkan konteks Stage 1 dan fasilitas sekolah.",
            "riskMitigation": [
                {
                    "risk": "Waktu atau fasilitas terbatas.",
                    "mitigation": "Skala proyek dibuat sederhana dan dekat dengan aktivitas sekolah.",
                }
            ],
            "reasoningSummary": (
                f"Rekomendasi {recommendation_type} disusun dari konteks project, "
                "terutama semua informasi yang tersedia pada Stage 1."
            ),
        }
