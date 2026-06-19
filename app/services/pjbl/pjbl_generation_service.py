from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.schemas.common_schema import UsedReferenceSchema
from app.schemas.generate_rpp_schema import GenerateRppRequest, GenerateRppResponse
from app.services.llm_client import LLMClient
from app.services.prompt_builder_service import PromptBuilderService
from app.services.rag_service import RAGService
from app.utils.text_cleaner import compact_text

MAX_PJBL_SUBJECTS = 5

logger = logging.getLogger(__name__)


class PjblGenerationService:
    def __init__(
        self,
        rag_service: RAGService | None = None,
        llm_client: LLMClient | None = None,
        prompt_builder: PromptBuilderService | None = None,
    ) -> None:
        self.rag_service = rag_service or RAGService()
        self.llm_client = llm_client or LLMClient()
        self.prompt_builder = prompt_builder or PromptBuilderService()

    async def generate(self, payload: GenerateRppRequest) -> GenerateRppResponse:
        generation_model = self._generation_model()
        try:
            references = await self.rag_service.search_for_context(
                query=payload.project.title or payload.project.subject or "RPP PjBL",
                subject=payload.project.subject,
                phase=payload.project.phase,
                top_k=5,
            )
        except Exception as exc:  # pragma: no cover - defensive external dependency guard
            logger.warning("RAG lookup failed while generating RPM Kokurikuler: %s", exc)
            references = []

        source_data = self._build_source_data(payload, references)
        fallback_content = self._fallback_content(source_data)
        fallback = {
            "contentJson": fallback_content,
            "contentMarkdown": self._to_markdown(fallback_content),
        }

        messages = [
            {
                "role": "system",
                "content": self._build_system_prompt(),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "instruction": (
                            "Susun RPP PjBL Kokurikuler final berdasarkan sourceData. "
                            "Gunakan Stage 1 sebagai konteks dan batasan, Stage 2 "
                            "sebagai proyek terpilih, Stage 3 sebagai rancangan alur, "
                            "Stage 4 sebagai asesmen, Stage 5 sebagai review final, "
                            "dan summary Kina sebagai keputusan final diskusi. Return "
                            "hanya JSON valid dengan key contentJson dan contentMarkdown."
                        ),
                        "sourceData": source_data,
                        "requiredResponseShape": fallback,
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        try:
            generated = await self.llm_client.generate_json(
                messages,
                fallback,
                model=generation_model,
                temperature=0.2,
            )
        except Exception as exc:  # pragma: no cover - defensive external dependency guard
            logger.warning("LLM generation failed; returning RPM fallback: %s", exc)
            generated = fallback
        content_json = (
            generated.get("contentJson") if isinstance(generated, dict) else None
        )
        if not isinstance(content_json, dict):
            content_json = fallback_content
        content_json = self._normalize_content(content_json, fallback_content)
        content_json = self._postprocess_content(content_json, fallback_content)

        content_markdown = self._to_markdown(content_json)

        return GenerateRppResponse(
            status="success",
            model=generation_model,
            rppType=payload.project.rppType,
            usedReferences=[
                UsedReferenceSchema(
                    cpReferenceId=reference.cpReferenceId,
                    sourceTitle=reference.sourceTitle,
                    similarityScore=reference.similarityScore,
                )
                for reference in references
            ],
            contentJson=content_json,
            contentMarkdown=content_markdown,
        )

    def _generation_model(self) -> str:
        llm_settings = getattr(self.llm_client, "settings", None)
        return getattr(
            llm_settings,
            "rpp_generation_model",
            "deepseek/deepseek-v4-pro",
        )

    def _build_system_prompt(self) -> str:
        return """
Anda adalah AI Service Petunjukku untuk menyusun RPM/RPP PjBL Kokurikuler final.

Output wajib hanya JSON valid:
{
  "contentJson": {...},
  "contentMarkdown": "..."
}

Aturan:
- Gunakan hanya sourceData.
- Bentuk akhir harus mengikuti template "RPM KOKURIKULER", bukan format bebas.
- contentMarkdown wajib memakai urutan dan judul bagian berikut:
  # RPM KOKURIKULER
  A. Identitas Pembelajaran
  B. Profil dan Arah Pembelajaran
     1. Gambaran Proyek
     2. Profil Lulusan yang Dikembangkan
     3. Mata Pelajaran/Muatan Terkait
  C. Desain Pembelajaran
     1. Praktik Pedagogis
     2. Lingkungan Belajar
     3. Kemitraan Pembelajaran
     4. Pemanfaatan Digital
     5. Sumber Daya
  D. Rangkaian Kegiatan Pembelajaran per Pertemuan
     1. Asesmen Formatif
     2. Asesmen Sumatif - Penilaian Kinerja
  E. Tindak Lanjut Pembelajaran
  F. Refleksi Guru
- Identitas wajib memuat: Nama Sekolah, Nama Guru, Jenjang, Fase,
  Kelas/Semester, Bentuk kokurikuler, Alokasi Waktu Total, Produk akhir,
  Mata pelajaran/muatan terkait, Jumlah Pertemuan, dan Konteks Proyek.
- Bagian C wajib memuat praktik pedagogis, lingkungan fisik/sosial/aman/reflektif,
  kemitraan, pemanfaatan digital, dan sumber daya.
- Bagian D wajib memuat tabel ringkas per pertemuan/tahap serta detail:
  Langkah Guru, Kegiatan Murid, dan Hasil yang Dikumpulkan.
- Jumlah baris pertemuan pada Bagian D harus sama dengan keputusan diskusi Kina
  tentang jumlah pertemuan/tahap. Jika guru memilih 4 pertemuan, buat 4 tahap.
- Gambaran Proyek harus berupa narasi proyek, bukan daftar mata pelajaran,
  bukan topik saja, dan bukan salinan identitas.
- Asesmen formatif wajib berupa kolom observasi; asesmen sumatif wajib berupa
  rubrik kinerja dengan level Sangat Baik, Baik, Cukup, dan Perlu Bimbingan.
- Stage 1 adalah konteks sekolah, kelas, isu lokal, durasi, fasilitas, dan batasan.
- Stage 2 adalah proyek terpilih, tujuan, driving question, produk, aktivitas awal,
  kelayakan, dan risiko.
- Stage 3 adalah rancangan alur pelaksanaan proyek, pedagogi, teknologi, kemitraan,
  produk kinerja akhir, dan langkah penting.
- Stage 4 adalah rencana asesmen formatif, bukti proses, instrumen, dukungan,
  dan pertemuan.
- Stage 5 adalah review final dan kesiapan dokumen.
- kinaChatSummary adalah keputusan final guru dari diskusi Kina.
- Jangan mengarang fasilitas, mitra, produk, atau durasi yang tidak didukung data.
- Jika data kurang, isi dengan rumusan konservatif dari sourceData dan tandai secara
  operasional tanpa menyebut "data tidak tersedia".
- Buat RPM ringkas, operasional, siap dipakai guru, dan konsisten dengan template.
- Jangan membuat PDF/DOCX.
""".strip()

    def _build_source_data(
        self,
        payload: GenerateRppRequest,
        references: list[Any],
    ) -> dict[str, Any]:
        stages_by_number = {
            stage.stageNumber: stage.contentJson for stage in payload.stages
        }
        return {
            "project": payload.project.model_dump(),
            "teacherProfile": self._dump(payload.teacherProfile),
            "school": self._dump(payload.school),
            "teacherSubject": self._dump(payload.teacherSubject),
            "teacherClass": self._dump(payload.teacherClass),
            "stage1": stages_by_number.get(1, {}),
            "stage2": stages_by_number.get(2, {}),
            "stage3": stages_by_number.get(3, {}),
            "stage4": stages_by_number.get(4, {}),
            "stage5": stages_by_number.get(5, {}),
            "stage1Flat": self._flatten_stage_data(stages_by_number.get(1, {})),
            "stage2Flat": self._flatten_stage_data(stages_by_number.get(2, {})),
            "stage3Flat": self._flatten_stage_data(stages_by_number.get(3, {})),
            "stage4Flat": self._flatten_stage_data(stages_by_number.get(4, {})),
            "stage5Flat": self._flatten_stage_data(stages_by_number.get(5, {})),
            "kinaChatSummary": payload.kinaChatSummary or {},
            "options": payload.options,
            "ragReferences": [reference.model_dump() for reference in references],
        }

    def _fallback_content(self, source_data: dict[str, Any]) -> dict[str, Any]:
        project = source_data.get("project") or {}
        stage1 = source_data.get("stage1") or {}
        stage2 = source_data.get("stage2") or {}
        stage3 = source_data.get("stage3") or {}
        stage4 = source_data.get("stage4") or {}
        stage5 = source_data.get("stage5") or {}
        stage1_flat = self._as_dict(source_data.get("stage1Flat"))
        stage2_flat = self._as_dict(source_data.get("stage2Flat"))
        stage3_flat = self._as_dict(source_data.get("stage3Flat"))
        stage4_flat = self._as_dict(source_data.get("stage4Flat"))
        stage5_flat = self._as_dict(source_data.get("stage5Flat"))
        summary = source_data.get("kinaChatSummary") or {}
        school_context = self._as_dict(stage1.get("schoolContext")) or self._as_dict(
            source_data.get("school")
        )
        area_context = self._as_dict(stage1.get("areaContext")) or self._as_dict(
            stage1_flat.get("environmentScanner")
        )
        mission_spec = self._as_dict(stage1.get("missionSpec")) or stage1_flat
        learning_duration = self._as_dict(mission_spec.get("learningDuration"))
        class_context = self._as_dict(stage1.get("classContext")) or self._as_dict(
            source_data.get("teacherClass")
        )
        selected_project = self._selected_project(stage2)

        title = (
            selected_project.get("recommendedProjectTitle")
            or selected_project.get("title")
            or stage2_flat.get("projectTitle")
            or stage2_flat.get("ideaTitle")
            or stage2.get("selectedProjectTitle")
            or project.get("title")
            or "RPP PjBL Kokurikuler"
        )
        duration = (
            learning_duration.get("durationText")
            or stage1_flat.get("durationLabel")
            or stage1_flat.get("durasiPembelajaran")
            or stage1.get("projectDuration")
            or self._duration_text(stage1_flat, project)
            or "2 x 35 menit (Jam Pelajaran)"
        )
        related_subjects = self._related_subjects(
            mission_spec,
            stage1_flat,
            project,
            source_data,
        )
        decision_text = self._decision_text(summary, stage3_flat)
        meeting_count = self._meeting_count(
            summary=summary,
            stage3_flat=stage3_flat,
            stage4_flat=stage4_flat,
            stage1_flat=stage1_flat,
            learning_duration=learning_duration,
            project=project,
        )
        jp_per_meeting = self._jp_per_meeting(
            learning_duration=learning_duration,
            stage1_flat=stage1_flat,
            project=project,
        )
        time_allocation = f"{jp_per_meeting} JP"
        total_time_allocation = (
            f"{meeting_count * jp_per_meeting} JP "
            f"({meeting_count} pertemuan x {jp_per_meeting} JP)"
        )
        final_product = (
            summary.get("finalProjectForm")
            or summary.get("finalProduct")
            or stage3_flat.get("produkKinerjaAkhirNarasi")
            or self._join(
                stage3_flat.get("produkKinerjaAkhir")
                or stage3_flat.get("finalStudentProduct")
                or selected_project.get("studentProduct")
                or stage2.get("studentProduct")
            )
            or "produk proyek, laporan singkat, presentasi, dan refleksi murid"
        )
        activities = self._string_list(
            summary.get("activitiesAndSchedule")
            or summary.get("implementationDuration")
            or stage3_flat.get("langkahPenting")
            or stage3_flat.get("projectActivitiesOverview")
            or selected_project.get("projectActivitiesOverview")
            or selected_project.get("overview")
            or stage2.get("projectActivitiesOverview")
        )
        if not activities:
            activities = [
                "Pemantik dan penjelasan konteks proyek",
                "Observasi atau pengumpulan data sederhana",
                "Penyusunan produk atau aksi akhir",
                "Presentasi, umpan balik, dan refleksi",
            ]
        project_context = self._project_context_text(
            title=title,
            final_product=final_product,
            selected_project=selected_project,
            stage1=stage1,
            stage1_flat=stage1_flat,
            summary=summary,
            school_context=school_context,
            area_context=area_context,
            related_subjects=related_subjects,
        )

        content = {
            "title": title,
            "subtitle": selected_project.get("projectTheme")
            or selected_project.get("themeLabel")
            or "Kegiatan kokurikuler berbasis proyek",
            "identity": {
                "schoolName": school_context.get("name")
                or source_data.get("school", {}).get("name"),
                "teacherName": source_data.get("teacherProfile", {}).get("fullName"),
                "city": school_context.get("city")
                or source_data.get("school", {}).get("city"),
                "subject": project.get("subject"),
                "phase": project.get("phase"),
                "educationLevel": mission_spec.get("educationLevel")
                or stage1_flat.get("jenjangPendidikan")
                or stage1_flat.get("jenjang"),
                "educationPhase": mission_spec.get("educationPhase")
                or stage1_flat.get("fase"),
                "relatedSubjects": related_subjects,
                "gradeLevel": project.get("gradeLevel")
                or class_context.get("className"),
                "rppType": project.get("rppType"),
                "timeAllocation": time_allocation,
                "timeAllocationTotal": total_time_allocation,
                "meetingCount": str(meeting_count),
                "kokurikulerForm": "Pembelajaran kolaboratif lintas disiplin ilmu",
                "finalProduct": final_product,
                "topic": title,
                "projectContext": project_context,
            },
            "projectOverview": {
                "theme": selected_project.get("projectTheme")
                or selected_project.get("themeLabel")
                or stage2_flat.get("projectTheme")
                or stage2_flat.get("themeLabel")
                or stage2.get("projectTheme")
                or stage1.get("theme"),
                "localIssue": stage1.get("localIssue")
                or stage1_flat.get("localIssue")
                or stage1_flat.get("studentNotes")
                or stage1_flat.get("localContext"),
                "background": project_context,
                "drivingQuestion": selected_project.get("drivingQuestion")
                or stage2.get("drivingQuestion"),
                "focusAndScope": self._safe_project_text(
                    summary.get("focusAndScope") or selected_project.get("projectFocus"),
                    related_subjects,
                ),
                "narrative": project_context,
                "studentNeeds": stage1.get("studentNeeds")
                or stage1_flat.get("studentNotes"),
                "areaContext": area_context,
                "initialRiskMonitoring": self._string_list_from_risk(
                    stage1.get("riskMonitoring")
                ),
            },
            "expectedOutcomes": self._expected_outcomes(title, final_product),
            "safeBoundaries": summary.get("riskMitigation")
            or self._risk_text(selected_project),
            "graduateProfiles": self._graduate_profiles(final_product),
            "relatedSubjectDetails": self._related_subject_details(
                related_subjects,
                title,
            ),
            "learningObjectives": self._string_list(
                selected_project.get("projectObjectives")
                or stage2_flat.get("projectObjectives")
                or stage2_flat.get("mainConfirmations")
                or stage2.get("projectObjectives")
            ),
            "studentContext": {
                "className": class_context.get("className"),
                "studentCount": class_context.get("studentCount"),
                "characteristics": class_context.get("studentCharacteristics"),
                "classCondition": mission_spec.get("classCondition")
                or stage1_flat.get("kondisiKelas"),
                "learningChallenges": self._string_list(
                    class_context.get("learningChallenges")
                ),
                "dominantLearningStyle": class_context.get("dominantLearningStyle"),
            },
            "learningDesign": {
                "finalProduct": final_product,
                "pedagogicalApproach": summary.get("pedagogicalPreference")
                or summary.get("learningStyle")
                or stage3_flat.get("praktikPedagogis")
                or stage3_flat.get("preferensiPedagogis"),
                "activityFlowReason": stage3_flat.get("alasanPraktikPedagogis"),
                "pedagogicalPracticeDescription": (
                    summary.get("learningStyle")
                    or summary.get("pedagogicalPreference")
                    or stage3_flat.get("alasanPraktikPedagogis")
                    or "Pembelajaran menggunakan mini-PjBL, diskusi kolaboratif, dan refleksi terarah agar murid mengalami proses proyek secara bertahap."
                ),
                "pedagogicalForms": self._pedagogical_forms(title),
                "learningEnvironment": self._learning_environment(
                    school_context,
                    stage1_flat,
                ),
                "partnerships": self._partnerships(stage3_flat),
                "digitalResources": self._digital_resources(
                    stage3_flat,
                    summary.get("digitalUse"),
                ),
                "resources": self._resources(stage3_flat, school_context),
                "activitiesAndSchedule": summary.get("activitiesAndSchedule")
                or summary.get("implementationDuration")
                or stage3_flat.get("ringkasan")
                or stage3_flat.get("summary")
                or self._join(activities),
                "rolesAndSupport": summary.get("rolesAndSupport")
                or "Siswa bekerja dalam kelompok kecil dengan pembagian peran sederhana; guru memantau proses dan memberi umpan balik singkat.",
                "facilitiesTechnologyPartnership": summary.get(
                    "facilitiesTechnologyPartnership"
                )
                or self._join(
                    [summary.get("facilitiesTechnologyUse"), summary.get("partnership")]
                )
                or self._join(
                    [
                        stage3_flat.get("fasilitasKelas"),
                        stage3_flat.get("pemanfaatanDigital"),
                        stage3_flat.get("fungsiTeknologiDigital"),
                        stage3_flat.get("kemitraanDetail"),
                    ]
                )
                or self._join(
                    school_context.get("facilities")
                    or school_context.get("availableFacilities")
                ),
                "riskMitigation": summary.get("riskMitigation")
                or self._risk_text(selected_project),
                "assessmentReflection": summary.get("assessmentReflection")
                or summary.get("projectAssessment")
                or self._assessment_reflection_text(stage4_flat)
                or "Guru menilai proses, produk akhir, presentasi, kontribusi anggota, dan refleksi singkat siswa.",
            },
            "meetingPlan": self._meeting_plan(
                activities,
                duration,
                meeting_count=meeting_count,
                title=title,
                final_product=final_product,
                decision_text=decision_text,
                stage4=stage4,
                stage4_flat=stage4_flat,
            ),
            "assessment": self._assessment_from_stage4(stage4, stage4_flat),
            "followUp": summary.get("followUp")
            or stage5_flat.get("followUp")
            or "Guru menindaklanjuti hasil proyek dengan memajang atau menggunakan produk akhir, memberi umpan balik singkat, dan mengajak murid menentukan perbaikan kecil untuk kegiatan berikutnya.",
            "teacherReflection": summary.get("teacherReflection")
            or stage5_flat.get("teacherReflection")
            or "Guru merefleksikan keterlibatan murid, kecukupan waktu, efektivitas pembagian peran, dukungan fasilitas, dan kualitas produk akhir sebagai dasar penyempurnaan proyek.",
            "teacherNotes": summary.get("teacherNotes")
            or stage5_flat.get("teacherNotes")
            or stage1.get("teacherExpectation"),
            "completionStatus": summary.get("projectCompletionStatus")
            or self._completion_status(stage5, stage5_flat),
        }
        if not content["learningObjectives"]:
            content["learningObjectives"] = [
                "Peserta didik mampu mengidentifikasi masalah nyata sesuai tema proyek.",
                "Peserta didik mampu mengumpulkan dan menyajikan data sederhana.",
                "Peserta didik mampu mempresentasikan hasil proyek secara kolaboratif.",
            ]
        return content

    def _postprocess_content(
        self,
        content: dict[str, Any],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = dict(content)
        fallback_identity = self._as_dict(fallback.get("identity"))
        identity = self._deep_merge(fallback_identity, self._as_dict(content.get("identity")))
        for key in (
            "meetingCount",
            "timeAllocation",
            "timeAllocationTotal",
            "finalProduct",
            "topic",
            "projectContext",
        ):
            if fallback_identity.get(key):
                identity[key] = fallback_identity[key]
        normalized["identity"] = identity

        fallback_overview = self._as_dict(fallback.get("projectOverview"))
        overview = self._deep_merge(
            fallback_overview,
            self._as_dict(content.get("projectOverview")),
        )
        related_subjects = self._string_list(identity.get("relatedSubjects"))
        narrative = self._safe_project_text(
            overview.get("narrative")
            or overview.get("background")
            or overview.get("focusAndScope"),
            related_subjects,
        )
        fallback_narrative = fallback_overview.get("narrative") or fallback_overview.get(
            "background"
        )
        if not narrative or self._is_subject_only_text(narrative, related_subjects):
            narrative = fallback_narrative
        if narrative:
            overview["narrative"] = narrative
            overview["background"] = narrative
        if self._is_subject_only_text(overview.get("focusAndScope"), related_subjects):
            overview["focusAndScope"] = fallback_overview.get("focusAndScope") or narrative
        normalized["projectOverview"] = overview

        fallback_plan = fallback.get("meetingPlan")
        meeting_count = self._int_value(identity.get("meetingCount")) or len(
            fallback_plan if isinstance(fallback_plan, list) else []
        )
        meeting_plan = content.get("meetingPlan")
        if not isinstance(meeting_plan, list) or len(meeting_plan) != meeting_count:
            normalized["meetingPlan"] = fallback_plan
        return normalized

    def _decision_text(
        self,
        summary: dict[str, Any],
        stage3_flat: dict[str, Any],
    ) -> str:
        parts: list[str] = []
        raw_history = summary.get("rawChatHistory")
        if isinstance(raw_history, list):
            for chat in raw_history:
                if isinstance(chat, dict):
                    message = chat.get("message") or chat.get("content")
                    if message:
                        parts.append(str(message))
                elif chat:
                    parts.append(str(chat))
        for value in (
            summary.get("discussionSummary"),
            summary.get("teacherNotes"),
            summary.get("implementationDuration"),
            summary.get("activitiesAndSchedule"),
            stage3_flat.get("implementationDuration"),
            stage3_flat.get("activitiesAndSchedule"),
            stage3_flat.get("ringkasan"),
            stage3_flat.get("summary"),
        ):
            if value:
                parts.append(self._join(value))
        return " ".join(part for part in parts if part)

    def _meeting_count(
        self,
        *,
        summary: dict[str, Any],
        stage3_flat: dict[str, Any],
        stage4_flat: dict[str, Any],
        stage1_flat: dict[str, Any],
        learning_duration: dict[str, Any],
        project: dict[str, Any],
    ) -> int:
        explicit_text = self._decision_text(summary, stage3_flat)
        from_text = self._meeting_count_from_text(explicit_text)
        if from_text:
            return from_text

        stage4_meetings = stage4_flat.get("pertemuan") or stage4_flat.get("meetings")
        if isinstance(stage4_meetings, list) and stage4_meetings:
            return self._clamp_meeting_count(len(stage4_meetings))

        for value in (
            stage3_flat.get("meetingCount"),
            stage3_flat.get("jumlahPertemuan"),
            learning_duration.get("meetingCount"),
            stage1_flat.get("jumlahPertemuan"),
            stage1_flat.get("meetingCount"),
            project.get("meetingCount"),
        ):
            number = self._int_value(value)
            if number:
                return self._clamp_meeting_count(number)
        return 4

    def _meeting_count_from_text(self, text: str) -> int | None:
        if not text:
            return None
        words = {
            "satu": 1,
            "dua": 2,
            "tiga": 3,
            "empat": 4,
            "lima": 5,
            "enam": 6,
            "tujuh": 7,
            "delapan": 8,
            "sembilan": 9,
            "sepuluh": 10,
        }
        pattern = re.compile(
            r"\b(\d+|satu|dua|tiga|empat|lima|enam|tujuh|delapan|sembilan|sepuluh)"
            r"\s*(?:x\s*)?(?:kali\s*)?(?:pertemuan|tahap)\b",
            re.IGNORECASE,
        )
        matches = list(pattern.finditer(text))
        if not matches:
            return None
        raw = matches[-1].group(1).casefold()
        number = int(raw) if raw.isdigit() else words.get(raw)
        return self._clamp_meeting_count(number) if number else None

    def _clamp_meeting_count(self, value: int) -> int:
        return max(1, min(int(value), 12))

    def _int_value(self, value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value if value > 0 else None
        if isinstance(value, float) and value > 0:
            return int(value)
        if isinstance(value, str):
            match = re.search(r"\d+", value)
            if match:
                return int(match.group(0))
        return None

    def _jp_per_meeting(
        self,
        *,
        learning_duration: dict[str, Any],
        stage1_flat: dict[str, Any],
        project: dict[str, Any],
    ) -> int:
        for value in (
            learning_duration.get("jpPerMeeting"),
            stage1_flat.get("jpPerMeeting"),
            stage1_flat.get("jpPerPertemuan"),
            project.get("totalJp"),
            stage1_flat.get("alokasiJpPerPertemuan"),
        ):
            number = self._int_value(value)
            if number:
                return max(1, min(number, 12))
        return 2

    def _project_context_text(
        self,
        *,
        title: str,
        final_product: str,
        selected_project: dict[str, Any],
        stage1: dict[str, Any],
        stage1_flat: dict[str, Any],
        summary: dict[str, Any],
        school_context: dict[str, Any],
        area_context: dict[str, Any],
        related_subjects: list[str],
    ) -> str:
        candidate = self._safe_project_text(
            selected_project.get("projectBackground")
            or selected_project.get("description")
            or summary.get("discussionSummary")
            or stage1.get("teacherExpectation"),
            related_subjects,
        )
        if candidate and len(candidate) >= 80:
            return candidate

        local_issue = self._join(
            stage1.get("localIssue")
            or stage1_flat.get("localIssue")
            or stage1_flat.get("studentNotes")
            or stage1_flat.get("localContext")
            or school_context.get("localContext")
        )
        area_summary = self._join(area_context.get("summary"))
        subject_text = ", ".join(related_subjects) if related_subjects else "muatan terkait"
        context_tail = local_issue or area_summary or "konteks nyata di sekitar sekolah"
        return (
            f"Kegiatan ini mengajak murid menjalankan proyek {title} secara bertahap "
            f"dengan menghubungkan {subject_text} dan {context_tail}. Murid mengamati "
            f"situasi nyata, mendiskusikan temuan, menyusun {final_product}, lalu "
            "mempresentasikan hasil dan refleksi agar pengalaman belajar menjadi "
            "kontekstual, aman, kolaboratif, dan dapat ditindaklanjuti guru."
        )

    def _safe_project_text(self, value: Any, related_subjects: list[str]) -> str:
        text = self._join(value)
        if not text or self._is_subject_only_text(text, related_subjects):
            return ""
        return text

    def _is_subject_only_text(self, value: Any, related_subjects: list[str]) -> bool:
        text = self._join(value)
        if not text:
            return False
        compact_text_value = re.sub(r"[^a-z0-9]+", "", text.casefold())
        compact_subjects = re.sub(
            r"[^a-z0-9]+",
            "",
            ", ".join(related_subjects).casefold(),
        )
        if compact_text_value and compact_text_value == compact_subjects:
            return True
        normalized_parts = {
            part.strip().casefold()
            for part in re.split(r"[,;/]|\bdan\b", text)
            if part.strip()
        }
        normalized_subjects = {subject.casefold() for subject in related_subjects}
        if normalized_parts and normalized_parts.issubset(normalized_subjects):
            return True
        lowered = text.casefold()
        has_project_signal = any(
            signal in lowered
            for signal in (
                "murid",
                "siswa",
                "proyek",
                "kegiatan",
                "mengamati",
                "menyusun",
                "membuat",
                "mempresentasikan",
                "merefleksikan",
            )
        )
        return len(text) < 45 and not has_project_signal

    def _flatten_stage_data(self, stage: Any) -> dict[str, Any]:
        if not isinstance(stage, dict):
            return {}
        merged: dict[str, Any] = {}
        for key in ("inputs", "generated", "spec", "summary"):
            value = stage.get(key)
            if isinstance(value, dict):
                merged.update(value)

        selected = stage.get("selectedProjectRecommendation")
        if isinstance(selected, dict):
            merged.update(selected)

        wizard = stage.get("wizard")
        if isinstance(wizard, dict):
            for snapshot_key in ("konteks", "fokus", "alur", "penilaian", "output"):
                snapshot = wizard.get(snapshot_key)
                if not isinstance(snapshot, dict):
                    continue
                for nested_key in (
                    "spec",
                    "mission",
                    "fokus",
                    "alur",
                    "penilaian",
                ):
                    nested = snapshot.get(nested_key)
                    if isinstance(nested, dict):
                        merged.update(nested)
                environment_scanner = snapshot.get("environmentScanner")
                if isinstance(environment_scanner, dict):
                    merged.setdefault("environmentScanner", environment_scanner)
        return merged

    def _duration_text(
        self,
        stage1_flat: dict[str, Any],
        project: dict[str, Any],
    ) -> str:
        total_jp = stage1_flat.get("alokasiJpTotal") or project.get("totalJp")
        minutes = stage1_flat.get("menitPerJp") or 35
        if total_jp:
            return f"{total_jp} JP x {minutes} menit"
        return ""

    def _related_subjects(
        self,
        mission_spec: dict[str, Any],
        stage1_flat: dict[str, Any],
        project: dict[str, Any],
        source_data: dict[str, Any],
    ) -> list[str]:
        subjects = self._string_list(
            mission_spec.get("relatedSubjects")
            or stage1_flat.get("mataPelajaranUtama")
            or stage1_flat.get("mainSubjects")
            or project.get("subject")
            or source_data.get("teacherSubject", {}).get("subjectName")
        )
        return self._normalize_related_subjects(subjects)

    def _normalize_related_subjects(self, subjects: list[str]) -> list[str]:
        normalized: list[str] = []
        seen: set[str] = set()

        def add(subject: Any) -> None:
            text = self._join(subject)
            if not text:
                return
            parts = [
                part.strip()
                for part in re.split(r"[,;/]|\s+\bdan\b\s+", text)
                if part.strip()
            ]
            for part in parts or [text]:
                key = part.casefold()
                if key in seen:
                    continue
                seen.add(key)
                normalized.append(part)

        for subject in subjects:
            add(subject)

        return normalized[:MAX_PJBL_SUBJECTS]

    def _expected_outcomes(self, title: str, final_product: str) -> list[str]:
        return [
            f"Murid menjelaskan tujuan proyek {title} dan alasan pilihan produk atau aksi akhir.",
            "Murid menyusun rencana sederhana yang memuat alat, bahan, jadwal, peran, dan kebutuhan pendukung.",
            "Murid bekerja sama dalam kelompok sesuai peran masing-masing dengan tanggung jawab.",
            f"Murid menghasilkan {final_product} sebagai bukti belajar proyek.",
            "Murid menyampaikan hasil kegiatan melalui presentasi singkat dan refleksi.",
        ]

    def _graduate_profiles(self, final_product: str) -> list[dict[str, str]]:
        return [
            {
                "dimension": "Kreativitas",
                "description": f"Murid mengembangkan ide, tampilan, dan cara menyajikan {final_product}.",
            },
            {
                "dimension": "Kolaborasi",
                "description": "Murid membagi peran, saling membantu, dan menyelesaikan tugas kelompok secara tertib.",
            },
            {
                "dimension": "Kemandirian",
                "description": "Murid bertanggung jawab pada tugasnya dan menyiapkan kebutuhan proyek sesuai kesepakatan.",
            },
            {
                "dimension": "Komunikasi",
                "description": "Murid menjelaskan proses dan hasil proyek secara runtut kepada teman atau warga sekolah.",
            },
            {
                "dimension": "Penalaran Kritis",
                "description": "Murid mengambil keputusan berdasarkan data sederhana, umpan balik, dan kondisi nyata.",
            },
        ]

    def _related_subject_details(
        self,
        related_subjects: list[str],
        title: str,
    ) -> list[dict[str, str]]:
        defaults = {
            "prakarya": "Murid merancang produk, alat, bahan, atau karya sederhana yang mendukung proyek.",
            "ips": "Murid mengaitkan proyek dengan kegiatan sosial, ekonomi, atau lingkungan sekitar.",
            "matematika": "Murid membaca, menghitung, atau membandingkan data sederhana yang muncul dari proyek.",
            "bahasa indonesia": "Murid menyusun laporan singkat, kalimat promosi, dan presentasi hasil proyek.",
            "seni budaya": "Murid membuat desain visual, label, poster, atau tampilan produk proyek.",
            "informatika": "Murid menggunakan alat digital sederhana untuk dokumentasi, desain, atau presentasi.",
        }
        details: list[dict[str, str]] = []
        for subject in related_subjects:
            lowered = subject.casefold()
            description = next(
                (text for key, text in defaults.items() if key in lowered),
                f"Murid mengaitkan muatan {subject} dengan proses dan hasil proyek {title}.",
            )
            details.append({"subject": subject, "description": description})
        return details

    def _pedagogical_forms(self, title: str) -> list[str]:
        return [
            f"Pembelajaran Berbasis Proyek - Murid bekerja bertahap dari konteks nyata menuju produk/aksi {title}.",
            "Belajar dari Masalah Nyata - Guru menggunakan pertanyaan pemantik yang dekat dengan kehidupan murid.",
            "Diskusi Kelompok - Guru memastikan setiap anggota memiliki peran yang jelas.",
            "Refleksi Terarah - Guru menutup tiap tahap dengan pertanyaan singkat tentang proses dan pembelajaran.",
        ]

    def _learning_environment(
        self,
        school_context: dict[str, Any],
        stage1_flat: dict[str, Any],
    ) -> dict[str, str]:
        facilities = self._join(
            school_context.get("availableFacilities")
            or school_context.get("facilities")
            or stage1_flat.get("fasilitas")
        )
        return {
            "physical": facilities
            or "Kelas untuk diskusi, area sekolah untuk pelaksanaan proyek, meja kerja, alat tulis, dan perlengkapan sederhana.",
            "social": "Kelompok bekerja dengan pembagian peran; guru menjaga suasana aman, tertib, saling menghargai, dan inklusif.",
            "safe": "Kegiatan tidak memaksa biaya mahal, memakai bahan aman, serta mengikuti aturan sekolah.",
            "reflective": "Guru memberi waktu murid menulis pengalaman, menyampaikan tantangan, dan merumuskan perbaikan.",
        }

    def _partnerships(self, stage3_flat: dict[str, Any]) -> list[dict[str, str]]:
        text = self._join(stage3_flat.get("kemitraanDetail"))
        if text:
            return [{"partner": "Mitra pembelajaran", "role": text}]
        return [
            {
                "partner": "Guru pendamping/wali kelas",
                "role": "Membantu pengawasan, pengaturan area, dan pemberian umpan balik.",
            },
            {
                "partner": "Warga sekolah",
                "role": "Menjadi audiens, pemberi masukan, atau pengguna hasil proyek.",
            },
        ]

    def _digital_resources(
        self,
        stage3_flat: dict[str, Any],
        summary_digital_use: Any = None,
    ) -> list[dict[str, str]]:
        digital = self._join(
            summary_digital_use
            or stage3_flat.get("pemanfaatanDigital")
            or stage3_flat.get("fungsiTeknologiDigital")
            or stage3_flat.get("platformDigital")
        )
        if digital:
            return [{"source": "Media/alat digital", "use": digital}]
        return [
            {
                "source": "Video/gambar pemantik",
                "use": "Membantu murid memahami konteks proyek sebelum bekerja dalam kelompok.",
            },
            {
                "source": "Canva/slide/dokumen digital",
                "use": "Mendukung desain sederhana, dokumentasi, atau presentasi hasil proyek.",
            },
        ]

    def _resources(
        self,
        stage3_flat: dict[str, Any],
        school_context: dict[str, Any],
    ) -> list[dict[str, str]]:
        facilities = self._string_list(
            stage3_flat.get("fasilitasKelas")
            or school_context.get("availableFacilities")
            or school_context.get("facilities")
        )
        resources = [
            {
                "resource": item,
                "function": "Dimanfaatkan untuk mendukung pelaksanaan proyek, kerja kelompok, dokumentasi, atau presentasi.",
            }
            for item in facilities[:4]
        ]
        if resources:
            return resources
        return [
            {
                "resource": "Tempat dan perlengkapan kegiatan",
                "function": "Menjadi area pelaksanaan proyek, diskusi kelompok, dan presentasi singkat.",
            },
            {
                "resource": "Alat tulis murid",
                "function": "Digunakan untuk mencatat data, menyusun rencana, dan menulis refleksi pembelajaran.",
            },
        ]

    def _assessment_reflection_text(self, stage4_flat: dict[str, Any]) -> str:
        meetings = stage4_flat.get("pertemuan")
        if not isinstance(meetings, list) or not meetings:
            return ""
        labels: list[str] = []
        for meeting in meetings:
            if not isinstance(meeting, dict):
                continue
            technique = meeting.get("asesmenFormatif")
            focus = meeting.get("fokusPertemuan")
            if technique or focus:
                labels.append(
                    " - ".join(str(part) for part in (focus, technique) if part)
                )
        return self._join(labels)

    def _assessment_from_stage4(
        self,
        stage4: dict[str, Any],
        stage4_flat: dict[str, Any],
    ) -> dict[str, Any]:
        assessment: dict[str, Any] = {
            "formativeDescription": (
                "Guru menggunakan observasi selama kegiatan. Catatan tidak perlu panjang; cukup tulis perilaku penting, bantuan yang diberikan, dan perubahan yang terlihat pada murid."
            ),
            "formativeColumns": [
                "Nama Murid",
                "Kolaborasi",
                "Kemandirian",
                "Komunikasi",
                "Catatan Guru",
            ],
            "process": [
                "Ketepatan observasi atau pengumpulan data",
                "Kerja sama dan pembagian peran",
                "Keterlibatan siswa selama kegiatan",
            ],
            "product": [
                "Kesesuaian produk dengan masalah yang dipilih",
                "Kejelasan data atau pesan yang disajikan",
                "Kerapian dan keterbacaan produk akhir",
            ],
            "presentation": [
                "Kejelasan penyampaian hasil",
                "Kemampuan menjawab pertanyaan sederhana",
            ],
            "reflection": "Siswa menuliskan satu hal yang dipelajari dan satu aksi kecil yang dapat dilakukan setelah proyek.",
            "summativeDescription": (
                "Asesmen sumatif digunakan setelah proyek selesai. Bukti yang dinilai dapat berupa produk/aksi akhir, catatan proses, presentasi kelompok, dan refleksi murid."
            ),
            "rubric": self._rubric(),
        }
        meetings = stage4_flat.get("pertemuan")
        if isinstance(meetings, list) and meetings:
            assessment["formativeMeetings"] = meetings
        available = stage4.get("availableTechniques")
        if isinstance(available, list) and available:
            assessment["availableTechniques"] = available
        return assessment

    def _completion_status(
        self,
        stage5: dict[str, Any],
        stage5_flat: dict[str, Any],
    ) -> str:
        generated = self._as_dict(stage5.get("generated"))
        final_doc = self._as_dict(generated.get("dokumenFinal"))
        status = self._join(stage5_flat.get("status") or final_doc.get("status"))
        return status or "draft"

    def _selected_project(self, stage2: dict[str, Any]) -> dict[str, Any]:
        selected = stage2.get("selectedProjectRecommendation")
        if isinstance(selected, dict):
            return selected
        inputs = self._as_dict(stage2.get("inputs"))
        generated = self._as_dict(stage2.get("generated"))
        selected_option = self._as_dict(inputs.get("selectedProjectOption"))
        selected_theme = self._as_dict(inputs.get("selectedTheme"))
        if selected_option or generated:
            return {
                "recommendedProjectTitle": selected_option.get("title")
                or generated.get("projectTitle"),
                "title": selected_option.get("title") or generated.get("projectTitle"),
                "projectTheme": selected_theme.get("label")
                or generated.get("projectTheme"),
                "themeLabel": selected_theme.get("label")
                or generated.get("projectTheme"),
                "projectBackground": selected_option.get("description")
                or generated.get("projectDescription"),
                "description": selected_option.get("description")
                or generated.get("projectDescription"),
                "projectFocus": selected_option.get("lens")
                or generated.get("projectLens"),
                "overview": selected_option.get("overview"),
                "projectActivitiesOverview": (
                    [selected_option.get("overview")]
                    if selected_option.get("overview")
                    else []
                ),
            }
        recommendations = stage2.get("projectRecommendations")
        if isinstance(recommendations, list) and recommendations:
            first = recommendations[0]
            if isinstance(first, dict):
                return first
        return stage2

    def _meeting_plan(
        self,
        activities: list[str],
        duration: str,
        *,
        meeting_count: int,
        title: str,
        final_product: str,
        decision_text: str = "",
        stage4: dict[str, Any] | None = None,
        stage4_flat: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        meetings = (stage4_flat or {}).get("pertemuan") or (stage4_flat or {}).get(
            "meetings"
        )
        if isinstance(meetings, list) and meetings:
            plan: list[dict[str, Any]] = []
            for index, meeting in enumerate(meetings):
                if not isinstance(meeting, dict):
                    continue
                plan.append(
                    {
                        "meeting": meeting.get("nomor") or index + 1,
                        "stageTitle": meeting.get("fokusPertemuan")
                        or f"Tahap {index + 1}",
                        "duration": meeting.get("duration") or "2 JP",
                        "opening": meeting.get("aktivitasMemahami")
                        or "Guru membuka dengan pertanyaan pemantik dan mengaitkan proyek dengan isu lokal.",
                        "mainActivities": [
                            item
                            for item in (
                                meeting.get("konteksMiniPjbl"),
                                meeting.get("produkSementara"),
                                meeting.get("bentukKerja"),
                            )
                            if item
                        ]
                        or activities,
                        "closing": meeting.get("metodeRefleksi")
                        or "Siswa mempresentasikan temuan atau produk awal, lalu menulis refleksi singkat.",
                        "formativeAssessment": meeting.get("asesmenFormatif")
                        or meeting.get("umpanBalik")
                        or "Observasi proses kelompok, cek produk, dan tanya jawab singkat.",
                        "teacherSteps": meeting.get("aktivitasMemahami")
                        or "Guru memberi pemantik, menjelaskan target tahap, memantau proses kelompok, dan memberi umpan balik singkat.",
                        "studentActivities": self._join(
                            [
                                meeting.get("konteksMiniPjbl"),
                                meeting.get("produkSementara"),
                                meeting.get("bentukKerja"),
                            ]
                        )
                        or "Murid bekerja dalam kelompok, mengumpulkan bukti, menyusun hasil sementara, dan berbagi temuan.",
                        "collectedEvidence": meeting.get("produkSementara")
                        or "Catatan proses, hasil kerja kelompok, dokumentasi, dan refleksi singkat.",
                    }
                )
            if plan and len(plan) == meeting_count:
                return plan

        if meeting_count <= 1:
            return [
                {
                    "meeting": 1,
                    "stageTitle": "Membuka Konteks dan Menyelesaikan Produk Mini",
                    "duration": "2 JP",
                    "opening": "Guru membuka dengan pertanyaan pemantik dan mengaitkan proyek dengan isu lokal.",
                    "mainActivities": activities,
                    "closing": "Siswa mempresentasikan temuan atau produk awal, lalu menulis refleksi singkat.",
                    "formativeAssessment": "Observasi proses kelompok, cek produk, dan tanya jawab singkat.",
                    "teacherSteps": "Guru membuka konteks proyek, menjelaskan batas aman kegiatan, memberi contoh kerja, memantau kelompok, dan menutup dengan refleksi.",
                    "studentActivities": f"Murid mendiskusikan konteks {title}, mengumpulkan informasi sederhana, menyusun {final_product}, lalu berbagi hasil secara singkat.",
                    "collectedEvidence": f"Catatan proses, dokumentasi sederhana, {final_product}, dan refleksi singkat.",
                }
            ]

        base_stages = [
            {
                "meeting": 1,
                "stageTitle": "Membuka Konteks Proyek",
                "duration": "2 JP",
                "opening": "Guru membuka dengan pertanyaan pemantik dan mengaitkan proyek dengan isu lokal.",
                "mainActivities": [
                    "Mengaitkan tema proyek dengan pengalaman murid dan lingkungan sekitar.",
                    "Menyepakati tujuan, batas aman, peran awal, dan bukti belajar yang akan dikumpulkan.",
                ],
                "closing": "Siswa mempresentasikan temuan atau produk awal, lalu menulis refleksi singkat.",
                "formativeAssessment": "Observasi proses kelompok, cek produk, dan tanya jawab singkat.",
                "teacherSteps": "Guru membuka konteks proyek, menunjukkan contoh yang relevan, menjelaskan batas area/aturan, dan memandu murid menyusun peta ide awal.",
                "studentActivities": f"Murid berbagi pengalaman tentang {title}, mengamati contoh, berdiskusi dalam kelompok, dan menulis pertanyaan atau dugaan awal.",
                "collectedEvidence": "Peta ide awal, daftar pertanyaan proyek, pembagian kelompok/peran awal, dan catatan refleksi singkat.",
            },
            {
                "meeting": 2,
                "stageTitle": "Observasi dan Pengumpulan Data",
                "duration": "2 JP",
                "opening": "Guru mengulas pertanyaan proyek dan mencontohkan cara mencatat data secara sederhana.",
                "mainActivities": [
                    "Observasi, wawancara singkat, studi contoh, atau pengumpulan data sederhana sesuai konteks proyek.",
                    "Mencatat temuan penting dan memilah informasi yang relevan untuk produk akhir.",
                ],
                "closing": "Kelompok menyampaikan temuan awal dan menerima umpan balik singkat.",
                "formativeAssessment": "Observasi ketepatan pengumpulan data, kerja sama, dan kelengkapan catatan.",
                "teacherSteps": "Guru menyiapkan format catatan, memastikan izin dan batas area jelas, mendampingi kelompok, serta membantu murid membedakan fakta dan pendapat.",
                "studentActivities": "Murid mengumpulkan informasi sesuai peran, mencatat bukti, mendokumentasikan proses seperlunya, dan menyepakati temuan utama kelompok.",
                "collectedEvidence": "Lembar observasi/catatan data, dokumentasi proses, dan daftar temuan utama.",
            },
            {
                "meeting": 3,
                "stageTitle": "Analisis Temuan dan Perencanaan Produk",
                "duration": "2 JP",
                "opening": "Guru membantu murid meninjau data yang sudah terkumpul dan menghubungkannya dengan produk akhir.",
                "mainActivities": [
                    "Memilih temuan paling penting untuk dijadikan isi produk atau aksi.",
                    "Menyusun rancangan produk, pembagian tugas, kebutuhan alat/bahan, dan kriteria keberhasilan.",
                ],
                "closing": "Kelompok melakukan cek cepat terhadap rancangan dan kebutuhan dukungan.",
                "formativeAssessment": "Cek rancangan produk, kejelasan peran, dan alasan keputusan kelompok.",
                "teacherSteps": "Guru memberi contoh struktur produk, menantang alasan pilihan kelompok, dan memastikan rancangan realistis dengan waktu serta fasilitas.",
                "studentActivities": f"Murid menganalisis temuan, memilih pesan utama, membagi tugas, dan membuat rancangan {final_product}.",
                "collectedEvidence": "Rancangan produk/aksi, daftar tugas anggota, kebutuhan sumber daya, dan catatan umpan balik guru.",
            },
            {
                "meeting": 4,
                "stageTitle": "Penyusunan Produk dan Presentasi Reflektif",
                "duration": "2 JP",
                "opening": "Guru mengingatkan kriteria produk, cara presentasi, dan format refleksi.",
                "mainActivities": [
                    "Menyelesaikan produk atau aksi akhir.",
                    "Mempresentasikan hasil, menerima umpan balik, dan menulis refleksi singkat.",
                ],
                "closing": "Guru bersama murid merumuskan pembelajaran penting dan tindak lanjut sederhana.",
                "formativeAssessment": "Penilaian kinerja melalui produk, presentasi, kontribusi anggota, dan refleksi.",
                "teacherSteps": "Guru memantau penyelesaian produk, memfasilitasi presentasi, memberi umpan balik, dan memandu refleksi akhir.",
                "studentActivities": f"Murid menyelesaikan {final_product}, mempresentasikan proses serta hasil, menanggapi pertanyaan, dan menulis refleksi singkat.",
                "collectedEvidence": f"{final_product}, dokumentasi/presentasi, catatan umpan balik, dan refleksi individu atau kelompok.",
            },
            {
                "meeting": 5,
                "stageTitle": "Penyempurnaan Produk",
                "duration": "2 JP",
                "opening": "Guru mengajak murid meninjau umpan balik dan menentukan perbaikan prioritas.",
                "mainActivities": [
                    "Menyempurnakan produk berdasarkan umpan balik.",
                    "Menyiapkan versi final dan bukti proses yang lebih rapi.",
                ],
                "closing": "Kelompok melakukan cek kesiapan presentasi atau pamer karya.",
                "formativeAssessment": "Cek revisi produk, ketepatan tindak lanjut umpan balik, dan kerapian bukti.",
                "teacherSteps": "Guru memberi klinik singkat per kelompok, membantu kelompok mengatur prioritas, dan memastikan semua anggota berkontribusi.",
                "studentActivities": "Murid memperbaiki produk, menata bukti belajar, dan melatih penjelasan singkat.",
                "collectedEvidence": "Produk hasil revisi, daftar perbaikan, dan bukti proses yang telah dirapikan.",
            },
            {
                "meeting": 6,
                "stageTitle": "Pamer Karya dan Tindak Lanjut",
                "duration": "2 JP",
                "opening": "Guru menjelaskan alur pamer karya, peran audiens, dan cara memberi apresiasi.",
                "mainActivities": [
                    "Menampilkan hasil proyek kepada teman, guru, atau warga sekolah.",
                    "Mengumpulkan respons audiens dan menyepakati tindak lanjut.",
                ],
                "closing": "Guru menutup dengan refleksi kelas dan apresiasi atas proses belajar.",
                "formativeAssessment": "Observasi komunikasi, tanggung jawab, dan kemampuan menerima umpan balik.",
                "teacherSteps": "Guru mengatur alur pamer karya, mengamati presentasi, mencatat bukti kinerja, dan memandu diskusi tindak lanjut.",
                "studentActivities": "Murid menjelaskan produk, menerima pertanyaan/masukan, dan menyusun rencana tindak lanjut sederhana.",
                "collectedEvidence": "Dokumentasi pamer karya, respons audiens, catatan tindak lanjut, dan refleksi akhir.",
            },
        ]

        if meeting_count <= len(base_stages):
            selected = base_stages[:meeting_count]
            if meeting_count == 2:
                selected[-1] = {
                    **selected[-1],
                    "stageTitle": "Penyusunan Produk, Presentasi, dan Refleksi",
                    "studentActivities": f"Murid mengolah temuan, menyusun {final_product}, mempresentasikan hasil, dan menulis refleksi singkat.",
                    "collectedEvidence": f"Catatan data, {final_product}, presentasi singkat, dan refleksi.",
                }
            if meeting_count == 3:
                selected[-1] = {
                    **selected[-1],
                    "stageTitle": "Penyusunan Produk, Presentasi, dan Refleksi",
                    "studentActivities": f"Murid menyelesaikan {final_product}, mempresentasikan proses serta hasil, dan menulis refleksi singkat.",
                    "collectedEvidence": f"{final_product}, catatan umpan balik, presentasi, dan refleksi.",
                }
            return selected

        plan = base_stages[:]
        for index in range(len(base_stages) + 1, meeting_count + 1):
            plan.append(
                {
                    "meeting": index,
                    "stageTitle": f"Pendalaman dan Tindak Lanjut {index}",
                    "duration": "2 JP",
                    "opening": "Guru membuka dengan meninjau capaian tahap sebelumnya.",
                    "mainActivities": activities,
                    "closing": "Kelompok menyampaikan kemajuan dan kebutuhan bantuan.",
                    "formativeAssessment": "Observasi proses, cek produk sementara, dan umpan balik singkat.",
                    "teacherSteps": "Guru memantau kemajuan kelompok, memberi arahan sesuai kebutuhan, dan memastikan bukti belajar terkumpul.",
                    "studentActivities": "Murid melanjutkan pekerjaan proyek, memperbaiki hasil, dan menyiapkan bukti untuk tahap berikutnya.",
                    "collectedEvidence": "Kemajuan produk, catatan proses, dokumentasi, dan refleksi singkat.",
                }
            )
        if decision_text and plan:
            plan[0]["opening"] = compact_text(
                f"{plan[0]['opening']} Keputusan diskusi guru: {decision_text}",
                500,
            )
        return plan

    def _rubric(self) -> list[dict[str, Any]]:
        return [
            {
                "dimension": "Kreativitas",
                "aspect": "Ide produk/aksi dan tampilan hasil",
                "excellent": "Produk/aksi menarik, sesuai tema, rapi, dan memiliki pengembangan ide sendiri.",
                "good": "Produk/aksi sesuai tema dan cukup rapi.",
                "fair": "Produk/aksi sudah dibuat, tetapi ide atau tampilan masih perlu diperjelas.",
                "needsGuidance": "Produk/aksi belum siap atau tidak sesuai tema.",
            },
            {
                "dimension": "Kolaborasi",
                "aspect": "Kerja kelompok dan pembagian peran",
                "excellent": "Semua anggota menjalankan peran, saling membantu, dan menyelesaikan masalah dengan baik.",
                "good": "Sebagian besar anggota menjalankan peran dengan baik.",
                "fair": "Kerja kelompok berjalan, tetapi masih bergantung pada beberapa anggota.",
                "needsGuidance": "Kelompok belum bekerja sama dengan baik.",
            },
            {
                "dimension": "Kemandirian",
                "aspect": "Tanggung jawab menyelesaikan tugas",
                "excellent": "Murid menyiapkan tugasnya tanpa banyak diingatkan dan membantu menjaga kerapian kegiatan.",
                "good": "Murid menyelesaikan tugas dengan sedikit arahan.",
                "fair": "Murid menyelesaikan sebagian tugas dengan banyak arahan.",
                "needsGuidance": "Murid belum menunjukkan tanggung jawab pada tugasnya.",
            },
            {
                "dimension": "Komunikasi",
                "aspect": "Promosi, pelayanan, dan presentasi",
                "excellent": "Murid menjelaskan hasil proyek dengan jelas, sopan, dan percaya diri.",
                "good": "Murid menjelaskan hasil proyek dengan cukup jelas dan sopan.",
                "fair": "Murid masih ragu-ragu saat menjelaskan hasil proyek.",
                "needsGuidance": "Murid belum mampu menjelaskan hasil proyek dengan jelas.",
            },
        ]

    def _normalize_content(
        self,
        content: dict[str, Any],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = dict(fallback)
        for key, value in content.items():
            if value not in (None, "", [], {}):
                if isinstance(value, dict) and isinstance(normalized.get(key), dict):
                    normalized[key] = self._deep_merge(
                        normalized.get(key) or {},
                        value,
                    )
                else:
                    normalized[key] = value
        return normalized

    def _deep_merge(
        self,
        fallback: dict[str, Any],
        value: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(fallback)
        for key, item in value.items():
            if item in (None, "", [], {}):
                continue
            if isinstance(item, dict) and isinstance(merged.get(key), dict):
                merged[key] = self._deep_merge(merged.get(key) or {}, item)
            else:
                merged[key] = item
        return merged

    def _to_markdown(self, content: dict[str, Any]) -> str:
        def text(value: Any, default: str = "-") -> str:
            normalized = self._join(value)
            return normalized or default

        def table(headers: list[str], rows: list[list[Any]]) -> list[str]:
            cleaned_rows = [
                [text(cell) for cell in row]
                for row in rows
                if any(text(cell, "") for cell in row)
            ]
            if not cleaned_rows:
                return []
            return [
                "| " + " | ".join(headers) + " |",
                "| " + " | ".join("---" for _ in headers) + " |",
                *[
                    "| " + " | ".join(cell.replace("\n", "<br>") for cell in row) + " |"
                    for row in cleaned_rows
                ],
            ]

        title = content.get("title") or "RPP PjBL Kokurikuler"
        identity = content.get("identity") or {}
        overview = content.get("projectOverview") or {}
        design = content.get("learningDesign") or {}
        assessment = content.get("assessment") or {}
        final_product = identity.get("finalProduct") or design.get("finalProduct") or "-"
        related_subjects = self._string_list(identity.get("relatedSubjects"))
        phase = str(identity.get("educationPhase") or identity.get("phase") or "-")
        if phase != "-" and not phase.casefold().startswith("fase "):
            phase = f"Fase {phase.upper()}"
        context_project = (
            overview.get("background")
            or overview.get("focusAndScope")
            or overview.get("localIssue")
            or "Kegiatan kokurikuler ini mengajak murid mengalami proses proyek nyata yang aman, kolaboratif, dan dekat dengan kehidupan sehari-hari."
        )
        meeting_count = text(identity.get("meetingCount"), "1")
        time_allocation = text(identity.get("timeAllocation"), "2 JP")
        total_time_allocation = text(
            identity.get("timeAllocationTotal"),
            f"{meeting_count} pertemuan x {time_allocation}",
        )
        lines = [
            "# RPM KOKURIKULER",
            "",
            f"## {title}",
            "",
            "## A. Identitas Pembelajaran",
            f"Nama Sekolah: {text(identity.get('schoolName'))}",
            f"Nama Guru: {text(identity.get('teacherName'))}",
            f"Jenjang Pendidikan: {text(identity.get('educationLevel'))}",
            f"Fase: {phase}",
            f"Kelas/Semester: {text(identity.get('gradeLevel'))}",
            f"Bentuk Kokurikuler: {text(identity.get('kokurikulerForm'), 'Pembelajaran kolaboratif lintas disiplin ilmu')}",
            f"Alokasi Waktu Total: {total_time_allocation}",
            f"Produk Akhir: {text(final_product)}",
            "Mata Pelajaran/Muatan Terkait: "
            + (", ".join(related_subjects) if related_subjects else "-"),
            "",
            "### Konteks Proyek",
            text(identity.get("projectContext") or context_project),
            "",
            "## B. Profil dan Arah Pembelajaran",
            "",
            "### 1. Gambaran Proyek",
            text(
                overview.get("narrative")
                or overview.get("background")
                or overview.get("focusAndScope")
                or overview.get("drivingQuestion")
                or "Murid bekerja dalam kelompok untuk menyelesaikan proyek kontekstual dan menghasilkan produk atau aksi akhir yang dapat dipresentasikan."
            ),
            "",
            "### Hasil yang Diharapkan",
        ]
        for index, item in enumerate(
            content.get("expectedOutcomes") or content.get("learningObjectives") or [],
            start=1,
        ):
            lines.append(f"{index}. {item}")
        evidence = [
            "catatan proses kelompok",
            "dokumentasi kegiatan",
            text(final_product),
            "presentasi singkat",
            "refleksi murid",
        ]
        lines.extend(
            [
                "",
                "### Bukti Belajar",
                *[f"- {item}" for item in evidence if item and item != "-"],
                "",
                "### Batas Aman Kegiatan",
                text(
                    content.get("safeBoundaries")
                    or design.get("riskMitigation")
                    or "Guru memastikan kegiatan sesuai aturan sekolah, aman bagi murid, dan realistis dengan waktu serta sumber daya yang tersedia."
                ),
                "",
                "### 2. Profil Lulusan yang Dikembangkan",
            ]
        )
        profile_rows = [
            [item.get("dimension"), item.get("description")]
            for item in content.get("graduateProfiles") or []
            if isinstance(item, dict)
        ]
        lines.extend(table(["Dimensi", "Perilaku yang Dikembangkan"], profile_rows))
        lines.extend(["", "### 3. Mata Pelajaran/Muatan Terkait"])
        subject_rows = [
            [item.get("subject"), item.get("description")]
            for item in content.get("relatedSubjectDetails") or []
            if isinstance(item, dict)
        ]
        lines.extend(table(["Mata Pelajaran/Muatan", "Peran dalam Proyek"], subject_rows))

        lines.extend(
            [
                "",
                "## C. Desain Pembelajaran",
                "",
                "### 1. Praktik Pedagogis",
                text(
                    design.get("pedagogicalPracticeDescription")
                    or design.get("pedagogicalApproach")
                    or "Praktik pedagogis menggunakan pembelajaran berbasis proyek, diskusi kelompok, dan refleksi terarah."
                ),
                "",
                "### Bentuk Praktik Pedagogis",
            ]
        )
        for item in design.get("pedagogicalForms") or []:
            lines.append(f"- {item}")
        environment = design.get("learningEnvironment") or {}
        lines.extend(["", "### 2. Lingkungan Belajar"])
        if isinstance(environment, dict):
            environment_rows = [
                ["Lingkungan Fisik", environment.get("physical")],
                ["Lingkungan Sosial", environment.get("social")],
                ["Lingkungan Belajar yang Aman", environment.get("safe")],
                ["Lingkungan Reflektif", environment.get("reflective")],
            ]
            lines.extend(table(["Aspek", "Rancangan"], environment_rows))

        lines.extend(["", "### 3. Kemitraan Pembelajaran"])
        partnership_rows = [
            [item.get("partner"), item.get("role")]
            for item in design.get("partnerships") or []
            if isinstance(item, dict)
        ]
        lines.extend(table(["Mitra", "Peran Mitra"], partnership_rows))

        lines.extend(["", "### 4. Pemanfaatan Digital"])
        digital_rows = [
            [item.get("source"), item.get("use")]
            for item in design.get("digitalResources") or []
            if isinstance(item, dict)
        ]
        lines.extend(table(["Sumber Digital", "Tautan/Fungsi"], digital_rows))

        lines.extend(["", "### 5. Sumber Daya"])
        resource_rows = [
            [item.get("resource"), item.get("function")]
            for item in design.get("resources") or []
            if isinstance(item, dict)
        ]
        lines.extend(table(["Sumber Daya", "Fungsi"], resource_rows))

        meeting_plan = content.get("meetingPlan") or []
        stage_names = [
            str(meeting.get("stageTitle") or f"Tahap {index + 1}")
            for index, meeting in enumerate(meeting_plan)
            if isinstance(meeting, dict)
        ]
        lines.extend(
            [
                "",
                "## D. Rangkaian Kegiatan Pembelajaran per Pertemuan",
                "",
                f"### Alur Proyek {title}",
                " → ".join(stage_names) if stage_names else "Pemantik → Kerja Kelompok → Produk/Aksi → Presentasi → Refleksi",
                "",
                text(
                    design.get("activitiesAndSchedule")
                    or "Kegiatan kokurikuler disusun bertahap agar murid bergerak dari pengenalan konteks, perencanaan, pelaksanaan, presentasi, sampai refleksi."
                ),
            ]
        )
        meeting_rows = [
            [
                meeting.get("meeting") or index + 1,
                meeting.get("stageTitle") or f"Tahap {index + 1}",
                meeting.get("duration") or "2 JP",
                self._join(meeting.get("mainActivities"))
                or meeting.get("studentActivities")
                or "-",
            ]
            for index, meeting in enumerate(meeting_plan)
            if isinstance(meeting, dict)
        ]
        lines.extend(["", *table(["Pertemuan", "Tahap Proyek", "Alokasi", "Kegiatan Inti"], meeting_rows)])
        for index, meeting in enumerate(meeting_plan):
            if not isinstance(meeting, dict):
                continue
            lines.extend(
                [
                    "",
                    f"### Tahap {index + 1} - {meeting.get('stageTitle') or 'Kegiatan Proyek'}",
                    f"Durasi: {meeting.get('duration') or '2 JP'}",
                    "",
                    "**Langkah Guru**",
                    text(meeting.get("teacherSteps") or meeting.get("opening")),
                    "",
                    "**Kegiatan Murid**",
                    text(
                        meeting.get("studentActivities")
                        or self._join(meeting.get("mainActivities"))
                    ),
                    "",
                    "**Hasil yang Dikumpulkan**",
                    text(meeting.get("collectedEvidence") or meeting.get("formativeAssessment")),
                ]
            )

        lines.extend(
            [
                "",
                "### 1. Asesmen Formatif",
                text(
                    assessment.get("formativeDescription")
                    or "Guru menggunakan observasi selama kegiatan dan mencatat perilaku penting yang muncul."
                ),
                "",
                *table(
                    assessment.get("formativeColumns")
                    or [
                        "Nama Murid",
                        "Kolaborasi",
                        "Kemandirian",
                        "Komunikasi",
                        "Catatan Guru",
                    ],
                    [["", "", "", "", "Catatan observasi singkat"]],
                ),
                "",
                "### 2. Asesmen Sumatif - Penilaian Kinerja",
                text(
                    assessment.get("summativeDescription")
                    or "Asesmen sumatif digunakan setelah proyek selesai berdasarkan bukti proses, produk, presentasi, dan refleksi murid."
                ),
            ]
        )
        rubric_rows = [
            [
                item.get("dimension"),
                item.get("aspect"),
                item.get("excellent"),
                item.get("good"),
                item.get("fair"),
                item.get("needsGuidance"),
            ]
            for item in assessment.get("rubric") or []
            if isinstance(item, dict)
        ]
        lines.extend(
            table(
                [
                    "Dimensi",
                    "Aspek",
                    "Sangat Baik",
                    "Baik",
                    "Cukup",
                    "Perlu Bimbingan",
                ],
                rubric_rows,
            )
        )

        lines.extend(
            [
                "",
                "## E. Tindak Lanjut Pembelajaran",
                text(
                    content.get("followUp")
                    or "Guru menindaklanjuti hasil proyek dengan memajang atau menggunakan produk akhir, memberi umpan balik singkat, dan mengajak murid menentukan perbaikan kecil untuk kegiatan berikutnya."
                ),
                "",
                "## F. Refleksi Guru",
                text(
                    content.get("teacherReflection")
                    or content.get("teacherNotes")
                    or "Guru merefleksikan keterlibatan murid, kecukupan waktu, efektivitas pembagian peran, dukungan fasilitas, dan kualitas produk akhir sebagai dasar penyempurnaan proyek."
                ),
            ]
        )
        if content.get("teacherNotes"):
            lines.extend(["", "### Catatan Guru", text(content["teacherNotes"])])
        return "\n".join(lines)

    def _risk_text(self, selected_project: dict[str, Any]) -> str:
        risks = selected_project.get("riskMitigation")
        if not isinstance(risks, list) or not risks:
            return "Guru memberi batas area, contoh pengisian, dan instruksi kerja singkat agar proyek tetap realistis."
        parts = []
        for item in risks:
            if isinstance(item, dict):
                risk = item.get("risk")
                mitigation = item.get("mitigation")
                if risk and mitigation:
                    parts.append(f"{risk}: {mitigation}")
        return self._join(parts) or "Risiko proyek dimitigasi dengan instruksi dan pendampingan guru."

    def _as_dict(self, value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    def _string_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [value]
        return []

    def _string_list_from_risk(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        risks: list[str] = []
        for item in value:
            if isinstance(item, dict):
                risk = item.get("risk")
                level = item.get("level")
                mitigation = item.get("mitigationNeed")
                text = " - ".join(
                    str(part)
                    for part in (risk, f"level: {level}" if level else "", mitigation)
                    if part
                )
                if text:
                    risks.append(text)
            elif str(item).strip():
                risks.append(str(item))
        return risks

    def _join(self, value: Any) -> str:
        if isinstance(value, list):
            parts = [self._join(item) for item in value]
            return ", ".join(part for part in parts if part)
        if isinstance(value, dict):
            parts = []
            for key, item in value.items():
                text = self._join(item)
                if text:
                    parts.append(f"{key}: {text}")
                if len(parts) >= 6:
                    break
            return "; ".join(parts)
        return compact_text(str(value or ""), 700)

    def _dump(self, value: Any) -> dict[str, Any]:
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if isinstance(value, dict):
            return value
        return {}
