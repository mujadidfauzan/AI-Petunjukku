param(
    [string]$BaseUrl = "http://localhost:8000",
    [string]$ApiKey = "",
    [string]$Stage2RequestPath = "postman/flows/pjbl-stage2-recommendation.request.json",
    [string]$OutputDir = "postman/flows/pjbl-results",
    [int]$SelectedProjectIndex = 1,
    [string]$KinaMessage = "Saya ingin mematangkan produk akhir proyek ini. Produk apa yang paling realistis untuk siswa kelas VII?"
)

$ErrorActionPreference = "Stop"

function Resolve-RepoPath {
    param([string]$Path)

    if ([System.IO.Path]::IsPathRooted($Path)) {
        return $Path
    }

    return Join-Path (Join-Path $PSScriptRoot "..") $Path
}

function Read-InternalApiKey {
    $envPath = Resolve-RepoPath ".env"
    if (-not (Test-Path $envPath)) {
        return ""
    }

    $line = Get-Content $envPath | Where-Object { $_ -match "^\s*INTERNAL_API_KEY\s*=" } | Select-Object -First 1
    if (-not $line) {
        return ""
    }

    return (($line -replace "^\s*INTERNAL_API_KEY\s*=", "").Trim().Trim('"').Trim("'"))
}

function Save-Json {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string]$Path
    )

    $Value | ConvertTo-Json -Depth 40 | Set-Content -Path $Path -Encoding UTF8
}

function New-SelectedStageTwoContent {
    param(
        [Parameter(Mandatory = $true)]$Recommendations,
        [Parameter(Mandatory = $true)][int]$SelectedIndex
    )

    $projects = @($Recommendations.projectRecommendations)
    if ($projects.Count -eq 0) {
        throw "Response Stage 2 tidak memiliki projectRecommendations."
    }

    if ($SelectedIndex -lt 1 -or $SelectedIndex -gt $projects.Count) {
        throw "SelectedProjectIndex harus di antara 1 sampai $($projects.Count)."
    }

    $selectedProject = $projects[$SelectedIndex - 1]
    $selectedTitle = $selectedProject.recommendedProjectTitle

    return [ordered]@{
        selectedProjectIndex = $SelectedIndex
        selectedProjectTitle = $selectedTitle
        selectedProjectRecommendation = $selectedProject
        recommendedProjectTitle = $selectedTitle
        projectTheme = $selectedProject.projectTheme
        projectFocus = $selectedProject.projectFocus
        projectBackground = $selectedProject.projectBackground
        projectObjectives = $selectedProject.projectObjectives
        drivingQuestion = $selectedProject.drivingQuestion
        studentProduct = $selectedProject.studentProduct
        projectActivitiesOverview = $selectedProject.projectActivitiesOverview
        feasibilityNotes = $selectedProject.feasibilityNotes
        riskMitigation = $selectedProject.riskMitigation
        projectRecommendations = $Recommendations.projectRecommendations
        projectTitleOptions = $Recommendations.projectTitleOptions
        selectionNote = "Dipilih untuk diskusi Kina Chat dari hasil rekomendasi Stage 2."
    }
}

if (-not $ApiKey) {
    $ApiKey = Read-InternalApiKey
}

if (-not $ApiKey) {
    throw "INTERNAL_API_KEY tidak ditemukan. Isi .env atau jalankan script dengan -ApiKey."
}

$stage2RequestFullPath = Resolve-RepoPath $Stage2RequestPath
$outputFullDir = Resolve-RepoPath $OutputDir
New-Item -ItemType Directory -Force -Path $outputFullDir | Out-Null

$headers = @{
    "X-Internal-API-Key" = $ApiKey
}
$jsonHeaders = @{
    "X-Internal-API-Key" = $ApiKey
    "Content-Type" = "application/json"
}

Write-Host "[1/3] Health check: $BaseUrl/internal/health"
$health = Invoke-RestMethod -Uri "$BaseUrl/internal/health" -Method Get -Headers $headers
Save-Json $health (Join-Path $outputFullDir "01-health.response.json")
Write-Host "      OK - service=$($health.service), llm=$($health.llm)"

Write-Host "[2/3] PJBL Stage 2 recommendation"
$stage2RequestRaw = Get-Content $stage2RequestFullPath -Raw
$stage2Request = $stage2RequestRaw | ConvertFrom-Json
$stage2Response = Invoke-RestMethod `
    -Uri "$BaseUrl/internal/ai/recommend-stage" `
    -Method Post `
    -Headers $jsonHeaders `
    -Body $stage2RequestRaw
Save-Json $stage2Response (Join-Path $outputFullDir "02-stage2-recommendation.response.json")
Write-Host "      OK - recommendationType=$($stage2Response.recommendationType), targetStage=$($stage2Response.targetStageNumber)"

Write-Host "[3/3] PJBL Kina Chat"
$stage2SelectedContent = New-SelectedStageTwoContent `
    -Recommendations $stage2Response.recommendations `
    -SelectedIndex $SelectedProjectIndex
Save-Json $stage2SelectedContent (Join-Path $outputFullDir "02b-stage2-selected-project.content.json")
Write-Host "      Selected project #$SelectedProjectIndex - $($stage2SelectedContent.selectedProjectTitle)"

$kinaRequest = [ordered]@{
    project = $stage2Request.project
    stages = @(
        $stage2Request.previousStages[0],
        [ordered]@{
            stageNumber = 2
            stageName = "Proyek Terpilih"
            contentJson = $stage2SelectedContent
        }
    )
    chatHistory = @()
    message = $KinaMessage
}
$kinaRequestJson = $kinaRequest | ConvertTo-Json -Depth 40
$kinaRequestPath = Join-Path $outputFullDir "03-kina-chat.request.json"
$kinaRequestJson | Set-Content -Path $kinaRequestPath -Encoding UTF8

$kinaResponse = Invoke-RestMethod `
    -Uri "$BaseUrl/internal/ai/kina-chat" `
    -Method Post `
    -Headers $jsonHeaders `
    -Body $kinaRequestJson
Save-Json $kinaResponse (Join-Path $outputFullDir "04-kina-chat.response.json")
Write-Host "      OK - reply:"
Write-Host $kinaResponse.reply

Write-Host ""
Write-Host "Hasil tersimpan di: $outputFullDir"
Write-Host "- 01-health.response.json"
Write-Host "- 02-stage2-recommendation.response.json"
Write-Host "- 02b-stage2-selected-project.content.json"
Write-Host "- 03-kina-chat.request.json"
Write-Host "- 04-kina-chat.response.json"
