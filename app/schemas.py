from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class KinaChatRequest(BaseModel):
    project_id: str = Field(default="demo-project-001")
    message_text: str
    current_stage: Optional[int] = Field(default=3, description="MVP diarahkan ke Stage 3")
    use_ai_generation: bool = True
    generate_if_requested: bool = False


class Stage4SaveRequest(BaseModel):
    project_id: str = Field(default="demo-project-001")
    jenis_asesmen: str = "Formatif"
    teknik_penilaian: List[str] = Field(default_factory=lambda: ["Observasi diskusi", "Penilaian LKPD"])
    alat_bahan: List[str] = Field(default_factory=lambda: ["LKPD", "Papan tulis", "Kartu soal"])
    media_pembelajaran: List[str] = Field(default_factory=lambda: ["Tabel perbandingan", "Contoh kasus harga barang"])
    refleksi_siswa: str = "Apa bagian yang paling membantu saya memahami konsep hari ini?"
    refleksi_guru: str = "Apakah siswa mampu menerapkan konsep pada masalah kontekstual?"


class GenerateDocumentRequest(BaseModel):
    project_id: str = Field(default="demo-project-001")
    output_type: str = Field(default="lkpd", description="lkpd atau modul_ajar")


class ApiResponse(BaseModel):
    success: bool
    message: str
    data: Dict[str, Any]
