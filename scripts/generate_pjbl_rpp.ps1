param(
    [string]$ResultsDir = "postman/flows/pjbl-results",
    [switch]$UseLlm,
    [switch]$ViaHttp,
    [string]$BaseUrl = "http://localhost:8000",
    [string]$ApiKey = ""
)

$ErrorActionPreference = "Stop"

function Read-JsonFile {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path)) {
        throw "File tidak ditemukan: $Path"
    }
    return Get-Content -LiteralPath $Path -Raw | ConvertFrom-Json
}

function Write-JsonFile {
    param(
        [string]$Path,
        [object]$Value
    )
    $Value | ConvertTo-Json -Depth 100 | Set-Content -LiteralPath $Path -Encoding UTF8
}

function Read-InternalApiKey {
    if (-not (Test-Path -LiteralPath ".env")) {
        return ""
    }
    $line = Get-Content ".env" | Where-Object { $_ -match "^\s*INTERNAL_API_KEY\s*=" } | Select-Object -First 1
    if (-not $line) {
        return ""
    }
    return (($line -replace "^\s*INTERNAL_API_KEY\s*=", "").Trim().Trim('"').Trim("'"))
}

$stage1Path = Join-Path $ResultsDir "01-stage1.content.json"
$stage2Path = Join-Path $ResultsDir "02b-stage2-selected-project.content.json"
$summaryPath = Join-Path $ResultsDir "05-kina-summary.response.json"
$requestPath = Join-Path $ResultsDir "07-generate-rpp.request.json"
$responsePath = Join-Path $ResultsDir "08-generate-rpp.response.json"

$stage1 = Read-JsonFile $stage1Path
$stage2 = Read-JsonFile $stage2Path
$summaryResponse = if (Test-Path -LiteralPath $summaryPath) {
    Read-JsonFile $summaryPath
} else {
    [pscustomobject]@{ summary = @{} }
}

$stage1Content = $stage1.contentJson
$stage2Content = $stage2
$selectedTitle = $stage2Content.selectedProjectTitle
if (-not $selectedTitle) {
    $selectedTitle = $stage2Content.recommendedProjectTitle
}
if (-not $selectedTitle) {
    $selectedTitle = "RPP PjBL Kokurikuler"
}

$schoolContext = $stage1Content.schoolContext
$classContext = $stage1Content.classContext
$summary = $summaryResponse.summary
if (-not $summary) {
    $summary = @{}
}

$payload = [ordered]@{
    project = [ordered]@{
        id = "pjbl-generated-from-flow"
        title = $selectedTitle
        rppType = "pjbl_kokurikuler"
        subject = "Projek Penguatan Profil Pelajar Pancasila"
        phase = "Fase D"
        gradeLevel = $classContext.className
    }
    teacherProfile = [ordered]@{
        fullName = "Guru PJBL"
        position = "Guru"
        educationLevel = "SMP"
    }
    school = [ordered]@{
        name = $schoolContext.name
        city = $schoolContext.city
        schoolEnvironment = $schoolContext.environment
        availableFacilities = $schoolContext.facilities
        localContext = $schoolContext.localContext
    }
    teacherSubject = [ordered]@{
        subjectName = "Projek Penguatan Profil Pelajar Pancasila"
        gradeLevel = $classContext.className
    }
    teacherClass = [ordered]@{
        className = $classContext.className
        studentCount = $classContext.studentCount
        studentCharacteristics = $classContext.studentCharacteristics
        learningChallenges = $classContext.learningChallenges
        dominantLearningStyle = $classContext.dominantLearningStyle
    }
    stages = @(
        [ordered]@{
            stageNumber = 1
            stageName = $stage1.stageName
            contentJson = $stage1Content
        },
        [ordered]@{
            stageNumber = 2
            stageName = "Rekomendasi Proyek Terpilih"
            contentJson = $stage2Content
        }
    )
    kinaChatSummary = $summary
    options = [ordered]@{
        output = "contentJson dan contentMarkdown"
    }
}

Write-JsonFile $requestPath $payload
Write-Host "Payload RPP PJBL disimpan: $requestPath"

if ($ViaHttp) {
    if (-not $ApiKey) {
        $ApiKey = Read-InternalApiKey
    }
    if (-not $ApiKey) {
        throw "INTERNAL_API_KEY tidak ditemukan. Isi .env atau jalankan script dengan -ApiKey."
    }
    $body = Get-Content -LiteralPath $requestPath -Raw
    $response = Invoke-RestMethod `
        -Method Post `
        -Uri "$BaseUrl/internal/ai/generate-rpp" `
        -Headers @{ "X-Internal-API-Key" = $ApiKey } `
        -ContentType "application/json" `
        -Body $body
    Write-JsonFile $responsePath $response
} else {
    if (-not $UseLlm) {
        $env:LLM_PROVIDER = "local"
        $env:OPENROUTER_API_KEY = ""
    }
    $env:PJBL_RPP_REQUEST_PATH = (Resolve-Path -LiteralPath $requestPath).Path
    $env:PJBL_RPP_RESPONSE_PATH = (Join-Path (Resolve-Path -LiteralPath $ResultsDir).Path "08-generate-rpp.response.json")

    @'
import asyncio
import json
import os

from app.schemas.generate_rpp_schema import GenerateRppRequest
from app.services.ai_orchestrator_service import AIOrchestratorService


async def main() -> None:
    request_path = os.environ["PJBL_RPP_REQUEST_PATH"]
    response_path = os.environ["PJBL_RPP_RESPONSE_PATH"]
    with open(request_path, "r", encoding="utf-8-sig") as handle:
        request_data = json.load(handle)
    payload = GenerateRppRequest(**request_data)
    response = await AIOrchestratorService().generate_rpp(payload)
    with open(response_path, "w", encoding="utf-8") as handle:
        json.dump(response.model_dump(), handle, ensure_ascii=False, indent=2)


asyncio.run(main())
'@ | python -
}

Write-Host "RPP PJBL berhasil dibuat: $responsePath"
