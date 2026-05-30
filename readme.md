# Petunjukku AI Service

Petunjukku AI Service adalah backend berbasis **FastAPI** yang bertanggung jawab untuk menjalankan proses AI pada aplikasi Petunjukku, seperti **RAG retrieval**, **AI recommendation**, **Kina Chat**, **summary chat**, dan **generate teks RPP**.

Service ini **tidak dipanggil langsung oleh frontend**. Frontend Next.js hanya berkomunikasi dengan **NestJS Application Backend**. NestJS kemudian memanggil FastAPI melalui internal API.

FastAPI **tidak bertanggung jawab membuat file PDF atau DOCX**. FastAPI hanya menghasilkan teks atau JSON terstruktur dari LLM. Proses memasukkan hasil AI ke template PDF/DOCX dilakukan oleh NestJS atau frontend menggunakan template dokumen yang sudah dibuat oleh tim.

---

## 1. Posisi AI Service dalam Arsitektur Petunjukku

Arsitektur utama Petunjukku:

```text
Next.js Frontend
↓
NestJS Application Backend
↓
FastAPI AI Service
↓
FAISS / RAG / LLM
```

Pembagian tanggung jawab:

| Komponen            | Tanggung Jawab                                                           |
| ------------------- | ------------------------------------------------------------------------ |
| Next.js             | UI, form stage, preview RPP, export action                               |
| NestJS              | Auth, user, teacher profile, RPP project, stage, database, orchestration |
| Supabase PostgreSQL | Penyimpanan data aplikasi                                                |
| FastAPI             | AI recommendation, RAG, Kina Chat, generate teks RPP                     |
| FAISS               | Vector search dokumen Capaian Pembelajaran                               |
| LLM API             | Generate rekomendasi, jawaban chat, dan teks RPP                         |

---

## 2. Prinsip Utama AI Service

AI Service mengikuti prinsip berikut:

1. **FastAPI hanya dipanggil oleh NestJS**, bukan oleh frontend.
2. **FastAPI tidak menyimpan data utama aplikasi** seperti project RPP, stage, chat, atau hasil generated RPP.
3. **FastAPI tidak membuat file PDF/DOCX**.
4. **FastAPI hanya mengembalikan hasil AI berupa teks atau JSON terstruktur**.
5. **NestJS yang menyimpan hasil AI ke Supabase**.
6. **Guru tetap melakukan review/edit sebelum hasil AI disimpan sebagai bagian final RPP**.

---

## 3. Fungsi Utama FastAPI

FastAPI AI Service memiliki beberapa fungsi utama:

### 3.1 RAG Retrieval

Mengambil referensi Capaian Pembelajaran dari dokumen resmi menggunakan embedding dan FAISS.

Contoh penggunaan:

- mencari CP berdasarkan fase dan mata pelajaran,
- mengambil referensi CP untuk Stage 2,
- mengambil konteks resmi untuk generate RPP,
- memberi dasar referensi pada Kina Chat.

---

### 3.2 AI Recommendation

Membuat rekomendasi isian stage RPP.

Contoh:

- rekomendasi Tujuan Pembelajaran dari Capaian Pembelajaran,
- rekomendasi aktivitas pembelajaran,
- rekomendasi asesmen,
- rekomendasi rubrik,
- rekomendasi diferensiasi,
- rekomendasi pertanyaan pemantik.

Contoh kasus utama:

```text
Stage 2 Intrakurikuler
↓
RAG mencari Capaian Pembelajaran
↓
LLM membuat rekomendasi Tujuan Pembelajaran
↓
FastAPI return JSON rekomendasi
↓
NestJS return ke frontend
↓
Guru review/edit
↓
Hasil final disimpan ke rpp_stages.content_json
```

---

### 3.3 Kina Chat

Menghasilkan jawaban chatbot Kina berdasarkan konteks project RPP, stage yang sudah diisi, profil guru, kelas, dan chat history.

FastAPI hanya menghasilkan jawaban. Penyimpanan chat ke tabel `kina_chats` dilakukan oleh NestJS.

---

### 3.4 Summarize Kina Chat

Merangkum diskusi Kina menjadi JSON terstruktur agar dapat disimpan sebagai bagian dari Stage 3.

Contoh hasil summary:

- ringkasan diskusi,
- strategi pembelajaran,
- alur kegiatan,
- rencana diferensiasi,
- fokus asesmen,
- kendala dan mitigasi.

---

### 3.5 Generate Final RPP Text

Membuat teks final RPP berdasarkan:

- data project,
- profil guru,
- sekolah,
- kelas,
- mapel,
- stage 1–5,
- hasil diskusi Kina,
- referensi CP dari RAG.

FastAPI mengembalikan:

```text
contentJson
contentMarkdown
usedReferences
model
```

FastAPI tidak membuat file dokumen. File PDF/DOCX dibuat setelah data ini dimasukkan ke template oleh sistem utama.

---

## 4. Struktur Folder Repo

Struktur folder yang disarankan:

```text
petunjukku-ai-service/
├── app/
│   ├── main.py
│   ├── core/
│   │   ├── config.py
│   │   ├── security.py
│   │   └── logging.py
│   ├── routers/
│   │   ├── health.py
│   │   ├── rag.py
│   │   └── ai.py
│   ├── schemas/
│   │   ├── common_schema.py
│   │   ├── rag_schema.py
│   │   ├── recommendation_schema.py
│   │   ├── kina_schema.py
│   │   └── generate_rpp_schema.py
│   ├── services/
│   │   ├── rag_service.py
│   │   ├── embedding_service.py
│   │   ├── faiss_service.py
│   │   ├── cp_reference_service.py
│   │   ├── prompt_builder_service.py
│   │   ├── recommendation_service.py
│   │   ├── kina_ai_service.py
│   │   ├── kina_summary_service.py
│   │   ├── rpp_generation_service.py
│   │   └── llm_client.py
│   ├── utils/
│   │   ├── json_parser.py
│   │   ├── text_cleaner.py
│   │   └── file_utils.py
│   └── data/
│       ├── raw_documents/
│       ├── processed_chunks/
│       └── vector_store/
│           ├── cp.index
│           └── cp_metadata.json
├── tests/
│   ├── test_health.py
│   ├── test_rag.py
│   └── test_recommendation.py
├── .env
├── .env.example
├── requirements.txt
├── README.md
└── run.py
```

---

## 5. Penjelasan Folder

### `app/main.py`

Entry point utama FastAPI.

Tugas:

- membuat instance FastAPI,
- mendaftarkan router,
- mengatur startup event,
- memuat FAISS index jika tersedia,
- menjalankan konfigurasi global.

---

### `app/core/`

Berisi konfigurasi utama aplikasi.

| File          | Fungsi                                |
| ------------- | ------------------------------------- |
| `config.py`   | Membaca environment variable          |
| `security.py` | Validasi internal API key dari NestJS |
| `logging.py`  | Konfigurasi logging aplikasi          |

---

### `app/routers/`

Berisi endpoint FastAPI.

| File        | Endpoint                                                                                                                  |
| ----------- | ------------------------------------------------------------------------------------------------------------------------- |
| `health.py` | `/internal/health`                                                                                                        |
| `rag.py`    | `/internal/rag/search`, `/internal/rag/index-documents`, `/internal/rag/references`                                       |
| `ai.py`     | `/internal/ai/recommend-stage`, `/internal/ai/kina-chat`, `/internal/ai/summarize-kina-chat`, `/internal/ai/generate-rpp` |

---

### `app/schemas/`

Berisi Pydantic schema untuk validasi request dan response.

| File                       | Fungsi                                                     |
| -------------------------- | ---------------------------------------------------------- |
| `common_schema.py`         | Schema umum seperti project, teacher, school, class, stage |
| `rag_schema.py`            | Schema RAG search dan RAG references                       |
| `recommendation_schema.py` | Schema rekomendasi stage                                   |
| `kina_schema.py`           | Schema Kina Chat dan summary                               |
| `generate_rpp_schema.py`   | Schema generate final RPP text                             |

---

### `app/services/`

Berisi business logic AI.

| File                        | Fungsi                                                 |
| --------------------------- | ------------------------------------------------------ |
| `rag_service.py`            | Mengatur proses retrieval CP                           |
| `embedding_service.py`      | Membuat embedding query dan dokumen                    |
| `faiss_service.py`          | Load, search, dan update FAISS index                   |
| `cp_reference_service.py`   | Mengambil metadata CP dari database atau metadata file |
| `prompt_builder_service.py` | Menyusun prompt LLM                                    |
| `recommendation_service.py` | Membuat rekomendasi isian stage                        |
| `kina_ai_service.py`        | Membuat jawaban chatbot Kina                           |
| `kina_summary_service.py`   | Merangkum diskusi Kina                                 |
| `rpp_generation_service.py` | Generate teks final RPP                                |
| `llm_client.py`             | Client untuk Gemini/OpenRouter/LLM API                 |

---

### `app/data/`

Berisi dokumen dan vector store.

| Folder              | Fungsi                                 |
| ------------------- | -------------------------------------- |
| `raw_documents/`    | Dokumen PDF asli seperti CP pemerintah |
| `processed_chunks/` | Hasil chunking dokumen                 |
| `vector_store/`     | FAISS index dan metadata vector        |

---

## 6. Environment Variable

Buat file `.env` berdasarkan `.env.example`.

Contoh:

```env
APP_NAME="Petunjukku AI Service"
APP_ENV="development"
APP_PORT=8000

INTERNAL_API_KEY="change-this-internal-key"

LLM_PROVIDER="openrouter"
OPENROUTER_API_KEY="your-openrouter-api-key"
GEMINI_API_KEY="your-gemini-api-key"
LLM_MODEL="gemini-1.5-flash"

EMBEDDING_MODEL_NAME="sentence-transformers/all-MiniLM-L6-v2"

SUPABASE_URL="https://your-project.supabase.co"
SUPABASE_SERVICE_ROLE_KEY="your-service-role-key"

FAISS_INDEX_PATH="app/data/vector_store/cp.index"
FAISS_METADATA_PATH="app/data/vector_store/cp_metadata.json"
```

Catatan:

- `INTERNAL_API_KEY` dipakai untuk melindungi endpoint internal.
- `SUPABASE_SERVICE_ROLE_KEY` hanya boleh dipakai di backend.
- Jangan commit `.env` ke repository.
- Jika RAG metadata disimpan dalam file lokal, `SUPABASE_SERVICE_ROLE_KEY` belum wajib dipakai pada tahap dummy/MVP awal.

---

## 7. Endpoint FastAPI

Semua endpoint menggunakan prefix `/internal`.

---

# 7.1 Health Check

## `GET /internal/health`

Endpoint untuk mengecek apakah AI Service berjalan.

### Response

```json
{
  "status": "ok",
  "service": "petunjukku-ai-service",
  "rag": "ok",
  "llm": "configured"
}
```

---

# 7.2 RAG Search

## `POST /internal/rag/search`

Endpoint untuk mencari referensi Capaian Pembelajaran.

### Request

```json
{
  "query": "Sistem Pencernaan Manusia kelas 7 IPA",
  "subject": "IPA",
  "phase": "Fase D",
  "gradeLevel": "Kelas 7",
  "topK": 5
}
```

### Response

```json
{
  "references": [
    {
      "cpReferenceId": "uuid",
      "sourceTitle": "Capaian Pembelajaran IPA Fase D",
      "documentType": "capaian_pembelajaran",
      "phase": "Fase D",
      "subject": "IPA",
      "element": "Pemahaman IPA",
      "chunkText": "Peserta didik mampu mengidentifikasi sistem organ...",
      "similarityScore": 0.87,
      "metadata": {
        "page": 12,
        "fileName": "CP_IPA_Fase_D.pdf"
      }
    }
  ]
}
```

---

# 7.3 AI Stage Recommendation

## `POST /internal/ai/recommend-stage`

Endpoint untuk membuat rekomendasi isian stage RPP.

Contoh penggunaan:

- Stage 2 Intrakurikuler: rekomendasi Tujuan Pembelajaran dari CP.
- Stage 4 Intrakurikuler: rekomendasi asesmen dan rubrik.
- Stage 2 PjBL: rekomendasi tujuan proyek dan aktivitas awal.

### Request

```json
{
  "project": {
    "id": "uuid",
    "title": "RPP Sistem Pencernaan Manusia",
    "rppType": "intrakurikuler",
    "subject": "IPA",
    "phase": "Fase D",
    "gradeLevel": "Kelas 7"
  },
  "teacherProfile": {
    "fullName": "Budi Santoso",
    "position": "Guru IPA",
    "educationLevel": "SMP"
  },
  "school": {
    "name": "SMP Negeri 1 Bandung",
    "province": "Jawa Barat",
    "city": "Bandung",
    "schoolEnvironment": "Sekolah berada di area perkotaan.",
    "availableFacilities": ["Proyektor", "Laboratorium IPA"],
    "localContext": "Siswa familiar dengan isu kesehatan sehari-hari."
  },
  "teacherClass": {
    "className": "7A",
    "gradeLevel": "Kelas 7",
    "studentCount": 32,
    "studentCharacteristics": "Siswa aktif dan suka aktivitas visual.",
    "learningChallenges": ["Kemampuan literasi beragam"],
    "dominantLearningStyle": "visual dan praktik"
  },
  "previousStages": [
    {
      "stageNumber": 1,
      "stageName": "Konteks Dasar Pembelajaran",
      "contentJson": {
        "topic": "Sistem Pencernaan Manusia",
        "timeAllocation": "2 JP"
      }
    }
  ],
  "targetStage": {
    "stageNumber": 2,
    "stageName": "Tujuan Pembelajaran",
    "recommendationType": "learning_objectives",
    "topic": "Sistem Pencernaan Manusia"
  },
  "options": {
    "topK": 5,
    "language": "id",
    "outputFormat": "json"
  }
}
```

### Response

```json
{
  "recommendationType": "learning_objectives",
  "targetStageNumber": 2,
  "ragReferences": [
    {
      "cpReferenceId": "uuid",
      "sourceTitle": "Capaian Pembelajaran IPA Fase D",
      "chunkText": "Peserta didik mampu mengidentifikasi sistem organ...",
      "similarityScore": 0.87
    }
  ],
  "recommendations": {
    "capaianPembelajaranSummary": "CP yang relevan berkaitan dengan pemahaman sistem organ dan fungsinya.",
    "learningObjectives": [
      "Peserta didik mampu mengidentifikasi organ-organ pada sistem pencernaan manusia.",
      "Peserta didik mampu menjelaskan fungsi organ pencernaan manusia secara runtut.",
      "Peserta didik mampu menghubungkan proses pencernaan dengan pentingnya menjaga kesehatan tubuh."
    ],
    "suggestedEssentialQuestion": "Bagaimana makanan yang kita konsumsi diproses oleh tubuh menjadi energi?",
    "reasoningSummary": "Tujuan pembelajaran disusun berdasarkan CP IPA Fase D dan disesuaikan dengan topik sistem pencernaan manusia untuk kelas 7."
  }
}
```

Catatan:

Endpoint ini tidak menyimpan hasil rekomendasi ke database. Hasil akan ditampilkan kepada guru untuk direview, diedit, lalu disimpan oleh NestJS ke `rpp_stages.content_json`.

---

# 7.4 Kina Chat

## `POST /internal/ai/kina-chat`

Endpoint untuk menghasilkan respons chatbot Kina.

### Request

```json
{
  "project": {
    "id": "uuid",
    "title": "RPP Sistem Pencernaan Manusia",
    "rppType": "intrakurikuler",
    "subject": "IPA",
    "phase": "Fase D",
    "gradeLevel": "Kelas 7"
  },
  "stages": [
    {
      "stageNumber": 1,
      "stageName": "Konteks Dasar Pembelajaran",
      "contentJson": {}
    },
    {
      "stageNumber": 2,
      "stageName": "Tujuan Pembelajaran",
      "contentJson": {}
    }
  ],
  "chatHistory": [
    {
      "role": "user",
      "message": "Saya ingin aktivitas pembelajaran yang lebih visual."
    },
    {
      "role": "assistant",
      "message": "Baik, kita bisa menggunakan gambar organ pencernaan dan diskusi kelompok."
    }
  ],
  "message": "Bagaimana cara membuat kegiatan inti yang cocok untuk siswa saya?"
}
```

### Response

```json
{
  "reply": "Untuk kelas 7A yang aktif dan menyukai aktivitas visual, kegiatan inti bisa dimulai dengan pengamatan gambar sistem pencernaan, lalu siswa mengisi tabel organ dan fungsi dalam kelompok kecil.",
  "usedReferences": [
    {
      "cpReferenceId": "uuid",
      "sourceTitle": "Capaian Pembelajaran IPA Fase D",
      "similarityScore": 0.84
    }
  ],
  "suggestedFollowUpQuestions": ["Apakah kegiatan ini ingin dibuat dalam bentuk diskusi kelompok?", "Apakah guru ingin menambahkan kuis singkat di akhir?"]
}
```

Catatan:

FastAPI hanya menghasilkan jawaban. Penyimpanan chat dilakukan oleh NestJS ke tabel `kina_chats`.

---

# 7.5 Summarize Kina Chat

## `POST /internal/ai/summarize-kina-chat`

Endpoint untuk merangkum percakapan Kina menjadi JSON terstruktur.

### Request

```json
{
  "project": {
    "id": "uuid",
    "rppType": "intrakurikuler",
    "subject": "IPA",
    "phase": "Fase D",
    "gradeLevel": "Kelas 7"
  },
  "chatHistory": [
    {
      "role": "user",
      "message": "Saya ingin pembelajaran yang visual."
    },
    {
      "role": "assistant",
      "message": "Gunakan gambar sistem pencernaan dan tabel organ-fungsi."
    }
  ],
  "summaryType": "intrakurikuler_stage_3"
}
```

### Response

```json
{
  "summary": {
    "discussionSummary": "Guru dan Kina menyepakati pembelajaran menggunakan pengamatan gambar, diskusi kelompok, dan kuis singkat.",
    "learningStrategy": "Pengamatan visual, diskusi kelompok, presentasi singkat",
    "activityFlowDecision": {
      "opening": "Guru memberi pertanyaan pemantik tentang makanan yang dikonsumsi siswa.",
      "mainActivity": "Siswa mengamati gambar sistem pencernaan dan mengisi tabel organ-fungsi.",
      "closing": "Guru memberi penguatan dan kuis singkat."
    },
    "differentiationPlan": {
      "support": "Siswa yang membutuhkan bantuan diberi tabel dengan contoh isian.",
      "enrichment": "Siswa cepat diberi pertanyaan pengayaan tentang gangguan pencernaan."
    },
    "assessmentFocus": "Pemahaman konsep organ dan fungsi sistem pencernaan."
  }
}
```

---

# 7.6 Generate Final RPP Text

## `POST /internal/ai/generate-rpp`

Endpoint untuk menghasilkan teks final RPP.

FastAPI hanya menghasilkan teks dan JSON terstruktur. FastAPI tidak menghasilkan PDF atau DOCX.

### Request

```json
{
  "project": {
    "id": "uuid",
    "title": "RPP Sistem Pencernaan Manusia",
    "rppType": "intrakurikuler",
    "subject": "IPA",
    "phase": "Fase D",
    "gradeLevel": "Kelas 7"
  },
  "teacherProfile": {},
  "school": {},
  "teacherSubject": {},
  "teacherClass": {},
  "stages": [
    {
      "stageNumber": 1,
      "contentJson": {}
    },
    {
      "stageNumber": 2,
      "contentJson": {}
    },
    {
      "stageNumber": 3,
      "contentJson": {}
    },
    {
      "stageNumber": 4,
      "contentJson": {}
    }
  ],
  "kinaChatSummary": {},
  "options": {
    "includeRubric": true,
    "includeReflection": true,
    "includeStudentWorksheet": false
  }
}
```

### Response

```json
{
  "status": "success",
  "model": "gemini-1.5-flash",
  "usedReferences": [
    {
      "cpReferenceId": "uuid",
      "sourceTitle": "Capaian Pembelajaran IPA Fase D",
      "similarityScore": 0.86
    }
  ],
  "contentJson": {
    "title": "RPP Sistem Pencernaan Manusia",
    "identity": {},
    "learningObjectives": [],
    "learningActivities": {},
    "assessment": {},
    "rubric": {},
    "reflection": {}
  },
  "contentMarkdown": "# RPP Sistem Pencernaan Manusia\n\n..."
}
```

Catatan:

Response dari endpoint ini disimpan oleh NestJS ke tabel `generated_rpps`.

---

# 7.7 Index RAG Documents

## `POST /internal/rag/index-documents`

Endpoint untuk indexing dokumen Capaian Pembelajaran ke FAISS.

### Request

```json
{
  "documentPath": "app/data/raw_documents/CP_IPA_Fase_D.pdf",
  "sourceTitle": "Capaian Pembelajaran IPA Fase D",
  "documentType": "capaian_pembelajaran",
  "subject": "IPA",
  "phase": "Fase D"
}
```

### Response

```json
{
  "message": "Dokumen berhasil di-index.",
  "sourceTitle": "Capaian Pembelajaran IPA Fase D",
  "chunksCreated": 42,
  "faissIndexPath": "app/data/vector_store/cp.index"
}
```

---

# 7.8 RAG References

## `GET /internal/rag/references`

Endpoint untuk melihat daftar referensi CP yang tersedia.

### Query Params

```text
subject=IPA
phase=Fase D
documentType=capaian_pembelajaran
```

### Response

```json
{
  "items": [
    {
      "id": "uuid",
      "sourceTitle": "Capaian Pembelajaran IPA Fase D",
      "subject": "IPA",
      "phase": "Fase D",
      "element": "Pemahaman IPA"
    }
  ]
}
```

---

## 8. Endpoint yang Tidak Ada di FastAPI

FastAPI tidak menyediakan endpoint berikut:

```text
POST /internal/documents/export-docx
POST /internal/documents/export-pdf
```

Alasannya:

- FastAPI tidak membuat file dokumen.
- LLM hanya menghasilkan teks atau JSON.
- Template PDF/DOCX sudah dibuat oleh tim.
- Proses memasukkan hasil AI ke template dilakukan oleh NestJS atau frontend.

---

## 9. Flow Generate Dokumen

Flow yang benar:

```text
Guru klik Generate RPP
↓
Next.js call NestJS
↓
NestJS ambil project, profile, school, subject, class, stages
↓
NestJS call FastAPI /internal/ai/generate-rpp
↓
FastAPI return contentJson dan contentMarkdown
↓
NestJS simpan ke generated_rpps
↓
Guru membuka preview
↓
Guru klik Export PDF/DOCX
↓
NestJS/frontend memasukkan contentJson ke template dokumen
↓
File final disimpan ke Supabase Storage
↓
Metadata file disimpan ke exported_documents
```

---

## 10. Prioritas Implementasi

### Tahap 1 — Dummy AI Service

```text
GET  /internal/health
POST /internal/ai/recommend-stage
```

Tujuan:

- memastikan FastAPI berjalan,
- memastikan NestJS bisa memanggil FastAPI,
- response masih boleh dummy.

---

### Tahap 2 — RAG Search

```text
POST /internal/rag/search
POST /internal/rag/index-documents
```

Tujuan:

- indexing dokumen CP,
- membuat embedding,
- mencari referensi CP dari FAISS.

---

### Tahap 3 — Recommendation dengan RAG + LLM

```text
POST /internal/ai/recommend-stage
```

Tujuan:

- Stage 2 Intrakurikuler bisa mengambil CP dari RAG,
- LLM menghasilkan rekomendasi Tujuan Pembelajaran.

---

### Tahap 4 — Kina Chat

```text
POST /internal/ai/kina-chat
POST /internal/ai/summarize-kina-chat
```

---

### Tahap 5 — Generate Final RPP Text

```text
POST /internal/ai/generate-rpp
```

---

## 11. Cara Menjalankan Project

Install dependency:

```bash
pip install -r requirements.txt
```

Jalankan FastAPI:

```bash
uvicorn app.main:app --reload --port 8000
```

Cek health:

```bash
curl http://localhost:8000/internal/health
```

---

## 12. Catatan Pengembangan

- FastAPI hanya menghasilkan teks dan JSON AI.
- FastAPI tidak menyimpan project, stage, chat, atau generated RPP.
- FastAPI tidak membuat PDF/DOCX.
- NestJS tetap menjadi pemilik data aplikasi.
- NestJS menyimpan hasil AI ke Supabase.
- NestJS/frontend mengurus template dokumen.
- FAISS menyimpan vector index.
- Supabase/PostgreSQL menyimpan metadata CP jika dibutuhkan.
- Semua endpoint FastAPI harus dilindungi `INTERNAL_API_KEY`.
