from __future__ import annotations

import json
from typing import Any

from app.schemas.common_schema import UsedReferenceSchema
from app.schemas.generate_rpp_schema import GenerateRppRequest, GenerateRppResponse
from app.services.llm_client import LLMClient
from app.services.prompt_builder_service import PromptBuilderService
from app.services.rag_service import RAGService
from app.utils.text_cleaner import compact_text


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
        references = await self.rag_service.search_for_context(
            query=payload.project.title or payload.project.subject or "RPP PjBL",
            subject=payload.project.subject,
            phase=payload.project.phase,
            top_k=5,
        )

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

        generated = await self.llm_client.generate_json(
            messages,
            fallback,
            temperature=0.2,
        )
        content_json = (
            generated.get("contentJson") if isinstance(generated, dict) else None
        )
        if not isinstance(content_json, dict):
            content_json = fallback_content
        content_json = self._normalize_content(content_json, fallback_content)

        content_markdown = self._to_markdown(content_json)

        return GenerateRppResponse(
            status="success",
            model=self.llm_client.model_name,
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

    def _build_system_prompt(self) -> str:
        return """
Anda adalah AI Service Petunjukku untuk menyusun RPP PjBL Kokurikuler final.

Output wajib hanya JSON valid:
{
  "contentJson": {...},
  "contentMarkdown": "..."
}

Aturan:
- Gunakan hanya sourceData.
- Ikuti template RPM/RPP Kokurikuler: A. Identitas Pembelajaran,
  B. Profil dan Arah Pembelajaran, C. Desain Pembelajaran,
  D. Rangkaian Kegiatan Pembelajaran per Pertemuan, Asesmen Formatif,
  dan Asesmen Sumatif - Penilaian Kinerja.
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
- Buat RPP ringkas, operasional, dan siap dipakai guru.
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
        final_product = (
            summary.get("finalProduct")
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
                "timeAllocation": duration,
                "kokurikulerForm": "Pembelajaran kolaboratif lintas disiplin ilmu",
                "finalProduct": final_product,
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
                "background": selected_project.get("projectBackground")
                or selected_project.get("description")
                or stage1.get("teacherExpectation"),
                "drivingQuestion": selected_project.get("drivingQuestion")
                or stage2.get("drivingQuestion"),
                "focusAndScope": summary.get("focusAndScope")
                or selected_project.get("projectFocus"),
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
                "pedagogicalApproach": stage3_flat.get("praktikPedagogis")
                or stage3_flat.get("preferensiPedagogis"),
                "activityFlowReason": stage3_flat.get("alasanPraktikPedagogis"),
                "pedagogicalPracticeDescription": (
                    stage3_flat.get("alasanPraktikPedagogis")
                    or "Pembelajaran menggunakan mini-PjBL, diskusi kolaboratif, dan refleksi terarah agar murid mengalami proses proyek secara bertahap."
                ),
                "pedagogicalForms": self._pedagogical_forms(title),
                "learningEnvironment": self._learning_environment(
                    school_context,
                    stage1_flat,
                ),
                "partnerships": self._partnerships(stage3_flat),
                "digitalResources": self._digital_resources(stage3_flat),
                "resources": self._resources(stage3_flat, school_context),
                "activitiesAndSchedule": summary.get("activitiesAndSchedule")
                or stage3_flat.get("ringkasan")
                or stage3_flat.get("summary")
                or self._join(activities),
                "rolesAndSupport": summary.get("rolesAndSupport")
                or "Siswa bekerja dalam kelompok kecil dengan pembagian peran sederhana; guru memantau proses dan memberi umpan balik singkat.",
                "facilitiesTechnologyPartnership": summary.get(
                    "facilitiesTechnologyPartnership"
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
                or self._assessment_reflection_text(stage4_flat)
                or "Guru menilai proses, produk akhir, presentasi, kontribusi anggota, dan refleksi singkat siswa.",
            },
            "meetingPlan": self._meeting_plan(
                activities,
                duration,
                stage4=stage4,
                stage4_flat=stage4_flat,
            ),
            "assessment": self._assessment_from_stage4(stage4, stage4_flat),
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
        return subjects or ["Prakarya", "IPS", "Matematika", "Bahasa Indonesia"]

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

    def _digital_resources(self, stage3_flat: dict[str, Any]) -> list[dict[str, str]]:
        digital = self._join(
            stage3_flat.get("pemanfaatanDigital")
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
        stage4: dict[str, Any] | None = None,
        stage4_flat: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        meetings = (stage4_flat or {}).get("pertemuan")
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
            if plan:
                return plan

        return [
            {
                "meeting": 1,
                "stageTitle": "Membuka Konteks Proyek",
                "duration": "2 JP",
                "opening": "Guru membuka dengan pertanyaan pemantik dan mengaitkan proyek dengan isu lokal.",
                "mainActivities": activities,
                "closing": "Siswa mempresentasikan temuan atau produk awal, lalu menulis refleksi singkat.",
                "formativeAssessment": "Observasi proses kelompok, cek produk, dan tanya jawab singkat.",
                "teacherSteps": "Guru membuka konteks proyek, menunjukkan contoh, dan memandu murid menyusun peta ide awal.",
                "studentActivities": "Murid berbagi pengalaman, mengamati contoh, berdiskusi, dan mencatat ide awal proyek.",
                "collectedEvidence": "Daftar ide awal, catatan kelompok, dan refleksi singkat.",
            }
        ]

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
        lines = [
            f"# {title}",
            "",
            "## A. Identitas Pembelajaran",
            f"Nama Sekolah: {identity.get('schoolName') or '-'}",
            f"Nama Guru: {identity.get('teacherName') or '-'}",
            f"Jenjang: {identity.get('educationLevel') or '-'}",
            f"Fase: {phase}",
            f"Kelas/Semester: {identity.get('gradeLevel') or '-'}",
            f"Bentuk kokurikuler: {identity.get('kokurikulerForm') or 'Pembelajaran kolaboratif lintas disiplin ilmu'}",
            f"Alokasi Waktu Total: {identity.get('timeAllocation') or '-'}",
            f"Produk akhir: {final_product}",
            "Mata pelajaran/muatan terkait: "
            + (", ".join(related_subjects) if related_subjects else "-"),
            "",
            "### Konteks Proyek",
            str(
                overview.get("background")
                or overview.get("focusAndScope")
                or "Kegiatan kokurikuler ini mengajak murid mengalami proses proyek nyata yang aman, kolaboratif, dan dekat dengan kehidupan sehari-hari."
            ),
            "",
            "## B. Profil dan Arah Pembelajaran",
            "",
            "### 1. Gambaran Proyek",
            str(
                overview.get("focusAndScope")
                or overview.get("drivingQuestion")
                or overview.get("localIssue")
                or "Murid bekerja dalam kelompok untuk menyelesaikan proyek kontekstual dan menghasilkan produk atau aksi akhir yang dapat dipresentasikan."
            ),
            "",
            "### Hasil yang Diharapkan",
        ]
        for item in content.get("expectedOutcomes") or content.get("learningObjectives") or []:
            lines.append(f"- {item}")
        lines.extend(
            [
                "",
                "### Batas Aman Kegiatan",
                str(
                    content.get("safeBoundaries")
                    or design.get("riskMitigation")
                    or "Guru memastikan kegiatan sesuai aturan sekolah, aman bagi murid, dan realistis dengan waktu serta sumber daya yang tersedia."
                ),
                "",
                "### 2. Profil Lulusan yang Dikembangkan",
            ]
        )
        for item in content.get("graduateProfiles") or []:
            if isinstance(item, dict):
                lines.append(
                    f"- **{item.get('dimension')}:** {item.get('description')}"
                )
        lines.extend(["", "### 3. Mata Pelajaran/Muatan Terkait"])
        for item in content.get("relatedSubjectDetails") or []:
            if isinstance(item, dict):
                lines.append(f"- **{item.get('subject')}:** {item.get('description')}")

        lines.extend(
            [
                "",
                "## C. Desain Pembelajaran",
                "",
                "### 1. Praktik Pedagogis",
                str(
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
            labels = {
                "physical": "Lingkungan Fisik",
                "social": "Lingkungan Sosial",
                "safe": "Lingkungan Belajar yang Aman",
                "reflective": "Lingkungan Reflektif",
            }
            for key, label in labels.items():
                if environment.get(key):
                    lines.append(f"- **{label}:** {environment[key]}")

        lines.extend(["", "### 3. Kemitraan Pembelajaran"])
        for item in design.get("partnerships") or []:
            if isinstance(item, dict):
                lines.append(f"- **{item.get('partner')}:** {item.get('role')}")

        lines.extend(["", "### 4. Pemanfaatan Digital"])
        for item in design.get("digitalResources") or []:
            if isinstance(item, dict):
                lines.append(f"- **{item.get('source')}:** {item.get('use')}")

        lines.extend(["", "### 5. Sumber Daya"])
        for item in design.get("resources") or []:
            if isinstance(item, dict):
                lines.append(f"- **{item.get('resource')}:** {item.get('function')}")

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
                str(
                    design.get("activitiesAndSchedule")
                    or "Kegiatan kokurikuler disusun bertahap agar murid bergerak dari pengenalan konteks, perencanaan, pelaksanaan, presentasi, sampai refleksi."
                ),
            ]
        )
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
                    str(meeting.get("teacherSteps") or meeting.get("opening") or "-"),
                    "",
                    "**Kegiatan Murid**",
                    str(
                        meeting.get("studentActivities")
                        or self._join(meeting.get("mainActivities"))
                        or "-"
                    ),
                    "",
                    "**Hasil yang Dikumpulkan**",
                    str(meeting.get("collectedEvidence") or meeting.get("formativeAssessment") or "-"),
                ]
            )

        lines.extend(
            [
                "",
                "### 1. Asesmen Formatif",
                str(
                    assessment.get("formativeDescription")
                    or "Guru menggunakan observasi selama kegiatan dan mencatat perilaku penting yang muncul."
                ),
                "",
                "Kolom observasi: "
                + ", ".join(assessment.get("formativeColumns") or []),
                "",
                "### 2. Asesmen Sumatif - Penilaian Kinerja",
                str(
                    assessment.get("summativeDescription")
                    or "Asesmen sumatif digunakan setelah proyek selesai berdasarkan bukti proses, produk, presentasi, dan refleksi murid."
                ),
            ]
        )
        for item in assessment.get("rubric") or []:
            if not isinstance(item, dict):
                continue
            lines.extend(
                [
                    "",
                    f"- **{item.get('dimension')} - {item.get('aspect')}:**",
                    f"  - Sangat Baik: {item.get('excellent')}",
                    f"  - Baik: {item.get('good')}",
                    f"  - Cukup: {item.get('fair')}",
                    f"  - Perlu Bimbingan: {item.get('needsGuidance')}",
                ]
            )

        if content.get("teacherNotes"):
            lines.extend(["", "## Catatan Guru", str(content["teacherNotes"])])
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
