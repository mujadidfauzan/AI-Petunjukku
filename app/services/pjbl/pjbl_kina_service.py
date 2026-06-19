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
from app.services.pjbl.pjbl_prompt_templates import PJBL_KINA_SYSTEM_PROMPT
from app.services.prompt_builder_service import PromptBuilderService
from app.services.rag_service import RAGService
from app.utils.text_cleaner import compact_text


logger = logging.getLogger(__name__)


COMPLETION_MESSAGE = (
    "Terima kasih, rancangan proyek Anda sudah selesai dan siap digunakan untuk "
    "tahap berikutnya."
)

DEFAULT_KINA_MODEL = "deepseek/deepseek-v4-flash"
MAX_KINA_RESPONSE_WORDS = 140

DISCUSSION_STAGES: tuple[tuple[str, str], ...] = (
    ("learning_style", "gaya pembelajaran"),
    ("pedagogical_preference", "preferensi pedagogis"),
    ("learning_environment", "lingkungan belajar"),
    ("implementation_duration", "lama pelaksanaan"),
    ("facility_technology_use", "pemanfaatan fasilitas dan teknologi"),
    ("digital_use", "pemanfaatan digital"),
    ("partnership", "kemitraan"),
    ("final_project_form", "bentuk proyek akhir"),
    ("project_assessment", "penilaian proyek"),
)

STAGE_KEYWORDS: dict[str, tuple[str, ...]] = {
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
    "pedagogical_preference": (
        "preferensi pedagogis",
        "pendekatan pedagogis",
        "model pembelajaran",
        "strategi pembelajaran",
        "praktik pedagogis",
        "inkuiri",
        "project based learning",
        "pjbl",
        "problem based learning",
        "pbl",
        "cooperative learning",
        "discovery",
        "diferensiasi",
        "scaffolding",
        "praktikpedagogis",
        "preferensipedagogis",
    ),
    "learning_environment": (
        "lingkungan belajar",
        "area belajar",
        "tempat belajar",
        "kelas",
        "luar kelas",
        "halaman sekolah",
        "kantin",
        "perpustakaan",
        "laboratorium",
        "sekitar sekolah",
        "lingkungan sekolah",
        "belajarenvironment",
        "learningenvironment",
    ),
    "implementation_duration": (
        "lama pelaksanaan",
        "durasi",
        "durasi kegiatan",
        "durasi proyek",
        "berapa lama",
        "berapa tahap",
        "berapa pertemuan",
        "alur kegiatan",
        "jadwal",
        "tahapan proyek",
        "tahap pelaksanaan",
        "timeline",
        "minggu pertama",
        "pertemuan",
        "projectactivitiesoverview",
        "activityflowdecision",
        "projectduration",
        "implementationduration",
    ),
    "facility_technology_use": (
        "pemanfaatan fasilitas",
        "fasilitas dan teknologi",
        "fasilitas",
        "teknologi",
        "proyektor",
        "internet",
        "gawai",
        "hp",
        "laptop",
        "kamera",
        "alat tulis",
        "bahan",
        "media",
        "facilityandtechnologyuse",
        "facilitiestechnologyuse",
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
    "partnership": (
        "kemitraan",
        "mitra",
        "narasumber",
        "orang tua",
        "komunitas",
        "warga",
        "umkm",
        "pelaku usaha",
        "tanpa mitra",
        "tidak perlu mitra",
        "tidak menggunakan mitra",
        "partnership",
        "kemitraandetail",
    ),
    "final_project_form": (
        "bentuk proyek akhir",
        "produk akhir",
        "aksi akhir",
        "hasil akhir",
        "poster",
        "kampanye",
        "prototipe",
        "laporan",
        "infografis",
        "infografik",
        "pameran",
        "video",
        "karya",
        "presentasi",
        "studentproduct",
        "finalstudentproduct",
        "produkkinerjaakhir",
    ),
    "project_assessment": (
        "penilaian proyek",
        "asesmen",
        "penilaian",
        "rubrik",
        "sumatif",
        "formatif",
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
    "learning_style": re.compile(
        r"\b(?:gaya pembelajaran|gaya belajar|visual|auditori|kinestetik|"
        r"praktik langsung|diskusi|kolaboratif|mandiri|diferensiasi|minat siswa)\b",
        flags=re.IGNORECASE,
    ),
    "pedagogical_preference": re.compile(
        r"\b(?:preferensi pedagogis|pendekatan pedagogis|model pembelajaran|"
        r"strategi pembelajaran|inkuiri|pjbl|project based learning|"
        r"cooperative learning|discovery|scaffolding)\b",
        flags=re.IGNORECASE,
    ),
    "learning_environment": re.compile(
        r"\b(?:lingkungan belajar|area belajar|tempat belajar|kelas|luar kelas|"
        r"halaman sekolah|kantin|perpustakaan|laboratorium|sekitar sekolah)\b",
        flags=re.IGNORECASE,
    ),
    "implementation_duration": re.compile(
        r"\b(?:lama pelaksanaan|durasi|jadwal|alur kegiatan|minggu pertama|"
        r"minggu kedua|minggu ketiga|pertemuan|tahapan proyek|berapa tahap|"
        r"berapa pertemuan)\b",
        flags=re.IGNORECASE,
    ),
    "facility_technology_use": re.compile(
        r"\b(?:pemanfaatan fasilitas|fasilitas|proyektor|halaman sekolah|"
        r"alat tulis|alat|peralatan|internet|gawai|hp|laptop|kamera|"
        r"teknologi)\b",
        flags=re.IGNORECASE,
    ),
    "digital_use": re.compile(
        r"\b(?:pemanfaatan digital|digital|aplikasi|platform|canva|google forms?|"
        r"google docs|google slides|padlet|spreadsheet|video|kamera|"
        r"dokumentasi digital|media digital)\b",
        flags=re.IGNORECASE,
    ),
    "partnership": re.compile(
        r"\b(?:mitra|kemitraan|narasumber|orang tua|komunitas|warga|umkm|"
        r"pelaku usaha|tanpa mitra|tidak perlu mitra|tidak menggunakan mitra)\b",
        flags=re.IGNORECASE,
    ),
    "final_project_form": re.compile(
        r"\b(?:bentuk proyek akhir|produk akhir|aksi akhir|hasil akhir|"
        r"infografis|infografik|poster|laporan|video|prototipe|kampanye|"
        r"pameran|presentasi)\b",
        flags=re.IGNORECASE,
    ),
    "project_assessment": re.compile(
        r"\b(?:penilaian proyek|penilaian|asesmen|rubrik|bukti proses|"
        r"kontribusi individu|kriteria keberhasilan|refleksi individu|"
        r"refleksi siswa|formatif|sumatif)\b",
        flags=re.IGNORECASE,
    ),
}
STAGE_REQUIRED_SLOTS: dict[str, tuple[tuple[str, str, re.Pattern[str]], ...]] = {
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
    "pedagogical_preference": (
        (
            "approach",
            "preferensi pedagogis",
            re.compile(
                r"\b(?:preferensi pedagogis|pendekatan pedagogis|model pembelajaran|"
                r"strategi pembelajaran|inkuiri|eksplorasi|pjbl|project based learning|"
                r"cooperative learning|kolaboratif|discovery|scaffolding|"
                r"diferensiasi|berbasis proyek)\b",
                flags=re.IGNORECASE,
            ),
        ),
    ),
    "learning_environment": (
        (
            "environment",
            "lingkungan belajar",
            re.compile(
                r"\b(?:lingkungan belajar|area belajar|tempat belajar|kelas|"
                r"luar kelas|halaman sekolah|halaman madrasah|kantin|"
                r"perpustakaan|laboratorium|sekitar sekolah|lingkungan sekolah|"
                r"area observasi|lokasi proyek)\b",
                flags=re.IGNORECASE,
            ),
        ),
    ),
    "implementation_duration": (
        (
            "duration_or_steps",
            "jumlah tahap atau pertemuan",
            re.compile(
                r"\b(?:\d+|satu|dua|tiga|empat|lima|enam|tujuh|delapan|"
                r"sembilan|sepuluh)\s*(?:hari|minggu|bulan|pertemuan|jp|jam|"
                r"menit|tahap)\b|\b(?:durasi|jadwal|alokasi waktu|"
                r"lama pelaksanaan|berapa tahap|berapa pertemuan|timeline)\b",
                flags=re.IGNORECASE,
            ),
        ),
    ),
    "facility_technology_use": (
        (
            "facility",
            "fasilitas atau teknologi",
            re.compile(
                r"\b(?:fasilitas|proyektor|internet|gawai|hp|laptop|kamera|"
                r"alat tulis|bahan|media|papan tulis|kelas|halaman sekolah|"
                r"perpustakaan|laboratorium|teknologi)\b",
                flags=re.IGNORECASE,
            ),
        ),
        (
            "usage",
            "cara pemanfaatan fasilitas atau teknologi",
            re.compile(
                r"\b(?:pakai|gunakan|menggunakan|digunakan|untuk|membantu|"
                r"presentasi|observasi|dokumentasi|pengumpulan data|"
                r"mengolah data|menyajikan hasil|membuat produk)\b",
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
                r"laptop|internet|tanpa digital|tidak menggunakan digital)\b",
                flags=re.IGNORECASE,
            ),
        ),
    ),
    "partnership": (
        (
            "partnership_decision",
            "keputusan kemitraan",
            re.compile(
                r"\b(?:mitra|kemitraan|narasumber|orang tua|komunitas|warga|"
                r"umkm|pelaku usaha|kantin|puskesmas|perpustakaan|tanpa mitra|"
                r"tidak perlu mitra|tidak menggunakan mitra|mitra internal)\b",
                flags=re.IGNORECASE,
            ),
        ),
    ),
    "final_project_form": (
        (
            "product_form",
            "bentuk proyek akhir",
            re.compile(
                r"\b(?:bentuk proyek akhir|produk akhir|aksi akhir|hasil akhir|"
                r"poster|infografis|infografik|laporan|video|prototipe|"
                r"kampanye|pameran|presentasi|karya|media kampanye|peta temuan|"
                r"tabel temuan|portofolio)\b",
                flags=re.IGNORECASE,
            ),
        ),
    ),
    "project_assessment": (
        (
            "assessment",
            "aspek atau kriteria penilaian proyek",
            re.compile(
                r"\b(?:penilaian proyek|asesmen|penilaian|nilai|rubrik|"
                r"kriteria|kontribusi|kerja sama|produk|proses|presentasi|"
                r"formatif|sumatif)\b",
                flags=re.IGNORECASE,
            ),
        ),
        (
            "evidence_reflection",
            "bukti penilaian atau refleksi",
            re.compile(
                r"\b(?:bukti|catatan|jurnal|observasi|dokumentasi|foto|"
                r"presentasi|refleksi|umpan balik|hasil kerja|lembar refleksi)\b",
                flags=re.IGNORECASE,
            ),
        ),
    ),
}
SAVED_STAGE_SUMMARY_FIELDS: dict[str, str] = {
    "learningStyle": "learning_style",
    "pedagogicalPreference": "pedagogical_preference",
    "pedagogicalApproach": "pedagogical_preference",
    "learningEnvironment": "learning_environment",
    "implementationDuration": "implementation_duration",
    "activitiesAndSchedule": "implementation_duration",
    "facilitiesTechnologyUse": "facility_technology_use",
    "facilityAndTechnologyUse": "facility_technology_use",
    "facilitiesTechnologyPartnership": "facility_technology_use",
    "digitalUse": "digital_use",
    "digitalPlatform": "digital_use",
    "partnership": "partnership",
    "partnershipDetail": "partnership",
    "finalProjectForm": "final_project_form",
    "finalProduct": "final_project_form",
    "finalStudentProduct": "final_project_form",
    "projectAssessment": "project_assessment",
    "assessmentReflection": "project_assessment",
}
STAGE_MEMORY_FIELDS: dict[str, str] = {
    "learning_style": "learningStyle",
    "pedagogical_preference": "pedagogicalPreference",
    "learning_environment": "learningEnvironment",
    "implementation_duration": "implementationDuration",
    "facility_technology_use": "facilitiesTechnologyUse",
    "digital_use": "digitalUse",
    "partnership": "partnership",
    "final_project_form": "finalProjectForm",
    "project_assessment": "projectAssessment",
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

            local_suggestions = self._local_suggested_questions(payload, analysis)
            llm_started = perf_counter()
            try:
                turn_output = await self._generate_single_turn(
                    payload=payload,
                    context=context,
                    analysis=analysis,
                    fallback=fallback,
                    local_suggestions=local_suggestions,
                )
                stage_statuses["llm"] = "success"
                route = "single_deepseek"
                stage_assessment = self._normalize_stage_assessment(
                    turn_output.get("stageAssessment"),
                    analysis=analysis,
                    stage3_memory=stage3_memory,
                )
                if analysis["input_relevance"] in {"irrelevant", "unclear"}:
                    reply = fallback
                else:
                    reply = self._sanitize_reply(
                        str(turn_output.get("reply") or ""),
                        fallback=fallback,
                        is_complete=self._assessment_is_complete(stage_assessment),
                        limit_options=analysis["teacher_uncertain"],
                        enforce_word_limit=True,
                    )
                suggested_followups = self._clean_suggestions(
                    [
                        item
                        for item in turn_output.get(
                            "suggestedFollowUpQuestions",
                            [],
                        )
                        if isinstance(item, str)
                    ]
                )
                if not suggested_followups:
                    suggested_followups = local_suggestions
            except Exception as exc:
                logger.warning("Kina single LLM turn failed: %s", exc)
                stage_statuses["llm"] = "error"
                route = "single_deepseek_fallback"
                reply = fallback
                stage_assessment = self._normalize_stage_assessment(
                    {},
                    analysis=analysis,
                    stage3_memory=stage3_memory,
                )
                suggested_followups = self._local_suggested_questions(payload, analysis)
            finally:
                timings["llm"] = self._elapsed_ms(llm_started)

            if (
                not compact_text(payload.message, 700)
                and re.search(
                    r"\b(?:belum melihat kaitan|apa kaitannya)\b",
                    reply,
                    flags=re.IGNORECASE,
                )
            ):
                reply = fallback

            stage3_memory = self._build_stage3_memory(
                payload,
                analysis,
                stage_assessment=stage_assessment,
            )
            progress = self._progress_payload(analysis, stage_assessment)

            return KinaChatResponse(
                reply=reply,
                model=self._kina_model(),
                usedReferences=[
                    UsedReferenceSchema(
                        cpReferenceId=reference.cpReferenceId,
                        sourceTitle=reference.sourceTitle,
                        similarityScore=reference.similarityScore,
                    )
                    for reference in references
                ],
                suggestedFollowUpQuestions=suggested_followups,
                progress=progress,
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
            "llm",
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

    async def _generate_single_turn(
        self,
        *,
        payload: KinaChatRequest,
        context: dict[str, Any],
        analysis: dict[str, Any],
        fallback: str,
        local_suggestions: list[str],
    ) -> dict[str, Any]:
        required_shape = {
            "reply": fallback,
            "stageAssessment": self._stage_assessment_fallback(
                analysis,
                context.get("stage_3_memory") or {},
            ),
            "suggestedFollowUpQuestions": local_suggestions,
        }
        return await self.llm_client.generate_json_once(
            [
                {"role": "system", "content": PJBL_KINA_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "latestUserMessage": payload.message,
                            "project": context["project"],
                            "stage1Context": context["stage_1_summary"],
                            "stage2SelectedProjectContext": context[
                                "stage_2_summary"
                            ],
                            "stage3Memory": context["stage_3_memory"],
                            "recentExchange": context["recent_exchange"],
                            "teacherDecisions": context["teacher_decisions"],
                            "savedStageDecisions": context[
                                "saved_stage_decisions"
                            ],
                            "turnContext": {
                                "isInitialTurn": not bool(
                                    compact_text(payload.message, 700)
                                ),
                                "activeStage": context[
                                    "current_conversation_stage_key"
                                ],
                                "activeLabel": context[
                                    "current_conversation_stage"
                                ],
                                "expectedStageBeforeMessage": context[
                                    "expected_stage_before_message"
                                ],
                                "expectedLabelBeforeMessage": context[
                                    "expected_label_before_message"
                                ],
                                "inputStageKeys": context["input_stage_keys"],
                                "inputOutOfSequence": context[
                                    "input_out_of_sequence"
                                ],
                                "inputRelevance": context["input_relevance"],
                                "teacherUncertain": context["teacher_uncertain"],
                                "changeRequested": context["change_requested"],
                                "missingSlots": context["missing_slots"],
                                "conversationComplete": context[
                                    "conversation_complete"
                                ],
                                "instruction": self._turn_instruction_from_context(
                                    context
                                ),
                            },
                            "discussionFlow": context["discussion_flow"],
                            "requiredResponseShape": required_shape,
                        },
                        ensure_ascii=False,
                    ),
                },
            ],
            model=self._kina_model(),
            temperature=0.35,
            max_tokens=1300,
        )

    def _stage_assessment_fallback(
        self,
        analysis: dict[str, Any],
        stage3_memory: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        confirmed = (
            stage3_memory.get("confirmedDecisions")
            if isinstance(stage3_memory, dict)
            else {}
        )
        if not isinstance(confirmed, dict):
            confirmed = {}
        slot_progress = analysis.get("stage_slot_progress") or {}
        stage_slot_sets = {
            key: set(slot_progress.get(key, [])) for key, _ in DISCUSSION_STAGES
        }
        assessment: dict[str, dict[str, Any]] = {}
        for key, label in DISCUSSION_STAGES:
            summary = compact_text(self._flatten(confirmed.get(key, "")), 500)
            complete = bool(analysis.get("evidence", {}).get(key)) and bool(summary)
            missing = [] if complete else self._missing_stage_slot_labels(
                key,
                stage_slot_sets,
            )
            assessment[key] = {
                "key": key,
                "label": label,
                "complete": complete,
                "summary": summary,
                "missingSlots": missing,
            }
        return assessment

    def _normalize_stage_assessment(
        self,
        value: Any,
        *,
        analysis: dict[str, Any],
        stage3_memory: dict[str, Any],
    ) -> dict[str, dict[str, Any]]:
        fallback = self._stage_assessment_fallback(analysis, stage3_memory)
        raw = value if isinstance(value, dict) else {}
        normalized: dict[str, dict[str, Any]] = {}

        for key, label in DISCUSSION_STAGES:
            item = raw.get(key) or raw.get(STAGE_MEMORY_FIELDS.get(key, ""))
            if not isinstance(item, dict):
                item = {}

            summary = compact_text(
                item.get("summary") or fallback[key].get("summary") or "",
                500,
            )
            missing = self._clean_string_list(
                item.get("missingSlots") or fallback[key].get("missingSlots") or [],
                limit=4,
            )
            complete = bool(item.get("complete", fallback[key]["complete"]))
            if complete and not summary:
                complete = False
            if complete:
                missing = []

            normalized[key] = {
                "key": key,
                "label": label,
                "complete": complete,
                "summary": summary,
                "missingSlots": missing,
            }

        return normalized

    def _assessment_is_complete(
        self,
        stage_assessment: dict[str, dict[str, Any]],
    ) -> bool:
        return all(
            bool(stage_assessment.get(key, {}).get("complete"))
            for key, _ in DISCUSSION_STAGES
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

    def _clean_internal_text(self, value: Any) -> str:
        return compact_text(str(value or ""), 700)

    def _kina_model(self) -> str:
        llm_settings = getattr(self.llm_client, "settings", None)
        configured = str(
            getattr(llm_settings, "kina_llm_model", DEFAULT_KINA_MODEL) or ""
        ).strip()
        if configured.startswith("deepseek/"):
            return configured
        return DEFAULT_KINA_MODEL

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

    def _progress_payload(
        self,
        analysis: dict[str, Any],
        stage_assessment: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        stage_assessment = stage_assessment or self._stage_assessment_fallback(
            analysis,
            {},
        )
        total_count = len(DISCUSSION_STAGES)
        completed_count = sum(
            1
            for key, _ in DISCUSSION_STAGES
            if stage_assessment.get(key, {}).get("complete")
        )
        active_stage = "complete"
        active_label = "selesai"
        for key, label in DISCUSSION_STAGES:
            if not stage_assessment.get(key, {}).get("complete"):
                active_stage = key
                active_label = label
                break

        is_complete = completed_count == total_count
        missing_slots = (
            []
            if is_complete
            else self._clean_string_list(
                stage_assessment.get(active_stage, {}).get("missingSlots") or [],
                limit=4,
            )
        )
        stage_slot_sets = {
            slot_key: set(analysis["stage_slot_progress"].get(slot_key, []))
            for slot_key, _ in DISCUSSION_STAGES
        }
        return {
            "activeStage": active_stage,
            "activeLabel": active_label,
            "completedCount": completed_count,
            "totalCount": total_count,
            "percentage": round((completed_count / total_count) * 100),
            "isComplete": is_complete,
            "missingSlots": missing_slots,
            "stages": [
                {
                    "key": key,
                    "label": label,
                    "complete": bool(stage_assessment.get(key, {}).get("complete")),
                    "summary": stage_assessment.get(key, {}).get("summary", ""),
                    "foundSlots": analysis["stage_slot_progress"].get(key, []),
                    "missingSlots": stage_assessment.get(key, {}).get(
                        "missingSlots",
                        self._missing_stage_slot_labels(key, stage_slot_sets),
                    ),
                }
                for key, label in DISCUSSION_STAGES
            ],
        }

    def _build_stage3_memory(
        self,
        payload: KinaChatRequest,
        analysis: dict[str, Any],
        *,
        stage_assessment: dict[str, dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        confirmed_decisions = self._memory_confirmed_decisions(payload)
        self._merge_saved_stage_decisions(payload, confirmed_decisions)
        self._merge_history_stage_decisions(payload, confirmed_decisions)
        if stage_assessment:
            for key, item in stage_assessment.items():
                summary = compact_text(item.get("summary") or "", 700)
                if key in dict(DISCUSSION_STAGES) and summary:
                    confirmed_decisions[key] = summary

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
            if (
                stage_assessment
                and stage_assessment.get(key, {}).get("complete")
            )
            or self._stage_slots_complete(key, stage_slot_sets[key])
        ]
        normalized_assessment = stage_assessment or self._stage_assessment_fallback(
            analysis,
            {"confirmedDecisions": confirmed_decisions},
        )
        open_questions = [
            f"{label}: {', '.join(missing)}"
            for key, label in DISCUSSION_STAGES
            if (
                missing := self._clean_string_list(
                    normalized_assessment.get(key, {}).get("missingSlots")
                    or self._missing_stage_slot_labels(key, stage_slot_sets),
                    limit=4,
                )
            )
        ][:7]

        return {
            "version": 2,
            "activeStage": self._progress_payload(
                analysis,
                normalized_assessment,
            )["activeStage"],
            "activeLabel": self._progress_payload(
                analysis,
                normalized_assessment,
            )["activeLabel"],
            "confirmedDecisions": {
                key: confirmed_decisions.get(key, "")
                for key, _ in DISCUSSION_STAGES
            },
            "savedStageFields": {
                STAGE_MEMORY_FIELDS[key]: confirmed_decisions.get(key, "")
                for key, _ in DISCUSSION_STAGES
            },
            "legacyStageFields": self._legacy_stage_fields(confirmed_decisions),
            "stageAssessment": normalized_assessment,
            "stageSummaries": {
                key: normalized_assessment.get(key, {}).get("summary", "")
                for key, _ in DISCUSSION_STAGES
            },
            "stageSlotProgress": stage_slot_progress,
            "completedStageKeys": completed_stage_keys,
            "latestSummary": self._stage3_memory_summary(confirmed_decisions),
            "openQuestions": open_questions,
        }

    def _legacy_stage_fields(
        self,
        confirmed_decisions: dict[str, str],
    ) -> dict[str, str]:
        facilities = confirmed_decisions.get("facility_technology_use", "")
        partnership = confirmed_decisions.get("partnership", "")
        facilities_and_partnership = compact_text(
            " ".join(part for part in (facilities, partnership) if part),
            900,
        )
        return {
            "learningStyle": confirmed_decisions.get("learning_style", ""),
            "pedagogicalApproach": confirmed_decisions.get(
                "pedagogical_preference",
                "",
            ),
            "activitiesAndSchedule": confirmed_decisions.get(
                "implementation_duration",
                "",
            ),
            "facilitiesTechnologyPartnership": facilities_and_partnership,
            "digitalUse": confirmed_decisions.get("digital_use", ""),
            "finalProduct": confirmed_decisions.get("final_project_form", ""),
            "assessmentReflection": confirmed_decisions.get(
                "project_assessment",
                "",
            ),
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
        raw_legacy_fields = raw_memory.get("legacyStageFields")
        raw_assessment = raw_memory.get("stageAssessment")
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
            if self._is_empty_saved_decision(value) and isinstance(
                raw_assessment,
                dict,
            ):
                assessment_item = raw_assessment.get(key)
                if isinstance(assessment_item, dict):
                    value = assessment_item.get("summary")
            if self._is_empty_saved_decision(value) and isinstance(
                raw_legacy_fields,
                dict,
            ):
                for legacy_field, legacy_stage_key in SAVED_STAGE_SUMMARY_FIELDS.items():
                    if legacy_stage_key == key:
                        value = raw_legacy_fields.get(legacy_field)
                        if not self._is_empty_saved_decision(value):
                            break
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
        if not message:
            return "current"
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
            r"aplikasi|platform|pedagogis|lingkungan belajar|kemitraan|mitra|"
            r"durasi|pertemuan|tahap)\b",
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
        raw_assessment = raw_memory.get("stageAssessment")
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

        if isinstance(raw_assessment, dict):
            for key, item in raw_assessment.items():
                if key not in stage_slots or not isinstance(item, dict):
                    continue
                if item.get("complete") and not self._is_empty_saved_decision(
                    item.get("summary")
                ):
                    stage_slots[key].update(
                        slot_key
                        for slot_key, _, _ in STAGE_REQUIRED_SLOTS.get(key, ())
                    )
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
                "durasi, fasilitas, biaya, dan risiko. Beri rekomendasi apakah perubahan "
                "itu layak, perlu dipersempit, atau sebaiknya menjadi variasi kecil."
            )
        if analysis.get("input_relevance") == "irrelevant":
            return (
                "Pesan guru tidak relevan dengan diskusi RPP PjBL saat ini. Jangan "
                "mencatatnya sebagai keputusan proyek dan jangan menjawab topik di luar "
                "cakupan secara panjang. Jelaskan batasan dengan sopan, lalu beri "
                f"jembatan singkat kembali ke {analysis['active_label']}."
            )
        if analysis.get("input_relevance") == "unclear":
            return (
                "Hubungan pesan guru dengan diskusi saat ini belum jelas. Jangan "
                "menganggapnya sebagai keputusan. Tawarkan contoh cara mengaitkannya "
                f"dengan {analysis['active_label']}, lalu minta klarifikasi singkat."
            )
        if analysis.get("input_relevance") == "project":
            return (
                "Pesan guru relevan dengan proyek tetapi membahas bagian lain. Jawab "
                "substansinya dulu dengan penilaian atau rekomendasi singkat, catat jika "
                "jelas, lalu hubungkan kembali ke "
                f"{analysis['active_label']} secara natural."
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
            f"Diskusikan {analysis['active_label']} sebagai keputusan desain proyek, "
            "bukan sebagai isian formulir. Jika guru memberi ide, nilai kelayakannya "
            "dan beri rekomendasi konkret. Jika guru bertanya atau ragu, jawab dulu "
            "dengan opsi dan alasan singkat. Pertahankan keputusan yang sudah "
            "disepakati, jangan menyimpulkan tahap sebelum informasi wajibnya lengkap, "
            f"dan ajukan maksimal satu pertanyaan hanya bila perlu.{missing_instruction}"
        )

    def _fallback_reply(
        self,
        payload: KinaChatRequest,
        analysis: dict[str, Any],
    ) -> str:
        project_title = self._project_title(payload)
        next_question = self._question_for_missing_slot(analysis)

        if not compact_text(payload.message, 700):
            return self._initial_context_reply(payload, next_question)
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
                f"Baik, rancangan {project_title} sudah mencakup gaya pembelajaran, "
                "preferensi pedagogis, lingkungan belajar, lama pelaksanaan, fasilitas "
                "dan teknologi, pemanfaatan digital, kemitraan, bentuk proyek akhir, "
                "serta penilaian proyek.\n\n"
                f"{COMPLETION_MESSAGE}"
            )
        if analysis["teacher_uncertain"]:
            return self._uncertainty_reply(project_title, analysis["active_stage"])

        latest_decision = compact_text(payload.message, 180)
        active_stage = analysis["active_stage"]
        if active_stage == "learning_style":
            return (
                f"Untuk {project_title}, gaya belajar sebaiknya tidak terlalu teoritis. "
                "Saya menilai praktik langsung yang dipadukan diskusi kecil akan lebih "
                "kuat, karena siswa bisa melihat masalah nyata lalu mengolah temuan "
                "bersama.\n\n"
                f"Kita bisa pakai itu sebagai arah awal, atau Bapak/Ibu ingin gaya lain? {next_question}"
            )
        if active_stage == "pedagogical_preference":
            return (
                "Gaya pembelajaran tadi sudah bisa jadi dasar. Rekomendasi saya: "
                "inkuiri terbimbing, karena proyek tetap memberi ruang eksplorasi tetapi "
                "guru masih menjaga arah, waktu, dan kualitas data siswa.\n\n"
                f"Kalau kelasnya cukup mandiri, pendekatan kolaboratif juga bisa diperkuat. {next_question}"
            )
        if active_stage == "learning_environment":
            return (
                "Untuk lingkungan belajar, pilihan paling aman biasanya kombinasi: kelas "
                "untuk diskusi dan refleksi, area sekolah untuk observasi singkat. Ini "
                "menjaga proyek tetap kontekstual tanpa membuat kontrol kelas terlalu berat.\n\n"
                f"{next_question}"
            )
        if active_stage == "implementation_duration":
            return (
                f"Saya tangkap arahnya: {latest_decision}. Dari sisi kelayakan, durasi "
                "perlu dibuat cukup pendek agar observasi, produk, dan presentasi tidak "
                "melebar.\n\n"
                f"Rekomendasi saya 3-4 tahap/pertemuan dengan target kecil tiap tahap. {next_question}"
            )
        if active_stage == "facility_technology_use":
            return (
                "Untuk fasilitas, prinsipnya pakai yang sudah tersedia agar proyek tidak "
                "berhenti karena alat. Proyektor cocok untuk contoh dan presentasi, "
                "sedangkan gawai cukup untuk dokumentasi atau pengumpulan data sederhana.\n\n"
                f"{next_question}"
            )
        if active_stage == "digital_use":
            return (
                "Pemanfaatan digital sebaiknya tidak menjadi beban tambahan. Menurut saya "
                "digital paling berguna untuk tiga hal: dokumentasi, pengumpulan data "
                "singkat, dan menyajikan produk akhir.\n\n"
                f"Jika akses internet terbatas, cukup pakai kamera dan Slides/Canva saat di kelas. {next_question}"
            )
        if active_stage == "partnership":
            return (
                "Kemitraan tidak wajib. Kalau waktunya pendek, tanpa mitra luar justru "
                "lebih aman. Jika ingin tetap ada nuansa nyata, cukup libatkan warga "
                "sekolah sebagai narasumber ringan.\n\n"
                f"{next_question}"
            )
        if active_stage == "final_project_form":
            return (
                "Bentuk proyek akhir perlu sederhana tapi terlihat hasil belajarnya. "
                "Saya cenderung merekomendasikan poster/infografis plus presentasi singkat, "
                "karena siswa bisa menunjukkan data, pesan, dan proses berpikirnya.\n\n"
                f"{next_question}"
            )
        return (
            "Untuk penilaian, jangan hanya menilai produk akhir. Lebih adil jika rubrik "
            "memuat proses kerja, ketepatan data, kualitas produk, presentasi, dan "
            "refleksi individu.\n\n"
            f"Ini membantu siswa yang kontribusinya kuat tetapi bukan penyaji utama tetap terlihat. {next_question}"
        )

    def _initial_context_reply(
        self,
        payload: KinaChatRequest,
        next_question: str,
    ) -> str:
        context = self._suggestion_context(payload)
        project_title = self._project_title(payload)
        issue = context.get("issue") or "isu lokal yang sudah dipetakan"
        location = context.get("location") or "lingkungan sekolah"
        duration = context.get("duration") or "durasi yang tersedia"
        products = context.get("products") or []
        product_text = ", ".join(products[:2]) if products else "produk proyek siswa"
        facilities = context.get("facilities") or []
        facility_text = ", ".join(facilities[:2]) if facilities else "fasilitas sekolah yang tersedia"
        question = next_question or "Gaya pembelajaran apa yang paling cocok untuk kelas ini?"

        return (
            f"Kita mulai Stage 3 dari {project_title}. Dari Stage 1, konteksnya "
            f"berangkat dari {issue} di {location}, dengan dukungan {facility_text} "
            f"dan alokasi sekitar {duration}.\n\n"
            f"Dari Stage 2, proyek sudah mengarah pada {product_text}. Menurut saya "
            "arah paling aman adalah diskusi singkat, observasi/praktik, lalu produk "
            f"visual agar siswa tidak hanya mendengar penjelasan. {question}"
        )

    def _uncertainty_reply(self, project_title: str, active_stage: str) -> str:
        options: dict[str, tuple[str, str, str]] = {
            "learning_style": (
                "gunakan praktik langsung agar siswa belajar dari pengalaman nyata",
                "gunakan diskusi kelompok kecil agar ide siswa saling melengkapi",
                "gunakan pendekatan visual agar temuan mudah dipahami dan dipresentasikan",
            ),
            "pedagogical_preference": (
                "inkuiri terbimbing agar siswa tetap punya arahan",
                "kolaboratif agar diskusi dan pembagian tugas lebih kuat",
                "diferensiasi sederhana agar siswa bisa memilih peran sesuai kemampuan",
            ),
            "learning_environment": (
                "kelas sebagai pusat diskusi dan refleksi",
                "area sekolah sebagai tempat observasi terbatas",
                "kombinasi kelas dan area sekolah agar proyek tetap kontekstual",
            ),
            "implementation_duration": (
                "tiga tahap untuk proyek singkat",
                "empat pertemuan agar ada waktu observasi, produk, dan presentasi",
                "alur mingguan dengan target kecil agar mudah dipantau",
            ),
            "facility_technology_use": (
                "gunakan fasilitas kelas yang sudah tersedia",
                "gunakan gawai secara terbatas hanya untuk dokumentasi atau riset",
                "gunakan proyektor untuk contoh, diskusi, dan presentasi hasil",
            ),
            "digital_use": (
                "gunakan gawai hanya untuk dokumentasi foto atau video singkat",
                "gunakan Canva atau Slides untuk menyusun produk presentasi",
                "gunakan Google Form sederhana untuk mengumpulkan data observasi",
            ),
            "partnership": (
                "tanpa mitra luar agar pelaksanaan lebih ringan",
                "libatkan warga sekolah sebagai narasumber sederhana",
                "libatkan orang tua hanya untuk dukungan alat atau informasi",
            ),
            "final_project_form": (
                "poster atau infografis karena mudah dibuat dan dipresentasikan",
                "laporan temuan singkat karena kuat untuk menunjukkan data",
                "presentasi kelompok dengan produk visual sederhana",
            ),
            "project_assessment": (
                "nilai proses dan kerja sama melalui observasi",
                "nilai produk menggunakan rubrik sederhana",
                "gabungkan presentasi kelompok dengan refleksi individu",
            ),
        }
        first, second, third = options.get(active_stage, options["learning_style"])
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
        grade = context["grade"]

        if active_stage == "learning_style":
            return [
                "Gunakan praktik langsung dan diskusi kelompok kecil.",
                "Gaya belajarnya visual dan kolaboratif agar hasil mudah dipresentasikan.",
                "Utamakan observasi langsung, kerja kelompok, lalu refleksi singkat.",
            ]
        if active_stage == "pedagogical_preference":
            return [
                "Gunakan inkuiri terbimbing agar murid tetap punya arahan.",
                "Pakai kolaboratif berbasis proyek dengan contoh dan umpan balik bertahap.",
                "Gunakan diferensiasi sederhana melalui pilihan peran dan produk.",
            ]
        if active_stage == "learning_environment":
            return [
                f"Gunakan kelas dan {location} sebagai lingkungan belajar.",
                f"Observasi dibatasi di {location} agar aman untuk {grade}.",
                "Kelas dipakai untuk diskusi, sedangkan area sekolah untuk observasi singkat.",
            ]
        if active_stage == "implementation_duration":
            flow = ", ".join(activities[:4])
            return [
                f"Gunakan durasi {duration}.",
                f"Proyek dijalankan dalam {duration} dengan alur: {flow}.",
                "Bagi menjadi 4 pertemuan: pemantik, observasi, produk, presentasi-refleksi.",
            ]
        if active_stage == "facility_technology_use":
            facility_text = ", ".join(facilities[:3])
            return [
                f"Gunakan {facility_text} untuk observasi, diskusi, dan presentasi.",
                f"Fasilitas cukup memakai {facility_text} agar proyek tetap sederhana.",
                "Pakai proyektor untuk contoh dan presentasi; gawai hanya untuk dokumentasi.",
            ]
        if active_stage == "digital_use":
            return [
                "Digital dipakai untuk dokumentasi foto, pengumpulan data, dan presentasi.",
                "Gunakan Canva atau Slides untuk menyusun produk akhir kelompok.",
                "Gunakan Google Form sederhana agar data observasi mudah dikumpulkan.",
            ]
        if active_stage == "partnership":
            return [
                "Tidak perlu mitra luar dulu agar proyek mudah dijalankan.",
                "Libatkan warga sekolah sebagai narasumber ringan.",
                "Gunakan orang tua hanya untuk dukungan alat atau informasi sederhana.",
            ]
        if active_stage == "final_project_form":
            product_text = ", ".join(products[:2])
            return [
                f"Bentuk akhirnya {product_text}.",
                f"Saya pilih {products[0]} karena paling realistis dibuat murid.",
                "Produk dibuat sederhana, visual, dan dipresentasikan singkat di kelas.",
            ]
        if active_stage == "project_assessment" and slot_key == "assessment":
            return [
                "Nilai proses kerja kelompok, ketepatan data, kualitas produk, dan presentasi.",
                "Aspek utamanya kelengkapan data, kolaborasi, dan kejelasan pesan produk.",
                "Gunakan rubrik sederhana untuk proses, produk, kontribusi, dan komunikasi.",
            ]
        if active_stage == "project_assessment" and slot_key == "evidence_reflection":
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
            ("learning_style", "style"): (
                "Gaya pembelajaran apa yang paling cocok untuk kelas ini?"
            ),
            ("pedagogical_preference", "approach"): (
                "Preferensi pedagogis apa yang ingin dipakai untuk proyek ini?"
            ),
            ("learning_environment", "environment"): (
                "Lingkungan belajar proyeknya akan berlangsung di mana?"
            ),
            ("implementation_duration", "duration_or_steps"): (
                "Lama pelaksanaannya ingin dibuat berapa tahap atau berapa pertemuan?"
            ),
            ("facility_technology_use", "facility"): (
                "Fasilitas atau teknologi apa yang paling realistis digunakan?"
            ),
            ("facility_technology_use", "usage"): (
                "Fasilitas dan teknologi itu akan dimanfaatkan untuk apa?"
            ),
            ("digital_use", "digital_plan"): (
                "Pemanfaatan digital apa yang paling realistis digunakan dalam proyek ini?"
            ),
            ("partnership", "partnership_decision"): (
                "Proyek ini perlu kemitraan tertentu atau cukup tanpa mitra luar?"
            ),
            ("final_project_form", "product_form"): (
                "Bentuk proyek akhir apa yang paling realistis dibuat murid?"
            ),
            ("project_assessment", "assessment"): (
                "Aspek proses dan hasil apa yang paling penting dinilai dalam proyek?"
            ),
            ("project_assessment", "evidence_reflection"): (
                "Bukti penilaian atau refleksi apa yang akan dikumpulkan dari murid?"
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
