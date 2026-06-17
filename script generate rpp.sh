$headers = @{
  "X-Internal-API-Key" = "change-this-internal-key"
}

$chatUri = "http://localhost:8000/internal/ai/kina-chat"
$summaryUri = "http://localhost:8000/internal/ai/summarize-kina-chat"

$project = @{
  id = "test-dummy-stage3-001"
  title = "RPM Polinomial Sederhana"
  rppType = "intrakurikuler"
  subject = "Matematika"
  phase = "Fase D"
  gradeLevel = "Kelas 7"
}

# Untuk test dummy, stages kosong.
# Backend akan memakai dummy Stage 1 dan Stage 2.
$stages = @()
$chatHistory = @()

function Send-KinaMessage {
  param([string]$message)

  $body = @{
    project = $project
    message = $message
    stages = $stages
    chatHistory = $chatHistory
  } | ConvertTo-Json -Depth 100

  $response = Invoke-RestMethod `
    -Uri $chatUri `
    -Method Post `
    -Headers $headers `
    -Body $body `
    -ContentType "application/json"

  Write-Host "`nKINA:" -ForegroundColor Green
  Write-Host $response.reply

  $script:chatHistory += @{
    role = "user"
    message = $message
  }

  $script:chatHistory += @{
    role = "assistant"
    message = $response.reply
  }

  $script:chatHistory |
    ConvertTo-Json -Depth 100 |
    Out-File ".\kina_chat_history.json" -Encoding utf8
}

function Save-KinaSummary {
  $body = @{
    project = $project
    summaryType = "stage3"
    stages = $stages
    chatHistory = $chatHistory
  } | ConvertTo-Json -Depth 100

  $summaryResponse = Invoke-RestMethod `
    -Uri $summaryUri `
    -Method Post `
    -Headers $headers `
    -Body $body `
    -ContentType "application/json"

  $summaryResponse |
    ConvertTo-Json -Depth 100 |
    Out-File ".\kina_chat_summary_response.json" -Encoding utf8

  if ($null -ne $summaryResponse.summary) {
    $summaryResponse.summary |
      ConvertTo-Json -Depth 100 |
      Out-File ".\kina_chat_summary.json" -Encoding utf8
  } else {
    $summaryResponse |
      ConvertTo-Json -Depth 100 |
      Out-File ".\kina_chat_summary.json" -Encoding utf8
  }

  Write-Host "Summary tersimpan ke kina_chat_summary.json" -ForegroundColor Green
}



$chatHistory = @()
Remove-Item .\kina_chat_history.json -ErrorAction SilentlyContinue
Remove-Item .\kina_chat_summary.json -ErrorAction SilentlyContinue
Remove-Item .\kina_chat_summary_response.json -ErrorAction SilentlyContinue

save-kinaSummary