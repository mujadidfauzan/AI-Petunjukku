from __future__ import annotations

from typing import Any, Dict, List

from app.data_store import now_iso, store


STAGE_4_DEFAULT_OPTIONS = {
    "jenis_asesmen": ["Formatif", "Sumatif", "Diagnostik"],
    "teknik_penilaian": ["Observasi diskusi", "Penilaian LKPD", "Presentasi kelompok", "Tes singkat"],
    "alat_bahan": ["LKPD", "Papan tulis", "Kartu soal", "Kalkulator sederhana", "Proyektor"],
    "media_pembelajaran": ["Tabel perbandingan", "Contoh kasus harga barang", "Slide singkat"],
}


class Stage4Service:
    def get_options(self) -> Dict[str, Any]:
        return STAGE_4_DEFAULT_OPTIONS

    def save_assessment(
        self,
        project_id: str,
        jenis_asesmen: str,
        teknik_penilaian: List[str],
        alat_bahan: List[str],
        media_pembelajaran: List[str],
        refleksi_siswa: str,
        refleksi_guru: str,
    ) -> Dict[str, Any]:
        planning_state = store.get_planning_state(project_id)
        assessment = {
            "jenis_asesmen": jenis_asesmen,
            "teknik_penilaian": teknik_penilaian,
            "alat_bahan": alat_bahan,
            "media_pembelajaran": media_pembelajaran,
            "refleksi_siswa": refleksi_siswa,
            "refleksi_guru": refleksi_guru,
            "rubrik_penilaian": [
                {
                    "aspek": "Pemahaman konsep",
                    "indikator": "Siswa mampu menjelaskan hubungan dua besaran senilai.",
                    "level": ["Perlu bimbingan", "Cukup", "Baik", "Sangat baik"],
                },
                {
                    "aspek": "Kolaborasi",
                    "indikator": "Siswa aktif berdiskusi dan berbagi tugas dalam kelompok.",
                    "level": ["Perlu bimbingan", "Cukup", "Baik", "Sangat baik"],
                },
                {
                    "aspek": "Penyelesaian masalah",
                    "indikator": "Siswa mampu menyelesaikan masalah perbandingan senilai secara tepat.",
                    "level": ["Perlu bimbingan", "Cukup", "Baik", "Sangat baik"],
                },
            ],
        }
        planning_state["assessment"] = assessment
        planning_state["ai_logs"].append(
            {
                "stage": 4,
                "action": "save_assessment_options",
                "created_at": now_iso(),
            }
        )
        store.save_planning_state(project_id, planning_state)
        return assessment


stage4_service = Stage4Service()
