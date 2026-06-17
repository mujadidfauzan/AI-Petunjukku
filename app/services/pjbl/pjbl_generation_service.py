from __future__ import annotations

import json
import re
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
            query=payload.project.title or payload.project.subject or "RPM Kokurikuler",
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
                            "Susun struktur JSON awal RPM Kokurikuler berdasarkan sourceData. "
                            "Struktur ini adalah kontrak data untuk renderer DOCX, bukan file DOCX. "
                            "Gunakan Stage 1 sebagai konteks dasar, Stage 2 sebagai proyek terpilih, "
                            "dan summary Kina sebagai keputusan final diskusi. Return hanya JSON valid "
                            "dengan key contentJson dan contentMarkdown."
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
Anda adalah AI Service Petunjukku untuk menyusun struktur JSON awal RPM Kokurikuler.

Output wajib hanya JSON valid:
{
  "contentJson": {...},
  "contentMarkdown": "..."
}

Aturan:
- contentJson adalah kontrak data untuk renderer DOCX, bukan data mentah chat.
- Ikuti urutan visual dokumen: cover, daftar isi, identitas, profil dan arah,
  desain pembelajaran, rangkaian kegiatan, asesmen formatif, asesmen sumatif.
- Gunakan camelCase untuk key JSON.
- Gunakan istilah Bahasa Indonesia pada key yang merepresentasikan bagian dokumen.
- Jangan memasukkan komentar DOCX sebagai konten JSON.
- Jangan hardcode satu proyek tertentu; gunakan sourceData.
- Produk akhir wajib berupa array.
- Jumlah tahap/pertemuan fleksibel sesuai analisis Kina.
- Total JP wajib dihitung dari tahapKegiatan.
- Rubrik asesmen sumatif wajib mengikuti semua profil lulusan.
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
        teacher_profile = source_data.get("teacherProfile") or {}
        school = source_data.get("school") or {}
        teacher_class = source_data.get("teacherClass") or {}
        stage1 = source_data.get("stage1") or {}
        stage2 = source_data.get("stage2") or {}
        summary = source_data.get("kinaChatSummary") or {}

        school_context = self._as_dict(stage1.get("schoolContext"))
        area_context = self._as_dict(stage1.get("areaContext"))
        mission_spec = self._as_dict(stage1.get("missionSpec"))
        learning_duration = self._as_dict(mission_spec.get("learningDuration"))
        class_context = self._as_dict(stage1.get("classContext")) or teacher_class
        selected_project = self._selected_project(stage2)

        title = (
            selected_project.get("recommendedProjectTitle")
            or stage2.get("selectedProjectTitle")
            or project.get("title")
            or "RPM Kokurikuler"
        )
        education_level = (
            mission_spec.get("educationLevel")
            or teacher_profile.get("educationLevel")
            or "SMP/MTs"
        )
        phase = (
            mission_spec.get("educationPhase")
            or project.get("phase")
            or "Fase D"
        )
        grade = (
            mission_spec.get("className")
            or class_context.get("className")
            or project.get("gradeLevel")
            or ""
        )
        related_subjects = self._string_list(mission_spec.get("relatedSubjects"))
        if not related_subjects and project.get("subject"):
            related_subjects = [str(project["subject"])]

        product = self._product_list(summary, selected_project, stage2)
        profil_lulusan = self._profil_lulusan(stage2, summary)
        tahap_kegiatan = self._tahap_kegiatan(
            selected_project=selected_project,
            summary=summary,
            stage1=stage1,
            total_jp=self._duration_jp(learning_duration),
        )
        total_jp = self._calculate_total_jp(tahap_kegiatan)

        local_issue = compact_text(str(stage1.get("localIssue") or ""), 500)
        context_text = self._join(
            [
                local_issue,
                school_context.get("localContext"),
                area_context.get("regionalContext"),
            ]
        )
        risk_text = summary.get("riskMitigation") or self._join(
            self._string_list_from_risk(stage1.get("riskMonitoring"))
        )
        if not risk_text:
            risk_text = self._risk_text(selected_project)

        content = {
            "documentMeta": {
                "documentType": "RPM Kokurikuler",
                "templateName": "RPM Kokurikuler",
                "title": title,
                "subtitle": local_issue,
                "educationLevel": education_level,
                "grade": grade,
                "phase": phase,
                "generatedFrom": "kinaChatAnalysis",
                "version": "1.0",
            },
            "sectionOrder": self._section_order(),
            "cover": {
                "judulUtama": "RPM Kokurikuler",
                "judulProyek": title,
                "subjudul": selected_project.get("drivingQuestion")
                or stage2.get("drivingQuestion")
                or local_issue,
                "alokasiWaktuTotal": {
                    "jumlahJP": total_jp,
                    "label": f"{total_jp} JP",
                },
                "jenjang": education_level,
                "kelas": grade,
            },
            "daftarIsi": self._daftar_isi(),
            "identitasPembelajaran": {
                "namaSekolah": school_context.get("name") or school.get("name") or "",
                "namaGuru": teacher_profile.get("fullName") or "Guru PJBL",
                "jenjang": education_level,
                "fase": phase,
                "kelasSemester": grade,
                "bentukKokurikuler": "Projek Penguatan Profil Pelajar Pancasila",
                "alokasiWaktuTotal": {
                    "jumlahJP": total_jp,
                    "label": f"{total_jp} JP",
                },
                "produkAkhir": product,
                "mataPelajaranMuatanTerkait": related_subjects,
                "konteksProyek": context_text,
            },
            "profilDanArahPembelajaran": {
                "gambaranProyek": {
                    "deskripsi": summary.get("focusAndScope")
                    or selected_project.get("projectBackground")
                    or context_text,
                    "hasilYangDiharapkan": self._expected_results(
                        selected_project, summary
                    ),
                    "buktiBelajar": product,
                    "batasAmanKegiatan": risk_text,
                },
                "profilLulusan": profil_lulusan,
                "mataPelajaranMuatan": self._mata_pelajaran_muatan(related_subjects),
            },
            "desainPembelajaran": {
                "praktikPedagogis": {
                    "deskripsi": "Pembelajaran menggunakan pendekatan proyek kontekstual berbasis masalah nyata di lingkungan sekolah.",
                    "bentukPraktikPedagogis": self._praktik_pedagogis(),
                },
                "lingkunganBelajar": {
                    "lingkunganFisik": school_context.get("environment")
                    or school.get("schoolEnvironment")
                    or "",
                    "lingkunganSosial": mission_spec.get("classCondition")
                    or class_context.get("studentCharacteristics")
                    or "",
                    "lingkunganAman": risk_text,
                    "lingkunganReflektif": summary.get("assessmentReflection")
                    or "Guru menutup kegiatan dengan refleksi singkat siswa terhadap proses dan hasil proyek.",
                },
                "kemitraanPembelajaran": self._kemitraan(summary),
                "pemanfaatanDigital": self._pemanfaatan_digital(
                    school_context, school, summary
                ),
                "sumberDaya": self._sumber_daya(school_context, school, product),
            },
            "rangkaianKegiatan": {
                "deskripsiAlur": summary.get("activitiesAndSchedule")
                or self._join(selected_project.get("projectActivitiesOverview")),
                "totalTahap": len(tahap_kegiatan),
                "totalJP": total_jp,
                "tahapKegiatan": tahap_kegiatan,
            },
            "asesmenFormatif": self._asesmen_formatif(),
            "asesmenSumatif": {
                "deskripsi": "Penilaian kinerja dilakukan terhadap proses, produk, presentasi, dan refleksi proyek.",
                "sumberDimensi": "profilDanArahPembelajaran.profilLulusan",
                "rubrik": [],
            },
            "validationRules": self._validation_rules(),
        }
        self._sync_alokasi_waktu(content)
        self._ensure_sumative_rubric(content)
        self._validate_rpm_contract(content)
        return content

    def _normalize_content(
        self,
        content: dict[str, Any],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        normalized = self._deep_merge(dict(fallback), content)
        try:
            self._sync_alokasi_waktu(normalized)
            self._ensure_sumative_rubric(normalized)
            self._validate_rpm_contract(normalized)
        except ValueError:
            normalized = dict(fallback)
            self._sync_alokasi_waktu(normalized)
            self._ensure_sumative_rubric(normalized)
            self._validate_rpm_contract(normalized)
        return normalized

    def _section_order(self) -> list[str]:
        return [
            "cover",
            "daftarIsi",
            "identitasPembelajaran",
            "profilDanArahPembelajaran",
            "desainPembelajaran",
            "rangkaianKegiatan",
            "asesmenFormatif",
            "asesmenSumatif",
        ]

    def _daftar_isi(self) -> list[dict[str, Any]]:
        return [
            {
                "kode": "A",
                "judul": "Identitas Pembelajaran",
                "subbagian": [],
            },
            {
                "kode": "B",
                "judul": "Profil dan Arah Pembelajaran",
                "subbagian": [
                    "Gambaran Proyek",
                    "Profil Lulusan yang Dikembangkan",
                    "Mata Pelajaran/Muatan Terkait",
                ],
            },
            {
                "kode": "C",
                "judul": "Desain Pembelajaran",
                "subbagian": [
                    "Praktik Pedagogis",
                    "Lingkungan Belajar",
                    "Kemitraan Pembelajaran",
                    "Pemanfaatan Digital",
                    "Sumber Daya",
                ],
            },
            {
                "kode": "D",
                "judul": "Rangkaian Kegiatan Pembelajaran per Pertemuan",
                "subbagian": [
                    "Asesmen Formatif",
                    "Asesmen Sumatif - Penilaian Kinerja",
                ],
            },
        ]

    def _validation_rules(self) -> dict[str, Any]:
        return {
            "requiredTopLevelKeys": [
                "documentMeta",
                "sectionOrder",
                "cover",
                "daftarIsi",
                "identitasPembelajaran",
                "profilDanArahPembelajaran",
                "desainPembelajaran",
                "rangkaianKegiatan",
                "asesmenFormatif",
                "asesmenSumatif",
            ],
            "computedFields": {
                "rangkaianKegiatan.totalTahap": "count(rangkaianKegiatan.tahapKegiatan)",
                "rangkaianKegiatan.totalJP": "sum(rangkaianKegiatan.tahapKegiatan[].alokasiJP)",
                "identitasPembelajaran.alokasiWaktuTotal.jumlahJP": "rangkaianKegiatan.totalJP",
                "cover.alokasiWaktuTotal.jumlahJP": "rangkaianKegiatan.totalJP",
                "identitasPembelajaran.alokasiWaktuTotal.label": "`${totalJP} JP`",
                "cover.alokasiWaktuTotal.label": "`${totalJP} JP`",
            },
            "consistencyRules": [
                "sectionOrder harus menentukan urutan render DOCX.",
                "produkAkhir harus berupa array.",
                "jumlah tahapKegiatan fleksibel berdasarkan analisis chat Kina.",
                "alokasiJP pada setiap tahap wajib berupa number.",
                "totalJP wajib dihitung dari seluruh tahapKegiatan.",
                "komentar DOCX tidak boleh masuk sebagai konten JSON.",
                "rubrik asesmenSumatif harus dibuat untuk semua profilLulusan.",
                "pemanfaatanDigital tidak wajib muncul pada tahap, tetapi jika relevan sebaiknya dihubungkan melalui pemanfaatanDigitalTerkait.",
                "mataPelajaranMuatanTerkait pada identitas tidak wajib sama dengan mataPelajaranMuatan pada bagian profil.",
            ],
        }

    def _calculate_total_jp(self, tahap_kegiatan: list[dict[str, Any]]) -> int:
        total = 0
        for tahap in tahap_kegiatan:
            alokasi = tahap.get("alokasiJP", 0)
            if isinstance(alokasi, (int, float)):
                total += int(alokasi)
        return total

    def _sync_alokasi_waktu(self, content: dict[str, Any]) -> None:
        rangkaian = self._as_dict(content.get("rangkaianKegiatan"))
        tahap_kegiatan = rangkaian.get("tahapKegiatan")
        if not isinstance(tahap_kegiatan, list):
            tahap_kegiatan = []
        total_jp = self._calculate_total_jp(tahap_kegiatan)
        rangkaian["totalTahap"] = len(tahap_kegiatan)
        rangkaian["totalJP"] = total_jp
        content["rangkaianKegiatan"] = rangkaian

        for section_key in ("cover", "identitasPembelajaran"):
            section = self._as_dict(content.get(section_key))
            section["alokasiWaktuTotal"] = {
                "jumlahJP": total_jp,
                "label": f"{total_jp} JP",
            }
            content[section_key] = section

    def _ensure_sumative_rubric(self, content: dict[str, Any]) -> None:
        profil_section = self._as_dict(content.get("profilDanArahPembelajaran"))
        profil_lulusan = profil_section.get("profilLulusan")
        if not isinstance(profil_lulusan, list):
            profil_lulusan = []

        rubrik = []
        for profile in profil_lulusan:
            if not isinstance(profile, dict):
                continue
            nama = str(profile.get("nama") or "").strip()
            if not nama:
                continue
            rubrik.append(
                {
                    "dimensi": nama,
                    "aspek": f"Kinerja proyek yang menunjukkan {nama}",
                    "sangatBaik": f"Menunjukkan {nama} secara konsisten, mandiri, dan berdampak pada kualitas proses maupun produk proyek.",
                    "baik": f"Menunjukkan {nama} dengan baik pada sebagian besar proses dan produk proyek.",
                    "cukup": f"Mulai menunjukkan {nama}, tetapi masih perlu arahan pada beberapa bagian kegiatan.",
                    "perluBimbingan": f"Belum menunjukkan {nama} secara memadai dan membutuhkan pendampingan intensif dari guru.",
                }
            )

        asesmen_sumatif = self._as_dict(content.get("asesmenSumatif"))
        asesmen_sumatif["sumberDimensi"] = "profilDanArahPembelajaran.profilLulusan"
        asesmen_sumatif["rubrik"] = rubrik
        content["asesmenSumatif"] = asesmen_sumatif

    def _validate_rpm_contract(self, content: dict[str, Any]) -> None:
        required = self._validation_rules()["requiredTopLevelKeys"]
        missing = [key for key in required if key not in content]
        if missing:
            raise ValueError(f"RPM Kokurikuler missing keys: {missing}")

        invalid_order = [
            key for key in content.get("sectionOrder", []) if key not in content
        ]
        if invalid_order:
            raise ValueError(f"sectionOrder memuat key tidak tersedia: {invalid_order}")

        tahap_kegiatan = self._as_dict(content.get("rangkaianKegiatan")).get(
            "tahapKegiatan"
        )
        if not isinstance(tahap_kegiatan, list) or not tahap_kegiatan:
            raise ValueError("rangkaianKegiatan.tahapKegiatan tidak boleh kosong")

        required_stage_fields = [
            "judulTahap",
            "alokasiJP",
            "langkahGuru",
            "kegiatanMurid",
            "hasilYangDikumpulkan",
        ]
        for index, tahap in enumerate(tahap_kegiatan, start=1):
            if not isinstance(tahap, dict):
                raise ValueError(f"tahapKegiatan[{index}] harus object")
            for field in required_stage_fields:
                value = tahap.get(field)
                if value in (None, "", []):
                    raise ValueError(f"tahapKegiatan[{index}].{field} wajib diisi")
            if not isinstance(tahap.get("alokasiJP"), (int, float)):
                raise ValueError(f"tahapKegiatan[{index}].alokasiJP wajib number")
            if not isinstance(tahap.get("hasilYangDikumpulkan"), list):
                raise ValueError(
                    f"tahapKegiatan[{index}].hasilYangDikumpulkan wajib array"
                )

        profil_lulusan = self._as_dict(
            content.get("profilDanArahPembelajaran")
        ).get("profilLulusan")
        if not isinstance(profil_lulusan, list) or not profil_lulusan:
            raise ValueError("profilLulusan tidak boleh kosong")
        rubrik = self._as_dict(content.get("asesmenSumatif")).get("rubrik")
        if not isinstance(rubrik, list) or len(rubrik) < len(profil_lulusan):
            raise ValueError("rubrik asesmenSumatif wajib mengikuti semua profilLulusan")

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

    def _duration_jp(self, learning_duration: dict[str, Any]) -> int:
        jp_per_meeting = learning_duration.get("jpPerMeeting")
        meeting_count = learning_duration.get("meetingCount")
        if isinstance(jp_per_meeting, (int, float)) and isinstance(
            meeting_count, (int, float)
        ):
            total = int(jp_per_meeting * meeting_count)
            if total > 0:
                return total

        duration_text = str(learning_duration.get("durationText") or "")
        match = re.search(r"(\d+)\s*x\s*(\d+)", duration_text, flags=re.IGNORECASE)
        if match:
            return int(match.group(1))
        return 2

    def _tahap_kegiatan(
        self,
        selected_project: dict[str, Any],
        summary: dict[str, Any],
        stage1: dict[str, Any],
        total_jp: int,
    ) -> list[dict[str, Any]]:
        activities = self._string_list(selected_project.get("projectActivitiesOverview"))
        if not activities:
            activities = [
                "Pembukaan dan pembagian peran kelompok",
                "Observasi atau pengumpulan data",
                "Penyusunan produk proyek",
                "Presentasi singkat dan refleksi",
            ]

        product = self._product_list(summary, selected_project, selected_project)
        summary_schedule = summary.get("activitiesAndSchedule")
        digital_related = ["Proyektor"] if "proyektor" in self._flatten(stage1).lower() else []

        return [
            {
                "nomorTahap": 1,
                "judulTahap": selected_project.get("recommendedProjectTitle")
                or "Pelaksanaan Proyek",
                "alokasiJP": max(1, total_jp),
                "langkahGuru": self._join(
                    [
                        "Guru membuka dengan pertanyaan pemantik, menjelaskan tujuan proyek, membagi kelompok, memberi format observasi, memantau proses, dan memandu refleksi.",
                        summary.get("rolesAndSupport"),
                    ]
                ),
                "kegiatanMurid": summary_schedule or self._join(activities),
                "hasilYangDikumpulkan": product,
                "pemanfaatanDigitalTerkait": digital_related,
            }
        ]

    def _product_list(
        self,
        summary: dict[str, Any],
        selected_project: dict[str, Any],
        stage2: dict[str, Any],
    ) -> list[str]:
        products = self._string_list(selected_project.get("studentProduct"))
        if not products:
            products = self._string_list(stage2.get("studentProduct"))
        final_product = summary.get("finalProduct")
        if isinstance(final_product, str) and final_product.strip():
            products.insert(0, compact_text(final_product, 250))
        products = [item for item in products if item]
        return list(dict.fromkeys(products)) or ["Produk akhir proyek"]

    def _profil_lulusan(
        self,
        stage2: dict[str, Any],
        summary: dict[str, Any],
    ) -> list[dict[str, str]]:
        raw_profiles = (
            stage2.get("profilLulusan")
            or stage2.get("profileLulusan")
            or stage2.get("graduateProfiles")
            or summary.get("profilLulusan")
            or summary.get("graduateProfiles")
        )
        profiles: list[dict[str, str]] = []
        if isinstance(raw_profiles, list):
            for index, item in enumerate(raw_profiles, start=1):
                if isinstance(item, dict):
                    name = str(item.get("nama") or item.get("name") or "").strip()
                    description = str(
                        item.get("deskripsi") or item.get("description") or ""
                    ).strip()
                else:
                    name = str(item).strip()
                    description = ""
                if name:
                    profiles.append(
                        {
                            "id": self._profile_id(index, name),
                            "nama": name,
                            "deskripsi": description
                            or f"Peserta didik mengembangkan karakter {name} melalui proses proyek.",
                        }
                    )
        if profiles:
            return profiles
        return [
            {
                "id": "profil-1",
                "nama": "Bernalar Kritis",
                "deskripsi": "Peserta didik mengamati masalah, membaca data sederhana, dan menyimpulkan temuan secara logis.",
            },
            {
                "id": "profil-2",
                "nama": "Gotong Royong",
                "deskripsi": "Peserta didik bekerja dalam kelompok dengan pembagian peran dan tanggung jawab yang jelas.",
            },
            {
                "id": "profil-3",
                "nama": "Kreatif",
                "deskripsi": "Peserta didik menyajikan temuan proyek dalam produk yang jelas, menarik, dan mudah dipahami.",
            },
        ]

    def _profile_id(self, index: int, name: str) -> str:
        slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
        return slug or f"profil-{index}"

    def _expected_results(
        self,
        selected_project: dict[str, Any],
        summary: dict[str, Any],
    ) -> list[str]:
        objectives = self._string_list(selected_project.get("projectObjectives"))
        if objectives:
            return objectives
        focus = summary.get("focusAndScope")
        if isinstance(focus, str) and focus.strip():
            return [focus]
        return [
            "Peserta didik mampu memahami masalah nyata di lingkungan sekolah.",
            "Peserta didik mampu menghasilkan produk proyek sesuai konteks dan durasi.",
            "Peserta didik mampu mempresentasikan hasil dan melakukan refleksi singkat.",
        ]

    def _mata_pelajaran_muatan(self, subjects: list[str]) -> list[dict[str, str]]:
        return [
            {
                "nama": subject,
                "kontribusiPembelajaran": f"Muatan {subject} mendukung proses memahami masalah, mengolah informasi, dan menyajikan hasil proyek.",
            }
            for subject in subjects
        ]

    def _praktik_pedagogis(self) -> list[dict[str, str]]:
        return [
            {
                "nama": "Project Based Learning",
                "deskripsi": "Murid menyelesaikan masalah nyata melalui tahapan eksplorasi, produksi, presentasi, dan refleksi.",
            },
            {
                "nama": "Observasi Kontekstual",
                "deskripsi": "Murid mengumpulkan data sederhana dari lingkungan belajar yang dekat dengan keseharian mereka.",
            },
            {
                "nama": "Diskusi Kelompok",
                "deskripsi": "Murid membagi peran, menyepakati temuan, dan menyiapkan produk secara kolaboratif.",
            },
            {
                "nama": "Refleksi Terarah",
                "deskripsi": "Murid menuliskan pembelajaran dan tindak lanjut sederhana dari pengalaman proyek.",
            },
        ]

    def _kemitraan(self, summary: dict[str, Any]) -> list[dict[str, str]]:
        partnership_text = str(summary.get("facilitiesTechnologyPartnership") or "")
        if "tanpa mitra" in partnership_text.lower():
            return [
                {
                    "mitra": "Tidak menggunakan mitra luar",
                    "peranMitra": "Kegiatan difokuskan pada sumber daya internal sekolah.",
                }
            ]
        return [
            {
                "mitra": "Warga sekolah",
                "peranMitra": "Menjadi konteks pengamatan, penerima informasi, atau pemberi umpan balik sederhana sesuai kebutuhan proyek.",
            }
        ]

    def _pemanfaatan_digital(
        self,
        school_context: dict[str, Any],
        school: dict[str, Any],
        summary: dict[str, Any],
    ) -> list[dict[str, Any]]:
        text = self._flatten([school_context, school, summary]).lower()
        items: list[dict[str, Any]] = []
        if "proyektor" in text:
            items.append(
                {
                    "sumberDigital": "Proyektor",
                    "tautan": "",
                    "fungsiDalamPembelajaran": "Menampilkan pertanyaan pemantik, contoh format kerja, atau hasil presentasi kelompok.",
                    "disarankanMunculPadaTahap": [1],
                }
            )
        if not items:
            items.append(
                {
                    "sumberDigital": "Dokumentasi digital opsional",
                    "tautan": "",
                    "fungsiDalamPembelajaran": "Mendokumentasikan proses atau produk proyek jika perangkat tersedia.",
                    "disarankanMunculPadaTahap": [],
                }
            )
        return items

    def _sumber_daya(
        self,
        school_context: dict[str, Any],
        school: dict[str, Any],
        product: list[str],
    ) -> list[dict[str, str]]:
        facilities = self._string_list(school_context.get("facilities"))
        if not facilities:
            facilities = self._string_list(school.get("availableFacilities"))
        resources = [
            {
                "nama": item,
                "kategori": "alat atau fasilitas",
                "fungsi": "Mendukung pelaksanaan, dokumentasi, atau penyajian hasil proyek.",
            }
            for item in facilities
        ]
        for item in product:
            resources.append(
                {
                    "nama": item,
                    "kategori": "produk atau bukti belajar",
                    "fungsi": "Menjadi bukti hasil belajar dan bahan penilaian kinerja.",
                }
            )
        return resources or [
            {
                "nama": "Sumber daya kelas",
                "kategori": "sumber pendukung",
                "fungsi": "Mendukung aktivitas proyek sesuai ketersediaan sekolah.",
            }
        ]

    def _asesmen_formatif(self) -> dict[str, Any]:
        return {
            "deskripsi": "Asesmen formatif digunakan sebagai contoh template observasi proses, bukan data murid final.",
            "instrumenObservasi": {
                "tipe": "template",
                "kolom": [
                    "namaMurid",
                    "kolaborasi",
                    "kemandirian",
                    "komunikasi",
                    "catatanGuru",
                ],
                "contohBaris": [
                    {
                        "namaMurid": "",
                        "kolaborasi": "",
                        "kemandirian": "",
                        "komunikasi": "",
                        "catatanGuru": "",
                    }
                ],
            },
        }

    def _to_markdown(self, content: dict[str, Any]) -> str:
        meta = content.get("documentMeta") or {}
        cover = content.get("cover") or {}
        lines = [
            f"# {cover.get('judulUtama') or meta.get('documentType') or 'RPM Kokurikuler'}",
            "",
            f"## {cover.get('judulProyek') or meta.get('title') or ''}",
            "",
        ]

        identity = content.get("identitasPembelajaran") or {}
        lines.extend(["## A. Identitas Pembelajaran"])
        for key, value in identity.items():
            if value not in (None, "", [], {}):
                lines.append(f"- {key}: {self._markdown_value(value)}")

        profile = content.get("profilDanArahPembelajaran") or {}
        gambaran = profile.get("gambaranProyek") or {}
        lines.extend(["", "## B. Profil dan Arah Pembelajaran"])
        if gambaran.get("deskripsi"):
            lines.append(f"- Gambaran Proyek: {gambaran['deskripsi']}")
        for item in gambaran.get("hasilYangDiharapkan") or []:
            lines.append(f"- Hasil yang Diharapkan: {item}")
        for item in profile.get("profilLulusan") or []:
            lines.append(f"- Profil Lulusan: {item.get('nama')} - {item.get('deskripsi')}")

        design = content.get("desainPembelajaran") or {}
        lines.extend(["", "## C. Desain Pembelajaran"])
        pedagogis = (design.get("praktikPedagogis") or {}).get(
            "bentukPraktikPedagogis"
        ) or []
        for item in pedagogis:
            lines.append(f"- Praktik Pedagogis: {item.get('nama')} - {item.get('deskripsi')}")

        rangkaian = content.get("rangkaianKegiatan") or {}
        lines.extend(["", "## D. Rangkaian Kegiatan Pembelajaran per Pertemuan"])
        lines.append(f"- Total JP: {rangkaian.get('totalJP', 0)} JP")
        for tahap in rangkaian.get("tahapKegiatan") or []:
            lines.append(f"### Tahap {tahap.get('nomorTahap')}: {tahap.get('judulTahap')}")
            lines.append(f"- Alokasi: {tahap.get('alokasiJP')} JP")
            lines.append(f"- Langkah Guru: {tahap.get('langkahGuru')}")
            lines.append(f"- Kegiatan Murid: {tahap.get('kegiatanMurid')}")
            lines.append(
                f"- Hasil yang Dikumpulkan: {self._markdown_value(tahap.get('hasilYangDikumpulkan'))}"
            )

        lines.extend(["", "## Asesmen Formatif"])
        lines.append((content.get("asesmenFormatif") or {}).get("deskripsi", ""))

        lines.extend(["", "## Asesmen Sumatif - Penilaian Kinerja"])
        for item in (content.get("asesmenSumatif") or {}).get("rubrik") or []:
            lines.append(f"- {item.get('dimensi')}: {item.get('aspek')}")
        return "\n".join(lines)

    def _markdown_value(self, value: Any) -> str:
        if isinstance(value, list):
            return ", ".join(str(item) for item in value)
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

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

    def _deep_merge(self, base: dict[str, Any], overlay: dict[str, Any]) -> dict[str, Any]:
        for key, value in overlay.items():
            if value in (None, "", [], {}):
                continue
            if isinstance(value, dict) and isinstance(base.get(key), dict):
                base[key] = self._deep_merge(dict(base[key]), value)
            else:
                base[key] = value
        return base

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
            return compact_text(
                " ".join(str(item) for item in value if str(item).strip()), 900
            )
        return compact_text(str(value or ""), 900)

    def _flatten(self, value: Any) -> str:
        try:
            return json.dumps(value, ensure_ascii=False)
        except TypeError:
            return str(value)

    def _dump(self, value: Any) -> dict[str, Any]:
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if isinstance(value, dict):
            return value
        return {}
