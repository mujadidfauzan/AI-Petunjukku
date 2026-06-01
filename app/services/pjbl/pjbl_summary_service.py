from __future__ import annotations

import json
from typing import Any

from app.schemas.kina_schema import KinaSummaryRequest, KinaSummaryResponse
from app.services.llm_client import LLMClient
from app.utils.text_cleaner import compact_text


class PjblSummaryService:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()

    async def summarize(self, payload: KinaSummaryRequest) -> KinaSummaryResponse:
        fallback = self._fallback_summary(payload)
        messages = [
            {
                "role": "system",
                "content": (
                    "Ringkas chat Kina menjadi JSON terstruktur untuk disimpan oleh NestJS "
                    "ke stage RPP. Jangan menyimpan data di FastAPI."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "project": payload.project.model_dump(),
                        "summaryType": payload.summaryType,
                        "chatHistory": [
                            chat.model_dump() for chat in payload.chatHistory
                        ],
                        "requiredResponseShape": fallback,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        summary = await self.llm_client.generate_json(messages, fallback)
        return KinaSummaryResponse(summary=summary)

    def _fallback_summary(self, payload: KinaSummaryRequest) -> dict[str, Any]:
        user_messages = [
            chat.message for chat in payload.chatHistory if chat.role == "user"
        ]
        assistant_messages = [
            chat.message for chat in payload.chatHistory if chat.role == "assistant"
        ]
        discussion = compact_text(" ".join(user_messages + assistant_messages), 360)
        if not discussion:
            discussion = "Belum ada percakapan yang cukup untuk diringkas."

        return {
            "discussionSummary": discussion,
            "learningStrategy": "Strategi pembelajaran disusun dari keputusan chat Kina.",
            "activityFlowDecision": {
                "opening": "Guru membuka pembelajaran dengan pertanyaan pemantik.",
                "mainActivity": "Siswa melakukan aktivitas utama sesuai topik dan konteks kelas.",
                "closing": "Guru memberi penguatan dan refleksi singkat.",
            },
            "differentiationPlan": {
                "support": "Siswa yang membutuhkan bantuan diberi contoh atau panduan bertahap.",
                "enrichment": "Siswa cepat diberi tantangan lanjutan yang relevan.",
            },
            "assessmentFocus": "Pemahaman konsep, partisipasi, dan kemampuan menerapkan materi.",
        }
