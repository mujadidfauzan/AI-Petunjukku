from fastapi import APIRouter, HTTPException

from app.schemas import ApiResponse, GenerateDocumentRequest, KinaChatRequest, Stage4SaveRequest
from app.services.ai_generation_service import ai_generation_service
from app.services.service_kina import kina_service
from app.services.stage4_service import stage4_service

router = APIRouter()


@router.get("/health")
async def health_check():
    return {"success": True, "message": "Kina MVP Backend is running"}


@router.post("/kina/chat", response_model=ApiResponse)
async def chat_with_kina(payload: KinaChatRequest):
    data = await kina_service.chat(
        project_id=payload.project_id,
        message_text=payload.message_text,
        current_stage=payload.current_stage,
        use_ai_generation=payload.use_ai_generation,
        generate_if_requested=payload.generate_if_requested,
    )
    return ApiResponse(success=True, message="Kina berhasil memproses percakapan.", data=data)


@router.get("/kina/chat/{project_id}", response_model=ApiResponse)
async def get_chat_history(project_id: str):
    data = {"project_id": project_id, "chats": kina_service.get_chat_history(project_id)}
    return ApiResponse(success=True, message="Riwayat chat berhasil diambil.", data=data)


@router.post("/kina/chat/{project_id}/summary", response_model=ApiResponse)
async def summarize_chat(project_id: str):
    data = await kina_service.summarize(project_id)
    return ApiResponse(success=True, message="Ringkasan chat berhasil dibuat.", data=data)


@router.get("/planning-state/{project_id}", response_model=ApiResponse)
async def get_planning_state(project_id: str):
    data = kina_service.get_planning_state(project_id)
    return ApiResponse(success=True, message="Planning state berhasil diambil.", data=data)


@router.get("/stage-4/options", response_model=ApiResponse)
async def get_stage_4_options():
    return ApiResponse(success=True, message="Opsi Stage 4 berhasil diambil.", data=stage4_service.get_options())


@router.post("/stage-4/save", response_model=ApiResponse)
async def save_stage_4(payload: Stage4SaveRequest):
    data = stage4_service.save_assessment(
        project_id=payload.project_id,
        jenis_asesmen=payload.jenis_asesmen,
        teknik_penilaian=payload.teknik_penilaian,
        alat_bahan=payload.alat_bahan,
        media_pembelajaran=payload.media_pembelajaran,
        refleksi_siswa=payload.refleksi_siswa,
        refleksi_guru=payload.refleksi_guru,
    )
    return ApiResponse(success=True, message="Stage 4 berhasil disimpan.", data=data)


@router.post("/ai/generate-document", response_model=ApiResponse)
async def generate_document(payload: GenerateDocumentRequest):
    try:
        data = ai_generation_service.generate_document(
            project_id=payload.project_id,
            output_type=payload.output_type,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return ApiResponse(success=True, message="Dokumen berhasil digenerate.", data=data)
