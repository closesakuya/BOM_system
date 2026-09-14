param([int]$Port = 8000)
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot

$PythonCommand = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
$VirtualEnvAvailable = $false
if (Test-Path -LiteralPath $PythonCommand) {
    try {
        & $PythonCommand --version *> $null
        $VirtualEnvAvailable = ($LASTEXITCODE -eq 0)
    } catch {
        $VirtualEnvAvailable = $false
    }
}
if (-not $VirtualEnvAvailable) {
    $SystemPython = Get-Command python -CommandType Application -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if (-not $SystemPython) {
        throw "项目虚拟环境不可用，并且 PATH 中未找到系统默认 python。请安装 Python 或运行 scripts\install_v1.ps1。"
    }
    $PythonCommand = $SystemPython.Source
    & $PythonCommand --version
    if ($LASTEXITCODE -ne 0) {
        throw "PATH 中的系统默认 python 无法运行。"
    }
    Write-Host "项目虚拟环境不可用，已改用系统默认 Python：$PythonCommand" -ForegroundColor Yellow
}
if (-not (Test-Path "frontend\dist\index.html")) { throw "前端尚未构建，请先运行 scripts\install_v1.ps1" }
$LanAddresses = Get-NetIPAddress -AddressFamily IPv4 -ErrorAction SilentlyContinue |
    Where-Object { $_.IPAddress -notlike "127.*" -and $_.IPAddress -notlike "169.254.*" } |
    Select-Object -ExpandProperty IPAddress -Unique
Write-Host "BOM V1.2 正在启动。0.0.0.0 是监听地址，不能直接在浏览器中访问。" -ForegroundColor Cyan
Write-Host "本机访问：http://127.0.0.1:$Port" -ForegroundColor Green
foreach ($Address in $LanAddresses) {
    Write-Host "局域网访问：http://${Address}:$Port" -ForegroundColor Green
}
& $PythonCommand -m uvicorn backend.app.main:app --host 0.0.0.0 --port $Port
