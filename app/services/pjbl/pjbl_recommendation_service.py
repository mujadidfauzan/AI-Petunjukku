from __future__ import annotations

import json
import re
from typing import Any

from app.schemas.recommendation_schema import (
    RecommendStageRequest,
    RecommendStageResponse,
)
from app.services.llm_client import LLMClient
from app.services.prompt_builder_service import PromptBuilderService
from app.services.rag_service import RAGService
from app.services.pjbl.pjbl_prompt_templates import PJBL_RECOMMENDATION_SYSTEM_PROMPT


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
        recommendation_type = str(
            target_stage.get("recommendationType") or "stage_recommendation"
        )
        target_stage_number = target_stage.get("stageNumber")
        topic = str(target_stage.get("topic") or payload.project.title or "")
        references = []
        fallback = self._fallback_recommendations(payload, recommendation_type, references)
        messages = [
            {
                "role": "system",
                "content": PJBL_RECOMMENDATION_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "project": payload.project.model_dump(),
                        "teacherProfile": payload.teacherProfile.model_dump()
                        if payload.teacherProfile
                        else {},
                        "school": payload.school.model_dump() if payload.school else {},
                        "teacherClass": payload.teacherClass.model_dump()
                        if payload.teacherClass
                        else {},
                        "previousStages": [
                            stage.model_dump() for stage in payload.previousStages
                        ],
                        "targetStage": target_stage,
                        "ragReferences": [
                            reference.model_dump() for reference in references
                        ],
                        "requiredResponseShape": fallback,
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        generated = await self.llm_client.generate_json(messages, fallback)
        recommendations = self._normalize_recommendations(generated, fallback)
        return RecommendStageResponse(
            rppType=payload.project.rppType,
            recommendationType=recommendation_type,
            targetStageNumber=int(target_stage_number)
            if target_stage_number is not None
            else None,
            ragReferences=references,
            recommendations=recommendations,
        )

    def _fallback_recommendations(
        self,
        payload: RecommendStageRequest,
        recommendation_type: str,
        references: list[Any],
    ) -> dict[str, Any]:
        topic = (
            payload.targetStage.get("topic")
            or payload.project.title
            or "topik pembelajaran"
        )
        stage_one = next(
            (stage.contentJson for stage in payload.previousStages if stage.stageNumber == 1),
            {},
        )
        stage_context = self._flatten_stage_context(stage_one)
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
            stage_context.get("studentNotes"),
            stage_context.get("kondisiKelas"),
            stage_context.get("localContext"),
            getattr(payload.school, "localContext", None) if payload.school else None,
            getattr(payload.school, "schoolEnvironment", None) if payload.school else None,
            payload.targetStage.get("topic"),
            topic,
        )
        grade_label = self._first_text(
            stage_context.get("fase"),
            payload.project.phase,
            payload.project.gradeLevel,
            "fase/kelas yang dipilih",
        )
        options = [
            {
                "id": self._slug(f"lingkungan-{local_issue}", "lingkungan"),
                "title": f"Investigasi Potensi Lingkungan Sekitar {school_name}",
                "themeId": "lingkungan",
                "themeLabel": "Lingkungan",
                "description": (
                    "Siswa memetakan peluang, masalah, dan sumber belajar di sekitar "
                    "sekolah lalu menyusun rekomendasi aksi sederhana yang sesuai "
                    f"dengan {grade_label}."
                ),
                "lens": subject_lens,
                "overview": (
                    f"Berangkat dari konteks {local_issue}, siswa melakukan observasi "
                    "terbatas di area yang aman, mencatat temuan utama, lalu "
                    "mempresentasikan solusi atau rekomendasi yang realistis."
                ),
                "confirmationTags": [
                    {"id": "izin_lokasi", "label": "Izin lokasi observasi"},
                    {"id": "keamanan_rute", "label": "Keamanan rute siswa"},
                    {"id": "jadwal", "label": "Keselarasan jadwal kelas"},
                ],
                "clarificationQuestions": [
                    {
                        "id": "lokasi_aman",
                        "inputType": "textarea",
                        "label": "Area sekitar sekolah mana yang paling aman dan mudah diawasi untuk observasi siswa?",
                        "placeholder": "Contoh: halaman sekolah, taman dekat gerbang, koridor kantin, atau area lain yang bisa diawasi guru.",
                        "required": True,
                        "answerKey": "observationPermit",
                    },
                    {
                        "id": "data_lingkungan",
                        "inputType": "single_choice",
                        "label": "Data sederhana apa yang paling mungkin dikumpulkan siswa tanpa mengganggu aktivitas sekitar?",
                        "required": True,
                        "answerKey": "mathFocusId",
                        "options": [
                            {
                                "id": "jumlah_temuan",
                                "label": "Jumlah dan jenis temuan di lokasi pengamatan.",
                            },
                            {
                                "id": "pola_aktivitas",
                                "label": "Pola aktivitas pada waktu ramai dan sepi.",
                            },
                            {
                                "id": "kondisi_fasilitas",
                                "label": "Kondisi fasilitas yang perlu diperbaiki atau dirawat.",
                            },
                        ],
                    },
                    {
                        "id": "penyesuaian_kelas",
                        "inputType": "textarea",
                        "label": "Apa penyesuaian kelas yang dibutuhkan agar observasi tetap aman dan selesai dalam alokasi waktu?",
                        "placeholder": "Contoh: kelompok kecil, lembar observasi sederhana, batas area, atau pendamping tambahan.",
                        "required": True,
                        "answerKey": "classAdjustments",
                    },
                ],
                "reasoningSummary": (
                    "Opsi ini dipilih karena paling dekat dengan konteks lokal dan "
                    "mudah dijalankan tanpa kebutuhan alat khusus."
                ),
            },
            {
                "id": self._slug(f"kolaborasi-{subject_lens}", "kolaborasi"),
                "title": "Kampanye Solusi Kecil untuk Warga Sekolah",
                "themeId": "campuran",
                "themeLabel": "Campuran/lainnya",
                "description": (
                    "Siswa memilih satu isu nyata di sekolah, merancang pesan kampanye, "
                    "dan membuat produk komunikasi sederhana untuk mengajak warga sekolah "
                    "melakukan aksi positif."
                ),
                "lens": f"{subject_lens} & Komunikasi",
                "overview": (
                    f"Proyek ini mengubah temuan tentang {local_issue} menjadi poster, "
                    "naskah ajakan, infografik, atau presentasi singkat yang dapat "
                    "dipakai di lingkungan sekolah."
                ),
                "confirmationTags": [
                    {"id": "media_kampanye", "label": "Media kampanye tersedia"},
                    {"id": "izin_publikasi", "label": "Izin publikasi karya"},
                    {"id": "audiens", "label": "Sasaran warga sekolah jelas"},
                ],
                "clarificationQuestions": [
                    {
                        "id": "sasaran_kampanye",
                        "inputType": "textarea",
                        "label": "Siapa sasaran kampanye yang paling realistis untuk murid jangkau?",
                        "placeholder": "Contoh: teman satu kelas, adik kelas, petugas sekolah, atau orang tua.",
                        "required": True,
                        "answerKey": "observationPermit",
                    },
                    {
                        "id": "produk_kampanye",
                        "inputType": "single_choice",
                        "label": "Produk kampanye mana yang paling sesuai dengan fasilitas kelas?",
                        "required": True,
                        "answerKey": "mathFocusId",
                        "options": [
                            {"id": "poster", "label": "Poster atau infografik cetak."},
                            {"id": "presentasi", "label": "Presentasi singkat kelompok."},
                            {"id": "video", "label": "Video pendek sederhana."},
                        ],
                    },
                    {
                        "id": "batasan_publikasi",
                        "inputType": "textarea",
                        "label": "Batasan apa yang perlu dipastikan sebelum karya siswa dipublikasikan?",
                        "placeholder": "Contoh: tidak menampilkan wajah tanpa izin, lokasi publikasi, atau bahasa yang digunakan.",
                        "required": True,
                        "answerKey": "mainConfirmations",
                    },
                ],
                "reasoningSummary": (
                    "Opsi ini cocok bila observasi lapangan perlu dibuat lebih aman "
                    "dan produk akhir harus tetap terlihat nyata."
                ),
            },
            {
                "id": self._slug(f"data-{school_name}-{city}", "data-sekolah"),
                "title": "Audit Sederhana Layanan dan Fasilitas Sekolah",
                "themeId": "teknologi",
                "themeLabel": "Teknologi",
                "description": (
                    "Siswa mengumpulkan data sederhana tentang fasilitas atau layanan "
                    "yang sering digunakan, lalu membuat prioritas perbaikan berbasis "
                    "bukti."
                ),
                "lens": f"{subject_lens} & Data",
                "overview": (
                    "Proyek dilakukan di area sekolah atau lokasi terdekat yang aman. "
                    "Siswa belajar membuat instrumen pengamatan, mengolah data ringkas, "
                    "dan menyusun usulan yang sopan serta dapat ditindaklanjuti."
                ),
                "confirmationTags": [
                    {"id": "akses_fasilitas", "label": "Akses fasilitas"},
                    {"id": "alat_data", "label": "Alat pencatatan data"},
                    {"id": "etika_observasi", "label": "Etika observasi"},
                ],
                "clarificationQuestions": [
                    {
                        "id": "fasilitas_prioritas",
                        "inputType": "textarea",
                        "label": "Fasilitas atau layanan apa yang paling layak diaudit siswa terlebih dahulu?",
                        "placeholder": "Contoh: perpustakaan, kantin, tempat sampah, taman, toilet, halte, atau akses masuk sekolah.",
                        "required": True,
                        "answerKey": "observationPermit",
                    },
                    {
                        "id": "metode_data",
                        "inputType": "single_choice",
                        "label": "Cara pengumpulan data mana yang paling aman dan ringan untuk kelas ini?",
                        "required": True,
                        "answerKey": "mathFocusId",
                        "options": [
                            {"id": "ceklist", "label": "Checklist kondisi fasilitas."},
                            {"id": "hitung", "label": "Menghitung frekuensi penggunaan."},
                            {"id": "wawancara", "label": "Wawancara singkat dengan warga sekolah."},
                        ],
                    },
                    {
                        "id": "izin_data",
                        "inputType": "textarea",
                        "label": "Izin atau etika apa yang perlu ditegaskan agar audit tidak mengganggu warga sekolah?",
                        "placeholder": "Contoh: waktu pengamatan, area yang boleh difoto, dan cara bertanya kepada narasumber.",
                        "required": True,
                        "answerKey": "mainConfirmations",
                    },
                ],
                "reasoningSummary": (
                    "Opsi ini memberi struktur data yang jelas dan mudah disesuaikan "
                    "dengan fasilitas sekolah yang tersedia."
                ),
            },
        ]
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

    def _normalize_recommendations(
        self,
        generated: dict[str, Any],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(generated, dict):
            generated = {}

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

        result = dict(generated)
        result["projectOptions"] = options[:3]
        result.setdefault("selectionGuidance", fallback.get("selectionGuidance", ""))
        result.setdefault("reasoningSummary", fallback.get("reasoningSummary", ""))
        return result

    def _normalize_option(
        self,
        item: dict[str, Any],
        index: int,
        fallback_options: list[Any],
    ) -> dict[str, Any]:
        fallback = (
            fallback_options[index]
            if index < len(fallback_options) and isinstance(fallback_options[index], dict)
            else {}
        )
        title = self._first_text(item.get("title"), fallback.get("title"), f"Opsi Proyek {index + 1}")
        option_id = self._first_text(item.get("id"), self._slug(title, f"opsi-{index + 1}"))
        questions = item.get("clarificationQuestions") or item.get("detailQuestions") or item.get("questions")
        if not isinstance(questions, list):
            questions = fallback.get("clarificationQuestions") or []
        tags = item.get("confirmationTags") or item.get("confirmTags") or item.get("requiredDetails")
        if not isinstance(tags, list):
            tags = fallback.get("confirmationTags") or []
        normalized_tags = self._normalize_tags(tags)
        if not normalized_tags:
            normalized_tags = self._normalize_tags(fallback.get("confirmationTags") or [])
        normalized_questions = self._normalize_questions(questions)
        if not normalized_questions:
            normalized_questions = self._normalize_questions(fallback.get("clarificationQuestions") or [])
        return {
            "id": self._slug(option_id, f"opsi-{index + 1}"),
            "title": title,
            "themeId": self._first_text(item.get("themeId"), fallback.get("themeId"), ""),
            "themeLabel": self._first_text(item.get("themeLabel"), item.get("theme"), fallback.get("themeLabel"), ""),
            "description": self._first_text(item.get("description"), fallback.get("description"), ""),
            "lens": self._first_text(item.get("lens"), fallback.get("lens"), "Lintas Disiplin"),
            "overview": self._first_text(item.get("overview"), item.get("projectOverview"), fallback.get("overview"), ""),
            "confirmationTags": normalized_tags,
            "clarificationQuestions": normalized_questions,
            "reasoningSummary": self._first_text(
                item.get("reasoningSummary"),
                item.get("reason"),
                fallback.get("reasoningSummary"),
                "",
            ),
        }

    def _normalize_tags(self, raw_tags: list[Any]) -> list[dict[str, str]]:
        tags: list[dict[str, str]] = []
        for index, tag in enumerate(raw_tags[:6]):
            if isinstance(tag, str):
                label = tag.strip()
                if label:
                    tags.append({"id": self._slug(label, f"tag-{index + 1}"), "label": label})
            elif isinstance(tag, dict):
                label = self._first_text(tag.get("label"), tag.get("title"), tag.get("name"), "")
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
            label = self._first_text(question.get("label"), question.get("question"), question.get("title"), "")
            if not label:
                continue
            input_type = self._first_text(question.get("inputType"), question.get("type"), "textarea")
            if input_type in {"choice", "radio", "select"}:
                input_type = "single_choice"
            if input_type not in {"textarea", "short_text", "single_choice"}:
                input_type = "textarea"
            options = question.get("options")
            normalized_options = self._normalize_tags(options if isinstance(options, list) else [])
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
            answer_key = self._first_text(question.get("answerKey"), question.get("field"), "")
            if answer_key:
                normalized["answerKey"] = answer_key
            if normalized_options:
                normalized["options"] = normalized_options
            questions.append(normalized)
        return questions

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
        merged.update({key: value for key, value in stage_one.items() if key not in {"inputs", "spec", "mission", "wizard"}})
        return merged

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
