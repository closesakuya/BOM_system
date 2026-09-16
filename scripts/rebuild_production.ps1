param(
    [string]$AccountsFile = "",
    [switch]$Activate
)
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot
$PythonCommand = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
try { & $PythonCommand --version *> $null; $PythonWorks = ($LASTEXITCODE -eq 0) } catch { $PythonWorks = $false }
if (-not $PythonWorks) {
    $PythonCommand = "python"
    & $PythonCommand --version
    if ($LASTEXITCODE -ne 0) { throw "未找到可用 Python，请先运行 install_v1.ps1。" }
}
if ($Activate) {
    Write-Host "请先停止 BOM 服务。确认后将备份当前库，用新版 Excel 重建的数据库替换当前业务数据。" -ForegroundColor Yellow
    if ((Read-Host "输入 REBUILD 确认替换当前库") -cne "REBUILD") { throw "已取消，不修改当前数据库。" }
}
$CandidatePath = Join-Path $ProjectRoot ("runtime\production-candidate-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff") + ".db")
if (-not $AccountsFile) {
    $LocalAccounts = Join-Path $ProjectRoot "docs\requirements\四次需求.md"
    if (Test-Path -LiteralPath $LocalAccounts) { $AccountsFile = $LocalAccounts }
}
if ($AccountsFile) {
    & $PythonCommand -m backend.app.production_rebuild --candidate $CandidatePath --accounts-file $AccountsFile
} else {
    & $PythonCommand -m backend.app.production_rebuild --candidate $CandidatePath
}
if ($LASTEXITCODE -ne 0) { throw "候选库构建失败，当前数据库未修改。" }
if ($Activate) {
    & $PythonCommand -m backend.app.production_rebuild --activate $CandidatePath
    if ($LASTEXITCODE -ne 0) { throw "启用失败，请检查备份与报告。" }
} else {
    Write-Host "仅构建候选库，不修改当前数据库：$CandidatePath"
}
