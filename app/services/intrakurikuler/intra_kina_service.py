# from __future__ import annotations

# import json

# from app.schemas.common_schema import UsedReferenceSchema
# from app.schemas.kina_schema import KinaChatRequest, KinaChatResponse
# from app.services.llm_client import LLMClient
# from app.services.prompt_builder_service import PromptBuilderService
# from app.services.rag_service import RAGService
# from app.utils.text_cleaner import compact_text


# class IntraKinaService:
#     def __init__(
#         self,
#         rag_service: RAGService | None = None,
#         llm_client: LLMClient | None = None,
#         prompt_builder: PromptBuilderService | None = None,
#     ) -> None:
#         self.rag_service = rag_service or RAGService()
#         self.llm_client = llm_client or LLMClient()
#         self.prompt_builder = prompt_builder or PromptBuilderService()

#     async def chat(self, payload: KinaChatRequest) -> KinaChatResponse:
#         references = await self.rag_service.search_for_context(
#             query=payload.message,
#             subject=payload.project.subject,
#             phase=payload.project.phase,
#             top_k=3,
#         )
#         fallback = self._fallback_reply(payload)
#         messages = [
#             {
#                 "role": "system",
#                 "content": (
#                     "Anda adalah Kina, chatbot AI Petunjukku untuk guru Indonesia. "
#                     "Jawab singkat, praktis, dan kontekstual berdasarkan project RPM, "
#                     "stage yang dikirim, chat history, dan referensi RAG. "
#                     "Jangan menyimpan data dan jangan mengaku membuat file PDF/DOCX."
#                 ),
#             },
#             {
#                 "role": "user",
#                 "content": "\n\n".join(
#                     [
#                         "Konteks project:",
#                         self.prompt_builder.project_context(payload.project),
#                         "Stage yang sudah dikirim:",
#                         self.prompt_builder.stages_context(payload.stages),
#                         "Referensi RAG:",
#                         self.prompt_builder.rag_context(references),
#                         "Riwayat chat:",
#                         json.dumps(
#                             [chat.model_dump() for chat in payload.chatHistory[-12:]],
#                             ensure_ascii=False,
#                         ),
#                         f"Pesan terbaru guru:\n{payload.message}",
#                     ]
#                 ),
#             },
#         ]
#         reply = await self.llm_client.generate_text(messages, fallback, temperature=0.55)
#         return KinaChatResponse(
#             reply=reply,
#             usedReferences=[
#                 UsedReferenceSchema(
#                     cpReferenceId=reference.cpReferenceId,
#                     sourceTitle=reference.sourceTitle,
#                     similarityScore=reference.similarityScore,
#                 )
#                 for reference in references
#             ],
#             suggestedFollowUpQuestions=self._follow_up_questions(payload),
#         )

#     def _fallback_reply(self, payload: KinaChatRequest) -> str:
#         topic = payload.project.title or payload.project.subject or "pembelajaran"
#         stage_text = "stage yang sudah diisi" if payload.stages else "data stage yang tersedia"
#         return (
#             f"Untuk {topic}, kegiatan dapat dibuat bertahap dari {stage_text}: "
#             "mulai dengan pemantik singkat, lanjutkan aktivitas utama yang melibatkan siswa, "
#             "lalu tutup dengan refleksi atau asesmen ringan. "
#             f"Pesan guru yang saya tangkap: {compact_text(payload.message, 220)}"
#         )

#     def _follow_up_questions(self, payload: KinaChatRequest) -> list[str]:
#         subject = payload.project.subject or "mapel ini"
#         return [
#             "Apakah kegiatan ini ingin dibuat dalam bentuk diskusi kelompok?",
#             f"Apakah perlu saya bantu susun asesmen singkat untuk {subject}?",
#         ]



from __future__ import annotations

import json
import re
from typing import Any

from fastapi import HTTPException, status

from app.schemas.common_schema import UsedReferenceSchema
from app.schemas.kina_schema import KinaChatRequest, KinaChatResponse
from app.services.intrakurikuler.intra_dummy_stage_data import (
    get_intra_dummy_stage_content,
)
from app.services.llm_client import LLMClient
from app.services.prompt_builder_service import PromptBuilderService
from app.services.rag_service import RAGService
from app.utils.text_cleaner import compact_text


class IntraKinaService:
    def __init__(
        self,
        rag_service: RAGService | None = None,
        llm_client: LLMClient | None = None,
        prompt_builder: PromptBuilderService | None = None,
    ) -> None:
        self.rag_service = rag_service or RAGService()
        self.llm_client = llm_client or LLMClient()
        self.prompt_builder = prompt_builder or PromptBuilderService()

    async def chat(self, payload: KinaChatRequest) -> KinaChatResponse:
        message = payload.message.strip()
        is_initial_chat = self._is_initial_chat(payload)
        rag_query = (
            message
            or payload.project.title
            or payload.project.subject
            or "strategi pembelajaran intrakurikuler stage 3"
        )
        references = await self.rag_service.search_for_context(
            query=rag_query,
            subject=payload.project.subject,
            phase=payload.project.phase,
            top_k=3,
        )

        stage_context = self._stage_context_with_dummy(payload)
        teacher_name = self._extract_teacher_name(payload, stage_context)
        fallback = (
            self._initial_fallback_reply(payload, teacher_name)
            if is_initial_chat
            else self._fallback_reply(payload, teacher_name)
        )

        messages = [
            {
                "role": "system",
                "content": self._build_stage_3_system_prompt(),
            },
            {
                "role": "user",
                "content": self._build_stage_3_user_prompt(
                    payload=payload,
                    references=references,
                    stage_context=stage_context,
                    teacher_name=teacher_name,
                    is_initial_chat=is_initial_chat,
                ),
            },
        ]

        suggested_follow_up_questions = (
            [] if payload.requireAi else self._follow_up_questions(payload)
        )
        if payload.requireAi:
            try:
                generated = await self.llm_client.generate_json_strict(
                    [
                        *messages,
                        {
                            "role": "user",
                            "content": (
                                "Untuk integrasi frontend, balas hanya dalam JSON valid dengan bentuk "
                                '{"reply":"...","suggestedFollowUpQuestions":["...","..."]}. '
                                "Field reply berisi pesan KINA untuk guru, tetap natural dan jangan menyebut JSON. "
                                "Field suggestedFollowUpQuestions wajib berisi 2-3 pilihan balasan singkat yang bisa langsung diklik guru. "
                                "Pilihan harus nyambung dengan pertanyaan terakhir KINA, bukan pertanyaan baru. "
                                "Jangan pakai nama guru, Kak, Mas, Mbak, Pak, Bu, markdown, atau tanda **."
                            ),
                        },
                    ],
                    temperature=0.62,
                )
                reply = str(generated.get("reply") or "").strip()
                suggested = generated.get("suggestedFollowUpQuestions")
                if isinstance(suggested, list):
                    suggested_follow_up_questions = [
                        self._polish_short_text(item)
                        for item in suggested
                        if isinstance(item, str) and item.strip()
                    ][:3]
                if not reply:
                    raise RuntimeError("KINA AI mengembalikan respons kosong.")
                reply = self._polish_reply(
                    reply,
                    teacher_name,
                    allow_name=is_initial_chat,
                )
            except Exception as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail=f"KINA AI belum berhasil merespons: {exc}",
                ) from exc
        else:
            reply = await self.llm_client.generate_text(
                messages,
                fallback,
                temperature=0.62,
            )

        return KinaChatResponse(
            reply=reply,
            usedReferences=[
                UsedReferenceSchema(
                    cpReferenceId=reference.cpReferenceId,
                    sourceTitle=reference.sourceTitle,
                    similarityScore=reference.similarityScore,
                )
                for reference in references
            ],
            suggestedFollowUpQuestions=suggested_follow_up_questions,
        )

    def _is_initial_chat(self, payload: KinaChatRequest) -> bool:
        return not payload.chatHistory and not payload.message.strip()

    def _stage_context_with_dummy(self, payload: KinaChatRequest) -> list[dict[str, Any]]:
        stages = [stage.model_dump() for stage in payload.stages or []]

        existing_stage_numbers = {
            stage.get("stageNumber")
            for stage in stages
            if isinstance(stage, dict)
        }

        if 1 not in existing_stage_numbers:
            stages.append(
                {
                    "stageNumber": 1,
                    "stageName": "Konteks Dasar Pembelajaran",
                    "contentJson": get_intra_dummy_stage_content(1),
                }
            )

        if 2 not in existing_stage_numbers:
            stages.append(
                {
                    "stageNumber": 2,
                    "stageName": "Fondasi Tujuan Pembelajaran",
                    "contentJson": get_intra_dummy_stage_content(2),
                }
            )

        return sorted(stages, key=lambda item: item.get("stageNumber") or 999)

    def _extract_teacher_name(
        self, payload: KinaChatRequest, stages: list[dict[str, Any]]
    ) -> str:
        project_data = payload.project.model_dump()
        for key in ("teacherName", "fullName", "name", "userName"):
            value = project_data.get(key)
            if isinstance(value, str) and value.strip():
                return self._first_name(value)

        for stage in stages:
            if stage.get("stageNumber") != 1:
                continue

            content = stage.get("contentJson") or {}
            if not isinstance(content, dict):
                continue

            for key in (
                "namaGuru",
                "nama_guru",
                "Nama guru",
                "nama",
                "teacherName",
                "fullName",
            ):
                value = content.get(key)
                if isinstance(value, str) and value.strip():
                    return self._first_name(value)

        return "teman guru"

    def _first_name(self, value: str) -> str:
        return value.strip().split()[0]

    def _polish_reply(
        self,
        value: str,
        teacher_name: str,
        *,
        allow_name: bool,
    ) -> str:
        text = self._polish_short_text(value)
        text = re.sub(r"\bAnda\b", "kamu", text, flags=re.IGNORECASE)
        text = re.sub(r"\bBapak/Ibu Guru\b", "kamu", text, flags=re.IGNORECASE)
        text = re.sub(r"\bBapak/Ibu\b", "kamu", text, flags=re.IGNORECASE)
        text = re.sub(r"\bPak/Bu\b", "kamu", text, flags=re.IGNORECASE)
        text = re.sub(r"\bSelanjutnya,?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\bBerikutnya,?\s*", "", text, flags=re.IGNORECASE)

        name = self._first_name(teacher_name) if teacher_name else ""
        if name and name != "teman":
            seen = 0

            def replace_repeated_name(match: re.Match[str]) -> str:
                nonlocal seen
                seen += 1
                return match.group(0) if allow_name and seen == 1 else ""

            text = re.sub(rf"\b{re.escape(name)}\b", replace_repeated_name, text)

        text = re.sub(r",\s*([?.!])", r"\1", text)
        text = re.sub(r"\s+([,.?!])", r"\1", text)
        return re.sub(r"\s+", " ", text).strip()

    def _polish_short_text(self, value: str) -> str:
        text = value.strip()
        text = re.sub(r"\*\*(.*?)\*\*", r"\1", text)
        text = re.sub(r"__(.*?)__", r"\1", text)
        text = text.replace("*", "")
        text = text.replace("`", "")
        text = re.sub(r"\b(Kak|Mas|Mbak)\b\.?", "", text, flags=re.IGNORECASE)
        text = re.sub(r",\s*([?.!])", r"\1", text)
        text = re.sub(r"\s+([,.?!])", r"\1", text)
        return re.sub(r"\s+", " ", text).strip()

    def _build_stage_3_system_prompt(self) -> str:
        return """
Kamu adalah KINA, teman ngobrol guru di Studio Guru.
Kamu sedang membantu guru menyusun Stage 3 RPM Intrakurikuler: strategi, pendekatan, fasilitas, platform, dan produk akhir.

PERAN KOMUNIKASI:
- Kamu bukan pewawancara.
- Kamu adalah partner ngobrol yang ramah, santai, dan tetap berguna.
- Validasi singkat, tangkap maksud guru, lalu ajukan 1 langkah kecil berikutnya.
- Buat guru merasa sedang ngobrol, bukan sedang mengisi formulir.
- Hindari gaya kaku seperti checklist, survei, atau interview.

GAYA BAHASA:
- Gunakan bahasa Indonesia santai, ringan, dan singkat.
- Gunakan "aku" dan "kamu" secara natural. Jangan gunakan "Anda", "Bapak/Ibu", "Pak", atau "Bu".
- Kalau bertanya pilihan berikutnya, gunakan "kamu" secara natural, misalnya "kamu mau..." atau "menurut kamu...".
- Nama guru hanya boleh dipakai saat membuka percakapan. Setelah chat berjalan, jangan pakai nama guru; pakai "kamu".
- Jangan membuka setiap balasan dengan nama guru.
- Jangan pakai sapaan "Kak", "Mas", atau "Mbak".
- Hindari pujian kosong seperti "oke juga tuh" atau "bagus sekali".
- Hindari kesan menggurui. Jangan menjelaskan terlalu panjang kalau guru baru memilih opsi.
- Jangan memakai kata "selanjutnya"; cukup arahkan dengan santai.
- Jangan terlalu cepat pindah ke pertanyaan berikutnya.
- Jika jawaban guru masih umum, beri contoh kecil dulu.
- Jika guru terlihat ragu, beri 2–3 opsi realistis, singkat saja.
- Jangan menggurui.
- Jangan gunakan markdown, bullet list, numbering, bold, italic, tanda **, atau backtick.

BATAS RESPONS:
- Maksimal 2 kalimat pendek.
- Total balasan idealnya 12-28 kata.
- Kalau guru baru memilih opsi, cukup kunci pilihannya dan tanya 1 hal berikutnya.
- Jika memberi opsi, maksimal 3 opsi.
- Ajukan maksimal 1 pertanyaan ringan di akhir.
- Jangan menulis pembuka panjang.
- Jangan membuat dokumen final.
- Jangan membuat PDF/DOCX.
- Jika sistem meminta format terstruktur, isi field reply dengan teks obrolan biasa dan jangan menyebut JSON di reply.
- Jangan menampilkan nama field teknis seperti active_field, teacher_inputs, atau contentJson.
- Contoh gaya yang diinginkan: "Sip, Google Classroom cukup buat kumpulin tugas dan komentar kelompok. Kamu mau kunci itu, atau tambah satu platform lagi?"
- Contoh yang harus dihindari: "Google Classroom, oke juga tuh Vito! Bisa buat..."

KONTEKS WAJIB:
- Stage 1 adalah konteks dasar pembelajaran.
- Stage 2 adalah fondasi tujuan pembelajaran.
- Stage 3 harus selalu mempertimbangkan Stage 1 dan Stage 2.
- Gunakan data Stage 1 seperti jenjang, kelas, mata pelajaran, materi, durasi, kondisi kelas, karakteristik siswa, dan fasilitas.
- Gunakan data Stage 2 seperti capaian pembelajaran, tujuan pembelajaran terpilih, dimensi profil lulusan, dan pertanyaan pemantik.
- Jangan memberi saran generik yang tidak nyambung dengan Stage 1 dan Stage 2.

URUTAN DISKUSI STAGE 3 WAJIB:
Diskusi harus berjalan urut, tetapi tetap natural.

1. gaya_pembelajaran
   Bahas bentuk belajar yang diinginkan guru, misalnya diskusi, studi kasus, eksperimen, mini proyek, latihan terarah, atau campuran.
   Jangan lanjut ke poin 2 sebelum arah gaya pembelajaran cukup jelas.

2. preferensi_pedagogis
   Bahas pendekatan/model pedagogis, misalnya PBL ringan, inquiry terbimbing, mini-PjBL, pembelajaran kolaboratif, atau direct instruction yang dipadukan aktivitas.
   Jika guru ragu, beri rekomendasi berdasarkan Stage 1 dan Stage 2.
   Jangan lanjut ke poin 3 sebelum pendekatan pedagogis cukup jelas.

3. pemanfaatan_fasilitas_dan_teknologi
   Bahas bagaimana fasilitas dari Stage 1 dimanfaatkan.
   Jangan bertanya ulang secara mentah "fasilitas apa yang tersedia" jika data fasilitas sudah ada.
   Contoh:
   - HP dan internet dapat digunakan untuk riset kecil, kuis interaktif, Google Form, Padlet, atau Google Slides.
   - Proyektor dapat digunakan untuk video pemantik, visualisasi konsep, atau presentasi.
   - Papan tulis dapat digunakan untuk pemetaan konsep, contoh bertahap, atau pembahasan bersama.
   Jangan lanjut ke poin 4 sebelum pemanfaatan fasilitas cukup jelas.

4. platform_digital
   Bahas platform digital hanya jika relevan dengan fasilitas dan strategi pembelajaran.
   Jika tidak diperlukan, boleh sepakati "tidak digunakan".
   Jangan memaksa guru memakai platform digital.

5. produk_kinerja_akhir
   Bahas produk/kinerja akhir siswa, misalnya laporan, poster, presentasi, video, infografik, portofolio, atau hasil latihan terstruktur.
   Produk akhir harus nyambung dengan gaya pembelajaran, pendekatan pedagogis, tujuan pembelajaran, dan fasilitas.
   Jika guru sudah menyebut minimal satu produk akhir yang masuk akal, jangan bertanya "ada lagi?".
   Langsung kunci produk itu dan tutup dengan kalimat bahwa rancangan Stage 3 sudah lengkap.

ATURAN MENJAGA URUTAN:
- Gunakan riwayat chat untuk menebak poin mana yang sudah selesai.
- Jangan loncat ke poin berikutnya jika poin saat ini belum cukup jelas.
- Jika guru bertanya di luar urutan, jawab seperlunya lalu kembalikan dengan halus ke poin yang sedang dibahas.
- Jika guru meminta rekomendasi, fokus memberi rekomendasi untuk poin yang sedang dibahas dan jangan langsung pindah topik.
- Jika guru memilih salah satu opsi, rangkum keputusan dengan natural, lalu arahkan pelan ke poin berikutnya.
- Khusus produk/kinerja akhir: setelah guru memilih produk, jangan minta tambahan produk. Tutup diskusi Stage 3.
- Jangan menanyakan semua poin sekaligus.
- Jangan membuat percakapan terasa seperti daftar pertanyaan.

PENUTUP:
Jika semua poin Stage 3 sudah cukup terjawab, berikan ringkasan akhir singkat yang mencakup:
1. gaya pembelajaran,
2. pendekatan pedagogis,
3. pemanfaatan fasilitas dan teknologi,
4. platform digital jika digunakan,
5. produk/kinerja akhir.

Akhiri dengan kalimat:
"Sip, datanya sudah lengkap dan siap dipakai ke tahap berikutnya."
""".strip()
    
    
    def _build_stage_3_user_prompt(
        self,
        payload: KinaChatRequest,
        references: list[Any],
        stage_context: list[dict[str, Any]],
        teacher_name: str,
        is_initial_chat: bool,
    ) -> str:
        latest_message_block = (
            "Belum ada pesan dari guru. Ini adalah awal percakapan Stage 3, "
            "jadi Kina harus menyapa dulu dan mengajukan pertanyaan pembuka."
            if is_initial_chat
            else f"Pesan terbaru guru:\n{payload.message}"
        )
        task_block = (
            """
Tugas kamu:
- Buka percakapan Stage 3 dengan hangat, singkat, dan natural.
- Jangan mengatakan guru belum mengisi pesan.
- Gunakan Stage 1 dan Stage 2 untuk memberi konteks singkat.
- Mulai dari poin pertama: gaya_pembelajaran.
- Ajukan hanya 1 pertanyaan ringan tentang bentuk belajar yang diinginkan guru.
- Jika membantu, beri 2-3 contoh opsi singkat seperti diskusi, studi kasus, eksperimen, mini proyek, atau latihan terarah.
- Jangan langsung masuk ke pendekatan pedagogis, fasilitas, platform digital, atau produk akhir.
""".strip()
            if is_initial_chat
            else """
Tugas kamu:
- Jawab pesan terbaru guru dengan gaya ngobrol yang santai dan pendek.
- Utamakan kata "kamu"; gunakan nama guru hanya kalau benar-benar perlu dan jangan diulang.
- Gunakan Stage 1 dan Stage 2 agar respons tidak generik.
- Jaga urutan diskusi Stage 3:
  1. gaya pembelajaran,
  2. preferensi pedagogis,
  3. pemanfaatan fasilitas dan teknologi,
  4. platform digital,
  5. produk/kinerja akhir.
- Tentukan posisi diskusi dari chatHistory.
- Jangan loncat ke poin berikutnya jika poin saat ini belum cukup jelas.
- Jika guru meminta saran, berikan saran yang kontekstual berdasarkan materi, kelas, kondisi kelas, tujuan pembelajaran, dan fasilitas.
- Jika guru menjawab pilihan, bantu rangkum keputusan dan arahkan pelan ke poin berikutnya.
- Jika semua poin sudah cukup, berikan ringkasan akhir Stage 3 dan tutup dengan:
  "Sip, datanya sudah lengkap dan siap dipakai ke tahap berikutnya."
""".strip()
        )
        return "\n\n".join(
            [
                "Konteks project:",
                self.prompt_builder.project_context(payload.project),

                "Nama guru yang dapat digunakan dalam sapaan:",
                teacher_name,

                "Data Stage 1 dan Stage 2 yang WAJIB menjadi konteks utama diskusi Stage 3:",
                json.dumps(stage_context, ensure_ascii=False, indent=2),

                "Referensi RAG jika relevan:",
                self.prompt_builder.rag_context(references),

                "Riwayat chat terakhir:",
                json.dumps(
                    [chat.model_dump() for chat in payload.chatHistory[-12:]],
                    ensure_ascii=False,
                    indent=2,
                ),

                latest_message_block,

                task_block,
            ]
        )

    def _fallback_reply(self, payload: KinaChatRequest, teacher_name: str) -> str:
        topic = payload.project.title or payload.project.subject or "pembelajaran"
        sapaan = teacher_name if teacher_name else "teman guru"

        return (
            f"Oke, {sapaan}. Kita susun alur untuk {topic} pelan-pelan ya. "
            "Mulai dari gaya belajarnya dulu: mau diskusi, studi kasus, mini proyek, latihan terarah, atau campuran?"
        )

    def _initial_fallback_reply(
        self,
        payload: KinaChatRequest,
        teacher_name: str,
    ) -> str:
        topic = payload.project.title or payload.project.subject or "pembelajaran ini"
        sapaan = teacher_name if teacher_name else "teman guru"

        return (
            f"Halo, {sapaan}. CP dan ATP untuk {topic} sudah siap. "
            "Kita mulai dari gaya belajarnya dulu ya: diskusi, studi kasus, mini proyek, latihan terarah, atau campuran?"
        )

    def _follow_up_questions(self, payload: KinaChatRequest) -> list[str]:
        subject = payload.project.subject or "mapel ini"
        return [
            "Mau aku bantu pilihkan opsi yang paling realistis untuk kondisi kelas ini?",
            f"Apakah aktivitas untuk {subject} ini lebih nyaman dibuat diskusi, studi kasus, atau mini proyek?",
        ]
