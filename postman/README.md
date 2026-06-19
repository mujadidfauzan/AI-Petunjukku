# Postman Testing

Import these two files into Postman:

- `petunjukku-ai-service.postman_collection.json`
- `petunjukku-ai-service-local.postman_environment.json`

Select environment `Petunjukku AI Service - Local`, then adjust:

- `base_url`: default `http://127.0.0.1:8000`
- `internal_api_key`: must match `INTERNAL_API_KEY` in `.env`
- `document_path`: only needed for `POST /internal/rag/index-documents`

## Try Branch Fahmi

```bash
git switch -c fahmi --track origin/fahmi
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Use the folder `AI - Intrakurikuler` to test the main changes in this branch.

## Try Branch Robby

```bash
git switch -c robby --track origin/robby
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Use the folder `AI - PjBL Kokurikuler`, especially:

- `Theme Recommendation`
- `Project Recommendation`

## Notes

- All routes are under `/internal`.
- Every request sends `X-Internal-API-Key`.
- `POST /internal/ai/recommend-stage` only accepts `targetStage.stageNumber = 2`.
- Without `OPENROUTER_API_KEY`, the service returns fallback/mock outputs from the code.
