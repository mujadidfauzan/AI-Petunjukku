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
from app.services.intrakurikuler.intra_prompt_templates import (
    INTRA_RECOMMENDATION_SYSTEM_PROMPT,
)


class IntraRecommendationService:
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
        references = await self.rag_service.search_for_context(
            query=topic or recommendation_type,
            subject=payload.project.subject,
            phase=payload.project.phase,
            top_k=int(payload.options.get("topK") or 5),
        )
        fallback = self._fallback_recommendations(payload, recommendation_type, references)
        messages = [
            {
                "role": "system",
                "content": INTRA_RECOMMENDATION_SYSTEM_PROMPT,
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
        cp_summary = (
            references[0].chunkText[:260] if references else "Referensi CP belum tersedia dari RAG."
        )
        return {
            "capaianPembelajaranSummary": cp_summary,
            "alurTujuanPembelajaran": [
                {
                    "order": 1,
                    "tujuanPembelajaran": f"Peserta didik mampu memahami konsep utama pada {topic}.",
                    "rationale": "Tujuan awal membantu siswa membangun pemahaman dasar.",
                },
                {
                    "order": 2,
                    "tujuanPembelajaran": f"Peserta didik mampu menjelaskan {topic} dengan contoh kontekstual.",
                    "rationale": "Tujuan ini menghubungkan konsep dengan pengalaman siswa.",
                },
                {
                    "order": 3,
                    "tujuanPembelajaran": f"Peserta didik mampu menerapkan pemahaman {topic} dalam aktivitas belajar.",
                    "rationale": "Tujuan akhir mendorong penerapan dan refleksi.",
                },
            ],
            "suggestedEssentialQuestion": f"Mengapa {topic} penting dipahami dalam kehidupan sehari-hari?",
            "reasoningSummary": (
                f"Rekomendasi {recommendation_type} disusun dari konteks project, "
                "stage sebelumnya, dan referensi RAG yang tersedia."
            ),
        }
