from __future__ import annotations

from copy import deepcopy
from typing import Any

INTRA_DUMMY_ONBOARDING = {
    "school": {
        "schoolName": "SMPN 15 SURABAYA",
        "educationLevel": "SMP/MTs",
        "academicYear": "2025/2026",
    },
    "teacherProfile": {
        "teacherName": "Guru Demo",
        "gender": "",
    },
    "teacherClass": {
        "gradeLevel": "VII / Ganjil",
        "phase": "Fase D",
    },
    "teacherSubject": {
        "subject": "Matematika",
    },
}

def get_intra_dummy_onboarding_content() -> dict:
    return INTRA_DUMMY_ONBOARDING

INTRA_DUMMY_STAGE_1: dict[str, Any] = {
    "stageNumber": 1,
    "stageName": "Konteks Dasar Pembelajaran",
    "title": "Konteks Dasar Pembelajaran",
    "contentJson": {
        "jenjangPendidikan": "SMP / MTs",
        "fase": "Fase D",
        "kelas": "Kelas 7",
        "mataPelajaran": "Matematika",
        "topikMateriPokok": "Polinomial sederhana dalam konteks pola bilangan",
        "durasiPembelajaran": "3 pertemuan x 35 menit",
        "jumlahPertemuan": 3,
        "kondisiKelas": (
            "Kemampuan siswa beragam. Sebagian siswa aktif berdiskusi, "
            "tetapi masih membutuhkan contoh konkret dan arahan bertahap "
            "untuk memahami konsep aljabar."
        ),
        "karakteristikSiswa": [
            "Siswa menyukai aktivitas visual dan diskusi kelompok.",
            "Sebagian siswa membutuhkan contoh kontekstual sebelum masuk ke bentuk simbolik.",
            "Kemampuan literasi matematika siswa masih beragam.",
        ],
        "fasilitasAwal": [
            "Papan tulis",
            "HP siswa",
            "Internet terbatas",
            "Proyektor jika tersedia",
        ],
    },
}


INTRA_DUMMY_STAGE_2: dict[str, Any] = {
    "stageNumber": 2,
    "stageName": "Fondasi Tujuan Pembelajaran",
    "title": "CP, Dimensi Profil Lulusan, Lintas Disiplin, dan ATP",
    "contentJson": {
        "dimensiProfilLulusan": [
            "Penalaran Kritis",
            "Kolaborasi",
            "Kreativitas",
            "Komunikasi",
        ],
        "mataPelajaranLintasDisiplin": [
            "Bahasa Indonesia",
            "Informatika",
        ],
        "capaianPembelajaran": (
            "Peserta didik mampu memahami, merepresentasikan, dan menggunakan "
            "bentuk aljabar sederhana untuk menyelesaikan masalah kontekstual. "
            "Peserta didik dapat menjelaskan hubungan antarbesaran, menyusun "
            "bentuk simbolik sederhana, serta mengomunikasikan strategi penyelesaian "
            "secara lisan maupun tertulis."
        ),
        "alurTujuanPembelajaran": [
            {
                "order": 1,
                "selected": True,
                "tujuanPembelajaran": (
                    "Murid mampu mengenali bentuk aljabar dan unsur-unsurnya, "
                    "seperti variabel, koefisien, konstanta, dan suku."
                ),
                "rationale": (
                    "Tujuan ini menjadi dasar sebelum murid memahami operasi "
                    "dan penerapan polinomial sederhana."
                ),
            },
            {
                "order": 2,
                "selected": True,
                "tujuanPembelajaran": (
                    "Murid mampu menyusun bentuk polinomial sederhana dari "
                    "situasi kontekstual atau pola bilangan."
                ),
                "rationale": (
                    "Tujuan ini membantu murid menghubungkan konteks nyata "
                    "dengan representasi simbolik matematika."
                ),
            },
            {
                "order": 3,
                "selected": True,
                "tujuanPembelajaran": (
                    "Murid mampu melakukan operasi penjumlahan dan pengurangan "
                    "polinomial sederhana secara tepat."
                ),
                "rationale": (
                    "Tujuan ini mengembangkan keterampilan prosedural setelah "
                    "murid memahami makna bentuk aljabar."
                ),
            },
            {
                "order": 4,
                "selected": False,
                "tujuanPembelajaran": (
                    "Murid mampu membuat produk sederhana yang menunjukkan "
                    "penerapan polinomial dalam konteks nyata."
                ),
                "rationale": (
                    "Tujuan ini dapat digunakan sebagai pengayaan jika waktu "
                    "pembelajaran memungkinkan."
                ),
            },
        ],
        "tujuanPembelajaranTerpilih": [
            "Murid mampu mengenali bentuk aljabar dan unsur-unsurnya.",
            "Murid mampu menyusun bentuk polinomial sederhana dari konteks atau pola bilangan.",
            "Murid mampu melakukan operasi penjumlahan dan pengurangan polinomial sederhana.",
        ],
        "pertanyaanPemantik": (
            "Bagaimana pola bilangan dapat dituliskan dalam bentuk aljabar "
            "atau polinomial sederhana?"
        ),
    },
}


INTRA_DUMMY_STAGE_4: dict[str, Any] = {
    "stageNumber": 4,
    "stageName": "Penilaian Dukungan Pelaksanaan",
    "title": "Asesmen Formatif",
    "contentJson": {
        "assessmentType": "formatif",
        "availableTechniques": [
            {
                "key": "tes_tertulis",
                "label": "Tes Tertulis",
                "description": "Soal pilihan ganda, isian, uraian",
            },
            {
                "key": "portofolio",
                "label": "Portofolio",
                "description": "Kumpulan karya siswa",
            },
        ],
        "meetings": [
            {
                "meetingOrder": 1,
                "meetingTitle": "Pertemuan 1 — Pembukaan Pembelajaran",
                "selectedTechnique": "tes_tertulis",
                "selectedTechniqueLabel": "Tes Tertulis",
                "description": "Guru menggunakan soal singkat untuk mengecek pemahaman awal siswa.",
            },
            {
                "meetingOrder": 2,
                "meetingTitle": "Pertemuan 2 — Diskusi dan Latihan Kelompok",
                "selectedTechnique": "portofolio",
                "selectedTechniqueLabel": "Portofolio",
                "description": "Guru menilai kumpulan hasil kerja kelompok dan catatan penyelesaian siswa.",
            },
            {
                "meetingOrder": 3,
                "meetingTitle": "Pertemuan 3 — Presentasi dan Refleksi",
                "selectedTechnique": "tes_tertulis",
                "selectedTechniqueLabel": "Tes Tertulis",
                "description": "Guru menggunakan soal tertulis untuk mengecek pemahaman akhir siswa.",
            },
        ],
    },
}


INTRA_DUMMY_SUMMATIVE_ASSESSMENT: dict[str, Any] = {
    "type": "tes_tertulis",
    "title": "Asesmen Sumatif Pemahaman Polinomial Sederhana",
    "description": (
        "Tes tertulis singkat digunakan untuk mengukur pemahaman murid terhadap "
        "unsur bentuk aljabar, penyusunan polinomial sederhana, serta operasi "
        "penjumlahan dan pengurangan polinomial sederhana."
    ),
    "sampleQuestions": [
        "Tentukan variabel, koefisien, dan konstanta dari bentuk 3x + 5.",
        "Sederhanakan bentuk 2x + 3x - 4.",
        "Buat satu contoh situasi sederhana yang dapat ditulis dalam bentuk aljabar.",
    ],
}


INTRA_DUMMY_RUBRIC: dict[str, Any] = {
    "criteria": [
        {
            "name": "Pemahaman konsep",
            "excellent": "Mampu menjelaskan unsur polinomial dengan tepat dan memberi contoh.",
            "good": "Mampu menjelaskan sebagian besar unsur polinomial dengan benar.",
            "needsSupport": "Masih membutuhkan bantuan untuk mengenali unsur polinomial.",
        },
        {
            "name": "Ketepatan prosedur",
            "excellent": "Mampu menyelesaikan operasi sederhana dengan langkah runtut dan tepat.",
            "good": "Mampu menyelesaikan sebagian besar soal dengan benar.",
            "needsSupport": "Masih keliru dalam langkah operasi atau penyederhanaan.",
        },
        {
            "name": "Kolaborasi",
            "excellent": "Aktif membantu kelompok dan menyampaikan pendapat dengan jelas.",
            "good": "Berpartisipasi dalam kelompok meskipun belum konsisten.",
            "needsSupport": "Masih perlu didorong untuk terlibat dalam kerja kelompok.",
        },
    ]
}

def get_intra_dummy_stages() -> list[dict[str, Any]]:
    return [
        deepcopy(INTRA_DUMMY_STAGE_1),
        deepcopy(INTRA_DUMMY_STAGE_2),
        deepcopy(INTRA_DUMMY_STAGE_4),
    ]


def get_intra_dummy_stage_content(stage_number: int) -> dict[str, Any]:
    mapping = {
        1: INTRA_DUMMY_STAGE_1["contentJson"],
        2: INTRA_DUMMY_STAGE_2["contentJson"],
        4: INTRA_DUMMY_STAGE_4["contentJson"],
    }
    return deepcopy(mapping.get(stage_number, {}))


def get_intra_dummy_summative_assessment() -> dict[str, Any]:
    return deepcopy(INTRA_DUMMY_SUMMATIVE_ASSESSMENT)


def get_intra_dummy_rubric() -> dict[str, Any]:
    return deepcopy(INTRA_DUMMY_RUBRIC)
