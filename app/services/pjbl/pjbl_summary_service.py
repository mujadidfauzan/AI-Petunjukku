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
            temperature=0.2,
        )
        return KinaSummaryResponse(summary=summary)

    def _build_system_prompt(self) -> str:
        return """
Anda adalah AI Petunjukku yang merangkum diskusi Kina Chat menjadi contentJson
Stage 3 RPP PjBL Kokurikuler.

Tugas:
- Baca seluruh chatHistory guru dan Kina.
- Ambil keputusan akhir, bukan semua percakapan mentah.
- Susun JSON ringkas yang siap dipakai generator RPP.
- Jangan membuat dokumen final.
- Jangan membuat PDF/DOCX.
- Jangan menambahkan teks di luar JSON.

Wajib kembalikan JSON valid dengan struktur:
{
  "discussionSummary": "",
  "focusAndScope": "",
  "learningStyle": "",
  "finalProduct": "",
  "activitiesAndSchedule": "",
  "rolesAndSupport": "",
  "facilitiesTechnologyPartnership": "",
  "digitalUse": "",
  "riskMitigation": "",
  "assessmentReflection": "",
  "teacherNotes": "",
  "projectCompletionStatus": "complete"
}

Aturan isi:
- focusAndScope berisi fokus masalah dan batas ruang lingkup proyek.
- learningStyle berisi gaya pembelajaran yang paling sesuai untuk siswa.
- finalProduct berisi produk atau aksi akhir siswa.
- activitiesAndSchedule berisi alur kegiatan dan durasi/jadwal.
- rolesAndSupport berisi peran siswa, kelompok, dan pendampingan guru.
- facilitiesTechnologyPartnership berisi fasilitas, teknologi, dan kemitraan.
- digitalUse berisi pemanfaatan digital, aplikasi, dokumentasi, atau platform.
- riskMitigation berisi risiko utama dan cara mencegahnya.
- assessmentReflection berisi cara asesmen, presentasi, bukti proses, dan refleksi.
- teacherNotes berisi preferensi penting guru.
- projectCompletionStatus isi "complete" jika sembilan bagian utama sudah cukup.

Jika informasi tidak eksplisit:
- Isi dengan inferensi paling aman dari chatHistory dan project.
- Jangan mengarang hal besar yang tidak punya dasar dari percakapan.
""".strip()

    def _fallback_summary(self, payload: KinaSummaryRequest) -> dict[str, Any]:
        user_messages = [
            chat.message for chat in payload.chatHistory if chat.role == "user"
        ]
        assistant_messages = [
            chat.message for chat in payload.chatHistory if chat.role == "assistant"
        ]
        raw_discussion = " ".join(user_messages + assistant_messages)
        discussion = compact_text(raw_discussion, 900)
        if not discussion:
            discussion = "Belum ada percakapan yang cukup untuk diringkas."

        completion_status = "complete" if self._looks_complete(raw_discussion) else "draft"
        return {
            "discussionSummary": discussion,
            "focusAndScope": self._find_recent_decision(
                user_messages,
                ("fokus proyek", "fokus", "ruang lingkup", "masalah utama"),
                "Fokus dan ruang lingkup proyek mengikuti proyek yang dipilih pada Stage 2.",
                exclude=("risiko", "mitigasi", "asesmen", "rubrik"),
                prefer_latest=False,
            ),
            "learningStyle": self._find_recent_decision(
                user_messages,
                (
                    "gaya pembelajaran",
                    "gaya belajar",
                    "visual",
                    "auditori",
                    "kinestetik",
                    "praktik langsung",
                    "diskusi",
                    "kolaboratif",
                    "diferensiasi",
                ),
                "Gaya pembelajaran disesuaikan dengan karakteristik siswa dan kebutuhan proyek.",
                exclude=("asesmen", "rubrik", "risiko", "mitigasi"),
            ),
            "finalProduct": self._find_recent_decision(
                user_messages,
                ("produk akhir", "aksi akhir", "poster infografis", "peta temuan"),
                "Produk akhir mengikuti produk yang dipilih pada Stage 2.",
                exclude=(
                    "asesmen",
                    "rubrik",
                    "kriteria",
                    "alur kegiatan",
                    "durasi",
                    "pembukaan",
                    "observasi area",
                ),
            ),
            "activitiesAndSchedule": self._find_recent_decision(
                user_messages,
                ("alur kegiatan", "jadwal", "durasi", "2 x 35", "pertemuan", "menit", "jp"),
                "Alur kegiatan mengikuti durasi dan batasan pada Stage 1.",
                exclude=("asesmen", "rubrik", "kriteria"),
            ),
            "rolesAndSupport": self._find_recent_decision(
                user_messages,
                ("peran", "kelompok", "ketua", "pencatat", "pendampingan"),
                "Peran siswa dan pendampingan guru disusun sederhana sesuai kebutuhan proyek.",
                exclude=("asesmen", "rubrik", "kriteria", "risiko", "mitigasi"),
            ),
            "facilitiesTechnologyPartnership": self._find_recent_decision(
                user_messages,
                ("fasilitas", "teknologi", "proyektor", "kemitraan", "mitra"),
                "Fasilitas dan teknologi memakai sumber daya yang tersedia di sekolah.",
            ),
            "digitalUse": self._find_recent_decision(
                user_messages,
                (
                    "pemanfaatan digital",
                    "digital",
                    "aplikasi",
                    "platform",
                    "canva",
                    "google form",
                    "google docs",
                    "google slides",
                    "padlet",
                    "dokumentasi",
                ),
                "Pemanfaatan digital digunakan seperlunya untuk dokumentasi, pengumpulan data, atau presentasi.",
                exclude=("risiko", "mitigasi"),
            ),
            "riskMitigation": self._find_recent_decision(
                user_messages,
                ("risiko", "mitigasi", "keselamatan", "izin", "panduan"),
                "Risiko utama dicegah dengan batas area, instruksi jelas, dan format kerja sederhana.",
            ),
            "assessmentReflection": self._find_recent_decision(
                user_messages,
                ("asesmen", "penilaian", "rubrik", "refleksi", "presentasi"),
                "Asesmen menilai proses, produk akhir, kontribusi siswa, dan refleksi singkat.",
            ),
            "teacherNotes": "Guru menginginkan proyek yang realistis, sederhana, dan sesuai konteks siswa.",
            "projectCompletionStatus": completion_status,
        }

    def _find_recent_decision(
        self,
        messages: list[str],
        keywords: tuple[str, ...],
        fallback: str,
        *,
        exclude: tuple[str, ...] = (),
        prefer_latest: bool = True,
    ) -> str:
        candidates = reversed(messages) if prefer_latest else messages
        for message in candidates:
            lowered = message.casefold()
            if any(keyword in lowered for keyword in keywords) and not any(
                keyword in lowered for keyword in exclude
            ):
                return compact_text(message, 450)
        return fallback

    def _looks_complete(self, text: str) -> bool:
        lowered = text.casefold()
        completion_signals = (
            "rancangan proyek anda sudah selesai",
            "sudah selesai",
            "siap digunakan untuk tahap berikutnya",
            "semua bagian utama",
        )
        return any(signal in lowered for signal in completion_signals)
