from __future__ import annotations

import json
import re
import unicodedata
from typing import Any

from app.schemas.lintas_disiplin_schema import (
    LintasDisiplinOptionSchema,
    RecommendLintasDisiplinRequest,
    RecommendLintasDisiplinResponse,
)
from app.services.llm_client import LLMClient
from app.services.prompt_builder_service import PromptBuilderService


DEFAULT_LINTAS_DISIPLIN_LABELS = [
    "Matematika",
    "Bahasa Indonesia",
    "Fisika",
    "Seni Budaya",
    "Biologi",
    "Pendidikan Kewarganegaraan",
    "Kimia",
    "Agama",
]


class IntraLintasDisiplinService:
    def __init__(
        self,
        llm_client: LLMClient | None = None,
        prompt_builder: PromptBuilderService | None = None,
    ) -> None:
        self.llm_client = llm_client or LLMClient()
        self.prompt_builder = prompt_builder or PromptBuilderService()

    async def recommend(
        self, payload: RecommendLintasDisiplinRequest
    ) -> RecommendLintasDisiplinResponse:
        main_subject = self._main_subject(payload)
        stage1_context = self._stage1_context(payload)
        fallback = self._fallback_subjects(main_subject)
        messages = [
            {
                "role": "system",
                "content": (
                    "Anda adalah asisten perencana pembelajaran Petunjukku. "
                    "Tugas Anda merekomendasikan mata pelajaran lintas disiplin yang "
                    "paling relevan untuk mengaitkan pembelajaran intrakurikuler. "
                    "Jawab hanya dalam JSON valid."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "instruction": (
                            "Rekomendasikan tepat 5 mata pelajaran lintas disiplin "
                            "yang paling cocok dikaitkan dengan mata pelajaran utama "
                            "dan konteks pembelajaran. Jangan memasukkan mata pelajaran "
                            "utama itu sendiri. Pilih mapel yang benar-benar bisa "
                            "memperkaya pembelajaran, bukan sekadar daftar umum. "
                            "Gunakan nama mapel resmi di Indonesia (contoh: Matematika, "
                            "Bahasa Indonesia, Fisika). Return hanya field subjects "
                            "berupa array 5 objek {id, label}. Field id gunakan "
                            "slug lowercase dengan underscore, misalnya bahasa_indonesia."
                        ),
                        "mataPelajaranUtama": main_subject,
                        "konteksStage1": stage1_context,
                        "profilLulusan": payload.profilLulusan,
                        "project": payload.project.model_dump(),
                        "school": payload.school.model_dump() if payload.school else {},
                        "teacherClass": payload.teacherClass.model_dump()
                        if payload.teacherClass
                        else {},
                        "requiredResponseShape": {"subjects": fallback},
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        generated = await self.llm_client.generate_json(messages, {"subjects": fallback})
        subjects = self._normalize_subjects(
            generated,
            main_subject=main_subject,
            fallback=fallback,
        )
        return RecommendLintasDisiplinResponse(
            subjects=subjects[:5],
            model=self.llm_client.model_name,
            source="ai_service",
        )

    def _main_subject(self, payload: RecommendLintasDisiplinRequest) -> str:
        for stage in payload.previousStages:
            if stage.stageNumber != 1:
                continue
            content = stage.contentJson or {}
            for key in ("mataPelajaran", "subject", "mapel"):
                value = content.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
        return (payload.project.subject or "").strip()

    def _stage1_context(self, payload: RecommendLintasDisiplinRequest) -> dict[str, Any]:
        for stage in payload.previousStages:
            if stage.stageNumber == 1 and isinstance(stage.contentJson, dict):
                return stage.contentJson
        return {}

    def _fallback_subjects(self, main_subject: str) -> list[dict[str, str]]:
        main_key = self._normalize_subject_key(main_subject)
        labels: list[str] = []
        for label in DEFAULT_LINTAS_DISIPLIN_LABELS:
            if self._normalize_subject_key(label) == main_key:
                continue
            labels.append(label)
            if len(labels) >= 5:
                break
        if len(labels) < 5:
            for label in DEFAULT_LINTAS_DISIPLIN_LABELS:
                if label in labels:
                    continue
                labels.append(label)
                if len(labels) >= 5:
                    break
        return [
            {"id": self._slugify_label(label), "label": label}
            for label in labels[:5]
        ]

    def _normalize_subjects(
        self,
        generated: dict[str, Any],
        *,
        main_subject: str,
        fallback: list[dict[str, str]],
    ) -> list[LintasDisiplinOptionSchema]:
        raw_items = generated.get("subjects")
        if not isinstance(raw_items, list):
            raw_items = generated.get("mataPelajaranLintasDisiplin")
        if not isinstance(raw_items, list):
            raw_items = []

        main_key = self._normalize_subject_key(main_subject)
        seen: set[str] = set()
        normalized: list[LintasDisiplinOptionSchema] = []

        for item in raw_items:
            label = ""
            item_id = ""
            if isinstance(item, str):
                label = item.strip()
            elif isinstance(item, dict):
                label = str(item.get("label") or item.get("name") or "").strip()
                item_id = str(item.get("id") or "").strip()
            if not label:
                continue
            if self._normalize_subject_key(label) == main_key:
                continue
            slug = item_id or self._slugify_label(label)
            if slug in seen:
                continue
            seen.add(slug)
            normalized.append(
                LintasDisiplinOptionSchema(id=slug, label=label)
            )
            if len(normalized) >= 5:
                return normalized

        for item in fallback:
            label = item["label"]
            slug = item["id"]
            if self._normalize_subject_key(label) == main_key or slug in seen:
                continue
            seen.add(slug)
            normalized.append(
                LintasDisiplinOptionSchema(id=slug, label=label)
            )
            if len(normalized) >= 5:
                break
        return normalized

    def _slugify_label(self, label: str) -> str:
        normalized = unicodedata.normalize("NFKD", label.strip().lower())
        ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
        slug = re.sub(r"[^a-z0-9]+", "_", ascii_text).strip("_")
        return slug or "mapel"

    def _normalize_subject_key(self, value: str) -> str:
        return self._slugify_label(value).replace("_", "")
