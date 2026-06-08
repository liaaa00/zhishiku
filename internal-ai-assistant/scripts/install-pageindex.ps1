param(
  [string]$RepoUrl = "https://github.com/VectifyAI/PageIndex.git",
  [string]$TargetDir = "",
  [switch]$SkipDependencyInstall
)

$ErrorActionPreference = "Stop"
$ProjectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
if (-not $TargetDir) {
  $TargetDir = Join-Path $ProjectRoot "third_party\PageIndex"
}
$BackendDir = Join-Path $ProjectRoot "backend"
$ReqFile = Join-Path $BackendDir "requirements-pageindex.txt"

Write-Host "Project root: $ProjectRoot"
Write-Host "PageIndex target: $TargetDir"

if (Test-Path $TargetDir) {
  Write-Host "PageIndex already exists, pulling latest..."
  git -C $TargetDir pull --ff-only
} else {
  New-Item -ItemType Directory -Force -Path (Split-Path $TargetDir -Parent) | Out-Null
  git clone --depth 1 $RepoUrl $TargetDir
}

if (-not $SkipDependencyInstall) {
  Write-Host "Installing optional PageIndex dependencies..."
  Set-Location $BackendDir
  python -m pip install -r $ReqFile
}

Write-Host ""
Write-Host "Done. Add this to your .env if you want to pin the official source path:"
Write-Host "PAGEINDEX_REPO_PATH=$TargetDir"
Write-Host "PAGEINDEX_ENABLED=1"
Write-Host ""
Write-Host "Restart backend after changing .env."
