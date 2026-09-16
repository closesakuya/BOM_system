$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

function Test-PythonExecutable([string]$Command) {
    try {
        & $Command --version *> $null
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

$VenvPath = Join-Path $ProjectRoot ".venv"
$PythonCommand = Join-Path $VenvPath "Scripts\python.exe"
if (-not (Test-PythonExecutable $PythonCommand)) {
    $SystemPython = Get-Command python -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $SystemPython -or -not (Test-PythonExecutable $SystemPython.Source)) {
        throw "项目虚拟环境不可用，并且 PATH 中未找到可运行的系统默认 python。"
    }
    Write-Host "正在使用系统默认 Python 创建项目虚拟环境：$($SystemPython.Source)" -ForegroundColor Yellow
    if (Test-Path -LiteralPath $VenvPath) {
        $BrokenVenvPath = Join-Path $ProjectRoot (".venv.invalid-" + (Get-Date -Format "yyyyMMdd-HHmmssfff"))
        Move-Item -LiteralPath $VenvPath -Destination $BrokenVenvPath
        Write-Host "原虚拟环境不可用，已保留到：$BrokenVenvPath" -ForegroundColor Yellow
    }
    & $SystemPython.Source -m venv $VenvPath
    if ($LASTEXITCODE -ne 0 -or -not (Test-PythonExecutable $PythonCommand)) {
        throw "使用系统默认 Python 创建项目虚拟环境失败。"
    }
}
& $PythonCommand -m pip install -r "backend\requirements.txt"
if ($LASTEXITCODE -ne 0) { throw "后端依赖安装失败。" }

Push-Location "frontend"
try {
    npm install
    if ($LASTEXITCODE -ne 0) { throw "前端依赖安装失败。" }
    npm run build
    if ($LASTEXITCODE -ne 0) { throw "前端生产构建失败。" }
} finally {
    Pop-Location
}

$DatabasePath = Join-Path $ProjectRoot "runtime\bom_v1.db"
if (-not (Test-Path -LiteralPath $DatabasePath)) {
    Write-Host "首次部署：从新版生产 Excel 构建独立数据库，验证后启用。" -ForegroundColor Cyan
    $CandidatePath = Join-Path $ProjectRoot ("runtime\production-candidate-" + (Get-Date -Format "yyyyMMdd-HHmmss-fff") + ".db")
    $LocalAccounts = Join-Path $ProjectRoot "docs\requirements\四次需求.md"
    if (Test-Path -LiteralPath $LocalAccounts) {
        & $PythonCommand -m backend.app.production_rebuild --candidate $CandidatePath --accounts-file $LocalAccounts
    } else {
        Write-Host "未提供本地账户配置，请依次输入四个账户的初始密码（输入不会显示）。"
        & $PythonCommand -m backend.app.production_rebuild --candidate $CandidatePath
    }
    if ($LASTEXITCODE -ne 0) { throw "新版生产数据构建失败；未替换任何数据库。" }
    & $PythonCommand -m backend.app.production_rebuild --activate $CandidatePath --target $DatabasePath
    if ($LASTEXITCODE -ne 0) { throw "候选库启用失败，请检查报告。" }
} else {
    Write-Host "检测到现有数据库，仅执行升级检查，不重复导入、不重置账户：$DatabasePath" -ForegroundColor Cyan
}
& $PythonCommand -m backend.app.v1_2_migration --check-applied
$AlreadyV12 = ($LASTEXITCODE -eq 0)
if ($LASTEXITCODE -gt 1) { throw "数据库版本检查失败，请先检查数据库完整性。" }
if (-not $AlreadyV12) {
Write-Host "正在执行 BOM V1.1 基线迁移..." -ForegroundColor Cyan
& $PythonCommand -m backend.app.v1_1_migration
if ($LASTEXITCODE -ne 0) {
    throw "BOM V1.1 数据库迁移失败。现有数据库未提交迁移，请查看 runtime\reports 和 runtime\backups。"
}
Write-Host "正在执行 BOM V1.1.1 数据库备份、未正式编号和关键器件码升级..." -ForegroundColor Cyan
& $PythonCommand -m backend.app.v1_1_1_migration
if ($LASTEXITCODE -ne 0) {
    throw "BOM V1.1.1 数据库迁移失败。现有数据库未提交迁移，请查看 runtime\reports 和 runtime\backups。"
}
& $PythonCommand -m backend.app.demo
if ($LASTEXITCODE -ne 0) { throw "V1.1.1 演示数据检查失败。" }
}
Write-Host "正在执行 V1.2 路径选配、停用和彻底删除升级..." -ForegroundColor Cyan
& $PythonCommand -m backend.app.v1_2_migration
if ($LASTEXITCODE -ne 0) { throw "V1.2 数据库升级失败，事务已回滚，请查看备份与报告。" }
& $PythonCommand -m backend.app.v1_2_demo
if ($LASTEXITCODE -ne 0) { throw "V1.2 演示数据初始化失败。" }
Write-Host "正在根据整机名称补全空白机型..." -ForegroundColor Cyan
& $PythonCommand -m backend.app.machine_model_backfill
if ($LASTEXITCODE -ne 0) {
    throw "整机机型初始化失败。数据库修改已回滚，请查看 runtime\reports 和 runtime\backups。"
}
& $PythonCommand -m backend.app.validation
if ($LASTEXITCODE -ne 0) { throw "V1.2 数据库完整性验证失败。" }
Write-Host "BOM V1.2 安装检查完成。运行 scripts\start_v1.ps1 启动。"
