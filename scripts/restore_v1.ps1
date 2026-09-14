param([Parameter(Mandatory = $true)][string]$BackupFile)
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$BackupRoot = (Resolve-Path (Join-Path $ProjectRoot "runtime\backups")).Path
$Source = (Resolve-Path $BackupFile).Path
if (-not $Source.StartsWith($BackupRoot, [System.StringComparison]::OrdinalIgnoreCase)) {
    throw "只允许恢复 runtime\backups 目录中的数据库备份"
}
if ([IO.Path]::GetExtension($Source) -ne ".db") { throw "备份文件必须是 .db" }
$Listening = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
if ($Listening) { throw "请先停止 BOM V1 服务，再执行恢复" }
$Target = Join-Path $ProjectRoot "runtime\bom_v1.db"
$Safety = Join-Path $BackupRoot ("before-restore-{0}.db" -f (Get-Date -Format "yyyyMMdd-HHmmss"))
if (Test-Path $Target) { Copy-Item -LiteralPath $Target -Destination $Safety }
& (Join-Path $ProjectRoot ".venv\Scripts\python.exe") -m backend.app.ops verify $Source
Copy-Item -LiteralPath $Source -Destination $Target -Force
& (Join-Path $ProjectRoot ".venv\Scripts\python.exe") -m backend.app.ops verify $Target
Write-Host "恢复完成。恢复前数据库保存在：$Safety"
