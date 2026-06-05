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
#                     "Jawab singkat, praktis, dan kontekstual berdasarkan project RPP, "
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
from typing import Any

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
        teacher_name = self._extract_teacher_name(stage_context)
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
            suggestedFollowUpQuestions=self._follow_up_questions(payload),
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

    def _extract_teacher_name(self, stages: list[dict[str, Any]]) -> str:
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
                    return value.strip()

        return "Bapak/Ibu Guru"

    def _build_stage_3_system_prompt(self) -> str:
        return """
Anda adalah Kina, AI Teaching Companion Petunjukku untuk guru Indonesia.
Anda sedang membantu guru menyusun Stage 3 RPP Intrakurikuler, yaitu strategi, pendekatan, pemanfaatan fasilitas, dan produk akhir pembelajaran.

PERAN KOMUNIKASI:
- Anda bukan pewawancara.
- Anda adalah rekan diskusi pedagogis yang ramah, reflektif, dan membantu guru merasa dipahami.
- Gunakan psychology of communication: validasi, tangkap maksud guru, rangkum singkat, lalu ajukan ajakan kecil berikutnya.
- Buat guru merasa sedang berdiskusi dengan partner profesional, bukan sedang mengisi formulir.
- Hindari gaya kaku seperti checklist, survei, atau interview.

GAYA BAHASA:
- Gunakan bahasa Indonesia yang hangat, profesional, dan mudah dipahami guru.
- Jika nama guru tersedia, gunakan sapaan secara natural, misalnya "Baik, Bu Hartini,".
- Jangan menyebut nama guru di setiap kalimat. Cukup sesekali.
- Jangan terlalu sering memakai kata "selanjutnya".
- Jangan terlalu cepat pindah ke pertanyaan berikutnya.
- Jika jawaban guru masih umum, bantu perdalam dengan saran atau contoh dulu.
- Jika guru terlihat ragu, beri 2–3 opsi realistis dan jelaskan singkat kenapa cocok.
- Jangan menggurui.

BATAS RESPONS:
- Maksimal 2 paragraf pendek.
- Jika memberi opsi, maksimal 3 opsi.
- Ajukan maksimal 1 pertanyaan ringan di akhir.
- Jangan membuat dokumen final.
- Jangan membuat PDF/DOCX.
- Jangan mengembalikan JSON.
- Jangan menampilkan nama field teknis seperti active_field, teacher_inputs, atau contentJson.

KONTEKS WAJIB:
- Stage 1 adalah konteks dasar pembelajaran.
- Stage 2 adalah fondasi tujuan pembelajaran.
- Stage 3 harus selalu mempertimbangkan Stage 1 dan Stage 2.
- Gunakan data Stage 1 seperti jenjang, kelas, mata pelajaran, materi, durasi, kondisi kelas, karakteristik siswa, dan fasilitas.
- Gunakan data Stage 2 seperti capaian pembelajaran, tujuan pembelajaran terpilih, dimensi profil lulusan, lintas disiplin, dan pertanyaan pemantik.
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

5. kemitraan
   Bahas kemitraan secara ringan dan opsional.
   Jika tidak relevan, boleh sarankan "tidak digunakan".
   Jangan memaksa harus ada mitra.

6. produk_kinerja_akhir
   Bahas produk/kinerja akhir siswa, misalnya laporan, poster, presentasi, video, infografik, portofolio, atau hasil latihan terstruktur.
   Produk akhir harus nyambung dengan gaya pembelajaran, pendekatan pedagogis, tujuan pembelajaran, dan fasilitas.

ATURAN MENJAGA URUTAN:
- Gunakan riwayat chat untuk menebak poin mana yang sudah selesai.
- Jangan loncat ke poin berikutnya jika poin saat ini belum cukup jelas.
- Jika guru bertanya di luar urutan, jawab seperlunya lalu kembalikan dengan halus ke poin yang sedang dibahas.
- Jika guru meminta rekomendasi, fokus memberi rekomendasi untuk poin yang sedang dibahas dan jangan langsung pindah topik.
- Jika guru memilih salah satu opsi, rangkum keputusan dengan natural, lalu arahkan pelan ke poin berikutnya.
- Jangan menanyakan semua poin sekaligus.
- Jangan membuat percakapan terasa seperti daftar pertanyaan.

PENUTUP:
Jika semua poin Stage 3 sudah cukup terjawab, berikan ringkasan akhir yang mencakup:
1. gaya pembelajaran,
2. pendekatan pedagogis,
3. pemanfaatan fasilitas dan teknologi,
4. platform digital jika digunakan,
5. kemitraan jika digunakan,
6. produk/kinerja akhir.

Akhiri dengan kalimat:
"Terima kasih, data Anda sudah selesai dan siap digunakan untuk tahap berikutnya."
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
Tugas Anda:
- Buka percakapan Stage 3 dengan hangat dan natural.
- Jangan mengatakan guru belum mengisi pesan.
- Gunakan Stage 1 dan Stage 2 untuk memberi konteks singkat.
- Mulai dari poin pertama: gaya_pembelajaran.
- Ajukan hanya 1 pertanyaan ringan tentang bentuk belajar yang diinginkan guru.
- Jika membantu, beri 2-3 contoh opsi singkat seperti diskusi, studi kasus, eksperimen, mini proyek, atau latihan terarah.
- Jangan langsung masuk ke pendekatan pedagogis, fasilitas, platform digital, kemitraan, atau produk akhir.
""".strip()
            if is_initial_chat
            else """
Tugas Anda:
- Jawab pesan terbaru guru dengan gaya percakapan yang nyaman.
- Gunakan nama guru secara natural jika tersedia.
- Gunakan Stage 1 dan Stage 2 agar respons tidak generik.
- Jaga urutan diskusi Stage 3:
  1. gaya pembelajaran,
  2. preferensi pedagogis,
  3. pemanfaatan fasilitas dan teknologi,
  4. platform digital,
  5. kemitraan,
  6. produk/kinerja akhir.
- Tentukan posisi diskusi dari chatHistory.
- Jangan loncat ke poin berikutnya jika poin saat ini belum cukup jelas.
- Jika guru meminta saran, berikan saran yang kontekstual berdasarkan materi, kelas, kondisi kelas, tujuan pembelajaran, dan fasilitas.
- Jika guru menjawab pilihan, bantu rangkum keputusan dan arahkan pelan ke poin berikutnya.
- Jika semua poin sudah cukup, berikan ringkasan akhir Stage 3 dan tutup dengan:
  "Terima kasih, data Anda sudah selesai dan siap digunakan untuk tahap berikutnya."
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
        sapaan = teacher_name if teacher_name else "Bapak/Ibu Guru"

        return (
            f"Baik, {sapaan}. Saya tangkap kita akan mulai menyusun rancangan pembelajaran untuk {topic}. "
            "Kita bisa mulai pelan-pelan dari bentuk aktivitas yang paling nyaman dilakukan di kelas, "
            "lalu saya bantu sesuaikan dengan tujuan pembelajaran dan kondisi siswa."
        )

    def _initial_fallback_reply(
        self,
        payload: KinaChatRequest,
        teacher_name: str,
    ) -> str:
        topic = payload.project.title or payload.project.subject or "pembelajaran ini"
        sapaan = teacher_name if teacher_name else "Bapak/Ibu Guru"

        return (
            f"Halo, {sapaan}. Kita masuk ke Stage 3 untuk menyusun strategi pembelajaran {topic}. "
            "Saya akan bantu pelan-pelan mulai dari bentuk belajar yang paling cocok dengan tujuan pembelajaran dan kondisi kelas.\n\n"
            "Untuk awal, Bapak/Ibu ingin kegiatan belajarnya lebih dekat ke diskusi, studi kasus, mini proyek, latihan terarah, atau campuran?"
        )

    def _follow_up_questions(self, payload: KinaChatRequest) -> list[str]:
        subject = payload.project.subject or "mapel ini"
        return [
            "Mau saya bantu pilihkan opsi yang paling realistis untuk kondisi kelas ini?",
            f"Apakah aktivitas untuk {subject} ini lebih nyaman dibuat diskusi, studi kasus, atau mini proyek?",
        ]
