param(
  [switch]$NoOpen
)

$ErrorActionPreference = 'Stop'
$Host.UI.RawUI.WindowTitle = 'Internal AI Assistant Launcher'

$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot '..')
$BackendDir = Join-Path $ProjectRoot 'backend'
$FrontendDir = Join-Path $ProjectRoot 'frontend'
$RuntimeDir = Join-Path $ProjectRoot '.runtime'
$UrlFile = Join-Path $RuntimeDir 'frontend-url.txt'
$FrontendLog = Join-Path $RuntimeDir 'frontend.log'

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
Remove-Item -LiteralPath $UrlFile -Force -ErrorAction SilentlyContinue

function Stop-PortProcess([int]$Port) {
  try {
    $owners = Get-NetTCPConnection -LocalPort $Port -ErrorAction SilentlyContinue |
      Where-Object { $_.State -eq 'Listen' } |
      Select-Object -ExpandProperty OwningProcess -Unique
    foreach ($ownerPid in $owners) {
      if ($ownerPid -and $ownerPid -ne $PID) {
        $proc = Get-Process -Id $ownerPid -ErrorAction SilentlyContinue
        if ($proc) {
          Write-Host "Free port ${Port}: stop $($proc.ProcessName)($ownerPid)"
          Stop-Process -Id $ownerPid -Force -ErrorAction SilentlyContinue
        }
      }
    }
  } catch {
    Write-Warning "Failed to inspect port ${Port}: $($_.Exception.Message)"
  }
}

function Test-Http([string]$Url) {
  try {
    Invoke-WebRequest -Uri $Url -UseBasicParsing -TimeoutSec 2 | Out-Null
    return $true
  } catch {
    return $false
  }
}

function Wait-Http([string]$Url, [int]$Seconds = 60) {
  $deadline = (Get-Date).AddSeconds($Seconds)
  while ((Get-Date) -lt $deadline) {
    if (Test-Http $Url) { return $true }
    Start-Sleep -Milliseconds 800
  }
  return $false
}

Write-Host '=== Internal AI Assistant one-click launcher ==='
Write-Host "Project: $ProjectRoot"
Write-Host 'It starts from the current project folder, so it always uses the latest edited code.'

Stop-PortProcess 5174

$BackendPort = 8000
if (Test-Http 'http://localhost:8000/api/health') {
  Write-Host 'Port 8000 already has a healthy backend. Reusing it.'
} else {
  Stop-PortProcess 8000
  Start-Sleep -Seconds 1
  if (Test-Http 'http://localhost:8000/api/health') {
    Write-Host 'Backend on port 8000 became healthy after cleanup.'
  } else {
    $BackendPort = 8002
    Stop-PortProcess 8002
  }
}

$BackendUrl = "http://127.0.0.1:$BackendPort"
Write-Host "Starting backend at $BackendUrl ..."
$backendCommand = "cd /d `"$BackendDir`" && python -m uvicorn app.main:app --host 0.0.0.0 --port $BackendPort --reload"
Start-Process cmd.exe -ArgumentList '/k', $backendCommand -WindowStyle Normal | Out-Null

if (Wait-Http "$BackendUrl/api/health" 60) {
  Write-Host "Backend is ready: $BackendUrl"
} else {
  Write-Warning "Backend was not ready in 60 seconds. Please check the backend command window."
}

Write-Host 'Starting frontend Vite dev server at fixed port http://localhost:5174 ...'
$frontendRunner = Join-Path $PSScriptRoot 'run-frontend.ps1'
Start-Process powershell.exe -ArgumentList @('-NoExit', '-ExecutionPolicy', 'Bypass', '-File', $frontendRunner, '-FrontendDir', $FrontendDir, '-LogFile', $FrontendLog, '-BackendUrl', $BackendUrl) -WindowStyle Normal | Out-Null

$frontendUrl = 'http://localhost:5174/'
Set-Content -LiteralPath $UrlFile -Value $frontendUrl -Encoding UTF8
Write-Host "Frontend URL: $frontendUrl"
if (!$NoOpen) {
  Start-Process ($frontendUrl + 'chat')
}

Write-Host ''
Write-Host 'Done.'
Write-Host '- Keep the backend and frontend command windows open.'
Write-Host '- Close those windows to stop services.'
Write-Host '- Chat page: http://localhost:5174/chat'
Write-Host '- Admin page: http://localhost:5174/admin'
Read-Host 'Press Enter to close this launcher window. Service windows will keep running'
