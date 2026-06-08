param(
  [Parameter(Mandatory=$true)][string]$FrontendDir,
  [Parameter(Mandatory=$true)][string]$LogFile
)

$ErrorActionPreference = 'Continue'
$Host.UI.RawUI.WindowTitle = 'Internal AI Assistant Frontend 5174'

Set-Location -LiteralPath $FrontendDir
$env:BROWSER = 'none'

New-Item -ItemType Directory -Force -Path (Split-Path -Parent $LogFile) | Out-Null
Remove-Item -LiteralPath $LogFile -Force -ErrorAction SilentlyContinue

Write-Host '=== Internal AI Assistant Frontend ==='
Write-Host "Folder: $FrontendDir"
Write-Host "URL:    http://localhost:5174/chat"
Write-Host "Log:    $LogFile"
Write-Host ''
Write-Host 'Starting Vite dev server...'
Write-Host 'If this window later shows FRONTEND SERVICE STOPPED, the window is still open but the service is no longer running.'
Write-Host ''

& npm run dev -- --host 0.0.0.0 2>&1 | Tee-Object -FilePath $LogFile -Append
$exitCode = if ($null -ne $LASTEXITCODE) { $LASTEXITCODE } else { 0 }

Write-Host ''
Write-Host '============================================================' -ForegroundColor Yellow
Write-Host "FRONTEND SERVICE STOPPED. Exit code: $exitCode" -ForegroundColor Yellow
Write-Host 'This explains why http://localhost:5174 may stop responding even if this window was not closed.' -ForegroundColor Yellow
Write-Host "Please check the log above or open: $LogFile" -ForegroundColor Yellow
Write-Host '============================================================' -ForegroundColor Yellow
Read-Host 'Press Enter to close this frontend window'
