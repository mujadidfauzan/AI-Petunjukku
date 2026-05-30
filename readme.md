# Petunjukku AI Service

AI Service Petunjukku adalah backend berbasis **FastAPI** yang bertanggung jawab untuk menjalankan proses AI, RAG, embedding, FAISS vector search, rekomendasi isian RPP, chatbot Kina, generate RPP, dan export dokumen.

Service ini **tidak dipanggil langsung oleh frontend**. Frontend Next.js hanya berkomunikasi dengan NestJS Application Backend. NestJS kemudian memanggil FastAPI AI Service melalui internal API.

---

## 1. Peran AI Service dalam Arsitektur Petunjukku

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

| Komponen            | Tanggung Jawab                                                  |
| ------------------- | --------------------------------------------------------------- |
| Next.js             | Tampilan aplikasi, Studio Guru, form stage, preview RPP         |
| NestJS              | Auth, user, teacher profile, RPP project, stage, database utama |
| Supabase PostgreSQL | Penyimpanan data aplikasi                                       |
| FastAPI AI Service  | RAG, AI recommendation, Kina chat, generate RPP, export dokumen |
| FAISS               | Vector search dokumen Capaian Pembelajaran                      |
| LLM API             | Generate rekomendasi, chat, dan dokumen RPP                     |

---

## 2. Fungsi Utama AI Service

AI Service tidak hanya digunakan untuk chatbot. AI Service memiliki beberapa fungsi utama:

1. **RAG Retrieval**
   Mengambil referensi resmi Capaian Pembelajaran dari dokumen pemerintah menggunakan embedding dan FAISS.

2. **AI Recommendation**
   Membuat rekomendasi isian stage RPP, misalnya rekomendasi Tujuan Pembelajaran dari Capaian Pembelajaran.

3. **Kina Chat**
   Menyediakan respons chatbot AI untuk diskusi guru pada stage tertentu.

4. **Kina Chat Summary**
   Merangkum hasil diskusi Kina menjadi data terstruktur untuk disimpan ke `rpp_stages.content_json`.

5. **Final RPP Generation**
   Membuat draft final RPP berdasarkan seluruh data stage, profil guru, kelas, sekolah, dan referensi RAG.

6. **Document Generation**
   Mengubah hasil RPP menjadi file DOCX atau PDF.

---

## 3. Struktur Folder Repo

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
│   │   ├── ai.py
│   │   └── documents.py
│   ├── schemas/
│   │   ├── rag_schema.py
│   │   ├── recommendation_schema.py
│   │   ├── kina_schema.py
│   │   ├── generate_rpp_schema.py
│   │   └── document_schema.py
│   ├── services/
│   │   ├── rag_service.py
│   │   ├── embedding_service.py
│   │   ├── faiss_service.py
│   │   ├── cp_reference_service.py
│   │   ├── prompt_builder_service.py
│   │   ├── recommendation_service.py
│   │   ├── kina_ai_service.py
│   │   ├── rpp_generation_service.py
│   │   ├── document_generation_service.py
│   │   ├── docx_export_service.py
│   │   ├── pdf_export_service.py
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

## 4. Penjelasan Folder

### `app/main.py`

Entry point utama FastAPI.

Tugas:

- membuat instance FastAPI,
- mendaftarkan router,
- mengatur CORS internal jika dibutuhkan,
- menjalankan startup event untuk load FAISS index.

---

### `app/core/`

Berisi konfigurasi global aplikasi.

| File          | Fungsi                                |
| ------------- | ------------------------------------- |
| `config.py`   | Membaca environment variable          |
| `security.py` | Validasi internal API key dari NestJS |
| `logging.py`  | Konfigurasi logging service           |

---

### `app/routers/`

Berisi definisi endpoint FastAPI.

| File           | Endpoint                                                                              |
| -------------- | ------------------------------------------------------------------------------------- |
| `health.py`    | `/internal/health`                                                                    |
| `rag.py`       | `/internal/rag/search`, `/internal/rag/index-documents`, `/internal/rag/references`   |
| `ai.py`        | `/internal/ai/recommend-stage`, `/internal/ai/kina-chat`, `/internal/ai/generate-rpp` |
| `documents.py` | `/internal/documents/export-docx`, `/internal/documents/export-pdf`                   |

---

### `app/schemas/`

Berisi Pydantic schema untuk request dan response.

| File                       | Fungsi                      |
| -------------------------- | --------------------------- |
| `rag_schema.py`            | Schema request/response RAG |
| `recommendation_schema.py` | Schema rekomendasi stage    |
| `kina_schema.py`           | Schema chatbot Kina         |
| `generate_rpp_schema.py`   | Schema generate final RPP   |
| `document_schema.py`       | Schema export dokumen       |

---

### `app/services/`

Berisi business logic utama AI Service.

| File                             | Fungsi                                         |
| -------------------------------- | ---------------------------------------------- |
| `rag_service.py`                 | Mengatur proses retrieval dokumen CP           |
| `embedding_service.py`           | Membuat embedding dari query atau dokumen      |
| `faiss_service.py`               | Load, search, dan update index FAISS           |
| `cp_reference_service.py`        | Mengambil metadata CP dari Supabase/PostgreSQL |
| `prompt_builder_service.py`      | Menyusun prompt untuk LLM                      |
| `recommendation_service.py`      | Membuat rekomendasi isian stage                |
| `kina_ai_service.py`             | Membuat respons chatbot Kina                   |
| `rpp_generation_service.py`      | Generate final RPP                             |
| `document_generation_service.py` | Orkestrasi export dokumen                      |
| `docx_export_service.py`         | Generate file DOCX                             |
| `pdf_export_service.py`          | Generate file PDF                              |
| `llm_client.py`                  | Client untuk Gemini/OpenRouter/LLM API         |

---

### `app/data/`

Berisi data dokumen dan vector store lokal.

| Folder              | Fungsi                                       |
| ------------------- | -------------------------------------------- |
| `raw_documents/`    | Menyimpan PDF CP atau dokumen kurikulum asli |
| `processed_chunks/` | Menyimpan hasil chunking dokumen             |
| `vector_store/`     | Menyimpan FAISS index dan metadata           |

---

## 5. Environment Variable

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

EMBEDDING_MODEL_NAME="sentence-transformers/all-MiniLM-L6-v2"

SUPABASE_URL="https://your-project.supabase.co"
SUPABASE_SERVICE_ROLE_KEY="your-service-role-key"

FAISS_INDEX_PATH="app/data/vector_store/cp.index"
FAISS_METADATA_PATH="app/data/vector_store/cp_metadata.json"
```

Catatan:

- `INTERNAL_API_KEY` digunakan agar endpoint FastAPI hanya dapat dipanggil oleh NestJS.
- `SUPABASE_SERVICE_ROLE_KEY` hanya boleh digunakan di backend, bukan frontend.
- `FAISS_INDEX_PATH` adalah lokasi file index FAISS.
- `FAISS_METADATA_PATH` adalah mapping metadata vector ke `cp_references`.

---

## 6. Endpoint FastAPI

Semua endpoint FastAPI menggunakan prefix `/internal` karena service ini hanya dipanggil oleh NestJS.

---

# 6.1 Health Check

## `GET /internal/health`

Endpoint untuk mengecek status AI Service.

### Response

```json
{
  "status": "ok",
  "service": "petunjukku-ai-service",
  "faiss": "ok",
  "llm": "configured"
}
```

---

# 6.2 RAG Search

## `POST /internal/rag/search`

Endpoint untuk mencari referensi Capaian Pembelajaran berdasarkan query, fase, dan mata pelajaran.

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

# 6.3 AI Stage Recommendation

## `POST /internal/ai/recommend-stage`

Endpoint untuk membuat rekomendasi isian stage RPP.

Contoh penggunaan:

- Stage 2 Intrakurikuler: membuat Tujuan Pembelajaran dari CP.
- Stage 4 Intrakurikuler: membuat asesmen dan rubrik.
- Stage 2 PjBL: membuat tujuan proyek dan ide aktivitas.

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

Endpoint ini tidak menyimpan hasil rekomendasi ke database. NestJS/frontend akan menampilkan rekomendasi ke guru. Guru dapat mengedit atau menerima rekomendasi tersebut, lalu hasil final disimpan ke `rpp_stages.content_json` melalui Stage API NestJS.

---

# 6.4 Kina Chat

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

FastAPI hanya menghasilkan respons. Penyimpanan chat ke tabel `kina_chats` dilakukan oleh NestJS.

---

# 6.5 Summarize Kina Chat

## `POST /internal/ai/summarize-kina-chat`

Endpoint untuk merangkum percakapan Kina menjadi data terstruktur yang dapat disimpan ke stage.

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

# 6.6 Generate Final RPP

## `POST /internal/ai/generate-rpp`

Endpoint untuk membuat draft final RPP berdasarkan seluruh data project dan stage.

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

NestJS yang menyimpan response ini ke tabel `generated_rpps`.

---

# 6.7 Index RAG Documents

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

# 6.8 RAG References

## `GET /internal/rag/references`

Endpoint untuk melihat daftar referensi CP yang sudah tersedia.

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

# 6.9 Export DOCX

## `POST /internal/documents/export-docx`

Endpoint untuk membuat file DOCX dari RPP.

### Request

```json
{
  "generatedRppId": "uuid",
  "contentJson": {},
  "contentMarkdown": "# RPP ..."
}
```

### Response

```json
{
  "fileName": "rpp-sistem-pencernaan.docx",
  "mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  "fileBase64": "..."
}
```

---

# 6.10 Export PDF

## `POST /internal/documents/export-pdf`

Endpoint untuk membuat file PDF dari RPP.

### Request

```json
{
  "generatedRppId": "uuid",
  "contentJson": {},
  "contentMarkdown": "# RPP ..."
}
```

### Response

```json
{
  "fileName": "rpp-sistem-pencernaan.pdf",
  "mimeType": "application/pdf",
  "fileBase64": "..."
}
```

---

## 7. Prioritas Implementasi

Untuk tahap awal, implementasi dilakukan bertahap.

### Tahap 1 — Integrasi Dasar

```text
GET  /internal/health
POST /internal/ai/recommend-stage
```

Pada tahap ini, response boleh dummy terlebih dahulu agar NestJS dapat menguji koneksi ke FastAPI.

---

### Tahap 2 — RAG Search

```text
POST /internal/rag/search
POST /internal/rag/index-documents
```

Pada tahap ini, FAISS mulai digunakan untuk mencari dokumen CP.

---

### Tahap 3 — LLM Recommendation

```text
POST /internal/ai/recommend-stage
```

Endpoint recommendation mulai menggunakan:

```text
RAG → Prompt Builder → LLM → JSON recommendation
```

---

### Tahap 4 — Chatbot Kina

```text
POST /internal/ai/kina-chat
POST /internal/ai/summarize-kina-chat
```

---

### Tahap 5 — Final RPP dan Export

```text
POST /internal/ai/generate-rpp
POST /internal/documents/export-docx
POST /internal/documents/export-pdf
```

---

## 8. Cara Menjalankan Project

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

## 9. Contoh Flow Stage 2 Intrakurikuler

Flow rekomendasi Tujuan Pembelajaran:

```text
Guru membuka Stage 2 Intrakurikuler
↓
Frontend meminta rekomendasi ke NestJS
↓
NestJS memanggil FastAPI /internal/ai/recommend-stage
↓
FastAPI mencari CP relevan melalui RAG
↓
FastAPI mengirim CP + konteks project ke LLM
↓
LLM menghasilkan rekomendasi Tujuan Pembelajaran
↓
FastAPI return rekomendasi ke NestJS
↓
NestJS return ke frontend
↓
Guru review/edit
↓
Guru menyimpan hasil final ke rpp_stages.content_json
```

---

## 10. Catatan Pengembangan

- FastAPI tidak menyimpan data utama RPP.
- Penyimpanan project, stage, chat, dan hasil generate tetap dilakukan oleh NestJS.
- FastAPI hanya menghasilkan output AI dan mengembalikannya ke NestJS.
- FAISS menyimpan vector index.
- Supabase/PostgreSQL menyimpan metadata referensi CP.
- LLM API dipanggil hanya dari FastAPI.
- Endpoint FastAPI bersifat internal dan harus dilindungi dengan internal API key.
