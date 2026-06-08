from __future__ import annotations

import json
from copy import deepcopy
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

        content_json = await self._generate_content_json_in_sections(
            source_data,
            response_shape,
        )

        content_json = self._normalize_generated_text(content_json)
        content_json = self._normalize_output_structure(content_json)

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
7. strictGroundingContract adalah batas grounding yang wajib ditaati agar tidak ada input tambahan di luar Stage 1-4.

B. Prinsip Utama
1. Ikuti struktur requiredResponseShape.
2. Object kosong pada requiredResponseShape hanya contoh struktur, bukan isi final.
3. Isi semua field naratif utama berdasarkan Stage 1-4.
4. Semua isi naratif ditulis oleh LLM API berdasarkan sourceData.
5. Jangan mengembalikan shape kosong.
6. Jangan mengarang identitas, fasilitas, platform, mitra, tautan, sumber daya, produk, perangkat, atau tugas yang tidak ada pada Stage 1-4.
7. Jangan memilih hanya satu item jika sourceData berisi beberapa item.
8. Gunakan istilah "murid", bukan "siswa" atau "peserta didik".
9. learningObjectives dan target pertemuan harus diawali "Murid mampu ...".
10. Gaya bahasa harus naratif, siap ditempel ke dokumen RPP, dan tidak berupa frasa pendek.

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
- discussionSummary digunakan sebagai konteks penguat agar narasi setiap bagian saling nyambung.

D. Aturan Learning Design
- pedagogicalPractice dikembangkan dari learningStrategy dan pedagogicalApproach Stage 3.
- partnership dikembangkan dari partnership Stage 3.
- digitalUse dikembangkan dari digitalPlatform Stage 3.
- resources dikembangkan dari facilityAndTechnologyUse Stage 3.
- partnership hanya memuat mitra pembelajaran.
- digitalUse hanya memuat media, aplikasi, sumber digital, atau platform digital.
- resources hanya memuat alat, bahan, fasilitas, atau sumber daya fisik yang disebut eksplisit pada Stage 3 field facilityAndTechnologyUse.
- Jangan memasukkan alat fisik ke digitalUse jika alat tersebut dijelaskan pada facilityAndTechnologyUse.
- Jangan memasukkan media/platform digital ke resources jika media tersebut dijelaskan pada digitalPlatform.
- Jangan menurunkan resources dari digitalPlatform.
- Jika digitalPlatform menyebut media digital atau platform digital, media tersebut masuk ke digitalUse, bukan otomatis membuat perangkat akses seperti gawai, HP, laptop, komputer, internet, atau WiFi masuk ke resources.
- Perangkat akses seperti gawai, HP, laptop, komputer, internet, atau WiFi hanya boleh masuk resources jika disebut eksplisit pada Stage 3 field facilityAndTechnologyUse.
- Jika facilityAndTechnologyUse hanya menyebut satu sumber daya, maka resources cukup memuat sumber daya tersebut.
- Jangan menulis "tidak digunakan" pada partnership, digitalUse, atau resources apabila Stage 3 menyebut bagian tersebut digunakan.
- Jika Stage 3 menyebut lebih dari satu mitra, media digital, atau sumber daya, pisahkan menjadi beberapa item.
- Jangan menambahkan mitra, media digital, atau sumber daya baru hanya karena dianggap umum dipakai di pembelajaran.

E. Aturan Produk, Tugas, Rubrik, dan Asesmen
- finalStudentProduct Stage 3 adalah acuan utama produk/kinerja murid.
- applying.product harus mengikuti finalStudentProduct Stage 3.
- Produk akhir, tugas utama, asesmen, rubrik, dan tindak lanjut harus konsisten dengan finalStudentProduct Stage 3 dan tujuan pembelajaran Stage 2.
- Jangan menambahkan produk besar lain seperti laporan tertulis, LKPD, poster, video, infografis, makalah, atau artefak lain jika tidak disebut pada Stage 1-4.
- Asesmen boleh mengukur pemahaman murid, tetapi tidak boleh mengganti produk akhir yang sudah diputuskan di Stage 3.

F. Field Naratif yang Tidak Boleh Kosong
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
- meetings[].formativeAssessment.technique
- meetings[].formativeAssessment.step9Description
- meetings[].formativeAssessment.observedIndicators
- meetings[].formativeAssessment.teacherRecordFormat
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

G. Kedalaman Narasi Minimal
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
- formativeAssessment.observedIndicators: 3-5 butir indikator konkret.
- formativeAssessment.teacherRecordFormat: 1-2 kalimat format catatan guru.
- assessment.summative.provision: 2-3 kalimat.
- assessment.summative.description: 2-3 kalimat.
- assessment.summative.sampleTasks: 3-5 butir.
- assessment.summative.criteria: 4-5 butir.
- rubric.criteria: 3-5 kriteria.
- followUp.description: 2-3 kalimat.
- completionChecklist: 4-6 item.
- finalFlowSummary: 2-3 kalimat.

H. Lintas Disiplin
- relatedDiscipline diambil dari Stage 2 jika tersedia.
- rationale menjelaskan alasan disiplin terkait relevan dengan pembelajaran.
- integrationForm menjelaskan bentuk integrasi lintas disiplin dalam kegiatan belajar, produk akhir, komunikasi hasil, atau penggunaan teknologi sesuai Stage 3.
- notes menjelaskan bahwa lintas disiplin bersifat pendukung, sedangkan kompetensi utama tetap berada pada mata pelajaran utama.
- Jangan menambah disiplin lain yang tidak ada pada Stage 2 atau Stage 3.

I. Struktur Meeting Activities
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
- formativeAssessment.step9Description dikembangkan dari teknik Stage 4 dan aktivitas pertemuan.
- formativeAssessment.observedIndicators berisi 3-5 indikator konkret yang diamati guru sesuai fokus, target, aktivitas, dan produk/kinerja pertemuan.
- formativeAssessment.teacherRecordFormat berisi format catatan guru yang praktis sesuai teknik asesmen.

J. Struktur Diagnostik
Setiap diagnostic wajib berisi:
- step1Description: cara guru melakukan cek kesiapan awal, alat atau media yang digunakan, cara murid menjawab, dan tujuan diagnostik.
- sampleQuestion: contoh soal sesuai materi pertemuan.
- answerOptions: pilihan A dan B jika sesuai.
- correctAnswer: jawaban tepat dan alasan singkat.
- step2Description: cara guru membaca hasil jawaban dan membentuk kelompok sementara.
- teacherNotes: kelompok A/B bersifat sementara, bukan label pintar/kurang pintar.

K. Struktur Memahami
Setiap understanding wajib berisi:
- teacherNotes: semua murid mendapat dasar konsep yang sama.
- step4Description: guru membahas jawaban murid dan meluruskan miskonsepsi.
- step5Description: guru menguatkan konsep dengan media atau sumber daya yang relevan.
- triggerQuestions: 3-4 pertanyaan pemantik.

L. Struktur Mengaplikasi
Setiap applying wajib berisi:
- step6Description: murid mulai mengerjakan mini-PjBL atau tugas aplikasi.
- differentiation.supportGroup: bantuan untuk murid yang membutuhkan dukungan.
- differentiation.advancedGroup: tantangan untuk murid yang lebih siap.
- step7Description: penyelesaian produk/kinerja dan persiapan penyampaian hasil.
- flowSummary: 3-4 butir alur kegiatan.
- product: produk akhir dari Stage 3.

M. Struktur Merefleksi
Setiap reflecting wajib berisi:
- description
- step8Description
- reflectionQuestions berisi 3-4 pertanyaan refleksi.

N. Struktur Asesmen
- Asesmen formatif hanya berada pada meetings[].formativeAssessment.
- assessment hanya berisi summative.
- Jangan membuat assessment.formative.
- Setiap meetings[].formativeAssessment wajib berisi technique, step9Description, observedIndicators, dan teacherRecordFormat.
- observedIndicators wajib berisi 3-5 indikator konkret yang diamati guru.
- teacherRecordFormat wajib berisi format catatan guru yang praktis sesuai teknik asesmen.
- assessment.summative harus berisi provision, description, sampleTasks, criteria, dan achievementLevels.
- rubric, followUp, teacherReflection, completionChecklist, dan finalFlowSummary harus berada di root-level contentJson, sejajar dengan assessment.
- Jangan memasukkan rubric, followUp, teacherReflection, completionChecklist, atau finalFlowSummary ke dalam assessment.
- Rubrik, tindak lanjut, refleksi guru, checklist, dan ringkasan akhir harus nyambung dengan tujuan pembelajaran, produk akhir, dan asesmen.
""".strip()

    async def _generate_content_json_in_sections(
        self,
        source_data: dict[str, Any],
        response_shape: dict[str, Any],
    ) -> dict[str, Any]:
        content = deepcopy(response_shape)

        overview_shape = {
            "materialContext": content.get("materialContext", ""),
            "profileAndLearningDirection": content.get(
                "profileAndLearningDirection", {}
            ),
            "learningDesign": content.get("learningDesign", {}),
            "meetingActivitiesOverview": (
                content.get("meetingActivities", {}).get("overview", "")
            ),
        }
        overview = await self._generate_rpp_section(
            section_name="profil, arah, dan desain pembelajaran",
            source_data=source_data,
            response_shape=overview_shape,
            max_tokens=4500,
        )
        content["materialContext"] = str(overview.get("materialContext", ""))
        if isinstance(overview.get("profileAndLearningDirection"), dict):
            content["profileAndLearningDirection"] = overview[
                "profileAndLearningDirection"
            ]
        if isinstance(overview.get("learningDesign"), dict):
            content["learningDesign"] = overview["learningDesign"]
        if isinstance(content.get("meetingActivities"), dict):
            content["meetingActivities"]["overview"] = str(
                overview.get("meetingActivitiesOverview", "")
            )

        meetings_shape = (
            content.get("meetingActivities", {}).get("meetings", [])
            if isinstance(content.get("meetingActivities"), dict)
            else []
        )
        generated_meetings: list[dict[str, Any]] = []
        for meeting_shape in meetings_shape:
            if not isinstance(meeting_shape, dict):
                continue
            meeting_result = await self._generate_rpp_section(
                section_name=f"rangkaian kegiatan pertemuan {meeting_shape.get('meetingOrder')}",
                source_data={
                    **source_data,
                    "currentMeetingShape": meeting_shape,
                },
                response_shape={"meeting": meeting_shape},
                max_tokens=4200,
            )
            meeting = meeting_result.get("meeting")
            generated_meetings.append(meeting if isinstance(meeting, dict) else meeting_shape)

        if isinstance(content.get("meetingActivities"), dict):
            content["meetingActivities"]["meetings"] = generated_meetings

        closing_shape = {
            "assessment": content.get("assessment", {}),
            "rubric": content.get("rubric", {}),
            "followUp": content.get("followUp", {}),
            "teacherReflection": content.get("teacherReflection", {}),
            "completionChecklist": content.get("completionChecklist", []),
            "finalFlowSummary": content.get("finalFlowSummary", ""),
        }
        closing = await self._generate_rpp_section(
            section_name="asesmen, rubrik, tindak lanjut, refleksi, dan checklist",
            source_data=source_data,
            response_shape=closing_shape,
            max_tokens=4500,
        )
        for key in closing_shape:
            if key in closing:
                content[key] = closing[key]

        return content

    async def _generate_rpp_section(
        self,
        *,
        section_name: str,
        source_data: dict[str, Any],
        response_shape: dict[str, Any],
        max_tokens: int,
    ) -> dict[str, Any]:
        messages = [
            {
                "role": "system",
                "content": """
Anda adalah AI Service Petunjukku untuk menyusun satu bagian RPP Intrakurikuler.

Aturan:
- Output wajib satu JSON object valid, tanpa markdown.
- Isi semua field di requiredResponseShape sesuai sectionName.
- Gunakan istilah "murid".
- Gunakan hanya sourceData Stage 1, Stage 2, Stage 3, Stage 4, onboarding, dan project.
- Jangan menambahkan perangkat, fasilitas, aplikasi, mitra, produk, atau tugas yang tidak disebut/diturunkan langsung dari sourceData.
- learningDesign.resources hanya dari strictGroundingContract.resourcesSourceText.
- learningDesign.digitalUse hanya dari strictGroundingContract.digitalUseSourceText.
- learningDesign.partnership hanya dari strictGroundingContract.partnershipSourceText.
- Produk, rubrik, asesmen, dan tugas utama harus konsisten dengan strictGroundingContract.finalStudentProductSourceText.
- Untuk setiap formativeAssessment, observedIndicators wajib 3-5 indikator konkret dan teacherRecordFormat wajib praktis untuk guru.
""".strip(),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "sectionName": section_name,
                        "sourceData": source_data,
                        "requiredResponseShape": response_shape,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        return await self.llm_client.generate_json_strict(
            messages,
            temperature=0.05,
            max_tokens=max_tokens,
        )

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
                stages_by_number[stage.stageNumber] = self._normalize_stage_content(
                    stage.stageNumber,
                    stage.contentJson,
                )

        stage3_from_stages = stages_by_number.get(3, {}) or {}
        stage3_from_summary = self._as_dict(payload.kinaChatSummary)
        stage3 = self._merge_dicts_keep_non_empty(stage3_from_summary, stage3_from_stages)

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
            "kinaChatSummary": self._dump(payload.kinaChatSummary),
            "strictGroundingContract": {
                "identitySource": "onboarding, Stage 1, Stage 2, dan project payload.",
                "topicSource": "Stage 1.",
                "learningObjectivesSource": "Stage 2.",
                "meetingCountSource": "Stage 1.",
                "formativeAssessmentSource": "Stage 4.",
                "partnershipSourceText": locked_decisions_from_stage3["partnership"],
                "digitalUseSourceText": locked_decisions_from_stage3["digitalPlatform"],
                "resourcesSourceText": locked_decisions_from_stage3["facilityAndTechnologyUse"],
                "finalStudentProductSourceText": locked_decisions_from_stage3["finalStudentProduct"],
                "differentiationSource": locked_decisions_from_stage3["differentiationPlan"],
                "activityFlowSource": locked_decisions_from_stage3["activityFlowDecision"],
                "hardRules": [
                    "partnership hanya boleh berasal dari partnershipSourceText.",
                    "digitalUse hanya boleh berasal dari digitalUseSourceText.",
                    "resources hanya boleh berasal dari resourcesSourceText.",
                    "produk akhir, tugas utama, rubrik, dan asesmen harus konsisten dengan finalStudentProductSourceText.",
                    "jangan menambahkan perangkat, media, aplikasi, fasilitas, atau produk yang tidak disebut pada Stage 1-4.",
                    "jangan menurunkan resources dari digitalUseSourceText.",
                ],
            },
            "ragReferences": [reference.model_dump() for reference in references],
        }

    def _normalize_stage_content(
        self,
        stage_number: int,
        content: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(content, dict):
            return {}

        inputs = content.get("inputs") if isinstance(content.get("inputs"), dict) else {}
        generated = (
            content.get("generated") if isinstance(content.get("generated"), dict) else {}
        )
        wizard = content.get("wizard") if isinstance(content.get("wizard"), dict) else {}

        if stage_number == 1:
            mission = self._nested_dict(wizard, "konteks", "mission")
            merged = self._merge_dicts_keep_non_empty(content, inputs, mission)
            total_jp = merged.get("alokasiJpTotal") or merged.get("totalJp") or ""
            minutes = merged.get("menitPerJp") or 35
            return self._merge_dicts_keep_non_empty(
                merged,
                {
                    "jenjangPendidikan": merged.get("jenjangPendidikan")
                    or merged.get("jenjang"),
                    "fase": merged.get("fase"),
                    "kelas": merged.get("kelas")
                    or merged.get("kelasSemester")
                    or merged.get("gradeLevel"),
                    "mataPelajaran": merged.get("mataPelajaran")
                    or merged.get("subject"),
                    "topikMateriPokok": merged.get("topikMateriPokok")
                    or merged.get("materiPokokBahasan")
                    or merged.get("topic"),
                    "durasiPembelajaran": merged.get("durasiPembelajaran")
                    or (f"{total_jp} JP x {minutes} menit" if total_jp else ""),
                    "jumlahPertemuan": merged.get("jumlahPertemuan")
                    or merged.get("meetingCount"),
                    "kondisiKelas": merged.get("kondisiKelas")
                    or merged.get("classConditions")
                    or merged.get("studentNotes"),
                    "fasilitasAwal": merged.get("fasilitasAwal")
                    or merged.get("fasilitasKelas")
                    or merged.get("facilities"),
                },
            )

        if stage_number == 2:
            fokus = self._nested_dict(wizard, "fokus", "fokus")
            merged = self._merge_dicts_keep_non_empty(content, inputs, fokus)
            lintas = (
                merged.get("lintasDisiplin")
                if isinstance(merged.get("lintasDisiplin"), dict)
                else {}
            )
            lintas_labels = self._extract_lintas_disiplin_labels(lintas)
            atp = merged.get("atpIndicators") or merged.get("tujuanPembelajaranTerpilih")
            if not isinstance(atp, list):
                atp = []
            return self._merge_dicts_keep_non_empty(
                merged,
                {
                    "dimensiProfilLulusan": merged.get("dimensiProfilLulusan")
                    or merged.get("profilLulusan"),
                    "mataPelajaranLintasDisiplin": merged.get(
                        "mataPelajaranLintasDisiplin"
                    )
                    or lintas_labels,
                    "capaianPembelajaran": merged.get("capaianPembelajaran")
                    or merged.get("cpText"),
                    "tujuanPembelajaranTerpilih": atp,
                    "alurTujuanPembelajaran": [
                        {
                            "order": index + 1,
                            "selected": True,
                            "tujuanPembelajaran": str(item),
                        }
                        for index, item in enumerate(atp)
                    ],
                    "pertanyaanPemantik": merged.get("pertanyaanPemantik")
                    or merged.get("essentialQuestion"),
                },
            )

        if stage_number == 3:
            alur = self._nested_dict(wizard, "alur", "alur")
            merged = self._merge_dicts_keep_non_empty(content, inputs, generated, alur)
            return self._merge_dicts_keep_non_empty(
                merged,
                {
                    "discussionSummary": merged.get("discussionSummary")
                    or merged.get("ringkasan")
                    or merged.get("summary"),
                    "learningStrategy": merged.get("learningStrategy")
                    or self._join_list(merged.get("gayaPembelajaran")),
                    "pedagogicalApproach": merged.get("pedagogicalApproach")
                    or merged.get("preferensiPedagogis")
                    or merged.get("praktikPedagogis"),
                    "facilityAndTechnologyUse": merged.get(
                        "facilityAndTechnologyUse"
                    )
                    or self._join_list(merged.get("fasilitasKelas")),
                    "digitalPlatform": merged.get("digitalPlatform")
                    or self._join_list(merged.get("platformDigital"))
                    or merged.get("pemanfaatanDigital"),
                    "partnership": merged.get("partnership")
                    or self._stringify_stage3_partnership(merged.get("kemitraan"))
                    or merged.get("kemitraanDetail"),
                    "finalStudentProduct": merged.get("finalStudentProduct")
                    or self._join_list(merged.get("produkKinerjaAkhir"))
                    or merged.get("produkKinerjaAkhirNarasi"),
                    "activityFlowDecision": merged.get("activityFlowDecision")
                    or merged.get("diagramTerpilih")
                    or merged.get("diagramVariants"),
                    "differentiationPlan": merged.get("differentiationPlan"),
                    "teacherNotes": merged.get("teacherNotes"),
                },
            )

        if stage_number == 4:
            penilaian = self._nested_dict(wizard, "penilaian", "penilaian")
            merged = self._merge_dicts_keep_non_empty(content, inputs, penilaian)
            return merged

        return self._merge_dicts_keep_non_empty(content, inputs, generated)

    def _nested_dict(self, value: dict[str, Any], *keys: str) -> dict[str, Any]:
        current: Any = value
        for key in keys:
            if not isinstance(current, dict):
                return {}
            current = current.get(key)
        return current if isinstance(current, dict) else {}

    def _extract_lintas_disiplin_labels(self, lintas: dict[str, Any]) -> list[str]:
        checked = lintas.get("mapelChecked")
        custom = lintas.get("mapelCustom")
        labels: list[str] = []

        if isinstance(checked, list):
            labels.extend(str(item) for item in checked if str(item).strip())

        if isinstance(custom, list):
            for item in custom:
                if not isinstance(item, dict):
                    continue
                item_id = str(item.get("id") or "")
                label = str(item.get("label") or "").strip()
                if label and (not checked or item_id in checked):
                    labels.append(label)

        return labels

    def _stringify_stage3_partnership(self, kemitraan: Any) -> str:
        if isinstance(kemitraan, str):
            return kemitraan
        if not isinstance(kemitraan, dict):
            return ""
        if kemitraan.get("digunakan") is False:
            return "Tidak digunakan"
        values = [
            self._join_list(kemitraan.get("pilihan")),
            str(kemitraan.get("catatan") or ""),
        ]
        return ". ".join(item for item in values if item.strip())

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
                        {"name": "", "description": ""},
                        {"name": "", "description": ""},
                    ],
                },
                "partnership": {
                    "items": [
                        {"partner": "", "partnerRole": ""},
                    ],
                    "notes": "",
                },
                "digitalUse": {
                    "items": [
                        {"sourceOrPlatform": "", "linkOrAccess": "", "function": ""},
                    ],
                    "notes": "",
                },
                "resources": [
                    {"name": "", "function": ""},
                ],
            },
            "meetingActivities": {
                "overview": "",
                "meetings": self._build_meeting_shape(source_data),
            },
            "assessment": {
                "summative": {
                    "provision": "",
                    "description": "",
                    "sampleTasks": ["", "", ""],
                    "criteria": ["", "", "", ""],
                    "achievementLevels": [
                        {"level": "Perlu Bimbingan", "description": "", "followUp": ""},
                        {"level": "Cukup", "description": "", "followUp": ""},
                        {"level": "Baik", "description": "", "followUp": ""},
                        {"level": "Sangat Baik", "description": "", "followUp": ""},
                    ],
                },
            },
            "rubric": {
                "criteria": [
                    {"criterion": "", "excellent": "", "good": "", "needsSupport": ""},
                    {"criterion": "", "excellent": "", "good": "", "needsSupport": ""},
                    {"criterion": "", "excellent": "", "good": "", "needsSupport": ""},
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
                    "",
                    "",
                    "",
                    "",
                ],
            },
            "completionChecklist": [
                {"item": "", "status": ""},
                {"item": "", "status": ""},
                {"item": "", "status": ""},
                {"item": "", "status": ""},
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
                        "answerOptions": ["", ""],
                        "correctAnswer": "",
                        "step2Description": "",
                        "teacherNotes": "",
                    },
                    "understanding": {
                        "teacherNotes": "",
                        "step4Description": "",
                        "step5Description": "",
                        "triggerQuestions": ["", "", ""],
                    },
                    "applying": {
                        "step6Description": "",
                        "differentiation": {
                            "supportGroup": "",
                            "advancedGroup": "",
                        },
                        "step7Description": "",
                        "flowSummary": ["", "", ""],
                        "product": "",
                    },
                    "reflecting": {
                        "description": "",
                        "step8Description": "",
                        "reflectionQuestions": ["", "", ""],
                    },
                    "formativeAssessment": {
                        "technique": str(stage4_item.get("selectedTechniqueLabel") or stage4_item.get("selectedTechnique") or ""),
                        "step9Description": str(stage4_item.get("description", "")),
                        "observedIndicators": ["", "", "", ""],
                        "teacherRecordFormat": "",
                    },
                }
            )

        return meetings

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

    def _dump(self, value: Any) -> dict[str, Any]:
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if isinstance(value, dict):
            return value
        return {}

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

    def _merge_dicts_keep_non_empty(self, *sources: dict[str, Any]) -> dict[str, Any]:
        merged: dict[str, Any] = {}

        for source in sources:
            if not isinstance(source, dict):
                continue

            for key, value in source.items():
                if self._is_empty_value(value):
                    continue

                merged[key] = value

        return merged

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

    def _format_checklist_status(self, status: Any) -> str:
        if isinstance(status, bool):
            return "[x]" if status else "[ ]"

        text = str(status or "").strip().lower()
        if text in {"true", "yes", "ya", "done", "selesai", "checked", "terpenuhi"}:
            return "[x]"
        return "[ ]"

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
        if partnership.get("notes"):
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
        if digital.get("notes"):
            lines.append(str(digital.get("notes", "")))

        lines.append("")
        lines.append("### 4. Sumber Daya")
        for item in learning_design.get("resources") or []:
            name = item.get("name", "")
            function = item.get("function", "")
            if name or function:
                lines.append(f"- **{name}**: {function}")

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

            step9_text = str(formative.get("step9Description") or formative.get("description") or "")
            if step9_text:
                lines.append(f"**Langkah - 9** {step9_text}")

            if formative.get("technique"):
                lines.append("")
                lines.append(f"**Teknik Asesmen:** {formative.get('technique')}")

            observed_indicators = formative.get("observedIndicators") or []
            if observed_indicators:
                lines.append("")
                lines.append("> **Indikator yang Diamati Guru**")
                for indicator in observed_indicators:
                    indicator_text = str(indicator).strip()
                    if indicator_text:
                        lines.append(f"> - {indicator_text}")

            if formative.get("teacherRecordFormat"):
                lines.append("")
                lines.append("> **Format Catatan Guru**")
                lines.append(f"> {formative.get('teacherRecordFormat')}")

        assessment = content.get("assessment") or {}
        summative = assessment.get("summative") or {}

        lines.extend(["", "## E. Asesmen Pembelajaran"])
        lines.append("### Asesmen Sumatif UH/UTS/UAS")

        if summative.get("provision"):
            lines.append(f"Ketentuan: {summative.get('provision')}")

        lines.append(str(summative.get("description", "")))

        if summative.get("sampleTasks"):
            lines.append("Contoh bentuk soal sumatif:")
            for task in summative.get("sampleTasks") or []:
                task_text = str(task).strip()
                if task_text:
                    lines.append(f"- {task_text}")

        if summative.get("criteria"):
            lines.append("Kriteria penilaian sumatif:")
            for criterion in summative.get("criteria") or []:
                criterion_text = str(criterion).strip()
                if criterion_text:
                    lines.append(f"- {criterion_text}")

        for level in summative.get("achievementLevels") or []:
            if isinstance(level, dict):
                lines.append(
                    f"- **{level.get('level', '')}**: {level.get('description', '')} "
                    f"Tindak lanjut: {level.get('followUp', '')}"
                )

        rubric = content.get("rubric") or {}
        lines.extend(["", "## F. Rubrik Penilaian"])
        for item in rubric.get("criteria") or []:
            criterion = item.get("criterion", "")
            excellent = item.get("excellent", "")
            good = item.get("good", "")
            needs_support = item.get("needsSupport", "")

            if criterion or excellent or good or needs_support:
                lines.append(f"- **{criterion}**")
                lines.append(f"  - Sangat Baik: {excellent}")
                lines.append(f"  - Baik: {good}")
                lines.append(f"  - Perlu Dukungan: {needs_support}")

        follow_up = content.get("followUp") or {}
        lines.extend(["", "## G. Tindak Lanjut Pembelajaran"])
        if follow_up.get("description"):
            lines.append(str(follow_up.get("description", "")))
        if follow_up.get("notYetAchieved"):
            lines.append(f"- Belum mencapai tujuan pembelajaran: {follow_up.get('notYetAchieved', '')}")
        if follow_up.get("almostAchieved"):
            lines.append(f"- Hampir mencapai tujuan pembelajaran: {follow_up.get('almostAchieved', '')}")
        if follow_up.get("achieved"):
            lines.append(f"- Sudah mencapai tujuan pembelajaran: {follow_up.get('achieved', '')}")
        if follow_up.get("exceeding"):
            lines.append(f"- Melampaui tujuan pembelajaran: {follow_up.get('exceeding', '')}")
        if follow_up.get("enrichmentExample"):
            lines.append(f"- Contoh pengayaan: {follow_up.get('enrichmentExample', '')}")

        teacher_reflection = content.get("teacherReflection") or {}
        lines.extend(["", "## H. Refleksi Guru"])
        if teacher_reflection.get("description"):
            lines.append(str(teacher_reflection.get("description", "")))
        for question in teacher_reflection.get("questions") or []:
            question_text = str(question).strip()
            if question_text:
                lines.append(f"- {question_text}")

        lines.extend(["", "## I. Checklist Kelengkapan RPP"])
        for item in content.get("completionChecklist") or []:
            if isinstance(item, dict):
                item_text = str(item.get("item", "")).strip()
                if item_text:
                    lines.append(f"- {self._format_checklist_status(item.get('status'))} {item_text}")
            else:
                item_text = str(item).strip()
                if item_text:
                    lines.append(f"- ☐ {item_text}")

        if content.get("finalFlowSummary"):
            lines.extend(["", "## Ringkasan Alur Final"])
            lines.append(str(content.get("finalFlowSummary", "")))

        return "\n".join(lines)
