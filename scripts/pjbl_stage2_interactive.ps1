param(
    [string]$BaseUrl = "http://localhost:8000",
    [string]$ApiKey = "",
    [string]$Stage2RequestPath = "postman/flows/pjbl-stage2-recommendation.request.json",
    [string]$OutputDir = "postman/flows/pjbl-results",
    [int]$SelectedThemeIndex = 0,
    [int]$SelectedProjectIndex = 0,
    [switch]$UseDefaults
)

$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
$OutputEncoding = [Console]::OutputEncoding

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

    ConvertTo-Json -InputObject $Value -Depth 60 | Set-Content -Path $Path -Encoding UTF8
}

function Show-JsonPreview {
    param(
        [Parameter(Mandatory = $true)][string]$Title,
        [Parameter(Mandatory = $true)]$Value
    )

    Write-Host ""
    Write-Host "=== $Title ==="
    ConvertTo-Json -InputObject $Value -Depth 30
    Write-Host "=== end $Title ==="
}

function Ask-Int {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][int]$Default
    )

    if ($UseDefaults) {
        Write-Host "$Label [$Default]"
        return $Default
    }

    $value = Read-Host "$Label [$Default]"
    if (-not $value.Trim()) {
        return $Default
    }

    $number = 0
    if ([int]::TryParse($value, [ref]$number)) {
        return $number
    }
    return $Default
}

function Copy-JsonObject {
    param([Parameter(Mandatory = $true)]$Value)

    return $Value | ConvertTo-Json -Depth 60 | ConvertFrom-Json
}

function Show-ThemeOptions {
    param([Parameter(Mandatory = $true)]$Recommendations)

    $themes = @($Recommendations.themes)
    if ($themes.Count -eq 0) {
        throw "Response rekomendasi tema tidak memiliki themes."
    }

    Write-Host ""
    Write-Host "Saran tema Stage 2:"
    for ($index = 0; $index -lt $themes.Count; $index++) {
        Write-Host "$($index + 1). $($themes[$index])"
    }

    return $themes
}

function Show-ProjectOptions {
    param([Parameter(Mandatory = $true)]$Recommendations)

    $projects = @($Recommendations.projectRecommendations)
    if ($projects.Count -eq 0) {
        throw "Response Stage 2 tidak memiliki projectRecommendations."
    }

    Write-Host ""
    Write-Host "Saran proyek Stage 2:"
    for ($index = 0; $index -lt $projects.Count; $index++) {
        $project = $projects[$index]
        Write-Host ""
        Write-Host "$($index + 1). $($project.recommendedProjectTitle)"
        Write-Host "   Tema: $($project.projectTheme)"
        Write-Host "   Fokus: $($project.projectFocus)"
        Write-Host "   Produk: $(@($project.studentProduct) -join ', ')"
        Write-Host "   Pertanyaan: $($project.drivingQuestion)"
    }

    return $projects
}

function New-SelectedStageTwoContent {
    param(
        [Parameter(Mandatory = $true)]$Recommendations,
        [Parameter(Mandatory = $true)][int]$SelectedIndex
    )

    $projects = @($Recommendations.projectRecommendations)
    if ($SelectedIndex -lt 1 -or $SelectedIndex -gt $projects.Count) {
        throw "Pilihan proyek harus di antara 1 sampai $($projects.Count)."
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
        selectionNote = "Dipilih dari terminal interaktif Stage 2."
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

if (-not (Test-Path $stage2RequestFullPath)) {
    throw "Payload Stage 2 tidak ditemukan: $stage2RequestFullPath. Jalankan scripts\pjbl_stage1_interactive.ps1 dulu."
}

$headers = @{
    "X-Internal-API-Key" = $ApiKey
}
$jsonHeaders = @{
    "X-Internal-API-Key" = $ApiKey
    "Content-Type" = "application/json"
}

Write-Host "PJBL Stage 2 only"
Write-Host "Script ini membaca payload dari Stage 1, meminta rekomendasi tema, memilih tema, lalu meminta rekomendasi proyek."
Write-Host ""

$health = Invoke-RestMethod -Uri "$BaseUrl/internal/health" -Method Get -Headers $headers
Write-Host "Service OK: $($health.service), llm=$($health.llm)"

$stage2RequestRaw = Get-Content $stage2RequestFullPath -Raw
$stage2Request = $stage2RequestRaw | ConvertFrom-Json

Write-Host ""
Write-Host "Project: $($stage2Request.project.title)"
Write-Host "Stage 1 issue: $($stage2Request.previousStages[0].contentJson.localIssue)"
Write-Host "Target Stage 2 topic: $($stage2Request.targetStage.topic)"
Show-JsonPreview "Input Stage 2 dari Stage 1" $stage2Request
Save-Json $stage2Request (Join-Path $outputFullDir "02-stage2.input-from-stage1.json")
Write-Host ""
Write-Host "[1/2] Memanggil rekomendasi tema Stage 2..."

$themeRequest = Copy-JsonObject $stage2Request
$themeRequest.targetStage.recommendationType = "project_theme_recommendation"
$themeRequest.targetStage.PSObject.Properties.Remove("selectedTheme")
$themeRequestJson = ConvertTo-Json -InputObject $themeRequest -Depth 60
Show-JsonPreview "Input rekomendasi tema" $themeRequest
Save-Json $themeRequest (Join-Path $outputFullDir "02a-theme-recommendation.request.json")

$themeResponse = Invoke-RestMethod `
    -Uri "$BaseUrl/internal/ai/recommend-stage" `
    -Method Post `
    -Headers $jsonHeaders `
    -Body $themeRequestJson

$themeResponsePath = Join-Path $outputFullDir "02-stage2-theme-recommendation.response.json"
Save-Json $themeResponse $themeResponsePath
Write-Host "Response rekomendasi tema tersimpan: $themeResponsePath"

$themes = Show-ThemeOptions $themeResponse.recommendations
if ($SelectedThemeIndex -lt 1) {
    $SelectedThemeIndex = Ask-Int "Pilih nomor tema untuk rekomendasi proyek" 1
}
if ($SelectedThemeIndex -lt 1 -or $SelectedThemeIndex -gt $themes.Count) {
    throw "Pilihan tema harus di antara 1 sampai $($themes.Count)."
}
$selectedTheme = $themes[$SelectedThemeIndex - 1]

Write-Host ""
Write-Host "Tema terpilih: $selectedTheme"
Write-Host ""
Write-Host "[2/2] Memanggil rekomendasi proyek berdasarkan tema terpilih..."

$projectRequest = Copy-JsonObject $stage2Request
$projectRequest.targetStage.recommendationType = "project_recommendation"
$projectRequest.targetStage.selectedTheme = $selectedTheme
$projectRequestJson = ConvertTo-Json -InputObject $projectRequest -Depth 60
Show-JsonPreview "Input rekomendasi proyek" $projectRequest
Save-Json $projectRequest (Join-Path $outputFullDir "02b-project-recommendation.request.json")
Save-Json $projectRequest $stage2RequestFullPath

$stage2Response = Invoke-RestMethod `
    -Uri "$BaseUrl/internal/ai/recommend-stage" `
    -Method Post `
    -Headers $jsonHeaders `
    -Body $projectRequestJson

$stage2ResponsePath = Join-Path $outputFullDir "02-stage2-recommendation.response.json"
Save-Json $stage2Response $stage2ResponsePath
Write-Host "Response rekomendasi proyek tersimpan: $stage2ResponsePath"

$projects = Show-ProjectOptions $stage2Response.recommendations
if ($SelectedProjectIndex -lt 1) {
    $SelectedProjectIndex = Ask-Int "Pilih nomor proyek untuk diskusi Kina" 1
}

$selectedContent = New-SelectedStageTwoContent `
    -Recommendations $stage2Response.recommendations `
    -SelectedIndex $SelectedProjectIndex
$selectedPath = Join-Path $outputFullDir "02b-stage2-selected-project.content.json"
Save-Json $selectedContent $selectedPath

Save-Json @() (Join-Path $outputFullDir "kina-chat-history.json")

Write-Host ""
Write-Host "Project terpilih: $($selectedContent.selectedProjectTitle)"
Write-Host "Stage 2 terpilih tersimpan: $selectedPath"
Write-Host ""
Write-Host "Lanjut chat Kina dengan:"
Write-Host "powershell -ExecutionPolicy Bypass -File scripts\chat_pjbl_kina.ps1 -Reset"
