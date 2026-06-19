# Petunjukku AI Service

Petunjukku AI Service adalah backend berbasis **FastAPI** yang bertanggung jawab untuk menjalankan proses AI pada aplikasi Petunjukku, seperti **RAG retrieval**, **AI recommendation Stage 2**, **Kina Chat**, **summary chat**, dan **generate teks RPP**.

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

| Komponen            | Tanggung Jawab                                                             |
| ------------------- | -------------------------------------------------------------------------- |
| Next.js             | UI, form stage, preview RPP, export action                                 |
| NestJS              | Auth, user, teacher profile, RPP project, stage, database, orchestration   |
| Supabase PostgreSQL | Penyimpanan data aplikasi                                                  |
| FastAPI             | RAG, AI recommendation Stage 2, Kina Chat, summary chat, generate teks RPP |
| FAISS               | Vector search dokumen Capaian Pembelajaran                                 |
| LLM API             | Generate rekomendasi, jawaban chat, summary chat, dan teks RPP             |

---

## 2. Prinsip Utama AI Service

AI Service mengikuti prinsip berikut:

1. **FastAPI hanya dipanggil oleh NestJS**, bukan oleh frontend.
2. **FastAPI tidak menyimpan data utama aplikasi** seperti project RPP, stage, chat, atau hasil generated RPP.
3. **FastAPI tidak membuat file PDF/DOCX**.
4. **FastAPI hanya mengembalikan hasil AI berupa teks atau JSON terstruktur**.
5. **NestJS yang menyimpan hasil AI ke Supabase**.
6. **Guru tetap melakukan review/edit sebelum hasil AI disimpan sebagai bagian final RPP**.
7. **RAG digunakan sebagai sumber referensi resmi**, terutama untuk mengambil Capaian Pembelajaran yang relevan.
8. **AI Recommendation hanya digunakan pada Stage 2**.
9. **Logic AI dipisahkan berdasarkan jenis RPP**, yaitu Intrakurikuler dan PjBL Kokurikuler.
10. **Endpoint FastAPI tetap umum**, sedangkan pemilihan logic dilakukan oleh AI Orchestrator berdasarkan `project.rppType`.

---

## 3. Fungsi Utama FastAPI

FastAPI AI Service memiliki beberapa fungsi utama.

### 3.1 RAG Retrieval

RAG Retrieval digunakan untuk mengambil referensi **Capaian Pembelajaran** dari dokumen resmi menggunakan embedding dan FAISS.

Contoh penggunaan:

- mencari Capaian Pembelajaran berdasarkan fase dan mata pelajaran,
- mengambil referensi Capaian Pembelajaran untuk Stage 2 Intrakurikuler,
- mengambil konteks resmi untuk generate final RPP,
- memberi dasar referensi pada Kina Chat jika diperlukan.

Status saat ini:

```text
RAG sudah selesai dan dapat digunakan oleh service AI Intrakurikuler maupun PjBL Kokurikuler.
```

---

### 3.2 AI Recommendation Stage 2

AI Recommendation hanya digunakan pada **Stage 2**.

Tidak ada AI Recommendation khusus untuk:

```text
Stage 1
Stage 3
Stage 4
Stage 5
```

Stage selain Stage 2 tetap bisa menggunakan AI dalam bentuk lain, misalnya Kina Chat, summarize chat, atau generate final RPP. Namun fitur **recommend-stage** hanya difokuskan untuk Stage 2.

---

#### 3.2.1 Recommendation Stage 2 Intrakurikuler

Pada Intrakurikuler, Stage 2 berfokus pada penyusunan **Alur Tujuan Pembelajaran**.

Flow:

```text
Input project dan konteks pembelajaran
↓
RAG mengambil Capaian Pembelajaran yang relevan
↓
Capaian Pembelajaran dikirim ke LLM sebagai konteks
↓
LLM menyusun rekomendasi Alur Tujuan Pembelajaran
↓
FastAPI mengembalikan JSON rekomendasi ke NestJS
```

Output utama:

```text
Alur Tujuan Pembelajaran
```

Catatan penting:

```text
Capaian Pembelajaran dari RAG = referensi resmi.
Alur Tujuan Pembelajaran = output rekomendasi LLM.
```

---

#### 3.2.2 Recommendation Stage 2 PjBL Kokurikuler

Pada PjBL Kokurikuler, Stage 2 berfokus pada rekomendasi **proyek yang akan dilakukan**.

Flow:

```text
Input semua konteks dari Stage 1
↓
LLM membaca konteks sekolah, siswa, lingkungan, mata pelajaran, fase, dan masalah sekitar
↓
LLM menyusun rekomendasi proyek yang akan dilakukan
↓
FastAPI mengembalikan JSON rekomendasi ke NestJS
```

Output utama:

```text
Rekomendasi Proyek yang Akan Dilakukan
```

Data utama yang digunakan:

```text
Semua konteks dari Stage 1
```

Contoh konteks Stage 1:

- jenjang,
- fase,
- mata pelajaran,
- kelas,
- karakteristik siswa,
- kondisi sekolah,
- lingkungan sekitar,
- fasilitas yang tersedia,
- masalah lokal,
- durasi proyek,
- batasan pelaksanaan.

Catatan penting:

```text
PjBL Stage 2 tidak berfokus pada rekomendasi CP sebagai output.
AI menggunakan konteks Stage 1 untuk menyarankan proyek yang realistis, kontekstual, dan dapat dilakukan oleh siswa.
```

---

### 3.3 Kina Chat

Kina Chat menghasilkan jawaban chatbot Kina berdasarkan:

- konteks project RPP,
- stage yang sudah diisi,
- profil guru,
- data sekolah,
- data kelas,
- riwayat chat,
- referensi Capaian Pembelajaran dari RAG jika diperlukan.

FastAPI hanya menghasilkan jawaban. Penyimpanan chat ke tabel `kina_chats` dilakukan oleh NestJS.

---

### 3.4 Summarize Kina Chat

Summarize Kina Chat digunakan untuk merangkum diskusi guru dengan Kina menjadi JSON terstruktur agar dapat disimpan sebagai bagian dari stage.

Contoh isi summary:

- ringkasan diskusi,
- strategi pembelajaran,
- alur kegiatan,
- rencana diferensiasi,
- fokus asesmen,
- kendala dan mitigasi,
- keputusan akhir guru.

---

### 3.5 Generate Final RPP Text

Generate Final RPP Text digunakan untuk membuat teks final RPP berdasarkan:

- data project,
- profil guru,
- sekolah,
- kelas,
- mapel,
- stage 1 sampai stage 5,
- hasil diskusi Kina,
- referensi Capaian Pembelajaran dari RAG jika diperlukan.

FastAPI mengembalikan:

```text
contentJson
contentMarkdown
usedReferences
model
```

FastAPI tidak membuat file dokumen. File PDF/DOCX dibuat setelah data ini dimasukkan ke template oleh NestJS atau frontend.

---

## 4. Pembagian Logic AI Berdasarkan Jenis RPP

Petunjukku memiliki dua jenis RPP utama:

```text
intrakurikuler
pjbl_kokurikuler
```

Kedua jenis RPP ini memiliki stage, prompt, struktur output, dan kebutuhan AI yang berbeda. Karena itu, logic FastAPI dipisahkan menjadi dua domain service:

```text
app/services/intrakurikuler/
app/services/pjbl/
```

Endpoint FastAPI tetap sama, tetapi service internal yang dipanggil akan berbeda berdasarkan `project.rppType`.

Contoh flow:

```text
POST /internal/ai/recommend-stage
↓
AI Orchestrator membaca project.rppType dan targetStage.stageNumber
↓
Jika intrakurikuler dan stageNumber = 2 → intra_recommendation_service.py
Jika pjbl_kokurikuler dan stageNumber = 2 → pjbl_recommendation_service.py
Jika stageNumber selain 2 → return error bahwa recommendation hanya tersedia untuk Stage 2
```

---

## 5. Pembagian Tugas Developer AI

### 5.1 Developer 1 — AI Intrakurikuler

Developer 1 bertanggung jawab untuk semua logic AI yang berhubungan dengan RPP Intrakurikuler.

Fokus kerja Developer 1:

- recommendation Stage 2 Intrakurikuler,
- prompt dari CP hasil RAG menjadi rekomendasi Alur Tujuan Pembelajaran,
- Kina Chat khusus Intrakurikuler,
- summary Kina Chat untuk Intrakurikuler,
- generate final text RPP Intrakurikuler.

Folder utama Developer 1:

```text
app/services/intrakurikuler/
├── intra_recommendation_service.py
├── intra_kina_service.py
├── intra_summary_service.py
├── intra_generation_service.py
└── intra_prompt_templates.py
```

Prioritas awal Developer 1:

```text
Stage 2 Intrakurikuler
↓
RAG mengambil Capaian Pembelajaran yang relevan
↓
LLM menyusun rekomendasi Alur Tujuan Pembelajaran
↓
FastAPI mengembalikan JSON rekomendasi ke NestJS
```

Output utama Stage 2 Intrakurikuler:

```text
Alur Tujuan Pembelajaran
```

---

### 5.2 Developer 2 — AI PjBL Kokurikuler

Developer 2 bertanggung jawab untuk semua logic AI yang berhubungan dengan RPP PjBL Kokurikuler.

Fokus kerja Developer 2:

- recommendation Stage 2 PjBL Kokurikuler,
- prompt dari semua konteks Stage 1 menjadi rekomendasi proyek yang akan dilakukan,
- Kina Chat khusus PjBL Kokurikuler,
- summary Kina Chat untuk PjBL Kokurikuler,
- generate final text RPP PjBL Kokurikuler.

Folder utama Developer 2:

```text
app/services/pjbl/
├── pjbl_recommendation_service.py
├── pjbl_kina_service.py
├── pjbl_summary_service.py
├── pjbl_generation_service.py
└── pjbl_prompt_templates.py
```

Prioritas awal Developer 2:

```text
Stage 2 PjBL Kokurikuler
↓
Mengambil semua konteks dari Stage 1
↓
LLM menyusun rekomendasi proyek yang akan dilakukan
↓
FastAPI mengembalikan JSON rekomendasi ke NestJS
```

Output utama Stage 2 PjBL Kokurikuler:

```text
Rekomendasi Proyek yang Akan Dilakukan
```

---

## 6. Struktur Folder Repo

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
│   │   ├── ai_orchestrator_service.py
│   │   ├── rag_service.py
│   │   ├── embedding_service.py
│   │   ├── faiss_service.py
│   │   ├── cp_reference_service.py
│   │   ├── prompt_builder_service.py
│   │   ├── llm_client.py
│   │   ├── intrakurikuler/
│   │   │   ├── intra_recommendation_service.py
│   │   │   ├── intra_kina_service.py
│   │   │   ├── intra_summary_service.py
│   │   │   ├── intra_generation_service.py
│   │   │   └── intra_prompt_templates.py
│   │   └── pjbl/
│   │       ├── pjbl_recommendation_service.py
│   │       ├── pjbl_kina_service.py
│   │       ├── pjbl_summary_service.py
│   │       ├── pjbl_generation_service.py
│   │       └── pjbl_prompt_templates.py
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
│   ├── test_intra_recommendation.py
│   └── test_pjbl_recommendation.py
├── .env
├── .env.example
├── requirements.txt
├── README.md
└── run.py
```

---

## 7. Penjelasan Folder

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

| File/Folder                  | Fungsi                                                                        |
| ---------------------------- | ----------------------------------------------------------------------------- |
| `ai_orchestrator_service.py` | Mengarahkan request ke service Intrakurikuler atau PjBL berdasarkan `rppType` |
| `rag_service.py`             | Mengatur proses retrieval CP                                                  |
| `embedding_service.py`       | Membuat embedding query dan dokumen                                           |
| `faiss_service.py`           | Load, search, dan update FAISS index                                          |
| `cp_reference_service.py`    | Mengambil metadata CP dari database atau metadata file                        |
| `prompt_builder_service.py`  | Helper umum untuk menyusun prompt                                             |
| `llm_client.py`              | Client untuk Gemini/OpenRouter/LLM API                                        |
| `intrakurikuler/`            | Logic AI khusus RPP Intrakurikuler                                            |
| `pjbl/`                      | Logic AI khusus RPP PjBL Kokurikuler                                          |

---

### `app/data/`

Berisi dokumen dan vector store.

| Folder              | Fungsi                                 |
| ------------------- | -------------------------------------- |
| `raw_documents/`    | Dokumen PDF asli seperti CP pemerintah |
| `processed_chunks/` | Hasil chunking dokumen                 |
| `vector_store/`     | FAISS index dan metadata vector        |

---

## 8. Environment Variable

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
LLM_MODEL="qwen/qwen3.7-plus"
LLM_MAX_TOKENS=12000

RESOURCE_DISCOVERY_ENABLED=true
YOUTUBE_API_KEY="your-youtube-data-api-key"
YOUTUBE_API_BASE_URL="https://www.googleapis.com/youtube/v3"
BOOK_CATALOG_API_URL="https://api.buku.cloudapp.web.id/api/catalogue/getPenggerakTextBooks"
BOOK_CATALOG_ALLOWED_DOMAINS="buku.kemendikdasmen.go.id,static.sc.cloudapp.web.id,static-sc.cloudapp.web.id,files.cloudapp.web.id"

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
- Jika metadata RAG disimpan dalam file lokal, `SUPABASE_SERVICE_ROLE_KEY` belum wajib dipakai pada tahap awal.
- `YOUTUBE_API_KEY` bersifat opsional. Tanpa key, provider YouTube dilewati dan generate tetap berjalan.
- `BOOK_CATALOG_API_URL` menggunakan endpoint katalog publik yang dipakai situs resmi SIBI. Provider ini tidak membutuhkan API key.
- Adapter memfilter hasil berdasarkan mata pelajaran dan kelas, lalu memprioritaskan buku siswa PDF resmi.

Contoh struktur respons SIBI yang didukung:

```json
{
  "results": [
    {
      "title": "Matematika untuk SMA/SMK Kelas X",
      "attachment": "https://static-sc.cloudapp.web.id/...pdf",
      "subject": "matematika",
      "class": "10",
      "level": "SMA/MA/SMK/MAK",
      "book_type": "buku_siswa",
      "publisher": "Pusat Perbukuan"
    }
  ]
}
```

---

## 9. Endpoint FastAPI

Semua endpoint menggunakan prefix `/internal` dan wajib dipanggil dengan header:

```http
X-Internal-API-Key: <INTERNAL_API_KEY>
```

---

### 9.1 Health Check

#### `GET /internal/health`

Endpoint untuk mengecek apakah AI Service berjalan.

Response:

```json
{
  "status": "ok",
  "service": "petunjukku-ai-service",
  "rag": "ok",
  "llm": "configured"
}
```

---

### 9.2 RAG Search

#### `POST /internal/rag/search`

Endpoint untuk mencari referensi Capaian Pembelajaran.

Request:

```json
{
  "query": "Sistem Pencernaan Manusia kelas 7 IPA",
  "subject": "IPA",
  "phase": "Fase D",
  "topK": 5
}
```

Response:

```json
{
  "cpText": "Menganalisis konsep kalor dan termodinamika serta penerapannya untuk mengidentifikasi fenomena perubahan iklim.",
  "selectedRecordId": "4422bb1b320ac7880a7f779c",
  "confidence": 0.7399036532336486,
  "query": "Ambil Capaian Pembelajaran resmi yang paling relevan. mata pelajaran Fisika. fase F. materi pokok atau konteks topik Termodinamika.",
  "sources": [
    {
      "document_id": "uuid",
      "chunk_id": "uuid",
      "similarity": 0.7399036532336486,
      "metadata": {
        "source": "Kepka_BSKAP_No_01k17e8396ajn15j3hcw0k773b.pdf",
        "file_name": "Kepka_BSKAP_No_01k17e8396ajn15j3hcw0k773b.pdf",
        "mime_type": "application/pdf",
        "content_type": "cp_record",
        "cp_record_id": "4422bb1b320ac7880a7f779c",
        "subject": "FISIKA",
        "subject_normalized": "fisika",
        "phase": "F",
        "phase_class_description": "Umumnya untuk Kelas XI dan XII SMA/MA/Program Paket C",
        "domain": "Reguler",
        "lampiran": "II",
        "jenjang": "SMA",
        "page": 164,
        "page_start": 164,
        "page_end": 166
      },
      "preview": "Mata pelajaran: FISIKA Fase: F Jenjang: SMA..."
    }
  ],
  "models": {
    "embedding": "google/gemini-embedding-2-preview",
    "llm": "google/gemini-2.5-flash"
  }
}
```

Catatan:

`cpText` adalah Capaian Pembelajaran yang ditemukan oleh RAG. Nilai ini digunakan sebagai referensi untuk LLM, bukan sebagai output final stage.

---

### 9.3 AI Stage 2 Recommendation

#### `POST /internal/ai/recommend-stage`

Endpoint untuk membuat rekomendasi isian **Stage 2**.

Endpoint ini hanya digunakan untuk:

```text
Stage 2 Intrakurikuler
Stage 2 PjBL Kokurikuler
```

Jika `targetStage.stageNumber` bukan `2`, service sebaiknya mengembalikan error validasi bahwa recommendation hanya tersedia untuk Stage 2.

Endpoint ini digunakan untuk dua jenis RPP:

```text
intrakurikuler
pjbl_kokurikuler
```

FastAPI akan memilih service berdasarkan `project.rppType`.

---

#### Request Intrakurikuler Stage 2

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
    "stageName": "Alur Tujuan Pembelajaran",
    "recommendationType": "learning_objectives_flow",
    "topic": "Sistem Pencernaan Manusia"
  },
  "options": {
    "topK": 5,
    "language": "id",
    "outputFormat": "json"
  }
}
```

#### Response Intrakurikuler Stage 2

```json
{
  "rppType": "intrakurikuler",
  "recommendationType": "learning_objectives_flow",
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
    "capaianPembelajaranSummary": "Referensi CP yang relevan berkaitan dengan pemahaman sistem organ dan fungsinya.",
    "alurTujuanPembelajaran": [
      {
        "order": 1,
        "tujuanPembelajaran": "Peserta didik mampu mengidentifikasi organ-organ pada sistem pencernaan manusia.",
        "rationale": "Tujuan ini menjadi fondasi awal sebelum siswa menjelaskan fungsi setiap organ."
      },
      {
        "order": 2,
        "tujuanPembelajaran": "Peserta didik mampu menjelaskan fungsi organ pencernaan manusia secara runtut.",
        "rationale": "Tujuan ini mengembangkan pemahaman siswa dari pengenalan organ menuju hubungan organ dan fungsi."
      },
      {
        "order": 3,
        "tujuanPembelajaran": "Peserta didik mampu menghubungkan proses pencernaan dengan pentingnya menjaga kesehatan tubuh.",
        "rationale": "Tujuan ini mengaitkan konsep ilmiah dengan kehidupan sehari-hari siswa."
      }
    ],
    "suggestedEssentialQuestion": "Bagaimana makanan yang kita konsumsi diproses oleh tubuh menjadi energi?",
    "reasoningSummary": "Alur Tujuan Pembelajaran disusun berdasarkan CP IPA Fase D yang ditemukan melalui RAG, lalu diurutkan dari pemahaman dasar menuju penerapan kontekstual."
  }
}
```

---

#### Request PjBL Stage 2

Untuk PjBL Kokurikuler, rekomendasi Stage 2 dibuat berdasarkan semua konteks yang sudah diisi pada Stage 1.

```json
{
  "project": {
    "id": "uuid",
    "title": "RPP PjBL Sampah Plastik",
    "rppType": "pjbl_kokurikuler",
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
    "availableFacilities": ["Proyektor", "Tempat sampah terpilah", "Halaman sekolah"],
    "localContext": "Sekolah memiliki masalah sampah plastik setelah jam istirahat."
  },
  "teacherClass": {
    "className": "7A",
    "gradeLevel": "Kelas 7",
    "studentCount": 32,
    "studentCharacteristics": "Siswa aktif dan suka kegiatan praktik.",
    "learningChallenges": ["Kemampuan kerja kelompok masih perlu diarahkan"],
    "dominantLearningStyle": "praktik dan visual"
  },
  "previousStages": [
    {
      "stageNumber": 1,
      "stageName": "Konteks Dasar Proyek",
      "contentJson": {
        "localIssue": "Sampah plastik banyak ditemukan di lingkungan sekolah setelah jam istirahat.",
        "schoolFacilities": ["Tempat sampah", "Halaman sekolah", "Proyektor"],
        "studentCharacteristics": "Siswa aktif, suka observasi, tetapi perlu arahan dalam kerja kelompok.",
        "projectDuration": "3 minggu",
        "implementationConstraints": ["Waktu terbatas", "Perlu pengawasan saat observasi lingkungan"]
      }
    }
  ],
  "targetStage": {
    "stageNumber": 2,
    "stageName": "Rekomendasi Proyek",
    "recommendationType": "project_recommendation",
    "topic": "Sampah Plastik di Lingkungan Sekolah"
  },
  "options": {
    "language": "id",
    "outputFormat": "json"
  }
}
```

#### Response PjBL Stage 2

```json
{
  "rppType": "pjbl_kokurikuler",
  "recommendationType": "project_recommendation",
  "targetStageNumber": 2,
  "recommendations": {
    "recommendedProjectTitle": "Aksi Sekolah Minim Sampah Plastik",
    "projectTheme": "Pengelolaan Sampah Plastik di Lingkungan Sekolah",
    "projectBackground": "Proyek ini berangkat dari masalah banyaknya sampah plastik di lingkungan sekolah setelah jam istirahat. Siswa diajak mengamati masalah, mencari penyebab, merancang solusi sederhana, dan membuat kampanye pengurangan sampah plastik.",
    "projectObjectives": [
      "Peserta didik mampu mengidentifikasi masalah sampah plastik di lingkungan sekolah.",
      "Peserta didik mampu menganalisis penyebab munculnya sampah plastik di lingkungan sekolah.",
      "Peserta didik mampu merancang solusi sederhana untuk mengurangi sampah plastik.",
      "Peserta didik mampu mempresentasikan hasil proyek secara kolaboratif."
    ],
    "drivingQuestion": "Bagaimana cara mengurangi sampah plastik di lingkungan sekolah melalui aksi nyata siswa?",
    "studentProduct": ["Poster kampanye pengurangan sampah plastik", "Laporan observasi sampah plastik", "Rancangan tempat pemilahan sampah sederhana"],
    "projectActivitiesOverview": [
      "Observasi kondisi sampah plastik di lingkungan sekolah.",
      "Diskusi kelompok tentang penyebab dan dampak sampah plastik.",
      "Perancangan solusi atau kampanye pengurangan sampah plastik.",
      "Pembuatan produk kampanye atau prototype sederhana.",
      "Presentasi hasil proyek di kelas."
    ],
    "feasibilityNotes": "Proyek ini realistis dilakukan dalam durasi 3 minggu karena menggunakan fasilitas yang tersedia di sekolah dan dekat dengan pengalaman sehari-hari siswa.",
    "riskMitigation": [
      {
        "risk": "Siswa kurang terarah saat observasi lingkungan.",
        "mitigation": "Guru menyediakan lembar observasi dan batas area pengamatan."
      },
      {
        "risk": "Waktu pengerjaan produk terlalu panjang.",
        "mitigation": "Produk dibuat sederhana dan fokus pada pesan kampanye atau solusi awal."
      }
    ],
    "reasoningSummary": "Rekomendasi proyek disusun berdasarkan konteks Stage 1, yaitu masalah sampah plastik di lingkungan sekolah, karakteristik siswa yang aktif, fasilitas yang tersedia, serta durasi proyek 3 minggu."
  }
}
```

Catatan:

Endpoint ini tidak menyimpan hasil rekomendasi ke database. Hasil akan ditampilkan kepada guru untuk direview, diedit, lalu disimpan oleh NestJS ke `rpp_stages.content_json`.

Penting:

```text
Intrakurikuler Stage 2:
CP dari RAG = referensi resmi.
Alur Tujuan Pembelajaran = hasil rekomendasi LLM.

PjBL Stage 2:
Konteks Stage 1 = input utama.
Rekomendasi proyek yang akan dilakukan = hasil rekomendasi LLM.
```

---

### 9.4 Kina Chat

#### `POST /internal/ai/kina-chat`

Endpoint untuk menghasilkan respons chatbot Kina.

Request:

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
      "stageName": "Alur Tujuan Pembelajaran",
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

Response:

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

### 9.5 Summarize Kina Chat

#### `POST /internal/ai/summarize-kina-chat`

Endpoint untuk merangkum percakapan Kina menjadi JSON terstruktur.

Request:

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

Response:

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

### Ini tolong direview lagi nanti disesuaikan dengan output masing masing!

### 9.6 Generate Final RPP Text

#### `POST /internal/ai/generate-rpp`

Endpoint untuk menghasilkan teks final RPP.

FastAPI hanya menghasilkan teks dan JSON terstruktur. FastAPI tidak menghasilkan PDF atau DOCX.

Request:

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

Response:

```json
{
  "status": "success",
  "model": "gemini-1.5-flash",
  "rppType": "intrakurikuler",
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

### 9.7 Index RAG Documents

#### `POST /internal/rag/index-documents`

Endpoint untuk indexing dokumen Capaian Pembelajaran ke FAISS.

Request:

```json
{
  "documentPath": "app/data/raw_documents/CP_IPA_Fase_D.pdf",
  "sourceTitle": "Capaian Pembelajaran IPA Fase D",
  "documentType": "capaian_pembelajaran",
  "subject": "IPA",
  "phase": "Fase D"
}
```

Response:

```json
{
  "message": "Dokumen berhasil di-index.",
  "sourceTitle": "Capaian Pembelajaran IPA Fase D",
  "chunksCreated": 42,
  "faissIndexPath": "app/data/vector_store/cp.index"
}
```

---

### 9.8 RAG References

#### `GET /internal/rag/references`

Endpoint untuk melihat daftar referensi CP yang tersedia.

Query params:

```text
subject=IPA
phase=Fase D
documentType=capaian_pembelajaran
```

Response:

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

## 10. Endpoint yang Tidak Ada di FastAPI

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

## 11. Flow Generate Dokumen

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

## 12. Prioritas Implementasi

### Tahap 1 — Integrasi Endpoint

```text
GET  /internal/health
POST /internal/ai/recommend-stage
```

Tujuan:

- memastikan FastAPI berjalan,
- memastikan NestJS bisa memanggil FastAPI,
- memastikan orchestrator bisa memilih service berdasarkan `rppType`,
- memastikan service menolak recommendation jika `stageNumber` bukan 2.

---

### Tahap 2 — Intrakurikuler dan PjBL Stage 2 Recommendation

```text
POST /internal/ai/recommend-stage
```

Fokus Developer 1:

```text
intrakurikuler stage 2
↓
CP dari RAG
↓
LLM
↓
rekomendasi Alur Tujuan Pembelajaran
```

Fokus Developer 2:

```text
pjbl stage 2
↓
semua konteks dari Stage 1
↓
LLM
↓
rekomendasi proyek yang akan dilakukan
```

---

### Tahap 3 — Kina Chat

```text
POST /internal/ai/kina-chat
```

Fokus Developer 1:

```text
Prompt Kina untuk diskusi Intrakurikuler
```

Fokus Developer 2:

```text
Prompt Kina untuk diskusi PjBL Kokurikuler
```

---

### Tahap 4 — Summarize Kina Chat

```text
POST /internal/ai/summarize-kina-chat
```

Fokus Developer 1:

```text
Summary Intrakurikuler
```

Fokus Developer 2:

```text
Summary PjBL Kokurikuler
```

---

### Tahap 5 — Generate Final RPP Text

```text
POST /internal/ai/generate-rpp
```

Fokus Developer 1:

```text
Generate final text RPP Intrakurikuler
```

Fokus Developer 2:

```text
Generate final text RPP PjBL Kokurikuler
```

---

## 13. Cara Menjalankan Project

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
curl -H "X-Internal-API-Key: change-this-internal-key" \
  http://localhost:8000/internal/health
```

---

## 14. Catatan Pengembangan

- FastAPI hanya menghasilkan teks dan JSON AI.
- FastAPI tidak menyimpan project, stage, chat, atau generated RPP.
- FastAPI tidak membuat PDF/DOCX.
- NestJS tetap menjadi pemilik data aplikasi.
- NestJS menyimpan hasil AI ke Supabase.
- NestJS/frontend mengurus template dokumen.
- FAISS menyimpan vector index.
- Supabase/PostgreSQL menyimpan metadata CP jika dibutuhkan.
- Semua endpoint FastAPI harus dilindungi `INTERNAL_API_KEY`.
- Logic AI dipisahkan berdasarkan `rppType`.
- Developer 1 fokus pada AI Intrakurikuler.
- Developer 2 fokus pada AI PjBL Kokurikuler.
- Recommendation hanya tersedia untuk Stage 2.
- Stage 2 Intrakurikuler menggunakan CP dari RAG sebagai referensi untuk menghasilkan Alur Tujuan Pembelajaran.
- Stage 2 PjBL menggunakan semua konteks dari Stage 1 untuk menghasilkan rekomendasi proyek yang akan dilakukan.
