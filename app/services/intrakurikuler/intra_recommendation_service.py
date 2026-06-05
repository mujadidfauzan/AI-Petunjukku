from __future__ import annotations

import json
import re
from typing import Any

from app.schemas.recommendation_schema import (
    RecommendStageRequest,
    RecommendStageResponse,
)
from app.schemas.rag_schema import RagReference, RagSearchRequest, RagSearchResponse
from app.services.llm_client import LLMClient
from app.services.prompt_builder_service import PromptBuilderService
from app.services.rag_service import RAGService
from app.services.intrakurikuler.intra_prompt_templates import (
    INTRA_RECOMMENDATION_SYSTEM_PROMPT,
)


class IntraRecommendationService:
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
        rag_response = await self.rag_service.search(
            RagSearchRequest(
                query=topic or recommendation_type,
                subject=payload.project.subject,
                phase=payload.project.phase,
                topK=int(payload.options.get("topK") or 5),
                documentType="capaian_pembelajaran",
            )
        )
        references = self._references_from_rag_response(rag_response)
        capaian_pembelajaran = self._capaian_pembelajaran_from_payload_or_rag(
            payload,
            rag_response,
            references,
        )
        fallback = self._fallback_recommendations(
            payload,
            recommendation_type,
            references,
            capaian_pembelajaran,
        )
        cp_input = {
            "text": fallback["capaianPembelajaran"],
        }
        messages = [
            {
                "role": "system",
                "content": INTRA_RECOMMENDATION_SYSTEM_PROMPT,
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "instruction": (
                            "Gunakan capaianPembelajaran.text sebagai CP resmi. "
                            "Jangan menulis ulang CP menjadi CP baru. Turunkan 3-5 "
                            "tujuan pembelajaran yang spesifik, terukur, dan sesuai "
                            "dengan CP serta konteks targetStage. Setiap tujuan harus "
                            "diawali 'Murid mampu ...'. Return hanya dua field: "
                            "capaianPembelajaran dan tujuanPembelajaran."
                        ),
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
                        "capaianPembelajaran": cp_input,
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

    def _references_from_rag_response(
        self,
        rag_response: RagSearchResponse,
    ) -> list[RagReference]:
        return [
            RagReference(
                cpReferenceId=str(source.metadata.get("cp_record_id") or source.chunk_id),
                sourceTitle=str(
                    source.metadata.get("source")
                    or source.metadata.get("file_name")
                    or ""
                ),
                documentType=str(
                    source.metadata.get("content_type") or "capaian_pembelajaran"
                ),
                phase=str(source.metadata.get("phase"))
                if source.metadata.get("phase")
                else None,
                subject=str(source.metadata.get("subject"))
                if source.metadata.get("subject")
                else None,
                element=source.metadata.get("element"),
                chunkText=source.preview,
                similarityScore=source.similarity,
                metadata=source.metadata,
            )
            for source in rag_response.sources
        ]

    def _capaian_pembelajaran_from_payload_or_rag(
        self,
        payload: RecommendStageRequest,
        rag_response: RagSearchResponse,
        references: list[RagReference],
    ) -> str:
        explicit_cp = self._explicit_capaian_pembelajaran(payload)
        if explicit_cp:
            return explicit_cp

        topic = str(payload.targetStage.get("topic") or payload.project.title or "")
        full_reference_text = (
            self._full_reference_text(payload, references[0]) if references else ""
        )
        element = self._infer_element(topic, payload.targetStage, full_reference_text)
        element_cp = self._extract_element_cp(full_reference_text, element)
        if element_cp:
            return element_cp

        cp_text = str(rag_response.cpText or "").strip()
        if cp_text and "Informasi tidak ditemukan" not in cp_text:
            return cp_text

        if full_reference_text:
            return self._clean_cp_text(full_reference_text)

        return "Referensi Capaian Pembelajaran belum tersedia dari RAG."

    def _explicit_capaian_pembelajaran(
        self,
        payload: RecommendStageRequest,
    ) -> str | None:
        candidates = [
            payload.targetStage.get("capaianPembelajaran"),
            payload.targetStage.get("capaianPembelajaranText"),
            payload.targetStage.get("cpText"),
            payload.options.get("capaianPembelajaran"),
            payload.options.get("capaianPembelajaranText"),
            payload.options.get("cpText"),
        ]

        for candidate in candidates:
            text = self._text_from_possible_cp(candidate)
            if text:
                return text

        for stage in payload.previousStages:
            if stage.stageNumber != 2:
                continue
            content = stage.contentJson or {}
            for key in (
                "capaianPembelajaran",
                "capaianPembelajaranText",
                "cpText",
            ):
                text = self._text_from_possible_cp(content.get(key))
                if text:
                    return text

        return None

    def _text_from_possible_cp(self, value: Any) -> str | None:
        if isinstance(value, str) and value.strip():
            return self._clean_cp_text(value)
        if isinstance(value, dict):
            for key in ("text", "content", "capaianPembelajaran", "cpText"):
                item = value.get(key)
                if isinstance(item, str) and item.strip():
                    return self._clean_cp_text(item)
        return None

    def _full_reference_text(
        self,
        payload: RecommendStageRequest,
        reference: RagReference,
    ) -> str:
        records = self.rag_service.vector_store.list_references(
            subject=payload.project.subject,
            phase=payload.project.phase,
            document_type="capaian_pembelajaran",
        )

        for record in records:
            metadata = record.get("metadata") or {}
            record_id = (
                record.get("cpReferenceId")
                or metadata.get("cpRecordId")
                or metadata.get("cp_record_id")
            )
            if str(record_id) == reference.cpReferenceId:
                return str(record.get("chunkText") or "")

        return reference.chunkText

    def _infer_element(
        self,
        topic: str,
        target_stage: dict[str, Any],
        reference_text: str,
    ) -> str | None:
        explicit_element = (
            target_stage.get("element")
            or target_stage.get("domain")
            or target_stage.get("domainMateri")
        )
        if explicit_element:
            return str(explicit_element)

        text = f"{topic} {reference_text[:1000]}".casefold()
        element_keywords = {
            "Aljabar": [
                "aljabar",
                "polinomial",
                "variabel",
                "koefisien",
                "konstanta",
                "suku",
                "persamaan",
                "fungsi",
            ],
            "Bilangan": [
                "bilangan",
                "rasio",
                "proporsi",
                "pecahan",
                "desimal",
                "persen",
                "aritmatika",
            ],
            "Pengukuran": [
                "pengukuran",
                "keliling",
                "luas",
                "volume",
                "juring",
                "busur",
            ],
            "Geometri": [
                "geometri",
                "bangun",
                "sudut",
                "segitiga",
                "pythagoras",
                "kesebangunan",
            ],
            "Analisis Data dan Peluang": [
                "data",
                "peluang",
                "statistika",
                "diagram",
                "rata-rata",
            ],
        }
        for element, keywords in element_keywords.items():
            if any(keyword in text for keyword in keywords):
                return element
        return None

    def _extract_element_cp(
        self,
        reference_text: str,
        element: str | None,
    ) -> str | None:
        if not reference_text or not element:
            return None

        text = self._clean_cp_text(reference_text)
        markers = list(
            re.finditer(
                r"\b\d+\.\d+\.?\s*"
                r"(Bilangan|Aljabar|Pengukuran|Geometri|"
                r"Analisis Data dan Peluang|Analisis Data|Peluang)\b",
                text,
                flags=re.IGNORECASE,
            )
        )
        if not markers:
            return None

        wanted_key = self._normalize_element_name(element)
        for index, marker in enumerate(markers):
            marker_key = self._normalize_element_name(marker.group(1))
            if marker_key != wanted_key:
                continue

            start = marker.end()
            end = markers[index + 1].start() if index + 1 < len(markers) else len(text)
            section = text[start:end].strip(" .")
            if not section:
                return None
            return self._sentence_case(section)

        return None

    def _normalize_element_name(self, value: str) -> str:
        normalized = " ".join(str(value).casefold().split())
        if normalized in {"analisis data", "peluang"}:
            return "analisis data dan peluang"
        return normalized

    def _clean_cp_text(self, value: str) -> str:
        text = str(value or "")
        if "Capaian Pembelajaran:" in text:
            text = text.split("Capaian Pembelajaran:", 1)[-1]
        text = re.sub(r"\s+", " ", text).strip()
        text = re.sub(
            r"^(?:\d+\.\s*)?Fase\s+(?:Fondasi|[A-F])\s*(?:\([^)]*\))?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(
            r"^Pada akhir [Ff]ase (?:Fondasi|[A-F]),?\s*"
            r"(?:murid|peserta didik) memiliki kemampuan sebagai berikut\.?\s*",
            "",
            text,
            flags=re.IGNORECASE,
        )
        return text.strip(" .")

    def _sentence_case(self, value: str) -> str:
        value = value.strip(" .")
        if not value:
            return value
        return f"{value[0].upper()}{value[1:]}."

    def _fallback_recommendations(
        self,
        payload: RecommendStageRequest,
        recommendation_type: str,
        references: list[Any],
        capaian_pembelajaran: str,
    ) -> dict[str, Any]:
        topic = (
            payload.targetStage.get("topic")
            or payload.project.title
            or "topik pembelajaran"
        )
        objectives = self._build_learning_objectives(capaian_pembelajaran, str(topic))
        return {
            "capaianPembelajaran": capaian_pembelajaran,
            "tujuanPembelajaran": objectives,
        }

    def _build_learning_objectives(
        self,
        capaian_pembelajaran: str,
        topic: str,
    ) -> list[str]:
        cp_lower = capaian_pembelajaran.casefold()
        topic_lower = topic.casefold()
        if any(
            keyword in f"{cp_lower} {topic_lower}"
            for keyword in ("aljabar", "polinomial", "variabel", "koefisien", "konstanta")
        ):
            objectives = [
                "Murid mampu mengenali dan menjelaskan pola dalam susunan benda "
                "atau bilangan sebagai dasar bentuk aljabar.",
                "Murid mampu menyatakan situasi kontekstual ke dalam bentuk "
                "aljabar sederhana yang memuat variabel, koefisien, konstanta, "
                "atau suku sejenis.",
                "Murid mampu menggunakan sifat operasi untuk menyederhanakan "
                "atau menghasilkan bentuk aljabar yang ekuivalen.",
            ]
            return objectives

        fragments = self._cp_fragments(capaian_pembelajaran)
        objectives = []
        for fragment in fragments[:4]:
            objective = self._objective_from_fragment(fragment)
            if not objective:
                continue
            objectives.append(objective)

        if not objectives:
            objectives = [
                f"Murid mampu menjelaskan konsep utama pada {topic}.",
                f"Murid mampu menerapkan pemahaman tentang {topic} dalam konteks sederhana.",
                f"Murid mampu mengomunikasikan hasil belajar tentang {topic} secara runtut.",
            ]

        return objectives

    def _cp_fragments(self, value: str) -> list[str]:
        text = re.sub(r"\s+", " ", value).strip()
        fragments = [
            fragment.strip(" .")
            for fragment in re.split(r";|\.\s+", text)
            if fragment.strip(" .")
        ]
        return [
            fragment
            for fragment in fragments
            if len(fragment.split()) >= 4 and not fragment.casefold().startswith("fase ")
        ]

    def _objective_from_fragment(self, fragment: str) -> str:
        cleaned = fragment.strip(" .")
        cleaned = re.sub(r"^(?:murid|peserta didik)\s+", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"^(?:dapat|mampu)\s+", "", cleaned, flags=re.IGNORECASE)
        if not cleaned:
            return ""
        return f"Murid mampu {cleaned[0].lower()}{cleaned[1:]}."

    def _normalize_recommendations(
        self,
        generated: dict[str, Any],
        fallback: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(generated, dict):
            generated = {}

        result = dict(generated)
        cp_text = fallback["capaianPembelajaran"]

        objectives = self._normalize_objectives(
            result.get("tujuanPembelajaran") or result.get("alurTujuanPembelajaran"),
            fallback["tujuanPembelajaran"],
        )

        return {
            "capaianPembelajaran": cp_text,
            "tujuanPembelajaran": objectives,
        }

    def _normalize_objectives(
        self,
        value: Any,
        fallback: list[str],
    ) -> list[str]:
        if not isinstance(value, list):
            return fallback

        objectives = []
        for item in value:
            if isinstance(item, str):
                objective_text = item
            elif isinstance(item, dict):
                objective_text = (
                    item.get("tujuanPembelajaran")
                    or item.get("objective")
                    or item.get("text")
                )
            else:
                continue

            objective_text = str(objective_text or "").strip()
            if not objective_text:
                continue
            if objective_text.startswith("Peserta didik mampu"):
                objective_text = objective_text.replace(
                    "Peserta didik mampu",
                    "Murid mampu",
                    1,
                )
            elif objective_text.startswith("Siswa mampu"):
                objective_text = objective_text.replace("Siswa mampu", "Murid mampu", 1)
            elif not objective_text.startswith("Murid mampu"):
                objective_text = (
                    f"Murid mampu {objective_text[0].lower()}{objective_text[1:]}"
                )

            objectives.append(objective_text)

        return objectives or fallback
