from __future__ import annotations

import json
import re
from typing import Any

from app.schemas.common_schema import UsedReferenceSchema
from app.schemas.generate_rpp_schema import GenerateRppRequest, GenerateRppResponse
from app.services.intrakurikuler.intra_dummy_stage_data import (
    get_intra_dummy_onboarding_content,
    get_intra_dummy_stage_content,
)
from app.services.llm_client import LLMClient
from app.services.prompt_builder_service import PromptBuilderService
from app.services.rag_service import RAGService


class IntraGenerationService:
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
            query=payload.project.title or payload.project.subject or "RPP",
            subject=payload.project.subject,
            phase=payload.project.phase,
            top_k=5,
        )

        source_data = self._build_source_data(payload, references)
        response_shape = self._empty_response_shape(payload, source_data)

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
                            "Isi requiredResponseShape menjadi contentJson RPP final berdasarkan sourceData. "
                            "Gunakan seluruh data Stage 1, Stage 2, Stage 3, dan Stage 4 sebagai dasar penyusunan RPP. "
                            "Jangan memilih sebagian data jika sourceData menyediakan beberapa item. "
                            "Semua isi naratif harus dikembangkan oleh LLM API berdasarkan sourceData. "
                            "Return hanya JSON valid dengan key contentJson."
                        ),
                        "project": payload.project.model_dump(),
                        "sourceData": source_data,
                        "requiredResponseShape": {
                            "contentJson": response_shape,
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        generated = await self.llm_client.generate_json(
            messages,
            fallback={"contentJson": response_shape},
            temperature=0.22,
        )

        content_json = generated.get("contentJson") if isinstance(generated, dict) else None

        if not isinstance(content_json, dict):
            content_json = response_shape

        content_json = self._normalize_generated_text(content_json)
        content_json = self._normalize_output_structure(content_json)
        content_json = self._enforce_stage1_stage2_stage4_structure(content_json, source_data)
        content_json = self._enforce_stage3_learning_design(content_json, source_data)

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
Anda adalah AI Service Petunjukku untuk menyusun RPP Intrakurikuler final.

Output wajib hanya JSON valid:
{"contentJson": {...}}

A. Cara Membaca Source Data
1. onboarding digunakan untuk identitas sekolah, guru, kelas, fase, dan mata pelajaran.
2. Stage 1 digunakan untuk konteks dasar kelas, topik, durasi, jumlah pertemuan, dan fasilitas awal yang tersedia.
3. Stage 2 digunakan untuk CP/ATP, profil lulusan, lintas disiplin, tujuan pembelajaran, dan pertanyaan pemantik.
4. Stage 3 digunakan sebagai keputusan final diskusi tentang strategi pembelajaran, praktik pedagogis, media digital, kemitraan, sumber daya yang dipilih, produk akhir, diferensiasi, dan alur kegiatan.
5. Stage 4 digunakan untuk teknik asesmen formatif per pertemuan.
6. lockedDecisionsFromStage3 adalah ringkasan keputusan final Stage 3 dan wajib diprioritaskan.

B. Prinsip Utama
1. Ikuti struktur requiredResponseShape.
2. Isi semua field naratif utama berdasarkan Stage 1-4.
3. Jangan mengembalikan shape kosong.
4. Jangan mengarang identitas, fasilitas, platform, mitra, tautan, atau sumber daya yang tidak ada pada Stage 1-4.
5. Jangan memilih hanya satu item jika sourceData berisi beberapa item.
6. Gunakan istilah "murid", bukan "siswa" atau "peserta didik".
7. learningObjectives dan target pertemuan harus diawali "Murid mampu ...".
8. Gaya bahasa harus naratif, siap ditempel ke dokumen RPP, dan tidak berupa frasa pendek.

C. Prioritas Keputusan
Jika ada konflik antar data, gunakan urutan prioritas berikut:
1. lockedDecisionsFromStage3
2. Stage 3
3. Stage 2
4. Stage 1

Aturan prioritas:
- topic, timeAllocation, dan meetingCount mengikuti Stage 1.
- element disimpulkan dari Stage 1 dan Stage 2.
- profil lulusan, lintas disiplin, tujuan pembelajaran, dan pertanyaan pemantik mengikuti Stage 2.
- teknik asesmen formatif per pertemuan mengikuti Stage 4.
- produk akhir, media digital, kemitraan, sumber daya yang dipilih, alur kegiatan, dan diferensiasi mengikuti Stage 3.
- fasilitasAwal pada Stage 1 hanya menunjukkan fasilitas yang tersedia. Fasilitas awal tidak otomatis menjadi sumber daya yang digunakan.
- partnership berasal dari field partnership Stage 3.
- digitalUse berasal dari field digitalPlatform Stage 3.
- resources berasal dari field facilityAndTechnologyUse Stage 3.
- discussionSummary hanya digunakan sebagai konteks penguat narasi, bukan sebagai sumber utama untuk mengelompokkan partnership, digitalUse, dan resources.

D. Aturan Learning Design
- pedagogicalPractice dikembangkan dari learningStrategy dan pedagogicalApproach Stage 3.
- partnership dikembangkan dari partnership Stage 3.
- digitalUse dikembangkan dari digitalPlatform Stage 3.
- resources dikembangkan dari facilityAndTechnologyUse Stage 3.
- partnership hanya memuat mitra pembelajaran.
- digitalUse hanya memuat media, aplikasi, sumber digital, atau platform digital.
- resources hanya memuat alat, bahan, fasilitas, atau sumber daya fisik.
- Jangan memasukkan alat fisik ke digitalUse jika alat tersebut dijelaskan pada facilityAndTechnologyUse.
- Jangan memasukkan media/platform digital ke resources jika media tersebut dijelaskan pada digitalPlatform.
- Jangan menulis "tidak digunakan" pada partnership, digitalUse, atau resources apabila Stage 3 menyebut bagian tersebut digunakan.

E. Field Naratif yang Tidak Boleh Kosong
Field berikut wajib diisi:
- materialContext
- profileAndLearningDirection.graduateProfiles[].description
- profileAndLearningDirection.interdisciplinaryIntegration.relatedDiscipline
- profileAndLearningDirection.interdisciplinaryIntegration.rationale
- profileAndLearningDirection.interdisciplinaryIntegration.integrationForm
- profileAndLearningDirection.interdisciplinaryIntegration.notes
- profileAndLearningDirection.learningObjectives
- profileAndLearningDirection.essentialQuestion
- learningDesign.pedagogicalPractice.description
- learningDesign.pedagogicalPractice.forms[].name
- learningDesign.pedagogicalPractice.forms[].description
- learningDesign.partnership.items[].partner
- learningDesign.partnership.items[].partnerRole
- learningDesign.partnership.notes
- learningDesign.digitalUse.items[].sourceOrPlatform
- learningDesign.digitalUse.items[].function
- learningDesign.digitalUse.notes
- learningDesign.resources[].name
- learningDesign.resources[].function
- meetingActivities.overview
- semua field utama di setiap meeting
- assessment.summative.provision
- assessment.summative.description
- assessment.summative.sampleTasks
- assessment.summative.criteria
- assessment.summative.achievementLevels
- rubric.criteria
- followUp
- teacherReflection
- completionChecklist
- finalFlowSummary

F. Kedalaman Narasi Minimal
- materialContext: 1 paragraf, 3 kalimat.
- graduateProfiles.description: 1 kalimat konkret tentang perilaku murid.
- interdisciplinaryIntegration.rationale: 3-4 kalimat.
- interdisciplinaryIntegration.integrationForm: 2-3 kalimat.
- interdisciplinaryIntegration.notes: 2 kalimat.
- pedagogicalPractice.description: 4 kalimat.
- pedagogicalPractice.forms[].description: 2 kalimat.
- partnership.items[].partnerRole: 2-3 kalimat.
- partnership.notes: 2 kalimat.
- digitalUse.items[].function: 2 kalimat.
- digitalUse.notes: 2 kalimat.
- resources[].function: 2 kalimat.
- meetingActivities.overview: 1 paragraf, 3-4 kalimat.
- meetings[].introParagraph: 1 paragraf, 3 kalimat.
- diagnostic.step1Description: 3-4 kalimat.
- diagnostic.step2Description: 3-4 kalimat.
- understanding.step4Description: 3-4 kalimat.
- understanding.step5Description: 3-4 kalimat.
- applying.step6Description: 3-4 kalimat.
- applying.step7Description: 3-4 kalimat.
- reflecting.description: 2 kalimat.
- reflecting.step8Description: 3-4 kalimat.
- formativeAssessment.step9Description: 2-3 kalimat.
- assessment.summative.provision: 2-3 kalimat.
- assessment.summative.description: 2-3 kalimat.
- assessment.summative.sampleTasks: 3-5 butir.
- assessment.summative.criteria: 4-5 butir.
- rubric.criteria: 3-5 kriteria.
- followUp.description: 2-3 kalimat.
- completionChecklist: 4-6 item.
- finalFlowSummary: 2-3 kalimat.

G. Lintas Disiplin
- relatedDiscipline diambil dari Stage 2 jika tersedia.
- rationale menjelaskan alasan disiplin terkait relevan dengan pembelajaran.
- integrationForm menjelaskan bentuk integrasi lintas disiplin dalam kegiatan belajar, produk akhir, komunikasi hasil, atau penggunaan teknologi sesuai Stage 3.
- notes menjelaskan bahwa lintas disiplin bersifat pendukung, sedangkan kompetensi utama tetap berada pada mata pelajaran utama.
- Jangan menambah disiplin lain yang tidak ada pada Stage 2 atau Stage 3.

H. Struktur Meeting Activities
meetingActivities harus berisi:
1. overview
2. meetings dengan jumlah sama seperti identity.meetingCount

Setiap meeting wajib berisi:
- meetingOrder
- meetingTitle
- duration
- introParagraph
- focus
- target
- diagnostic
- understanding
- applying
- reflecting
- formativeAssessment

Aturan isi meeting:
- meetingTitle boleh mengikuti Stage 4 jika tersedia.
- duration mengikuti alokasi per pertemuan dari Stage 1.
- focus dan target mengikuti tujuan pembelajaran Stage 2.
- applying.product mengikuti finalStudentProduct Stage 3.
- differentiation mengikuti differentiationPlan Stage 3.
- formativeAssessment.technique mengikuti Stage 4.
- formativeAssessment.step9Description harus sesuai teknik Stage 4 dan aktivitas pertemuan.

I. Struktur Diagnostik
Setiap diagnostic wajib berisi:
- step1Description: cara guru melakukan cek kesiapan awal, alat atau media yang digunakan, cara murid menjawab, dan tujuan diagnostik.
- sampleQuestion: contoh soal sesuai materi pertemuan.
- answerOptions: pilihan A dan B jika sesuai.
- correctAnswer: jawaban tepat dan alasan singkat.
- step2Description: cara guru membaca hasil jawaban dan membentuk kelompok sementara.
- teacherNotes: kelompok A/B bersifat sementara, bukan label pintar/kurang pintar.

J. Struktur Memahami
Setiap understanding wajib berisi:
- teacherNotes: semua murid mendapat dasar konsep yang sama.
- step4Description: guru membahas jawaban murid dan meluruskan miskonsepsi.
- step5Description: guru menguatkan konsep dengan media atau sumber daya yang relevan.
- triggerQuestions: 3-4 pertanyaan pemantik.

K. Struktur Mengaplikasi
Setiap applying wajib berisi:
- step6Description: murid mulai mengerjakan mini-PjBL atau tugas aplikasi.
- differentiation.supportGroup: bantuan untuk murid yang membutuhkan dukungan.
- differentiation.advancedGroup: tantangan untuk murid yang lebih siap.
- step7Description: penyelesaian produk/kinerja dan persiapan penyampaian hasil.
- flowSummary: 3-4 butir alur kegiatan.
- product: produk akhir dari Stage 3.

L. Struktur Merefleksi
Setiap reflecting wajib berisi:
- description
- step8Description
- reflectionQuestions berisi 3-4 pertanyaan refleksi.

M. Struktur Asesmen
- Asesmen formatif hanya berada pada meetings[].formativeAssessment.
- assessment hanya berisi summative.
- Jangan membuat assessment.formative.
- assessment.summative harus berisi provision, description, sampleTasks, criteria, dan achievementLevels.
- rubric, followUp, teacherReflection, completionChecklist, dan finalFlowSummary harus berada di root-level contentJson, sejajar dengan assessment.
- Jangan memasukkan rubric, followUp, teacherReflection, completionChecklist, atau finalFlowSummary ke dalam assessment.
- Rubrik, tindak lanjut, refleksi guru, checklist, dan ringkasan akhir harus nyambung dengan tujuan pembelajaran, produk akhir, dan asesmen.
""".strip()

    def _build_source_data(
        self,
        payload: GenerateRppRequest,
        references: list[Any],
    ) -> dict[str, Any]:
        dummy_onboarding = get_intra_dummy_onboarding_content()

        school = self._dump(payload.school) or dummy_onboarding.get("school", {})
        teacher_profile = self._dump(payload.teacherProfile) or dummy_onboarding.get("teacherProfile", {})
        teacher_class = self._dump(payload.teacherClass) or dummy_onboarding.get("teacherClass", {})
        teacher_subject = self._dump(payload.teacherSubject) or dummy_onboarding.get("teacherSubject", {})

        onboarding = {
            "school": school,
            "teacherProfile": teacher_profile,
            "teacherClass": teacher_class,
            "teacherSubject": teacher_subject,
        }

        stages_by_number = {
            1: get_intra_dummy_stage_content(1),
            2: get_intra_dummy_stage_content(2),
            4: get_intra_dummy_stage_content(4),
        }

        for stage in payload.stages or []:
            if stage.contentJson:
                stages_by_number[stage.stageNumber] = stage.contentJson

        stage3_from_stages = stages_by_number.get(3, {}) or {}
        stage3_from_summary = self._as_dict(payload.kinaChatSummary)
        stage3 = stage3_from_stages or stage3_from_summary

        locked_decisions_from_stage3 = {
            "discussionSummary": stage3.get("discussionSummary", ""),
            "learningStrategy": stage3.get("learningStrategy", ""),
            "pedagogicalApproach": stage3.get("pedagogicalApproach", ""),
            "facilityAndTechnologyUse": stage3.get("facilityAndTechnologyUse", ""),
            "digitalPlatform": stage3.get("digitalPlatform", ""),
            "partnership": stage3.get("partnership", ""),
            "finalStudentProduct": stage3.get("finalStudentProduct", ""),
            "activityFlowDecision": stage3.get("activityFlowDecision", {}),
            "differentiationPlan": stage3.get("differentiationPlan", {}),
            "teacherNotes": stage3.get("teacherNotes", ""),
        }

        return {
            "onboarding": onboarding,
            "stage1_basicContext": stages_by_number.get(1, {}),
            "stage2_curriculumFoundation": stages_by_number.get(2, {}),
            "stage3_learningStrategyFromKina": stage3,
            "lockedDecisionsFromStage3": locked_decisions_from_stage3,
            "stage4_formativeAssessment": stages_by_number.get(4, {}),
            "kinaChatSummary": payload.kinaChatSummary,
            "ragReferences": [reference.model_dump() for reference in references],
        }

    def _empty_response_shape(
        self,
        payload: GenerateRppRequest,
        source_data: dict[str, Any],
    ) -> dict[str, Any]:
        onboarding = source_data.get("onboarding") or {}
        school = onboarding.get("school") or {}
        teacher_profile = onboarding.get("teacherProfile") or {}
        teacher_class = onboarding.get("teacherClass") or {}
        teacher_subject = onboarding.get("teacherSubject") or {}
        stage1 = source_data.get("stage1_basicContext") or {}
        stage2 = source_data.get("stage2_curriculumFoundation") or {}

        return {
            "title": payload.project.title or "",
            "identity": {
                "schoolName": school.get("schoolName", ""),
                "teacherName": teacher_profile.get("teacherName", ""),
                "educationLevel": school.get("educationLevel", stage1.get("jenjangPendidikan", "")),
                "phase": teacher_class.get("phase", payload.project.phase or stage1.get("fase", "")),
                "gradeLevel": teacher_class.get("gradeLevel", payload.project.gradeLevel or stage1.get("kelas", "")),
                "subject": teacher_subject.get("subject", payload.project.subject or stage1.get("mataPelajaran", "")),
                "topic": stage1.get("topikMateriPokok", ""),
                "element": self._infer_element(stage1, stage2),
                "timeAllocation": stage1.get("durasiPembelajaran", ""),
                "meetingCount": str(stage1.get("jumlahPertemuan", "")),
                "academicYear": school.get("academicYear", ""),
                "rppType": payload.project.rppType,
            },
            "materialContext": "",
            "profileAndLearningDirection": {
                "graduateProfiles": self._build_graduate_profile_shape(stage2),
                "interdisciplinaryIntegration": {
                    "relatedDiscipline": self._join_list(stage2.get("mataPelajaranLintasDisiplin")),
                    "rationale": "",
                    "integrationForm": "",
                    "notes": "",
                },
                "learningObjectives": self._build_learning_objectives(stage2),
                "essentialQuestion": stage2.get("pertanyaanPemantik", ""),
            },
            "learningDesign": {
                "pedagogicalPractice": {
                    "description": "",
                    "forms": [
                        {
                            "name": "",
                            "description": "",
                        }
                    ],
                },
                "partnership": {
                    "items": [],
                    "notes": "",
                },
                "digitalUse": {
                    "items": [],
                    "notes": "",
                },
                "resources": [],
            },
            "meetingActivities": {
                "overview": "",
                "meetings": self._build_meeting_shape(source_data),
            },
            "assessment": {
                "summative": {
                    "provision": "",
                    "description": "",
                    "sampleTasks": [],
                    "criteria": [],
                    "achievementLevels": [
                        {
                            "level": "Perlu Bimbingan",
                            "description": "",
                            "followUp": "",
                        },
                        {
                            "level": "Cukup",
                            "description": "",
                            "followUp": "",
                        },
                        {
                            "level": "Baik",
                            "description": "",
                            "followUp": "",
                        },
                        {
                            "level": "Sangat Baik",
                            "description": "",
                            "followUp": "",
                        },
                    ],
                },
            },
            "rubric": {
                "criteria": [
                    {
                        "criterion": "",
                        "excellent": "",
                        "good": "",
                        "needsSupport": "",
                    }
                ],
            },
            "followUp": {
                "description": "",
                "notYetAchieved": "",
                "almostAchieved": "",
                "achieved": "",
                "exceeding": "",
                "enrichmentExample": "",
            },
            "teacherReflection": {
                "description": "",
                "questions": [
                    "Apakah tujuan pembelajaran tercapai?",
                    "Bagian mana yang paling efektif?",
                    "Bagian mana yang perlu diperbaiki?",
                    "Apakah asesmen diagnostik membantu menentukan kebutuhan belajar murid?",
                    "Bagaimana respons murid terhadap kegiatan mini proyek?",
                    "Apakah asesmen formatif memberi informasi yang cukup untuk tindak lanjut?",
                    "Apa perbaikan untuk RPP berikutnya?",
                ],
            },
            "completionChecklist": [
                {
                    "item": "",
                    "status": "",
                }
            ],
            "finalFlowSummary": "",
        }

    def _build_graduate_profile_shape(self, stage2: dict[str, Any]) -> list[dict[str, str]]:
        dimensions = stage2.get("dimensiProfilLulusan") or []

        if not isinstance(dimensions, list) or not dimensions:
            return [
                {
                    "dimension": "",
                    "description": "",
                }
            ]

        return [
            {
                "dimension": str(dimension),
                "description": "",
            }
            for dimension in dimensions
        ]

    def _build_learning_objectives(self, stage2: dict[str, Any]) -> list[str]:
        selected = stage2.get("tujuanPembelajaranTerpilih")

        if isinstance(selected, list) and selected:
            return [self._ensure_murid_mampu(str(item)) for item in selected]

        atp = stage2.get("alurTujuanPembelajaran")

        if isinstance(atp, list):
            objectives: list[str] = []

            for item in atp:
                if isinstance(item, dict) and item.get("selected") is True:
                    objective = item.get("tujuanPembelajaran")
                    if objective:
                        objectives.append(self._ensure_murid_mampu(str(objective)))

            if objectives:
                return objectives

        return []

    def _build_meeting_shape(self, source_data: dict[str, Any]) -> list[dict[str, Any]]:
        stage1 = source_data.get("stage1_basicContext") or {}
        stage4 = source_data.get("stage4_formativeAssessment") or {}

        meeting_count = int(stage1.get("jumlahPertemuan") or 1)
        stage4_meetings = stage4.get("meetings") or []
        duration = self._extract_meeting_duration(str(stage1.get("durasiPembelajaran", "")))

        meetings: list[dict[str, Any]] = []

        for index in range(meeting_count):
            stage4_item = stage4_meetings[index] if index < len(stage4_meetings) else {}

            meetings.append(
                {
                    "meetingOrder": index + 1,
                    "meetingTitle": str(stage4_item.get("meetingTitle", "")),
                    "duration": duration,
                    "introParagraph": "",
                    "focus": "",
                    "target": "",
                    "diagnostic": {
                        "step1Description": "",
                        "sampleQuestion": "",
                        "answerOptions": [],
                        "correctAnswer": "",
                        "step2Description": "",
                        "teacherNotes": "",
                    },
                    "understanding": {
                        "teacherNotes": "",
                        "step4Description": "",
                        "step5Description": "",
                        "triggerQuestions": [],
                    },
                    "applying": {
                        "step6Description": "",
                        "differentiation": {
                            "supportGroup": "",
                            "advancedGroup": "",
                        },
                        "step7Description": "",
                        "flowSummary": [],
                        "product": "",
                    },
                    "reflecting": {
                        "description": "",
                        "step8Description": "",
                        "reflectionQuestions": [],
                    },
                    "formativeAssessment": {
                        "technique": str(stage4_item.get("selectedTechniqueLabel") or stage4_item.get("selectedTechnique") or ""),
                        "step9Description": str(stage4_item.get("description", "")),
                        "observedIndicators": [],
                        "teacherRecordFormat": "",
                    },
                }
            )

        return meetings

    def _enforce_stage1_stage2_stage4_structure(
        self,
        content: dict[str, Any],
        source_data: dict[str, Any],
    ) -> dict[str, Any]:
        stage1 = source_data.get("stage1_basicContext") or {}
        stage2 = source_data.get("stage2_curriculumFoundation") or {}

        identity = content.setdefault("identity", {})
        identity["topic"] = stage1.get("topikMateriPokok", identity.get("topic", ""))
        identity["element"] = self._infer_element(stage1, stage2)
        identity["timeAllocation"] = stage1.get("durasiPembelajaran", identity.get("timeAllocation", ""))
        identity["meetingCount"] = str(stage1.get("jumlahPertemuan", identity.get("meetingCount", "")))

        profile = content.setdefault("profileAndLearningDirection", {})

        generated_profiles = profile.get("graduateProfiles") or []
        profile["graduateProfiles"] = self._merge_graduate_profiles(
            stage2=stage2,
            generated_profiles=generated_profiles,
        )

        interdisciplinary = profile.setdefault("interdisciplinaryIntegration", {})
        if not interdisciplinary.get("relatedDiscipline"):
            interdisciplinary["relatedDiscipline"] = self._join_list(stage2.get("mataPelajaranLintasDisiplin"))

        objectives = self._build_learning_objectives(stage2)
        if objectives:
            profile["learningObjectives"] = objectives

        if not profile.get("essentialQuestion"):
            profile["essentialQuestion"] = stage2.get("pertanyaanPemantik", "")

        return content

    def _merge_graduate_profiles(
        self,
        stage2: dict[str, Any],
        generated_profiles: list[Any],
    ) -> list[dict[str, str]]:
        dimensions = stage2.get("dimensiProfilLulusan") or []

        if not isinstance(dimensions, list) or not dimensions:
            return generated_profiles if isinstance(generated_profiles, list) else []

        generated_by_dimension: dict[str, dict[str, Any]] = {}

        if isinstance(generated_profiles, list):
            for item in generated_profiles:
                if isinstance(item, dict):
                    dimension = str(item.get("dimension", "")).strip()
                    if dimension:
                        generated_by_dimension[dimension.lower()] = item

        merged: list[dict[str, str]] = []

        for dimension in dimensions:
            dimension_text = str(dimension)
            generated_item = generated_by_dimension.get(dimension_text.lower(), {})
            description = str(generated_item.get("description", "")).strip()

            if not description:
                description = (
                    f"Murid mengembangkan dimensi {dimension_text} melalui kegiatan memahami konsep, "
                    "berdiskusi, mengerjakan tugas aplikasi, dan merefleksikan proses belajar."
                )

            merged.append(
                {
                    "dimension": dimension_text,
                    "description": description,
                }
            )

        return merged

    def _enforce_stage3_learning_design(
        self,
        content: dict[str, Any],
        source_data: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(content, dict):
            return content

        learning_design = content.setdefault("learningDesign", {})

        learning_design["partnership"] = self._stage3_partnership(source_data)
        learning_design["digitalUse"] = self._stage3_digital_use(source_data)
        learning_design["resources"] = self._stage3_resources(source_data)

        return content

    def _stage3_partnership(self, source_data: dict[str, Any]) -> dict[str, Any]:
        stage3 = source_data.get("stage3_learningStrategyFromKina") or {}
        locked = source_data.get("lockedDecisionsFromStage3") or {}

        partnership_text = str(stage3.get("partnership") or locked.get("partnership") or "")
        partners = self._extract_partner_items(partnership_text)

        items = [
            {
                "partner": partner,
                "partnerRole": (
                    f"{partner} berperan sebagai mitra pendukung sesuai hasil diskusi Stage 3. "
                    "Peran mitra membantu bagian pembelajaran yang relevan dengan kebutuhan kegiatan, tanpa menggantikan peran guru utama."
                ),
            }
            for partner in partners
        ]

        return {
            "items": items,
            "notes": (
                "Kemitraan digunakan sesuai keputusan Stage 3 dan bersifat mendukung pelaksanaan pembelajaran. "
                "Guru utama tetap menjadi pengarah kegiatan, sedangkan mitra membantu aspek tertentu yang relevan."
                if items
                else ""
            ),
        }

    def _stage3_digital_use(self, source_data: dict[str, Any]) -> dict[str, Any]:
        stage3 = source_data.get("stage3_learningStrategyFromKina") or {}
        locked = source_data.get("lockedDecisionsFromStage3") or {}

        digital_text = str(stage3.get("digitalPlatform") or locked.get("digitalPlatform") or "")
        platforms = self._extract_stage3_items(digital_text)

        items = [
            {
                "sourceOrPlatform": platform,
                "linkOrAccess": "",
                "function": (
                    f"{platform} digunakan sebagai media atau platform digital sesuai keputusan Stage 3. "
                    "Penggunaannya mendukung penyampaian materi, proses kerja murid, atau penyajian produk akhir pembelajaran."
                ),
            }
            for platform in platforms
        ]

        return {
            "items": items,
            "notes": (
                "Pemanfaatan digital mengikuti keputusan Stage 3 dan digunakan sebagai pendukung pembelajaran. "
                "Media digital ditempatkan pada tahap kegiatan yang relevan agar membantu pemahaman atau penyajian hasil belajar murid."
                if items
                else ""
            ),
        }

    def _stage3_resources(self, source_data: dict[str, Any]) -> list[dict[str, str]]:
        stage3 = source_data.get("stage3_learningStrategyFromKina") or {}
        locked = source_data.get("lockedDecisionsFromStage3") or {}

        resource_text = str(stage3.get("facilityAndTechnologyUse") or locked.get("facilityAndTechnologyUse") or "")
        resources = self._extract_stage3_items(resource_text)

        return [
            {
                "name": resource,
                "function": (
                    f"{resource} digunakan sebagai sumber daya pembelajaran sesuai keputusan Stage 3. "
                    "Sumber daya ini membantu guru dan murid menjalankan kegiatan inti, penyampaian materi, atau penyajian hasil belajar secara lebih terarah."
                ),
            }
            for resource in resources
        ]

    def _extract_partner_items(self, text: str) -> list[str]:
        if not self._has_real_value(text):
            return []

        sentences = self._split_stage3_sentences(text)
        results: list[str] = []

        for sentence in sentences:
            candidate = sentence

            connector_match = re.search(
                r"\b(?:dengan|bersama|melibatkan|mengundang|berkolaborasi dengan|bekerja sama dengan)\b\s+(.+)",
                candidate,
                flags=re.IGNORECASE,
            )

            if connector_match:
                candidate = connector_match.group(1)

            candidate = self._cut_after_context_words(candidate)
            parts = self._split_stage3_items(candidate)

            for part in parts:
                label = self._clean_stage3_label(part)
                if self._looks_like_stage3_item(label):
                    results.append(label)

        return self._unique_keep_order(results)

    def _extract_stage3_items(self, text: str) -> list[str]:
        if not self._has_real_value(text):
            return []

        sentences = self._split_stage3_sentences(text)
        results: list[str] = []

        for sentence in sentences:
            candidates: list[str] = []

            before_usage = re.match(
                r"(.+?)\s+\b(?:digunakan|dipakai|dimanfaatkan|berfungsi)\b",
                sentence,
                flags=re.IGNORECASE,
            )

            if before_usage:
                candidates.append(before_usage.group(1))

            after_usage = re.search(
                r"\b(?:menggunakan|memanfaatkan|melalui|dengan)\b\s+(.+?)(?:\s+\b(?:sebagai|untuk|agar|guna|dalam|pada|yang)\b|,|$)",
                sentence,
                flags=re.IGNORECASE,
            )

            if after_usage:
                candidates.append(after_usage.group(1))

            before_for = re.match(
                r"(.+?)\s+\b(?:untuk|sebagai)\b",
                sentence,
                flags=re.IGNORECASE,
            )

            if before_for:
                candidates.append(before_for.group(1))

            if not candidates:
                candidates.append(sentence)

            for candidate in candidates:
                candidate = self._cut_after_context_words(candidate)
                parts = self._split_stage3_items(candidate)

                for part in parts:
                    label = self._clean_stage3_label(part)
                    if self._looks_like_stage3_item(label):
                        results.append(label)

        return self._unique_keep_order(results)

    def _split_stage3_sentences(self, text: str) -> list[str]:
        return [
            re.sub(r"^(dan|serta|kemudian)\s+", "", sentence.strip(), flags=re.IGNORECASE)
            for sentence in re.split(r"[.;\n]+", text)
            if sentence.strip()
        ]

    def _split_stage3_items(self, text: str) -> list[str]:
        return [
            item.strip()
            for item in re.split(r",|\s+dan\s+|\s+serta\s+|&", text, flags=re.IGNORECASE)
            if item.strip()
        ]

    def _cut_after_context_words(self, text: str) -> str:
        return re.split(
            r"\b(?:sebagai|untuk|agar|guna|dalam rangka|yang bertugas|yang berperan|yang digunakan|yang dipakai)\b",
            text,
            maxsplit=1,
            flags=re.IGNORECASE,
        )[0].strip()

    def _clean_stage3_label(self, value: str) -> str:
        label = str(value or "").strip()
        label = label.strip(" .,:;/-")
        label = re.sub(
            r"^(media|platform|aplikasi|alat|bahan|fasilitas|sumber daya|menggunakan|memanfaatkan|akan|murid)\s+",
            "",
            label,
            flags=re.IGNORECASE,
        )
        label = re.sub(r"\s+", " ", label)
        return label.strip()

    def _looks_like_stage3_item(self, value: str) -> bool:
        label = str(value or "").strip()

        if not label:
            return False

        if len(label) <= 1:
            return False

        if len(label.split()) > 8:
            return False

        if re.search(
            r"\b(?:digunakan|dipakai|dimanfaatkan|memanfaatkan|menggunakan|berfungsi|menampilkan|menyampaikan)\b",
            label,
            flags=re.IGNORECASE,
        ):
            return False

        return True

    def _unique_keep_order(self, values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []

        for value in values:
            cleaned = value.strip()
            key = cleaned.lower()

            if key and key not in seen:
                seen.add(key)
                result.append(cleaned)

        return result

    def _infer_element(self, stage1: dict[str, Any], stage2: dict[str, Any]) -> str:
        for key in ("elemen", "element", "domain", "domainMateri"):
            value = stage2.get(key) or stage1.get(key)
            if value:
                return str(value)

        text = " ".join(
            [
                str(stage1.get("topikMateriPokok", "")),
                str(stage2.get("capaianPembelajaran", "")),
                self._join_list(stage2.get("tujuanPembelajaranTerpilih")),
            ]
        ).lower()

        if any(keyword in text for keyword in ["polinomial", "aljabar", "variabel", "koefisien", "konstanta", "suku"]):
            return "Aljabar"

        if any(keyword in text for keyword in ["bilangan", "pecahan", "desimal", "persen"]):
            return "Bilangan"

        return ""

    def _extract_meeting_duration(self, duration_text: str) -> str:
        lower_text = duration_text.lower()

        if "35" in lower_text:
            return "35 menit"
        if "40" in lower_text:
            return "40 menit"
        if "45" in lower_text:
            return "45 menit"
        if "80" in lower_text:
            return "80 menit"

        return duration_text

    def _ensure_murid_mampu(self, text: str) -> str:
        cleaned = str(text or "").strip()

        if not cleaned:
            return ""

        if cleaned.startswith("Murid mampu"):
            return cleaned

        if cleaned.startswith("Peserta didik mampu"):
            return cleaned.replace("Peserta didik mampu", "Murid mampu", 1)

        if cleaned.startswith("Siswa mampu"):
            return cleaned.replace("Siswa mampu", "Murid mampu", 1)

        return f"Murid mampu {cleaned[0].lower() + cleaned[1:] if cleaned else cleaned}"

    def _join_list(self, value: Any) -> str:
        if isinstance(value, list):
            return ", ".join(str(item) for item in value if str(item).strip())
        if value is None:
            return ""
        return str(value)

    def _has_real_value(self, value: Any) -> bool:
        text = str(value or "").strip().lower()

        if not text:
            return False

        negative_phrases = [
            "tidak digunakan",
            "tidak ada",
            "tanpa",
            "belum digunakan",
            "tidak melibatkan",
        ]

        return not any(phrase in text for phrase in negative_phrases)

    def _as_dict(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {}

        if hasattr(value, "model_dump"):
            value = value.model_dump()

        if isinstance(value, dict):
            if isinstance(value.get("contentJson"), dict):
                return value.get("contentJson") or {}
            return value

        if isinstance(value, str):
            try:
                parsed = json.loads(value)
                if isinstance(parsed, dict):
                    if isinstance(parsed.get("contentJson"), dict):
                        return parsed.get("contentJson") or {}
                    return parsed
            except json.JSONDecodeError:
                return {}

        return {}

    def _normalize_generated_text(self, content: dict[str, Any]) -> dict[str, Any]:
        content_text = json.dumps(content, ensure_ascii=False)
        content_text = content_text.replace("Siswa", "Murid")
        content_text = content_text.replace("siswa", "murid")
        content_text = content_text.replace("Peserta didik", "Murid")
        content_text = content_text.replace("peserta didik", "murid")
        content_text = content_text.replace("â", "-")
        content_text = content_text.replace("—", "-")
        return json.loads(content_text)

    def _normalize_output_structure(self, content: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(content, dict):
            return content

        assessment = content.get("assessment")

        if isinstance(assessment, dict):
            misplaced_root_keys = [
                "rubric",
                "followUp",
                "teacherReflection",
                "completionChecklist",
                "finalFlowSummary",
            ]

            for key in misplaced_root_keys:
                misplaced_value = assessment.get(key)

                if not self._is_empty_value(misplaced_value):
                    current_root_value = content.get(key)

                    if self._is_empty_value(current_root_value):
                        content[key] = misplaced_value

                if key in assessment:
                    assessment.pop(key, None)

            summative = assessment.get("summative") or {}
            content["assessment"] = {
                "summative": summative,
            }

        if self._is_empty_value(content.get("rubric")):
            content["rubric"] = {
                "criteria": []
            }

        if self._is_empty_value(content.get("followUp")):
            content["followUp"] = {
                "description": "",
                "notYetAchieved": "",
                "almostAchieved": "",
                "achieved": "",
                "exceeding": "",
                "enrichmentExample": "",
            }

        if self._is_empty_value(content.get("teacherReflection")):
            content["teacherReflection"] = {
                "description": "",
                "questions": []
            }

        if self._is_empty_value(content.get("completionChecklist")):
            content["completionChecklist"] = []

        if self._is_empty_value(content.get("finalFlowSummary")):
            content["finalFlowSummary"] = ""

        return content

    def _is_empty_value(self, value: Any) -> bool:
        if value is None:
            return True

        if isinstance(value, str):
            return not value.strip()

        if isinstance(value, list):
            if not value:
                return True
            return all(self._is_empty_value(item) for item in value)

        if isinstance(value, dict):
            if not value:
                return True
            return all(self._is_empty_value(item) for item in value.values())

        return False

    def _append_list_items(self, lines: list[str], items: Any, prefix: str = "-") -> None:
        if not isinstance(items, list):
            return

        for item in items:
            if isinstance(item, dict):
                label = item.get("label") or item.get("option") or item.get("answer") or item.get("text") or ""
                value = item.get("value") or item.get("description") or item.get("content") or ""
                text = f"{label}. {value}" if label and value else str(label or value)
                if text.strip():
                    lines.append(f"{prefix} {text}")
            else:
                text = str(item).strip()
                if text:
                    lines.append(f"{prefix} {text}")

    def _to_markdown(self, content: dict[str, Any]) -> str:
        title = content.get("title") or "RPP Pembelajaran"
        lines = [f"# {title}", ""]

        identity = content.get("identity") or {}
        lines.extend(["## A. Identitas Pembelajaran"])
        for key, value in identity.items():
            lines.append(f"- {key}: {value}")

        lines.extend(["", "### Konteks Materi"])
        lines.append(str(content.get("materialContext", "")))

        profile = content.get("profileAndLearningDirection") or {}
        lines.extend(["", "## B. Profil dan Arah Pembelajaran"])

        lines.append("### 1. Profil Lulusan yang Dikembangkan")
        for item in profile.get("graduateProfiles") or []:
            lines.append(f"- **{item.get('dimension', '')}**: {item.get('description', '')}")

        lines.append("")
        lines.append("### 2. Lintas Disiplin Ilmu")
        interdisciplinary = profile.get("interdisciplinaryIntegration") or {}
        lines.append(f"- Disiplin ilmu terkait: {interdisciplinary.get('relatedDiscipline', '')}")
        lines.append(f"- Alasan keterkaitan: {interdisciplinary.get('rationale', '')}")
        lines.append(f"- Bentuk integrasi: {interdisciplinary.get('integrationForm', '')}")
        lines.append(f"- Catatan: {interdisciplinary.get('notes', '')}")

        lines.append("")
        lines.append("### 3. Tujuan Pembelajaran")
        for objective in profile.get("learningObjectives") or []:
            lines.append(f"- {objective}")

        if profile.get("essentialQuestion"):
            lines.append("")
            lines.append(f"Pertanyaan pemantik: {profile.get('essentialQuestion')}")

        learning_design = content.get("learningDesign") or {}
        lines.extend(["", "## C. Desain Pembelajaran"])

        pedagogical = learning_design.get("pedagogicalPractice") or {}
        lines.append("### 1. Praktik Pedagogis")
        lines.append(str(pedagogical.get("description", "")))
        for item in pedagogical.get("forms") or []:
            lines.append(f"- **{item.get('name', '')}**: {item.get('description', '')}")

        partnership = learning_design.get("partnership") or {}
        lines.append("")
        lines.append("### 2. Kemitraan Pembelajaran")
        for item in partnership.get("items") or []:
            partner = item.get("partner", "")
            role = item.get("partnerRole", "")
            if partner or role:
                lines.append(f"- **{partner}**: {role}")
        lines.append(str(partnership.get("notes", "")))

        digital = learning_design.get("digitalUse") or {}
        lines.append("")
        lines.append("### 3. Pemanfaatan Digital")
        for item in digital.get("items") or []:
            source = item.get("sourceOrPlatform", "")
            access = item.get("linkOrAccess", "")
            function = item.get("function", "")
            if source or function:
                lines.append(f"- **{source}**: {function}")
            if access:
                lines.append(f"  Akses: {access}")
        lines.append(str(digital.get("notes", "")))

        lines.append("")
        lines.append("### 4. Sumber Daya")
        for item in learning_design.get("resources") or []:
            lines.append(f"- **{item.get('name', '')}**: {item.get('function', '')}")

        meeting_activities = content.get("meetingActivities") or {}
        lines.extend(["", "## D. Rangkaian Kegiatan Pembelajaran per Pertemuan"])
        lines.append(str(meeting_activities.get("overview", "")))

        for meeting in meeting_activities.get("meetings") or []:
            lines.append("")
            lines.append(f"### D.{meeting.get('meetingOrder', '')} {meeting.get('meetingTitle', '')}")
            lines.append(str(meeting.get("introParagraph", "")))
            lines.append(f"- **Fokus Pertemuan:** {meeting.get('focus', '')}")
            lines.append(f"- **Target Pertemuan:** {meeting.get('target', '')}")

            diagnostic = meeting.get("diagnostic") or {}
            lines.append("")
            lines.append("#### 1. Analisis Diagnostik / Cek Kesiapan Awal")
            lines.append(str(diagnostic.get("step1Description") or diagnostic.get("description") or ""))

            if diagnostic.get("sampleQuestion"):
                lines.append("")
                lines.append("**Contoh Soal Diagnostik Berbasis Kertas**")
                lines.append(str(diagnostic.get("sampleQuestion")))

            self._append_list_items(lines, diagnostic.get("answerOptions") or [])

            if diagnostic.get("correctAnswer"):
                lines.append(f"Jawaban yang diharapkan: {diagnostic.get('correctAnswer')}")

            if diagnostic.get("step2Description"):
                lines.append(str(diagnostic.get("step2Description")))

            if diagnostic.get("teacherNotes"):
                lines.append(f"Catatan penting untuk guru: {diagnostic.get('teacherNotes')}")

            understanding = meeting.get("understanding") or {}
            lines.append("")
            lines.append("#### 2. Memahami")

            if understanding.get("teacherNotes"):
                lines.append(f"Catatan penting untuk guru: {understanding.get('teacherNotes')}")

            lines.append(str(understanding.get("step4Description") or understanding.get("description") or ""))

            if understanding.get("step5Description"):
                lines.append(str(understanding.get("step5Description")))

            if understanding.get("triggerQuestions"):
                lines.append("Pertanyaan pemantik:")
                self._append_list_items(lines, understanding.get("triggerQuestions") or [])

            applying = meeting.get("applying") or {}
            lines.append("")
            lines.append("#### 3. Mengaplikasi")
            lines.append(str(applying.get("step6Description") or applying.get("description") or ""))

            differentiation = applying.get("differentiation") or {}
            if differentiation:
                lines.append("Diferensiasi tahap aplikasi:")
                lines.append(f"- Kelompok perlu dukungan: {differentiation.get('supportGroup', '')}")
                lines.append(f"- Kelompok lebih siap: {differentiation.get('advancedGroup', '')}")

            if applying.get("step7Description"):
                lines.append(str(applying.get("step7Description")))

            if applying.get("flowSummary"):
                lines.append("Ringkasan alur mengaplikasi:")
                self._append_list_items(lines, applying.get("flowSummary") or [])

            if applying.get("product"):
                lines.append(f"Produk/kinerja yang dikumpulkan: {applying.get('product')}")

            reflecting = meeting.get("reflecting") or {}
            lines.append("")
            lines.append("#### 4. Merefleksi")
            lines.append(str(reflecting.get("description", "")))

            if reflecting.get("step8Description"):
                lines.append(str(reflecting.get("step8Description")))

            if reflecting.get("reflectionQuestions"):
                lines.append("Pertanyaan refleksi:")
                self._append_list_items(lines, reflecting.get("reflectionQuestions") or [])

            formative = meeting.get("formativeAssessment") or {}
            lines.append("")
            lines.append("#### 5. Asesmen Formatif")
            lines.append(str(formative.get("step9Description") or formative.get("description") or ""))

            if formative.get("technique"):
                lines.append(f"Teknik: {formative.get('technique')}")

            if formative.get("observedIndicators"):
                lines.append("Indikator yang diamati guru:")
                self._append_list_items(lines, formative.get("observedIndicators") or [])

            if formative.get("teacherRecordFormat"):
                lines.append(f"Bentuk catatan formatif: {formative.get('teacherRecordFormat')}")

        assessment = content.get("assessment") or {}
        summative = assessment.get("summative") or {}

        lines.extend(["", "## E. Asesmen Pembelajaran"])
        lines.append("### Asesmen Sumatif UH/UTS/UAS")

        if summative.get("provision"):
            lines.append(f"Ketentuan: {summative.get('provision')}")

        lines.append(str(summative.get("description", "")))

        lines.append("Contoh bentuk soal sumatif:")
        for task in summative.get("sampleTasks") or []:
            lines.append(f"- {task}")

        lines.append("Kriteria penilaian sumatif:")
        for criterion in summative.get("criteria") or []:
            lines.append(f"- {criterion}")

        for level in summative.get("achievementLevels") or []:
            lines.append(
                f"- **{level.get('level', '')}**: {level.get('description', '')} "
                f"Tindak lanjut: {level.get('followUp', '')}"
            )

        rubric = content.get("rubric") or {}
        lines.extend(["", "## F. Rubrik Penilaian"])
        for item in rubric.get("criteria") or []:
            lines.append(f"- **{item.get('criterion', '')}**")
            lines.append(f"  - Sangat Baik: {item.get('excellent', '')}")
            lines.append(f"  - Baik: {item.get('good', '')}")
            lines.append(f"  - Perlu Dukungan: {item.get('needsSupport', '')}")

        follow_up = content.get("followUp") or {}
        lines.extend(["", "## G. Tindak Lanjut Pembelajaran"])
        lines.append(str(follow_up.get("description", "")))
        lines.append(f"- Belum mencapai tujuan pembelajaran: {follow_up.get('notYetAchieved', '')}")
        lines.append(f"- Hampir mencapai tujuan pembelajaran: {follow_up.get('almostAchieved', '')}")
        lines.append(f"- Sudah mencapai tujuan pembelajaran: {follow_up.get('achieved', '')}")
        lines.append(f"- Melampaui tujuan pembelajaran: {follow_up.get('exceeding', '')}")
        lines.append(f"- Contoh pengayaan: {follow_up.get('enrichmentExample', '')}")

        teacher_reflection = content.get("teacherReflection") or {}
        lines.extend(["", "## H. Refleksi Guru"])
        lines.append(str(teacher_reflection.get("description", "")))
        for question in teacher_reflection.get("questions") or []:
            lines.append(f"- {question}")

        lines.extend(["", "## I. Checklist Kelengkapan RPP"])
        for item in content.get("completionChecklist") or []:
            lines.append(f"- {item.get('item', '')}: {item.get('status', '')}")

        lines.extend(["", "## Ringkasan Alur Final"])
        lines.append(str(content.get("finalFlowSummary", "")))

        return "\n".join(lines)

    def _dump(self, value: Any) -> dict[str, Any]:
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if isinstance(value, dict):
            return value
        return {}