from __future__ import annotations

import hashlib
import re
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
from app.services.faiss_service import FaissService
from app.services.llm_client import LLMClient
from app.utils.file_utils import read_document_text
from app.utils.text_cleaner import compact_text, split_text_into_chunks


NO_CONTEXT_ANSWER = "Informasi tidak ditemukan dalam dokumen yang tersedia."


class RAGService:
    def __init__(
        self,
        config: Settings = settings,
        embedding_service: EmbeddingService | None = None,
        vector_store: FaissService | None = None,
        llm_client: LLMClient | None = None,
    ) -> None:
        self.settings = config
        self.embedding_service = embedding_service or EmbeddingService(config)
        self.vector_store = vector_store or FaissService(config)
        self.llm_client = llm_client or LLMClient(config)

    async def search(self, payload: RagSearchRequest) -> RagSearchResponse:
        query = self._build_search_query(payload)
        embedding = await self.embedding_service.embed_text(query)
        matches = self.vector_store.search(
            embedding,
            top_k=payload.topK,
            filters={
                "subject": payload.subject,
                "phase": payload.phase,
                "documentType": payload.documentType,
            },
        )
        sources = [self._to_source(match) for match in matches]
        best_match = matches[0] if matches else None
        best_source = sources[0] if sources else None
        cp_text = await self._generate_cp_text(
            query=query,
            matches=matches,
            fallback=self._fallback_cp_text(payload.query, best_match),
        )
        return RagSearchResponse(
            cpText=cp_text,
            selectedRecordId=str(best_source.metadata.get("cp_record_id"))
            if best_source and best_source.metadata.get("cp_record_id")
            else None,
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
                sourceTitle=str(source.metadata.get("source") or source.metadata.get("file_name") or ""),
                documentType=str(source.metadata.get("content_type") or "capaian_pembelajaran"),
                phase=str(source.metadata.get("phase")) if source.metadata.get("phase") else None,
                subject=str(source.metadata.get("subject")) if source.metadata.get("subject") else None,
                element=None,
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
        file_hash = hashlib.sha256(path.read_bytes()).hexdigest()
        if self._should_extract_cp_records(payload, path):
            records = await self._index_cp_pdf_records(
                payload=payload,
                path=path,
                file_hash=file_hash,
            )
        else:
            records = await self._index_generic_document(
                payload=payload,
                path=path,
                file_hash=file_hash,
            )

        self.vector_store.replace_records(
            records,
            file_hash=file_hash,
            source_title=payload.sourceTitle,
            document_type=payload.documentType,
        )
        return RagIndexDocumentsResponse(
            message="Dokumen berhasil di-index.",
            sourceTitle=payload.sourceTitle,
            chunksCreated=len(records),
            faissIndexPath=self.settings.faiss_index_path,
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

    async def _generate_cp_text(
        self,
        *,
        query: str,
        matches: list[dict[str, Any]],
        fallback: str,
    ) -> str:
        if not matches:
            return NO_CONTEXT_ANSWER

        context = self._format_retrieved_context(matches)
        messages = [
            {
                "role": "system",
                "content": (
                    "Anda adalah asisten kurikulum yang mengambil Capaian "
                    "Pembelajaran resmi dari konteks dokumen. Gunakan hanya "
                    "konteks. Jangan membuat CP baru."
                ),
            },
            {
                "role": "user",
                "content": f"""
Ambil teks Capaian Pembelajaran yang paling relevan.

Kebutuhan:
{query}

Konteks dokumen:
{context}

Aturan:
1. Tulis hanya CP yang relevan, singkat, dan setia pada dokumen.
2. Jangan menulis sumber di jawaban.
3. Jangan menambah tujuan pembelajaran atau aktivitas.
4. Jika konteks tidak cukup, jawab persis: {NO_CONTEXT_ANSWER}
""".strip(),
            },
        ]
        return await self.llm_client.generate_text(
            messages,
            fallback,
            temperature=0.1,
            max_tokens=700,
        )

    def _format_retrieved_context(self, matches: list[dict[str, Any]]) -> str:
        blocks = []
        for index, match in enumerate(matches, 1):
            metadata = self._source_metadata(match)
            blocks.append(
                "\n".join(
                    [
                        f"[Sumber {index}]",
                        f"chunk_id: {self._chunk_id(match)}",
                        f"file_name: {metadata.get('file_name')}",
                        f"mata_pelajaran: {metadata.get('subject')}",
                        f"fase: {metadata.get('phase')}",
                        f"jenjang: {metadata.get('jenjang')}",
                        f"page: {metadata.get('page')}",
                        f"similarity: {match.get('similarityScore')}",
                        "content:",
                        str(match.get("chunkText") or ""),
                    ]
                )
            )
        return "\n\n".join(blocks)

    def _fallback_cp_text(self, topic: str, match: dict[str, Any] | None) -> str:
        if not match:
            return NO_CONTEXT_ANSWER

        text = str(match.get("chunkText") or "")
        cp_text = text.split("Capaian Pembelajaran:", 1)[-1]
        cp_text = re.sub(r"\s+", " ", cp_text).strip()
        cp_text = re.sub(
            r"^(?:\d+\.\s*)?Fase\s+(?:Fondasi|[A-F])\s*(?:\([^)]*\))?\s*",
            "",
            cp_text,
            flags=re.IGNORECASE,
        )
        cp_text = re.sub(
            r"^Pada akhir [Ff]ase (?:Fondasi|[A-F]),?\s*(?:murid|peserta didik) memiliki kemampuan sebagai berikut\.?\s*",
            "",
            cp_text,
        ).strip()

        topic_tokens = [
            token
            for token in re.findall(r"[A-Za-zÀ-ÿ0-9]+", topic.casefold())
            if len(token) > 3
        ]
        clauses = [
            clause.strip(" .")
            for clause in re.split(r";|\.\s+", cp_text)
            if clause.strip(" .")
        ]
        scored: list[tuple[int, int, str]] = []
        for index, clause in enumerate(clauses):
            lowered = clause.casefold()
            score = sum(1 for token in topic_tokens if token in lowered)
            if score:
                scored.append((score, -index, clause))

        if scored:
            scored.sort(reverse=True)
            return self._clean_cp_clause(scored[0][2])

        return self._sentence_case(compact_text(cp_text, 600))

    def _clean_cp_clause(self, clause: str) -> str:
        cleaned = re.sub(r"\s+", " ", clause).strip(" .")
        cleaned = re.sub(r"^\d+(?:\.\d+)*\.?\s*", "", cleaned)
        cleaned = re.sub(
            r"^(?:Pemahaman\s+(?:IPA|Fisika|Kimia|Biologi)|Keterampilan\s+Proses)\s+",
            "",
            cleaned,
            flags=re.IGNORECASE,
        )
        return f"{self._sentence_case(cleaned)}."

    def _sentence_case(self, value: str) -> str:
        value = value.strip()
        if not value:
            return value
        return value[0].upper() + value[1:]

    def _to_source(self, item: dict[str, Any]) -> SourceChunk:
        content = str(item.get("chunkText") or "")
        return SourceChunk(
            document_id=self._document_id(item),
            chunk_id=self._chunk_id(item),
            similarity=float(item.get("similarityScore") or 0),
            metadata=self._source_metadata(item),
            preview=compact_text(content, 260),
        )

    def _document_id(self, item: dict[str, Any]) -> str:
        metadata = item.get("metadata") or {}
        raw = "|".join(
            [
                str(metadata.get("fileHash") or metadata.get("file_hash") or ""),
                str(item.get("sourceTitle") or ""),
                str(item.get("documentType") or ""),
            ]
        )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))

    def _chunk_id(self, item: dict[str, Any]) -> str:
        raw = str(item.get("cpReferenceId") or "")
        if not raw:
            metadata = item.get("metadata") or {}
            raw = "|".join(
                [
                    str(metadata.get("fileHash") or metadata.get("file_hash") or ""),
                    str(metadata.get("chunkIndex") or metadata.get("chunk_index") or ""),
                ]
            )
        return str(uuid.uuid5(uuid.NAMESPACE_URL, raw))

    def _source_metadata(self, item: dict[str, Any]) -> dict[str, Any]:
        metadata = item.get("metadata") or {}
        phase_code = item.get("phaseCode") or metadata.get("phaseCode")
        phase = self._normalize_phase(str(phase_code or item.get("phase") or ""))
        file_name = metadata.get("fileName") or metadata.get("file_name") or ""
        cp_record_id = item.get("cpReferenceId") or metadata.get("cpRecordId")
        return {
            "source": file_name,
            "file_name": file_name,
            "mime_type": "application/pdf" if str(file_name).lower().endswith(".pdf") else None,
            "content_type": "cp_record"
            if item.get("documentType") == "capaian_pembelajaran"
            else "document_chunk",
            "cp_record_id": cp_record_id,
            "subject": item.get("subject"),
            "subject_normalized": metadata.get("subjectNormalized")
            or metadata.get("subject_normalized"),
            "phase": phase,
            "phase_class_description": metadata.get("phaseClassDescription")
            or metadata.get("phase_class_description"),
            "domain": metadata.get("domain"),
            "lampiran": metadata.get("lampiran"),
            "jenjang": metadata.get("jenjang"),
            "page": metadata.get("page"),
            "page_start": metadata.get("pageStart") or metadata.get("page_start"),
            "page_end": metadata.get("pageEnd") or metadata.get("page_end"),
        }

    def _should_extract_cp_records(
        self,
        payload: RagIndexDocumentsRequest,
        path: Path,
    ) -> bool:
        return (
            payload.documentType == "capaian_pembelajaran"
            and path.suffix.lower() == ".pdf"
        )

    async def _index_cp_pdf_records(
        self,
        *,
        payload: RagIndexDocumentsRequest,
        path: Path,
        file_hash: str,
    ) -> list[dict[str, Any]]:
        content = path.read_bytes()
        cp_records = extract_cp_records_from_pdf_bytes(path.name, content)
        if not cp_records:
            return await self._index_generic_document(
                payload=payload,
                path=path,
                file_hash=file_hash,
            )

        chunks = [cp_record_to_chunk_content(record) for record in cp_records]
        embeddings = await self.embedding_service.embed_texts(chunks)
        records = []
        for index, (record, chunk, embedding) in enumerate(
            zip(cp_records, chunks, embeddings, strict=True)
        ):
            source = record.get("source") or {}
            phase_code = str(record.get("phase") or "")
            records.append(
                {
                    "cpReferenceId": str(record.get("id") or ""),
                    "sourceTitle": payload.sourceTitle,
                    "documentType": payload.documentType,
                    "subject": record.get("subject"),
                    "subjectSearchKeys": self._subject_search_keys(record.get("subject")),
                    "phase": self._phase_label(phase_code),
                    "phaseCode": phase_code,
                    "element": None,
                    "chunkText": chunk,
                    "embedding": embedding,
                    "metadata": {
                        "fileName": path.name,
                        "fileHash": file_hash,
                        "chunkIndex": index,
                        "sourcePath": str(path),
                        "cpRecordId": record.get("id"),
                        "subjectNormalized": record.get("subject_normalized"),
                        "phaseClassDescription": record.get("phase_class_description"),
                        "domain": record.get("domain"),
                        "lampiran": record.get("lampiran"),
                        "jenjang": record.get("jenjang"),
                        "page": source.get("page_start"),
                        "pageStart": source.get("page_start"),
                        "pageEnd": source.get("page_end"),
                        "parseConfidence": record.get("parse_confidence"),
                    },
                }
            )
        return records

    async def _index_generic_document(
        self,
        *,
        payload: RagIndexDocumentsRequest,
        path: Path,
        file_hash: str,
    ) -> list[dict[str, Any]]:
        text, file_metadata = read_document_text(path)
        chunks = split_text_into_chunks(text)
        embeddings = await self.embedding_service.embed_texts(chunks) if chunks else []

        records = []
        for index, (chunk, embedding) in enumerate(zip(chunks, embeddings, strict=True)):
            cp_reference_id = str(
                uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    f"{file_hash}:{payload.sourceTitle}:{index}",
                )
            )
            records.append(
                {
                    "cpReferenceId": cp_reference_id,
                    "sourceTitle": payload.sourceTitle,
                    "documentType": payload.documentType,
                    "subject": payload.subject,
                    "subjectSearchKeys": self._subject_search_keys(payload.subject),
                    "phase": payload.phase,
                    "phaseCode": self._normalize_phase(payload.phase),
                    "element": None,
                    "chunkText": chunk,
                    "embedding": embedding,
                    "metadata": {
                        **file_metadata,
                        "fileHash": file_hash,
                        "chunkIndex": index,
                        "sourcePath": str(path),
                        "indexingMode": "generic_chunk",
                    },
                }
            )
        return records

    def _build_search_query(self, payload: RagSearchRequest) -> str:
        parts = ["Ambil Capaian Pembelajaran resmi yang paling relevan"]
        if payload.subject:
            parts.append(f"mata pelajaran {payload.subject}")
        if payload.phase:
            parts.append(f"fase {self._normalize_phase(payload.phase)}")
        if payload.query:
            parts.append(f"materi pokok atau konteks topik {payload.query}")
        return ". ".join(parts) + "."

    def _to_reference(self, item: dict[str, Any]) -> RagReference:
        return RagReference(
            cpReferenceId=str(item.get("cpReferenceId") or ""),
            sourceTitle=str(item.get("sourceTitle") or ""),
            documentType=str(item.get("documentType") or "capaian_pembelajaran"),
            phase=item.get("phase"),
            subject=item.get("subject"),
            element=item.get("element"),
            chunkText=compact_text(item.get("chunkText"), 1600),
            similarityScore=float(item.get("similarityScore") or 0),
            metadata=item.get("metadata") or {},
        )

    def _phase_label(self, value: str | None) -> str | None:
        if not value:
            return None
        if value.casefold() == "fondasi":
            return "Fase Fondasi"
        if value.upper() in {"A", "B", "C", "D", "E", "F"}:
            return f"Fase {value.upper()}"
        return value

    def _normalize_phase(self, value: str | None) -> str | None:
        if not value:
            return None
        cleaned = value.strip()
        lowered = cleaned.casefold()
        if "fondasi" in lowered:
            return "Fondasi"
        if lowered.startswith("fase "):
            cleaned = cleaned[5:].strip()
        return cleaned.upper()

    def _subject_search_keys(self, subject: str | None) -> list[str]:
        if not subject:
            return []
        key = "_".join("".join(char.lower() if char.isalnum() else " " for char in subject).split())
        keys = {key}
        is_special_education = key.startswith("pendidikan_khusus_")
        if not is_special_education and ("ilmu_pengetahuan_alam_dan_sosial" in key or key == "ipas"):
            keys.update({"ipa", "ipas", "ilmu_pengetahuan_alam_dan_sosial"})
        elif not is_special_education and ("ilmu_pengetahuan_alam" in key or key == "ipa"):
            keys.update({"ipa", "ilmu_pengetahuan_alam"})
        if not is_special_education and ("ilmu_pengetahuan_sosial" in key or key == "ips"):
            keys.update({"ips", "ilmu_pengetahuan_sosial"})
        if key in {"pkn", "ppkn"} or "pendidikan_pancasila" in key:
            keys.update({"pkn", "ppkn", "pendidikan_pancasila"})
        if key == "paibp" or "pendidikan_agama_islam_dan_budi_pekerti" in key:
            keys.update({"paibp", "pendidikan_agama_islam_dan_budi_pekerti"})
        return sorted(keys)
