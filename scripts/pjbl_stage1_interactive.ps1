param(
    [string]$OutputDir = "postman/flows/pjbl-results",
    [string]$Stage2RequestPath = "postman/flows/pjbl-stage2-recommendation.request.json",
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

function Ask-Text {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][string]$Default
    )

    if ($UseDefaults) {
        Write-Host "$Label [$Default]"
        return $Default
    }

    $value = Read-Host "$Label [$Default]"
    if (-not $value.Trim()) {
        return $Default
    }
    return $value.Trim()
}

function Ask-Int {
    param(
        [Parameter(Mandatory = $true)][string]$Label,
        [Parameter(Mandatory = $true)][int]$Default
    )

    $text = Ask-Text $Label ([string]$Default)
    $number = 0
    if ([int]::TryParse($text, [ref]$number)) {
        return $number
    }
    return $Default
}

function Split-List {
    param([string]$Text)

    return @(
        $Text -split "," |
            ForEach-Object { $_.Trim() } |
            Where-Object { $_ }
    )
}

$outputFullDir = Resolve-RepoPath $OutputDir
$stage2RequestFullPath = Resolve-RepoPath $Stage2RequestPath
New-Item -ItemType Directory -Force -Path $outputFullDir | Out-Null
New-Item -ItemType Directory -Force -Path (Split-Path $stage2RequestFullPath -Parent) | Out-Null

Write-Host "PJBL Stage 1 only"
Write-Host "Script ini hanya mengumpulkan input Stage 1 dan membuat payload untuk pengujian Stage 2."
Write-Host ""

Write-Host "== Project =="
$projectId = Ask-Text "Project ID" "test-pjbl-001"
$projectTitle = Ask-Text "Judul project" "Proyek Pengelolaan Sampah Plastik di Sekolah"
$subject = Ask-Text "Subject/mapel" "Projek Penguatan Profil Pelajar Pancasila"
$phase = Ask-Text "Fase" "D"
$gradeLevel = Ask-Text "Kelas/jenjang" "VII"

Write-Host ""
Write-Host "== Data guru, sekolah, dan kelas =="
$teacherName = Ask-Text "Nama guru" "Guru Test"
$schoolName = Ask-Text "Nama sekolah" "SMP Test"
$city = Ask-Text "Kota" "Jakarta"
$schoolEnvironment = Ask-Text "Lingkungan sekolah" "Sekolah perkotaan dengan kantin dan halaman kecil"
$facilitiesText = Ask-Text "Fasilitas, pisahkan koma" "kelas, halaman sekolah, proyektor, tempat sampah terpilah"
$localContext = Ask-Text "Konteks lokal sekolah" "Sampah plastik dari kantin masih banyak tercampur dengan sampah lain."
$className = Ask-Text "Nama kelas" "VII A"
$studentCount = Ask-Int "Jumlah siswa" 32
$studentCharacteristics = Ask-Text "Karakteristik siswa" "Siswa aktif berdiskusi, suka kegiatan observasi, dan mudah terlibat jika aktivitas dekat dengan kehidupan sehari-hari."
$learningChallengesText = Ask-Text "Tantangan belajar, pisahkan koma" "sebagian siswa kurang teliti mencatat data, waktu kegiatan proyek perlu dibatasi"
$dominantLearningStyle = Ask-Text "Gaya belajar dominan" "kinestetik dan visual"

Write-Host ""
Write-Host "== Stage 1 =="
$theme = Ask-Text "Tema Stage 1" "Gaya Hidup Berkelanjutan"
$localIssue = Ask-Text "Isu lokal" "Sampah plastik di lingkungan sekolah"
$projectDuration = Ask-Text "Durasi proyek" "2 x 35 menit (Jam Pelajaran)"
$studentNeeds = Ask-Text "Kebutuhan siswa" "Butuh kegiatan nyata, sederhana, dan dekat dengan keseharian siswa."
$constraintsText = Ask-Text "Batasan proyek, pisahkan koma" "biaya rendah, alat mudah ditemukan, dilakukan di area sekolah, produk akhir harus realistis untuk siswa kelas VII"
$teacherExpectation = Ask-Text "Harapan guru" "Proyek menghasilkan aksi sederhana yang dapat dipresentasikan dan diterapkan di sekolah."

Write-Host ""
Write-Host "== Target Stage 2 =="
$topic = Ask-Text "Topik rekomendasi Stage 2" $localIssue
$selectedTheme = Ask-Text "Tema terpilih untuk rekomendasi" $theme

$facilities = Split-List $facilitiesText
$learningChallenges = Split-List $learningChallengesText
$constraints = Split-List $constraintsText

$stageOne = [ordered]@{
    stageNumber = 1
    stageName = "Konteks dan Kebutuhan Proyek"
    contentJson = [ordered]@{
        theme = $theme
        localIssue = $localIssue
        projectDuration = $projectDuration
        studentNeeds = $studentNeeds
        schoolContext = [ordered]@{
            name = $schoolName
            city = $city
            environment = $schoolEnvironment
            facilities = $facilities
            localContext = $localContext
        }
        classContext = [ordered]@{
            className = $className
            studentCount = $studentCount
            studentCharacteristics = $studentCharacteristics
            learningChallenges = $learningChallenges
            dominantLearningStyle = $dominantLearningStyle
        }
        constraints = $constraints
        teacherExpectation = $teacherExpectation
    }
}

$stage2Request = [ordered]@{
    project = [ordered]@{
        id = $projectId
        title = $projectTitle
        rppType = "pjbl_kokurikuler"
        subject = $subject
        phase = $phase
        gradeLevel = $gradeLevel
    }
    teacherProfile = [ordered]@{
        fullName = $teacherName
        position = "Guru"
    }
    school = [ordered]@{
        name = $schoolName
        city = $city
        schoolEnvironment = $schoolEnvironment
        availableFacilities = $facilities
        localContext = $localContext
    }
    teacherClass = [ordered]@{
        className = $className
        gradeLevel = $gradeLevel
        studentCount = $studentCount
        studentCharacteristics = $studentCharacteristics
        learningChallenges = $learningChallenges
        dominantLearningStyle = $dominantLearningStyle
    }
    previousStages = @($stageOne)
    targetStage = [ordered]@{
        stageNumber = 2
        stageName = "Rekomendasi Proyek"
        recommendationType = "project_recommendation"
        topic = $topic
        selectedTheme = $selectedTheme
    }
    options = [ordered]@{
        topK = 3
    }
}

$stageOnePath = Join-Path $outputFullDir "01-stage1.content.json"
Show-JsonPreview "Input Stage 1" $stageOne
Show-JsonPreview "Payload yang akan masuk ke Stage 2" $stage2Request
Save-Json $stageOne $stageOnePath
Save-Json $stage2Request $stage2RequestFullPath

Write-Host ""
Write-Host "Stage 1 tersimpan: $stageOnePath"
Write-Host "Payload Stage 2 tersimpan: $stage2RequestFullPath"
Write-Host ""
Write-Host "Lanjut uji Stage 2 dengan:"
Write-Host "powershell -ExecutionPolicy Bypass -File scripts\pjbl_stage2_interactive.ps1"
