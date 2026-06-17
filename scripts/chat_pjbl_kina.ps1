param(
    [string]$BaseUrl = "http://localhost:8000",
    [string]$ApiKey = "",
    [string]$Stage2RequestPath = "postman/flows/pjbl-stage2-recommendation.request.json",
    [string]$SelectedProjectPath = "postman/flows/pjbl-results/02b-stage2-selected-project.content.json",
    [string]$OutputDir = "postman/flows/pjbl-results",
    [int]$SelectedProjectIndex = 1,
    [switch]$RefreshStage2,
    [switch]$Reset,
    [string]$OnceMessage = ""
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

function Read-JsonFile {
    param([Parameter(Mandatory = $true)][string]$Path)

    return Get-Content $Path -Raw | ConvertFrom-Json
}

function Save-Json {
    param(
        [Parameter(Mandatory = $true)]$Value,
        [Parameter(Mandatory = $true)][string]$Path
    )

    ConvertTo-Json -InputObject $Value -Depth 50 | Set-Content -Path $Path -Encoding UTF8
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

function Read-ChatHistory {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path $Path)) {
        return @()
    }

    $raw = (Get-Content $Path -Raw).Trim()
    if (-not $raw) {
        return @()
    }

    $history = $raw | ConvertFrom-Json
    if (-not $history) {
        return @()
    }

    return @($history)
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

function Ensure-SelectedProjectContent {
    param(
        [Parameter(Mandatory = $true)]$Stage2RequestRaw,
        [Parameter(Mandatory = $true)]$SelectedProjectFullPath,
        [Parameter(Mandatory = $true)]$JsonHeaders,
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [Parameter(Mandatory = $true)][int]$SelectedProjectIndex,
        [Parameter(Mandatory = $true)][bool]$RefreshStage2
    )

    if ((Test-Path $SelectedProjectFullPath) -and -not $RefreshStage2) {
        return Read-JsonFile $SelectedProjectFullPath
    }

    Write-Host "Membuat ulang Stage 2 recommendation untuk memilih project #$SelectedProjectIndex..."
    $stage2Response = Invoke-RestMethod `
        -Uri "$BaseUrl/internal/ai/recommend-stage" `
        -Method Post `
        -Headers $JsonHeaders `
        -Body $Stage2RequestRaw

    $responsePath = Join-Path (Split-Path $SelectedProjectFullPath -Parent) "02-stage2-recommendation.response.json"
    Save-Json $stage2Response $responsePath

    $selectedContent = New-SelectedStageTwoContent `
        -Recommendations $stage2Response.recommendations `
        -SelectedIndex $SelectedProjectIndex
    Save-Json $selectedContent $SelectedProjectFullPath
    return $selectedContent
}

function Invoke-KinaTurn {
    param(
        [Parameter(Mandatory = $true)]$Project,
        [Parameter(Mandatory = $true)]$StageOne,
        [Parameter(Mandatory = $true)]$StageTwoContent,
        [Parameter(Mandatory = $true)]$ChatHistory,
        [Parameter(Mandatory = $true)][string]$Message,
        [Parameter(Mandatory = $true)]$JsonHeaders,
        [Parameter(Mandatory = $true)][string]$BaseUrl,
        [Parameter(Mandatory = $true)][string]$OutputFullDir
    )

    $request = [ordered]@{
        project = $Project
        stages = @(
            $StageOne,
            [ordered]@{
                stageNumber = 2
                stageName = "Proyek Terpilih"
                contentJson = $StageTwoContent
            }
        )
        chatHistory = @($ChatHistory)
        message = $Message
    }

    $requestPath = Join-Path $OutputFullDir "kina-chat.latest.request.json"
    $requestJson = ConvertTo-Json -InputObject $request -Depth 50
    $requestJson | Set-Content -Path $requestPath -Encoding UTF8
    Show-JsonPreview "Input Kina Chat" $request

    $response = Invoke-RestMethod `
        -Uri "$BaseUrl/internal/ai/kina-chat" `
        -Method Post `
        -Headers $JsonHeaders `
        -Body $requestJson

    Save-Json $response (Join-Path $OutputFullDir "kina-chat.latest.response.json")
    return $response
}

function Show-History {
    param($ChatHistory)

    $items = @($ChatHistory)
    if ($items.Count -eq 0) {
        Write-Host "Belum ada riwayat chat."
        return
    }

    Write-Host ""
    Write-Host "Riwayat terakhir:"
    foreach ($item in ($items | Select-Object -Last 8)) {
        $label = if ($item.role -eq "assistant") { "Kina" } else { "Guru" }
        Write-Host "${label}: $($item.message)"
    }
}

function Get-KinaInfoPoints {
    return @(
        [ordered]@{
            key = "focusScope"
            label = "Fokus dan ruang lingkup proyek"
            patterns = @("fokus proyek", "pemetaan jenis", "lokasi sampah", "sumber sampah", "sumber masalah", "masalah.*dominan")
            excludes = @("risiko", "mitigasi", "asesmen", "rubrik")
        },
        [ordered]@{
            key = "finalProduct"
            label = "Produk atau aksi akhir"
            patterns = @("produk akhir", "aksi akhir", "poster infografis", "berbentuk peta temuan")
            excludes = @("asesmen", "rubrik", "kriteria")
        },
        [ordered]@{
            key = "activitiesSchedule"
            label = "Alur kegiatan dan jadwal"
            patterns = @("alur kegiatan", "jadwal", "durasi", "2 x 35", "pembukaan dan pembagian", "menyusun peta temuan")
            excludes = @("asesmen menggunakan", "rubrik")
        },
        [ordered]@{
            key = "rolesSupport"
            label = "Pembagian peran dan pendampingan"
            patterns = @("peran", "kelompok berisi", "ketua", "pencatat", "penanda", "penyaji", "lembar cek", "memantau")
            excludes = @("risiko", "mitigasi")
        },
        [ordered]@{
            key = "facilitiesPartnership"
            label = "Fasilitas, teknologi, dan kemitraan"
            patterns = @("fasilitas", "teknologi", "proyek dilakukan tanpa mitra", "tanpa mitra", "mitra luar", "alat yang digunakan", "fasilitas yang digunakan")
            excludes = @()
        },
        [ordered]@{
            key = "riskMitigation"
            label = "Risiko dan mitigasi"
            patterns = @("risiko", "mitigasi", "tidak konsisten", "keluar dari area", "timer", "batas area", "lembar observasi seragam", "cek kemajuan")
            excludes = @()
        },
        [ordered]@{
            key = "assessmentReflection"
            label = "Asesmen, presentasi, dan refleksi"
            patterns = @("asesmen", "penilaian", "rubrik", "kriteria", "kontribusi individu", "presentasi", "refleksi")
            excludes = @("produk akhir", "alur kegiatan", "durasi", "pembukaan", "observasi area")
        }
    )
}

function Test-KinaInfoPoint {
    param(
        [Parameter(Mandatory = $true)]$Point,
        [string[]]$Messages = @()
    )

    foreach ($message in $Messages) {
        $text = $message.ToLowerInvariant()
        $excluded = $false
        foreach ($exclude in @($Point.excludes)) {
            if ($exclude -and $text -match $exclude) {
                $excluded = $true
                break
            }
        }
        if ($excluded) {
            continue
        }

        foreach ($pattern in @($Point.patterns)) {
            if ($pattern -and $text -match $pattern) {
                return $true
            }
        }
    }

    return $false
}

function Get-KinaProgress {
    param(
        [Parameter(Mandatory = $true)]$ChatHistory,
        [string]$PendingMessage = ""
    )

    $teacherMessages = @(
        @($ChatHistory) |
            Where-Object { $_.role -eq "user" } |
            ForEach-Object { [string]$_.message }
    )
    if ($PendingMessage.Trim()) {
        $teacherMessages += $PendingMessage.Trim()
    }

    $points = @()
    foreach ($point in Get-KinaInfoPoints) {
        $completed = Test-KinaInfoPoint -Point $point -Messages $teacherMessages
        $points += [ordered]@{
            key = $point.key
            label = $point.label
            completed = $completed
        }
    }

    $completedCount = @($points | Where-Object { $_.completed }).Count
    $totalCount = @($points).Count
    $percent = if ($totalCount -gt 0) {
        [math]::Round(($completedCount / $totalCount) * 100)
    } else {
        0
    }

    return [ordered]@{
        completedCount = $completedCount
        totalCount = $totalCount
        percent = $percent
        completed = @($points | Where-Object { $_.completed } | ForEach-Object { $_.label })
        missing = @($points | Where-Object { -not $_.completed } | ForEach-Object { $_.label })
        points = $points
    }
}

function Show-KinaProgress {
    param([Parameter(Mandatory = $true)]$Progress)

    Write-Host ""
    Write-Host "Progres informasi Kina: $($Progress.percent)% ($($Progress.completedCount)/$($Progress.totalCount))"
    foreach ($point in @($Progress.points)) {
        $mark = if ($point.completed) { "[x]" } else { "[ ]" }
        Write-Host "$mark $($point.label)"
    }
    Write-Host ""
}

if (-not $ApiKey) {
    $ApiKey = Read-InternalApiKey
}

if (-not $ApiKey) {
    throw "INTERNAL_API_KEY tidak ditemukan. Isi .env atau jalankan script dengan -ApiKey."
}

$stage2RequestFullPath = Resolve-RepoPath $Stage2RequestPath
$selectedProjectFullPath = Resolve-RepoPath $SelectedProjectPath
$outputFullDir = Resolve-RepoPath $OutputDir
$historyPath = Join-Path $outputFullDir "kina-chat-history.json"
$transcriptPath = Join-Path $outputFullDir "kina-chat-transcript.json"
$progressPath = Join-Path $outputFullDir "kina-chat-progress.json"
New-Item -ItemType Directory -Force -Path $outputFullDir | Out-Null

$headers = @{
    "X-Internal-API-Key" = $ApiKey
}
$jsonHeaders = @{
    "X-Internal-API-Key" = $ApiKey
    "Content-Type" = "application/json"
}

$stage2RequestRaw = Get-Content $stage2RequestFullPath -Raw
$stage2Request = $stage2RequestRaw | ConvertFrom-Json
$stageOne = $stage2Request.previousStages[0]

$health = Invoke-RestMethod -Uri "$BaseUrl/internal/health" -Method Get -Headers $headers
Write-Host "Service OK: $($health.service), llm=$($health.llm)"

$stageTwoContent = Ensure-SelectedProjectContent `
    -Stage2RequestRaw $stage2RequestRaw `
    -SelectedProjectFullPath $selectedProjectFullPath `
    -JsonHeaders $jsonHeaders `
    -BaseUrl $BaseUrl `
    -SelectedProjectIndex $SelectedProjectIndex `
    -RefreshStage2 ([bool]$RefreshStage2)

if ($Reset) {
    Save-Json @() $historyPath
    Save-Json (Get-KinaProgress -ChatHistory @()) $progressPath
}

$chatHistory = @(Read-ChatHistory $historyPath)
$progress = Get-KinaProgress -ChatHistory $chatHistory
Save-Json $progress $progressPath
Write-Host "Project terpilih: $($stageTwoContent.selectedProjectTitle)"
Write-Host "History tersimpan di: $historyPath"
Write-Host "Progres tersimpan di: $progressPath"
Show-KinaProgress $progress
Write-Host ""
Write-Host "Ketik pesan guru lalu Enter."
Write-Host "Command: /exit, /reset, /history, /project, /progress"
Write-Host ""

while ($true) {
    if ($OnceMessage) {
        $message = $OnceMessage
        $OnceMessage = ""
        Write-Host "Guru: $message"
    } else {
        $message = Read-Host "Guru"
    }

    if (-not $message.Trim()) {
        if (-not $OnceMessage) {
            continue
        }
    }

    $command = $message.Trim().ToLowerInvariant()
    if ($command -eq "/exit") {
        Write-Host "Selesai."
        break
    }
    if ($command -eq "/reset") {
        $chatHistory = @()
        Save-Json @() $historyPath
        $progress = Get-KinaProgress -ChatHistory $chatHistory
        Save-Json $progress $progressPath
        Write-Host "Riwayat chat direset."
        Show-KinaProgress $progress
        continue
    }
    if ($command -eq "/history") {
        Show-History $chatHistory
        continue
    }
    if ($command -eq "/project") {
        Write-Host "Project terpilih: $($stageTwoContent.selectedProjectTitle)"
        Write-Host "Driving question: $($stageTwoContent.drivingQuestion)"
        continue
    }
    if ($command -eq "/progress") {
        $progress = Get-KinaProgress -ChatHistory $chatHistory
        Save-Json $progress $progressPath
        Show-KinaProgress $progress
        continue
    }

    $previewProgress = Get-KinaProgress -ChatHistory $chatHistory -PendingMessage $message
    Show-KinaProgress $previewProgress

    $response = Invoke-KinaTurn `
        -Project $stage2Request.project `
        -StageOne $stageOne `
        -StageTwoContent $stageTwoContent `
        -ChatHistory $chatHistory `
        -Message $message `
        -JsonHeaders $jsonHeaders `
        -BaseUrl $BaseUrl `
        -OutputFullDir $outputFullDir

    Write-Host ""
    Write-Host "Kina:"
    Write-Host $response.reply
    Write-Host ""

    $chatHistory += [ordered]@{
        role = "user"
        message = $message
    }
    $chatHistory += [ordered]@{
        role = "assistant"
        message = $response.reply
    }

    $progress = Get-KinaProgress -ChatHistory $chatHistory
    Save-Json @($chatHistory) $historyPath
    Save-Json $progress $progressPath
    Save-Json ([ordered]@{
        project = $stage2Request.project
        selectedProject = $stageTwoContent
        progress = $progress
        chatHistory = @($chatHistory)
    }) $transcriptPath
    Show-KinaProgress $progress

    if (-not $OnceMessage -and $PSBoundParameters.ContainsKey("OnceMessage")) {
        break
    }
}
