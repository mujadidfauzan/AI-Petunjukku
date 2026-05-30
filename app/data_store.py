from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# DUMMY_STAGE_1 = {
#     "Nama Sekolah": "SMP Muhammadiyah",
#     "Nama guru": "Bu Hartini",
#     "Jenjang": "SMP",
#     "fase_pendidikan": "Fase D",
#     "kelas": "Kelas 7",
#     "mapel_utama": "Matematika",
#     "mapel_kolaborasi": None,
#     "Materi pokok bahasa" : "bilangan Polinominal",
#     "durasi_pembelajaran": "2 JP",
#     "Jumlah pertemuan" : "2"
#     "karakter_siswa": "Kemampuan siswa beragam dan perlu aktivitas kelompok.",
#     "lokasi_sekolah": "Lingkungan sekolah perkotaan",
#     "pemindaian_lingkungan": "Lingkungan sekitar memiliki banyak contoh transaksi jual beli yang bisa dijadikan konteks perbandingan senilai.",
#     "pemantauan_risiko": "Sebagian siswa mungkin masih bingung membedakan perbandingan senilai dan tidak senilai.",
# }
DUMMY_STAGE_1 = {
    "Nama Sekolah": "SMP Muhammadiyah",
    "Nama guru": "Bu Hartini",
    "Jenjang": "SMP",
    "fase_pendidikan": "Fase D",
    "kelas": "Kelas 7",
    "mapel_utama": "Matematika",
    "mapel_kolaborasi": None,
    "Materi pokok bahasa" : "bilangan Polinominal",
    "durasi_pembelajaran": "2 JP",
    "Jumlah pertemuan" : "2",
    "kondisi_kelas": "Kemampuan siswa beragam dan perlu aktivitas kelompok.",
}

# DUMMY_STAGE_2 = {
#     "tujuan_pembelajaran": "Siswa dapat memahami konsep perbandingan senilai dan menyelesaikan masalah sehari-hari yang berkaitan dengan rasio.",
#     "kompetensi_diharapkan": "Siswa mampu mengidentifikasi hubungan dua besaran yang senilai dan menggunakan tabel/rasio untuk menyelesaikan masalah.",
#     "outcome_pembelajaran": "Siswa menghasilkan penyelesaian masalah kontekstual tentang perbandingan senilai secara berkelompok.",
#     "profil_pelajar_pancasila": ["Bernalar kritis", "Gotong royong"],
#     "catatan_khusus": "Gunakan contoh dekat dengan kehidupan siswa dan aktivitas kelompok sederhana.",
#     "validasi_mapel_fase": "Matematika Fase D sesuai untuk topik perbandingan senilai.",
#     "cp_tp_relevan": [
#         "Peserta didik dapat menggunakan rasio dan proporsi untuk menyelesaikan masalah kontekstual.",
#         "Peserta didik dapat merepresentasikan hubungan antarbesaran dalam tabel atau bentuk sederhana."
#     ],
# }

DUMMY_STAGE_2 = {
    "stage": 2,
    "title": "CP, Tujuan Pembelajaran, Profil Lulusan, dan Lintas Disiplin",
    "template_section": "B. Profil dan Arah Pembelajaran",

    "fields": {
        "capaian_pembelajaran": {
            "label": "Capaian Pembelajaran",
            "required": True,
            "source": "dummy_manual",
            "input_type": "text",
            "discussion_with_ai": False,
            "value": (
                "Peserta didik mampu menggunakan rasio dan proporsi untuk "
                "menyelesaikan masalah kontekstual serta merepresentasikan "
                "hubungan antarbesaran dalam bentuk tabel atau perbandingan sederhana."
            ),
        },

        "cp_terpilih": {
            "label": "CP terpilih",
            "required": True,
            "source": "dummy_manual",
            "input_type": "text",
            "discussion_with_ai": False,
            "value": (
                "Peserta didik dapat memahami dan menggunakan konsep perbandingan "
                "senilai dalam situasi sehari-hari, seperti hubungan jumlah barang "
                "dan harga."
            ),
        },

        "profil_lulusan": {
            "label": "Profil lulusan",
            "required": True,
            "source": "ai_recommendation_dummy",
            "input_type": "multi_choice",
            "discussion_with_ai": True,
            "ai_recommendations": [
                "Bernalar kritis",
                "Gotong royong",
                "Kreatif",
            ],
            "value": [
                "Bernalar kritis",
                "Gotong royong",
            ],
        },

        "preferensi_lintas_disiplin": {
            "label": "Preferensi lintas disiplin",
            "required": False,
            "source": "ai_discussion_dummy",
            "input_type": "chatbot_discussion",
            "discussion_with_ai": True,
            "ai_recommendations": [
                "IPS melalui konteks transaksi jual beli.",
                "Bahasa Indonesia melalui penjelasan tertulis hasil diskusi.",
                "Informatika melalui pembuatan tabel sederhana.",
            ],
            "value": "IPS melalui konteks transaksi jual beli di kantin atau koperasi sekolah.",
        },

        "konteks_lokal": {
            "label": "Konteks lokal",
            "required": False,
            "source": "teacher_or_chatbot_dummy",
            "input_type": "chatbot_discussion",
            "discussion_with_ai": True,
            "value": (
                "Lingkungan sekolah memiliki contoh transaksi jual beli seperti "
                "kantin, koperasi sekolah, dan toko sekitar sekolah."
            ),
        },

        "target_hasil_murid": {
            "label": "Target hasil murid",
            "required": True,
            "source": "ai_generated_editable_dummy",
            "input_type": "editable_text",
            "discussion_with_ai": True,
            "value": (
                "Setelah pembelajaran, murid mampu mengenali situasi perbandingan "
                "senilai, menyelesaikan masalah menggunakan rasio, dan menjelaskan "
                "strategi penyelesaiannya secara sederhana."
            ),
        },
    },

    "ai_outputs": {
        "tujuan_pembelajaran_utama": (
            "Murid mampu memahami konsep perbandingan senilai dan menerapkannya "
            "untuk menyelesaikan masalah sehari-hari."
        ),
        "tujuan_pembelajaran_turunan": [
            "Murid mampu mengidentifikasi hubungan dua besaran yang senilai.",
            "Murid mampu menyajikan hubungan dua besaran dalam bentuk tabel.",
            "Murid mampu menentukan nilai yang belum diketahui menggunakan rasio.",
        ],
        "kriteria_ketercapaian_tujuan_pembelajaran": [
            "Murid dapat membedakan contoh perbandingan senilai dan bukan senilai.",
            "Murid dapat melengkapi tabel perbandingan senilai dengan benar.",
            "Murid dapat menyelesaikan soal kontekstual perbandingan senilai.",
        ],
    },

    "chatbot_discussion_plan": {
        "can_be_discussed_with_ai": True,
        "discussion_fields": [
            "profil_lulusan",
            "preferensi_lintas_disiplin",
            "konteks_lokal",
            "target_hasil_murid",
        ],
        "example_questions": [
            "Saya menyarankan profil lulusan bernalar kritis dan gotong royong. Apakah ingin memakai ini atau diganti?",
            "Materi ini bisa dikaitkan dengan IPS, Bahasa Indonesia, atau Informatika. Mau pilih yang mana?",
            "Apakah ada konteks lokal dari sekolah atau lingkungan sekitar yang ingin dimasukkan?",
            "Apakah target hasil murid ini sudah sesuai, atau ingin dibuat lebih sederhana?"
        ],
    },

    # Compatibility sementara untuk kode lama.
    # Jangan dihapus dulu karena ai_generation_service.py masih membaca key ini.
    "tujuan_pembelajaran": (
        "Murid mampu memahami konsep perbandingan senilai dan menerapkannya "
        "untuk menyelesaikan masalah sehari-hari."
    ),
    "profil_pelajar_pancasila": [
        "Bernalar kritis",
        "Gotong royong",
    ],
}


def empty_planning_state() -> Dict[str, Any]:
    return {
        "learning_brief": deepcopy(DUMMY_STAGE_1),
        "curriculum": deepcopy(DUMMY_STAGE_2),
        "strategy": {},
        "assessment": {},
        "review": {},
        "generated_documents": {},
        "content_json": {},
        "content_markdown": "",
        "ai_logs": [],
    }


class InMemoryDataStore:
    """Database sementara untuk MVP terminal. Ganti class ini dengan repository Supabase/Postgres saat production."""

    def __init__(self) -> None:
        self.projects: Dict[str, Dict[str, Any]] = {
            "demo-project-001": {
                "id": "demo-project-001",
                "title": "LKPD Matematika Perbandingan Senilai",
                "rpp_type": "intrakurikuler",
                "subject": "Matematika",
                "phase": "Fase D",
                "grade_level": "Kelas 7",
                "status": "in_progress",
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
        }
        self.planning_states: Dict[str, Dict[str, Any]] = {
            "demo-project-001": empty_planning_state()
        }
        self.chats: Dict[str, List[Dict[str, Any]]] = {"demo-project-001": []}
        self.generated_documents: Dict[str, Dict[str, Any]] = {}

    def get_project(self, project_id: str) -> Dict[str, Any]:
        if project_id not in self.projects:
            self.projects[project_id] = {
                "id": project_id,
                "title": "Project Baru",
                "rpp_type": "intrakurikuler",
                "subject": "Matematika",
                "phase": "Fase D",
                "grade_level": "Kelas 7",
                "status": "in_progress",
                "created_at": now_iso(),
                "updated_at": now_iso(),
            }
        return self.projects[project_id]

    def get_planning_state(self, project_id: str) -> Dict[str, Any]:
        if project_id not in self.planning_states:
            self.planning_states[project_id] = empty_planning_state()
        return self.planning_states[project_id]

    def save_planning_state(self, project_id: str, planning_state: Dict[str, Any]) -> Dict[str, Any]:
        planning_state["updated_at"] = now_iso()
        self.planning_states[project_id] = planning_state
        return planning_state

    def add_chat(self, project_id: str, role: str, message: str, stage: int, metadata: Dict[str, Any] | None = None) -> Dict[str, Any]:
        chat = {
            "id": f"chat-{len(self.chats.get(project_id, [])) + 1}",
            "project_id": project_id,
            "role": role,
            "message": message,
            "stage": stage,
            "metadata": metadata or {},
            "created_at": now_iso(),
        }
        self.chats.setdefault(project_id, []).append(chat)
        return chat

    def get_chats(self, project_id: str) -> List[Dict[str, Any]]:
        return self.chats.get(project_id, [])

    def save_generated_document(self, project_id: str, output_type: str, document: Dict[str, Any]) -> Dict[str, Any]:
        doc_id = f"generated-{project_id}-{output_type}"
        payload = {
            "id": doc_id,
            "project_id": project_id,
            "output_type": output_type,
            "content_json": document,
            "created_at": now_iso(),
        }
        self.generated_documents[doc_id] = payload
        self.projects[project_id]["status"] = "generated"
        self.projects[project_id]["updated_at"] = now_iso()
        return payload


store = InMemoryDataStore()
