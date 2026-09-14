param([string]$Label = "daily", [int]$Retain = 30)
$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $ProjectRoot
& ".venv\Scripts\python.exe" -m backend.app.ops backup --label $Label --retain $Retain
