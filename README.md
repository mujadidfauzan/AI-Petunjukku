# Kina MVP Backend

MVP backend untuk flow:

`Data Dummy Stage 1-2 -> Chatbot Kina/OpenRouter -> Stage 3 -> Stage 4 -> Stage 5 Generate Document`

## 1. Setup

```bash
cd kina_mvp_backend
python -m venv .venv
source .venv/bin/activate  # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env       # Windows PowerShell: copy .env.example .env
```

Isi `OPENROUTER_API_KEY` di `.env` kalau ingin memakai OpenRouter sungguhan. Kalau kosong, sistem tetap jalan dengan mock LLM.

## 2. Jalankan server

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Buka:

```text
http://localhost:8000/docs
```

## 3. Test via curl

### Health check

```bash
curl http://localhost:8000/health
```

### Stage 3 - Chat Kina

```bash
curl -X POST http://localhost:8000/kina/chat \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "demo-project-001",
    "message_text": "Saya ingin aktivitas pembelajaran yang sederhana, aktif, dan berbasis diskusi kelompok.",
    "current_stage": 3,
    "use_ai_generation": true
  }'
```

### Lihat planning_state

```bash
curl http://localhost:8000/planning-state/demo-project-001
```

### Stage 4 - Simpan asesmen

```bash
curl -X POST http://localhost:8000/stage-4/save \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "demo-project-001",
    "jenis_asesmen": "Formatif",
    "teknik_penilaian": ["Observasi diskusi", "Penilaian LKPD"],
    "alat_bahan": ["LKPD", "Papan tulis", "Kartu soal"],
    "media_pembelajaran": ["Tabel perbandingan", "Contoh kasus harga barang"],
    "refleksi_siswa": "Apa strategi yang paling membantu saya menyelesaikan soal perbandingan senilai?",
    "refleksi_guru": "Apakah siswa mampu menghubungkan rasio dengan situasi nyata?"
  }'
```

### Stage 5 - Generate dokumen

```bash
curl -X POST http://localhost:8000/ai/generate-document \
  -H "Content-Type: application/json" \
  -d '{
    "project_id": "demo-project-001",
    "output_type": "lkpd"
  }'
```

## 4. Test via PowerShell

```powershell
$body = @{
  project_id = "demo-project-001"
  message_text = "Saya ingin aktivitas pembelajaran yang sederhana, aktif, dan berbasis diskusi kelompok."
  current_stage = 3
  use_ai_generation = $true
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "http://localhost:8000/kina/chat" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

```powershell
$body = @{
  project_id = "demo-project-001"
  jenis_asesmen = "Formatif"
  teknik_penilaian = @("Observasi diskusi", "Penilaian LKPD")
  alat_bahan = @("LKPD", "Papan tulis", "Kartu soal")
  media_pembelajaran = @("Tabel perbandingan", "Contoh kasus harga barang")
  refleksi_siswa = "Apa strategi yang paling membantu saya menyelesaikan soal perbandingan senilai?"
  refleksi_guru = "Apakah siswa mampu menghubungkan rasio dengan situasi nyata?"
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "http://localhost:8000/stage-4/save" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```

```powershell
$body = @{
  project_id = "demo-project-001"
  output_type = "lkpd"
} | ConvertTo-Json

Invoke-RestMethod `
  -Uri "http://localhost:8000/ai/generate-document" `
  -Method Post `
  -ContentType "application/json" `
  -Body $body
```
