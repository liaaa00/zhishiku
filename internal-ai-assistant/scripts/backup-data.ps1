[CmdletBinding()]
param(
    [string]$OutputDir = "backups",
    [switch]$IncludeEnv
)

$ErrorActionPreference = "Stop"

$projectRoot = Resolve-Path (Join-Path $PSScriptRoot "..")
$backendData = Join-Path $projectRoot "backend\data"
$envFile = Join-Path $projectRoot ".env"
$timestamp = Get-Date -Format "yyyyMMdd-HHmmss"
$backupRoot = Join-Path $projectRoot $OutputDir
$staging = Join-Path $backupRoot "staging-$timestamp"
$archive = Join-Path $backupRoot "internal-ai-assistant-data-$timestamp.zip"

Write-Host "内部 AI 问答助手数据备份脚本"
Write-Host "项目目录: $projectRoot"
Write-Host "输出目录: $backupRoot"

if (-not (Test-Path -LiteralPath $backendData)) {
    throw "后端数据目录不存在: $backendData"
}

New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
New-Item -ItemType Directory -Force -Path $staging | Out-Null

try {
    $dataTarget = Join-Path $staging "backend-data"
    Copy-Item -LiteralPath $backendData -Destination $dataTarget -Recurse -Force

    $manifest = @()
    $manifest += "backup_time=$timestamp"
    $manifest += "project_root=$projectRoot"
    $manifest += "included=backend/data"
    $manifest += "included_env=$IncludeEnv"
    $manifest += "qdrant_volume=NOT_INCLUDED; backup Docker volume qdrant_storage separately"
    $manifest += "note=.env is excluded by default; use -IncludeEnv only for encrypted/offline backups"

    if ($IncludeEnv) {
        if (Test-Path -LiteralPath $envFile) {
            Copy-Item -LiteralPath $envFile -Destination (Join-Path $staging ".env") -Force
            Write-Warning ".env 已包含在备份中，请仅保存到加密或受控位置。"
        } else {
            Write-Warning ".env 不存在，未包含运行密钥配置。"
        }
    }

    $manifest | Set-Content -Encoding UTF8 (Join-Path $staging "MANIFEST.txt")

    if (Test-Path -LiteralPath $archive) {
        throw "备份文件已存在: $archive"
    }
    Compress-Archive -Path (Join-Path $staging "*") -DestinationPath $archive -CompressionLevel Optimal
    Write-Host "备份完成: $archive"
    Write-Host "注意: Qdrant Docker volume 未包含在此 zip 中，请按部署手册单独备份 qdrant_storage。"
}
finally {
    if (Test-Path -LiteralPath $staging) {
        $resolvedStaging = (Resolve-Path -LiteralPath $staging).Path
        $resolvedBackupRoot = (Resolve-Path -LiteralPath $backupRoot).Path
        if ($resolvedStaging.StartsWith($resolvedBackupRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
            Remove-Item -LiteralPath $resolvedStaging -Recurse -Force
        } else {
            Write-Warning "未删除临时目录，路径校验未通过: $resolvedStaging"
        }
    }
}
