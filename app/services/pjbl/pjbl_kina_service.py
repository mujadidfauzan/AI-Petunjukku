from __future__ import annotations

import json
import logging
import re
from time import perf_counter
from typing import Any

from app.schemas.common_schema import UsedReferenceSchema
from app.schemas.kina_schema import (
    KinaChatRequest,
    KinaChatResponse,
    KinaInformationPoint,
    KinaInformationProgress,
)
from app.schemas.rag_schema import RagReference
from app.services.llm_client import LLMClient
from app.services.pjbl.pjbl_prompt_templates import (
    PJBL_KINA_EVALUATOR_SYSTEM_PROMPT,
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

DEFAULT_KINA_MODEL = "qwen/qwen3-coder-flash"
MAX_KINA_RESPONSE_WORDS = 120

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

EVALUATOR_CHECKS: tuple[str, ...] = (
    "natural_language",
    "not_form_like",
    "max_one_question",
    "validates_teacher",
    "gives_useful_suggestion",
    "avoids_repetition",
    "pedagogically_safe",
    "not_too_long",
    "direct_and_concise",
    "avoids_ai_style",
    "clear_for_teacher",
    "no_internal_output",
    "handles_input_relevance",
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
            context = self._build_kina_context(payload, references, analysis)
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

                    evaluator_started = perf_counter()
                    try:
                        evaluation = await self._evaluate_kina_draft(
                            user_message=payload.message,
                            draft=draft,
                            analysis=analysis,
                        )
                    except Exception:
                        timings["evaluator"] = self._elapsed_ms(evaluator_started)
                        stage_statuses["evaluator"] = "error"
                        route = "evaluator_fallback_to_draft"
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
                    else:
                        timings["evaluator"] = self._elapsed_ms(evaluator_started)
                        stage_statuses["evaluator"] = "success"
                        if evaluation["decision"] == "revise":
                            final_started = perf_counter()
                            try:
                                reply = await self._generate_kina_final_response(
                                    draft=draft,
                                    solver_output=solver_output,
                                    revision_instruction=evaluation[
                                        "revision_instruction"
                                    ],
                                    fallback=fallback,
                                    analysis=analysis,
                                )
                                stage_statuses["final"] = "success"
                                route = "revised"
                            except Exception:
                                stage_statuses["final"] = "error"
                                route = "final_fallback_to_draft"
                                if analysis["input_relevance"] in {
                                    "irrelevant",
                                    "unclear",
                                }:
                                    reply = fallback
                                else:
                                    reply = self._sanitize_reply(
                                        draft,
                                        fallback=fallback,
                                        is_complete=analysis["is_complete"],
                                        limit_options=analysis["teacher_uncertain"],
                                        enforce_word_limit=True,
                                    )
                            finally:
                                timings["final"] = self._elapsed_ms(final_started)
                        else:
                            route = "passed"
                            reply = draft

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
                informationProgress=self._information_progress(analysis),
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
            "evaluator",
            "final",
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
            "final_product": (
                "Pastikan produk akhir menjawab masalah dan sesuai fasilitas.",
                "Produk atau aksi akhir apa yang paling sesuai?",
            ),
            "activities_schedule": (
                "Susun kegiatan bertahap dari observasi hingga presentasi.",
                "Berapa lama durasi proyek yang tersedia?",
            ),
            "roles_support": (
                "Gunakan peran kelompok yang jelas agar kontribusi siswa merata.",
                "Bagaimana peran siswa akan dibagi dalam kelompok?",
            ),
            "facilities_partnership": (
                "Utamakan fasilitas yang tersedia dan kemitraan yang realistis.",
                "Fasilitas apa yang paling realistis digunakan?",
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

    async def _evaluate_kina_draft(
        self,
        *,
        user_message: str,
        draft: str,
        analysis: dict[str, Any],
    ) -> dict[str, Any]:
        requirements = self._evaluation_requirements(user_message, analysis)
        evaluation = await self.llm_client.generate_json(
            [
                {"role": "system", "content": PJBL_KINA_EVALUATOR_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "\n\n".join(
                        [
                            f"PESAN GURU:\n{user_message}",
                            f"DRAFT KINA:\n{draft}",
                            "KEWAJIBAN KONTEKSTUAL:",
                            json.dumps(requirements, ensure_ascii=False),
                        ]
                    ),
                },
            ],
            {},
            model=self._evaluator_model(),
            temperature=0.0,
            max_tokens=450,
        )
        return self._normalize_evaluation(
            evaluation,
            draft=draft,
            requirements=requirements,
        )

    async def _generate_kina_final_response(
        self,
        *,
        draft: str,
        solver_output: dict[str, Any],
        revision_instruction: str,
        fallback: str,
        analysis: dict[str, Any],
    ) -> str:
        relevant_substance = {
            key: solver_output[key]
            for key in (
                "decision_summary",
                "recommended_response_points",
                "pedagogical_suggestions",
                "question_to_ask",
            )
        }
        revised = await self.llm_client.generate_text(
            [
                {"role": "system", "content": PJBL_KINA_SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": "\n\n".join(
                        [
                            f"DRAFT KINA:\n{draft}",
                            f"INSTRUKSI REVISI:\n{revision_instruction}",
                            "SUBSTANSI YANG HARUS DIPERTAHANKAN:",
                            json.dumps(relevant_substance, ensure_ascii=False),
                            "Perbaiki satu kali dan keluarkan hanya teks final Kina. "
                            f"Gunakan maksimal {MAX_KINA_RESPONSE_WORDS} kata, langsung "
                            "ke inti, tanpa metafora atau bahasa khas AI. Jangan menyebut "
                            "proses internal, evaluator, score, atau JSON.",
                        ]
                    ),
                },
            ],
            "",
            model=self._kina_model(),
            temperature=0.4,
            max_tokens=700,
        )
        if not str(revised or "").strip() or self._looks_like_json(str(revised)):
            raise ValueError("Revisi Kina kosong.")
        return self._sanitize_reply(
            revised,
            fallback=fallback,
            is_complete=analysis["is_complete"],
            limit_options=analysis["teacher_uncertain"],
            enforce_word_limit=True,
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

    def _evaluation_requirements(
        self,
        user_message: str,
        analysis: dict[str, Any],
    ) -> dict[str, Any]:
        requires_validation = bool(
            analysis["teacher_uncertain"]
            or analysis["change_requested"]
            or DECISION_PATTERN.search(user_message)
            or SHORT_CONFIRMATION_PATTERN.search(user_message)
            or SIMPLE_FACT_PATTERN.search(user_message)
        )
        return {
            "requires_validation": requires_validation,
            "requires_useful_suggestion": not analysis["is_complete"],
            "input_relevance": analysis["input_relevance"],
            "requires_relevance_handling": analysis["input_relevance"]
            in {"project", "irrelevant", "unclear"},
            "conversation_complete": analysis["is_complete"],
        }

    def _normalize_evaluation(
        self,
        value: Any,
        *,
        draft: str,
        requirements: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(value, dict) or not isinstance(value.get("checks"), dict):
            raise ValueError("Output Evaluator tidak valid.")

        checks = {
            check: value["checks"].get(check) is True for check in EVALUATOR_CHECKS
        }
        for check, local_result in self._local_evaluator_checks(draft).items():
            checks[check] = checks[check] and local_result
        if not requirements["requires_validation"]:
            checks["validates_teacher"] = True
        if not requirements["requires_useful_suggestion"]:
            checks["gives_useful_suggestion"] = True
        if not requirements["requires_relevance_handling"]:
            checks["handles_input_relevance"] = True

        passed = all(checks.values())
        must_fix = self._clean_string_list(value.get("must_fix", []), limit=4)
        failed_checks = [check for check, result in checks.items() if not result]
        must_fix.extend(
            instruction
            for check in failed_checks
            if (instruction := self._revision_instruction_for_check(check))
        )
        must_fix = list(dict.fromkeys(must_fix))[:6]
        model_instruction = self._clean_internal_text(
            value.get("revision_instruction", "")
        )
        revision_parts = must_fix.copy()
        if model_instruction:
            revision_parts.append(model_instruction)
        revision_instruction = "; ".join(dict.fromkeys(revision_parts))
        if not passed and not revision_instruction:
            revision_instruction = "Perbaiki seluruh kriteria evaluator yang gagal."
        return {
            "decision": "pass" if passed else "revise",
            "checks": checks,
            "must_fix": must_fix,
            "revision_instruction": compact_text(revision_instruction, 700),
        }

    def _local_evaluator_checks(self, draft: str) -> dict[str, bool]:
        words = re.findall(r"\S+", draft)
        normalized_sentences = [
            re.sub(r"\W+", " ", sentence.casefold()).strip()
            for sentence in re.split(r"(?<=[.!?])\s+", draft)
            if sentence.strip()
        ]
        repeated_sentence = len(normalized_sentences) != len(
            set(normalized_sentences)
        )
        list_markers = re.findall(r"(?m)^\s*(?:[-*]|\d+[.)])\s+", draft)
        field_labels = re.findall(r"(?m)^\s*[A-Za-zÀ-ÿ][^\n:]{1,30}:\s*", draft)
        return {
            "not_form_like": len(list_markers) < 4 and len(field_labels) < 4,
            "max_one_question": draft.count("?") <= 1,
            "avoids_repetition": not repeated_sentence,
            "not_too_long": len(words) <= MAX_KINA_RESPONSE_WORDS,
            "direct_and_concise": len(words) <= MAX_KINA_RESPONSE_WORDS,
            "avoids_ai_style": not bool(AI_STYLE_PATTERN.search(draft)),
            "no_internal_output": not self._contains_forbidden_content(draft),
        }

    def _revision_instruction_for_check(self, check: str) -> str:
        instructions = {
            "natural_language": "Gunakan bahasa Indonesia percakapan yang wajar.",
            "not_form_like": "Ubah daftar atau format isian menjadi percakapan singkat.",
            "max_one_question": "Sisakan maksimal satu pertanyaan.",
            "validates_teacher": "Akui maksud atau keputusan guru secara singkat.",
            "gives_useful_suggestion": "Berikan satu saran konkret yang relevan.",
            "avoids_repetition": "Hapus pengulangan keputusan atau pertanyaan.",
            "pedagogically_safe": "Perbaiki saran agar realistis dan aman bagi siswa.",
            "not_too_long": f"Batasi respons maksimal {MAX_KINA_RESPONSE_WORDS} kata.",
            "direct_and_concise": "Hapus pengantar dan penjelasan yang tidak diperlukan.",
            "avoids_ai_style": "Hapus metafora dan frasa generik khas AI.",
            "clear_for_teacher": "Gunakan istilah sederhana yang mudah dipahami guru.",
            "no_internal_output": "Hapus JSON, istilah teknis, dan proses internal.",
            "handles_input_relevance": (
                "Tanggapi sesuai relevansi input dan arahkan kembali ke tahap aktif bila perlu."
            ),
        }
        return instructions.get(check, "")

    def _clean_internal_text(self, value: Any) -> str:
        return compact_text(str(value or ""), 700)

    def _kina_model(self) -> str:
        llm_settings = getattr(self.llm_client, "settings", None)
        return getattr(llm_settings, "kina_llm_model", DEFAULT_KINA_MODEL)

    def _solver_model(self) -> str:
        llm_settings = getattr(self.llm_client, "settings", None)
        return getattr(llm_settings, "kina_solver_model", None) or self._kina_model()

    def _evaluator_model(self) -> str:
        llm_settings = getattr(self.llm_client, "settings", None)
        return getattr(llm_settings, "kina_evaluator_model", None) or self._kina_model()

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
        self._apply_saved_stage_evidence(payload, evidence)

        previous_assistant = ""
        for chat in payload.chatHistory:
            if chat.role == "assistant":
                previous_assistant = chat.message
                continue
            if chat.role == "user":
                self._apply_user_decision(chat.message, previous_assistant, evidence)

        if evidence["final_product"]:
            evidence["focus_scope"] = True
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

        active_stage, active_label, completed_count = self._active_stage_from_evidence(
            evidence
        )
        is_complete = completed_count == len(DISCUSSION_STAGES)
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

    def _information_progress(
        self,
        analysis: dict[str, Any],
    ) -> KinaInformationProgress:
        evidence = analysis.get("evidence") or {}
        points = [
            KinaInformationPoint(
                key=key,
                label=label,
                completed=bool(evidence.get(key)),
            )
            for key, label in DISCUSSION_STAGES
        ]
        completed_labels = [point.label for point in points if point.completed]
        missing_labels = [point.label for point in points if not point.completed]
        total_count = len(points)
        completed_count = len(completed_labels)
        percent = (
            round((completed_count / total_count) * 100)
            if total_count
            else 0
        )
        return KinaInformationProgress(
            completedCount=completed_count,
            totalCount=total_count,
            percent=percent,
            activeStage=analysis.get("active_stage"),
            activeLabel=analysis.get("active_label"),
            completed=completed_labels,
            missing=missing_labels,
            points=points,
        )

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
            r"penilaian|refleksi)\b",
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
        ):
            return

        direct_matches = self._decision_stage_matches(message)
        if direct_matches:
            for key in direct_matches:
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
                evidence[matching_stages[-1]] = True
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

        if analysis["input_relevance"] == "irrelevant":
            follow_up = self._suggested_questions(analysis)
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
