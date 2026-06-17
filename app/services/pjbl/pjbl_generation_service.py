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
                            "sebagai proyek terpilih, dan summary Kina sebagai "
                            "keputusan final diskusi. Return hanya JSON valid dengan "
                            "key contentJson dan contentMarkdown."
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
        content_json = generated.get("contentJson") if isinstance(generated, dict) else None
        if not isinstance(content_json, dict):
            content_json = fallback_content
        content_json = self._normalize_content(content_json, fallback_content)

        content_markdown = generated.get("contentMarkdown") if isinstance(generated, dict) else None
        if not isinstance(content_markdown, str) or not content_markdown.strip():
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
- Stage 1 adalah konteks sekolah, kelas, isu lokal, durasi, fasilitas, dan batasan.
- Stage 2 adalah proyek terpilih, tujuan, driving question, produk, aktivitas awal,
  kelayakan, dan risiko.
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
            "kinaChatSummary": payload.kinaChatSummary or {},
            "options": payload.options,
            "ragReferences": [reference.model_dump() for reference in references],
        }

    def _fallback_content(self, source_data: dict[str, Any]) -> dict[str, Any]:
        project = source_data.get("project") or {}
        stage1 = source_data.get("stage1") or {}
        stage2 = source_data.get("stage2") or {}
        summary = source_data.get("kinaChatSummary") or {}
        school_context = self._as_dict(stage1.get("schoolContext"))
        area_context = self._as_dict(stage1.get("areaContext"))
        mission_spec = self._as_dict(stage1.get("missionSpec"))
        learning_duration = self._as_dict(mission_spec.get("learningDuration"))
        class_context = self._as_dict(stage1.get("classContext"))
        selected_project = self._selected_project(stage2)

        title = (
            selected_project.get("recommendedProjectTitle")
            or stage2.get("selectedProjectTitle")
            or project.get("title")
            or "RPP PjBL Kokurikuler"
        )
        duration = (
            learning_duration.get("durationText")
            or stage1.get("projectDuration")
            or "2 x 35 menit (Jam Pelajaran)"
        )
        activities = self._string_list(
            selected_project.get("projectActivitiesOverview")
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
            "identity": {
                "schoolName": school_context.get("name")
                or source_data.get("school", {}).get("name"),
                "city": school_context.get("city")
                or source_data.get("school", {}).get("city"),
                "subject": project.get("subject"),
                "phase": project.get("phase"),
                "educationLevel": mission_spec.get("educationLevel"),
                "educationPhase": mission_spec.get("educationPhase"),
                "relatedSubjects": self._string_list(
                    mission_spec.get("relatedSubjects")
                ),
                "gradeLevel": project.get("gradeLevel")
                or class_context.get("className"),
                "rppType": project.get("rppType"),
                "timeAllocation": duration,
            },
            "projectOverview": {
                "theme": selected_project.get("projectTheme")
                or stage2.get("projectTheme")
                or stage1.get("theme"),
                "localIssue": stage1.get("localIssue"),
                "background": selected_project.get("projectBackground")
                or stage1.get("teacherExpectation"),
                "drivingQuestion": selected_project.get("drivingQuestion")
                or stage2.get("drivingQuestion"),
                "focusAndScope": summary.get("focusAndScope")
                or selected_project.get("projectFocus"),
                "studentNeeds": stage1.get("studentNeeds"),
                "areaContext": area_context,
                "initialRiskMonitoring": self._string_list_from_risk(
                    stage1.get("riskMonitoring")
                ),
            },
            "learningObjectives": self._string_list(
                selected_project.get("projectObjectives")
                or stage2.get("projectObjectives")
            ),
            "studentContext": {
                "className": class_context.get("className"),
                "studentCount": class_context.get("studentCount"),
                "characteristics": class_context.get("studentCharacteristics"),
                "classCondition": mission_spec.get("classCondition"),
                "learningChallenges": self._string_list(
                    class_context.get("learningChallenges")
                ),
                "dominantLearningStyle": class_context.get("dominantLearningStyle"),
            },
            "learningDesign": {
                "finalProduct": summary.get("finalProduct")
                or self._join(
                    selected_project.get("studentProduct")
                    or stage2.get("studentProduct")
                ),
                "activitiesAndSchedule": summary.get("activitiesAndSchedule")
                or self._join(activities),
                "rolesAndSupport": summary.get("rolesAndSupport")
                or "Siswa bekerja dalam kelompok kecil dengan pembagian peran sederhana; guru memantau proses dan memberi umpan balik singkat.",
                "facilitiesTechnologyPartnership": summary.get(
                    "facilitiesTechnologyPartnership"
                )
                or self._join(school_context.get("facilities")),
                "riskMitigation": summary.get("riskMitigation")
                or self._risk_text(selected_project),
                "assessmentReflection": summary.get("assessmentReflection")
                or "Guru menilai proses, produk akhir, presentasi, kontribusi anggota, dan refleksi singkat siswa.",
            },
            "meetingPlan": self._meeting_plan(activities, duration),
            "assessment": {
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
                "rubric": self._rubric(),
            },
            "teacherNotes": summary.get("teacherNotes")
            or stage1.get("teacherExpectation"),
            "completionStatus": summary.get("projectCompletionStatus") or "draft",
        }
        if not content["learningObjectives"]:
            content["learningObjectives"] = [
                "Peserta didik mampu mengidentifikasi masalah nyata sesuai tema proyek.",
                "Peserta didik mampu mengumpulkan dan menyajikan data sederhana.",
                "Peserta didik mampu mempresentasikan hasil proyek secara kolaboratif.",
            ]
        return content

    def _selected_project(self, stage2: dict[str, Any]) -> dict[str, Any]:
        selected = stage2.get("selectedProjectRecommendation")
        if isinstance(selected, dict):
            return selected
        recommendations = stage2.get("projectRecommendations")
        if isinstance(recommendations, list) and recommendations:
            first = recommendations[0]
            if isinstance(first, dict):
                return first
        return stage2

    def _meeting_plan(self, activities: list[str], duration: str) -> list[dict[str, Any]]:
        return [
            {
                "meeting": 1,
                "duration": duration,
                "opening": "Guru membuka dengan pertanyaan pemantik dan mengaitkan proyek dengan isu lokal.",
                "mainActivities": activities,
                "closing": "Siswa mempresentasikan temuan atau produk awal, lalu menulis refleksi singkat.",
                "formativeAssessment": "Observasi proses kelompok, cek produk, dan tanya jawab singkat.",
            }
        ]

    def _rubric(self) -> list[dict[str, str]]:
        return [
            {
                "criterion": "Pemahaman masalah",
                "description": "Siswa mampu menjelaskan masalah proyek sesuai konteks sekolah.",
            },
            {
                "criterion": "Kualitas produk",
                "description": "Produk akhir jelas, relevan, dan dapat dipahami warga kelas/sekolah.",
            },
            {
                "criterion": "Kolaborasi",
                "description": "Siswa menjalankan peran dan bekerja sama secara bertanggung jawab.",
            },
            {
                "criterion": "Refleksi",
                "description": "Siswa mampu menyampaikan pembelajaran dan rencana tindak lanjut sederhana.",
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
                normalized[key] = value
        return normalized

    def _to_markdown(self, content: dict[str, Any]) -> str:
        lines = [f"# {content.get('title') or 'RPP PjBL Kokurikuler'}", ""]
        lines.extend(["## A. Identitas"])
        for key, value in (content.get("identity") or {}).items():
            if value not in (None, "", [], {}):
                if isinstance(value, list):
                    lines.append(f"- {key}: {', '.join(str(item) for item in value)}")
                else:
                    lines.append(f"- {key}: {value}")

        overview = content.get("projectOverview") or {}
        lines.extend(["", "## B. Gambaran Proyek"])
        for key in ("theme", "localIssue", "background", "drivingQuestion", "focusAndScope"):
            if overview.get(key):
                lines.append(f"- {key}: {overview[key]}")
        area_context = overview.get("areaContext") or {}
        if isinstance(area_context, dict) and area_context:
            lines.extend(["", "### Konteks Daerah Sekitar"])
            for key, value in area_context.items():
                if isinstance(value, list):
                    lines.append(f"- {key}: {', '.join(str(item) for item in value)}")
                elif value:
                    lines.append(f"- {key}: {value}")
        initial_risks = overview.get("initialRiskMonitoring") or []
        if initial_risks:
            lines.extend(["", "### Pemantauan Risiko Awal"])
            for risk in initial_risks:
                lines.append(f"- {risk}")

        lines.extend(["", "## C. Tujuan Pembelajaran"])
        for objective in content.get("learningObjectives") or []:
            lines.append(f"- {objective}")

        design = content.get("learningDesign") or {}
        lines.extend(["", "## D. Desain Pembelajaran"])
        for key, value in design.items():
            lines.append(f"- {key}: {value}")

        lines.extend(["", "## E. Alur Kegiatan"])
        for meeting in content.get("meetingPlan") or []:
            lines.append(f"### Pertemuan {meeting.get('meeting')}")
            lines.append(f"- Durasi: {meeting.get('duration')}")
            lines.append(f"- Pembuka: {meeting.get('opening')}")
            lines.append("- Kegiatan inti:")
            for activity in meeting.get("mainActivities") or []:
                lines.append(f"  - {activity}")
            lines.append(f"- Penutup: {meeting.get('closing')}")
            lines.append(f"- Asesmen formatif: {meeting.get('formativeAssessment')}")

        assessment = content.get("assessment") or {}
        lines.extend(["", "## F. Asesmen dan Refleksi"])
        for key in ("process", "product", "presentation"):
            values = assessment.get(key) or []
            if values:
                lines.append(f"### {key}")
                for value in values:
                    lines.append(f"- {value}")
        if assessment.get("reflection"):
            lines.append(f"- Refleksi: {assessment['reflection']}")

        lines.extend(["", "## G. Rubrik Singkat"])
        for item in assessment.get("rubric") or []:
            lines.append(f"- {item.get('criterion')}: {item.get('description')}")

        if content.get("teacherNotes"):
            lines.extend(["", "## H. Catatan Guru", str(content["teacherNotes"])])
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
            return ", ".join(str(item) for item in value if str(item).strip())
        return compact_text(str(value or ""), 700)

    def _dump(self, value: Any) -> dict[str, Any]:
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if isinstance(value, dict):
            return value
        return {}
