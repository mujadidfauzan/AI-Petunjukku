from __future__ import annotations

import json
from typing import Any

from fastapi import HTTPException, status

from app.schemas.stage3_diagram_schema import (
    FlowDiagramSchema,
    FlowLaneSchema,
    FlowStepSchema,
    Stage3DiagramRequest,
    Stage3DiagramResponse,
    Stage3GeneratedDesignSchema,
)
from app.services.llm_client import LLMClient


class IntraStage3DiagramService:
    def __init__(self, llm_client: LLMClient | None = None) -> None:
        self.llm_client = llm_client or LLMClient()

    async def generate(self, payload: Stage3DiagramRequest) -> Stage3DiagramResponse:
        messages = [
            {
                "role": "system",
                "content": self._system_prompt(),
            },
            {
                "role": "user",
                "content": self._user_prompt(payload),
            },
        ]

        try:
            raw = await self.llm_client.generate_json_strict(
                messages,
                temperature=0.35,
                max_tokens=3200,
            )
            generated = self._parse_generated_design(raw)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=f"AI belum berhasil membuat diagram Stage 3: {exc}",
            ) from exc

        return Stage3DiagramResponse(
            generatedDesign=generated,
            model=self.llm_client.model_name,
            source="ai_service",
        )

    def _system_prompt(self) -> str:
        return """
Anda adalah KINA, AI Teaching Companion Petunjukku.
Tugas Anda adalah membuat 3 alternatif diagram alur pembelajaran Stage 3 RPP Intrakurikuler.

ATURAN WAJIB:
- Balas hanya JSON valid.
- Jangan menulis markdown.
- Diagram harus praktis untuk guru Indonesia.
- Diagram harus mengikuti Stage 1, Stage 2, dan input Stage 3.
- Buat tepat 3 diagram dengan key "a", "b", dan "c".
- Setiap diagram memiliki 3 lane: pembukaan/perencanaan, inti/pelaksanaan, penutup/refleksi.
- Setiap lane berisi 3-5 step.
- Step type hanya: "start", "process", "decision", "end".
- Jika type "decision", wajib isi "yes" dan "no".
- Label step pendek agar muat di UI, maksimal 8 kata.
- Jangan menambahkan fasilitas/platform/kemitraan yang tidak dipilih guru.
- Produk akhir harus konsisten dengan input Stage 3.

FORMAT JSON:
{
  "summary": "ringkasan pendek",
  "praktikPedagogis": "nama praktik pedagogis",
  "alasanPraktikPedagogis": "alasan singkat",
  "kemitraanDetail": "detail kemitraan atau tidak digunakan",
  "pemanfaatanDigital": "cara pemanfaatan digital",
  "fungsiTeknologiDigital": "fungsi teknologi",
  "produkKinerjaAkhirNarasi": "narasi produk akhir",
  "langkahPenting": ["butir 1", "butir 2", "butir 3"],
  "diagrams": {
    "a": {"title": "Diagram A - ...", "lanes": []},
    "b": {"title": "Diagram B - ...", "lanes": []},
    "c": {"title": "Diagram C - ...", "lanes": []}
  }
}
""".strip()

    def _user_prompt(self, payload: Stage3DiagramRequest) -> str:
        return "\n\n".join(
            [
                "Project:",
                json.dumps(payload.project.model_dump(), ensure_ascii=False, indent=2),
                "Stage 1-2 tersimpan:",
                json.dumps(
                    [stage.model_dump() for stage in payload.stages],
                    ensure_ascii=False,
                    indent=2,
                ),
                "Input Stage 3 yang sudah dikunci:",
                json.dumps(payload.stage3Inputs, ensure_ascii=False, indent=2),
                "Ringkasan chat KINA terakhir:",
                json.dumps(
                    [chat.model_dump() for chat in payload.chatHistory[-12:]],
                    ensure_ascii=False,
                    indent=2,
                ),
                "Buat tiga variasi diagram: A sebagai alur utama, B sebagai alur pendampingan bertahap, C sebagai alur berbasis produk/refleksi.",
            ]
        )

    def _parse_generated_design(
        self, raw: dict[str, Any]
    ) -> Stage3GeneratedDesignSchema:
        diagrams_raw = raw.get("diagrams")
        if not isinstance(diagrams_raw, dict):
            raise ValueError("Field diagrams tidak ditemukan.")

        diagrams: dict[str, FlowDiagramSchema] = {}
        for diagram_id in ("a", "b", "c"):
            diagram = self._parse_diagram(diagrams_raw.get(diagram_id), diagram_id)
            diagrams[diagram_id] = diagram

        return Stage3GeneratedDesignSchema(
            summary=self._text(raw.get("summary"), "Diagram Stage 3 siap dipilih."),
            praktikPedagogis=self._text(raw.get("praktikPedagogis")),
            alasanPraktikPedagogis=self._text(raw.get("alasanPraktikPedagogis")),
            kemitraanDetail=self._text(raw.get("kemitraanDetail")),
            pemanfaatanDigital=self._text(raw.get("pemanfaatanDigital")),
            fungsiTeknologiDigital=self._text(raw.get("fungsiTeknologiDigital")),
            produkKinerjaAkhirNarasi=self._text(raw.get("produkKinerjaAkhirNarasi")),
            langkahPenting=self._text_list(raw.get("langkahPenting")),
            diagrams=diagrams,
            source="ai",
        )

    def _parse_diagram(self, raw: Any, diagram_id: str) -> FlowDiagramSchema:
        if not isinstance(raw, dict):
            raise ValueError(f"Diagram {diagram_id} tidak valid.")

        lanes_raw = raw.get("lanes")
        if not isinstance(lanes_raw, list) or not lanes_raw:
            raise ValueError(f"Diagram {diagram_id} tidak memiliki lanes.")

        lanes = [
            self._parse_lane(lane, lane_index)
            for lane_index, lane in enumerate(lanes_raw[:4])
        ]
        if not lanes:
            raise ValueError(f"Diagram {diagram_id} tidak memiliki lane valid.")

        return FlowDiagramSchema(
            title=self._text(raw.get("title"), f"Diagram {diagram_id.upper()}"),
            lanes=lanes,
        )

    def _parse_lane(self, raw: Any, lane_index: int) -> FlowLaneSchema:
        if not isinstance(raw, dict):
            raise ValueError("Lane diagram tidak valid.")

        steps_raw = raw.get("steps")
        if not isinstance(steps_raw, list) or not steps_raw:
            raise ValueError("Lane diagram tidak memiliki steps.")

        steps = [
            self._parse_step(step, step_index)
            for step_index, step in enumerate(steps_raw[:5])
        ]
        if not steps:
            raise ValueError("Lane diagram tidak memiliki step valid.")

        return FlowLaneSchema(
            id=self._text(raw.get("id"), f"lane-{lane_index + 1}"),
            title=self._text(raw.get("title"), f"Tahap {lane_index + 1}"),
            steps=steps,
        )

    def _parse_step(self, raw: Any, step_index: int) -> FlowStepSchema:
        if not isinstance(raw, dict):
            raise ValueError("Step diagram tidak valid.")

        step_type = raw.get("type")
        if step_type not in {"start", "process", "decision", "end"}:
            step_type = "process"

        return FlowStepSchema(
            id=self._text(raw.get("id"), str(step_index + 1)),
            type=step_type,
            label=self._text(raw.get("label"), "Aktivitas"),
            yes=self._text(raw.get("yes"), "Lanjut") if step_type == "decision" else None,
            no=self._text(raw.get("no"), "Perbaiki") if step_type == "decision" else None,
        )

    def _text(self, value: Any, fallback: str = "") -> str:
        if isinstance(value, str) and value.strip():
            return value.strip()
        return fallback

    def _text_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [item.strip() for item in value if isinstance(item, str) and item.strip()]
