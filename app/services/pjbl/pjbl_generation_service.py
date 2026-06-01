from __future__ import annotations

import json
from typing import Any

from app.schemas.common_schema import UsedReferenceSchema
from app.schemas.generate_rpp_schema import GenerateRppRequest, GenerateRppResponse
from app.services.llm_client import LLMClient
from app.services.prompt_builder_service import PromptBuilderService
from app.services.rag_service import RAGService


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
            query=payload.project.title or payload.project.subject or "RPP",
            subject=payload.project.subject,
            phase=payload.project.phase,
            top_k=5,
        )
        fallback_content = self._fallback_content(payload)
        messages = [
            {
                "role": "system",
                "content": (
                    "Anda adalah AI Service Petunjukku. Buat teks final RPP sebagai "
                    "contentJson dan contentMarkdown. Jangan membuat file PDF/DOCX."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "project": payload.project.model_dump(),
                        "teacherProfile": self._dump(payload.teacherProfile),
                        "school": self._dump(payload.school),
                        "teacherSubject": self._dump(payload.teacherSubject),
                        "teacherClass": self._dump(payload.teacherClass),
                        "stages": [stage.model_dump() for stage in payload.stages],
                        "kinaChatSummary": payload.kinaChatSummary,
                        "options": payload.options,
                        "ragReferences": [
                            reference.model_dump() for reference in references
                        ],
                        "requiredResponseShape": {
                            "contentJson": fallback_content,
                            "contentMarkdown": self._to_markdown(fallback_content),
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ]
        generated = await self.llm_client.generate_json(
            messages,
            {
                "contentJson": fallback_content,
                "contentMarkdown": self._to_markdown(fallback_content),
            },
            temperature=0.35,
        )
        content_json = generated.get("contentJson") or fallback_content
        content_markdown = generated.get("contentMarkdown") or self._to_markdown(
            content_json
        )
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
            contentMarkdown=str(content_markdown),
        )

    def _fallback_content(self, payload: GenerateRppRequest) -> dict[str, Any]:
        stages_by_number = {stage.stageNumber: stage.contentJson for stage in payload.stages}
        title = payload.project.title or "RPP Pembelajaran"
        return {
            "title": title,
            "identity": {
                "subject": payload.project.subject,
                "phase": payload.project.phase,
                "gradeLevel": payload.project.gradeLevel,
                "rppType": payload.project.rppType,
            },
            "learningObjectives": self._extract_objectives(stages_by_number),
            "learningActivities": stages_by_number.get(3, {}),
            "assessment": stages_by_number.get(4, {}),
            "rubric": stages_by_number.get(4, {}).get("rubric", {}),
            "reflection": {
                "student": "Siswa menuliskan hal yang sudah dipahami dan hal yang masih membingungkan.",
                "teacher": "Guru meninjau ketercapaian tujuan dan menyesuaikan tindak lanjut.",
            },
        }

    def _extract_objectives(self, stages_by_number: dict[int, dict[str, Any]]) -> list[str]:
        stage_two = stages_by_number.get(2, {})
        for key in (
            "learningObjectives",
            "tujuanPembelajaran",
            "tujuan_pembelajaran",
        ):
            value = stage_two.get(key)
            if isinstance(value, list):
                return [str(item) for item in value]
            if isinstance(value, str) and value.strip():
                return [value]
        return ["Peserta didik mencapai tujuan pembelajaran sesuai CP dan konteks kelas."]

    def _to_markdown(self, content: dict[str, Any]) -> str:
        title = content.get("title") or "RPP Pembelajaran"
        lines = [f"# {title}", "", "## Identitas"]
        for key, value in (content.get("identity") or {}).items():
            lines.append(f"- {key}: {value}")
        lines.extend(["", "## Tujuan Pembelajaran"])
        for objective in content.get("learningObjectives") or []:
            lines.append(f"- {objective}")
        lines.extend(["", "## Kegiatan Pembelajaran"])
        lines.append(json.dumps(content.get("learningActivities") or {}, ensure_ascii=False))
        lines.extend(["", "## Asesmen"])
        lines.append(json.dumps(content.get("assessment") or {}, ensure_ascii=False))
        return "\n".join(lines)

    def _dump(self, value: Any) -> dict[str, Any]:
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if isinstance(value, dict):
            return value
        return {}
