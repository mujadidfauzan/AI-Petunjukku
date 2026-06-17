from __future__ import annotations

import json
from typing import Any

from app.schemas.common_schema import ProjectSchema, StageSchema
from app.schemas.rag_schema import RagReference
from app.utils.text_cleaner import compact_text


class PromptBuilderService:
    def project_context(self, project: ProjectSchema) -> str:
        return "\n".join(
            part
            for part in [
                f"Judul: {project.title}",
                f"Tipe RPM: {project.rppType}",
                f"Mata pelajaran: {project.subject}",
                f"Fase: {project.phase}",
                f"Kelas/Jenjang: {project.gradeLevel}",
            ]
            if part and not part.endswith("None")
        )

    def stages_context(self, stages: list[StageSchema]) -> str:
        blocks = []
        for stage in stages:
            content = compact_text(json.dumps(stage.contentJson, ensure_ascii=False), 2500)
            blocks.append(
                f"Stage {stage.stageNumber} - {stage.stageName or '-'}:\n{content}"
            )
        return "\n\n".join(blocks) if blocks else "Belum ada stage yang dikirim."

    def rag_context(self, references: list[RagReference]) -> str:
        if not references:
            return "Tidak ada referensi RAG yang ditemukan."
        return "\n\n".join(
            [
                f"[{index}] {ref.sourceTitle} | {ref.subject or '-'} | {ref.phase or '-'} | score={ref.similarityScore:.3f}\n{compact_text(ref.chunkText, 1000)}"
                for index, ref in enumerate(references, 1)
            ]
        )
