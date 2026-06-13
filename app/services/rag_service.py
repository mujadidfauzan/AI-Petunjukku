from __future__ import annotations

import hashlib
import logging
import uuid
from pathlib import Path
from typing import Any

from app.core.config import Settings, settings
from app.schemas.rag_schema import (
    ModelInfo,
    RagIndexDocumentsRequest,
    RagIndexDocumentsResponse,
    RagReference,
    RagReferenceItem,
    RagSearchRequest,
    RagSearchResponse,
    SourceChunk,
)
from app.services.cp_pdf_extractor import (
    cp_record_to_chunk_content,
    extract_cp_records_from_pdf_bytes,
)
from app.services.embedding_service import EmbeddingService
from app.services.llm_client import LLMClient
from app.services.local_vector_store import LocalVectorStore
from app.services.text_chunker import TextChunk
from app.utils.file_utils import read_document_text
from app.utils.text_cleaner import split_text_into_chunks
from app.utils.vector_utils import preview_text


NO_CONTEXT_ANSWER = "Informasi tidak ditemukan dalam dokumen yang tersedia."
logger = logging.getLogger(__name__)


class RAGService:
    def __init__(
        self,
        config: Settings = settings,
        embedding_service: EmbeddingService | None = None,
        vector_store: LocalVectorStore | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.settings = config
        self.embedding_service = embedding_service or EmbeddingService(config)
        self.vector_store = vector_store or LocalVectorStore(config)
        self.llm_client = llm_client or LLMClient(config)

    async def search(self, payload: RagSearchRequest) -> RagSearchResponse:
        await self._ensure_cp_pdf_indexed()

        query = self._build_search_query(payload)
        embedding = await self.embedding_service.embed_text(query)
        metadata_filters: dict[str, str] = {}
        if payload.subject:
            metadata_filters["subject_normalized"] = self._normalize_subject_key(payload.subject)
        if payload.phase:
            metadata_filters["phase"] = self._normalize_phase(payload.phase)
        if payload.documentType == "capaian_pembelajaran":
            metadata_filters["content_type"] = "cp_record"

        matches = self.vector_store.match_document_chunks(
            query_embedding=embedding,
            match_count=payload.topK,
            similarity_threshold=0.2,
            metadata_filters=metadata_filters,
        )

        sources = [self._to_source(match) for match in matches]
        best_source = sources[0] if sources else None
        selected_record_id = None
        if best_source:
            raw_record_id = best_source.metadata.get("cp_record_id")
            selected_record_id = str(raw_record_id) if raw_record_id else best_source.chunk_id

        if not matches:
            cp_text = NO_CONTEXT_ANSWER
        else:
            retrieved_context = self._format_retrieved_context(matches)
            cp_text = await self._generate_cp_text(
                query=query,
                retrieved_context=retrieved_context,
            )

        return RagSearchResponse(
            cpText=cp_text,
            selectedRecordId=selected_record_id,
            confidence=best_source.similarity if best_source else 0,
            query=query,
            sources=sources,
            models=ModelInfo(
                embedding=self.settings.embedding_model_name,
                llm=self.settings.llm_model,
            ),
        )

    async def search_for_context(
        self,
        *,
        query: str,
        subject: str | None = None,
        phase: str | None = None,
        top_k: int = 5,
    ) -> list[RagReference]:
        response = await self.search(
            RagSearchRequest(
                query=query,
                subject=subject,
                phase=phase,
                topK=top_k,
                documentType="capaian_pembelajaran",
            )
        )
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
            for source in response.sources
        ]

    async def index_documents(
        self,
        payload: RagIndexDocumentsRequest,
    ) -> RagIndexDocumentsResponse:
        path = Path(payload.documentPath).expanduser().resolve()
        records = await self._index_path(path)
        return RagIndexDocumentsResponse(
            message="Dokumen berhasil di-index.",
            sourceTitle=payload.sourceTitle,
            chunksCreated=records,
            faissIndexPath=self.settings.local_vector_index_path,
        )

    def list_references(
        self,
        *,
        subject: str | None,
        phase: str | None,
        document_type: str | None,
    ) -> list[RagReferenceItem]:
        records = self.vector_store.list_references(
            subject=subject,
            phase=phase,
            document_type=document_type,
        )
        return [
            RagReferenceItem(
                id=str(item.get("cpReferenceId")),
                sourceTitle=str(item.get("sourceTitle") or ""),
                subject=item.get("subject"),
                phase=item.get("phase"),
                element=item.get("element"),
            )
            for item in records
        ]

    def status(self) -> str:
        return self.vector_store.backend_name()

    async def _ensure_cp_pdf_indexed(self) -> None:
        pdf_path = Path(self.settings.cp_pdf_path).expanduser().resolve()
        if not pdf_path.exists() or not pdf_path.is_file():
            logger.warning("CP PDF tidak ditemukan untuk auto-index: %s", pdf_path)
            return
        await self._index_path(pdf_path)

    async def _index_path(self, path: Path) -> int:
        content = path.read_bytes()
        if not content:
            raise ValueError(f"File kosong: {path}")

        file_hash = hashlib.sha256(content).hexdigest()
        existing_document = self.vector_store.find_indexed_document(
            file_hash=file_hash,
            file_name=path.name,
        )
        if existing_document:
            return self.vector_store.count_chunks_for_document(existing_document["id"])

        chunks = self._extract_chunks(file_name=path.name, path=path, content=content)
        if not chunks:
            raise ValueError("Tidak ada CP yang dapat diekstrak dari dokumen.")

        document = self.vector_store.create_document(
            title=path.stem,
            file_name=path.name,
            file_path=str(path),
            mime_type="application/pdf" if path.suffix.lower() == ".pdf" else None,
            file_hash=file_hash,
        )

        batch_size = 16
        for start in range(0, len(chunks), batch_size):
            batch_chunks = chunks[start : start + batch_size]
            embeddings = await self.embedding_service.embed_texts(
                [chunk.content for chunk in batch_chunks]
            )
            self.vector_store.save_document_chunks_batch(
                document_id=document["id"],
                chunks=batch_chunks,
                embeddings=embeddings,
            )
        return len(chunks)

    def _extract_chunks(self, *, file_name: str, path: Path, content: bytes) -> list[TextChunk]:
        if path.suffix.lower() == ".pdf":
            records = extract_cp_records_from_pdf_bytes(file_name, content)
            if records:
                chunks = []
                for index, record in enumerate(records):
                    content_text = cp_record_to_chunk_content(record)
                    if not content_text.strip():
                        continue
                    source = record.get("source") or {}
                    chunks.append(
                        TextChunk(
                            chunk_index=index,
                            content=content_text,
                            metadata={
                                "source": file_name,
                                "file_name": file_name,
                                "mime_type": "application/pdf",
                                "content_type": "cp_record",
                                "cp_record_id": record.get("id"),
                                "subject": record.get("subject"),
                                "subject_normalized": record.get("subject_normalized"),
                                "phase": record.get("phase"),
                                "phase_class_description": record.get("phase_class_description"),
                                "domain": record.get("domain"),
                                "lampiran": record.get("lampiran"),
                                "jenjang": record.get("jenjang"),
                                "page": source.get("page_start"),
                                "page_start": source.get("page_start"),
                                "page_end": source.get("page_end"),
                            },
                            token_count=max(1, len(content_text) // 4),
                        )
                    )
                return chunks

        text, file_metadata = read_document_text(path)
        raw_chunks = split_text_into_chunks(text)
        return [
            TextChunk(
                chunk_index=index,
                content=chunk,
                metadata={
                    **file_metadata,
                    "source": path.name,
                    "file_name": path.name,
                    "content_type": "document_chunk",
                },
                token_count=max(1, len(chunk) // 4),
            )
            for index, chunk in enumerate(raw_chunks)
        ]

    async def _generate_cp_text(
        self,
        *,
        query: str,
        retrieved_context: str,
    ) -> str:
        if not retrieved_context.strip():
            return NO_CONTEXT_ANSWER

        messages = [
            {
                "role": "system",
                "content": (
                    "Kamu adalah asisten kurikulum yang mengekstrak Capaian "
                    "Pembelajaran dari konteks dokumen. Gunakan hanya konteks "
                    "yang diberikan. Jangan menambah kebijakan, tujuan "
                    "pembelajaran, atau interpretasi di luar dokumen."
                ),
            },
            {
                "role": "user",
                "content": f"""
Ambil teks Capaian Pembelajaran yang paling relevan untuk Stage 2 RPP intrakurikuler.

Konteks hasil retrieval:
{retrieved_context}

Kebutuhan:
{query}

Aturan output:
1. Tulis hanya teks Capaian Pembelajaran yang relevan.
2. Jika ada beberapa elemen CP dalam konteks, gabungkan secara ringkas tetapi tetap setia pada dokumen.
3. Jangan membuat CP baru.
4. Jangan menulis daftar sumber di dalam jawaban; sumber dikirim lewat field sources.
5. Jika konteks tidak cukup, jawab persis: {NO_CONTEXT_ANSWER}
""".strip(),
            },
        ]
        return await self.llm_client.generate_text(
            messages,
            NO_CONTEXT_ANSWER,
            temperature=0.2,
            max_tokens=900,
        )

    def _format_retrieved_context(self, matches: list[dict[str, Any]]) -> str:
        blocks = []
        for index, match in enumerate(matches, 1):
            metadata = match.get("metadata") or {}
            blocks.append(
                "\n".join(
                    [
                        f"[Sumber {index}]",
                        f"chunk_id: {match.get('chunk_id')}",
                        f"file_name: {metadata.get('file_name') or metadata.get('source')}",
                        f"mata_pelajaran: {metadata.get('subject')}",
                        f"fase: {metadata.get('phase')}",
                        f"jenjang: {metadata.get('jenjang')}",
                        f"page: {metadata.get('page')}",
                        f"similarity: {match.get('similarity')}",
                        "content:",
                        match.get("content") or "",
                    ]
                )
            )
        return "\n\n".join(blocks)

    def _build_search_query(self, payload: RagSearchRequest) -> str:
        parts = ["Ambil Capaian Pembelajaran resmi yang paling relevan"]
        if payload.subject:
            parts.append(f"mata pelajaran {payload.subject}")
        if payload.phase:
            parts.append(f"fase {self._normalize_phase(payload.phase)}")
        if payload.query:
            parts.append(f"materi pokok atau konteks topik {payload.query}")
        return ". ".join(parts) + "."

    def _normalize_subject_key(self, value: str) -> str:
        return "_".join(
            "".join(char.lower() if char.isalnum() else " " for char in value).split()
        )

    def _normalize_phase(self, value: str) -> str:
        cleaned = value.strip()
        lowered = cleaned.casefold()
        if "fondasi" in lowered:
            return "Fondasi"
        if lowered.startswith("fase "):
            cleaned = cleaned[5:].strip()
        return cleaned.upper()

    def _to_source(self, match: dict[str, Any]) -> SourceChunk:
        content = match.get("content") or ""
        return SourceChunk(
            document_id=str(match.get("document_id") or self._document_id(match)),
            chunk_id=str(match.get("chunk_id") or self._chunk_id(match)),
            similarity=float(match.get("similarity") or 0),
            metadata=match.get("metadata") or {},
            preview=preview_text(content, 260),
        )

    def _document_id(self, item: dict[str, Any]) -> str:
        metadata = item.get("metadata") or {}
        raw = "|".join(
            [
                str(metadata.get("file_hash") or ""),
                str(metadata.get("file_name") or ""),
                str(metadata.get("content_type") or ""),
            ]
        )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))

    def _chunk_id(self, item: dict[str, Any]) -> str:
        metadata = item.get("metadata") or {}
        raw = "|".join(
            [
                str(metadata.get("cp_record_id") or ""),
                str(item.get("chunk_index") or ""),
                str(item.get("content") or "")[:120],
            ]
        )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))
