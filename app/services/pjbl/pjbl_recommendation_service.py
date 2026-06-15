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
        recommendation_type = (
            "project_recommendation"
            if selected_theme
            else "project_theme_recommendation"
        )
        target_stage_number = target_stage.get("stageNumber")
        references = []
        fallback = self._fallback_recommendations(
            payload, recommendation_type, references
        )
        required_response_shape = self._required_response_shape(recommendation_type)
        llm_input = {
            "project": payload.project.model_dump(),
            "teacherProfile": (
                payload.teacherProfile.model_dump() if payload.teacherProfile else {}
            ),
            "school": payload.school.model_dump() if payload.school else {},
            "teacherClass": (
                payload.teacherClass.model_dump() if payload.teacherClass else {}
            ),
            "previousStages": [stage.model_dump() for stage in payload.previousStages],
            "targetStage": target_stage,
            "environmentContext": self._environment_context(
                payload,
                self._flatten_stage_context(
                    next(
                        (
                            stage.contentJson
                            for stage in payload.previousStages
                            if stage.stageNumber == 1
                        ),
                        {},
                    )
                ),
            ),
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
        generated = await self.llm_client.generate_json(
            messages,
            fallback,
            temperature=0.7,
        )
        logger.info(
            "[PjBL Recommend] LLM raw output (%s):\n%s",
            recommendation_type,
            json.dumps(generated, ensure_ascii=False, indent=2, default=str),
        )
        recommendations = self._normalize_recommendations(generated, fallback)
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

    def _required_response_shape(self, recommendation_type: str) -> dict[str, Any]:
        if recommendation_type == "project_theme_recommendation":
            return {"projectThemes": [{"label": "..."}]}
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

    def _fallback_recommendations(
        self,
        payload: RecommendStageRequest,
        recommendation_type: str,
        references: list[Any],
    ) -> dict[str, Any]:
        subject_context = (
            payload.project.subject or payload.project.title or "mata pelajaran terkait"
        )
        stage_one = next(
            (
                stage.contentJson
                for stage in payload.previousStages
                if stage.stageNumber == 1
            ),
            {},
        )
        stage_context = self._flatten_stage_context(stage_one)
        environment_context = self._environment_context(payload, stage_context)
        school_name = self._first_text(
            getattr(payload.school, "name", None) if payload.school else None,
            "lingkungan sekolah",
        )
        city = self._first_text(
            getattr(payload.school, "city", None) if payload.school else None,
            getattr(payload.school, "district", None) if payload.school else None,
            "",
        )
        subjects = self._string_list(
            stage_context.get("mainSubjects")
            or stage_context.get("collabSubjects")
            or payload.project.subject
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
                subject_lens=subject_lens,
                local_issue=local_issue,
            )
            return {
                "projectThemes": themes,
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
            self._place_label(places, index, "")
            for index in range(min(len(places), 6))
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
                "keywords": ("sejarah", "budaya", "tradisi", "museum", "tokoh", "perubahan"),
                "title": "Cerita Perubahan {theme} di {place}",
                "product": "linimasa sederhana dan cerita singkat yang dapat dibaca teman sekelas",
                "activity": "siswa mencari perubahan, tokoh, benda, atau cerita yang berkaitan dengan {place}",
                "data": "wawancara singkat, catatan observasi, dokumentasi tempat, dan perbandingan kondisi dulu-kini",
                "lens_suffix": " & Cerita Lokal",
            },
            {
                "key": "prototipe",
                "score": 0,
                "keywords": ("teknologi", "informatika", "fasilitas", "lingkungan", "layanan", "solusi"),
                "title": "Ide Perbaikan Kecil untuk {place}",
                "product": "usulan perbaikan kecil berisi alasan, langkah, dan perkiraan kebutuhan",
                "activity": "siswa menemukan satu kebutuhan nyata di {place}, membuat beberapa ide perbaikan, lalu memilih yang paling mungkin dilakukan",
                "data": "daftar kebutuhan pengguna, foto kondisi, hasil uji coba kecil, dan masukan teman",
                "lens_suffix": " & Aksi Nyata",
            },
            {
                "key": "dokumenter",
                "score": 0,
                "keywords": ("bahasa", "cerita", "komunikasi", "sosial", "budaya", "sejarah"),
                "title": "Suara Warga Sekolah tentang {theme}",
                "product": "kutipan pilihan, ringkasan temuan, dan bahan presentasi singkat",
                "activity": "siswa menyusun pertanyaan sederhana, mendengar cerita warga sekolah, lalu memilih kutipan yang paling membantu memahami tema",
                "data": "kutipan narasumber, rekaman suasana, catatan observasi, dan daftar izin publikasi",
                "lens_suffix": " & Komunikasi",
            },
            {
                "key": "simulasi",
                "score": 0,
                "keywords": ("risiko", "ekonomi", "keputusan", "pasar", "usaha", "mitigasi"),
                "title": "Pilihan Keputusan dari Kasus di {place}",
                "product": "tabel pilihan tindakan, alasan pro-kontra, dan keputusan kelompok",
                "activity": "siswa mengambil satu kasus dari {place}, membuat beberapa pilihan tindakan, lalu membandingkan dampak tiap pilihan",
                "data": "data situasi, kemungkinan risiko, pilihan tindakan, dan alasan pro-kontra",
                "lens_suffix": " & Keputusan Berbasis Data",
            },
            {
                "key": "panduan",
                "score": 0,
                "keywords": ("aman", "etika", "layanan", "fasilitas", "kesehatan", "sosial"),
                "title": "Kebiasaan Baik yang Bisa Dicoba di {place}",
                "product": "daftar langkah sederhana dan contoh penerapannya di sekolah",
                "activity": "siswa mengamati kebiasaan atau kebutuhan di {place}, lalu merumuskan langkah baik yang mudah diikuti",
                "data": "hasil observasi perilaku, catatan risiko, masukan warga sekolah, dan contoh praktik yang sudah berjalan",
                "lens_suffix": " & Sikap Sosial",
            },
            {
                "key": "tur",
                "score": 0,
                "keywords": ("sejarah", "budaya", "geografi", "tempat", "ruang", "lingkungan"),
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
                "keywords": ("kolaborasi", "komunitas", "pameran", "apresiasi", "pengunjung"),
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
            option_id = self._slug(f"{pattern['key']}-{selected_theme_label}-{place}", f"opsi-{index + 1}")
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
        text = re.sub(r"\s*&\s*", " dan ", self._first_text(subject_lens, "lintas disiplin"))
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
        subject_lens: str,
        local_issue: str,
    ) -> list[dict[str, str]]:
        context_text = " ".join(
            [
                local_issue,
                self._summarize_context_value(environment_context),
                self._summarize_context_value(environment_context.get("categoryGroups")),
                self._summarize_context_value(environment_context.get("places")),
                self._summarize_context_value(environment_context.get("risks")),
                self._summarize_context_value(stage_context.get("environmentScanner")),
                self._summarize_context_value(stage_context.get("localContext")),
                self._summarize_context_value(stage_context.get("kondisiKelas")),
            ]
        )
        labels = self._theme_labels_from_context(context_text, with_default=False)
        if not labels:
            labels = self._theme_labels_from_context(subject_lens)
        return [{"label": label} for label in labels[:7]]

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

    def _has_rigid_project_option_pattern(
        self, options: list[dict[str, Any]]
    ) -> bool:
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
            for index, item in enumerate(raw_themes[:7])
            if isinstance(item, (dict, str))
        ]

        if not themes:
            seen_labels: set[str] = set()
            for index, item in enumerate(fallback_themes):
                if len(themes) >= 7 or not isinstance(item, dict):
                    break
                normalized = self._normalize_theme(item, index, fallback_themes)
                label_key = self._slug(normalized["label"], "")
                if label_key in seen_labels:
                    continue
                seen_labels.add(label_key)
                themes.append(normalized)

        result = dict(generated)
        result["projectThemes"] = themes[:7]
        result.setdefault("selectionGuidance", fallback.get("selectionGuidance", ""))
        result.setdefault("reasoningSummary", fallback.get("reasoningSummary", ""))
        return result

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
                        "name": self._first_text(place.get("name"), "")
                        if isinstance(place, dict)
                        else "",
                        "category": self._first_text(place.get("category"), "")
                        if isinstance(place, dict)
                        else "",
                        "distanceLabel": self._first_text(
                            place.get("distanceLabel"), ""
                        )
                        if isinstance(place, dict)
                        else "",
                        "relevanceNote": self._first_text(
                            place.get("relevanceNote"), ""
                        )
                        if isinstance(place, dict)
                        else "",
                    }
                    for place in raw_places[:6]
                    if isinstance(place, dict)
                    and self._first_text(place.get("name"), "")
                ]
            raw_category_groups = source.get("categoryGroups")
            if isinstance(raw_category_groups, list) and not category_groups:
                category_groups = [
                    {
                        "label": self._first_text(group.get("label"), "")
                        if isinstance(group, dict)
                        else "",
                        "description": self._first_text(
                            group.get("description"), ""
                        )
                        if isinstance(group, dict)
                        else "",
                        "learningUses": group.get("learningUses", [])
                        if isinstance(group, dict)
                        and isinstance(group.get("learningUses"), list)
                        else [],
                        "places": [
                            {
                                "name": self._first_text(place.get("name"), ""),
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
                        else [],
                    }
                    for group in raw_category_groups[:6]
                    if isinstance(group, dict)
                    and self._first_text(group.get("label"), "")
                ]
            raw_risks = source.get("risks")
            if isinstance(raw_risks, list) and not risks:
                risks = [
                    {
                        "title": self._first_text(risk.get("title"), "")
                        if isinstance(risk, dict)
                        else "",
                        "level": self._first_text(risk.get("level"), "")
                        if isinstance(risk, dict)
                        else "",
                        "description": self._first_text(
                            risk.get("description"), ""
                        )
                        if isinstance(risk, dict)
                        else "",
                    }
                    for risk in raw_risks[:3]
                    if isinstance(risk, dict)
                    and self._first_text(risk.get("title"), "")
                ]

        return {
            "summary": summary,
            "categoryGroups": category_groups,
            "places": places,
            "risks": risks,
            "radiusMeters": radius_meters,
            "source": source_name,
            "fetchedAt": fetched_at,
        }

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
            if len(labels) >= 7:
                break

        if not labels and with_default:
            labels.append("Kontekstual")
        return [self._short_theme_label(label) for label in labels]

    def _short_theme_label(self, label: str) -> str:
        text = re.sub(r"\s+", " ", self._first_text(label, "Tema")).strip()
        text = re.sub(r"\s+([&/|-])\s*$", "", text)
        return text[:64].strip(" .;:")

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
