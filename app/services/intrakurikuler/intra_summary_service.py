# from __future__ import annotations

# import json
# from typing import Any

# from app.schemas.kina_schema import KinaSummaryRequest, KinaSummaryResponse
# from app.services.llm_client import LLMClient
# from app.utils.text_cleaner import compact_text


# class IntraSummaryService:
#     def __init__(self, llm_client: LLMClient | None = None) -> None:
#         self.llm_client = llm_client or LLMClient()

#     async def summarize(self, payload: KinaSummaryRequest) -> KinaSummaryResponse:
#         fallback = self._fallback_summary(payload)
#         messages = [
#             {
#                 "role": "system",
#                 "content": (
#                     "Ringkas chat Kina menjadi JSON terstruktur untuk disimpan oleh NestJS "
#                     "ke stage RPM. Jangan menyimpan data di FastAPI."
#                 ),
#             },
#             {
#                 "role": "user",
#                 "content": json.dumps(
#                     {
#                         "project": payload.project.model_dump(),
#                         "summaryType": payload.summaryType,
#                         "chatHistory": [
#                             chat.model_dump() for chat in payload.chatHistory
#                         ],
#                         "requiredResponseShape": fallback,
#                     },
#                     ensure_ascii=False,
#                 ),
#             },
#         ]
#         summary = await self.llm_client.generate_json(messages, fallback)
#         return KinaSummaryResponse(summary=summary)

#     def _fallback_summary(self, payload: KinaSummaryRequest) -> dict[str, Any]:
#         user_messages = [
#             chat.message for chat in payload.chatHistory if chat.role == "user"
#         ]
#         assistant_messages = [
#             chat.message for chat in payload.chatHistory if chat.role == "assistant"
#         ]
#         discussion = compact_text(" ".join(user_messages + assistant_messages), 360)
#         if not discussion:
#             discussion = "Belum ada percakapan yang cukup untuk diringkas."

#         return {
#             "discussionSummary": discussion,
#             "learningStrategy": "Strategi pembelajaran disusun dari keputusan chat Kina.",
#             "activityFlowDecision": {
#                 "opening": "Guru membuka pembelajaran dengan pertanyaan pemantik.",
#                 "mainActivity": "Siswa melakukan aktivitas utama sesuai topik dan konteks kelas.",
#                 "closing": "Guru memberi penguatan dan refleksi singkat.",
#             },
#             "differentiationPlan": {
#                 "support": "Siswa yang membutuhkan bantuan diberi contoh atau panduan bertahap.",
#                 "enrichment": "Siswa cepat diberi tantangan lanjutan yang relevan.",
#             },
#             "assessmentFocus": "Pemahaman konsep, partisipasi, dan kemampuan menerapkan materi.",
#         }


from __future__ import annotations

import json
from typing import Any

from app.schemas.kina_schema import KinaSummaryRequest, KinaSummaryResponse
from app.services.llm_client import LLMClient
from app.utils.text_cleaner import compact_text


class IntraSummaryService:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()

    async def summarize(self, payload: KinaSummaryRequest) -> KinaSummaryResponse:
        fallback = self._fallback_summary(payload)

        messages = [
            {
                "role": "system",
                "content": self._build_system_prompt(),
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

        summary = await self.llm_client.generate_json(
            messages,
            fallback,
            temperature=0.25,
        )

        return KinaSummaryResponse(summary=summary)

    def _build_system_prompt(self) -> str:
        return """
Anda adalah AI Petunjukku yang bertugas merangkum diskusi Kina Chat menjadi contentJson Stage 3 RPM Intrakurikuler.

Tugas Anda:
- Baca seluruh chatHistory antara guru dan Kina.
- Ambil keputusan akhir dari diskusi, bukan semua percakapan mentah.
- Susun hasilnya menjadi JSON terstruktur untuk Stage 3.
- Jangan membuat dokumen final.
- Jangan membuat PDF/DOCX.
- Jangan menambahkan penjelasan di luar JSON.

Stage 3 berisi rancangan strategi dan alur pembelajaran.

Wajib kembalikan JSON valid dengan struktur:
{
  "discussionSummary": "",
  "learningStrategy": "",
  "pedagogicalApproach": "",
  "facilityAndTechnologyUse": "",
  "digitalPlatform": "",
  "finalStudentProduct": "",
  "activityFlowDecision": {
    "opening": "",
    "mainActivity": "",
    "closing": ""
  },
  "differentiationPlan": {
    "support": "",
    "enrichment": ""
  },
  "teacherNotes": "",
  "stage3CompletionStatus": "complete"
}

Aturan isi:
- discussionSummary: ringkasan singkat keputusan diskusi.
- learningStrategy: gaya pembelajaran yang dipilih guru.
- pedagogicalApproach: pendekatan pedagogis/model pembelajaran yang disepakati.
- facilityAndTechnologyUse: bagaimana fasilitas dan teknologi dimanfaatkan.
- digitalPlatform: platform digital yang dipakai. Jika tidak ada, isi "Tidak digunakan".
- finalStudentProduct: produk atau kinerja akhir murid.
- activityFlowDecision.opening: kegiatan pembuka pembelajaran.
- activityFlowDecision.mainActivity: kegiatan inti pembelajaran.
- activityFlowDecision.closing: kegiatan penutup pembelajaran.
- differentiationPlan.support: dukungan untuk siswa yang membutuhkan bantuan.
- differentiationPlan.enrichment: pengayaan untuk siswa yang lebih cepat.
- teacherNotes: catatan penting dari preferensi guru.
- stage3CompletionStatus: isi "complete" jika informasi utama sudah cukup.

Jika ada informasi yang tidak disebut eksplisit oleh guru:
- Jangan kosongkan.
- Isi dengan inferensi yang paling aman berdasarkan chatHistory dan konteks project.
- Tetap tulis secara realistis dan tidak berlebihan.
""".strip()

    def _fallback_summary(self, payload: KinaSummaryRequest) -> dict[str, Any]:
        user_messages = [
            chat.message for chat in payload.chatHistory if chat.role == "user"
        ]
        assistant_messages = [
            chat.message for chat in payload.chatHistory if chat.role == "assistant"
        ]

        discussion = compact_text(" ".join(user_messages + assistant_messages), 600)
        if not discussion:
            discussion = "Diskusi Stage 3 belum cukup panjang, tetapi rancangan awal tetap disusun berdasarkan konteks pembelajaran."

        return {
            "discussionSummary": discussion,
            "learningStrategy": "Studi kasus dan diskusi kelompok kecil",
            "pedagogicalApproach": "Mini-PjBL ringan dengan arahan guru",
            "facilityAndTechnologyUse": (
                "HP siswa, internet terbatas, papan tulis, dan proyektor dimanfaatkan "
                "untuk mencari contoh pola sederhana, membahas bentuk aljabar, dan "
                "menyajikan hasil diskusi kelompok."
            ),
            "digitalPlatform": "Google Slides",
            "finalStudentProduct": (
                "Presentasi kelompok singkat tentang contoh penerapan polinomial sederhana."
            ),
            "activityFlowDecision": {
                "opening": (
                    "Guru membuka pembelajaran dengan pertanyaan pemantik tentang pola bilangan "
                    "dalam kehidupan sehari-hari."
                ),
                "mainActivity": (
                    "Siswa berdiskusi dalam kelompok kecil untuk mengamati pola, menyusun bentuk "
                    "aljabar sederhana, dan menjelaskan unsur polinomial."
                ),
                "closing": (
                    "Setiap kelompok menyampaikan hasil diskusi, lalu guru memberi penguatan "
                    "dan refleksi singkat."
                ),
            },
            "differentiationPlan": {
                "support": (
                    "Siswa yang membutuhkan bantuan diberi contoh bertahap dan panduan pertanyaan."
                ),
                "enrichment": (
                    "Siswa yang lebih cepat diminta membuat contoh pola tambahan dan menjelaskan "
                    "bentuk polinomialnya."
                ),
            },
            "teacherNotes": "Guru menginginkan aktivitas yang tidak terlalu berat, tetap terarah, dan sesuai dengan kondisi kelas.",
            "stage3CompletionStatus": "complete",
        }
