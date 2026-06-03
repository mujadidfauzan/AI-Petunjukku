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
from app.services.pjbl.pjbl_prompt_templates import (
    PJBL_RECOMMENDATION_SYSTEM_PROMPT,
    PJBL_THEME_RECOMMENDATION_SYSTEM_PROMPT,
)


THEME_RECOMMENDATION_TYPE = "project_theme_recommendation"
# Maximum number of themes to return; not a required count.
DEFAULT_THEME_COUNT = 4
PROJECT_RECOMMENDATION_COUNT = 3
SUBJECT_FIELD_KEYS = {
    "mapel",
    "mataPelajaran",
    "mata_pelajaran",
    "selectedSubject",
    "selected_subject",
    "subject",
    "subjectName",
    "subject_name",
}
SUBJECT_THEME_HINTS = {
    "ipa": [
        "Limbah",
        "Ekosistem",
        "Kesehatan",
        "Energi",
        "Pencemaran",
        "Air",
        "Tanaman",
        "Sampah",
        "Plastik",
    ],
    "ipas": [
        "Lingkungan",
        "Ekosistem",
        "Kesehatan",
        "Energi",
        "Komunitas",
        "Limbah",
        "Air",
    ],
    "ips": [
        "Ekonomi",
        "Budaya",
        "Sosial",
        "Komunitas",
        "Sejarah",
        "Lingkungan",
    ],
    "matematika": [
        "Data",
        "Pengukuran",
        "Statistika",
        "Pola",
        "Geometri",
        "Anggaran",
    ],
    "bahasa_indonesia": [
        "Literasi",
        "Cerita",
        "Komunikasi",
        "Narasi",
        "Presentasi",
        "Publikasi",
    ],
    "bahasa_inggris": [
        "Komunikasi",
        "Cerita",
        "Kosakata",
        "Presentasi",
        "Percakapan",
    ],
    "informatika": [
        "Data",
        "Aplikasi",
        "Digital",
        "Algoritma",
        "Keamanan",
        "Informasi",
    ],
    "pjok": [
        "Kebugaran",
        "Kesehatan",
        "Gerak",
        "Gizi",
        "Permainan",
    ],
    "prakarya": [
        "Kerajinan",
        "Produk",
        "Budidaya",
        "Teknologi",
        "Kewirausahaan",
    ],
    "pendidikan_pancasila": [
        "Toleransi",
        "Demokrasi",
        "Gotongroyong",
        "Kewargaan",
        "Keragaman",
    ],
}
CONTEXT_THEME_HINTS = (
    (("sampah", "plastik", "limbah"), ("Limbah", "Ekosistem", "Kesehatan", "Pencemaran", "Sampah")),
    (("air", "sungai", "banjir"), ("Air", "Ekosistem", "Kesehatan", "Konservasi")),
    (("energi", "listrik", "surya"), ("Energi", "Teknologi", "Konservasi")),
    (("pengeluaran", "uang jajan", "anggaran", "transportasi", "paket data", "biaya"), ("Data", "Anggaran", "Statistika", "Konsumsi")),
    (("harga", "pokok", "sembako", "beras", "telur", "cabai", "minyak", "warung", "kantin"), ("Ekonomi", "Konsumsi", "Pasar", "Kebutuhan", "DayaBeli")),
    (("makanan", "gizi", "kantin"), ("Gizi", "Kesehatan", "Konsumsi")),
    (("tanaman", "kebun", "pohon"), ("Tanaman", "Ekosistem", "Budidaya")),
    (("data", "survei", "grafik"), ("Data", "Statistika", "Pengukuran")),
    (("cerita", "poster", "kampanye"), ("Literasi", "Komunikasi", "Publikasi")),
    (("pasar", "jual", "beli"), ("Ekonomi", "Kewirausahaan", "Komunitas")),
)
THEME_CONFLICT_GROUPS = (
    {"limbah", "sampah", "plastik", "pencemaran"},
    {"lingkungan", "ekosistem", "konservasi"},
    {"kesehatan", "gizi", "konsumsi"},
    {"energi", "listrik", "surya"},
    {"data", "statistika"},
    {"literasi", "cerita", "narasi"},
    {"ekonomi", "kewirausahaan"},
)
THEME_STOPWORDS = {
    "akan",
    "atau",
    "bagi",
    "banyak",
    "batasan",
    "belajar",
    "berada",
    "beragam",
    "berbasis",
    "berdasarkan",
    "berkaitan",
    "bisa",
    "dalam",
    "dapat",
    "dari",
    "dengan",
    "dibuat",
    "dilakukan",
    "disusun",
    "ditemukan",
    "durasi",
    "fasilitas",
    "guru",
    "halaman",
    "hasil",
    "ingin",
    "indonesia",
    "ipa",
    "ipas",
    "ips",
    "istirahat",
    "jam",
    "karakteristik",
    "kelas",
    "kegiatan",
    "kendala",
    "konteks",
    "lokal",
    "masalah",
    "melalui",
    "memiliki",
    "menjadi",
    "mata",
    "mapel",
    "murid",
    "pada",
    "pelajaran",
    "pembelajaran",
    "pelaksanaan",
    "pengelolaan",
    "pengurangan",
    "peserta",
    "pjok",
    "projek",
    "project",
    "proyek",
    "saat",
    "saja",
    "sangat",
    "sebagai",
    "selectedsubject",
    "setelah",
    "sekolah",
    "semua",
    "siswa",
    "stage",
    "subject",
    "subjectname",
    "tempat",
    "tema",
    "terbatas",
    "tersedia",
    "untuk",
    "yang",
}


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
        references = []
        if self._is_theme_recommendation(recommendation_type):
            fallback = self._fallback_theme_recommendations(payload)
            messages = self._build_theme_messages(
                payload=payload,
                fallback=fallback,
            )
            generated = await self.llm_client.generate_json(
                messages,
                fallback,
                temperature=0.25,
                max_tokens=300,
            )
            recommendations = self._normalize_theme_recommendations(
                generated,
                fallback,
                payload,
            )
        else:
            fallback = self._fallback_recommendations(
                payload,
                recommendation_type,
                references,
            )
            messages = self._build_project_messages(
                payload=payload,
                fallback=fallback,
            )
            generated = await self.llm_client.generate_json(messages, fallback)
            recommendations = self._normalize_project_recommendations(
                generated,
                fallback,
            )
        return RecommendStageResponse(
            rppType=payload.project.rppType,
            recommendationType=recommendation_type,
            targetStageNumber=int(target_stage_number)
            if target_stage_number is not None
            else None,
            ragReferences=references,
            recommendations=recommendations,
        )

    def _build_theme_messages(
        self,
        *,
        payload: RecommendStageRequest,
        fallback: dict[str, Any],
    ) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": PJBL_THEME_RECOMMENDATION_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "previousStages": [
                            stage.model_dump() for stage in payload.previousStages
                        ],
                        "targetStage": payload.targetStage,
                        "subjectConstraint": self._subject_constraint(payload),
                        "maxThemes": DEFAULT_THEME_COUNT,
                        "themeCountRule": (
                            "Maksimal, bukan jumlah wajib. Jangan mengisi slot "
                            "kosong dengan tema yang tidak relevan."
                        ),
                        "requiredResponseShape": fallback,
                    },
                    ensure_ascii=False,
                ),
            },
        ]

    def _build_project_messages(
        self,
        *,
        payload: RecommendStageRequest,
        fallback: dict[str, Any],
    ) -> list[dict[str, str]]:
        return [
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
                        "stageOneContext": self._stage_one_context(payload),
                        "targetStage": payload.targetStage,
                        "selectedTheme": self._selected_theme(payload),
                        "projectRecommendationCount": PROJECT_RECOMMENDATION_COUNT,
                        "projectRecommendationRule": (
                            "Buat tepat 3 rekomendasi proyek yang berdiri sendiri. "
                            "Setiap proyek harus berbeda fokus, produk, dan aktivitas "
                            "utama; bukan tahap atau pengembangan dari proyek lain."
                        ),
                        "requiredResponseShape": fallback,
                    },
                    ensure_ascii=False,
                ),
            },
        ]

    def _is_theme_recommendation(self, recommendation_type: str) -> bool:
        return recommendation_type == THEME_RECOMMENDATION_TYPE

    def _fallback_recommendations(
        self,
        payload: RecommendStageRequest,
        recommendation_type: str,
        references: list[Any],
    ) -> dict[str, Any]:
        topic = payload.targetStage.get("topic") or payload.project.title or "topik pembelajaran"
        stage_one = self._stage_one_context(payload)
        local_issue = stage_one.get("localIssue") or payload.targetStage.get("topic") or topic
        selected_theme = self._selected_theme(payload)
        project_theme = selected_theme or str(local_issue)
        project_recommendations = self._project_recommendation_options(
            project_theme=project_theme,
            local_issue=str(local_issue),
            recommendation_type=recommendation_type,
        )
        title_options = [
            str(project["recommendedProjectTitle"])
            for project in project_recommendations
        ]
        primary_project = project_recommendations[0]
        return {
            "projectRecommendations": project_recommendations,
            "recommendedProjectTitle": primary_project["recommendedProjectTitle"],
            "projectTitleOptions": title_options,
            "projectTheme": project_theme,
            "projectBackground": primary_project["projectBackground"],
            "projectObjectives": primary_project["projectObjectives"],
            "drivingQuestion": primary_project["drivingQuestion"],
            "studentProduct": primary_project["studentProduct"],
            "projectActivitiesOverview": primary_project["projectActivitiesOverview"],
            "feasibilityNotes": primary_project["feasibilityNotes"],
            "riskMitigation": primary_project["riskMitigation"],
            "reasoningSummary": (
                f"Rekomendasi {recommendation_type} disusun dari konteks project, "
                "terutama semua informasi yang tersedia pada Stage 1. Tiga opsi "
                "proyek dibuat sebagai alternatif yang berdiri sendiri, bukan "
                "sebagai urutan pelaksanaan."
            ),
        }

    def _fallback_theme_recommendations(
        self,
        payload: RecommendStageRequest,
    ) -> dict[str, Any]:
        stage_one = self._stage_one_context(payload)
        subject = self._subject_constraint(payload)
        context_text = self._text_values(stage_one)
        themes = self._subject_theme_candidates(subject, context_text)
        themes.extend(
            theme
            for theme in self._extract_theme_words(stage_one)
            if self._is_subject_aligned_theme(theme, subject, context_text)
        )
        if len(themes) < DEFAULT_THEME_COUNT:
            extra_context = self._extra_theme_context(payload)
            extra_text = self._text_values(extra_context)
            themes.extend(
                theme
                for theme in self._extract_theme_words(extra_context)
                if self._is_subject_aligned_theme(theme, subject, extra_text)
            )

        return {"themes": self._ensure_theme_count(themes, subject)}

    def _normalize_theme_recommendations(
        self,
        recommendations: dict[str, Any],
        fallback: dict[str, Any],
        payload: RecommendStageRequest,
    ) -> dict[str, Any]:
        raw_themes = recommendations.get("themes")
        if not isinstance(raw_themes, list):
            raw_themes = []

        themes = []
        subject = self._subject_constraint(payload)
        for item in raw_themes:
            theme = self._normalize_theme_word(item)
            if theme and theme.casefold() not in {value.casefold() for value in themes}:
                themes.append(theme)

        themes.extend(str(theme) for theme in fallback.get("themes", []))
        return {"themes": self._ensure_theme_count(themes, subject)}

    def _stage_one_context(self, payload: RecommendStageRequest) -> dict[str, Any]:
        return next(
            (
                stage.contentJson
                for stage in payload.previousStages
                if stage.stageNumber == 1
            ),
            {},
        )

    def _subject_constraint(self, payload: RecommendStageRequest) -> str | None:
        stage_subject = self._subject_from_value(self._stage_one_context(payload))
        return stage_subject or payload.project.subject

    def _selected_theme(self, payload: RecommendStageRequest) -> str | None:
        selected_theme = payload.targetStage.get("selectedTheme")
        if not selected_theme:
            return None
        return self._normalize_theme_word(selected_theme)

    def _normalize_project_recommendations(
        self,
        recommendations: dict[str, Any],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(recommendations, dict):
            recommendations = {}

        projects = []
        seen_titles = set()
        raw_projects = recommendations.get("projectRecommendations")
        if isinstance(raw_projects, list):
            for item in raw_projects:
                project = self._normalize_project_recommendation_item(item)
                if not project:
                    continue
                title_key = project["recommendedProjectTitle"].casefold()
                if title_key in seen_titles:
                    continue
                seen_titles.add(title_key)
                projects.append(project)
                if len(projects) == PROJECT_RECOMMENDATION_COUNT:
                    break

        legacy_project = self._normalize_project_recommendation_item(recommendations)
        if not projects and legacy_project:
            projects.append(legacy_project)
            seen_titles.add(legacy_project["recommendedProjectTitle"].casefold())

        fallback_projects = fallback.get("projectRecommendations")
        if isinstance(fallback_projects, list):
            for item in fallback_projects:
                if len(projects) == PROJECT_RECOMMENDATION_COUNT:
                    break
                project = self._normalize_project_recommendation_item(item)
                if not project:
                    continue
                title_key = project["recommendedProjectTitle"].casefold()
                if title_key in seen_titles:
                    continue
                seen_titles.add(title_key)
                projects.append(project)

        if not projects:
            return fallback

        primary_project = projects[0]
        result = dict(recommendations)
        result["projectRecommendations"] = projects
        result["recommendedProjectTitle"] = primary_project["recommendedProjectTitle"]
        result["projectTitleOptions"] = [
            project["recommendedProjectTitle"] for project in projects
        ]
        result["projectTheme"] = (
            primary_project.get("projectTheme") or fallback.get("projectTheme")
        )
        for key in (
            "projectBackground",
            "projectObjectives",
            "drivingQuestion",
            "studentProduct",
            "projectActivitiesOverview",
            "feasibilityNotes",
            "riskMitigation",
        ):
            if key in primary_project:
                result[key] = primary_project[key]
        return result

    def _normalize_project_recommendation_item(
        self,
        value: Any,
    ) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None

        title = (
            value.get("recommendedProjectTitle")
            or value.get("projectTitle")
            or value.get("title")
        )
        if not isinstance(title, str) or not title.strip():
            return None

        project = dict(value)
        project["recommendedProjectTitle"] = title.strip()
        return project

    def _project_recommendation_options(
        self,
        *,
        project_theme: str,
        local_issue: str,
        recommendation_type: str,
    ) -> list[dict[str, Any]]:
        issue_context = self._compact_issue_text(local_issue)
        option_specs = (
            {
                "title": f"Pemetaan {project_theme} di Sekitar Sekolah",
                "focus": "Observasi dan pemetaan data sederhana.",
                "objective": "Peserta didik mampu mengumpulkan dan menyajikan data sederhana dari konteks sekitar.",
                "question": f"Apa pola masalah {project_theme} yang terlihat dari data sekitar sekolah?",
                "products": ["Tabel data", "Peta temuan", "Presentasi hasil"],
                "activities": ["Observasi konteks Stage 1", "Pengumpulan data", "Penyajian temuan", "Presentasi"],
                "risk": "Data siswa kurang konsisten.",
                "mitigation": "Guru menyiapkan format observasi singkat dan contoh pengisian.",
            },
            {
                "title": f"Simulasi Solusi {project_theme}",
                "focus": "Simulasi pilihan, dampak, dan pengambilan keputusan.",
                "objective": "Peserta didik mampu membandingkan beberapa pilihan solusi dan dampaknya.",
                "question": f"Pilihan solusi apa yang paling realistis untuk masalah {project_theme}?",
                "products": ["Skenario simulasi", "Tabel perbandingan", "Rekomendasi solusi"],
                "activities": ["Menyusun skenario", "Membandingkan pilihan", "Simulasi keputusan", "Refleksi"],
                "risk": "Diskusi melebar dari konteks utama.",
                "mitigation": "Guru memberi batasan skenario dan kriteria keputusan yang jelas.",
            },
            {
                "title": f"Kampanye Aksi {project_theme}",
                "focus": "Komunikasi solusi dan aksi edukasi warga sekolah.",
                "objective": "Peserta didik mampu merancang pesan aksi yang relevan dengan konteks Stage 1.",
                "question": f"Bagaimana siswa dapat mengajak warga sekolah merespons masalah {project_theme}?",
                "products": ["Media kampanye", "Naskah ajakan", "Dokumentasi aksi"],
                "activities": ["Merumuskan pesan", "Membuat media", "Melakukan kampanye kecil", "Refleksi respons"],
                "risk": "Pesan kampanye terlalu umum.",
                "mitigation": "Guru meminta setiap pesan dikaitkan langsung dengan konteks Stage 1.",
            },
        )
        return [
            self._build_project_recommendation_from_spec(
                project_theme=project_theme,
                issue_context=issue_context,
                recommendation_type=recommendation_type,
                spec=spec,
            )
            for spec in option_specs[:PROJECT_RECOMMENDATION_COUNT]
        ]

    def _build_project_recommendation_from_spec(
        self,
        *,
        project_theme: str,
        issue_context: str,
        recommendation_type: str,
        spec: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "recommendedProjectTitle": spec["title"],
            "projectTheme": project_theme,
            "projectFocus": spec["focus"],
            "projectBackground": f"Proyek disusun dari konteks Stage 1: {issue_context}",
            "projectObjectives": [
                f"Peserta didik mampu mengidentifikasi masalah terkait {project_theme}.",
                spec["objective"],
                "Peserta didik mampu mempresentasikan hasil proyek secara kolaboratif.",
            ],
            "drivingQuestion": spec["question"],
            "studentProduct": spec["products"],
            "projectActivitiesOverview": spec["activities"],
            "feasibilityNotes": "Opsi ini dibuat sederhana agar realistis dilakukan sesuai konteks Stage 1.",
            "riskMitigation": [
                {
                    "risk": spec["risk"],
                    "mitigation": spec["mitigation"],
                }
            ],
            "independenceNote": "Proyek ini berdiri sendiri dan bukan tahap dari opsi proyek lain.",
            "reasoningSummary": (
                f"Rekomendasi {recommendation_type} ini memakai tema {project_theme} "
                "dan konteks Stage 1 sebagai dasar."
            ),
        }

    def _compact_issue_text(self, local_issue: str) -> str:
        text = " ".join(str(local_issue or "").split())
        if not text:
            return "konteks Stage 1"
        if len(text) <= 180:
            return text
        return f"{text[:177].rstrip()}..."
    def _extra_theme_context(self, payload: RecommendStageRequest) -> dict[str, Any]:
        return {
            "project": payload.project.model_dump(),
            "school": payload.school.model_dump() if payload.school else {},
            "teacherClass": payload.teacherClass.model_dump()
            if payload.teacherClass
            else {},
            "targetStage": payload.targetStage,
        }

    def _subject_from_value(self, value: Any) -> str | None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key in SUBJECT_FIELD_KEYS:
                    subject = self._first_text_value(item)
                    if subject:
                        return subject
            for item in value.values():
                subject = self._subject_from_value(item)
                if subject:
                    return subject
        if isinstance(value, list):
            for item in value:
                subject = self._subject_from_value(item)
                if subject:
                    return subject
        return None

    def _first_text_value(self, value: Any) -> str | None:
        if isinstance(value, str):
            cleaned = value.strip()
            return cleaned or None
        if isinstance(value, dict):
            for key in ("subject", "subjectName", "name", "label", "title"):
                item = value.get(key)
                if isinstance(item, str) and item.strip():
                    return item.strip()
        if isinstance(value, list):
            for item in value:
                text = self._first_text_value(item)
                if text:
                    return text
        return None

    def _subject_theme_candidates(
        self,
        subject: str | None,
        context_text: str,
    ) -> list[str]:
        context_candidates = self._context_theme_candidates(context_text)
        subject_candidates = self._subject_theme_hints(subject)
        if context_candidates:
            return context_candidates
        if not subject_candidates:
            return context_candidates

        return subject_candidates

    def _context_theme_candidates(self, context_text: str) -> list[str]:
        lowered = context_text.casefold()
        themes = []
        for keywords, candidates in CONTEXT_THEME_HINTS:
            if any(keyword in lowered for keyword in keywords):
                themes.extend(candidates)
        return themes

    def _subject_theme_hints(self, subject: str | None) -> list[str]:
        subject_key = self._subject_key(subject)
        if not subject_key:
            return []
        if subject_key in SUBJECT_THEME_HINTS:
            return SUBJECT_THEME_HINTS[subject_key]
        for key, themes in SUBJECT_THEME_HINTS.items():
            if key in subject_key or subject_key in key:
                return themes
        return []

    def _is_subject_aligned_theme(
        self,
        theme: str,
        subject: str | None,
        context_text: str,
    ) -> bool:
        subject_hints = self._subject_theme_hints(subject)
        if not subject_hints:
            return True

        theme_key = theme.casefold()
        hint_keys = {hint.casefold() for hint in subject_hints}
        if theme_key in hint_keys:
            return True

        context_candidates = {
            candidate.casefold()
            for candidate in self._context_theme_candidates(context_text)
        }
        return theme_key in context_candidates.intersection(hint_keys)

    def _subject_key(self, subject: str | None) -> str | None:
        if not subject:
            return None
        key = "_".join(
            "".join(
                char.lower() if char.isalnum() else " "
                for char in subject
            ).split()
        )
        aliases = {
            "ilmu_pengetahuan_alam": "ipa",
            "ilmu_pengetahuan_alam_dan_sosial": "ipas",
            "ilmu_pengetahuan_sosial": "ips",
            "pendidikan_jasmani_olahraga_dan_kesehatan": "pjok",
            "pkn": "pendidikan_pancasila",
            "ppkn": "pendidikan_pancasila",
        }
        return aliases.get(key, key)

    def _extract_theme_words(self, value: Any) -> list[str]:
        text = self._text_values(value)

        themes = []
        seen = set()
        for token in re.findall(r"[^\W_]+", text, flags=re.UNICODE):
            theme = self._normalize_theme_word(token)
            if not theme:
                continue
            key = theme.casefold()
            if key in seen:
                continue
            seen.add(key)
            themes.append(theme)
        return themes

    def _text_values(self, value: Any) -> str:
        if isinstance(value, dict):
            return " ".join(self._text_values(item) for item in value.values())
        if isinstance(value, list):
            return " ".join(self._text_values(item) for item in value)
        return str(value or "")

    def _normalize_theme_word(self, value: Any) -> str | None:
        words = re.findall(r"[^\W_]+", str(value), flags=re.UNICODE)
        for word in words:
            lowered = word.casefold()
            if lowered in THEME_STOPWORDS:
                continue
            if len(word) < 3 or word.isdigit():
                continue
            return word[:1].upper() + word[1:].lower()
        return None

    def _theme_conflict_key(self, theme: str) -> str:
        theme_key = theme.casefold()
        for index, group in enumerate(THEME_CONFLICT_GROUPS):
            if theme_key in group:
                return f"group:{index}"
        return f"theme:{theme_key}"

    def _ensure_theme_count(
        self,
        themes: list[str],
        subject: str | None = None,
    ) -> list[str]:
        normalized = []
        seen = set()
        for theme in themes:
            normalized_theme = self._normalize_theme_word(theme)
            if not normalized_theme:
                continue
            key = self._theme_conflict_key(normalized_theme)
            if key in seen:
                continue
            seen.add(key)
            normalized.append(normalized_theme)
            if len(normalized) == DEFAULT_THEME_COUNT:
                return normalized

        return normalized
