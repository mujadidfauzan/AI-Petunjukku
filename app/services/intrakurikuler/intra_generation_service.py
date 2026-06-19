from __future__ import annotations

import json
from typing import Any

from app.schemas.common_schema import UsedReferenceSchema
from app.schemas.generate_rpp_schema import GenerateRppRequest, GenerateRppResponse
from app.services.intrakurikuler.intra_dummy_stage_data import (
    get_intra_dummy_onboarding_content,
    get_intra_dummy_stage_content,
)
from app.services.intrakurikuler.resource_discovery_service import (
    ResourceDiscoveryService,
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
        resource_discovery_service: ResourceDiscoveryService | None = None,
    ) -> None:
        self.rag_service = rag_service or RAGService()
        self.llm_client = llm_client or LLMClient()
        self.prompt_builder = prompt_builder or PromptBuilderService()
        self.resource_discovery_service = (
            resource_discovery_service or ResourceDiscoveryService()
        )

    async def generate(self, payload: GenerateRppRequest) -> GenerateRppResponse:
        references = await self.rag_service.search_for_context(
            query=payload.project.title or payload.project.subject or "RPM",
            subject=payload.project.subject,
            phase=payload.project.phase,
            top_k=5,
        )

        source_data = self._build_source_data(payload, references)
        discovered_resources = await self.resource_discovery_service.discover(
            source_data
        )
        self._attach_discovered_resources(source_data, discovered_resources)
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
                            "Isi requiredResponseShape menjadi contentJson RPM final berdasarkan sourceData. "
                            "Gunakan seluruh data Stage 1, Stage 2, Stage 3, dan Stage 4 sebagai satu-satunya dasar penyusunan RPM. "
                            "Semua isi naratif harus ditulis oleh LLM API berdasarkan sourceData, bukan oleh kode backend. "
                            "Jangan memilih sebagian data jika sourceData menyediakan beberapa item. "
                            "requiredResponseShape adalah skema wajib. Semua key root dan key nested wajib tetap ada di output akhir. "
                            "Field string pada requiredResponseShape tidak boleh dibiarkan kosong jika sourceData cukup untuk mengisinya. "
                            "Jumlah item list boleh disesuaikan dengan sourceData, tetapi struktur utama tidak boleh dihapus. "
                            "Output dianggap gagal jika hanya mengisi bagian identitas, profil, atau konteks materi tanpa mengisi learningDesign, meetingActivities, dan assessment. "
                            "Jangan menambahkan informasi, perangkat, sumber daya, produk, tugas, tautan, aplikasi, atau fasilitas yang tidak disebut atau tidak dapat diturunkan langsung dari Stage 1-4. "
                            "Gunakan Stage 3 untuk mengisi learningDesign.partnership, learningDesign.digitalUse, learningDesign.resources, produk akhir, diferensiasi, dan alur kegiatan. "
                            "learningDesign.partnership hanya boleh berasal dari Stage 3 field partnership. "
                            "Preferensi learningDesign.digitalUse berasal dari Stage 3 field mediaPreferences, mediaUsage, dan legacy digitalPlatform. "
                            "Judul, penyedia, dan tautan konkret learningDesign.digitalUse hanya boleh berasal dari sourceData.selectedResources yang sudah diverifikasi resource discovery service. "
                            "Jika selectedResources kosong, jangan mengarang judul buku, judul video, kanal, atau URL. "
                            "learningDesign.resources hanya boleh berasal dari Stage 3 field facilityAndTechnologyUse. "
                            "Jangan menurunkan resources dari digitalPlatform. Jika digitalPlatform menyebut media atau platform digital, jangan otomatis menambahkan perangkat akses seperti gawai, HP, laptop, komputer, internet, atau WiFi ke resources kecuali perangkat itu disebut eksplisit pada facilityAndTechnologyUse. "
                            "Produk akhir, tugas utama, dan asesmen harus konsisten dengan finalStudentProduct Stage 3. Jangan menambahkan produk besar lain seperti laporan tertulis, LKPD, poster, video, atau artefak tambahan jika tidak disebut pada Stage 1-4. "
                            "Gunakan Stage 4 untuk mengisi formativeAssessment pada setiap pertemuan. "
                            "Untuk setiap formativeAssessment, isi observedIndicators dengan 3-5 indikator konkret dan teacherRecordFormat dengan format catatan guru yang sesuai teknik asesmen. "
                            "Jangan membiarkan observedIndicators kosong. Jangan membiarkan teacherRecordFormat kosong. "
                            "Wajib isi root contentJson berikut: title, identity, materialContext, profileAndLearningDirection, learningDesign, meetingActivities, assessment, followUp, teacherReflection, completionChecklist, dan finalFlowSummary. "
                            "Wajib isi learningDesign.pedagogicalPractice, learningDesign.partnership, learningDesign.digitalUse, dan learningDesign.resources. "
                            "Wajib isi meetingActivities.overview dan seluruh meetings sesuai jumlah pertemuan. "
                            "Wajib isi setiap meeting dengan diagnostic, understanding, applying, reflecting, dan formativeAssessment. "
                            "Jangan mengembalikan JSON parsial. "
                            "profileAndLearningDirection.interdisciplinaryIntegration wajib berasal dari Stage 2 field mataPelajaranLintasDisiplin dan tetap ditampilkan meskipun hanya sebagai pendukung. "
                            "learningDesign.partnership wajib berasal dari Stage 3 field partnership dan tetap ditampilkan; jika Stage 3 menyatakan tidak digunakan, tuliskan secara eksplisit bahwa tidak ada kemitraan khusus. "
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

        content_json = None

        for attempt in range(3):
            generated = await self.llm_client.generate_json(
                messages,
                fallback={"contentJson": {}},
                temperature=0.0,
            )

            candidate = generated.get("contentJson") if isinstance(generated, dict) else None

            if not isinstance(candidate, dict):
                continue

            candidate = self._normalize_generated_text(candidate)
            candidate = self._normalize_output_structure(candidate)
            candidate = self._apply_identity_defaults(candidate, payload, source_data)
            candidate = self._apply_meeting_title_defaults(candidate, source_data)

            if self._is_content_complete_enough(candidate):
                content_json = candidate
                break

        if not isinstance(content_json, dict):
            raise ValueError(
                "Generate RPM gagal: output LLM masih kosong/tidak lengkap setelah 3 percobaan."
            )

        
        # content_json = self._normalize_generated_text(content_json)
        # content_json = self._normalize_output_structure(content_json)

        # pre_repair_content_json = content_json

        # repaired_content_json = await self._repair_grounding_with_llm(
        #     content_json=content_json,
        #     source_data=source_data,
        #     response_shape=response_shape,
        # )

        # repaired_content_json = self._normalize_generated_text(repaired_content_json)
        # repaired_content_json = self._normalize_output_structure(repaired_content_json)

        # if self._has_required_rpm_sections(repaired_content_json):
        #     content_json = repaired_content_json
        # else:
        #     content_json = pre_repair_content_json

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
    def _is_content_complete_enough(self, content: dict[str, Any]) -> bool:
        if not isinstance(content, dict):
            return False

        required_root_keys = [
            "title",
            "identity",
            "materialContext",
            "profileAndLearningDirection",
            "learningDesign",
            "meetingActivities",
            "assessment",
            "followUp",
            "teacherReflection",
            "completionChecklist",
            "finalFlowSummary",
        ]

        for key in required_root_keys:
            if key not in content:
                return False

        learning_design = content.get("learningDesign") or {}
        if self._is_empty_value(learning_design.get("pedagogicalPractice")):
            return False
        if self._is_empty_value(learning_design.get("partnership")):
            return False
        if self._is_empty_value(learning_design.get("digitalUse")):
            return False
        if self._is_empty_value(learning_design.get("resources")):
            return False

        profile = content.get("profileAndLearningDirection") or {}
        interdisciplinary = profile.get("interdisciplinaryIntegration") or {}
        if self._is_empty_value(interdisciplinary):
            return False

        for key in ("relatedDiscipline", "rationale", "integrationForm", "notes"):
            if not str(interdisciplinary.get(key, "")).strip():
                return False

        meeting_activities = content.get("meetingActivities") or {}
        if not str(meeting_activities.get("overview", "")).strip():
            return False

        meetings = meeting_activities.get("meetings")
        if not isinstance(meetings, list) or not meetings:
            return False

        for meeting in meetings:
            if not isinstance(meeting, dict):
                return False

            if not str(meeting.get("introParagraph", "")).strip():
                return False
            if not str(meeting.get("focus", "")).strip():
                return False
            if not str(meeting.get("target", "")).strip():
                return False

            diagnostic = meeting.get("diagnostic") or {}
            understanding = meeting.get("understanding") or {}
            applying = meeting.get("applying") or {}
            reflecting = meeting.get("reflecting") or {}
            formative = meeting.get("formativeAssessment") or {}

            if not str(diagnostic.get("step1Description", "")).strip():
                return False
            if not str(understanding.get("step4Description", "")).strip():
                return False
            if not str(applying.get("step6Description", "")).strip():
                return False
            if not str(reflecting.get("step8Description", "")).strip():
                return False
            if not str(formative.get("teacherRecordFormat", "")).strip():
                return False

            indicators = formative.get("observedIndicators") or []
            valid_indicators = [
                item for item in indicators
                if isinstance(item, str) and item.strip()
            ]
            if len(valid_indicators) < 3:
                return False

        assessment = content.get("assessment") or {}
        summative = assessment.get("summative") or {}

        if not str(summative.get("description", "")).strip():
            return False

        return True
    def _build_system_prompt(self) -> str:
        return """
Anda adalah AI Service Petunjukku untuk menyusun RPM Intrakurikuler final.

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
10. Gaya bahasa harus naratif, siap ditempel ke dokumen RPM, dan tidak berupa frasa pendek.

B2. Standar Kualitas Isi Seperti Template Final
1. Output harus terasa sebagai panduan mengajar yang bisa langsung dijalankan guru, bukan ringkasan umum.
2. Setiap bagian kegiatan wajib menyebut konteks konkret dari Stage 1-4, seperti objek kelas, lingkungan sekolah, data sederhana, masalah kontekstual, media yang dipilih, sumber daya yang tersedia, atau produk akhir.
3. Jika sourceData hanya memberi topik umum, turunkan contoh konkret yang wajar dari topik, kelas, dan lingkungan sekolah tanpa menambah fasilitas, platform, mitra, atau produk baru.
4. Hindari kalimat generik tanpa detail operasional, misalnya "murid mencari contoh nyata", "guru memberi penjelasan", atau "murid berdiskusi" jika tidak dijelaskan contoh yang dibahas, cara kerja, bukti belajar, dan peran guru.
5. Untuk setiap pertemuan, buat alur yang runtut: cek awal, pembahasan miskonsepsi, penguatan konsep, tugas aplikasi, berbagi hasil, refleksi, dan asesmen formatif.
6. Kegiatan harus sesuai alokasi waktu. Jika hanya 1 pertemuan, produk harus kecil dan selesai di kelas; jangan mengubahnya menjadi proyek besar.
7. Pakai contoh yang dekat dengan guru dan murid Indonesia, seperti kelas, kantin, koperasi, jadwal, kelompok belajar, data sederhana, peta lingkungan sekolah, atau fenomena lokal yang relevan dengan topik.
8. Jangan mengulang frasa yang sama antarbagian. Setiap langkah harus menambah informasi baru yang membantu guru menjalankan kelas.
9. Gunakan gaya seperti contoh final: konkret, instruktif, pedagogis, dan tetap ringkas dalam batas template.

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
- preferensi digitalUse berasal dari mediaPreferences, mediaUsage, dan legacy digitalPlatform Stage 3.
- judul, penyedia, dan tautan digitalUse berasal dari selectedResources.
- resources berasal dari field facilityAndTechnologyUse Stage 3.
- discussionSummary digunakan sebagai konteks penguat agar narasi setiap bagian saling nyambung.

D. Aturan Learning Design
- pedagogicalPractice dikembangkan dari learningStrategy dan pedagogicalApproach Stage 3.
- partnership dikembangkan dari partnership Stage 3.
- digitalUse dikembangkan dari mediaPreferences, mediaUsage, legacy digitalPlatform, dan selectedResources.
- resources dikembangkan dari facilityAndTechnologyUse Stage 3.
- partnership hanya memuat mitra pembelajaran.
- digitalUse hanya memuat media, aplikasi, sumber digital, atau platform digital.
- Setiap selectedResources wajib dipertahankan judul, provider, URL, fungsi, dan alasan pemilihannya tanpa diubah atau dikarang ulang.
- Jika selectedResources kosong, digitalUse boleh menjelaskan preferensi media, tetapi linkOrAccess wajib kosong dan tidak boleh memuat URL buatan.
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

E. Aturan Produk, Tugas,dan Asesmen
- finalStudentProduct Stage 3 adalah acuan utama produk/kinerja murid.
- applying.product harus mengikuti finalStudentProduct Stage 3.
- Produk akhir, tugas utama, asesmen, dan tindak lanjut harus konsisten dengan finalStudentProduct Stage 3 dan tujuan pembelajaran Stage 2.
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
- followUp
- teacherReflection
- completionChecklist
- finalFlowSummary

G. Kedalaman Narasi Minimal
- materialContext: 1 paragraf, 3-4 kalimat, memuat konteks materi, situasi kelas, dan alasan konteks dipilih.
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
- meetings[].introParagraph: 1 paragraf, 3-4 kalimat, memuat fokus, durasi, konteks kegiatan, dan target bukti belajar.
- diagnostic.step1Description: 4-5 kalimat, memuat alat, instruksi guru, cara murid menjawab, contoh konteks, dan tujuan diagnostik.
- diagnostic.step2Description: 4-5 kalimat, memuat cara guru membaca jawaban, aturan Kelompok A/B, tujuan diferensiasi, dan transisi ke pembahasan.
- understanding.step4Description: 4-5 kalimat, memuat jawaban yang dibahas, miskonsepsi yang mungkin muncul, dan cara guru meluruskannya.
- understanding.step5Description: 4-5 kalimat, memuat penguatan konsep, contoh atau noncontoh, sumber daya yang dipakai, dan catatan keterkaitan dengan konteks.
- applying.step6Description: 4-5 kalimat, memuat nama tugas atau mini-proyek kecil, bahan yang digunakan, tindakan murid, dan hasil antara.
- applying.step7Description: 4-5 kalimat, memuat cara murid menyelesaikan produk, cara guru berkeliling memberi umpan balik, dan cara hasil dibagikan.
- reflecting.description: 2 kalimat.
- reflecting.step8Description: 3-4 kalimat.
- formativeAssessment.step9Description: 2-3 kalimat.
- formativeAssessment.observedIndicators: 3-5 butir indikator konkret.
- formativeAssessment.teacherRecordFormat: 1-2 kalimat format catatan guru.
- assessment.summative.provision: 2-3 kalimat.
- assessment.summative.description: 2-3 kalimat.
- assessment.summative.sampleTasks: 3-5 butir.
- assessment.summative.criteria: 4-5 butir.
- followUp.description: 2-3 kalimat.
- completionChecklist: 4-6 item.
- finalFlowSummary: 2-3 kalimat.

H. Lintas Disiplin
- relatedDiscipline diambil dari Stage 2 jika tersedia.
- rationale menjelaskan alasan disiplin terkait relevan dengan pembelajaran.
- integrationForm menjelaskan bentuk integrasi lintas disiplin dalam kegiatan belajar, produk akhir, komunikasi hasil, atau penggunaan teknologi sesuai Stage 3.
- notes menjelaskan bahwa lintas disiplin bersifat pendukung, sedangkan kompetensi utama tetap berada pada mata pelajaran utama.
- Jangan menambah disiplin lain yang tidak ada pada Stage 2 atau Stage 3.
- Bagian lintas disiplin tetap wajib ada di output. Jika Stage 2 tidak memilih lintas disiplin khusus, tuliskan bahwa tidak ada lintas disiplin khusus dan pembelajaran tetap berpusat pada mata pelajaran utama.

H2. Kemitraan
- partnership diambil dari Stage 3 field partnership.
- Bagian kemitraan tetap wajib ada di output karena Stage 3 menanyakan keputusan kemitraan.
- Jika Stage 3 menyebut mitra tertentu, setiap mitra harus menjadi item terpisah dengan partner dan partnerRole.
- Jika Stage 3 menyatakan tidak ada atau tidak digunakan, tuliskan secara eksplisit "Tidak ada kemitraan khusus" sebagai partner dan jelaskan bahwa pembelajaran dapat berjalan tanpa mitra eksternal.

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
- meetingTitle adalah judul materi/fokus pertemuan yang ringkas seperti "Bilangan Bulat dan Garis Bilangan".
- meetingTitle tidak boleh berisi judul asesmen/LKPD seperti "LKPD Pertemuan 1", "LKPD Pertemuan 2", atau "Asesmen Formatif".
- Jika Stage 4 meetingTitle berisi LKPD/asesmen, abaikan dan gunakan focus, target, atau topik Stage 1 sebagai judul pertemuan.
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
- step1Description: cara guru melakukan cek kesiapan awal, alat atau media yang digunakan, instruksi singkat kepada murid, cara murid menjawab, dan tujuan diagnostik.
- sampleQuestion: contoh soal sesuai materi pertemuan, konkret, kontekstual, dan bisa dikerjakan di kelas.
- answerOptions: wajib pilihan A dan B jika sampleQuestion berbentuk pilihan; pilihan A/B harus jelas dan tidak boleh kosong.
- correctAnswer: jawaban tepat dan alasan singkat yang menjelaskan konsep inti.
- step2Description: cara guru membaca hasil jawaban dan membentuk kelompok sementara. Wajib konsisten: Kelompok A adalah murid yang lebih siap atau menjawab tepat; Kelompok B adalah murid yang masih ragu, belum tepat, atau membutuhkan dukungan bertahap.
- teacherNotes: buat banyak kata dan inti penjelasan sama dengan contoh, berikut "Kelompok A/B bersifat sementara dan tidak boleh disebut sebagai kelompok pintar atau kurang pintar. Guru perlu menyampaikan bahwa pengelompokan hanya digunakan untuk menyesuaikan bentuk bantuan belajar. Murid dapat berpindah kelompok pada kegiatan berikutnya ketika pemahamannya berubah" .

K. Struktur Memahami
Setiap understanding wajib berisi:
- teacherNotes: buat banyak kata dan inti penjelasan sama dengan contoh, berikut "Pada tahap memahami, guru belum membedakan tugas antara Kelompok A dan Kelompok B. Semua murid tetap mendapatkan penjelasan konsep yang sama agar memiliki dasar pemahaman bersama. Hasil diagnostik digunakan sebagai pintu masuk untuk memilih contoh yang perlu dibahas"
- step4Description: guru membahas jawaban murid dan meluruskan miskonsepsi.
- step5Description: guru menguatkan konsep dengan media atau sumber daya yang relevan.
- triggerQuestions: 3-4 pertanyaan pemantik.

L. Struktur Mengaplikasi
Setiap applying wajib berisi:
- step6Description: murid mulai mengerjakan mini-PjBL atau tugas aplikasi kecil yang dapat selesai sesuai alokasi waktu. Jelaskan judul tugas, bahan atau data yang dipakai, cara kerja kelompok, dan hasil antara yang harus terlihat.
- differentiation.supportGroup: bantuan untuk Kelompok B, yaitu murid yang membutuhkan dukungan; tuliskan contoh scaffold, template, pertanyaan bantu, atau langkah bertahap.
- differentiation.advancedGroup: tantangan untuk Kelompok A, yaitu murid yang lebih siap; tuliskan perluasan, pembandingan, alasan tambahan, atau contoh baru yang masih sesuai tujuan.
- step7Description: penyelesaian produk/kinerja dan persiapan penyampaian hasil. Jelaskan cara guru memberi umpan balik, bentuk berbagi hasil, dan apa yang harus dikumpulkan.
- flowSummary: 4 butir alur kegiatan yang dimulai dari memahami masalah, merancang strategi, membuat produk/kinerja, dan berbagi/menanggapi hasil.
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
- followUp, teacherReflection, completionChecklist, dan finalFlowSummary harus berada di root-level contentJson, sejajar dengan assessment.
- Jangan memasukkan followUp, teacherReflection, completionChecklist, atau finalFlowSummary ke dalam assessment.
- Tindak lanjut, refleksi guru, checklist, dan ringkasan akhir harus nyambung dengan tujuan pembelajaran, produk akhir, dan asesmen.
- Jangan membuat root-level rubric.
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
        stage3 = self._merge_dicts_keep_non_empty(stage3_from_summary, stage3_from_stages)
        stage1 = self._normalize_stage1_basic_context(
            stages_by_number.get(1, {}),
            payload,
            onboarding,
        )
        stage2 = stages_by_number.get(2, {}) or {}
        interdisciplinary_source = self._join_list(stage2.get("mataPelajaranLintasDisiplin"))

        locked_decisions_from_stage3 = {
            "discussionSummary": stage3.get("discussionSummary", ""),
            "learningStrategy": stage3.get("learningStrategy", ""),
            "pedagogicalApproach": stage3.get("pedagogicalApproach", ""),
            "facilityAndTechnologyUse": stage3.get("facilityAndTechnologyUse", ""),
            "mediaPreferences": stage3.get("mediaPreferences", []),
            "mediaUsage": stage3.get("mediaUsage", ""),
            "resourceDiscoveryMode": stage3.get(
                "resourceDiscoveryMode", "automatic"
            ),
            "selectedResources": stage3.get("selectedResources", []),
            "digitalPlatform": stage3.get("digitalPlatform", ""),
            "partnership": stage3.get("partnership", ""),
            "finalStudentProduct": stage3.get("finalStudentProduct", ""),
            "activityFlowDecision": stage3.get("activityFlowDecision", {}),
            "differentiationPlan": stage3.get("differentiationPlan", {}),
            "teacherNotes": stage3.get("teacherNotes", ""),
        }

        return {
            "onboarding": onboarding,
            "stage1_basicContext": stage1,
            "stage2_curriculumFoundation": stages_by_number.get(2, {}),
            "stage3_learningStrategyFromKina": stage3,
            "lockedDecisionsFromStage3": locked_decisions_from_stage3,
            "stage4_formativeAssessment": stages_by_number.get(4, {}),
            "kinaChatSummary": self._dump(payload.kinaChatSummary),
            "strictGroundingContract": {
                "identitySource": "onboarding, Stage 1, Stage 2, dan project payload.",
                "topicSource": "Stage 1.",
                "learningObjectivesSource": "Stage 2.",
                "interdisciplinarySourceText": interdisciplinary_source,
                "meetingCountSource": "Stage 1.",
                "formativeAssessmentSource": "Stage 4.",
                "partnershipSourceText": locked_decisions_from_stage3["partnership"],
                "mediaPreferences": locked_decisions_from_stage3["mediaPreferences"],
                "mediaUsage": locked_decisions_from_stage3["mediaUsage"],
                "selectedResources": locked_decisions_from_stage3[
                    "selectedResources"
                ],
                "digitalUseSourceText": locked_decisions_from_stage3["digitalPlatform"],
                "resourcesSourceText": locked_decisions_from_stage3["facilityAndTechnologyUse"],
                "finalStudentProductSourceText": locked_decisions_from_stage3["finalStudentProduct"],
                "differentiationSource": locked_decisions_from_stage3["differentiationPlan"],
                "activityFlowSource": locked_decisions_from_stage3["activityFlowDecision"],
                "hardRules": [
                    "interdisciplinaryIntegration hanya boleh berasal dari interdisciplinarySourceText dan konteks Stage 2.",
                    "partnership hanya boleh berasal dari partnershipSourceText.",
                    "preferensi digitalUse hanya boleh berasal dari mediaPreferences, mediaUsage, dan digitalUseSourceText.",
                    "judul dan tautan digitalUse hanya boleh berasal dari selectedResources.",
                    "resources hanya boleh berasal dari resourcesSourceText.",
                    "produk akhir, tugas utama, dan asesmen harus konsisten dengan finalStudentProductSourceText.",
                    "jangan menambahkan perangkat, media, aplikasi, fasilitas, atau produk yang tidak disebut pada Stage 1-4.",
                    "jangan menurunkan resources dari digitalUseSourceText.",
                ],
            },
            "ragReferences": [reference.model_dump() for reference in references],
        }

    def _attach_discovered_resources(
        self,
        source_data: dict[str, Any],
        resources: list[Any],
    ) -> None:
        serialized = [
            item.model_dump() if hasattr(item, "model_dump") else item
            for item in resources
            if isinstance(item, dict) or hasattr(item, "model_dump")
        ]
        source_data["selectedResources"] = serialized

        stage3 = self._as_dict(source_data.get("stage3_learningStrategyFromKina"))
        stage3["selectedResources"] = serialized
        stage3.setdefault("resourceDiscoveryMode", "automatic")
        source_data["stage3_learningStrategyFromKina"] = stage3

        locked = self._as_dict(source_data.get("lockedDecisionsFromStage3"))
        locked["selectedResources"] = serialized
        source_data["lockedDecisionsFromStage3"] = locked

        contract = self._as_dict(source_data.get("strictGroundingContract"))
        contract["selectedResources"] = serialized
        source_data["strictGroundingContract"] = contract

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
        identity = self._identity_defaults(payload, source_data)

        return {
            "title": payload.project.title or "",
          "identity": {
                "schoolName": identity["schoolName"],
                "teacherName": identity["teacherName"],
                "educationLevel": identity["educationLevel"],
                "phase": identity["phase"],
                "gradeLevel": identity["gradeLevel"],
                "subject": identity["subject"],
                "topic": identity["topic"],
                "element": self._infer_element(stage1, stage2),
                "timeAllocation": stage1.get("durasiPembelajaran", ""),
                "meetingCount": str(stage1.get("jumlahPertemuan", "")),
                "academicYear": identity["academicYear"],
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
                    "items": self._build_digital_use_shape(source_data),
                    "notes": self._digital_use_notes(source_data),
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

    def _build_digital_use_shape(
        self,
        source_data: dict[str, Any],
    ) -> list[dict[str, str]]:
        resources = source_data.get("selectedResources")
        if not isinstance(resources, list) or not resources:
            return [
                {
                    "sourceOrPlatform": "",
                    "linkOrAccess": "",
                    "function": "",
                }
            ]

        items: list[dict[str, str]] = []
        for resource in resources:
            if not isinstance(resource, dict):
                continue
            title = str(resource.get("title") or "").strip()
            url = str(resource.get("url") or "").strip()
            if not title or not url:
                continue
            provider = str(resource.get("provider") or "").strip()
            usage = str(resource.get("usage") or "").strip()
            reason = str(resource.get("selectionReason") or "").strip()
            items.append(
                {
                    "sourceOrPlatform": (
                        f"{title} - {provider}" if provider else title
                    ),
                    "linkOrAccess": url,
                    "function": usage or reason,
                }
            )

        return items or [
            {
                "sourceOrPlatform": "",
                "linkOrAccess": "",
                "function": "",
            }
        ]

    def _digital_use_notes(self, source_data: dict[str, Any]) -> str:
        resources = source_data.get("selectedResources")
        if isinstance(resources, list) and resources:
            return (
                "Sumber belajar dipilih otomatis oleh KINA berdasarkan mata "
                "pelajaran, fase, kelas, topik, tujuan pembelajaran, dan "
                "ketersediaan fasilitas."
            )
        return ""

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
    def _has_required_rpm_sections(self, content: dict[str, Any]) -> bool:
        if not isinstance(content, dict):
            return False

        required_root_keys = [
            "title",
            "identity",
            "materialContext",
            "profileAndLearningDirection",
            "learningDesign",
            "meetingActivities",
            "assessment",
            "followUp",
            "teacherReflection",
            "completionChecklist",
            "finalFlowSummary",
        ]

        for key in required_root_keys:
            if key not in content:
                return False

        learning_design = content.get("learningDesign")
        if not isinstance(learning_design, dict):
            return False

        for key in ("pedagogicalPractice", "partnership", "digitalUse", "resources"):
            if key not in learning_design:
                return False

        meeting_activities = content.get("meetingActivities")
        if not isinstance(meeting_activities, dict):
            return False

        meetings = meeting_activities.get("meetings")
        if not isinstance(meetings, list) or not meetings:
            return False

        assessment = content.get("assessment")
        if not isinstance(assessment, dict):
            return False

        if "summative" not in assessment:
            return False

        return True
    def _build_meeting_shape(self, source_data: dict[str, Any]) -> list[dict[str, Any]]:
        stage1 = source_data.get("stage1_basicContext") or {}
        stage4 = source_data.get("stage4_formativeAssessment") or {}

        meeting_count = int(stage1.get("jumlahPertemuan") or 1)
        stage4_meetings = stage4.get("meetings") or []
        duration = self._extract_meeting_duration(str(stage1.get("durasiPembelajaran", "")))

        meetings: list[dict[str, Any]] = []

        for index in range(meeting_count):
            stage4_item = stage4_meetings[index] if index < len(stage4_meetings) else {}
            meeting_title = self._meeting_title_from_stage4(
                stage4_item,
                index + 1,
                stage1,
            )

            meetings.append(
                {
                    "meetingOrder": index + 1,
                    "meetingTitle": meeting_title,
                    "duration": duration,
                    "introParagraph": "",
                    "focus": self._first_text(stage4_item.get("focus"), stage4_item.get("fokusPertemuan")),
                    "target": self._first_text(stage4_item.get("target"), stage4_item.get("targetPertemuan")),
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
                        "flowSummary": ["", "", "", ""],
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

    async def _repair_grounding_with_llm(
        self,
        content_json: dict[str, Any],
        source_data: dict[str, Any],
        response_shape: dict[str, Any],
    ) -> dict[str, Any]:
        messages = [
            {
                "role": "system",
                "content": """
Anda adalah pemeriksa grounding RPM Petunjukku.

Tugas:
1. Periksa contentJson yang sudah dibuat.
2. Pastikan semua isi hanya berasal dari sourceData Stage 1, Stage 2, Stage 3, Stage 4, onboarding, dan project payload.
3. Hapus atau tulis ulang isi yang tidak didukung sourceData.
4. Pertahankan struktur contentJson.
5. Jangan menambah data baru di luar sourceData.
6. Jangan mengosongkan seluruh dokumen; perbaiki hanya bagian yang melanggar grounding.

Aturan keras:
- learningDesign.partnership hanya boleh berasal dari strictGroundingContract.partnershipSourceText.
- learningDesign.digitalUse hanya boleh berasal dari strictGroundingContract.digitalUseSourceText.
- learningDesign.resources hanya boleh berasal dari strictGroundingContract.resourcesSourceText.
- Jangan menurunkan resources dari digitalUseSourceText.
- Jika media/platform digital disebut, media/platform tersebut masuk ke digitalUse, bukan otomatis menjadi alasan menambah perangkat akses ke resources.
- Perangkat akses seperti gawai, HP, laptop, komputer, internet, atau WiFi hanya boleh masuk resources jika disebut eksplisit pada resourcesSourceText atau Stage 1-4.
- Jika resourcesSourceText hanya menyebut satu sumber daya, resources cukup memuat sumber daya tersebut.
- Produk akhir, tugas utama, dan asesmen harus konsisten dengan strictGroundingContract.finalStudentProductSourceText dan tujuan pembelajaran Stage 2.
- Jangan menambahkan produk besar lain seperti laporan tertulis, LKPD, poster, video, infografis, makalah, atau artefak lain jika tidak disebut pada Stage 1-4.
- Asesmen formatif tetap mengikuti Stage 4.
- Indikator formatif boleh dikembangkan oleh LLM, tetapi harus sesuai teknik Stage 4, fokus pertemuan, target, aktivitas, dan produk yang tersedia dalam sourceData.
- Jika ada item tidak didukung sourceData, hapus item tersebut atau tulis ulang agar sesuai sourceData.
- Jangan membuat atau mempertahankan root-level rubric.
- Jika contentJsonToRepair memiliki root-level rubric, hapus field tersebut.
- Pertahankan seluruh struktur utama contentJson.
- Jangan menghapus root utama contentJson.
- Root utama yang wajib tetap ada: title, identity, materialContext, profileAndLearningDirection, learningDesign, meetingActivities, assessment, followUp, teacherReflection, completionChecklist, finalFlowSummary.
- Jika suatu bagian kurang grounded, tulis ulang isinya agar grounded, bukan menghapus seluruh bagian.
- Jika ragu, pertahankan struktur dan kosongkan hanya item spesifik yang melanggar, bukan seluruh section.
Output wajib hanya JSON valid:
{"contentJson": {...}}
""".strip(),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "instruction": (
                            "Perbaiki contentJson agar sepenuhnya grounded pada sourceData. "
                            "Jangan menambahkan informasi di luar Stage 1-4. "
                            "Pertahankan struktur lengkap seperti requiredResponseShape. "
                            "Jangan menghapus root utama seperti learningDesign, meetingActivities, assessment, followUp, teacherReflection, completionChecklist, atau finalFlowSummary. "
                            "Return hanya JSON valid dengan key contentJson."
                        ),
                        "sourceData": source_data,
                        "requiredResponseShape": {
                            "contentJson": response_shape,
                        },
                        "contentJsonToRepair": content_json,
                    },
                    ensure_ascii=False,
                ),
            },
        ]

        repaired = await self.llm_client.generate_json(
            messages,
            fallback={"contentJson": {}},
            temperature=0.0,
        )

        repaired_content = repaired.get("contentJson") if isinstance(repaired, dict) else None

        if isinstance(repaired_content, dict):
            return repaired_content

        return content_json

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

    def _meeting_title_from_stage4(
        self,
        stage4_item: Any,
        order: int,
        stage1: dict[str, Any],
    ) -> str:
        item = self._as_dict(stage4_item)
        for value in (
            item.get("meetingTitle"),
            item.get("title"),
            item.get("focus"),
            item.get("fokusPertemuan"),
            item.get("target"),
            item.get("targetPertemuan"),
            stage1.get("topikMateriPokok"),
            stage1.get("materiPokokBahasan"),
            stage1.get("topic"),
        ):
            title = self._clean_meeting_title(value, order)
            if title:
                return title
        return ""

    def _clean_meeting_title(self, value: Any, order: int) -> str:
        title = str(value or "").strip()
        if not title:
            return ""

        lower = title.lower()
        if "lkpd" in lower or "asesmen formatif" in lower:
            return ""

        prefixes = (
            f"d.{order}",
            f"pertemuan {order}",
            f"pertemuan ke-{order}",
            f"pertemuan ke {order}",
        )
        cleaned = title
        for prefix in prefixes:
            if cleaned.lower().startswith(prefix):
                cleaned = cleaned[len(prefix):].lstrip(" -–—:").strip()
                break

        return cleaned

    def _apply_meeting_title_defaults(
        self,
        content: dict[str, Any],
        source_data: dict[str, Any],
    ) -> dict[str, Any]:
        meeting_activities = self._as_dict(content.get("meetingActivities"))
        meetings = meeting_activities.get("meetings")
        if not isinstance(meetings, list):
            return content

        stage1 = self._as_dict(source_data.get("stage1_basicContext"))
        stage4 = self._as_dict(source_data.get("stage4_formativeAssessment"))
        stage4_meetings = stage4.get("meetings") if isinstance(stage4.get("meetings"), list) else []

        for index, meeting in enumerate(meetings):
            if not isinstance(meeting, dict):
                continue
            order = int(meeting.get("meetingOrder") or index + 1)
            current = self._clean_meeting_title(meeting.get("meetingTitle"), order)
            stage4_item = stage4_meetings[index] if index < len(stage4_meetings) else {}
            replacement = self._meeting_title_from_stage4(stage4_item, order, stage1)
            focus_title = self._clean_meeting_title(meeting.get("focus"), order)
            target_title = self._clean_meeting_title(meeting.get("target"), order)
            meeting["meetingTitle"] = current or replacement or focus_title or target_title

        content["meetingActivities"] = meeting_activities
        return content

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

    def _normalize_stage1_basic_context(
        self,
        raw_stage1: Any,
        payload: GenerateRppRequest,
        onboarding: dict[str, Any],
    ) -> dict[str, Any]:
        raw = self._as_dict(raw_stage1)
        inputs = self._as_dict(raw.get("inputs"))
        wizard = self._as_dict(raw.get("wizard"))
        konteks = self._as_dict(wizard.get("konteks"))
        mission = self._as_dict(konteks.get("mission"))
        merged = self._merge_dicts_keep_non_empty(raw, inputs, mission)

        teacher_profile = self._as_dict(onboarding.get("teacherProfile"))
        teacher_class = self._as_dict(onboarding.get("teacherClass"))
        teacher_subject = self._as_dict(onboarding.get("teacherSubject"))
        school = self._as_dict(onboarding.get("school"))

        phase = self._format_phase(
            self._first_text(
                merged.get("fase"),
                merged.get("phase"),
                teacher_class.get("phase"),
                payload.project.phase,
            )
        )
        grade_level = self._format_class_label(
            self._first_text(
                merged.get("kelasSemester"),
                merged.get("kelas"),
                merged.get("gradeLevel"),
                teacher_class.get("gradeLevel"),
                payload.project.gradeLevel,
            ),
            phase,
        )
        education_level = self._format_education_level(
            self._first_text(
                merged.get("jenjangPendidikan"),
                merged.get("jenjang"),
                merged.get("educationLevel"),
                school.get("educationLevel"),
                school.get("schoolLevel"),
                teacher_profile.get("educationLevel"),
            )
        )

        return {
            **raw,
            **inputs,
            **mission,
            "jenjangPendidikan": education_level,
            "educationLevel": education_level,
            "fase": phase,
            "phase": phase,
            "kelas": grade_level,
            "kelasSemester": grade_level,
            "gradeLevel": grade_level,
            "mataPelajaran": self._first_text(
                merged.get("mataPelajaran"),
                merged.get("subject"),
                teacher_subject.get("subject"),
                teacher_subject.get("subjectName"),
                payload.project.subject,
            ),
            "topikMateriPokok": self._first_text(
                merged.get("topikMateriPokok"),
                merged.get("materiPokokBahasan"),
                merged.get("topic"),
                getattr(payload.project, "topic", None),
            ),
            "durasiPembelajaran": self._first_text(
                merged.get("durasiPembelajaran"),
                self._format_jp(
                    merged.get("alokasiJpTotal")
                    or getattr(payload.project, "totalJp", None)
                ),
            ),
            "jumlahPertemuan": self._first_text(
                merged.get("jumlahPertemuan"),
                getattr(payload.project, "meetingCount", None),
            ),
        }

    def _identity_defaults(
        self,
        payload: GenerateRppRequest,
        source_data: dict[str, Any],
    ) -> dict[str, str]:
        onboarding = source_data.get("onboarding") or {}
        school = self._as_dict(onboarding.get("school"))
        teacher_profile = self._as_dict(onboarding.get("teacherProfile"))
        teacher_class = self._as_dict(onboarding.get("teacherClass"))
        teacher_subject = self._as_dict(onboarding.get("teacherSubject"))
        stage1 = self._as_dict(source_data.get("stage1_basicContext"))

        phase = self._format_phase(
            self._first_text(
                teacher_class.get("phase"),
                payload.project.phase,
                stage1.get("fase"),
                stage1.get("phase"),
            )
        )

        return {
            "schoolName": self._first_text(school.get("schoolName"), school.get("name")),
            "teacherName": self._first_text(
                teacher_profile.get("teacherName"),
                teacher_profile.get("fullName"),
            ),
            "educationLevel": self._format_education_level(
                self._first_text(
                    school.get("educationLevel"),
                    school.get("schoolLevel"),
                    teacher_profile.get("educationLevel"),
                    stage1.get("jenjangPendidikan"),
                    stage1.get("educationLevel"),
                )
            ),
            "phase": phase,
            "gradeLevel": self._format_class_label(
                self._first_text(
                    teacher_class.get("gradeLevel"),
                    payload.project.gradeLevel,
                    stage1.get("kelas"),
                    stage1.get("kelasSemester"),
                    stage1.get("gradeLevel"),
                ),
                phase,
            ),
            "subject": self._first_text(
                teacher_subject.get("subject"),
                teacher_subject.get("subjectName"),
                payload.project.subject,
                stage1.get("mataPelajaran"),
            ),
            "topic": self._first_text(
                stage1.get("topikMateriPokok"),
                stage1.get("materiPokokBahasan"),
                getattr(payload.project, "topic", None),
            ),
            "academicYear": self._first_text(school.get("academicYear")),
        }

    def _apply_identity_defaults(
        self,
        content: dict[str, Any],
        payload: GenerateRppRequest,
        source_data: dict[str, Any],
    ) -> dict[str, Any]:
        identity = self._as_dict(content.get("identity"))
        defaults = self._identity_defaults(payload, source_data)

        for key, value in defaults.items():
            if value:
                identity[key] = value

        content["identity"] = identity
        return content

    def _first_text(self, *values: Any) -> str:
        for value in values:
            if value is None:
                continue
            text = str(value).strip()
            if text and not self._is_blank_identity_value(text):
                return text
        return ""

    def _is_blank_identity_value(self, value: str) -> bool:
        cleaned = str(value or "").strip()
        return not cleaned or cleaned in {"-", "–", "—"} or cleaned.lower() in {
            "none",
            "null",
            "undefined",
        }

    def _format_education_level(self, value: str) -> str:
        raw = str(value or "").strip()
        key = raw.lower().replace("_", "-").replace(" ", "-")
        mapping = {
            "sd": "SD/MI",
            "sd/mi": "SD/MI",
            "smp": "SMP/MTs",
            "smp/mts": "SMP/MTs",
            "sma": "SMA/MA/Paket C",
            "sma/ma/paket-c": "SMA/MA/Paket C",
            "smk": "SMK/MAK",
            "smk/mak": "SMK/MAK",
            "kesetaraan": "Kesetaraan",
            "pendidikan-khusus": "Pendidikan Khusus",
        }
        return mapping.get(key, raw)

    def _format_phase(self, value: str) -> str:
        raw = str(value or "").strip()
        if not raw:
            return ""
        normalized = raw.upper().replace("FASE", "").strip()
        if normalized in {"A", "B", "C", "D", "E", "F"}:
            return f"Fase {normalized}"
        if normalized == "FONDASI":
            return "Fase Fondasi"
        return raw

    def _format_class_label(self, value: str, phase: str = "") -> str:
        raw = str(value or "").strip()
        mapping = {
            "kelas 1": "Kelas I",
            "kelas i": "Kelas I",
            "1": "Kelas I",
            "i": "Kelas I",
            "kelas 2": "Kelas II",
            "kelas ii": "Kelas II",
            "2": "Kelas II",
            "ii": "Kelas II",
            "kelas 3": "Kelas III",
            "kelas iii": "Kelas III",
            "3": "Kelas III",
            "iii": "Kelas III",
            "kelas 4": "Kelas IV",
            "kelas iv": "Kelas IV",
            "4": "Kelas IV",
            "iv": "Kelas IV",
            "kelas 5": "Kelas V",
            "kelas v": "Kelas V",
            "5": "Kelas V",
            "v": "Kelas V",
            "kelas 6": "Kelas VI",
            "kelas vi": "Kelas VI",
            "6": "Kelas VI",
            "vi": "Kelas VI",
            "kelas 7": "Kelas VII",
            "kelas vii": "Kelas VII",
            "7": "Kelas VII",
            "vii": "Kelas VII",
            "kelas 8": "Kelas VIII",
            "kelas viii": "Kelas VIII",
            "8": "Kelas VIII",
            "viii": "Kelas VIII",
            "kelas 9": "Kelas IX",
            "kelas ix": "Kelas IX",
            "9": "Kelas IX",
            "ix": "Kelas IX",
            "kelas 10": "Kelas X",
            "kelas x": "Kelas X",
            "10": "Kelas X",
            "x": "Kelas X",
            "kelas 11": "Kelas XI",
            "kelas xi": "Kelas XI",
            "11": "Kelas XI",
            "xi": "Kelas XI",
            "kelas 12": "Kelas XII",
            "kelas xii": "Kelas XII",
            "12": "Kelas XII",
            "xii": "Kelas XII",
        }
        normalized = raw.lower().replace("/", " ").replace("-", " ")
        normalized = " ".join(normalized.split())
        if normalized in mapping:
            return mapping[normalized]

        fallback_by_phase = {
            "fase a": "Kelas I",
            "fase b": "Kelas III",
            "fase c": "Kelas V",
            "fase d": "Kelas VII",
            "fase e": "Kelas X",
            "fase f": "Kelas XI",
        }
        phase_key = str(phase or "").strip().lower()
        if self._is_blank_identity_value(raw):
            return fallback_by_phase.get(phase_key, "")
        return raw

    def _format_jp(self, value: Any) -> str:
        if value is None:
            return ""
        try:
            number = int(value)
        except (TypeError, ValueError):
            return str(value).strip()
        return f"{number} JP" if number > 0 else ""

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

            assessment.pop("rubric", None)

            summative = assessment.get("summative") or {}
            content["assessment"] = {
                "summative": summative,
            }

        content.pop("rubric", None)

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
        title = content.get("title") or "RPM Pembelajaran"
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

        follow_up = content.get("followUp") or {}
        lines.extend(["", "## F. Tindak Lanjut Pembelajaran"])
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
        lines.extend(["", "## G. Refleksi Guru"])
        if teacher_reflection.get("description"):
            lines.append(str(teacher_reflection.get("description", "")))
        for question in teacher_reflection.get("questions") or []:
            question_text = str(question).strip()
            if question_text:
                lines.append(f"- {question_text}")

        lines.extend(["", "## H. Checklist Kelengkapan RPM"])
        for item in content.get("completionChecklist") or []:
            item_text = str(item.get("item", "")).strip()
            status_text = str(item.get("status", "")).strip()
            if item_text or status_text:
                lines.append(f"- {item_text}: {status_text}")

        if content.get("finalFlowSummary"):
            lines.extend(["", "## Ringkasan Alur Final"])
            lines.append(str(content.get("finalFlowSummary", "")))

        return "\n".join(lines)
