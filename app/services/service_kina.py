from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.data_store import now_iso, store
from app.services.openrouter_client import OpenRouterClient

STAGE_3_FIELDS = [
    {
        "key": "gaya_pembelajaran",
        "label": "Gaya pembelajaran",
        "question": "Guru ingin pembelajaran lebih banyak diskusi, eksperimen, studi kasus, proyek kecil, atau campuran?",
        "required": True,
    },
    {
        "key": "preferensi_pedagogis",
        "label": "Preferensi pedagogis",
        "question": "Apakah ada model yang ingin digunakan? Misalnya PBL, inquiry, mini-PjBL, kolaboratif, atau AI yang memilihkan?",
        "required": False,
    },
    {
        "key": "fasilitas_kelas",
        "label": "Fasilitas kelas",
        "question": "Fasilitas yang tersedia apa saja? Misalnya proyektor, HP murid, internet, lab, papan tulis, kertas plano, atau lainnya?",
        "required": True,
    },
    {
        "key": "ketersediaan_teknologi",
        "label": "Ketersediaan teknologi",
        "question": "Apakah boleh menggunakan media digital dalam pembelajaran?",
        "required": True,
    },
    {
        "key": "platform_digital",
        "label": "Platform digital",
        "question": "Platform apa yang bisa digunakan? Misalnya Google Form, Canva, Padlet, LMS, video, kuis interaktif, AI, atau lainnya?",
        "required": False,
    },
    {
        "key": "kemitraan",
        "label": "Kemitraan",
        "question": "Apakah pembelajaran ingin melibatkan mitra, seperti guru mapel lain, orang tua, komunitas, narasumber, dunia kerja, atau tidak digunakan?",
        "required": False,
    },
    {
        "key": "produk_kinerja_akhir",
        "label": "Produk/kinerja akhir",
        "question": "Murid akan menghasilkan apa di akhir pembelajaran? Misalnya laporan, poster, presentasi, infografik, prototipe, portofolio, atau lainnya?",
        "required": True,
    },
]
class KinaService:
    """
    MVP service_kina.py

    Flow:
    1. Ambil data dummy Stage 1 dan Stage 2 dari planning_state.
    2. Kirim konteks ke OpenRouter untuk membuat Stage 3.
    3. Simpan chat user dan assistant.
    4. Simpan hasil Stage 3 ke planning_state["strategy"].
    """

    def __init__(self, llm_client: Optional[OpenRouterClient] = None) -> None:
        self.llm_client = llm_client or OpenRouterClient()

    async def chat(
        self,
        project_id: str,
        message_text: str,
        current_stage: Optional[int] = 3,
        use_ai_generation: bool = True,
        generate_if_requested: bool = False,
    ) -> Dict[str, Any]:
        project = store.get_project(project_id)
        planning_state = store.get_planning_state(project_id)
        chat_history = store.get_chats(project_id)
        stage = current_stage or 3

        store.add_chat(project_id=project_id, role="user", message=message_text, stage=stage)

        if stage != 3:
            assistant_payload = {
                "assistant_message": "Untuk BOT ini, percakapan Kina difokuskan untuk membangun Stage 3 terlebih dahulu.",
                "structured_update": {},
                "missing_fields": [],
                "next_question": "Silakan beri instruksi rancangan kegiatan pembelajaran untuk Stage 3.",
            }
        elif use_ai_generation:
            system_prompt = self._build_system_prompt()
            user_prompt = self._build_stage_3_prompt(
                project=project,
                planning_state=planning_state,
                chat_history=chat_history,
                message_text=message_text,
            )
            assistant_payload = await self.llm_client.generate_json(system_prompt, user_prompt)
        else:
            assistant_payload = self._manual_response()

        structured_update = assistant_payload.get("structured_update", {})
        if structured_update:
            planning_state["strategy"] = self._deep_merge(
                planning_state.get("strategy", {}),
                structured_update,
            )
            planning_state["ai_logs"].append(
                {
                    "stage": stage,
                    "action": "update_strategy_from_kina_chat",
                    "structured_update": structured_update,
                    "created_at": now_iso(),
                }
            )
            store.save_planning_state(project_id, planning_state)

        store.add_chat(
            project_id=project_id,
            role="assistant",
            message=assistant_payload.get("assistant_message", ""),
            stage=stage,
            metadata={
                "missing_fields": assistant_payload.get("missing_fields", []),
                "next_question": assistant_payload.get("next_question"),
                "structured_update_keys": list(structured_update.keys()),
                "generate_if_requested": generate_if_requested,
            },
        )

        return {
            "project": project,
            "stage": stage,
            "assistant_message": assistant_payload.get("assistant_message", ""),
            "stage_3": planning_state.get("strategy", {}),
            "planning_state": planning_state,
            "missing_fields": assistant_payload.get("missing_fields", []),
            "next_question": assistant_payload.get("next_question"),
        }

    def get_chat_history(self, project_id: str) -> List[Dict[str, Any]]:
        store.get_project(project_id)
        return store.get_chats(project_id)

    def get_planning_state(self, project_id: str) -> Dict[str, Any]:
        store.get_project(project_id)
        return store.get_planning_state(project_id)

    async def summarize(self, project_id: str) -> Dict[str, Any]:
        planning_state = store.get_planning_state(project_id)
        chats = store.get_chats(project_id)
        summary = {
            "summary": "Diskusi Kina menghasilkan rancangan pembelajaran Stage 3 berbasis konteks Stage 1 dan tujuan Stage 2.",
            "key_decisions": [
                f"Pendekatan: {planning_state.get('strategy', {}).get('pendekatan_pembelajaran', '-')}",
                f"Model: {planning_state.get('strategy', {}).get('model_pembelajaran', '-')}",
                "Aktivitas utama diarahkan pada diskusi kelompok dan penyelesaian masalah kontekstual.",
            ],
            "chat_count": len(chats),
            "stage_3": planning_state.get("strategy", {}),
        }
        store.add_chat(
            project_id=project_id,
            role="assistant",
            message=summary["summary"],
            stage=3,
            metadata={"type": "summary", "summary": summary},
        )
        return summary
    # Menyimpan data
    def _deep_merge(self, old: Dict[str, Any], new: Dict[str, Any]) -> Dict[str, Any]:
        result = dict(old)

        for key, value in new.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value

        return result
    
    def _build_system_prompt(self) -> str:
        return """
Anda adalah Kina, AI Teaching Companion untuk guru Indonesia.
Tugas Anda adalah membantu guru menyusun Stage 3 Rancangan Pembelajaran.
Gunakan konteks Stage 1 dan Stage 2 yang diberikan.
Jawaban harus praktis, kontekstual, dan siap dipakai untuk LKPD atau Modul Ajar.

Tugas utama Anda:
1. Berdiskusi bertahap dengan guru untuk mengisi data Stage 3.
2. Ajukan hanya SATU pertanyaan dalam satu respons.
3. Simpan jawaban guru ke field Stage 3 yang sedang aktif.
4. Jika guru meminta rekomendasi, berikan 2–3 opsi yang relevan.
5. Jangan langsung menyimpan permintaan rekomendasi sebagai jawaban final.
6. Jika guru memilih salah satu opsi atau meminta AI memilihkan, simpan pilihan tersebut sebagai jawaban field aktif.
7. Setelah satu field selesai, lanjutkan ke field berikutnya.
8. Jika semua input utama sudah cukup, langsung hasilkan output AI Stage 3.
9. Jangan bertanya revisi.
10. Jangan meminta guru menjawab "tidak ada revisi".
11. Jangan langsung masuk Stage 4.
12. Jangan membuat dokumen final.

Field input Stage 3:
1. gaya_pembelajaran
2. preferensi_pedagogis
3. fasilitas_kelas
4. ketersediaan_teknologi
5. platform_digital
6. kemitraan
7. produk_kinerja_akhir

Output AI Stage 3 setelah data cukup:
1. praktik_pedagogis
2. alasan_pemilihan_praktik_pedagogis
3. bentuk_kemitraan_dan_peran_mitra
4. pemanfaatan_digital
5. fungsi_teknologi_digital
6. produk_kinerja_akhir

WAJIB kembalikan JSON valid tanpa markdown dengan struktur:
{
  "assistant_message": "jawaban natural untuk guru, singkat dan komunikatif",
  "structured_update": {
    "teacher_inputs": {},
    "ai_outputs": {},
    "progress": {
      "active_field": "nama_field_yang_sedang_ditanyakan_atau_null",
      "completed_fields": [],
      "is_ready_to_generate_outputs": false,
      "is_stage_3_complete": false,
      "is_ready_for_next_stage": false
    }
  },
  "missing_fields": [],
  "next_question": "pertanyaan lanjutan_atau_null"
}

Aturan penting:
- Jika terdapat data nama guru pada Stage 1, gunakan sapaan nama guru secara natural, misalnya "Baik Bu Hartini," tetapi jangan berlebihan.
- Gunakan data Stage 1 dan Stage 2 secara aktif, terutama jenjang, kelas, mata pelajaran, materi, kondisi kelas, tujuan pembelajaran, dan profil lulusan.
- Jika guru baru memulai Stage 3, tanyakan field pertama: gaya_pembelajaran.
- Jika guru menjawab field aktif dengan jelas, simpan ringkasan jawabannya ke structured_update.teacher_inputs.
- Jika field opsional tidak dijawab atau guru berkata tidak ada/tidak perlu, simpan nilai "Tidak digunakan" atau "Tidak ada preferensi khusus", lalu lanjut ke field berikutnya.
- Jika guru meminta rekomendasi, contoh, saran, alternatif, atau klarifikasi, simpan rekomendasi ke structured_update.temporary_recommendations dan pertahankan active_field yang sama.
- Jika guru memilih rekomendasi, simpan pilihan tersebut ke teacher_inputs dan lanjut ke field berikutnya.
- Jika guru meminta AI memilihkan, pilih opsi terbaik berdasarkan Stage 1, Stage 2, dan jawaban sebelumnya.
- Jika semua input utama sudah lengkap, langsung isi structured_update.ai_outputs.
- Setelah ai_outputs dibuat, tampilkan ringkasan output Stage 3 langsung di assistant_message.
- Jangan menulis "Apakah ada bagian yang ingin direvisi?"
- Jangan menulis "Jika tidak ada revisi..."
- Jangan menulis "Apakah ingin melanjutkan?"
- Setelah ai_outputs dibuat, set progress.active_field = null.
- Set progress.is_ready_to_generate_outputs = true.
- Set progress.is_stage_3_complete = true.
- Set progress.is_ready_for_next_stage = true.
- Set next_question = null.
- Akhiri assistant_message dengan kalimat persis:
"Terima kasih, data Anda sudah selesai dan siap digunakan untuk tahap berikutnya."
""".strip()
    
   
    def _build_stage_3_prompt(
        self,
        project: Dict[str, Any],
        planning_state: Dict[str, Any],
        chat_history: List[Dict[str, Any]],
        message_text: str,
    ) -> str:
        return f"""
Project:
{project}

Stage 1 - Konteks Dasar:
{planning_state.get('learning_brief', {})}

Stage 2 - CP, Tujuan Pembelajaran, Profil Lulusan, dan Lintas Disiplin:
{planning_state.get('curriculum', {})}

Stage 3 saat ini:
{planning_state.get('strategy', {})}

Urutan field Stage 3 yang harus didiskusikan:
{STAGE_3_FIELDS}

Riwayat chat terakhir:
{chat_history[-8:]}

Pesan guru terbaru:
{message_text}

Instruksi:
- Baca progress Stage 3 saat ini, terutama progress.active_field.
- Jika belum ada active_field atau Stage 3 baru dimulai, tanyakan field pertama yaitu gaya_pembelajaran.
- Jika pesan guru berupa jawaban final yang jelas, simpan ke structured_update.teacher_inputs[active_field].
- Jika pesan guru meminta rekomendasi, contoh, saran, alternatif, perbandingan, atau klarifikasi, jangan langsung menyimpan pesan itu sebagai jawaban final.
- Jika guru meminta rekomendasi, berikan 2–3 opsi yang relevan dengan Stage 1, Stage 2, jawaban sebelumnya, dan kondisi kelas.
- Simpan rekomendasi sementara ke structured_update.temporary_recommendations[active_field].
- Pertahankan progress.active_field pada field yang sama sampai guru memilih, menyetujui, atau meminta AI memilihkan.
- Jika guru memilih salah satu opsi, simpan pilihan tersebut ke teacher_inputs[active_field], lalu lanjut ke field berikutnya.
- Jika guru meminta AI memilihkan, pilih opsi terbaik, simpan ke teacher_inputs[active_field], lalu lanjut ke field berikutnya.
- Jika field aktif bersifat opsional dan guru menjawab tidak ada/tidak perlu, simpan "Tidak digunakan" atau "Tidak ada preferensi khusus", lalu lanjut ke field berikutnya.
- Ajukan hanya satu pertanyaan lanjutan dalam satu respons.
- Jangan isi semua field sekaligus kecuali guru memang memberikan semua data.

Jika semua teacher_inputs utama sudah lengkap:
- Langsung buat structured_update.ai_outputs Stage 3.
- Tampilkan hasil output Stage 3 secara ringkas dan rapi dalam assistant_message.
- Jangan bertanya revisi.
- Jangan meminta guru menjawab "tidak ada revisi".
- Jangan menulis "Apakah ada bagian yang ingin direvisi?"
- Jangan menulis "Jika tidak ada revisi..."
- Jangan menulis "Apakah ingin melanjutkan?"
- Set progress.active_field = null.
- Set progress.is_ready_to_generate_outputs = true.
- Set progress.is_stage_3_complete = true.
- Set progress.is_ready_for_next_stage = true.
- Set next_question = null.
- Akhiri assistant_message dengan kalimat persis:
"Terima kasih, data Anda sudah selesai dan siap digunakan untuk tahap berikutnya."
""".strip()

    def _manual_response(self) -> Dict[str, Any]:
        return {
            "assistant_message": "Baik, saya catat. AI generation dimatikan, jadi belum ada update Stage 3 otomatis.",
            "structured_update": {},
            "missing_fields": [],
            "next_question": "Aktifkan use_ai_generation untuk membuat rancangan Stage 3 otomatis.",
        }


kina_service = KinaService()
