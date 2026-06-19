from __future__ import annotations

import json
import logging
import re
from time import perf_counter
from typing import Any

from app.schemas.common_schema import UsedReferenceSchema
from app.schemas.kina_schema import KinaChatRequest, KinaChatResponse
from app.schemas.rag_schema import RagReference
from app.services.llm_client import LLMClient
from app.services.pjbl.pjbl_prompt_templates import (
    PJBL_KINA_SOLVER_SYSTEM_PROMPT,
    PJBL_KINA_SYSTEM_PROMPT,
)
from app.services.prompt_builder_service import PromptBuilderService
from app.services.rag_service import RAGService
from app.utils.text_cleaner import compact_text


logger = logging.getLogger(__name__)


COMPLETION_MESSAGE = (
    "Terima kasih, rancangan proyek Anda sudah selesai dan siap digunakan untuk "
    "tahap berikutnya."
)

DEFAULT_KINA_MODEL = "deepseek/deepseek-v4-flash"
MAX_KINA_RESPONSE_WORDS = 120

DISCUSSION_STAGES: tuple[tuple[str, str], ...] = (
    ("focus_scope", "fokus dan ruang lingkup proyek"),
    ("learning_style", "gaya pembelajaran"),
    ("final_product", "produk atau aksi akhir"),
    ("activities_schedule", "alur kegiatan dan jadwal"),
    ("roles_support", "pembagian peran dan pendampingan"),
    ("facilities_partnership", "fasilitas, teknologi, dan kemitraan"),
    ("digital_use", "pemanfaatan digital"),
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
    "learning_style": (
        "gaya pembelajaran",
        "gaya belajar",
        "visual",
        "auditori",
        "kinestetik",
        "praktik langsung",
        "diskusi",
        "kolaboratif",
        "mandiri",
        "diferensiasi",
        "minat siswa",
        "learningstyle",
        "dominantlearningstyle",
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
        "durasi proyek",
        "berapa lama",
        "projectactivitiesoverview",
        "activityflowdecision",
        "projectduration",
    ),
    "roles_support": (
        "pembagian peran",
        "peran siswa",
        "peran ketua",
        "peran anggota",
        "kerja kelompok",
        "kelompok empat orang",
        "ketua kelompok",
        "anggota kelompok",
        "pencatat data",
        "pengolah data",
        "penyaji",
        "pendampingan",
        "cek kemajuan",
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
    "digital_use": (
        "pemanfaatan digital",
        "digital",
        "aplikasi",
        "platform",
        "canva",
        "google form",
        "google forms",
        "google docs",
        "google slides",
        "padlet",
        "spreadsheet",
        "video",
        "kamera",
        "dokumentasi digital",
        "media digital",
        "digitalresources",
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
SOLVER_LLM_REQUEST_PATTERN = re.compile(
    r"(?:\?|\b(?:bagaimana|mengapa|kenapa|sebaiknya|tolong|bantu|sarankan|"
    r"minta saran|butuh saran|bandingkan|lebih baik|apa saja|apa yang|"
    r"apakah|bisakah|dapatkah)\b)",
    flags=re.IGNORECASE,
)
COMPLEX_PEDAGOGICAL_PATTERN = re.compile(
    r"\b(?:risiko|mitigasi|keselamatan|konflik|kendala|masalah|biaya|"
    r"perizinan|diferensiasi|asesmen diagnostik|kebutuhan khusus)\b",
    flags=re.IGNORECASE,
)
SHORT_CONFIRMATION_PATTERN = re.compile(
    r"^\s*(?:ya|iya|setuju|sepakat|baik|oke|ok|pilih|saya pilih|"
    r"saya memilih|gunakan|tetap|tanpa|tidak menggunakan)\b",
    flags=re.IGNORECASE,
)
SIMPLE_FACT_PATTERN = re.compile(
    r"(?:\b(?:\d+|satu|dua|tiga|empat|lima|enam|tujuh|delapan|sembilan|"
    r"sepuluh)\s*(?:hari|minggu|bulan|pertemuan|JP|jam|orang|siswa|kelompok)\b|"
    r"\b(?:infografis|laporan observasi|poster|video|prototipe|presentasi|"
    r"kampanye)\b)",
    flags=re.IGNORECASE,
)
STAGE_DECISION_PATTERNS: dict[str, re.Pattern[str]] = {
    "focus_scope": re.compile(
        r"\b(?:fokus proyek|ruang lingkup|masalah utama|fokusnya|masalahnya)\b",
        flags=re.IGNORECASE,
    ),
    "learning_style": re.compile(
        r"\b(?:gaya pembelajaran|gaya belajar|visual|auditori|kinestetik|"
        r"praktik langsung|diskusi|kolaboratif|mandiri|diferensiasi|minat siswa)\b",
        flags=re.IGNORECASE,
    ),
    "final_product": re.compile(
        r"\b(?:produk akhir|aksi akhir|memilih|pilih|gunakan)\b.{0,60}"
        r"\b(?:infografis|poster|laporan|video|prototipe|kampanye|pameran)\b",
        flags=re.IGNORECASE | re.DOTALL,
    ),
    "activities_schedule": re.compile(
        r"\b(?:durasi|jadwal|alur kegiatan|minggu pertama|minggu kedua|"
        r"minggu ketiga|pertemuan|tahapan proyek)\b",
        flags=re.IGNORECASE,
    ),
    "roles_support": re.compile(
        r"\b(?:pembagian peran|peran ketua|peran anggota|kelompok .{0,20} orang|"
        r"pencatat data|pengolah data|penyaji|cek kemajuan|pendampingan)\b",
        flags=re.IGNORECASE,
    ),
    "facilities_partnership": re.compile(
        r"\b(?:fasilitas|proyektor|halaman sekolah|alat tulis|alat|peralatan|"
        r"internet|gawai|drone|kamera|"
        r"mitra|kemitraan|orang tua|komunitas)\b",
        flags=re.IGNORECASE,
    ),
    "digital_use": re.compile(
        r"\b(?:pemanfaatan digital|digital|aplikasi|platform|canva|google forms?|"
        r"google docs|google slides|padlet|spreadsheet|video|kamera|"
        r"dokumentasi digital|media digital)\b",
        flags=re.IGNORECASE,
    ),
    "risk_mitigation": re.compile(
        r"\b(?:risiko|mitigasi|keselamatan|perizinan|keterlambatan|"
        r"batas area|lembar panduan|target mingguan)\b",
        flags=re.IGNORECASE,
    ),
    "assessment_reflection": re.compile(
        r"\b(?:penilaian|asesmen|rubrik|bukti proses|kontribusi individu|"
        r"kriteria keberhasilan|refleksi individu|refleksi siswa)\b",
        flags=re.IGNORECASE,
    ),
}
STAGE_REQUIRED_SLOTS: dict[str, tuple[tuple[str, str, re.Pattern[str]], ...]] = {
    "focus_scope": (
        (
            "issue",
            "masalah utama",
            re.compile(
                r"\b(?:sampah|limbah|kebersihan|boros|hemat|jajan|kantin|"
                r"perundungan|disiplin|minat baca|literasi|antre|antri|air|"
                r"tanaman|lingkungan|kebiasaan|tantangan|kebutuhan|masalah)\b",
                flags=re.IGNORECASE,
            ),
        ),
        (
            "boundary",
            "batas lokasi atau sasaran",
            re.compile(
                r"\b(?:kantin|kelas|halaman|perpustakaan|sekolah|warga|"
                r"siswa|murid|kelompok|area|lokasi|sekitar|sasaran|"
                r"batasi|batas|ruang lingkup|lingkup)\b",
                flags=re.IGNORECASE,
            ),
        ),
    ),
    "learning_style": (
        (
            "style",
            "gaya pembelajaran",
            re.compile(
                r"\b(?:gaya pembelajaran|gaya belajar|visual|auditori|"
                r"kinestetik|praktik langsung|diskusi|kolaboratif|mandiri|"
                r"diferensiasi|minat siswa|eksplorasi|observasi langsung)\b",
                flags=re.IGNORECASE,
            ),
        ),
    ),
    "final_product": (
        (
            "product",
            "produk atau aksi akhir",
            re.compile(
                r"\b(?:poster|infografis|laporan|video|prototipe|kampanye|"
                r"pameran|presentasi|produk akhir|aksi akhir|karya|"
                r"media kampanye|peta temuan)\b",
                flags=re.IGNORECASE,
            ),
        ),
    ),
    "activities_schedule": (
        (
            "duration",
            "durasi atau jumlah pertemuan",
            re.compile(
                r"\b(?:\d+|satu|dua|tiga|empat|lima|enam|tujuh|delapan|"
                r"sembilan|sepuluh)\s*(?:hari|minggu|bulan|pertemuan|jp|jam|"
                r"menit)\b|\b(?:durasi|jadwal|alokasi waktu)\b",
                flags=re.IGNORECASE,
            ),
        ),
        (
            "flow",
            "alur kegiatan utama",
            re.compile(
                r"\b(?:observasi|wawancara|survei|diskusi|mengumpulkan|data|"
                r"membuat|menyusun|presentasi|refleksi|tahap|alur|mulai|"
                r"lanjut|akhir|pertemuan pertama|minggu pertama)\b",
                flags=re.IGNORECASE,
            ),
        ),
    ),
    "roles_support": (
        (
            "roles",
            "peran atau bentuk kelompok",
            re.compile(
                r"\b(?:kelompok|tim|anggota|ketua|pencatat|penyaji|pengolah|"
                r"peran|individu|berpasangan)\b",
                flags=re.IGNORECASE,
            ),
        ),
        (
            "support",
            "cara pendampingan guru",
            re.compile(
                r"\b(?:monitoring|pantau|memantau|pendampingan|bimbing|"
                r"membimbing|cek|umpan balik|lembar kerja|guru|arahan|"
                r"dibantu|difasilitasi)\b",
                flags=re.IGNORECASE,
            ),
        ),
    ),
    "facilities_partnership": (
        (
            "facilities",
            "fasilitas atau teknologi",
            re.compile(
                r"\b(?:fasilitas|proyektor|internet|gawai|hp|laptop|kamera|"
                r"alat tulis|halaman sekolah|kelas|perpustakaan|laboratorium|"
                r"google|canva|padlet|slides|form)\b",
                flags=re.IGNORECASE,
            ),
        ),
        (
            "use_or_partnership",
            "cara penggunaan atau keputusan kemitraan",
            re.compile(
                r"\b(?:pakai|gunakan|menggunakan|digunakan|untuk|platform|"
                r"mitra|kemitraan|orang tua|komunitas|warga|tanpa mitra|"
                r"tidak menggunakan|tidak perlu mitra)\b",
                flags=re.IGNORECASE,
            ),
        ),
    ),
    "digital_use": (
        (
            "digital_plan",
            "pemanfaatan digital",
            re.compile(
                r"\b(?:pemanfaatan digital|digital|aplikasi|platform|canva|"
                r"google forms?|google docs|google slides|padlet|spreadsheet|"
                r"video|kamera|foto|dokumentasi|media digital|gawai|hp|"
                r"laptop|internet)\b",
                flags=re.IGNORECASE,
            ),
        ),
    ),
    "risk_mitigation": (
        (
            "risk",
            "risiko utama",
            re.compile(
                r"\b(?:risiko|kendala|hambatan|keselamatan|izin|perizinan|"
                r"biaya|keterlambatan|alat terbatas|internet|konflik|"
                r"cuaca|ramai)\b",
                flags=re.IGNORECASE,
            ),
        ),
        (
            "mitigation",
            "cara mitigasi",
            re.compile(
                r"\b(?:mitigasi|cegah|mencegah|antisipasi|batas|panduan|"
                r"aturan|dampingi|pengawasan|cadangan|sederhanakan|aman|"
                r"hemat|target|izin guru)\b",
                flags=re.IGNORECASE,
            ),
        ),
    ),
    "assessment_reflection": (
        (
            "assessment",
            "aspek yang dinilai",
            re.compile(
                r"\b(?:asesmen|penilaian|nilai|rubrik|kriteria|kontribusi|"
                r"kerja sama|produk|proses|presentasi)\b",
                flags=re.IGNORECASE,
            ),
        ),
        (
            "evidence_reflection",
            "bukti proses atau refleksi",
            re.compile(
                r"\b(?:bukti|catatan|jurnal|observasi|dokumentasi|foto|"
                r"presentasi|refleksi|umpan balik|hasil kerja|lembar refleksi)\b",
                flags=re.IGNORECASE,
            ),
        ),
    ),
}
SAVED_STAGE_SUMMARY_FIELDS: dict[str, str] = {
    "focusAndScope": "focus_scope",
    "learningStyle": "learning_style",
    "finalProduct": "final_product",
    "activitiesAndSchedule": "activities_schedule",
    "rolesAndSupport": "roles_support",
    "facilitiesTechnologyPartnership": "facilities_partnership",
    "digitalUse": "digital_use",
    "riskMitigation": "risk_mitigation",
    "assessmentReflection": "assessment_reflection",
}
STAGE_MEMORY_FIELDS: dict[str, str] = {
    stage_key: field_name
    for field_name, stage_key in SAVED_STAGE_SUMMARY_FIELDS.items()
}
AI_STYLE_PATTERN = re.compile(
    r"\b(?:berada di persimpangan|menjadi jantung(?: dari)?|pada akhirnya|"
    r"dalam konteks ini|perlu digarisbawahi|perlu dicatat bahwa|"
    r"tidak hanya .{0,80} tetapi juga|mari kita|tentu saja|"
    r"sebuah langkah penting|membuka peluang|memberikan warna)\b",
    flags=re.IGNORECASE | re.DOTALL,
)
IRRELEVANT_INPUT_PATTERN = re.compile(
    r"\b(?:resep|masakan|cuaca|ramalan cuaca|sepak bola|film|musik|bitcoin|"
    r"saham|trading|coding|pemrograman|game|gim|politik|presiden|wisata|"
    r"hotel|tiket pesawat)\b",
    flags=re.IGNORECASE,
)
CONVERSATION_REFERENCE_PATTERN = re.compile(
    r"\b(?:ini|itu|tersebut|yang pertama|yang kedua|yang ketiga|opsi pertama|"
    r"opsi kedua|opsi ketiga|setuju|tidak setuju|cukup|lanjut|tetap|ubah)\b",
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
    (r"\bSolver\b", "pertimbangan pedagogis"),
    (r"\bEvaluator\b", "peninjauan respons"),
    (r"\bscore\b", "penilaian"),
    (r"\bJSON\b", "format terstruktur"),
)

KINA_RESPONSE_RULES: tuple[str, ...] = (
    "Validasi maksud guru dan rangkum keputusan yang sudah tersedia.",
    "Pastikan input relevan dengan diskusi PjBL saat ini sebelum mencatat keputusan.",
    "Berikan saran konkret sebelum mengajukan pertanyaan.",
    "Gunakan bahasa Indonesia yang natural, hangat, dan profesional.",
    "Ajukan maksimal satu pertanyaan ringan dan jangan mengulang jawaban yang ada.",
    "Jika guru ragu, berikan maksimal tiga pilihan realistis dengan alasan singkat.",
    "Jangan membuat respons seperti formulir atau menyusun RPP lengkap terlalu dini.",
)

SOLVER_FIELDS: tuple[str, ...] = (
    "teacher_intent",
    "known_context",
    "decision_summary",
    "response_goal",
    "recommended_response_points",
    "pedagogical_suggestions",
    "question_to_ask",
    "risk_notes",
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
        total_started = perf_counter()
        timings: dict[str, float] = {}
        stage_statuses: dict[str, str] = {}
        route = "unhandled_error"

        try:
            context_started = perf_counter()
            analysis = self._analyze_stage(payload)
            timings["context"] = self._elapsed_ms(context_started)
            stage_statuses["context"] = "success"

            # RAG sementara dinonaktifkan untuk Kina PjBL. Konteks Stage 1,
            # Stage 2, keputusan guru, dan riwayat singkat menjadi sumber utama.
            references: list[RagReference] = []
            timings["rag"] = 0.0
            stage_statuses["rag"] = "skipped"

            fallback = self._fallback_reply(payload, analysis)
            context_started = perf_counter()
            stage3_memory = self._build_stage3_memory(payload, analysis)
            context = self._build_kina_context(
                payload,
                references,
                analysis,
                stage3_memory=stage3_memory,
            )
            timings["context"] += self._elapsed_ms(context_started)

            solver_started = perf_counter()
            try:
                if self._can_use_local_solver(payload.message, analysis):
                    solver_output = self._solve_pedagogical_response_locally(
                        user_message=payload.message,
                        context=context,
                        analysis=analysis,
                    )
                    solver_mode = "local"
                else:
                    solver_output = await self._solve_pedagogical_response(
                        user_message=payload.message,
                        context=context,
                    )
                    solver_mode = "llm"
            except Exception:
                timings["solver"] = self._elapsed_ms(solver_started)
                stage_statuses["solver"] = "error"
                route = "solver_fallback"
                fallback_started = perf_counter()
                try:
                    reply = await self._existing_generation_fallback(
                        payload, references, analysis, fallback
                    )
                    stage_statuses["fallback"] = "success"
                except Exception:
                    stage_statuses["fallback"] = "error"
                    raise
                finally:
                    timings["fallback"] = self._elapsed_ms(fallback_started)
            else:
                timings["solver"] = self._elapsed_ms(solver_started)
                stage_statuses["solver"] = solver_mode

                draft_started = perf_counter()
                try:
                    draft = await self._generate_kina_draft(
                        user_message=payload.message,
                        context=context,
                        solver_output=solver_output,
                        fallback=fallback,
                        analysis=analysis,
                    )
                except Exception:
                    timings["draft"] = self._elapsed_ms(draft_started)
                    stage_statuses["draft"] = "error"
                    route = "draft_fallback"
                    fallback_started = perf_counter()
                    try:
                        reply = await self._existing_generation_fallback(
                            payload, references, analysis, fallback
                        )
                        stage_statuses["fallback"] = "success"
                    except Exception:
                        stage_statuses["fallback"] = "error"
                        raise
                    finally:
                        timings["fallback"] = self._elapsed_ms(fallback_started)
                else:
                    timings["draft"] = self._elapsed_ms(draft_started)
                    stage_statuses["draft"] = "success"
                    route = "draft_sanitized"
                    if analysis["input_relevance"] in {"irrelevant", "unclear"}:
                        reply = fallback
                    else:
                        reply = self._sanitize_reply(
                            draft,
                            fallback=fallback,
                            is_complete=analysis["is_complete"],
                            limit_options=analysis["teacher_uncertain"],
                            enforce_word_limit=True,
                        )

            suggestions_started = perf_counter()
            try:
                suggested_followups = await self._suggested_questions(
                    payload,
                    analysis,
                    reply,
                )
                stage_statuses["suggestions"] = "success"
            except Exception:
                suggested_followups = self._local_suggested_questions(payload, analysis)
                stage_statuses["suggestions"] = "fallback"
            finally:
                timings["suggestions"] = self._elapsed_ms(suggestions_started)

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
                suggestedFollowUpQuestions=suggested_followups,
                progress=self._progress_payload(analysis),
                stage3Memory=stage3_memory,
            )
        finally:
            timings["total"] = self._elapsed_ms(total_started)
            self._log_timing_summary(
                project_id=payload.project.id,
                route=route,
                timings=timings,
                stage_statuses=stage_statuses,
            )

    def _elapsed_ms(self, started: float) -> float:
        return round((perf_counter() - started) * 1000, 1)

    def _log_timing_summary(
        self,
        *,
        project_id: str,
        route: str,
        timings: dict[str, float],
        stage_statuses: dict[str, str],
    ) -> None:
        ordered_stages = (
            "context",
            "rag",
            "solver",
            "draft",
            "suggestions",
            "fallback",
            "total",
        )
        duration_text = " ".join(
            f"{stage}_ms={timings[stage]:.1f}"
            for stage in ordered_stages
            if stage in timings
        )
        status_text = ",".join(
            f"{stage}:{status}"
            for stage, status in stage_statuses.items()
        )
        logger.info(
            "Kina timing project_id=%s model=%s route=%s statuses=%s %s",
            project_id,
            self._kina_model(),
            route,
            status_text or "none",
            duration_text,
        )

    def _build_kina_context(
        self,
        payload: KinaChatRequest,
        references: list[RagReference],
        analysis: dict[str, Any],
        *,
        stage3_memory: dict[str, Any],
    ) -> dict[str, Any]:
        stage_summaries = {1: "Belum tersedia.", 2: "Belum tersedia."}
        for stage_number in stage_summaries:
            matching_stages = [
                stage for stage in payload.stages if stage.stageNumber == stage_number
            ]
            if matching_stages:
                stage_summaries[stage_number] = compact_text(
                    self.prompt_builder.stages_context(matching_stages),
                    1800,
                )

        recent_history = [
            {
                "role": chat.role,
                "message": compact_text(chat.message, 350),
            }
            for chat in payload.chatHistory[-6:]
        ]
        teacher_decisions = [
            compact_text(chat.message, 350)
            for chat in payload.chatHistory
            if chat.role == "user"
            and DECISION_PATTERN.search(chat.message)
            and not UNCERTAINTY_PATTERN.search(chat.message)
        ][-5:]
        if DECISION_PATTERN.search(payload.message) and not UNCERTAINTY_PATTERN.search(
            payload.message
        ):
            teacher_decisions.append(compact_text(payload.message, 350))
        saved_stage_decisions = [
            compact_text(
                f"Stage {stage.stageNumber} - {stage.stageName or '-'}: "
                f"{self._flatten(stage.contentJson)}",
                600,
            )
            for stage in payload.stages
            if stage.stageNumber > 2 and stage.contentJson
        ][-5:]

        return {
            "latest_user_message": compact_text(payload.message, 700),
            "project": compact_text(
                self.prompt_builder.project_context(payload.project), 700
            ),
            "stage_1_summary": stage_summaries[1],
            "stage_2_summary": stage_summaries[2],
            "stage_3_memory": stage3_memory,
            "confirmed_stage_decisions": stage3_memory.get(
                "confirmedDecisions",
                {},
            ),
            "teacher_decisions": teacher_decisions[-5:],
            "saved_stage_decisions": saved_stage_decisions,
            "recent_exchange": recent_history,
            "current_conversation_stage": analysis["active_label"],
            "current_conversation_stage_key": analysis["active_stage"],
            "expected_stage_before_message": analysis[
                "expected_stage_before_message"
            ],
            "expected_label_before_message": analysis[
                "expected_label_before_message"
            ],
            "input_stage_keys": analysis["input_stage_keys"],
            "input_out_of_sequence": analysis["input_out_of_sequence"],
            "input_relevance": analysis["input_relevance"],
            "conversation_complete": analysis["is_complete"],
            "teacher_uncertain": analysis["teacher_uncertain"],
            "change_requested": analysis["change_requested"],
            "stage_slot_progress": analysis["stage_slot_progress"],
            "missing_slots": analysis["missing_slots"],
            "supporting_references": [
                {
                    "title": reference.sourceTitle,
                    "excerpt": compact_text(reference.chunkText, 350),
                }
                for reference in references[:3]
            ],
            "response_rules": list(KINA_RESPONSE_RULES),
            "communication_method": [
                "Validasi maksud guru sebelum memberi arahan.",
                "Tangkap dan rangkum keputusan guru secara singkat.",
                "Berikan saran atau contoh konkret jika jawaban guru masih umum.",
                "Ajukan satu pertanyaan kecil untuk melanjutkan bagian aktif.",
                "Jaga percakapan tetap natural, bukan seperti formulir.",
            ],
            "discussion_flow": [
                {"key": key, "label": label}
                for key, label in DISCUSSION_STAGES
            ],
        }

    def _can_use_local_solver(
        self,
        user_message: str,
        analysis: dict[str, Any],
    ) -> bool:
        message = compact_text(user_message, 700)
        if not message or len(message) > 500:
            return False
        if (
            analysis["change_requested"]
            or analysis["teacher_uncertain"]
            or analysis["input_relevance"] in {"irrelevant", "unclear"}
        ):
            return False
        if SOLVER_LLM_REQUEST_PATTERN.search(message):
            return False
        if COMPLEX_PEDAGOGICAL_PATTERN.search(message):
            return False
        if analysis["is_complete"]:
            return True
        return bool(
            DECISION_PATTERN.search(message)
            or SHORT_CONFIRMATION_PATTERN.search(message)
            or SIMPLE_FACT_PATTERN.search(message)
        )

    def _solve_pedagogical_response_locally(
        self,
        *,
        user_message: str,
        context: dict[str, Any],
        analysis: dict[str, Any],
    ) -> dict[str, Any]:
        decision = compact_text(user_message, 350)
        active_stage = analysis["active_stage"]
        project_context = compact_text(context.get("project", ""), 350)

        if analysis["is_complete"]:
            return self._normalize_solver_output(
                {
                    "teacher_intent": "Mengonfirmasi bahwa rancangan proyek selesai.",
                    "known_context": project_context,
                    "decision_summary": decision,
                    "response_goal": "Merangkum rancangan dan menutup diskusi.",
                    "recommended_response_points": [
                        "Validasi bahwa seluruh bagian utama proyek sudah dibahas.",
                        "Ringkas kesiapan rancangan untuk tahap berikutnya.",
                        f"Tutup dengan kalimat: {COMPLETION_MESSAGE}",
                    ],
                    "pedagogical_suggestions": [],
                    "question_to_ask": "",
                    "risk_notes": [],
                }
            )

        stage_guidance = {
            "focus_scope": (
                "Arahkan pembahasan pada satu masalah utama yang realistis.",
                "Apa batas masalah yang paling realistis untuk proyek ini?",
            ),
            "learning_style": (
                "Selaraskan proyek dengan gaya belajar dominan siswa.",
                "Gaya pembelajaran apa yang paling cocok untuk kelas ini?",
            ),
            "final_product": (
                "Pastikan produk akhir menjawab masalah dan sesuai fasilitas.",
                "Produk atau aksi akhir apa yang paling sesuai?",
            ),
            "activities_schedule": (
                "Susun kegiatan bertahap dari observasi hingga presentasi.",
                "Berapa minggu PjBL ini akan dilakukan?",
            ),
            "roles_support": (
                "Gunakan peran kelompok yang jelas agar kontribusi siswa merata.",
                "Bagaimana peran siswa akan dibagi dalam kelompok?",
            ),
            "facilities_partnership": (
                "Utamakan fasilitas yang tersedia dan kemitraan yang realistis.",
                "Fasilitas apa yang paling realistis digunakan?",
            ),
            "digital_use": (
                "Gunakan digital hanya untuk membantu proses belajar yang perlu.",
                "Pemanfaatan digital apa yang paling realistis digunakan?",
            ),
            "risk_mitigation": (
                "Prioritaskan risiko yang paling mungkin menghambat pelaksanaan.",
                "Risiko utama apa yang perlu dicegah terlebih dahulu?",
            ),
            "assessment_reflection": (
                "Seimbangkan penilaian proses, produk, dan kontribusi individu.",
                "Aspek proses dan hasil apa yang akan dinilai?",
            ),
        }
        suggestion, question = stage_guidance[active_stage]
        decision_area = self._local_decision_area(user_message, active_stage)
        return self._normalize_solver_output(
            {
                "teacher_intent": f"Mengonfirmasi keputusan tentang {decision_area}.",
                "known_context": project_context,
                "decision_summary": decision,
                "response_goal": (
                    "Memvalidasi keputusan guru, memberi penguatan singkat, dan "
                    f"melanjutkan ke {analysis['active_label']}."
                ),
                "recommended_response_points": [
                    f"Validasi keputusan guru: {decision}",
                    f"Pertahankan keputusan tersebut dalam rancangan {project_context}.",
                    suggestion,
                ],
                "pedagogical_suggestions": [suggestion],
                "question_to_ask": question,
                "risk_notes": [
                    "Jangan menanyakan kembali keputusan yang baru dikonfirmasi."
                ],
            }
        )

    def _local_decision_area(self, message: str, active_stage: str) -> str:
        for stage_key, stage_label in DISCUSSION_STAGES:
            if self._matches_stage(message, stage_key):
                return stage_label

        stage_keys = [stage_key for stage_key, _ in DISCUSSION_STAGES]
        active_index = stage_keys.index(active_stage)
        if active_index > 0:
            return DISCUSSION_STAGES[active_index - 1][1]
        return DISCUSSION_STAGES[active_index][1]

    async def _solve_pedagogical_response(
        self,
        *,
        user_message: str,
        context: dict[str, Any],
    ) -> dict[str, Any]:
        solver_output = await self.llm_client.generate_json(
            [
                {"role": "system", "content": PJBL_KINA_SOLVER_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "\n\n".join(
                        [
                            f"PESAN GURU:\n{user_message}",
                            "KONTEKS RINGKAS:",
                            json.dumps(context, ensure_ascii=False),
                            f"ARAH GILIRAN:\n{self._turn_instruction_from_context(context)}",
                        ]
                    ),
                },
            ],
            {},
            model=self._solver_model(),
            temperature=0.2,
            max_tokens=900,
        )
        return self._normalize_solver_output(solver_output)

    async def _generate_kina_draft(
        self,
        *,
        user_message: str,
        context: dict[str, Any],
        solver_output: dict[str, Any],
        fallback: str,
        analysis: dict[str, Any],
    ) -> str:
        draft = await self.llm_client.generate_text(
            [
                {"role": "system", "content": PJBL_KINA_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "\n\n".join(
                        [
                            f"PESAN GURU:\n{user_message}",
                            "SUBSTANSI DARI SOLVER:",
                            json.dumps(solver_output, ensure_ascii=False),
                            "KONTEKS RANCANGAN PJBL:",
                            json.dumps(
                                {
                                    "project": context["project"],
                                    "stage_1_summary": context["stage_1_summary"],
                                    "stage_2_summary": context["stage_2_summary"],
                                    "stage_3_memory": context["stage_3_memory"],
                                    "confirmed_stage_decisions": context[
                                        "confirmed_stage_decisions"
                                    ],
                                    "teacher_decisions": context[
                                        "teacher_decisions"
                                    ],
                                    "saved_stage_decisions": context[
                                        "saved_stage_decisions"
                                    ],
                                    "recent_exchange": context["recent_exchange"],
                                    "communication_method": context[
                                        "communication_method"
                                    ],
                                    "discussion_flow": context["discussion_flow"],
                                },
                                ensure_ascii=False,
                            ),
                            "KONTEKS GILIRAN:",
                            json.dumps(
                                {
                                    "current_conversation_stage": context[
                                        "current_conversation_stage"
                                    ],
                                    "conversation_complete": context[
                                        "conversation_complete"
                                    ],
                                    "teacher_uncertain": context[
                                        "teacher_uncertain"
                                    ],
                                    "change_requested": context["change_requested"],
                                    "input_out_of_sequence": context[
                                        "input_out_of_sequence"
                                    ],
                                    "expected_stage_before_message": context[
                                        "expected_stage_before_message"
                                    ],
                                    "input_relevance": context["input_relevance"],
                                },
                                ensure_ascii=False,
                            ),
                            "Tulis hanya teks respons Kina yang natural. Validasi "
                            "maksud guru, sampaikan saran konkret bila relevan, lalu "
                            "ajukan maksimal satu pertanyaan ringan. Gunakan maksimal "
                            f"{MAX_KINA_RESPONSE_WORDS} kata, langsung ke inti, tanpa "
                            "metafora atau frasa generik khas AI. Jika input tidak relevan, "
                            "jangan masukkan sebagai keputusan proyek; jelaskan batasan "
                            "secara singkat dan arahkan kembali ke tahap aktif.",
                        ]
                    ),
                },
            ],
            "",
            model=self._kina_model(),
            temperature=0.55,
            max_tokens=700,
        )
        if not str(draft or "").strip() or self._looks_like_json(str(draft)):
            raise ValueError("Draft Kina kosong.")
        return self._sanitize_reply(
            draft,
            fallback=fallback,
            is_complete=analysis["is_complete"],
            limit_options=analysis["teacher_uncertain"],
            enforce_word_limit=False,
        )

    async def _existing_generation_fallback(
        self,
        payload: KinaChatRequest,
        references: list[RagReference],
        analysis: dict[str, Any],
        fallback: str,
    ) -> str:
        generated_reply = await self.llm_client.generate_text(
            self._build_messages(payload, references, analysis),
            fallback,
            model=self._kina_model(),
            temperature=0.55,
        )
        return self._sanitize_reply(
            generated_reply,
            fallback=fallback,
            is_complete=analysis["is_complete"],
            limit_options=analysis["teacher_uncertain"],
        )

    def _turn_instruction_from_context(self, context: dict[str, Any]) -> str:
        return self._turn_instruction(
            {
                "change_requested": context["change_requested"],
                "is_complete": context["conversation_complete"],
                "active_label": context["current_conversation_stage"],
                "input_out_of_sequence": context["input_out_of_sequence"],
                "expected_label_before_message": context[
                    "expected_label_before_message"
                ],
                "input_relevance": context["input_relevance"],
            }
        )

    def _normalize_solver_output(self, value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or not all(
            field in value for field in SOLVER_FIELDS
        ):
            raise ValueError("Output Solver tidak lengkap.")

        normalized = {
            "teacher_intent": self._clean_internal_text(value["teacher_intent"]),
            "known_context": self._clean_internal_text(value["known_context"]),
            "decision_summary": self._clean_internal_text(value["decision_summary"]),
            "response_goal": self._clean_internal_text(value["response_goal"]),
            "recommended_response_points": self._clean_string_list(
                value["recommended_response_points"], limit=6
            ),
            "pedagogical_suggestions": self._clean_string_list(
                value["pedagogical_suggestions"], limit=3
            ),
            "question_to_ask": self._clean_internal_text(value["question_to_ask"]),
            "risk_notes": self._clean_string_list(value["risk_notes"], limit=4),
        }
        normalized["question_to_ask"] = self._limit_questions(
            normalized["question_to_ask"]
        )
        if not normalized["teacher_intent"] or not normalized[
            "recommended_response_points"
        ]:
            raise ValueError("Output Solver tidak memiliki substansi yang cukup.")
        return normalized

    def _clean_internal_text(self, value: Any) -> str:
        return compact_text(str(value or ""), 700)

    def _kina_model(self) -> str:
        llm_settings = getattr(self.llm_client, "settings", None)
        return getattr(llm_settings, "kina_llm_model", DEFAULT_KINA_MODEL)

    def _solver_model(self) -> str:
        llm_settings = getattr(self.llm_client, "settings", None)
        return getattr(llm_settings, "kina_solver_model", None) or self._kina_model()

    def _suggestion_model(self) -> str:
        llm_settings = getattr(self.llm_client, "settings", None)
        return getattr(llm_settings, "kina_suggestion_model", "openai/gpt-4o-mini")

    def _clean_string_list(self, value: Any, *, limit: int) -> list[str]:
        if not isinstance(value, list):
            return []
        return [
            cleaned
            for item in value[:limit]
            if (cleaned := self._clean_internal_text(item))
        ]

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
                "MEMORY STAGE 3 YANG TERSIMPAN:",
                json.dumps(
                    getattr(payload, "stage3Memory", {}) or {},
                    ensure_ascii=False,
                    indent=2,
                ),
                "REFERENSI RAG JIKA RELEVAN:",
                self.prompt_builder.rag_context(references),
                "RIWAYAT DISKUSI TERAKHIR:",
                json.dumps(history, ensure_ascii=False, indent=2),
                f"PESAN TERBARU GURU:\n{payload.message}",
                f"POSISI DISKUSI SAAT INI:\n{analysis['active_label']}",
                f"INSTRUKSI UNTUK GILIRAN INI:\n{self._turn_instruction(analysis)}",
                "METODE KOMUNIKASI:",
                "\n".join(
                    [
                        "- Validasi maksud guru.",
                        "- Rangkum keputusan yang baru diberikan.",
                        "- Beri saran konkret jika jawaban masih umum.",
                        "- Ajukan satu pertanyaan ringan untuk bagian aktif.",
                        "- Jaga percakapan tetap natural, bukan seperti formulir.",
                    ]
                ),
            ]
        )
        return [
            {"role": "system", "content": PJBL_KINA_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

    def _analyze_stage(self, payload: KinaChatRequest) -> dict[str, Any]:
        evidence = {key: False for key, _ in DISCUSSION_STAGES}
        stage_slots = {key: set() for key, _ in DISCUSSION_STAGES}
        self._apply_saved_stage_evidence(payload, evidence, stage_slots)
        self._apply_memory_stage_evidence(payload, evidence, stage_slots)

        previous_assistant = ""
        for chat in payload.chatHistory:
            if chat.role == "assistant":
                previous_assistant = chat.message
                continue
            if chat.role == "user":
                self._apply_user_decision(
                    chat.message,
                    previous_assistant,
                    evidence,
                    stage_slots,
                )

        expected_stage, expected_label, _ = self._active_stage_from_evidence(evidence)
        input_stage_keys = self._decision_stage_matches(payload.message)
        input_out_of_sequence = bool(
            input_stage_keys
            and expected_stage != "complete"
            and expected_stage not in input_stage_keys
        )
        change_requested = bool(PROJECT_CHANGE_PATTERN.search(payload.message))
        teacher_uncertain = bool(UNCERTAINTY_PATTERN.search(payload.message))
        input_relevance = self._classify_input_relevance(
            payload=payload,
            expected_stage=expected_stage,
            input_stage_keys=input_stage_keys,
            previous_assistant=previous_assistant,
        )

        self._apply_user_decision(
            payload.message,
            previous_assistant,
            evidence,
            stage_slots,
        )

        # Pernyataan umum seperti "sudah lengkap" tidak boleh memaksa semua
        # tahap selesai. Completion hanya berasal dari slot wajib setiap tahap.
        if GLOBAL_COMPLETION_PATTERN.search(payload.message):
            for key, _ in DISCUSSION_STAGES:
                evidence[key] = self._stage_slots_complete(key, stage_slots[key])

        active_stage, active_label, completed_count = self._active_stage_from_evidence(
            evidence
        )
        is_complete = completed_count == len(DISCUSSION_STAGES)
        stage_slot_progress = {
            key: sorted(stage_slots[key])
            for key, _ in DISCUSSION_STAGES
        }
        missing_slot_keys = self._missing_stage_slot_keys(active_stage, stage_slots)
        return {
            "active_stage": active_stage,
            "active_label": active_label,
            "expected_stage_before_message": expected_stage,
            "expected_label_before_message": expected_label,
            "input_stage_keys": input_stage_keys,
            "input_out_of_sequence": input_out_of_sequence,
            "input_relevance": input_relevance,
            "evidence": evidence,
            "change_requested": change_requested,
            "teacher_uncertain": teacher_uncertain,
            "is_complete": is_complete,
            "stage_slot_progress": stage_slot_progress,
            "missing_slot_keys": missing_slot_keys,
            "missing_slots": self._missing_stage_slot_labels(
                active_stage,
                stage_slots,
            ),
        }

    def _active_stage_from_evidence(
        self,
        evidence: dict[str, bool],
    ) -> tuple[str, str, int]:
        completed_count = 0
        for key, label in DISCUSSION_STAGES:
            if evidence[key]:
                completed_count += 1
                continue
            return key, label, completed_count
        return "complete", "selesai", completed_count

    def _progress_payload(self, analysis: dict[str, Any]) -> dict[str, Any]:
        evidence = analysis["evidence"]
        total_count = len(DISCUSSION_STAGES)
        completed_count = sum(1 for key, _ in DISCUSSION_STAGES if evidence[key])
        return {
            "activeStage": analysis["active_stage"],
            "activeLabel": analysis["active_label"],
            "completedCount": completed_count,
            "totalCount": total_count,
            "percentage": round((completed_count / total_count) * 100),
            "isComplete": analysis["is_complete"],
            "missingSlots": analysis["missing_slots"],
            "stages": [
                {
                    "key": key,
                    "label": label,
                    "complete": evidence[key],
                    "foundSlots": analysis["stage_slot_progress"].get(key, []),
                    "missingSlots": self._missing_stage_slot_labels(
                        key,
                        {slot_key: set(analysis["stage_slot_progress"].get(slot_key, []))
                         for slot_key, _ in DISCUSSION_STAGES},
                    ),
                }
                for key, label in DISCUSSION_STAGES
            ],
        }

    def _build_stage3_memory(
        self,
        payload: KinaChatRequest,
        analysis: dict[str, Any],
    ) -> dict[str, Any]:
        confirmed_decisions = self._memory_confirmed_decisions(payload)
        self._merge_saved_stage_decisions(payload, confirmed_decisions)
        self._merge_history_stage_decisions(payload, confirmed_decisions)

        stage_slot_progress: dict[str, list[str]] = {}
        for key, _ in DISCUSSION_STAGES:
            found_slots = set(analysis.get("stage_slot_progress", {}).get(key, []))
            found_slots.update(
                self._stage_slot_matches(
                    self._flatten(confirmed_decisions.get(key, "")),
                    key,
                )
            )
            stage_slot_progress[key] = sorted(found_slots)

        stage_slot_sets = {
            key: set(stage_slot_progress.get(key, [])) for key, _ in DISCUSSION_STAGES
        }
        completed_stage_keys = [
            key
            for key, _ in DISCUSSION_STAGES
            if self._stage_slots_complete(key, stage_slot_sets[key])
        ]
        open_questions = [
            f"{label}: {', '.join(missing)}"
            for key, label in DISCUSSION_STAGES
            if (
                missing := self._missing_stage_slot_labels(key, stage_slot_sets)
            )
        ][:7]

        return {
            "version": 1,
            "activeStage": analysis["active_stage"],
            "activeLabel": analysis["active_label"],
            "confirmedDecisions": {
                key: confirmed_decisions.get(key, "")
                for key, _ in DISCUSSION_STAGES
            },
            "savedStageFields": {
                STAGE_MEMORY_FIELDS[key]: confirmed_decisions.get(key, "")
                for key, _ in DISCUSSION_STAGES
            },
            "stageSlotProgress": stage_slot_progress,
            "completedStageKeys": completed_stage_keys,
            "latestSummary": self._stage3_memory_summary(confirmed_decisions),
            "openQuestions": open_questions,
        }

    def _memory_confirmed_decisions(
        self,
        payload: KinaChatRequest,
    ) -> dict[str, str]:
        raw_memory = (
            payload.stage3Memory
            if isinstance(getattr(payload, "stage3Memory", None), dict)
            else {}
        )
        raw_confirmed = raw_memory.get("confirmedDecisions")
        raw_saved_fields = raw_memory.get("savedStageFields")
        confirmed: dict[str, str] = {}

        for key, _ in DISCUSSION_STAGES:
            field_name = STAGE_MEMORY_FIELDS[key]
            value = None
            if isinstance(raw_confirmed, dict):
                value = raw_confirmed.get(key) or raw_confirmed.get(field_name)
            if self._is_empty_saved_decision(value) and isinstance(
                raw_saved_fields,
                dict,
            ):
                value = raw_saved_fields.get(field_name) or raw_saved_fields.get(key)
            if not self._is_empty_saved_decision(value):
                confirmed[key] = compact_text(self._flatten(value), 700)

        return confirmed

    def _merge_saved_stage_decisions(
        self,
        payload: KinaChatRequest,
        confirmed_decisions: dict[str, str],
    ) -> None:
        for stage in payload.stages:
            if stage.stageNumber != 3 or not isinstance(stage.contentJson, dict):
                continue
            for field_name, stage_key in SAVED_STAGE_SUMMARY_FIELDS.items():
                value = stage.contentJson.get(field_name)
                if not self._is_empty_saved_decision(value):
                    confirmed_decisions[stage_key] = compact_text(
                        self._flatten(value),
                        700,
                    )

    def _merge_history_stage_decisions(
        self,
        payload: KinaChatRequest,
        confirmed_decisions: dict[str, str],
    ) -> None:
        previous_assistant = ""
        for chat in payload.chatHistory:
            if chat.role == "assistant":
                previous_assistant = chat.message
                continue
            if chat.role == "user":
                self._merge_user_message_into_memory(
                    chat.message,
                    previous_assistant,
                    confirmed_decisions,
                )

        self._merge_user_message_into_memory(
            payload.message,
            previous_assistant,
            confirmed_decisions,
        )

    def _merge_user_message_into_memory(
        self,
        message: str,
        previous_assistant: str,
        confirmed_decisions: dict[str, str],
    ) -> None:
        if (
            not message
            or UNCERTAINTY_PATTERN.search(message)
            or IRRELEVANT_INPUT_PATTERN.search(message)
            or SOLVER_LLM_REQUEST_PATTERN.search(message)
        ):
            return
        if not (
            DECISION_PATTERN.search(message)
            or SHORT_CONFIRMATION_PATTERN.search(message)
            or SIMPLE_FACT_PATTERN.search(message)
            or self._message_has_any_stage_slot(message)
        ):
            return

        stage_keys = self._decision_stage_matches(message)
        used_question_context = False
        if not stage_keys:
            for context in (self._last_question(previous_assistant), previous_assistant):
                stage_keys = [
                    key
                    for key, _ in DISCUSSION_STAGES
                    if self._matches_stage(context, key)
                ]
                if stage_keys:
                    used_question_context = True
                    break
        if not stage_keys:
            return

        decision_text = (
            self._decision_memory_text(message, previous_assistant)
            if used_question_context
            else compact_text(message, 700)
        )
        if not decision_text:
            return
        for key in stage_keys:
            confirmed_decisions[key] = decision_text

    def _decision_memory_text(self, message: str, previous_assistant: str) -> str:
        cleaned_message = compact_text(message, 450)
        if not cleaned_message:
            return ""
        question_context = self._last_question(previous_assistant)
        if question_context and (
            SHORT_CONFIRMATION_PATTERN.search(cleaned_message)
            or len(cleaned_message.split()) <= 18
        ):
            return compact_text(
                f"{question_context} Jawaban guru: {cleaned_message}",
                700,
            )
        return cleaned_message

    def _stage3_memory_summary(self, confirmed_decisions: dict[str, str]) -> str:
        parts = [
            f"{label}: {confirmed_decisions[key]}"
            for key, label in DISCUSSION_STAGES
            if confirmed_decisions.get(key)
        ]
        return compact_text("; ".join(parts), 1200)

    def _classify_input_relevance(
        self,
        *,
        payload: KinaChatRequest,
        expected_stage: str,
        input_stage_keys: list[str],
        previous_assistant: str,
    ) -> str:
        message = compact_text(payload.message, 700)
        if IRRELEVANT_INPUT_PATTERN.search(message):
            return "irrelevant"

        broad_stage_matches = [
            key
            for key, _ in DISCUSSION_STAGES
            if self._matches_stage(message, key)
        ]
        if expected_stage in broad_stage_matches or expected_stage in input_stage_keys:
            return "current"
        if broad_stage_matches or input_stage_keys or PROJECT_CHANGE_PATTERN.search(message):
            return "project"

        if re.search(
            r"\b(?:proyek|PjBL|siswa|guru|kelas|sekolah|pembelajaran|observasi|"
            r"presentasi|kelompok|produk|kegiatan|jadwal|fasilitas|asesmen|"
            r"penilaian|refleksi|gaya belajar|gaya pembelajaran|digital|"
            r"aplikasi|platform)\b",
            message,
            flags=re.IGNORECASE,
        ):
            return "current"

        if CONVERSATION_REFERENCE_PATTERN.search(message):
            return "current"

        if previous_assistant and len(message.split()) <= 15:
            return "current"

        context_text = " ".join(
            [
                payload.project.title or "",
                payload.project.subject or "",
                payload.project.phase or "",
                self._flatten([stage.contentJson for stage in payload.stages[:2]]),
            ]
        ).casefold()
        message_tokens = {
            token
            for token in re.findall(r"[a-zA-ZÀ-ÿ]{4,}", message.casefold())
            if token
            not in {
                "yang",
                "untuk",
                "dengan",
                "dalam",
                "saya",
                "guru",
                "bapak",
                "ibu",
                "apakah",
                "bagaimana",
            }
        }
        if any(token in context_text for token in message_tokens):
            return "current"
        return "unclear"

    def _apply_saved_stage_evidence(
        self,
        payload: KinaChatRequest,
        evidence: dict[str, bool],
        stage_slots: dict[str, set[str]],
    ) -> None:
        for stage in payload.stages:
            if stage.stageNumber != 3 or not isinstance(stage.contentJson, dict):
                continue
            for field_name, stage_key in SAVED_STAGE_SUMMARY_FIELDS.items():
                value = stage.contentJson.get(field_name)
                if self._is_empty_saved_decision(value):
                    continue
                stage_text = self._flatten(value)
                stage_slots[stage_key].update(
                    self._stage_slot_matches(stage_text, stage_key)
                )
                if self._stage_slots_complete(stage_key, stage_slots[stage_key]):
                    evidence[stage_key] = True

    def _apply_memory_stage_evidence(
        self,
        payload: KinaChatRequest,
        evidence: dict[str, bool],
        stage_slots: dict[str, set[str]],
    ) -> None:
        raw_memory = (
            payload.stage3Memory
            if isinstance(getattr(payload, "stage3Memory", None), dict)
            else {}
        )
        confirmed_decisions = self._memory_confirmed_decisions(payload)
        raw_stage_progress = raw_memory.get("stageSlotProgress")
        raw_completed = raw_memory.get("completedStageKeys")
        completed_stage_keys = (
            {
                key
                for key in raw_completed
                if isinstance(key, str) and key in stage_slots
            }
            if isinstance(raw_completed, list)
            else set()
        )

        if isinstance(raw_stage_progress, dict):
            valid_slots = {
                key: {
                    slot_key
                    for slot_key, _, _ in STAGE_REQUIRED_SLOTS.get(key, ())
                }
                for key, _ in DISCUSSION_STAGES
            }
            for key, slots in raw_stage_progress.items():
                if key not in stage_slots or not isinstance(slots, list):
                    continue
                stage_slots[key].update(
                    slot for slot in slots if slot in valid_slots.get(key, set())
                )

        for key, decision in confirmed_decisions.items():
            if key not in stage_slots:
                continue
            stage_slots[key].update(self._stage_slot_matches(decision, key))
            if key in completed_stage_keys and decision:
                stage_slots[key].update(
                    slot_key
                    for slot_key, _, _ in STAGE_REQUIRED_SLOTS.get(key, ())
                )
            if self._stage_slots_complete(key, stage_slots[key]):
                evidence[key] = True

        for key, _ in DISCUSSION_STAGES:
            if self._stage_slots_complete(key, stage_slots[key]):
                evidence[key] = True

    def _apply_user_decision(
        self,
        message: str,
        previous_assistant: str,
        evidence: dict[str, bool],
        stage_slots: dict[str, set[str]],
    ) -> None:
        if (
            not message
            or UNCERTAINTY_PATTERN.search(message)
            or IRRELEVANT_INPUT_PATTERN.search(message)
        ):
            return
        if SOLVER_LLM_REQUEST_PATTERN.search(message):
            return
        if not (
            DECISION_PATTERN.search(message)
            or SHORT_CONFIRMATION_PATTERN.search(message)
            or SIMPLE_FACT_PATTERN.search(message)
            or self._message_has_any_stage_slot(message)
        ):
            return

        direct_matches = self._decision_stage_matches(message)
        if direct_matches:
            for key in direct_matches:
                stage_slots[key].update(self._stage_slot_matches(message, key))
                if self._stage_slots_complete(key, stage_slots[key]):
                    evidence[key] = True
            return

        question_context = self._last_question(previous_assistant)
        for context in (question_context, previous_assistant):
            if not context:
                continue
            matching_stages = [
                key
                for key, _ in DISCUSSION_STAGES
                if self._matches_stage(context, key)
            ]
            if matching_stages:
                key = matching_stages[-1]
                stage_slots[key].update(self._stage_slot_matches(message, key))
                if self._stage_slots_complete(key, stage_slots[key]):
                    evidence[key] = True
                return

    def _last_question(self, text: str) -> str:
        question_matches = re.findall(r"[^.!?]*\?", text or "")
        if question_matches:
            return question_matches[-1].strip()
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[.!?])\s+", text or "")
            if sentence.strip()
        ]
        return sentences[-1] if sentences else ""

    def _decision_stage_matches(self, text: str) -> list[str]:
        return [
            key
            for key, _ in DISCUSSION_STAGES
            if STAGE_DECISION_PATTERNS[key].search(text or "")
        ]

    def _matches_stage(self, text: str, stage_key: str) -> bool:
        lowered = text.casefold()
        return any(keyword in lowered for keyword in STAGE_KEYWORDS[stage_key])

    def _stage_slot_matches(self, text: str, stage_key: str) -> set[str]:
        if not text:
            return set()
        return {
            slot_key
            for slot_key, _, pattern in STAGE_REQUIRED_SLOTS.get(stage_key, ())
            if pattern.search(text)
        }

    def _message_has_any_stage_slot(self, text: str) -> bool:
        return any(
            self._stage_slot_matches(text, key)
            for key, _ in DISCUSSION_STAGES
        )

    def _is_empty_saved_decision(self, value: Any) -> bool:
        if value is None:
            return True
        if isinstance(value, str):
            return not value.strip()
        if isinstance(value, list):
            return not any(not self._is_empty_saved_decision(item) for item in value)
        if isinstance(value, dict):
            return not any(
                not self._is_empty_saved_decision(item) for item in value.values()
            )
        return False

    def _stage_slots_complete(self, stage_key: str, slots: set[str]) -> bool:
        required = {slot_key for slot_key, _, _ in STAGE_REQUIRED_SLOTS.get(stage_key, ())}
        return bool(required) and required.issubset(slots)

    def _missing_stage_slot_keys(
        self,
        stage_key: str,
        stage_slots: dict[str, set[str]],
    ) -> list[str]:
        if stage_key == "complete":
            return []
        found = stage_slots.get(stage_key, set())
        return [
            slot_key
            for slot_key, _, _ in STAGE_REQUIRED_SLOTS.get(stage_key, ())
            if slot_key not in found
        ]

    def _missing_stage_slot_labels(
        self,
        stage_key: str,
        stage_slots: dict[str, set[str]],
    ) -> list[str]:
        if stage_key == "complete":
            return []
        found = stage_slots.get(stage_key, set())
        return [
            label
            for slot_key, label, _ in STAGE_REQUIRED_SLOTS.get(stage_key, ())
            if slot_key not in found
        ]

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
        if analysis.get("input_relevance") == "irrelevant":
            return (
                "Pesan guru tidak relevan dengan diskusi RPP PjBL saat ini. Jangan "
                "mencatatnya sebagai keputusan proyek dan jangan menjawab topik di luar "
                "cakupan secara panjang. Jelaskan batasan dengan sopan lalu arahkan "
                f"kembali ke {analysis['active_label']} dengan satu pertanyaan ringan."
            )
        if analysis.get("input_relevance") == "unclear":
            return (
                "Hubungan pesan guru dengan diskusi saat ini belum jelas. Jangan "
                "menganggapnya sebagai keputusan. Minta klarifikasi singkat tentang "
                f"kaitannya dengan {analysis['active_label']}."
            )
        if analysis.get("input_relevance") == "project":
            return (
                "Pesan guru relevan dengan proyek tetapi membahas bagian lain. Tanggapi "
                "secara singkat tanpa mengabaikannya, lalu kembalikan pembahasan ke "
                f"bagian yang sedang aktif: {analysis['active_label']}."
            )
        if analysis["is_complete"]:
            return (
                "Ringkas keputusan akhir secara singkat, jangan ajukan pertanyaan, dan "
                f"akhiri dengan kalimat persis: {COMPLETION_MESSAGE}"
            )
        missing_slots = analysis.get("missing_slots") or []
        missing_instruction = (
            " Gali informasi yang belum jelas: " + ", ".join(missing_slots) + "."
            if missing_slots
            else ""
        )
        return (
            f"Utamakan {analysis['active_label']}. Jika guru bertanya tentang bagian "
            "lain, jawab seperlunya lalu kembalikan pembahasan ke bagian aktif. "
            "Pertahankan keputusan yang sudah disepakati, jangan menyimpulkan tahap "
            "sebelum informasi wajibnya lengkap, dan ajukan maksimal satu pertanyaan "
            f"ringan.{missing_instruction}"
        )

    def _fallback_reply(
        self,
        payload: KinaChatRequest,
        analysis: dict[str, Any],
    ) -> str:
        project_title = self._project_title(payload)
        next_question = self._question_for_missing_slot(analysis)

        if analysis["input_relevance"] == "irrelevant":
            follow_up = self._local_suggested_questions(payload, analysis)
            redirect = (
                follow_up[0]
                if follow_up
                else "Rancangan proyek sudah lengkap dan tidak memerlukan keputusan baru."
            )
            return (
                "Pesan tersebut tidak terkait dengan pembahasan RPP PjBL yang sedang "
                f"kita matangkan. Saat ini kita masih membahas {analysis['active_label']}.\n\n"
                f"{redirect}"
            )
        if analysis["input_relevance"] == "unclear":
            return (
                "Saya belum melihat kaitan pesan tersebut dengan rancangan proyek yang "
                f"sedang dibahas. Apa kaitannya dengan {analysis['active_label']}?"
            )
        if analysis["change_requested"]:
            return (
                f"Baik, perubahan arah dari proyek {project_title} dapat dipertimbangkan. "
                "Perubahan itu perlu diperiksa terhadap tujuan proyek, durasi, fasilitas, "
                "biaya, dan risiko agar rancangan tetap realistis.\n\n"
                "Bagian utama proyek mana yang ingin Bapak/Ibu ubah?"
            )
        if analysis["is_complete"]:
            return (
                f"Baik, rancangan {project_title} sudah mencakup fokus proyek, gaya "
                "pembelajaran, produk akhir, alur kegiatan, pembagian peran, fasilitas, "
                "pemanfaatan digital, mitigasi risiko, serta asesmen dan refleksi. "
                "Seluruh keputusan tersebut dapat menjadi dasar pelaksanaan proyek "
                "yang terarah.\n\n"
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
                f"{next_question}"
            )
        if active_stage == "learning_style":
            return (
                f"Baik, fokus {project_title} sudah mulai terarah. Sekarang kita perlu "
                "menyesuaikan cara belajar yang paling cocok, misalnya lebih banyak "
                "praktik langsung, diskusi, visual, atau kerja kolaboratif.\n\n"
                f"{next_question}"
            )
        if active_stage == "final_product":
            return (
                f"Baik, gaya pembelajaran sudah dapat menjadi dasar pelaksanaan "
                f"{project_title}. Berikutnya, produk atau aksi akhir perlu dipilih agar "
                "benar-benar menjawab masalah proyek dan tetap sesuai waktu serta "
                "fasilitas sekolah.\n\n"
                f"{next_question}"
            )
        if active_stage == "activities_schedule":
            return (
                f"Baik, pilihan guru sudah saya tangkap: {latest_decision}. Keputusan ini "
                "akan menjadi dasar penyusunan kegiatan proyek dari pengenalan masalah "
                "hingga presentasi dan refleksi.\n\n"
                f"{next_question}"
            )
        if active_stage == "roles_support":
            return (
                "Baik, alur dan waktu proyek sudah cukup terarah. Agar semua siswa "
                "berkontribusi, pembagian kelompok, peran anggota, dan cara guru "
                "memantau kemajuan perlu disepakati.\n\n"
                f"{next_question}"
            )
        if active_stage == "facilities_partnership":
            return (
                "Baik, pembagian peran siswa sudah dapat menjadi dasar pelaksanaan. "
                "Selanjutnya kita perlu memilih fasilitas dan teknologi yang benar-benar "
                "tersedia, sedangkan kemitraan tetap bersifat opsional.\n\n"
                f"{next_question}"
            )
        if active_stage == "digital_use":
            return (
                "Baik, fasilitas dan kemitraan sudah cukup jelas. Sekarang kita perlu "
                "menentukan pemanfaatan digital yang benar-benar membantu, misalnya "
                "untuk dokumentasi, pengumpulan data, desain produk, atau presentasi.\n\n"
                f"{next_question}"
            )
        if active_stage == "risk_mitigation":
            return (
                "Baik, pemanfaatan digital sudah cukup terarah. Sekarang kita perlu "
                "mengantisipasi risiko yang paling mungkin terjadi agar proyek tetap "
                "aman, hemat biaya, dan selesai tepat waktu.\n\n"
                f"{next_question}"
            )
        return (
            "Baik, risiko utama dan langkah pencegahannya sudah cukup terarah. Bagian "
            "terakhir adalah menentukan bukti proses, kualitas produk, kontribusi siswa, "
            "cara presentasi, dan refleksi yang akan dinilai.\n\n"
            f"{next_question}"
        )

    def _uncertainty_reply(self, project_title: str, active_stage: str) -> str:
        options: dict[str, tuple[str, str, str]] = {
            "focus_scope": (
                "batasi proyek pada satu lokasi sekolah agar observasi mudah",
                "batasi pada satu kelompok sasaran agar solusi lebih terarah",
                "batasi pada satu kebiasaan utama agar dampaknya dapat diamati",
            ),
            "learning_style": (
                "gunakan praktik langsung agar siswa belajar dari pengalaman nyata",
                "gunakan diskusi kelompok kecil agar ide siswa saling melengkapi",
                "gunakan pendekatan visual agar temuan mudah dipahami dan dipresentasikan",
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
            "digital_use": (
                "gunakan gawai hanya untuk dokumentasi foto atau video singkat",
                "gunakan Canva atau Slides untuk menyusun produk presentasi",
                "gunakan Google Form sederhana untuk mengumpulkan data observasi",
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

    async def _suggested_questions(
        self,
        payload: KinaChatRequest,
        analysis: dict[str, Any],
        reply: str,
    ) -> list[str]:
        if analysis["is_complete"]:
            return []
        local_suggestions = self._local_suggested_questions(payload, analysis)
        context = self._suggestion_context(payload)
        generated = await self.llm_client.generate_json(
            [
                {
                    "role": "system",
                    "content": (
                        "Anda membuat suggestedFollowUpQuestions untuk chatbot KINA. "
                        "Tulis 2-3 opsi jawaban singkat yang bisa langsung diklik guru. "
                        "Opsi harus menjawab pertanyaan terakhir KINA, mengikuti konteks proyek, "
                        "dan terdengar natural sebagai jawaban guru. Jangan membuat pertanyaan baru, "
                        "jangan menulis markdown, jangan numbering, jangan memakai istilah teknis."
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "latestUserMessage": payload.message,
                            "kinaReply": reply,
                            "activeStage": analysis.get("active_stage"),
                            "activeLabel": analysis.get("active_label"),
                            "missingSlots": analysis.get("missing_slots"),
                            "project": payload.project.model_dump(),
                            "context": context,
                            "localFallbackOptions": local_suggestions,
                            "requiredResponseShape": {
                                "suggestedFollowUpQuestions": local_suggestions,
                            },
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            {"suggestedFollowUpQuestions": local_suggestions},
            model=self._suggestion_model(),
            temperature=0.45,
            max_tokens=350,
        )
        raw_suggestions = generated.get("suggestedFollowUpQuestions")
        if not isinstance(raw_suggestions, list):
            raw_suggestions = local_suggestions
        cleaned = self._clean_suggestions(
            [item for item in raw_suggestions if isinstance(item, str)]
        )
        return cleaned or local_suggestions

    def _local_suggested_questions(
        self,
        payload: KinaChatRequest,
        analysis: dict[str, Any],
    ) -> list[str]:
        if analysis["is_complete"]:
            return []
        context = self._suggestion_context(payload)
        active_stage = str(analysis.get("active_stage") or "")
        missing = analysis.get("missing_slot_keys") or []
        slot_key = str(missing[0] if missing else "")
        suggestions = self._suggestions_for_slot(active_stage, slot_key, context)
        return self._clean_suggestions(suggestions)

    def _suggestion_context(self, payload: KinaChatRequest) -> dict[str, Any]:
        stage_one = self._stage_content(payload, 1)
        stage_two = self._stage_content(payload, 2)
        stage3_memory = getattr(payload, "stage3Memory", {}) or {}
        all_context = self._flatten(
            [stage_one, stage_two, stage3_memory, payload.project.model_dump()]
        )

        issue = self._first_text(
            self._find_value(stage_one, ("localIssue", "issue", "masalahLokal")),
            self._find_value(stage_one, ("localContext", "regionalContext")),
            self._find_value(stage_two, ("projectBackground", "description")),
            payload.project.title,
        )
        duration = self._first_text(
            self._find_value(stage_one, ("durationText", "projectDuration")),
            self._find_value(stage_one, ("learningDuration", "durasiPembelajaran")),
            self._find_duration_text(all_context),
        )
        location = self._first_text(
            self._find_location_text(stage_one),
            self._find_location_text(stage_two),
            "area sekolah",
        )
        products = self._context_list(
            self._find_value(stage_two, ("studentProduct", "finalProduct"))
        )
        if not products:
            products = ["poster infografis", "tabel temuan", "presentasi singkat"]
        activities = self._context_list(
            self._find_value(stage_two, ("projectActivitiesOverview", "activities"))
        )
        if not activities:
            activities = ["observasi", "pengolahan data", "penyajian hasil", "refleksi"]
        facilities = self._context_list(
            self._find_value(stage_one, ("facilities", "availableFacilities"))
        )
        if not facilities:
            facilities = ["kelas", "papan tulis", "gawai guru"]
        risks = self._context_list(
            self._find_value(stage_one, ("riskMonitoring", "risks"))
        ) or self._context_list(self._find_value(stage_two, ("riskMitigation",)))
        if not risks:
            risks = ["waktu terbatas", "data kurang konsisten"]

        return {
            "issue": compact_text(issue, 110),
            "duration": compact_text(duration, 80),
            "location": compact_text(location, 90),
            "stage3Memory": stage3_memory,
            "products": [compact_text(item, 70) for item in products[:4]],
            "mentioned_products": self._mentioned_products(payload.message),
            "activities": [compact_text(item, 70) for item in activities[:5]],
            "facilities": [compact_text(item, 55) for item in facilities[:5]],
            "mentioned_facilities": self._mentioned_facilities(payload.message),
            "risks": [compact_text(item, 80) for item in risks[:3]],
            "grade": payload.project.gradeLevel or "kelas yang dipilih",
        }

    def _stage_content(self, payload: KinaChatRequest, stage_number: int) -> Any:
        for stage in payload.stages:
            if stage.stageNumber == stage_number:
                return stage.contentJson or {}
        return {}

    def _suggestions_for_slot(
        self,
        active_stage: str,
        slot_key: str,
        context: dict[str, Any],
    ) -> list[str]:
        issue = context["issue"] or "masalah yang paling dekat dengan siswa"
        location = context["location"] or "area sekolah"
        duration = context["duration"] or "durasi yang tersedia"
        products = context["mentioned_products"] or context["products"]
        activities = context["activities"]
        facilities = context["mentioned_facilities"] or context["facilities"]
        risks = context["risks"]
        grade = context["grade"]

        if active_stage == "focus_scope" and slot_key == "issue":
            return [
                f"Fokus pada {issue}.",
                f"Masalah utamanya adalah kebiasaan di {location} yang paling mudah diamati murid.",
                f"Ambil satu masalah yang dekat dengan {grade} dan bisa diamati langsung.",
            ]
        if active_stage == "focus_scope" and slot_key == "boundary":
            return [
                f"Batasi observasi di {location}.",
                f"Sasarannya murid {grade} dan warga sekolah yang terlibat langsung.",
                "Ruang lingkupnya cukup di area sekolah agar aman dan mudah dipantau.",
            ]
        if active_stage == "learning_style":
            return [
                "Gunakan praktik langsung dan diskusi kelompok kecil.",
                "Gaya belajarnya visual dan kolaboratif agar hasil mudah dipresentasikan.",
                "Utamakan observasi langsung, kerja kelompok, lalu refleksi singkat.",
            ]
        if active_stage == "final_product":
            product_text = ", ".join(products[:2])
            return [
                f"Produk akhirnya {product_text}.",
                f"Saya pilih {products[0]} karena paling realistis dibuat murid.",
                "Produk dibuat sederhana, visual, dan dipresentasikan singkat di kelas.",
            ]
        if active_stage == "activities_schedule" and slot_key == "duration":
            return [
                f"Gunakan durasi {duration}.",
                f"Proyek dijalankan dalam {duration} dengan target kecil tiap tahap.",
                "Durasi dibuat singkat agar observasi, produk, dan refleksi tetap selesai.",
            ]
        if active_stage == "activities_schedule" and slot_key == "flow":
            flow = ", ".join(activities[:4])
            return [
                f"Alurnya: {flow}.",
                "Mulai dari pemantik, observasi, olah data, buat produk, lalu refleksi.",
                "Bagi kegiatan menjadi pembuka, kerja kelompok, presentasi, dan refleksi.",
            ]
        if active_stage == "roles_support" and slot_key == "roles":
            return [
                "Murid bekerja kelompok kecil dengan ketua, pencatat, pengolah data, dan penyaji.",
                "Peran dibagi sesuai minat agar semua murid berkontribusi.",
                "Gunakan kelompok 4 orang agar pembagian tugas mudah dipantau.",
            ]
        if active_stage == "roles_support" and slot_key == "support":
            return [
                "Guru memantau memakai lembar cek singkat di setiap tahap.",
                "Guru memberi contoh dulu, lalu mengecek kemajuan tiap kelompok.",
                "Pendampingan dilakukan lewat pertanyaan pemandu dan umpan balik cepat.",
            ]
        if active_stage == "facilities_partnership" and slot_key == "facilities":
            facility_text = ", ".join(facilities[:3])
            return [
                f"Gunakan {facility_text} sebagai fasilitas utama.",
                f"Fasilitas cukup memakai {facility_text} agar proyek tetap sederhana.",
                "Pakai fasilitas yang sudah tersedia di sekolah tanpa alat tambahan mahal.",
            ]
        if active_stage == "facilities_partnership" and slot_key == "use_or_partnership":
            return [
                "Fasilitas dipakai untuk observasi, dokumentasi, dan presentasi; tanpa mitra luar.",
                "Teknologi hanya dipakai seperlunya untuk dokumentasi dan menyajikan hasil.",
                "Kemitraan tidak digunakan dulu agar proyek tetap mudah dijalankan.",
            ]
        if active_stage == "digital_use":
            return [
                "Digital dipakai untuk dokumentasi foto, pengumpulan data, dan presentasi.",
                "Gunakan Canva atau Slides untuk menyusun produk akhir kelompok.",
                "Gunakan Google Form sederhana agar data observasi mudah dikumpulkan.",
            ]
        if active_stage == "risk_mitigation" and slot_key == "risk":
            risk_text = risks[0]
            return [
                f"Risiko utamanya {risk_text}.",
                "Risiko yang perlu dijaga adalah waktu terbatas dan data kelompok tidak konsisten.",
                "Risiko utama: murid melebar dari tugas atau keluar dari area pengamatan.",
            ]
        if active_stage == "risk_mitigation" and slot_key == "mitigation":
            return [
                "Mitigasinya pakai batas area, timer, dan lembar observasi seragam.",
                "Guru memberi contoh pengisian dan mengecek tiap kelompok secara berkala.",
                "Sederhanakan target supaya proyek selesai dalam waktu yang tersedia.",
            ]
        if active_stage == "assessment_reflection" and slot_key == "assessment":
            return [
                "Nilai proses kerja kelompok, ketepatan data, kualitas produk, dan presentasi.",
                "Aspek utamanya kelengkapan data, kolaborasi, dan kejelasan pesan produk.",
                "Gunakan rubrik sederhana untuk proses, produk, kontribusi, dan komunikasi.",
            ]
        if active_stage == "assessment_reflection" and slot_key == "evidence_reflection":
            return [
                "Buktinya catatan observasi, produk akhir, presentasi, dan refleksi singkat.",
                "Murid mengumpulkan hasil kerja kelompok dan menulis satu kalimat refleksi.",
                "Setiap kelompok presentasi singkat lalu menuliskan hal yang mereka pelajari.",
            ]
        return [
            "Saya pilih opsi yang paling sederhana dan realistis untuk kondisi kelas.",
            "Gunakan rancangan yang mudah dipantau guru dan bisa selesai sesuai waktu.",
            "Batasi dulu agar proyek tetap aman, jelas, dan tidak terlalu luas.",
        ]

    def _mentioned_products(self, message: str) -> list[str]:
        product_terms = (
            "poster",
            "infografis",
            "laporan",
            "video",
            "prototipe",
            "kampanye",
            "pameran",
            "presentasi",
            "tabel data",
            "peta temuan",
        )
        return self._mentioned_terms(message, product_terms)

    def _mentioned_facilities(self, message: str) -> list[str]:
        facility_terms = (
            "proyektor",
            "internet",
            "gawai",
            "hp",
            "laptop",
            "kamera",
            "kertas plano",
            "spidol",
            "papan tulis",
            "kantin",
            "halaman sekolah",
            "halaman madrasah",
            "kelas",
            "google form",
            "canva",
            "padlet",
        )
        return self._mentioned_terms(message, facility_terms)

    def _mentioned_terms(self, message: str, terms: tuple[str, ...]) -> list[str]:
        lowered = str(message or "").casefold()
        found = [term for term in terms if term in lowered]
        return [term if term.isupper() else term for term in dict.fromkeys(found)]

    def _clean_suggestions(self, suggestions: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for suggestion in suggestions:
            text = self._polish_suggestion(suggestion)
            key = text.casefold()
            if not text or key in seen:
                continue
            seen.add(key)
            cleaned.append(text)
            if len(cleaned) >= 3:
                break
        return cleaned

    def _polish_suggestion(self, value: Any) -> str:
        text = compact_text(str(value or ""), 150)
        text = re.sub(r"\s+([,.?!])", r"\1", text)
        return text.strip()

    def _first_text(self, *values: Any) -> str:
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
            if value is not None and not isinstance(value, (dict, list, tuple, set)):
                text = str(value).strip()
                if text:
                    return text
        return ""

    def _context_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            result: list[str] = []
            for item in value:
                if isinstance(item, dict):
                    direct = self._first_text(
                        item.get("name"),
                        item.get("title"),
                        item.get("risk"),
                        item.get("description"),
                        item.get("mitigation"),
                        item.get("learningPotential"),
                    )
                    if direct:
                        result.append(direct)
                elif str(item).strip():
                    result.append(str(item).strip())
            return result
        if isinstance(value, dict):
            return [
                text
                for item in value.values()
                if (text := self._first_text(item))
            ][:5]
        if isinstance(value, str) and value.strip():
            return [value.strip()]
        return []

    def _find_location_text(self, value: Any) -> str:
        text = self._flatten(value)
        candidates = [
            "kantin",
            "halaman sekolah",
            "halaman madrasah",
            "ruang kelas",
            "kelas",
            "perpustakaan",
            "area sekolah",
            "madrasah",
            "sekolah",
        ]
        found = [candidate for candidate in candidates if candidate in text.casefold()]
        return ", ".join(dict.fromkeys(found[:3]))

    def _find_duration_text(self, text: str) -> str:
        match = re.search(
            r"\b(?:\d+|satu|dua|tiga|empat|lima|enam|tujuh|delapan|"
            r"sembilan|sepuluh)\s*(?:x\s*)?(?:jp|jam|menit|hari|minggu|"
            r"bulan|pertemuan)\b(?:\s*\([^)]*\))?",
            text,
            flags=re.IGNORECASE,
        )
        return match.group(0) if match else ""

    def _question_for_missing_slot(self, analysis: dict[str, Any]) -> str:
        active_stage = analysis.get("active_stage")
        missing = analysis.get("missing_slot_keys") or []
        first_missing = missing[0] if missing else ""
        questions: dict[tuple[str, str], str] = {
            ("focus_scope", "issue"): (
                "Masalah utama apa yang paling perlu dijawab melalui proyek ini?"
            ),
            ("focus_scope", "boundary"): (
                "Batas lokasi atau sasaran proyeknya ingin difokuskan ke mana?"
            ),
            ("learning_style", "style"): (
                "Gaya pembelajaran apa yang paling cocok untuk kelas ini?"
            ),
            ("final_product", "product"): (
                "Produk atau aksi akhir apa yang paling realistis dibuat murid?"
            ),
            ("activities_schedule", "duration"): (
                "Berapa minggu PjBL ini akan dilakukan?"
            ),
            ("activities_schedule", "flow"): (
                "Alur kegiatan utamanya mau dibuat seperti apa dari awal sampai refleksi?"
            ),
            ("roles_support", "roles"): (
                "Bagaimana peran murid akan dibagi dalam kelompok?"
            ),
            ("roles_support", "support"): (
                "Bagaimana guru akan memantau dan mendampingi kerja kelompok?"
            ),
            ("facilities_partnership", "facilities"): (
                "Fasilitas atau teknologi apa yang paling realistis digunakan?"
            ),
            ("facilities_partnership", "use_or_partnership"): (
                "Fasilitas itu akan dipakai untuk apa, dan perlu mitra atau tanpa mitra?"
            ),
            ("digital_use", "digital_plan"): (
                "Pemanfaatan digital apa yang paling realistis digunakan dalam proyek ini?"
            ),
            ("risk_mitigation", "risk"): (
                "Risiko utama apa yang paling mungkin menghambat proyek ini?"
            ),
            ("risk_mitigation", "mitigation"): (
                "Cara mencegah risiko itu paling realistis seperti apa?"
            ),
            ("assessment_reflection", "assessment"): (
                "Aspek proses dan hasil apa yang paling penting dinilai?"
            ),
            ("assessment_reflection", "evidence_reflection"): (
                "Bukti proses atau refleksi apa yang akan dikumpulkan dari murid?"
            ),
        }
        return questions.get((str(active_stage), str(first_missing)), "")

    def _sanitize_reply(
        self,
        reply: str,
        *,
        fallback: str,
        is_complete: bool,
        limit_options: bool,
        enforce_word_limit: bool = True,
    ) -> str:
        candidate = str(reply or "").strip()
        if not candidate or self._looks_like_json(candidate):
            candidate = fallback

        candidate = self._remove_forbidden_claims(candidate)
        candidate = self._replace_internal_terms(candidate)
        if enforce_word_limit and AI_STYLE_PATTERN.search(candidate):
            candidate = fallback
            candidate = self._remove_forbidden_claims(candidate)
            candidate = self._replace_internal_terms(candidate)
        if limit_options:
            candidate = self._limit_numbered_options(candidate)
        candidate = self._limit_questions(candidate)
        candidate = self._limit_paragraphs(candidate)
        if enforce_word_limit:
            candidate = self._limit_words(candidate, MAX_KINA_RESPONSE_WORDS)

        if is_complete:
            candidate = candidate.replace("?", ".")
            candidate = self._ensure_completion(candidate)
            if enforce_word_limit:
                candidate = self._limit_completion_words(
                    candidate,
                    MAX_KINA_RESPONSE_WORDS,
                )

        if not candidate or self._contains_forbidden_content(candidate):
            candidate = self._limit_paragraphs(self._limit_questions(fallback))
            if enforce_word_limit:
                candidate = self._limit_words(candidate, MAX_KINA_RESPONSE_WORDS)
            if is_complete:
                candidate = self._ensure_completion(candidate)
                if enforce_word_limit:
                    candidate = self._limit_completion_words(
                        candidate,
                        MAX_KINA_RESPONSE_WORDS,
                    )
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

    def _limit_words(self, text: str, max_words: int) -> str:
        words = re.findall(r"\S+", text)
        if len(words) <= max_words:
            return text

        truncated = " ".join(words[:max_words]).rstrip(" ,;:")
        sentence_end = max(truncated.rfind("."), truncated.rfind("?"))
        if sentence_end >= len(truncated) // 2:
            return truncated[: sentence_end + 1]
        return f"{truncated.rstrip('.')}..."

    def _limit_completion_words(self, text: str, max_words: int) -> str:
        if len(re.findall(r"\S+", text)) <= max_words:
            return text
        closing_words = len(re.findall(r"\S+", COMPLETION_MESSAGE))
        summary_limit = max(20, max_words - closing_words)
        summary = text.replace(COMPLETION_MESSAGE, "").strip()
        return f"{self._limit_words(summary, summary_limit)}\n\n{COMPLETION_MESSAGE}"

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
