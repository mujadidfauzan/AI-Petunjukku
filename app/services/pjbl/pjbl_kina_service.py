from __future__ import annotations

import json

from app.schemas.common_schema import UsedReferenceSchema
from app.schemas.kina_schema import KinaChatRequest, KinaChatResponse
from app.services.llm_client import LLMClient
from app.services.prompt_builder_service import PromptBuilderService
from app.services.rag_service import RAGService
from app.utils.text_cleaner import compact_text


class PjblKinaService:
    def __init__(
        self,
        rag_service: RAGService | None = None,
        llm_client: LLMClient | None = None,
        prompt_builder: PromptBuilderService | None = None,
    ) -> None:
        self.rag_service = rag_service or RAGService()
        self.llm_client = llm_client or LLMClient()
        self.prompt_builder = prompt_builder or PromptBuilderService()

    async def chat(self, payload: KinaChatRequest) -> KinaChatResponse:
        message = payload.message.strip()
        rag_query = message or payload.project.title or payload.project.subject or "PjBL"
        references = await self.rag_service.search_for_context(
            query=rag_query,
            subject=payload.project.subject,
            phase=payload.project.phase,
            top_k=3,
        )
        fallback = self._fallback_reply(payload)
        messages = [
            {
                "role": "system",
                "content": (
                    "Anda adalah Kina, chatbot AI Petunjukku untuk guru Indonesia. "
                    "Jawab singkat, praktis, dan kontekstual berdasarkan project RPM, "
                    "stage yang dikirim, chat history, dan referensi RAG. "
                    "Jangan menyimpan data dan jangan mengaku membuat file PDF/DOCX."
                ),
            },
            {
                "role": "user",
                "content": "\n\n".join(
                    [
                        "Konteks project:",
                        self.prompt_builder.project_context(payload.project),
                        "Stage yang sudah dikirim:",
                        self.prompt_builder.stages_context(payload.stages),
                        "Referensi RAG:",
                        self.prompt_builder.rag_context(references),
                        "Riwayat chat:",
                        json.dumps(
                            [chat.model_dump() for chat in payload.chatHistory[-12:]],
                            ensure_ascii=False,
                        ),
                        f"Pesan terbaru guru:\n{payload.message}",
                    ]
                ),
            },
        ]
        reply = await self.llm_client.generate_text(messages, fallback, temperature=0.55)
        return KinaChatResponse(
            reply=reply,
            usedReferences=[
                UsedReferenceSchema(
                    cpReferenceId=reference.cpReferenceId,
                    sourceTitle=reference.sourceTitle,
                    similarityScore=reference.similarityScore,
                )
                for reference in references
            ],
            suggestedFollowUpQuestions=self._follow_up_questions(payload),
        )

    def _fallback_reply(self, payload: KinaChatRequest) -> str:
        topic = payload.project.title or payload.project.subject or "pembelajaran"
        stage_text = "stage yang sudah diisi" if payload.stages else "data stage yang tersedia"
        return (
            f"Untuk {topic}, kegiatan dapat dibuat bertahap dari {stage_text}: "
            "mulai dengan pemantik singkat, lanjutkan aktivitas utama yang melibatkan siswa, "
            "lalu tutup dengan refleksi atau asesmen ringan. "
            f"Pesan guru yang saya tangkap: {compact_text(payload.message, 220)}"
        )

    def _follow_up_questions(self, payload: KinaChatRequest) -> list[str]:
        subject = payload.project.subject or "mapel ini"
        return [
            "Apakah kegiatan ini ingin dibuat dalam bentuk diskusi kelompok?",
            f"Apakah perlu saya bantu susun asesmen singkat untuk {subject}?",
        ]
