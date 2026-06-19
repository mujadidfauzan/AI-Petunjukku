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
  "learningStyle": "",
  "pedagogicalPreference": "",
  "learningEnvironment": "",
  "implementationDuration": "",
  "facilitiesTechnologyUse": "",
  "digitalUse": "",
  "partnership": "",
  "finalProjectForm": "",
  "projectAssessment": "",
  "stageCompletionSummary": {
    "learning_style": {"complete": false, "summary": ""},
    "pedagogical_preference": {"complete": false, "summary": ""},
    "learning_environment": {"complete": false, "summary": ""},
    "implementation_duration": {"complete": false, "summary": ""},
    "facility_technology_use": {"complete": false, "summary": ""},
    "digital_use": {"complete": false, "summary": ""},
    "partnership": {"complete": false, "summary": ""},
    "final_project_form": {"complete": false, "summary": ""},
    "project_assessment": {"complete": false, "summary": ""}
  },
  "finalProduct": "",
  "activitiesAndSchedule": "",
  "facilitiesTechnologyPartnership": "",
  "assessmentReflection": "",
  "teacherNotes": "",
  "projectCompletionStatus": "complete"
}

Aturan isi:
- learningStyle berisi gaya pembelajaran yang paling sesuai untuk siswa.
- pedagogicalPreference berisi pendekatan/preferensi pedagogis.
- learningEnvironment berisi lingkungan/tempat belajar proyek.
- implementationDuration berisi lama pelaksanaan, jumlah tahap, atau jumlah pertemuan.
- facilitiesTechnologyUse berisi fasilitas/teknologi dan cara pemanfaatannya.
- digitalUse berisi pemanfaatan digital, aplikasi, dokumentasi, atau platform.
- partnership berisi keputusan kemitraan, termasuk tanpa mitra jika itu pilihan guru.
- finalProjectForm berisi bentuk proyek akhir siswa.
- projectAssessment berisi cara penilaian proyek.
- Field legacy finalProduct, activitiesAndSchedule, facilitiesTechnologyPartnership,
  dan assessmentReflection harus diisi dari field baru yang sepadan untuk kompatibilitas.
- teacherNotes berisi preferensi penting guru.
- projectCompletionStatus isi "complete" jika 9 data utama sudah cukup.

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
        learning_style = self._find_recent_decision(
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
            exclude=("asesmen", "rubrik"),
        )
        pedagogical_preference = self._find_recent_decision(
            user_messages,
            (
                "preferensi pedagogis",
                "pendekatan pedagogis",
                "model pembelajaran",
                "strategi pembelajaran",
                "inkuiri",
                "kolaboratif",
                "diferensiasi",
                "mini-pjbl",
            ),
            "Preferensi pedagogis menggunakan pendekatan proyek terbimbing dan kolaboratif.",
        )
        learning_environment = self._find_recent_decision(
            user_messages,
            (
                "lingkungan belajar",
                "area belajar",
                "tempat belajar",
                "kelas",
                "halaman sekolah",
                "kantin",
                "perpustakaan",
                "luar kelas",
            ),
            "Lingkungan belajar mengikuti konteks sekolah dan proyek yang dipilih.",
        )
        implementation_duration = self._find_recent_decision(
            user_messages,
            (
                "lama pelaksanaan",
                "durasi",
                "pertemuan",
                "tahap",
                "minggu",
                "jp",
                "jam",
                "menit",
            ),
            "Lama pelaksanaan mengikuti durasi dan batasan pada Stage 1.",
            exclude=("asesmen", "rubrik", "kriteria"),
        )
        facilities_technology = self._find_recent_decision(
            user_messages,
            (
                "fasilitas",
                "teknologi",
                "proyektor",
                "gawai",
                "laptop",
                "kamera",
                "internet",
                "alat tulis",
            ),
            "Fasilitas dan teknologi memakai sumber daya yang tersedia di sekolah.",
        )
        digital_use = self._find_recent_decision(
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
        )
        partnership = self._find_recent_decision(
            user_messages,
            (
                "kemitraan",
                "mitra",
                "narasumber",
                "orang tua",
                "komunitas",
                "warga",
                "tanpa mitra",
            ),
            "Kemitraan bersifat opsional dan dapat dijalankan tanpa mitra luar jika lebih realistis.",
        )
        final_project_form = self._find_recent_decision(
            user_messages,
            (
                "bentuk proyek akhir",
                "produk akhir",
                "aksi akhir",
                "poster",
                "infografis",
                "laporan",
                "video",
                "prototipe",
                "presentasi",
            ),
            "Bentuk proyek akhir mengikuti produk yang dipilih pada Stage 2.",
            exclude=("asesmen", "rubrik", "kriteria"),
        )
        project_assessment = self._find_recent_decision(
            user_messages,
            (
                "penilaian proyek",
                "asesmen",
                "penilaian",
                "rubrik",
                "refleksi",
                "presentasi",
                "bukti",
                "kriteria",
            ),
            "Penilaian proyek menilai proses, produk akhir, presentasi, kontribusi siswa, dan refleksi singkat.",
        )
        facilities_partnership = compact_text(
            " ".join(
                part for part in (facilities_technology, partnership) if part
            ),
            900,
        )
        return {
            "discussionSummary": discussion,
            "learningStyle": learning_style,
            "pedagogicalPreference": pedagogical_preference,
            "learningEnvironment": learning_environment,
            "implementationDuration": implementation_duration,
            "facilitiesTechnologyUse": facilities_technology,
            "digitalUse": digital_use,
            "partnership": partnership,
            "finalProjectForm": final_project_form,
            "projectAssessment": project_assessment,
            "stageCompletionSummary": {
                "learning_style": {"complete": bool(learning_style), "summary": learning_style},
                "pedagogical_preference": {"complete": bool(pedagogical_preference), "summary": pedagogical_preference},
                "learning_environment": {"complete": bool(learning_environment), "summary": learning_environment},
                "implementation_duration": {"complete": bool(implementation_duration), "summary": implementation_duration},
                "facility_technology_use": {"complete": bool(facilities_technology), "summary": facilities_technology},
                "digital_use": {"complete": bool(digital_use), "summary": digital_use},
                "partnership": {"complete": bool(partnership), "summary": partnership},
                "final_project_form": {"complete": bool(final_project_form), "summary": final_project_form},
                "project_assessment": {"complete": bool(project_assessment), "summary": project_assessment},
            },
            "finalProduct": final_project_form,
            "activitiesAndSchedule": implementation_duration,
            "facilitiesTechnologyPartnership": facilities_partnership,
            "assessmentReflection": project_assessment,
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
