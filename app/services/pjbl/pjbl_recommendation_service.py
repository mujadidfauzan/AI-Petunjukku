from __future__ import annotations

import json
import logging
import re
from typing import Any

from app.schemas.recommendation_schema import (
    RecommendStageRequest,
    RecommendStageResponse,
)
from app.services.llm_client import LLMClient
from app.services.pjbl.pjbl_prompt_templates import PJBL_RECOMMENDATION_SYSTEM_PROMPT
from app.services.prompt_builder_service import PromptBuilderService
from app.services.rag_service import RAGService
from fastapi import HTTPException, status

logger = logging.getLogger(__name__)


class PjblRecommendationService:
    def __init__(
        self,
        rag_service: RAGService | None = None,
        llm_client: LLMClient | None = None,
        prompt_builder: PromptBuilderService | None = None,
    ) -> None:
        self.rag_service = rag_service or RAGService()
        self.llm_client = llm_client or LLMClient()
        self.prompt_builder = prompt_builder or PromptBuilderService()

    async def recommend(self, payload: RecommendStageRequest) -> RecommendStageResponse:
        target_stage = payload.targetStage
        selected_theme = self._selected_theme(payload)
        recommendation_type = self._recommendation_type(payload, selected_theme)
        target_stage_number = target_stage.get("stageNumber")
        references = []
        stage_context = self._flatten_stage_context(
            next(
                (
                    stage.contentJson
                    for stage in payload.previousStages
                    if stage.stageNumber == 1
                ),
                {},
            )
        )
        subjects = self._subjects(payload, stage_context)
        environment_context = self._environment_context(
            payload,
            stage_context,
            subjects,
        )
        required_response_shape = self._required_response_shape(recommendation_type)
        project_input = payload.project.model_dump()
        if subjects and self._is_generic_subject(project_input.get("subject")):
            project_input["resolvedSubject"] = ", ".join(subjects)
        llm_input = {
            "project": project_input,
            "subjectContext": {
                "mainSubjects": subjects,
                "subjectLens": " & ".join(subjects[:2]) if subjects else "",
                "instruction": (
                    "Tema dan opsi wajib selaras dengan mainSubjects. Abaikan kategori "
                    "tempat mentah yang hanya cocok untuk mata pelajaran lain."
                ),
            },
            "teacherProfile": (
                payload.teacherProfile.model_dump() if payload.teacherProfile else {}
            ),
            "school": payload.school.model_dump() if payload.school else {},
            "teacherClass": (
                payload.teacherClass.model_dump() if payload.teacherClass else {}
            ),
            "previousStages": [stage.model_dump() for stage in payload.previousStages],
            "targetStage": target_stage,
            "environmentContext": environment_context,
            "ragReferences": [reference.model_dump() for reference in references],
            "requiredResponseShape": required_response_shape,
        }
        messages = [
            {
                "role": "system",
                "content": PJBL_RECOMMENDATION_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": json.dumps(llm_input, ensure_ascii=False),
            },
        ]
        logger.info(
            "[PjBL Recommend] LLM input (%s):\n%s",
            recommendation_type,
            json.dumps(llm_input, ensure_ascii=False, indent=2, default=str),
        )
        try:
            generated = await self.llm_client.generate_json_strict(
                messages,
                temperature=0.7,
            )
        except Exception as exc:
            logger.warning(
                "[PjBL Recommend] LLM error (%s): %s",
                recommendation_type,
                exc,
            )
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail="Ada error saat memanggil LLM. Rekomendasi belum dapat dibuat.",
            ) from exc
        logger.info(
            "[PjBL Recommend] LLM raw output (%s):\n%s",
            recommendation_type,
            json.dumps(generated, ensure_ascii=False, indent=2, default=str),
        )
        self._assert_llm_output_valid(generated, recommendation_type)
        recommendations = self._normalize_recommendations(
            generated,
            self._normalization_context(
                recommendation_type,
                environment_context,
                subjects,
            ),
        )
        logger.info(
            "[PjBL Recommend] API normalized output (%s):\n%s",
            recommendation_type,
            json.dumps(recommendations, ensure_ascii=False, indent=2, default=str),
        )
        return RecommendStageResponse(
            rppType=payload.project.rppType,
            recommendationType=recommendation_type,
            targetStageNumber=(
                int(target_stage_number) if target_stage_number is not None else None
            ),
            ragReferences=references,
            recommendations=recommendations,
        )

    def _recommendation_type(
        self,
        payload: RecommendStageRequest,
        selected_theme: Any,
    ) -> str:
        requested_type = self._first_text(
            (
                payload.targetStage.get("recommendationType")
                if isinstance(payload.targetStage, dict)
                else None
            ),
            (
                payload.options.get("recommendationType")
                if isinstance(payload.options, dict)
                else None
            ),
            "",
        )
        allowed_types = {
            "project_theme_recommendation",
            "project_recommendation",
        }
        if requested_type:
            if requested_type not in allowed_types:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "recommendationType PjBL tidak didukung: " f"{requested_type}"
                    ),
                )
            if requested_type == "project_recommendation" and not selected_theme:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=(
                        "selectedTheme wajib dikirim untuk recommendationType "
                        "project_recommendation."
                    ),
                )
            return requested_type

        return (
            "project_recommendation"
            if selected_theme
            else "project_theme_recommendation"
        )

    def _required_response_shape(self, recommendation_type: str) -> dict[str, Any]:
        if recommendation_type == "project_theme_recommendation":
            return {
                "projectThemes": [
                    {"label": ""},
                    {"label": ""},
                    {"label": ""},
                ]
            }
        return {
            "projectOptions": [
                {
                    "id": "...",
                    "title": "...",
                    "themeId": "...",
                    "themeLabel": "...",
                    "description": "...",
                    "lens": "...",
                    "overview": "...",
                    "confirmationTags": [{"id": "...", "label": "..."}],
                    "clarificationQuestions": [
                        {
                            "id": "...",
                            "inputType": "textarea",
                            "label": "...",
                            "placeholder": "...",
                            "required": True,
                        }
                    ],
                    "reasoningSummary": "...",
                }
            ],
            "selectionGuidance": "...",
            "reasoningSummary": "...",
        }

    def _normalization_context(
        self,
        recommendation_type: str,
        environment_context: dict[str, Any],
        subjects: list[str],
    ) -> dict[str, Any]:
        if recommendation_type == "project_theme_recommendation":
            return {
                "projectThemes": [],
                "_meta": {
                    "blockedThemeKeywords": (
                        self._blocked_theme_keywords(subjects)
                        + self._omitted_theme_keywords(environment_context)
                    ),
                    "subjectAlignedThemeLabels": [],
                },
            }
        return {
            "projectOptions": [],
            "selectionGuidance": "",
            "reasoningSummary": "",
        }

    def _assert_llm_output_valid(
        self,
        generated: dict[str, Any],
        recommendation_type: str,
    ) -> None:
        if recommendation_type == "project_theme_recommendation":
            themes = generated.get("projectThemes")
            if not isinstance(themes, list) or len(themes) != 3:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        "Ada error pada output LLM. projectThemes harus berisi "
                        "tepat 3 tema."
                    ),
                )
            for theme in themes:
                label = (
                    theme.get("label")
                    if isinstance(theme, dict)
                    else theme if isinstance(theme, str) else ""
                )
                if not self._first_text(label, ""):
                    raise HTTPException(
                        status_code=status.HTTP_502_BAD_GATEWAY,
                        detail=(
                            "Ada error pada output LLM. Setiap tema wajib memiliki label."
                        ),
                    )
            return

        options = generated.get("projectOptions")
        if not isinstance(options, list) or len(options) != 3:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=(
                    "Ada error pada output LLM. projectOptions harus berisi "
                    "tepat 3 opsi proyek."
                ),
            )

        required_text_fields = (
            "title",
            "description",
            "lens",
            "overview",
            "reasoningSummary",
        )
        for option in options:
            if not isinstance(option, dict):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail="Ada error pada output LLM. Setiap opsi proyek harus object.",
                )
            missing_text = [
                field
                for field in required_text_fields
                if not self._first_text(option.get(field), "")
            ]
            if missing_text:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        "Ada error pada output LLM. Field opsi proyek belum lengkap: "
                        + ", ".join(missing_text)
                    ),
                )
            if not isinstance(option.get("confirmationTags"), list):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        "Ada error pada output LLM. confirmationTags harus berupa list."
                    ),
                )
            if not isinstance(option.get("clarificationQuestions"), list):
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=(
                        "Ada error pada output LLM. clarificationQuestions harus berupa list."
                    ),
                )

    def _fallback_recommendations(
        self,
        payload: RecommendStageRequest,
        recommendation_type: str,
        references: list[Any],
        *,
        stage_context: dict[str, Any] | None = None,
        environment_context: dict[str, Any] | None = None,
        subjects: list[str] | None = None,
    ) -> dict[str, Any]:
        stage_context = stage_context or self._flatten_stage_context(
            next(
                (
                    stage.contentJson
                    for stage in payload.previousStages
                    if stage.stageNumber == 1
                ),
                {},
            )
        )
        subjects = subjects or self._subjects(payload, stage_context)
        environment_context = environment_context or self._environment_context(
            payload,
            stage_context,
            subjects,
        )
        subject_context = (
            ", ".join(subjects) or payload.project.title or "mata pelajaran terkait"
        )
        school_name = self._first_text(
            getattr(payload.school, "name", None) if payload.school else None,
            "lingkungan sekolah",
        )
        city = self._first_text(
            getattr(payload.school, "city", None) if payload.school else None,
            getattr(payload.school, "district", None) if payload.school else None,
            "",
        )
        subject_lens = " & ".join(subjects[:2]) if subjects else "Lintas Disiplin"
        local_issue = self._first_text(
            stage_context.get("localIssue"),
            environment_context.get("summary"),
            stage_context.get("studentNotes"),
            stage_context.get("kondisiKelas"),
            stage_context.get("localContext"),
            getattr(payload.school, "localContext", None) if payload.school else None,
            (
                getattr(payload.school, "schoolEnvironment", None)
                if payload.school
                else None
            ),
            subject_context,
        )
        grade_label = self._first_text(
            stage_context.get("fase"),
            payload.project.phase,
            payload.project.gradeLevel,
            "fase/kelas yang dipilih",
        )
        selected_theme = self._selected_theme(payload)
        if not selected_theme:
            themes = self._fallback_project_themes(
                stage_context=stage_context,
                environment_context=environment_context,
                subjects=subjects,
                subject_lens=subject_lens,
                local_issue=local_issue,
            )
            return {
                "projectThemes": themes[:3],
                "_meta": {
                    "subjectLens": subject_lens,
                    "subjectAlignedThemeLabels": [
                        theme["label"]
                        for theme in themes[:3]
                        if isinstance(theme, dict)
                    ],
                    "blockedThemeKeywords": (
                        self._blocked_theme_keywords(subjects)
                        + self._omitted_theme_keywords(environment_context)
                    ),
                },
                "selectionGuidance": (
                    "Pilih satu tema yang paling dekat dengan konteks sekolah, "
                    "aman dijalankan, dan sesuai dengan mata pelajaran serta durasi."
                ),
                "reasoningSummary": (
                    "Tema proyek disusun dari informasi sekolah, pemindai lingkungan, "
                    "pemantauan risiko, spesifikasi misi, dan kondisi kelas pada Stage 1."
                ),
            }

        selected_theme_label = self._theme_label(selected_theme)
        places = environment_context.get("places")
        if not isinstance(places, list):
            places = []
        options = self._fallback_project_options(
            selected_theme_label=selected_theme_label,
            subject_lens=subject_lens,
            places=places,
            local_issue=local_issue,
            school_name=school_name,
            city=city,
            grade_label=grade_label,
            stage_context=stage_context,
        )
        return {
            "projectOptions": options,
            "selectionGuidance": (
                "Pilih opsi yang paling mudah diberi izin, paling aman, dan paling "
                "sesuai dengan alokasi waktu kelas."
            ),
            "reasoningSummary": (
                f"Rekomendasi {recommendation_type} disusun dari konteks Stage 1, "
                "profil sekolah, karakteristik kelas, fasilitas, dan batasan pelaksanaan."
            ),
        }

    def _fallback_project_options(
        self,
        *,
        selected_theme_label: str,
        subject_lens: str,
        places: list[Any],
        local_issue: str,
        school_name: str,
        city: str,
        grade_label: str,
        stage_context: dict[str, Any],
    ) -> list[dict[str, Any]]:
        theme_id = self._slug(selected_theme_label, "tema-terpilih")
        place_labels = [
            self._place_label(places, index, "") for index in range(min(len(places), 6))
        ]
        place_labels = [label for label in place_labels if label]
        if not place_labels:
            place_labels = [
                "lingkungan sekolah",
                "ruang belajar dan fasilitas sekolah",
                "warga sekolah dan lokasi terdekat",
            ]
        categories = self._place_categories(places)
        evidence = self._first_text(
            ", ".join(categories[:3]),
            "catatan observasi, dokumentasi visual, data sederhana, dan wawancara singkat",
        )
        theme_text = selected_theme_label.casefold()
        subject_text = (
            f"{subject_lens} {stage_context.get('mainSubjects', '')}".casefold()
        )
        context_text = f"{theme_text} {subject_text} {local_issue}".casefold()
        context_seed = sum(
            ord(char)
            for char in " ".join(
                [
                    selected_theme_label,
                    subject_lens,
                    local_issue,
                    " ".join(place_labels),
                    city,
                ]
            )
        )

        patterns = [
            {
                "key": "galeri",
                "score": 0,
                "keywords": ("seni", "budaya", "visual", "tradisi", "karya"),
                "title": "Cerita Visual {theme} dari {place}",
                "product": "kumpulan karya visual dengan keterangan singkat yang menjelaskan makna tiap karya",
                "activity": "siswa memilih objek, suasana, atau praktik lokal yang terlihat di {place}, lalu mengolahnya menjadi gambar, kolase, atau karya sederhana",
                "data": "sketsa lapangan, foto referensi yang berizin, catatan warna/bentuk, dan cerita warga sekolah",
                "lens_suffix": " & Ekspresi Visual",
            },
            {
                "key": "arsip",
                "score": 0,
                "keywords": (
                    "sejarah",
                    "budaya",
                    "tradisi",
                    "museum",
                    "tokoh",
                    "perubahan",
                ),
                "title": "Cerita Perubahan {theme} di {place}",
                "product": "linimasa sederhana dan cerita singkat yang dapat dibaca teman sekelas",
                "activity": "siswa mencari perubahan, tokoh, benda, atau cerita yang berkaitan dengan {place}",
                "data": "wawancara singkat, catatan observasi, dokumentasi tempat, dan perbandingan kondisi dulu-kini",
                "lens_suffix": " & Cerita Lokal",
            },
            {
                "key": "prototipe",
                "score": 0,
                "keywords": (
                    "teknologi",
                    "informatika",
                    "fasilitas",
                    "lingkungan",
                    "layanan",
                    "solusi",
                ),
                "title": "Ide Perbaikan Kecil untuk {place}",
                "product": "usulan perbaikan kecil berisi alasan, langkah, dan perkiraan kebutuhan",
                "activity": "siswa menemukan satu kebutuhan nyata di {place}, membuat beberapa ide perbaikan, lalu memilih yang paling mungkin dilakukan",
                "data": "daftar kebutuhan pengguna, foto kondisi, hasil uji coba kecil, dan masukan teman",
                "lens_suffix": " & Aksi Nyata",
            },
            {
                "key": "dokumenter",
                "score": 0,
                "keywords": (
                    "bahasa",
                    "cerita",
                    "komunikasi",
                    "sosial",
                    "budaya",
                    "sejarah",
                ),
                "title": "Suara Warga Sekolah tentang {theme}",
                "product": "kutipan pilihan, ringkasan temuan, dan bahan presentasi singkat",
                "activity": "siswa menyusun pertanyaan sederhana, mendengar cerita warga sekolah, lalu memilih kutipan yang paling membantu memahami tema",
                "data": "kutipan narasumber, rekaman suasana, catatan observasi, dan daftar izin publikasi",
                "lens_suffix": " & Komunikasi",
            },
            {
                "key": "simulasi",
                "score": 0,
                "keywords": (
                    "risiko",
                    "ekonomi",
                    "keputusan",
                    "pasar",
                    "usaha",
                    "mitigasi",
                ),
                "title": "Pilihan Keputusan dari Kasus di {place}",
                "product": "tabel pilihan tindakan, alasan pro-kontra, dan keputusan kelompok",
                "activity": "siswa mengambil satu kasus dari {place}, membuat beberapa pilihan tindakan, lalu membandingkan dampak tiap pilihan",
                "data": "data situasi, kemungkinan risiko, pilihan tindakan, dan alasan pro-kontra",
                "lens_suffix": " & Keputusan Berbasis Data",
            },
            {
                "key": "panduan",
                "score": 0,
                "keywords": (
                    "aman",
                    "etika",
                    "layanan",
                    "fasilitas",
                    "kesehatan",
                    "sosial",
                ),
                "title": "Kebiasaan Baik yang Bisa Dicoba di {place}",
                "product": "daftar langkah sederhana dan contoh penerapannya di sekolah",
                "activity": "siswa mengamati kebiasaan atau kebutuhan di {place}, lalu merumuskan langkah baik yang mudah diikuti",
                "data": "hasil observasi perilaku, catatan risiko, masukan warga sekolah, dan contoh praktik yang sudah berjalan",
                "lens_suffix": " & Sikap Sosial",
            },
            {
                "key": "tur",
                "score": 0,
                "keywords": (
                    "sejarah",
                    "budaya",
                    "geografi",
                    "tempat",
                    "ruang",
                    "lingkungan",
                ),
                "title": "Rute Belajar {theme} di Sekitar {school}",
                "product": "rute belajar singkat, kartu informasi lokasi, dan catatan keamanan",
                "activity": "siswa menyusun rute aman yang menghubungkan beberapa titik sekitar sekolah dan menjelaskan alasan memilih tiap titik",
                "data": "nama titik, jarak, alasan pemilihan, catatan keamanan, dan cerita singkat tiap lokasi",
                "lens_suffix": " & Ruang Lokal",
            },
            {
                "key": "eksperimen",
                "score": 0,
                "keywords": ("ipa", "sains", "kesehatan", "air", "tanaman", "cuaca"),
                "title": "Uji Sederhana tentang {theme} di {place}",
                "product": "tabel hasil pengamatan dan kesimpulan sederhana berbasis bukti",
                "activity": "siswa merancang pengamatan sederhana di {place}, mengukur indikator yang aman, lalu membandingkan hasilnya",
                "data": "hasil ukur sederhana, kondisi lokasi, foto proses, dan catatan variabel pengganggu",
                "lens_suffix": " & Bukti Lapangan",
            },
            {
                "key": "festival",
                "score": 0,
                "keywords": (
                    "kolaborasi",
                    "komunitas",
                    "pameran",
                    "apresiasi",
                    "pengunjung",
                ),
                "title": "Berbagi Karya {theme} dengan Warga Sekolah",
                "product": "sesi berbagi karya, catatan tanggapan pengunjung, dan refleksi kelompok",
                "activity": "siswa menyiapkan cara sederhana untuk membagikan temuan, karya, atau cerita dari lingkungan sekolah kepada warga sekolah",
                "data": "hasil kurasi karya, kebutuhan alat, alur pengunjung, dan umpan balik warga sekolah",
                "lens_suffix": " & Apresiasi",
            },
            {
                "key": "rancang-layanan",
                "score": 0,
                "keywords": ("layanan", "fasilitas", "sosial", "kebutuhan", "bantuan"),
                "title": "Alur Bantuan Sederhana untuk Kebutuhan di {place}",
                "product": "alur bantuan sederhana, pembagian peran, dan rencana uji coba terbatas",
                "activity": "siswa mengidentifikasi kebutuhan pengguna di {place}, membuat alur bantuan sederhana, lalu meminta masukan dari calon pengguna",
                "data": "profil pengguna, masalah utama, alur layanan, dan catatan masukan",
                "lens_suffix": " & Kepedulian Sosial",
            },
        ]

        for pattern in patterns:
            keywords = pattern["keywords"]
            pattern["score"] = sum(1 for keyword in keywords if keyword in context_text)
        selected_patterns = sorted(
            patterns,
            key=lambda item: (
                -int(item["score"]),
                (context_seed + patterns.index(item) * 7) % len(patterns),
            ),
        )
        if not any(int(item["score"]) > 0 for item in selected_patterns):
            selected_patterns = [
                patterns[index]
                for index in self._pattern_indexes(
                    f"{selected_theme_label}-{subject_lens}-{local_issue}",
                    len(patterns),
                )
            ]
        selected_patterns = selected_patterns[:3]

        options: list[dict[str, Any]] = []
        for index, pattern in enumerate(selected_patterns):
            place = place_labels[index % len(place_labels)]
            title = str(pattern["title"]).format(
                theme=selected_theme_label,
                place=place,
                school=school_name,
                city=city,
            )
            activity = str(pattern["activity"]).format(place=place)
            data = str(pattern["data"])
            product = str(pattern["product"])
            lens = f"{subject_lens}{pattern['lens_suffix']}"
            option_id = self._slug(
                f"{pattern['key']}-{selected_theme_label}-{place}", f"opsi-{index + 1}"
            )
            options.append(
                {
                    "id": option_id,
                    "title": title,
                    "themeId": theme_id,
                    "themeLabel": selected_theme_label,
                    "description": (
                        f"{activity.capitalize()} sebagai proyek {grade_label} "
                        f"yang terkait dengan {selected_theme_label}."
                    ),
                    "lens": lens,
                    "overview": self._fallback_option_overview(
                        pattern_key=str(pattern["key"]),
                        title=title,
                        theme_label=selected_theme_label,
                        place=place,
                        school_name=school_name,
                        subject_lens=subject_lens,
                        product=product,
                    ),
                    "confirmationTags": self._project_pattern_tags(pattern["key"]),
                    "clarificationQuestions": self._project_pattern_questions(
                        pattern_key=str(pattern["key"]),
                        place=place,
                        product=product,
                    ),
                    "reasoningSummary": (
                        f"Opsi ini dipilih karena bentuk proyeknya cocok dengan "
                        f"{subject_lens}, tema {selected_theme_label}, dan konteks "
                        "lingkungan yang tersedia."
                    ),
                }
            )
        return options

    def _pattern_indexes(self, selected_theme_label: str, count: int) -> list[int]:
        seed = sum(ord(char) for char in selected_theme_label)
        indexes: list[int] = []
        step = 3 if count % 3 != 0 else 5
        cursor = seed % max(count, 1)
        while len(indexes) < count:
            if cursor not in indexes:
                indexes.append(cursor)
            cursor = (cursor + step) % count
        return indexes

    def _fallback_option_overview(
        self,
        *,
        pattern_key: str,
        title: str,
        theme_label: str,
        place: str,
        school_name: str,
        subject_lens: str,
        product: str,
    ) -> str:
        place_text = self._clean_place_reference(place)
        subject_text = self._natural_subject_lens(subject_lens)
        school_text = school_name if school_name != "lingkungan sekolah" else "sekolah"
        templates: dict[str, tuple[str, str, str]] = {
            "galeri": (
                f"Proyek ini mengajak siswa melihat {theme_label} melalui objek, suasana, atau kebiasaan yang bisa diamati di {place_text}.",
                f"Di sekolah, siswa mengamati lokasi, membuat sketsa atau dokumentasi berizin, lalu mengolah temuan itu menjadi karya sederhana dengan sudut pandang {subject_text}.",
                f"Hasil akhirnya berupa {product} yang dapat dipajang atau dipresentasikan untuk menjelaskan hubungan karya dengan konteks {school_text}.",
            ),
            "arsip": (
                f"Proyek ini membantu siswa menelusuri cerita perubahan yang berkaitan dengan {theme_label} di {place_text}.",
                f"Siswa mengumpulkan cerita dari observasi, sumber lokal, atau wawancara singkat, lalu menyusun urutan peristiwa dan makna yang mudah dipahami teman sekelas.",
                f"Produk akhirnya berupa {product} yang menghubungkan pembelajaran {subject_text} dengan lingkungan nyata {school_text}.",
            ),
            "prototipe": (
                f"Proyek ini dimulai dari satu kebutuhan nyata yang terlihat di {place_text}.",
                f"Siswa mengamati masalahnya, memilih ide perbaikan yang sederhana, lalu membuat rancangan solusi yang mungkin dicoba di lingkungan {school_text}.",
                f"Produk akhirnya berupa {product}, lengkap dengan alasan mengapa solusi itu sesuai dengan tema {theme_label}.",
            ),
            "dokumenter": (
                f"Proyek ini mengajak siswa memahami {theme_label} dari cerita warga sekolah dan pengamatan sekitar {place_text}.",
                f"Siswa menyiapkan pertanyaan, mengumpulkan kutipan atau catatan lapangan, lalu memilih temuan yang paling kuat untuk dibahas bersama.",
                f"Produk akhirnya berupa {product} yang menunjukkan keterkaitan {subject_text} dengan kehidupan sehari-hari di {school_text}.",
            ),
            "simulasi": (
                f"Proyek ini memakai kasus nyata di {place_text} sebagai bahan belajar tentang {theme_label}.",
                f"Siswa mengamati situasi, menyusun beberapa pilihan tindakan, lalu membandingkan dampak baik, risiko, dan alasan dari tiap pilihan dalam diskusi kelompok.",
                f"Produk akhirnya berupa {product} yang membantu siswa mengambil keputusan berbasis bukti sesuai konteks {school_text}.",
            ),
            "panduan": (
                f"Proyek ini berfokus pada kebiasaan baik yang bisa diterapkan di {place_text}.",
                f"Siswa mengamati perilaku atau kebutuhan yang muncul, mendiskusikan contoh yang sudah baik, lalu menyusun langkah sederhana yang bisa dicoba warga sekolah.",
                f"Produk akhirnya berupa {product} yang dekat dengan tema {theme_label} dan mudah digunakan di {school_text}.",
            ),
            "tur": (
                f"Proyek ini mengubah lingkungan sekitar {school_text} menjadi rute belajar tentang {theme_label}.",
                f"Siswa memilih beberapa titik yang aman, menjelaskan alasan pemilihannya, lalu menulis cerita singkat untuk setiap titik dengan sudut pandang {subject_text}.",
                f"Produk akhirnya berupa {product} yang dapat dipakai sebagai bahan presentasi atau panduan belajar kelas.",
            ),
            "eksperimen": (
                f"Proyek ini mengajak siswa menguji pertanyaan sederhana tentang {theme_label} di {place_text}.",
                f"Siswa menentukan indikator yang aman diamati, mencatat hasilnya secara teratur, lalu membandingkan temuan antar kelompok.",
                f"Produk akhirnya berupa {product} yang menunjukkan cara siswa memakai bukti lapangan dalam pembelajaran {subject_text}.",
            ),
            "festival": (
                f"Proyek ini memberi ruang bagi siswa untuk membagikan temuan atau karya tentang {theme_label} kepada warga {school_text}.",
                f"Siswa memilih hasil terbaik dari pengamatan, menyiapkan cara penyajian yang sederhana, lalu meminta tanggapan dari teman atau warga sekolah.",
                f"Produk akhirnya berupa {product} yang membuat pembelajaran terasa nyata dan bisa diapresiasi bersama.",
            ),
            "rancang-layanan": (
                f"Proyek ini dimulai dari kebutuhan warga sekolah yang terlihat di {place_text}.",
                f"Siswa mengamati siapa yang membutuhkan bantuan, menyusun alur bantuan sederhana, lalu meminta masukan agar rancangannya realistis dilakukan di {school_text}.",
                f"Produk akhirnya berupa {product} yang mengaitkan tema {theme_label} dengan kepedulian dan pemecahan masalah sehari-hari.",
            ),
        }
        sentences = templates.get(
            pattern_key,
            (
                f"Proyek {title} memakai konteks {place_text} agar siswa melihat {theme_label} dalam situasi yang dekat dengan sekolah.",
                f"Siswa mengumpulkan bukti sederhana, mendiskusikan maknanya dengan sudut pandang {subject_text}, lalu menyusun hasil yang bisa ditinjau guru.",
                f"Produk akhirnya berupa {product} yang relevan untuk konteks {school_text}.",
            ),
        )
        return " ".join(sentences)

    def _clean_place_reference(self, place: str) -> str:
        text = re.sub(r"\s+", " ", self._first_text(place, "lingkungan sekolah"))
        text = re.sub(r"\s*\([^)]*\)", "", text).strip(" .")
        return text or "lingkungan sekolah"

    def _natural_subject_lens(self, subject_lens: str) -> str:
        text = re.sub(
            r"\s*&\s*", " dan ", self._first_text(subject_lens, "lintas disiplin")
        )
        return text.strip() or "lintas disiplin"

    def _project_pattern_tags(self, pattern_key: Any) -> list[dict[str, str]]:
        common = [{"id": "izin", "label": "Izin dan etika aman"}]
        tags_by_pattern: dict[str, list[dict[str, str]]] = {
            "galeri": [
                {"id": "media_karya", "label": "Media karya tersedia"},
                {"id": "kurasi", "label": "Kriteria kurasi jelas"},
            ],
            "arsip": [
                {"id": "sumber", "label": "Sumber cerita terverifikasi"},
                {"id": "narasumber", "label": "Narasumber aman dijangkau"},
            ],
            "prototipe": [
                {"id": "bahan", "label": "Bahan sederhana tersedia"},
                {"id": "masukan", "label": "Masukan pengguna"},
            ],
            "dokumenter": [
                {"id": "izin_wawancara", "label": "Izin wawancara"},
                {"id": "pertanyaan", "label": "Daftar pertanyaan"},
            ],
            "simulasi": [
                {"id": "skenario", "label": "Skenario kasus jelas"},
                {"id": "peran", "label": "Pembagian peran"},
            ],
            "panduan": [
                {"id": "sasaran", "label": "Sasaran panduan jelas"},
                {"id": "validasi", "label": "Validasi warga sekolah"},
            ],
            "tur": [
                {"id": "rute", "label": "Rute aman"},
                {"id": "titik", "label": "Titik cerita terpilih"},
            ],
            "eksperimen": [
                {"id": "alat_ukur", "label": "Alat ukur sederhana"},
                {"id": "variabel", "label": "Variabel aman"},
            ],
            "festival": [
                {"id": "alur_berbagi", "label": "Alur berbagi karya"},
                {"id": "area", "label": "Area kegiatan tersedia"},
            ],
            "rancang-layanan": [
                {"id": "pengguna", "label": "Calon pengguna jelas"},
                {"id": "alur", "label": "Alur bantuan sederhana"},
            ],
        }
        return common + tags_by_pattern.get(str(pattern_key), [])

    def _project_pattern_questions(
        self,
        *,
        pattern_key: str,
        place: str,
        product: str,
    ) -> list[dict[str, Any]]:
        return [
            {
                "id": "batas_lokasi",
                "inputType": "textarea",
                "label": f"Bagian mana dari {place} yang boleh dipakai siswa untuk mencari bukti?",
                "placeholder": "Tuliskan batas area, waktu, dan pendampingan yang dibutuhkan.",
                "required": True,
                "answerKey": "observationPermit",
            },
            {
                "id": "produk_akhir",
                "inputType": "textarea",
                "label": f"Seperti apa bentuk akhir {product} yang realistis untuk kelas ini?",
                "placeholder": "Contoh: ukuran, durasi, jumlah halaman, media, atau bentuk presentasi.",
                "required": True,
                "answerKey": "mainConfirmations",
            },
            {
                "id": f"detail_{self._slug(pattern_key, 'proyek')}",
                "inputType": "textarea",
                "label": "Data, izin, atau alat apa yang paling perlu dipastikan sebelum proyek dimulai?",
                "placeholder": "Tuliskan kebutuhan praktis yang harus disiapkan guru dan siswa.",
                "required": True,
                "answerKey": "classAdjustments",
            },
        ]

    def _fallback_project_themes(
        self,
        *,
        stage_context: dict[str, Any],
        environment_context: dict[str, Any],
        subjects: list[str],
        subject_lens: str,
        local_issue: str,
    ) -> list[dict[str, str]]:
        subject_labels = self._subject_aligned_theme_labels(
            subjects,
            environment_context,
        )
        labels = subject_labels
        if not labels:
            context_text = " ".join(
                [
                    local_issue,
                    self._summarize_context_value(environment_context),
                    self._summarize_context_value(
                        environment_context.get("categoryGroups")
                    ),
                    self._summarize_context_value(environment_context.get("places")),
                    self._summarize_context_value(environment_context.get("risks")),
                    self._summarize_context_value(
                        stage_context.get("environmentScanner")
                    ),
                    self._summarize_context_value(stage_context.get("localContext")),
                    self._summarize_context_value(stage_context.get("kondisiKelas")),
                    subject_lens,
                ]
            )
            labels = self._theme_labels_from_context(context_text, with_default=False)
        labels = self._ensure_three_theme_labels(labels, subject_lens, local_issue)
        return [{"label": label} for label in labels[:3]]

    def _normalize_recommendations(
        self,
        generated: dict[str, Any],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(generated, dict):
            generated = {}

        if "projectThemes" in fallback:
            return self._normalize_theme_recommendations(generated, fallback)

        raw_options = generated.get("projectOptions") or generated.get("options") or []
        if not isinstance(raw_options, list):
            raw_options = []

        fallback_options = fallback.get("projectOptions")
        if not isinstance(fallback_options, list):
            fallback_options = []

        options = [
            self._normalize_option(item, index, fallback_options)
            for index, item in enumerate(raw_options[:3])
            if isinstance(item, dict)
        ]
        if self._has_rigid_project_option_pattern(options):
            options = []

        if not options and generated.get("recommendedProjectTitle"):
            options.append(
                self._normalize_option(
                    {
                        "title": generated.get("recommendedProjectTitle"),
                        "themeLabel": generated.get("projectTheme"),
                        "description": generated.get("projectBackground"),
                        "overview": generated.get("feasibilityNotes"),
                    },
                    0,
                    fallback_options,
                )
            )

        seen_ids = {option["id"] for option in options}
        for index, item in enumerate(fallback_options):
            if len(options) >= 3 or not isinstance(item, dict):
                break
            normalized = self._normalize_option(item, index, fallback_options)
            if normalized["id"] in seen_ids:
                normalized["id"] = f"{normalized['id']}-{len(options) + 1}"
            seen_ids.add(normalized["id"])
            options.append(normalized)

        result = {
            "projectOptions": options[:3],
            "selectionGuidance": self._first_text(
                generated.get("selectionGuidance"),
                fallback.get("selectionGuidance"),
                "",
            ),
            "reasoningSummary": self._first_text(
                generated.get("reasoningSummary"),
                fallback.get("reasoningSummary"),
                "",
            ),
        }
        return result

    def _has_rigid_project_option_pattern(self, options: list[dict[str, Any]]) -> bool:
        if len(options) < 3:
            return False
        title_prefixes = [
            self._first_text(option.get("title"), "").casefold()
            for option in options[:3]
        ]
        rigid_sets = (
            ("pemetaan", "kampanye", "audit"),
            ("analisis", "kampanye", "audit"),
            ("pemetaan", "proyek kampanye", "audit"),
        )
        for rigid_set in rigid_sets:
            if all(
                title_prefixes[index].startswith(prefix)
                for index, prefix in enumerate(rigid_set)
            ):
                return True
        formulaic_starters = (
            "festival mini",
            "rancang layanan",
            "dokumenter pendek",
            "jejak waktu",
            "tur narasi",
            "prototipe solusi",
            "panduan praktik",
            "simulasi keputusan",
            "eksperimen lapangan",
            "galeri cerita",
        )
        formulaic_count = sum(
            1
            for title in title_prefixes
            if any(title.startswith(starter) for starter in formulaic_starters)
        )
        if formulaic_count >= 2:
            return True
        return False

    def _normalize_theme_recommendations(
        self,
        generated: dict[str, Any],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        raw_themes = (
            generated.get("projectThemes")
            or generated.get("themes")
            or generated.get("themeOptions")
            or []
        )
        if not isinstance(raw_themes, list):
            raw_themes = []

        fallback_themes = fallback.get("projectThemes")
        if not isinstance(fallback_themes, list):
            fallback_themes = []

        themes = [
            self._normalize_theme(item, index, fallback_themes)
            for index, item in enumerate(raw_themes[:3])
            if isinstance(item, (dict, str))
        ]
        themes = self._filter_theme_recommendations(themes, fallback)

        if not themes:
            seen_labels: set[str] = set()
            for index, item in enumerate(fallback_themes):
                if len(themes) >= 3 or not isinstance(item, dict):
                    break
                normalized = self._normalize_theme(item, index, fallback_themes)
                label_key = self._slug(normalized["label"], "")
                if label_key in seen_labels:
                    continue
                seen_labels.add(label_key)
                themes.append(normalized)

        seen_labels = {self._slug(theme["label"], "") for theme in themes}
        for index, item in enumerate(fallback_themes):
            if len(themes) >= 3 or not isinstance(item, dict):
                break
            normalized = self._normalize_theme(item, index, fallback_themes)
            label_key = self._slug(normalized["label"], "")
            if label_key in seen_labels:
                continue
            seen_labels.add(label_key)
            themes.append(normalized)

        result = {
            key: value
            for key, value in generated.items()
            if not str(key).startswith("_")
        }
        result["projectThemes"] = themes[:3]
        result.setdefault("selectionGuidance", fallback.get("selectionGuidance", ""))
        result.setdefault("reasoningSummary", fallback.get("reasoningSummary", ""))
        return result

    def _filter_theme_recommendations(
        self,
        themes: list[dict[str, str]],
        fallback: dict[str, Any],
    ) -> list[dict[str, str]]:
        meta = fallback.get("_meta")
        if not isinstance(meta, dict):
            return themes

        blocked_keywords = self._string_list(meta.get("blockedThemeKeywords"))
        fallback_labels = self._string_list(meta.get("subjectAlignedThemeLabels"))
        if not blocked_keywords:
            return themes

        fallback_text = " ".join(fallback_labels).casefold()
        filtered: list[dict[str, str]] = []
        for theme in themes:
            label = self._first_text(theme.get("label"), "")
            label_text = label.casefold()
            blocked = [
                keyword
                for keyword in blocked_keywords
                if keyword in label_text and keyword not in fallback_text
            ]
            if blocked:
                continue
            filtered.append(theme)
        return filtered

    def _normalize_theme(
        self,
        item: dict[str, Any] | str,
        index: int,
        fallback_themes: list[Any],
    ) -> dict[str, str]:
        fallback = (
            fallback_themes[index]
            if index < len(fallback_themes) and isinstance(fallback_themes[index], dict)
            else {}
        )
        if isinstance(item, str):
            label = self._first_text(
                item, fallback.get("label"), f"Tema Proyek {index + 1}"
            )
            return {"label": self._short_theme_label(label)}

        label = self._first_text(
            item.get("label"),
            item.get("title"),
            item.get("name"),
            fallback.get("label"),
            f"Tema Proyek {index + 1}",
        )
        return {"label": self._short_theme_label(label)}

    def _normalize_option(
        self,
        item: dict[str, Any],
        index: int,
        fallback_options: list[Any],
    ) -> dict[str, Any]:
        fallback = (
            fallback_options[index]
            if index < len(fallback_options)
            and isinstance(fallback_options[index], dict)
            else {}
        )
        is_fallback_item = item is fallback
        title = self._first_text(
            item.get("title"), fallback.get("title"), f"Opsi Proyek {index + 1}"
        )
        option_id = self._first_text(
            item.get("id"), self._slug(title, f"opsi-{index + 1}")
        )
        questions = (
            item.get("clarificationQuestions")
            or item.get("detailQuestions")
            or item.get("questions")
        )
        if not isinstance(questions, list):
            questions = fallback.get("clarificationQuestions") or []
        tags = (
            item.get("confirmationTags")
            or item.get("confirmTags")
            or item.get("requiredDetails")
        )
        if not isinstance(tags, list):
            tags = fallback.get("confirmationTags") or []
        normalized_tags = self._normalize_tags(tags)
        if not normalized_tags:
            normalized_tags = self._normalize_tags(
                fallback.get("confirmationTags") or []
            )
        normalized_questions = self._normalize_questions(questions)
        if not normalized_questions:
            normalized_questions = self._normalize_questions(
                fallback.get("clarificationQuestions") or []
            )
        theme_label = self._first_text(
            item.get("themeLabel"),
            item.get("theme"),
            fallback.get("themeLabel"),
            "",
        )
        lens = self._first_text(
            item.get("lens"), fallback.get("lens"), "Lintas Disiplin"
        )
        raw_description = self._first_text(
            item.get("description"),
            item.get("projectBackground"),
            item.get("summary"),
            "",
        )
        description = self._first_text(
            raw_description,
            fallback.get("description") if is_fallback_item else "",
            self._build_option_description(title, theme_label, lens),
        )
        raw_overview = self._first_text(
            item.get("overview"),
            item.get("projectOverview"),
            item.get("feasibilityNotes"),
            "",
        )
        if self._is_generic_fallback_overview(raw_overview):
            raw_overview = ""
        generated_overview = self._build_option_overview(
            title=title,
            theme_label=theme_label,
            lens=lens,
            description=description,
            questions=normalized_questions,
        )
        fallback_overview = self._first_text(fallback.get("overview"), "")
        if self._is_generic_fallback_overview(fallback_overview):
            fallback_overview = ""
        overview = self._first_text(
            raw_overview,
            fallback_overview if is_fallback_item else "",
            generated_overview,
        )
        return {
            "id": self._slug(option_id, f"opsi-{index + 1}"),
            "title": title,
            "themeId": self._first_text(
                item.get("themeId"), fallback.get("themeId"), ""
            ),
            "themeLabel": theme_label,
            "description": description,
            "lens": lens,
            "overview": overview,
            "confirmationTags": normalized_tags,
            "clarificationQuestions": normalized_questions,
            "reasoningSummary": self._first_text(
                item.get("reasoningSummary"),
                item.get("reason"),
                fallback.get("reasoningSummary"),
                "",
            ),
        }

    def _build_option_description(
        self,
        title: str,
        theme_label: str,
        lens: str,
    ) -> str:
        theme_text = f" bertema {theme_label}" if theme_label else ""
        return (
            f"Siswa menjalankan proyek {title}{theme_text} dengan sudut pandang "
            f"{lens}, lalu menyusun hasil belajar yang dapat ditinjau guru."
        )

    def _build_option_overview(
        self,
        *,
        title: str,
        theme_label: str,
        lens: str,
        description: str,
        questions: list[dict[str, Any]],
    ) -> str:
        question_labels = [
            self._first_text(question.get("label"), "")
            for question in questions[:3]
            if isinstance(question, dict)
        ]
        detail_focus = "; ".join(label for label in question_labels if label)
        theme_text = f" pada tema {theme_label}" if theme_label else ""
        activity_detail = self._project_activity_detail(title, theme_label)
        first_sentence = (
            f"Dalam proyek {title}{theme_text}, {activity_detail} "
            f"Temuan ditafsirkan dengan lensa {lens} agar siswa tidak hanya "
            "mengumpulkan informasi, tetapi juga menjelaskan makna dan prioritasnya."
        )
        second_sentence = (
            "Produk akhirnya berupa bahan presentasi atau laporan ringkas yang "
            "memuat konteks kasus, bukti utama, analisis siswa, dan rekomendasi "
            "tindakan yang realistis untuk lingkungan sekolah."
        )
        if detail_focus:
            return (
                f"{first_sentence} {second_sentence} Detail yang perlu dipastikan "
                f"meliputi: {detail_focus}."
            )
        if description:
            return f"{first_sentence} {second_sentence} {description}"
        return f"{first_sentence} {second_sentence}"

    def _is_generic_fallback_overview(self, overview: str) -> bool:
        text = overview.casefold()
        generic_starts = (
            "berangkat dari konteks",
            "proyek ini mengubah temuan tentang",
            "proyek dilakukan di area sekolah",
        )
        bad_fragments = (
            "pemindai lingkungan juga memberi konteks",
            "catatan observasi, dokumentasi visual, data sederhana",
            "sehingga siswa dapat menjelaskan hubungan",
        )
        return any(text.startswith(pattern) for pattern in generic_starts) or any(
            fragment in text for fragment in bad_fragments
        )

    def _project_activity_detail(self, title: str, theme_label: str) -> str:
        text = f"{title} {theme_label}".casefold()
        if any(keyword in text for keyword in ("statistik", "survei", "data sekolah")):
            return (
                "siswa merancang survei kecil tentang kehidupan sekolah, menentukan "
                "variabel yang mudah diukur, mengumpulkan data dari teman atau warga "
                "sekolah, lalu menyajikannya dalam tabel, diagram, dan interpretasi "
                "singkat."
            )
        if any(keyword in text for keyword in ("pasar", "usaha", "umkm", "ekonomi")):
            return (
                "siswa memilih satu usaha atau aktivitas ekonomi lokal, mengamati "
                "alur layanan, harga, kebutuhan pembeli, serta risiko sederhana "
                "seperti stok, cuaca, persaingan, atau perubahan jumlah pengunjung."
            )
        if any(keyword in text for keyword in ("mitigasi", "risiko")):
            return (
                "siswa membuat peta risiko dari kasus nyata, memberi skor peluang "
                "dan dampak, lalu merancang langkah pencegahan, pengurangan dampak, "
                "dan pihak yang perlu dilibatkan."
            )
        if any(keyword in text for keyword in ("studi kasus", "kasus")):
            return (
                "siswa mendalami satu kasus lokal melalui observasi, wawancara "
                "singkat, dan dokumentasi bukti, lalu membandingkan kondisi ideal "
                "dengan kondisi yang mereka temukan."
            )
        if any(keyword in text for keyword in ("sejarah", "budaya", "tradisi")):
            return (
                "siswa menelusuri cerita, artefak, tempat, atau praktik budaya di "
                "sekitar sekolah, lalu menyusun garis waktu, makna, dan perubahan "
                "yang terlihat dari sumber lokal."
            )
        if any(keyword in text for keyword in ("seni", "pameran", "kreasi")):
            return (
                "siswa mengumpulkan referensi visual, membuat sketsa atau karya "
                "sederhana, lalu mengurasi pesan, teknik, dan alasan pemilihan media "
                "untuk dipresentasikan."
            )
        if any(keyword in text for keyword in ("kampanye", "poster", "publikasi")):
            return (
                "siswa menentukan sasaran pesan, mengolah temuan menjadi narasi "
                "persuasif, lalu membuat media kampanye yang dapat dipasang atau "
                "dipresentasikan kepada warga sekolah."
            )
        if any(keyword in text for keyword in ("audit", "fasilitas", "lingkungan")):
            return (
                "siswa menyusun checklist pengamatan, memeriksa kondisi beberapa "
                "titik, mendokumentasikan bukti, lalu mengelompokkan temuan menurut "
                "urgensi dan kemudahan perbaikan."
            )
        return (
            "siswa menentukan fokus pengamatan, membagi peran kelompok, "
            "mengumpulkan bukti lapangan sederhana, dan memilih temuan yang paling "
            "kuat untuk dianalisis lebih lanjut."
        )

    def _normalize_tags(self, raw_tags: list[Any]) -> list[dict[str, str]]:
        tags: list[dict[str, str]] = []
        for index, tag in enumerate(raw_tags[:6]):
            if isinstance(tag, str):
                label = tag.strip()
                if label:
                    tags.append(
                        {"id": self._slug(label, f"tag-{index + 1}"), "label": label}
                    )
            elif isinstance(tag, dict):
                label = self._first_text(
                    tag.get("label"), tag.get("title"), tag.get("name"), ""
                )
                if label:
                    tags.append(
                        {
                            "id": self._slug(
                                self._first_text(tag.get("id"), label),
                                f"tag-{index + 1}",
                            ),
                            "label": label,
                        }
                    )
        return tags

    def _normalize_questions(self, raw_questions: list[Any]) -> list[dict[str, Any]]:
        questions: list[dict[str, Any]] = []
        for index, question in enumerate(raw_questions[:5]):
            if isinstance(question, str):
                label = question.strip()
                if label:
                    questions.append(
                        {
                            "id": self._slug(label, f"pertanyaan-{index + 1}"),
                            "inputType": "textarea",
                            "label": label,
                            "placeholder": "Tuliskan sesuai kondisi kelas/sekolah.",
                            "required": True,
                        }
                    )
                continue
            if not isinstance(question, dict):
                continue
            label = self._first_text(
                question.get("label"),
                question.get("question"),
                question.get("title"),
                "",
            )
            if not label:
                continue
            input_type = self._first_text(
                question.get("inputType"), question.get("type"), "textarea"
            )
            if input_type in {"choice", "radio", "select"}:
                input_type = "single_choice"
            if input_type not in {"textarea", "short_text", "single_choice"}:
                input_type = "textarea"
            options = question.get("options")
            normalized_options = self._normalize_tags(
                options if isinstance(options, list) else []
            )
            if input_type == "single_choice" and not normalized_options:
                input_type = "textarea"
            normalized: dict[str, Any] = {
                "id": self._slug(
                    self._first_text(question.get("id"), label),
                    f"pertanyaan-{index + 1}",
                ),
                "inputType": input_type,
                "label": label,
                "placeholder": self._first_text(
                    question.get("placeholder"),
                    "Tuliskan sesuai kondisi kelas/sekolah.",
                ),
                "required": bool(question.get("required", True)),
            }
            answer_key = self._first_text(
                question.get("answerKey"), question.get("field"), ""
            )
            if answer_key:
                normalized["answerKey"] = answer_key
            if normalized_options:
                normalized["options"] = normalized_options
            questions.append(normalized)
        return questions

    def _environment_context(
        self,
        payload: RecommendStageRequest,
        stage_context: dict[str, Any],
        subjects: list[str] | None = None,
    ) -> dict[str, Any]:
        sources: list[Any] = []
        if isinstance(payload.placesContext, dict):
            sources.append(payload.placesContext)
            payload_value = payload.placesContext.get("payload")
            if isinstance(payload_value, dict):
                sources.append(payload_value)
        scanner_context = stage_context.get("environmentScanner")
        if isinstance(scanner_context, dict):
            sources.append(scanner_context)

        summary = ""
        places: list[dict[str, Any]] = []
        category_groups: list[dict[str, Any]] = []
        risks: list[dict[str, Any]] = []
        radius_meters: Any = None
        source_name = ""
        fetched_at = ""

        for source in sources:
            if not isinstance(source, dict):
                continue
            summary = self._first_text(summary, source.get("summary"))
            radius_meters = radius_meters or source.get("radiusMeters")
            source_name = self._first_text(source_name, source.get("source"))
            fetched_at = self._first_text(fetched_at, source.get("fetchedAt"))
            raw_places = source.get("places")
            if isinstance(raw_places, list) and not places:
                places = [
                    {
                        "name": (
                            self._first_text(place.get("name"), "")
                            if isinstance(place, dict)
                            else ""
                        ),
                        "categoryId": (
                            self._first_text(place.get("categoryId"), "")
                            if isinstance(place, dict)
                            else ""
                        ),
                        "category": (
                            self._first_text(place.get("category"), "")
                            if isinstance(place, dict)
                            else ""
                        ),
                        "distanceLabel": (
                            self._first_text(place.get("distanceLabel"), "")
                            if isinstance(place, dict)
                            else ""
                        ),
                        "relevanceNote": (
                            self._first_text(place.get("relevanceNote"), "")
                            if isinstance(place, dict)
                            else ""
                        ),
                    }
                    for place in raw_places[:6]
                    if isinstance(place, dict)
                    and self._first_text(place.get("name"), "")
                ]
            raw_category_groups = source.get("categoryGroups")
            if isinstance(raw_category_groups, list) and not category_groups:
                category_groups = [
                    {
                        "id": (
                            self._first_text(group.get("id"), "")
                            if isinstance(group, dict)
                            else ""
                        ),
                        "label": (
                            self._first_text(group.get("label"), "")
                            if isinstance(group, dict)
                            else ""
                        ),
                        "description": (
                            self._first_text(group.get("description"), "")
                            if isinstance(group, dict)
                            else ""
                        ),
                        "learningUses": (
                            group.get("learningUses", [])
                            if isinstance(group, dict)
                            and isinstance(group.get("learningUses"), list)
                            else []
                        ),
                        "places": (
                            [
                                {
                                    "name": self._first_text(place.get("name"), ""),
                                    "categoryId": self._first_text(
                                        place.get("categoryId"), ""
                                    ),
                                    "category": self._first_text(
                                        place.get("category"), ""
                                    ),
                                    "distanceLabel": self._first_text(
                                        place.get("distanceLabel"), ""
                                    ),
                                    "relevanceNote": self._first_text(
                                        place.get("relevanceNote"), ""
                                    ),
                                }
                                for place in group.get("places", [])[:4]
                                if isinstance(place, dict)
                                and self._first_text(place.get("name"), "")
                            ]
                            if isinstance(group, dict)
                            and isinstance(group.get("places"), list)
                            else []
                        ),
                        "subjectFitScore": (
                            self._subject_fit_score(group, subjects or [])
                            if isinstance(group, dict)
                            else 0
                        ),
                    }
                    for group in raw_category_groups[:6]
                    if isinstance(group, dict)
                    and self._first_text(group.get("label"), "")
                ]
            raw_risks = source.get("risks")
            if isinstance(raw_risks, list) and not risks:
                risks = [
                    {
                        "title": (
                            self._first_text(risk.get("title"), "")
                            if isinstance(risk, dict)
                            else ""
                        ),
                        "level": (
                            self._first_text(risk.get("level"), "")
                            if isinstance(risk, dict)
                            else ""
                        ),
                        "description": (
                            self._first_text(risk.get("description"), "")
                            if isinstance(risk, dict)
                            else ""
                        ),
                    }
                    for risk in raw_risks[:3]
                    if isinstance(risk, dict)
                    and self._first_text(risk.get("title"), "")
                ]

        category_groups, places, omitted_labels = self._filter_environment_context(
            category_groups,
            places,
            subjects or [],
        )
        return {
            "summary": summary,
            "categoryGroups": category_groups,
            "places": places,
            "risks": risks,
            "radiusMeters": radius_meters,
            "source": source_name,
            "fetchedAt": fetched_at,
            "subjectAlignment": {
                "mainSubjects": subjects or [],
                "includedCategoryLabels": [
                    self._first_text(group.get("label"), "")
                    for group in category_groups
                    if isinstance(group, dict)
                    and self._first_text(group.get("label"), "")
                ],
                "omittedCategoryLabels": omitted_labels,
            },
        }

    def _filter_environment_context(
        self,
        category_groups: list[dict[str, Any]],
        places: list[dict[str, Any]],
        subjects: list[str],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
        if not subjects:
            return category_groups, places, []

        scored_groups: list[tuple[int, dict[str, Any]]] = [
            (self._subject_fit_score(group, subjects), group)
            for group in category_groups
        ]
        has_aligned_group = any(score > 0 for score, _group in scored_groups)
        omitted_labels: list[str] = []
        if has_aligned_group:
            filtered_groups = [
                dict(group, subjectFitScore=score)
                for score, group in sorted(
                    scored_groups,
                    key=lambda item: (
                        -item[0],
                        self._first_text(item[1].get("label"), ""),
                    ),
                )
                if score > 0
            ]
            omitted_labels = [
                self._first_text(group.get("label"), "")
                for score, group in scored_groups
                if score <= 0 and self._first_text(group.get("label"), "")
            ]
        else:
            filtered_groups = category_groups

        scored_places = [
            (self._subject_fit_score(place, subjects), place) for place in places
        ]
        has_aligned_place = any(score > 0 for score, _place in scored_places)
        if has_aligned_place:
            filtered_places = [
                dict(place, subjectFitScore=score)
                for score, place in sorted(
                    scored_places,
                    key=lambda item: (
                        -item[0],
                        self._first_text(item[1].get("distanceLabel"), ""),
                    ),
                )
                if score > 0
            ]
        else:
            filtered_places = places

        return filtered_groups[:6], filtered_places[:6], omitted_labels[:6]

    def _subject_fit_score(self, value: Any, subjects: list[str]) -> int:
        if not subjects:
            return 0
        text = self._searchable_context_text(value).casefold()
        if isinstance(value, dict):
            text = " ".join(
                [
                    text,
                    self._first_text(value.get("id"), ""),
                    self._first_text(value.get("categoryId"), ""),
                    self._first_text(value.get("category"), ""),
                    self._first_text(value.get("label"), ""),
                    self._summarize_context_value(value.get("learningUses")),
                    self._summarize_context_value(value.get("places")),
                ]
            ).casefold()
        focus_terms = self._subject_focus_terms(subjects)
        score = sum(3 for term in focus_terms if term in text)
        score += sum(1 for subject in subjects if subject.casefold() in text)
        return score

    def _subject_focus_terms(self, subjects: list[str]) -> list[str]:
        subject_text = " ".join(subjects).casefold()
        terms: list[str] = []
        if any(keyword in subject_text for keyword in ("matematika", "statistika")):
            terms.extend(
                [
                    "data",
                    "harga",
                    "jarak",
                    "ukur",
                    "survei",
                    "statistik",
                    "grafik",
                    "diagram",
                    "tabel",
                    "perbandingan",
                    "persentase",
                    "biaya",
                    "keputusan",
                ]
            )
        if any(
            keyword in subject_text for keyword in ("ekonomi", "bisnis", "wirausaha")
        ):
            terms.extend(
                [
                    "ekonomi",
                    "umkm",
                    "usaha",
                    "jual",
                    "beli",
                    "pasar",
                    "harga",
                    "biaya",
                    "transaksi",
                    "kebutuhan",
                    "pembeli",
                    "pengunjung",
                    "keputusan",
                ]
            )
        if any(
            keyword in subject_text for keyword in ("ipa", "biologi", "kimia", "fisika")
        ):
            terms.extend(["sains", "ipa", "kesehatan", "air", "tanaman", "cuaca"])
        if any(keyword in subject_text for keyword in ("sejarah", "seni", "budaya")):
            terms.extend(["budaya", "sejarah", "tradisi", "karya", "visual"])
        if any(keyword in subject_text for keyword in ("ppkn", "pkn", "sosiologi")):
            terms.extend(["warga", "sosial", "layanan", "kesehatan", "publik"])
        return list(dict.fromkeys(term for term in terms if term))

    def _blocked_theme_keywords(self, subjects: list[str]) -> list[str]:
        subject_text = " ".join(subjects).casefold()
        blocked: list[str] = []
        if not any(
            keyword in subject_text
            for keyword in ("ipa", "biologi", "ppkn", "pkn", "sosiologi")
        ):
            blocked.extend(["kesehatan", "sehat", "vaksin"])
        if not any(
            keyword in subject_text
            for keyword in ("sejarah", "seni", "budaya", "bahasa")
        ):
            blocked.extend(["budaya", "sejarah", "tradisi"])
        return list(dict.fromkeys(blocked))

    def _omitted_theme_keywords(self, environment_context: dict[str, Any]) -> list[str]:
        subject_alignment = environment_context.get("subjectAlignment")
        if not isinstance(subject_alignment, dict):
            return []
        omitted_labels = self._string_list(
            subject_alignment.get("omittedCategoryLabels")
        )
        stopwords = {"dan", "atau", "lokal", "sekitar"}
        keywords: list[str] = []
        for label in omitted_labels:
            for word in re.findall(r"[A-Za-z0-9]+", label.casefold()):
                if len(word) >= 4 and word not in stopwords:
                    keywords.append(word)
        return list(dict.fromkeys(keywords))

    def _subject_aligned_theme_labels(
        self,
        subjects: list[str],
        environment_context: dict[str, Any],
    ) -> list[str]:
        subject_text = " ".join(subjects).casefold()
        context_text = self._searchable_context_text(environment_context).casefold()
        labels: list[str] = []

        def add(label: str) -> None:
            if label not in labels:
                labels.append(label)

        if "ekonomi" in subject_text:
            if any(
                term in context_text
                for term in ("umkm", "usaha", "jual", "beli", "harga", "pasar")
            ):
                add("Ekonomi Lokal")
                add("Data Harga")
                add("Jual Beli")
                add("Kebutuhan Warga")
            else:
                add("Keputusan Ekonomi")
        if any(term in subject_text for term in ("matematika", "statistika")):
            if any(
                term in context_text
                for term in (
                    "harga",
                    "data",
                    "survei",
                    "jarak",
                    "pengunjung",
                    "kebutuhan",
                )
            ):
                add("Survei Data")
                add("Perbandingan Biaya")
                add("Statistik Sekolah")
            else:
                add("Data Kontekstual")

        if not labels:
            for group in environment_context.get("categoryGroups", []):
                if not isinstance(group, dict):
                    continue
                label = self._first_text(group.get("label"), "")
                if label:
                    add(self._short_theme_label(label))
        return labels[:3]

    def _place_label(self, places: list[Any], index: int, fallback: str) -> str:
        if index < len(places) and isinstance(places[index], dict):
            place = places[index]
            name = self._first_text(place.get("name"), "")
            category = self._first_text(place.get("category"), "")
            distance = self._first_text(place.get("distanceLabel"), "")
            if name and category and distance:
                return f"{name} ({category}, {distance})"
            if name and category:
                return f"{name} ({category})"
            if name:
                return name
        return fallback

    def _place_categories(self, places: list[Any]) -> list[str]:
        categories: list[str] = []
        for place in places:
            if not isinstance(place, dict):
                continue
            category = self._first_text(place.get("category"), "")
            note = self._first_text(place.get("relevanceNote"), "")
            label = " - ".join(part for part in (category, note) if part)
            if label and label not in categories:
                categories.append(label)
        return categories

    def _selected_theme(self, payload: RecommendStageRequest) -> Any:
        target_stage = payload.targetStage or {}
        options = payload.options or {}
        return (
            target_stage.get("selectedTheme")
            or target_stage.get("selectedThemeId")
            or target_stage.get("selectedProjectTheme")
            or target_stage.get("projectTheme")
            or options.get("selectedTheme")
            or options.get("selectedThemeId")
            or options.get("selectedProjectTheme")
            or options.get("projectTheme")
        )

    def _theme_label(self, selected_theme: Any) -> str:
        if isinstance(selected_theme, dict):
            return self._first_text(
                selected_theme.get("label"),
                selected_theme.get("title"),
                selected_theme.get("name"),
                selected_theme.get("id"),
                "Tema Terpilih",
            )
        return self._first_text(selected_theme, "Tema Terpilih")

    def _flatten_stage_context(self, stage_one: Any) -> dict[str, Any]:
        if not isinstance(stage_one, dict):
            return {}
        merged: dict[str, Any] = {}
        for key in ("inputs", "spec", "mission"):
            value = stage_one.get(key)
            if isinstance(value, dict):
                merged.update(value)
        wizard = stage_one.get("wizard")
        if isinstance(wizard, dict):
            konteks = wizard.get("konteks")
            if isinstance(konteks, dict):
                for key in ("spec", "mission"):
                    value = konteks.get(key)
                    if isinstance(value, dict):
                        merged.update(value)
                environment_scanner = konteks.get("environmentScanner")
                if isinstance(environment_scanner, dict):
                    merged.setdefault("environmentScanner", environment_scanner)
                    merged.setdefault(
                        "localContext",
                        self._summarize_context_value(environment_scanner),
                    )
                    merged.setdefault(
                        "localIssue",
                        self._summarize_context_value(environment_scanner),
                    )
        merged.update(
            {
                key: value
                for key, value in stage_one.items()
                if key not in {"inputs", "spec", "mission", "wizard"}
            }
        )
        self._merge_stage_one_sections(merged, stage_one)
        return merged

    def _merge_stage_one_sections(
        self,
        merged: dict[str, Any],
        stage_one: dict[str, Any],
    ) -> None:
        school_info = self._first_section(
            stage_one,
            "schoolInformation",
            "informasiSekolah",
        )
        environment_scanner = self._first_section(
            stage_one,
            "environmentScanner",
            "pemindaiLingkungan",
        )
        risk_monitoring = self._first_section(
            stage_one,
            "riskMonitoring",
            "pemantauanRisiko",
        )
        mission_spec = self._first_section(
            stage_one,
            "missionSpec",
            "spesifikasiMisi",
        )

        if school_info:
            merged.setdefault(
                "schoolName",
                self._first_text(
                    school_info.get("schoolName"),
                    school_info.get("namaSekolah"),
                    school_info.get("name"),
                ),
            )
            merged.setdefault(
                "schoolAddress",
                self._first_text(
                    school_info.get("address"),
                    school_info.get("alamat"),
                ),
            )

        environment_summary = self._summarize_context_value(environment_scanner)
        if environment_summary:
            merged.setdefault("localContext", environment_summary)
            merged.setdefault("localIssue", environment_summary)

        risk_summary = self._summarize_context_value(risk_monitoring)
        if risk_summary:
            merged.setdefault("riskNotes", risk_summary)
            merged.setdefault("implementationConstraints", risk_summary)

        if mission_spec:
            merged.setdefault(
                "mainSubjects",
                mission_spec.get("relatedSubjects")
                or mission_spec.get("muatanMataPelajaranTerkait")
                or mission_spec.get("mataPelajaranTerkait"),
            )
            merged.setdefault(
                "fase",
                self._first_text(
                    mission_spec.get("educationPhase"),
                    mission_spec.get("fasePendidikan"),
                    mission_spec.get("fase"),
                ),
            )
            merged.setdefault(
                "educationLevel",
                self._first_text(
                    mission_spec.get("educationLevel"),
                    mission_spec.get("jenjangPendidikan"),
                    mission_spec.get("jenjang"),
                ),
            )
            merged.setdefault(
                "projectDuration",
                self._summarize_context_value(
                    mission_spec.get("learningDuration")
                    or mission_spec.get("durasiPembelajaran")
                ),
            )
            merged.setdefault(
                "kondisiKelas",
                self._summarize_context_value(
                    mission_spec.get("classCondition")
                    or mission_spec.get("kondisiKelas")
                ),
            )

    def _first_section(self, data: dict[str, Any], *keys: str) -> dict[str, Any]:
        for key in keys:
            value = data.get(key)
            if isinstance(value, dict):
                return value
        return {}

    def _searchable_context_text(self, value: Any, depth: int = 0) -> str:
        if depth > 4:
            return ""
        if isinstance(value, str):
            return value.strip()
        if isinstance(value, list):
            return " ".join(
                self._searchable_context_text(item, depth + 1) for item in value[:10]
            )
        if isinstance(value, dict):
            parts: list[str] = []
            for key, item in list(value.items())[:20]:
                parts.append(str(key))
                parts.append(self._searchable_context_text(item, depth + 1))
            return " ".join(part for part in parts if part)
        if value is not None:
            return str(value).strip()
        return ""

    def _summarize_context_value(self, value: Any) -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list):
            items = [self._summarize_context_value(item) for item in value[:6]]
            return "; ".join(item for item in items if item)
        if isinstance(value, dict):
            direct = self._first_text(
                value.get("summary"),
                value.get("description"),
                value.get("deskripsi"),
                value.get("localIssue"),
                value.get("context"),
                value.get("konteks"),
                value.get("name"),
                value.get("nama"),
                value.get("title"),
                value.get("judul"),
            )
            if direct:
                return direct
            parts = []
            for key, item in value.items():
                summary = self._summarize_context_value(item)
                if summary:
                    parts.append(f"{key}: {summary}")
                if len(parts) >= 6:
                    break
            return "; ".join(parts)
        if value is not None:
            return str(value).strip()
        return ""

    def _focus_phrase(self, value: Any) -> str:
        text = self._summarize_context_value(value)
        if not text:
            return ""
        text = re.sub(r"\s+", " ", text).strip(" .;:")
        words = text.split()
        if len(words) > 6:
            text = " ".join(words[:6])
        return text[:80].strip(" .;:")

    def _theme_labels_from_context(
        self,
        text: str,
        *,
        with_default: bool = True,
    ) -> list[str]:
        stopwords = {
            "yang",
            "dan",
            "atau",
            "dengan",
            "untuk",
            "dari",
            "pada",
            "dalam",
            "sekitar",
            "sekolah",
            "siswa",
            "murid",
            "kelas",
            "dekat",
            "berada",
            "aktif",
            "perlu",
            "dapat",
            "the",
        }
        words = re.findall(r"[A-Za-z0-9]+", text)
        labels: list[str] = []
        seen: set[str] = set()
        for word in words:
            clean = word.strip()
            key = clean.casefold()
            if len(clean) < 4 or key in stopwords or key in seen:
                continue
            seen.add(key)
            labels.append(clean if clean.isupper() else clean.title())
            if len(labels) >= 3:
                break

        if not labels and with_default:
            labels.append("Kontekstual")
        return [self._short_theme_label(label) for label in labels]

    def _short_theme_label(self, label: str) -> str:
        text = re.sub(r"\s+", " ", self._first_text(label, "Tema")).strip()
        text = re.sub(r"\s+([&/|-])\s*$", "", text)
        return text[:64].strip(" .;:")

    def _ensure_three_theme_labels(
        self,
        labels: list[str],
        subject_lens: str,
        local_issue: str,
    ) -> list[str]:
        filled: list[str] = []
        seen: set[str] = set()
        candidates = (
            labels
            + self._theme_labels_from_context(
                f"{subject_lens} {local_issue}",
                with_default=True,
            )
            + ["Lingkungan Sekolah", "Kebiasaan Warga", "Data Sekolah"]
        )
        for candidate in candidates:
            label = self._short_theme_label(candidate)
            key = self._slug(label, "")
            if not key or key in seen:
                continue
            seen.add(key)
            filled.append(label)
            if len(filled) >= 3:
                break
        return filled

    def _subjects(
        self,
        payload: RecommendStageRequest,
        stage_context: dict[str, Any],
    ) -> list[str]:
        subjects = self._string_list(stage_context.get("mainSubjects"))
        if not subjects:
            subjects = self._string_list(stage_context.get("collabSubjects"))
        project_subject = self._first_text(payload.project.subject, "")
        if not subjects and not self._is_generic_subject(project_subject):
            subjects = self._string_list(project_subject)
        return subjects

    def _is_generic_subject(self, value: Any) -> bool:
        text = self._first_text(value, "").casefold()
        return not text or text in {
            "umum",
            "general",
            "lintas disiplin",
            "mata pelajaran terkait",
        }

    def _string_list(self, value: Any) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        if isinstance(value, str) and value.strip():
            return [item.strip() for item in value.split(",") if item.strip()]
        return []

    def _first_text(self, *values: Any) -> str:
        fallback = ""
        for value in values:
            if isinstance(value, str) and value.strip():
                return value.strip()
            if value is not None and not isinstance(value, (dict, list, tuple, set)):
                text = str(value).strip()
                if text:
                    return text
        return fallback

    def _slug(self, value: str, fallback: str) -> str:
        text = value.strip().lower()
        text = re.sub(r"[^a-z0-9]+", "-", text)
        text = re.sub(r"-+", "-", text).strip("-")
        return text[:64] or fallback
