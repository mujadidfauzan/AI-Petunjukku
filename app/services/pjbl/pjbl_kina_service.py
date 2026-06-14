from __future__ import annotations

import json
import re
from typing import Any

from app.schemas.common_schema import UsedReferenceSchema
from app.schemas.kina_schema import KinaChatRequest, KinaChatResponse
from app.schemas.rag_schema import RagReference
from app.services.llm_client import LLMClient
from app.services.pjbl.pjbl_prompt_templates import PJBL_KINA_SYSTEM_PROMPT
from app.services.prompt_builder_service import PromptBuilderService
from app.services.rag_service import RAGService
from app.utils.text_cleaner import compact_text


COMPLETION_MESSAGE = (
    "Terima kasih, rancangan proyek Anda sudah selesai dan siap digunakan untuk "
    "tahap berikutnya."
)

DISCUSSION_STAGES: tuple[tuple[str, str], ...] = (
    ("focus_scope", "fokus dan ruang lingkup proyek"),
    ("final_product", "produk atau aksi akhir"),
    ("activities_schedule", "alur kegiatan dan jadwal"),
    ("roles_support", "pembagian peran dan pendampingan"),
    ("facilities_partnership", "fasilitas, teknologi, dan kemitraan"),
    ("risk_mitigation", "risiko dan mitigasi"),
    ("assessment_reflection", "asesmen, presentasi, dan refleksi"),
)

STAGE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "focus_scope": (
        "fokus proyek",
        "ruang lingkup",
        "masalah utama",
        "tujuan proyek",
        "driving question",
        "drivingquestion",
        "pertanyaan mendasar",
        "projectobjectives",
        "proyek ini",
    ),
    "final_product": (
        "produk akhir",
        "aksi akhir",
        "poster",
        "kampanye",
        "prototipe",
        "laporan",
        "infografis",
        "pameran",
        "video",
        "karya",
        "studentproduct",
    ),
    "activities_schedule": (
        "alur kegiatan",
        "jadwal",
        "tahapan proyek",
        "timeline",
        "minggu pertama",
        "pertemuan",
        "durasi kegiatan",
        "projectactivitiesoverview",
        "activityflowdecision",
        "projectduration",
    ),
    "roles_support": (
        "pembagian peran",
        "peran siswa",
        "kerja kelompok",
        "ketua kelompok",
        "anggota kelompok",
        "pendampingan",
        "monitoring guru",
        "studentroles",
        "teacherfacilitation",
    ),
    "facilities_partnership": (
        "fasilitas",
        "teknologi",
        "proyektor",
        "internet",
        "gawai",
        "kemitraan",
        "mitra",
        "orang tua",
        "komunitas",
        "tanpa mitra",
        "facilityandtechnologyuse",
        "partnership",
    ),
    "risk_mitigation": (
        "risiko",
        "mitigasi",
        "keselamatan",
        "perizinan",
        "izin kegiatan",
        "keterlambatan",
        "keterbatasan biaya",
        "risiko proyek",
        "riskmitigation",
    ),
    "assessment_reflection": (
        "asesmen",
        "penilaian",
        "rubrik",
        "bukti proses",
        "kontribusi individu",
        "umpan balik",
        "refleksi siswa",
        "kriteria keberhasilan",
        "assessmentfocus",
        "reflection",
    ),
}

DECISION_PATTERN = re.compile(
    r"\b(setuju|sepakat|memilih|pilih|ditetapkan|tetapkan|gunakan|menggunakan|"
    r"akan|ingin|cocok|sudah jelas|sudah cukup|tetap|tanpa|tidak menggunakan)\b",
    flags=re.IGNORECASE,
)
UNCERTAINTY_PATTERN = re.compile(
    r"\b(bingung|ragu|belum tahu|belum yakin|minta saran|butuh saran|"
    r"apa saja opsinya|opsi apa|pilihan apa)\b",
    flags=re.IGNORECASE,
)
PROJECT_CHANGE_PATTERN = re.compile(
    r"(?:\b(?:ubah|ganti|mengganti|revisi)\b.{0,50}\bproyek\b|"
    r"\bproyek\b.{0,50}\b(?:ubah|ganti|mengganti|revisi)\b)",
    flags=re.IGNORECASE | re.DOTALL,
)
GLOBAL_COMPLETION_PATTERN = re.compile(
    r"\b(semua(?:nya)? (?:sudah )?(?:jelas|selesai|lengkap)|"
    r"sudah lengkap|cukup semua|rancangan sudah selesai)\b",
    flags=re.IGNORECASE,
)

INTERNAL_TERM_REPLACEMENTS: tuple[tuple[str, str], ...] = (
    (r"\bcontentJson\b", "data rancangan"),
    (r"\bchatHistory\b", "riwayat diskusi"),
    (r"\bstage_context\b", "konteks tahapan"),
    (r"\bproject_context\b", "konteks proyek"),
    (r"\brag_context\b", "referensi pendukung"),
    (r"\blatest_message\b", "pesan terbaru"),
    (r"\bactive_stage\b", "bagian diskusi"),
    (r"\bDTO\b", "data masukan"),
    (r"\bschema\b", "struktur data"),
)


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
        analysis = self._analyze_stage(payload)
        references = await self.rag_service.search_for_context(
            query=payload.message,
            subject=payload.project.subject,
            phase=payload.project.phase,
            top_k=3,
        )
        fallback = self._fallback_reply(payload, analysis)
        messages = self._build_messages(payload, references, analysis)
        generated_reply = await self.llm_client.generate_text(
            messages,
            fallback,
            temperature=0.55,
        )
        reply = self._sanitize_reply(
            generated_reply,
            fallback=fallback,
            is_complete=analysis["is_complete"],
            limit_options=analysis["teacher_uncertain"],
        )
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
            suggestedFollowUpQuestions=self._suggested_questions(analysis),
        )

    def _build_messages(
        self,
        payload: KinaChatRequest,
        references: list[RagReference],
        analysis: dict[str, Any],
    ) -> list[dict[str, str]]:
        history = [chat.model_dump() for chat in payload.chatHistory[-12:]]
        user_prompt = "\n\n".join(
            [
                "KONTEKS PROJECT:",
                self.prompt_builder.project_context(payload.project),
                "DATA STAGE YANG TERSEDIA:",
                self.prompt_builder.stages_context(payload.stages),
                "REFERENSI RAG JIKA RELEVAN:",
                self.prompt_builder.rag_context(references),
                "RIWAYAT DISKUSI TERAKHIR:",
                json.dumps(history, ensure_ascii=False, indent=2),
                f"PESAN TERBARU GURU:\n{payload.message}",
                f"POSISI DISKUSI SAAT INI:\n{analysis['active_label']}",
                f"INSTRUKSI UNTUK GILIRAN INI:\n{self._turn_instruction(analysis)}",
            ]
        )
        return [
            {"role": "system", "content": PJBL_KINA_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

    def _analyze_stage(self, payload: KinaChatRequest) -> dict[str, Any]:
        evidence = {key: False for key, _ in DISCUSSION_STAGES}
        self._apply_saved_stage_evidence(payload, evidence)

        previous_assistant = ""
        for chat in payload.chatHistory:
            if chat.role == "assistant":
                previous_assistant = chat.message
                continue
            if chat.role == "user":
                self._apply_user_decision(chat.message, previous_assistant, evidence)

        self._apply_user_decision(payload.message, previous_assistant, evidence)

        if GLOBAL_COMPLETION_PATTERN.search(payload.message):
            context = f"{previous_assistant}\n{payload.message}"
            matched_count = sum(
                self._matches_stage(context, key) for key, _ in DISCUSSION_STAGES
            )
            if matched_count >= 5 or sum(evidence.values()) >= 5:
                evidence = {key: True for key, _ in DISCUSSION_STAGES}

        # Memilih produk berarti fokus proyek sudah dipahami. Bukti dari bagian
        # yang lebih akhir tidak otomatis menyelesaikan bagian sebelumnya.
        if evidence["final_product"]:
            evidence["focus_scope"] = True

        active_stage = "complete"
        active_label = "selesai"
        completed_count = 0
        for key, label in DISCUSSION_STAGES:
            if evidence[key]:
                completed_count += 1
                continue
            active_stage = key
            active_label = label
            break

        is_complete = completed_count == len(DISCUSSION_STAGES)
        return {
            "active_stage": active_stage,
            "active_label": active_label,
            "evidence": evidence,
            "change_requested": bool(PROJECT_CHANGE_PATTERN.search(payload.message)),
            "teacher_uncertain": bool(UNCERTAINTY_PATTERN.search(payload.message)),
            "is_complete": is_complete,
        }

    def _apply_saved_stage_evidence(
        self,
        payload: KinaChatRequest,
        evidence: dict[str, bool],
    ) -> None:
        for stage in payload.stages:
            if stage.stageNumber <= 2 or not stage.contentJson:
                continue
            stage_text = self._flatten(stage.contentJson)
            for key, _ in DISCUSSION_STAGES:
                if self._matches_stage(stage_text, key):
                    evidence[key] = True

    def _apply_user_decision(
        self,
        message: str,
        previous_assistant: str,
        evidence: dict[str, bool],
    ) -> None:
        if not message or UNCERTAINTY_PATTERN.search(message):
            return
        if not DECISION_PATTERN.search(message):
            return

        direct_matches = [
            key for key, _ in DISCUSSION_STAGES if self._matches_stage(message, key)
        ]
        if direct_matches:
            for key in direct_matches:
                evidence[key] = True
            return

        for key, _ in DISCUSSION_STAGES:
            if self._matches_stage(previous_assistant, key):
                evidence[key] = True
                return

    def _matches_stage(self, text: str, stage_key: str) -> bool:
        lowered = text.casefold()
        return any(keyword in lowered for keyword in STAGE_KEYWORDS[stage_key])

    def _flatten(self, value: Any) -> str:
        if isinstance(value, dict):
            return " ".join(
                f"{key} {self._flatten(item)}" for key, item in value.items()
            )
        if isinstance(value, list):
            return " ".join(self._flatten(item) for item in value)
        return str(value or "")

    def _turn_instruction(self, analysis: dict[str, Any]) -> str:
        if analysis["change_requested"]:
            return (
                "Guru meminta perubahan proyek. Jelaskan dampaknya terhadap tujuan, "
                "durasi, fasilitas, biaya, dan risiko sebelum mengarahkan perubahan."
            )
        if analysis["is_complete"]:
            return (
                "Ringkas keputusan akhir secara singkat, jangan ajukan pertanyaan, dan "
                f"akhiri dengan kalimat persis: {COMPLETION_MESSAGE}"
            )
        return (
            f"Utamakan {analysis['active_label']}. Jika guru bertanya tentang bagian "
            "lain, jawab seperlunya lalu kembalikan pembahasan ke bagian aktif. "
            "Pertahankan keputusan yang sudah disepakati dan ajukan maksimal satu "
            "pertanyaan ringan."
        )

    def _fallback_reply(
        self,
        payload: KinaChatRequest,
        analysis: dict[str, Any],
    ) -> str:
        project_title = self._project_title(payload)

        if analysis["change_requested"]:
            return (
                f"Baik, perubahan arah dari proyek {project_title} dapat dipertimbangkan. "
                "Perubahan itu perlu diperiksa terhadap tujuan proyek, durasi, fasilitas, "
                "biaya, dan risiko agar rancangan tetap realistis.\n\n"
                "Bagian utama proyek mana yang ingin Bapak/Ibu ubah?"
            )
        if analysis["is_complete"]:
            return (
                f"Baik, rancangan {project_title} sudah mencakup fokus proyek, produk "
                "akhir, alur kegiatan, pembagian peran, fasilitas, mitigasi risiko, "
                "serta asesmen dan refleksi. Seluruh keputusan tersebut dapat menjadi "
                "dasar pelaksanaan proyek yang terarah.\n\n"
                f"{COMPLETION_MESSAGE}"
            )
        if analysis["teacher_uncertain"]:
            return self._uncertainty_reply(project_title, analysis["active_stage"])

        latest_decision = compact_text(payload.message, 180)
        active_stage = analysis["active_stage"]
        if active_stage == "focus_scope":
            return (
                f"Baik, kita akan mematangkan {project_title} tanpa mengganti arah "
                "proyek yang sudah dipilih. Fokus awalnya perlu dibatasi pada masalah, "
                "tujuan, dan pertanyaan mendasar yang realistis bagi siswa.\n\n"
                "Masalah utama apa yang paling perlu dijawab melalui proyek ini?"
            )
        if active_stage == "final_product":
            return (
                f"Baik, fokus {project_title} sudah cukup jelas. Berikutnya, produk atau "
                "aksi akhir perlu dipilih agar benar-benar menjawab masalah proyek dan "
                "tetap sesuai waktu serta fasilitas sekolah.\n\n"
                "Produk akhir apa yang paling realistis dibuat siswa?"
            )
        if active_stage == "activities_schedule":
            return (
                f"Baik, pilihan guru sudah saya tangkap: {latest_decision}. Keputusan ini "
                "akan menjadi dasar penyusunan kegiatan proyek dari pengenalan masalah "
                "hingga presentasi dan refleksi.\n\n"
                "Berapa lama waktu yang tersedia untuk menjalankan rangkaian proyek ini?"
            )
        if active_stage == "roles_support":
            return (
                "Baik, alur dan waktu proyek sudah cukup terarah. Agar semua siswa "
                "berkontribusi, pembagian kelompok, peran anggota, dan cara guru "
                "memantau kemajuan perlu disepakati.\n\n"
                "Apakah siswa akan bekerja dalam kelompok kecil dengan peran yang berbeda?"
            )
        if active_stage == "facilities_partnership":
            return (
                "Baik, pembagian peran siswa sudah dapat menjadi dasar pelaksanaan. "
                "Selanjutnya kita perlu memilih fasilitas dan teknologi yang benar-benar "
                "tersedia, sedangkan kemitraan tetap bersifat opsional.\n\n"
                "Fasilitas sekolah mana yang paling realistis digunakan untuk proyek ini?"
            )
        if active_stage == "risk_mitigation":
            return (
                "Baik, kebutuhan fasilitas dan dukungan proyek sudah cukup jelas. "
                "Sekarang kita perlu mengantisipasi risiko yang paling mungkin terjadi "
                "agar proyek tetap aman, hemat biaya, dan selesai tepat waktu.\n\n"
                "Risiko apa yang paling Bapak/Ibu khawatirkan selama pelaksanaan proyek?"
            )
        return (
            "Baik, risiko utama dan langkah pencegahannya sudah cukup terarah. Bagian "
            "terakhir adalah menentukan bukti proses, kualitas produk, kontribusi siswa, "
            "cara presentasi, dan refleksi yang akan dinilai.\n\n"
            "Aspek apa yang paling penting dinilai dari proses dan hasil proyek siswa?"
        )

    def _uncertainty_reply(self, project_title: str, active_stage: str) -> str:
        options: dict[str, tuple[str, str, str]] = {
            "focus_scope": (
                "batasi proyek pada satu lokasi sekolah agar observasi mudah",
                "batasi pada satu kelompok sasaran agar solusi lebih terarah",
                "batasi pada satu kebiasaan utama agar dampaknya dapat diamati",
            ),
            "final_product": (
                "media kampanye sederhana karena murah dan mudah dipresentasikan",
                "laporan temuan karena kuat untuk menunjukkan proses pengumpulan data",
                "prototipe atau aksi kecil karena memberi pengalaman praktik langsung",
            ),
            "activities_schedule": (
                "alur tiga tahap untuk durasi singkat",
                "alur lima tahap untuk proyek beberapa minggu",
                "alur mingguan dengan target kecil agar mudah dipantau",
            ),
            "roles_support": (
                "kelompok kecil dengan ketua, pencatat, dan penyaji",
                "peran bergilir agar kontribusi siswa lebih merata",
                "pembagian berdasarkan minat dengan lembar monitoring guru",
            ),
            "facilities_partnership": (
                "gunakan fasilitas kelas yang sudah tersedia",
                "gunakan gawai secara terbatas hanya untuk dokumentasi atau riset",
                "libatkan mitra internal sekolah tanpa pihak luar",
            ),
            "risk_mitigation": (
                "sederhanakan produk untuk mencegah keterlambatan",
                "batasi alat dan bahan untuk mengendalikan biaya",
                "gunakan panduan keselamatan dan area kerja yang jelas",
            ),
            "assessment_reflection": (
                "nilai proses dan kerja sama melalui observasi",
                "nilai produk menggunakan rubrik sederhana",
                "gabungkan presentasi kelompok dengan refleksi individu",
            ),
        }
        first, second, third = options[active_stage]
        return (
            f"Wajar jika Bapak/Ibu masih ragu saat mematangkan {project_title}. Kita dapat "
            "memilih pendekatan yang paling sederhana dan sesuai kondisi sekolah.\n\n"
            f"Tiga opsi realistisnya adalah: 1) {first}; 2) {second}; atau 3) {third}. "
            "Opsi mana yang paling sesuai dengan kondisi siswa?"
        )

    def _project_title(self, payload: KinaChatRequest) -> str:
        for stage in payload.stages:
            if stage.stageNumber != 2:
                continue
            title = self._find_value(
                stage.contentJson,
                ("selectedProjectTitle", "recommendedProjectTitle", "projectTitle"),
            )
            if title:
                return str(title)
        return payload.project.title or payload.project.subject or "proyek PjBL ini"

    def _find_value(self, value: Any, keys: tuple[str, ...]) -> Any | None:
        if isinstance(value, dict):
            for key in keys:
                candidate = value.get(key)
                if candidate:
                    return candidate
            for item in value.values():
                candidate = self._find_value(item, keys)
                if candidate:
                    return candidate
        if isinstance(value, list):
            for item in value:
                candidate = self._find_value(item, keys)
                if candidate:
                    return candidate
        return None

    def _suggested_questions(self, analysis: dict[str, Any]) -> list[str]:
        if analysis["is_complete"]:
            return []
        questions = {
            "focus_scope": "Apa batas masalah yang paling realistis untuk proyek ini?",
            "final_product": "Produk atau aksi akhir apa yang paling sesuai?",
            "activities_schedule": "Berapa lama durasi proyek yang tersedia?",
            "roles_support": "Bagaimana peran siswa akan dibagi dalam kelompok?",
            "facilities_partnership": "Fasilitas apa yang paling realistis digunakan?",
            "risk_mitigation": "Risiko utama apa yang perlu dicegah terlebih dahulu?",
            "assessment_reflection": "Aspek proses dan hasil apa yang akan dinilai?",
        }
        return [questions[analysis["active_stage"]]]

    def _sanitize_reply(
        self,
        reply: str,
        *,
        fallback: str,
        is_complete: bool,
        limit_options: bool,
    ) -> str:
        candidate = str(reply or "").strip()
        if not candidate or self._looks_like_json(candidate):
            candidate = fallback

        candidate = self._remove_forbidden_claims(candidate)
        candidate = self._replace_internal_terms(candidate)
        if limit_options:
            candidate = self._limit_numbered_options(candidate)
        candidate = self._limit_questions(candidate)
        candidate = self._limit_paragraphs(candidate)

        if is_complete:
            candidate = candidate.replace("?", ".")
            candidate = self._ensure_completion(candidate)

        if not candidate or self._contains_forbidden_content(candidate):
            candidate = self._limit_paragraphs(self._limit_questions(fallback))
            if is_complete:
                candidate = self._ensure_completion(candidate)
        return candidate.strip()

    def _looks_like_json(self, text: str) -> bool:
        stripped = text.strip()
        return bool(
            stripped.startswith(("{", "["))
            or "```" in stripped
            or re.search(r'"[^"\n]+"\s*:\s*', stripped)
            or re.search(r"\bberikut\s+json\b", stripped, flags=re.IGNORECASE)
        )

    def _remove_forbidden_claims(self, text: str) -> str:
        cleaned_paragraphs = []
        for paragraph in re.split(r"\n\s*\n", text):
            sentences = re.split(r"(?<=[.!?])\s+", paragraph)
            allowed = [
                sentence
                for sentence in sentences
                if not re.search(
                    r"(?:\b(?:membuat|membuatkan|menyusun|menghasilkan)\b.{0,35}"
                    r"\b(?:PDF|DOCX|file|dokumen (?:final|akhir))\b|"
                    r"\b(?:PDF|DOCX|file final|dokumen (?:final|akhir))\b)",
                    sentence,
                    flags=re.IGNORECASE,
                )
            ]
            if allowed:
                cleaned_paragraphs.append(" ".join(allowed).strip())
        return "\n\n".join(cleaned_paragraphs)

    def _replace_internal_terms(self, text: str) -> str:
        result = text
        for pattern, replacement in INTERNAL_TERM_REPLACEMENTS:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
        return result

    def _limit_numbered_options(self, text: str) -> str:
        matches = list(re.finditer(r"(?<!\w)(\d+)[.)]\s", text))
        if len(matches) <= 3:
            return text
        return text[: matches[3].start()].rstrip(" ;,\n")

    def _limit_questions(self, text: str) -> str:
        seen_question = False
        characters: list[str] = []
        for character in text:
            if character != "?":
                characters.append(character)
                continue
            if seen_question:
                characters.append(".")
            else:
                characters.append(character)
                seen_question = True
        return "".join(characters)

    def _limit_paragraphs(self, text: str) -> str:
        normalized = text.replace("\r\n", "\n").replace("\r", "\n")
        paragraphs = [
            re.sub(r"\s+", " ", paragraph).strip()
            for paragraph in re.split(r"\n\s*\n", normalized)
            if paragraph.strip()
        ]
        if not paragraphs:
            return ""
        if len(paragraphs) > 2:
            paragraphs = [paragraphs[0], " ".join(paragraphs[1:])]
        return "\n\n".join(self._truncate(paragraph, 700) for paragraph in paragraphs)

    def _truncate(self, paragraph: str, max_length: int) -> str:
        if len(paragraph) <= max_length:
            return paragraph
        candidate = paragraph[:max_length].rstrip()
        sentence_end = max(candidate.rfind("."), candidate.rfind("?"))
        if sentence_end >= 250:
            return candidate[: sentence_end + 1]
        return f"{candidate.rstrip(' ,;:')}..."

    def _ensure_completion(self, text: str) -> str:
        if text.rstrip().endswith(COMPLETION_MESSAGE):
            return text
        without_closing = text.replace(COMPLETION_MESSAGE, "").strip()
        paragraphs = [
            part.strip() for part in without_closing.split("\n\n") if part.strip()
        ]
        summary = paragraphs[0] if paragraphs else "Rancangan proyek telah lengkap."
        return f"{self._truncate(summary, 700)}\n\n{COMPLETION_MESSAGE}"

    def _contains_forbidden_content(self, text: str) -> bool:
        if self._looks_like_json(text):
            return True
        forbidden_patterns = [pattern for pattern, _ in INTERNAL_TERM_REPLACEMENTS]
        forbidden_patterns.append(
            r"\b(PDF|DOCX|dokumen (?:final|akhir)|file final)\b"
        )
        return any(
            re.search(pattern, text, flags=re.IGNORECASE)
            for pattern in forbidden_patterns
        )
