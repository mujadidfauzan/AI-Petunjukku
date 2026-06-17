
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
            temperature=0.15,
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

Prinsip pengambilan keputusan:
- Keputusan utama harus berasal dari pesan guru.
- Saran dari Kina hanya boleh dimasukkan jika guru menyetujui, memilih, menguatkan, atau mengulang saran tersebut.
- Jika Kina memberi beberapa opsi, ambil hanya opsi yang dipilih guru.
- Jika guru menolak suatu opsi, jangan masukkan opsi tersebut ke summary.
- Jika guru mengganti keputusan lama, gunakan keputusan terbaru dari guru.
- Jika guru berkata "tidak digunakan", "tidak perlu", atau "tidak memakai", catat sebagai "Tidak digunakan".
- Jangan memasukkan fasilitas, platform digital, mitra, atau produk akhir hanya karena pernah disarankan Kina.
- Gunakan istilah "murid", bukan "siswa".

Stage 3 berisi rancangan strategi dan alur pembelajaran.

Wajib kembalikan JSON valid dengan struktur:
{
  "discussionSummary": "",
  "learningStrategy": "",
  "pedagogicalApproach": "",
  "facilityAndTechnologyUse": "",
  "digitalPlatform": "",
  "partnership": "",
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
- partnership: bentuk kemitraan. Jika tidak ada, isi "Tidak digunakan".
- finalStudentProduct: produk atau kinerja akhir murid.
- activityFlowDecision.opening: kegiatan pembuka pembelajaran.
- activityFlowDecision.mainActivity: kegiatan inti pembelajaran.
- activityFlowDecision.closing: kegiatan penutup pembelajaran.
- differentiationPlan.support: dukungan untuk murid yang membutuhkan bantuan.
- differentiationPlan.enrichment: pengayaan untuk murid yang lebih cepat.
- teacherNotes: catatan penting dari preferensi guru.
- stage3CompletionStatus: isi "complete" hanya jika informasi utama Stage 3 sudah cukup; isi "partial" jika masih ada keputusan utama yang belum jelas.

Jika ada informasi yang tidak disebut eksplisit oleh guru:
- Jangan mengarang detail spesifik seperti nama platform, fasilitas, mitra, atau produk.
- Boleh membuat inferensi ringan untuk activityFlowDecision dan differentiationPlan agar tetap dapat dipakai generate RPM.
- Inferensi harus realistis, umum, dan mengikuti keputusan yang sudah benar-benar muncul dalam chatHistory.
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
            "learningStrategy": "Belum dapat disimpulkan secara spesifik dari chat history.",
            "pedagogicalApproach": "Belum dapat disimpulkan secara spesifik dari chat history.",
            "facilityAndTechnologyUse": "Belum dapat disimpulkan secara spesifik dari chat history.",
            "digitalPlatform": "Tidak digunakan",
            "partnership": "Tidak digunakan",
            "finalStudentProduct": "Belum dapat disimpulkan secara spesifik dari chat history.",
            "activityFlowDecision": {
                "opening": "Guru membuka pembelajaran sesuai konteks materi dan pertanyaan pemantik yang tersedia.",
                "mainActivity": "Murid mengikuti aktivitas pembelajaran sesuai strategi yang telah dibahas dalam chat.",
                "closing": "Guru menutup pembelajaran dengan penguatan dan refleksi singkat.",
            },
            "differentiationPlan": {
                "support": "Murid yang membutuhkan bantuan diberi arahan bertahap dan contoh tambahan.",
                "enrichment": "Murid yang lebih cepat diberi tantangan lanjutan sesuai materi.",
            },
            "teacherNotes": "Ringkasan fallback dibuat karena hasil summary LLM tidak tersedia atau belum lengkap.",
            "stage3CompletionStatus": "partial",
        }