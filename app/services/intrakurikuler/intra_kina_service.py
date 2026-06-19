

from __future__ import annotations
import json
import re
from typing import Any

from fastapi import HTTPException, status

from app.services.intrakurikuler.stage3_conversation.stage3_prompt_composer import (
    compose_stage3_system_prompt,
)
from app.schemas.common_schema import UsedReferenceSchema
from app.schemas.kina_schema import KinaChatRequest, KinaChatResponse
from app.services.intrakurikuler.intra_dummy_stage_data import (
    get_intra_dummy_onboarding_content,
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
        onboarding_content = self._onboarding_context_with_dummy(payload)
        teacher_name = self._extract_teacher_name(
            payload,
            stage_context,
            onboarding_content,
        )
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
                    onboarding_content=onboarding_content,
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
                                "Jangan pakai markdown, tanda **, atau menyebut format JSON."
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

        has_frontend_stages = any(
            isinstance(stage, dict) and not self._is_empty_value(stage.get("contentJson"))
            for stage in stages
        )

        if has_frontend_stages:
            # Jika frontend sudah mengirim stage, jangan campur dengan dummy.
            return sorted(stages, key=lambda item: item.get("stageNumber") or 999)

        # Dummy hanya dipakai untuk mode testing/demo ketika frontend belum mengirim stage sama sekali.
        stages.extend(
            [
                {
                    "stageNumber": 1,
                    "stageName": "Konteks Dasar Pembelajaran",
                    "contentJson": get_intra_dummy_stage_content(1),
                },
                {
                    "stageNumber": 2,
                    "stageName": "Fondasi Tujuan Pembelajaran",
                    "contentJson": get_intra_dummy_stage_content(2),
                },
            ]
        )

        return sorted(stages, key=lambda item: item.get("stageNumber") or 999)
    def _onboarding_context_with_dummy(self, payload: KinaChatRequest) -> dict[str, Any]:
        payload_onboarding = {
            "school": self._dump_model(getattr(payload, "school", None)),
            "teacherProfile": self._dump_model(getattr(payload, "teacherProfile", None)),
            "teacherClass": self._dump_model(getattr(payload, "teacherClass", None)),
            "teacherSubject": self._dump_model(getattr(payload, "teacherSubject", None)),
        }

        has_frontend_onboarding = any(
            not self._is_empty_value(value)
            for value in payload_onboarding.values()
        )

        if has_frontend_onboarding:
            return payload_onboarding

        return get_intra_dummy_onboarding_content()


    def _dump_model(self, value: Any) -> dict[str, Any]:
        if value is None:
            return {}

        if hasattr(value, "model_dump"):
            return value.model_dump()

        if isinstance(value, dict):
            return value

        return {}

    def _is_empty_value(self, value: Any) -> bool:
        if value is None:
            return True

        if isinstance(value, str):
            return not value.strip()

        if isinstance(value, list):
            if not value:
                return True
            return all(self._is_empty_value(item) for item in value)

        if isinstance(value, dict):
            if not value:
                return True
            return all(self._is_empty_value(item) for item in value.values())

        return False
    
    def _extract_teacher_name(
        self,
        payload: KinaChatRequest,
        stages: list[dict[str, Any]],
        onboarding_context: dict[str, Any],
    ) -> str:
        teacher_profile = onboarding_context.get("teacherProfile") or {}

        for key in ("teacherName", "fullName", "namaGuru", "nama_guru", "nama"):
            teacher_name = teacher_profile.get(key)
            if isinstance(teacher_name, str) and teacher_name.strip():
                return teacher_name.strip()

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
        return compose_stage3_system_prompt()

    
    
    def _build_stage_3_user_prompt(
        self,
        payload: KinaChatRequest,
        references: list[Any],
        stage_context: list[dict[str, Any]],
        onboarding_content: dict[str, Any],
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
- Jangan langsung masuk ke pendekatan pedagogis, fasilitas, platform digital, kemitraan, atau produk akhir.
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
  5. kemitraan,
  6. produk/kinerja akhir.
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

            "Data onboarding guru, sekolah, kelas, dan mata pelajaran:",
            json.dumps(onboarding_content, ensure_ascii=False, indent=2),

            "Data Stage 1 dan Stage 2 yang WAJIB menjadi konteks utama diskusi Stage 3:",
            json.dumps(stage_context, ensure_ascii=False, indent=2),

            "Referensi RAG jika relevan:",
            self.prompt_builder.rag_context(references),

            "Riwayat chat terakhir:",
            json.dumps(
                [chat.model_dump() for chat in payload.chatHistory[-50:]],
                ensure_ascii=False,
                indent=2,
            ),

            latest_message_block,

            """
Tugas Anda:
- Jawab pesan terbaru guru dengan gaya percakapan yang nyaman, hangat, dan profesional.
- Jangan selalu menyapa nama guru di awal respons.
- Gunakan sapaan nama guru hanya jika terasa natural, misalnya saat awal diskusi, menguatkan keputusan penting, menjawab kebingungan, atau menutup diskusi.
- Variasikan kalimat pembuka respons agar tidak berulang, terutama hindari terlalu sering memakai "Baik", "Senang mendengar", atau "Terima kasih".
- Gunakan nama guru secara natural jika tersedia.
- Gunakan data teacherProfile.gender dari onboarding untuk menentukan sapaan.
- Jika gender bernilai "Perempuan" atau "perempuan", gunakan sapaan "Ibu".
- Jika gender bernilai "Laki-laki" atau "laki-laki", gunakan sapaan "Bapak".
- Jika gender tidak tersedia atau tidak jelas, gunakan sapaan netral "Bapak/Ibu Guru".
- Jangan menebak gender hanya dari nama guru.
- Jangan menggunakan dua sapaan dalam satu kalimat.
- Jika nama guru terlalu panjang, boleh gunakan sapaan dan nama depan dari onboarding agar respons lebih natural.
- Jangan menyebut nama guru di setiap respons jika tidak diperlukan.
- Gunakan Stage 1 dan Stage 2 agar respons tidak generik.
- Tentukan posisi diskusi dari chatHistory, tetapi jangan tampilkan nama field teknis kepada guru.
- PRIORITAS TERTINGGI: sebelum menjawab, periksa seluruh chatHistory dan tentukan secara internal field wajib Stage 3 mana yang sudah jelas dan mana yang belum.
- Field wajib Stage 3 adalah: gaya pembelajaran, preferensi pedagogis, fasilitas/teknologi, sumber belajar/media, kemitraan, dan produk/kinerja akhir.
- Field yang sudah terjawab di bagian mana pun dalam chatHistory dianggap selesai, meskipun muncul tidak sesuai urutan.
- Jika semua field wajib sudah jelas dan pesan terbaru guru berisi sinyal selesai seperti "cukup", "tidak ada", "tidak ada tambahan", "semua sudah oke", "semua sesuai", "siap dilaksanakan", "boleh berikan ringkasan", "boleh menyelesaikan diskusi", atau "selesaikan", langsung berikan ringkasan akhir Stage 3.
- Jika guru berkata "lanjutkan", pahami berdasarkan konteks: jika semua field wajib sudah jelas, lanjutkan ke ringkasan akhir; jika masih ada field wajib yang belum jelas, lanjutkan hanya ke field yang belum jelas tersebut.
- Setelah guru memberi sinyal selesai dan semua field wajib sudah jelas, jangan bertanya "apakah ada tambahan", "apakah sudah cukup", "apakah sudah siap", atau pertanyaan konfirmasi lain.
- Jika semua field wajib sudah jelas, dilarang membuka pertanyaan lanjutan.
- Jika guru sudah meminta ringkasan, langsung berikan ringkasan.
- Jika guru sudah meminta menyelesaikan diskusi, berikan ringkasan akhir jika belum diberikan, lalu tutup diskusi dengan kalimat penutup.
- Jaga urutan diskusi Stage 3:
  1. gaya pembelajaran,
  2. preferensi pedagogis,
  3. pemanfaatan fasilitas dan teknologi,
  4. sumber belajar dan media,
  5. kemitraan,
  6. produk/kinerja akhir.
- Jangan loncat ke poin berikutnya jika poin saat ini belum cukup jelas.
- Jika guru meminta saran, bingung, atau meminta contoh, fokus bantu pada poin yang sedang dibahas saja.
- Jika guru menjawab "setuju", "oke", "baik", "boleh", atau jawaban pendek sejenis, jangan langsung pindah topik.
- Setelah guru menyetujui pilihan, rangkum keputusan tersebut secara natural lalu ajukan satu pertanyaan pendalaman ringan agar keputusan lebih operasional.
- Pindah ke poin berikutnya hanya jika guru memberi sinyal eksplisit seperti "lanjut", "bisa dilanjutkan", "sudah jelas", "cukup", "sudah cukup", atau "oke lanjut".
- Saat membahas sumber belajar/media, tawarkan maksimal 3 tipe yang sesuai: buku resmi Kemendikdasmen, video YouTube, media interaktif, media non-digital, atau dipilihkan otomatis.
- Jangan meminta guru memasukkan tautan. Resource discovery service akan mencari dan memilih judul serta URL setelah Stage 3.
- Jika guru memilih tidak menggunakan media digital atau kemitraan, validasi pilihan itu sebagai keputusan yang sah dan jangan memaksakan opsi lain.
- Jangan menawarkan terlalu banyak topik dalam satu respons.
- Jangan menutup respons penjelasan dengan dorongan untuk pindah tahap.
- Pastikan respons selalu nyambung dengan keputusan guru sebelumnya di chatHistory.
- Jangan menanyakan ulang keputusan yang sudah dipilih guru.
- Ketika masuk ke poin baru, awali dengan mengaitkan poin baru tersebut dengan keputusan sebelumnya.
- Jika gaya pembelajaran sudah dipilih, saat membahas preferensi pedagogis jangan bertanya ulang bentuk gaya pembelajaran. Gunakan gaya pembelajaran tersebut sebagai dasar rekomendasi pedagogis.
- Jika fasilitas sudah dipilih, saat membahas sumber belajar/media jangan bertanya ulang fasilitas. Kaitkan rekomendasi tipe media dengan fasilitas yang sudah dipilih.
- Jika guru berkata "tadi sudah dibahas", akui bahwa poin itu sudah dibahas dan lanjutkan ke poin berikutnya yang belum selesai.
- Jangan memberikan ringkasan akhir Stage 3 sebelum keenam bagian wajib sudah dibahas: gaya pembelajaran, preferensi pedagogis, fasilitas/teknologi, sumber belajar/media, kemitraan, dan produk/kinerja akhir.
- Jika guru berkata "cukup", "tidak ada", atau "sudah cukup", pahami itu sebagai cukup untuk bagian yang sedang dibahas, bukan otomatis selesai seluruh Stage 3.
- Jika masih ada bagian wajib yang belum dibahas, lanjutkan ke bagian tersebut dengan halus.
- Jika guru menyebut "guru Bahasa Indonesia", "guru Informatika", "orang tua", "komunitas", atau pihak tertentu saat membahas kemitraan, catat itu sebagai mitra yang dipilih.
- Jangan menyimpulkan "tidak menggunakan kemitraan" jika guru menyebut pihak tertentu sebagai mitra.
- Jika produk akhir sudah dibahas lebih dulu, jangan tanyakan ulang produk akhir. Cukup akui bahwa produk akhir sudah dibahas, lalu lanjutkan ke bagian wajib yang belum selesai.
- - Jika semua poin Stage 3 sudah benar-benar cukup, berikan ringkasan akhir Stage 3.
- Setelah ringkasan akhir, jangan ajukan pertanyaan apa pun.
- Jangan menutup ringkasan akhir dengan "apakah ada tambahan", "apakah sudah sesuai", atau pertanyaan konfirmasi lain.
- Tutup respons dengan kalimat:
  "Terima kasih, data Anda sudah selesai dan siap digunakan untuk tahap berikutnya."
""".strip(),
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
