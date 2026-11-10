# =============================================================================
# SPORTPREDICT AI - SCRIPT DE INICIO RÁPIDO (BACKEND FASTAPI + FRONTEND NEXT.JS)
# =============================================================================
$ProjectRoot = $PSScriptRoot
$BackendDir = Join-Path $ProjectRoot "backend"
$FrontendDir = Join-Path $ProjectRoot "frontend"
$PythonExe = Join-Path $BackendDir ".venv\Scripts\python.exe"

Write-Host "Iniciando Backend FastAPI en http://localhost:8000 ..." -ForegroundColor Cyan
Start-Process -FilePath $PythonExe -ArgumentList "-m uvicorn app.main:app --host 0.0.0.0 --port 8000" -WorkingDirectory $BackendDir

Write-Host "Iniciando Frontend Next.js en http://localhost:3000 ..." -ForegroundColor Cyan
Start-Process -FilePath "npm.cmd" -ArgumentList "run dev" -WorkingDirectory $FrontendDir

Write-Host "Ambos servicios han sido lanzados. Abre http://localhost:3000 en tu navegador." -ForegroundColor Green
