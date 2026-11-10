$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$ToolsDir = Join-Path $ProjectRoot ".tools"
$UvZip = Join-Path $ToolsDir "uv.zip"
$UvExe = Join-Path $ToolsDir "uv.exe"
$BackendDir = $PSScriptRoot
$VenvDir = Join-Path $BackendDir ".venv"

New-Item -ItemType Directory -Force -Path $ToolsDir | Out-Null

if (-not (Test-Path $UvExe)) {
    Write-Host "Descargando gestor aislado uv..."
    Invoke-WebRequest -Uri "https://github.com/astral-sh/uv/releases/latest/download/uv-x86_64-pc-windows-msvc.zip" -OutFile $UvZip
    Expand-Archive -Path $UvZip -DestinationPath $ToolsDir -Force
    Remove-Item $UvZip -Force
}

$env:UV_PYTHON_INSTALL_DIR = Join-Path $ToolsDir "python"
$env:UV_CACHE_DIR = Join-Path $ToolsDir "uv-cache"

Write-Host "Creando entorno virtual Python 3.12 aislado en $VenvDir..."
& $UvExe venv $VenvDir --python 3.12

Write-Host "Instalando dependencias de Machine Learning y FastAPI..."
& $UvExe pip install --python (Join-Path $VenvDir "Scripts\python.exe") -r (Join-Path $BackendDir "requirements.txt")

Write-Host "Entorno Python aislado configurado correctamente."
