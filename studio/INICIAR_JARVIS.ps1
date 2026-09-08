$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $root

function Fail($msg) {
    Write-Host "[ERRO] $msg" -ForegroundColor Red
    Read-Host "Prime Enter para sair"
    exit 1
}

Write-Host "============================================"
Write-Host "  JARVIS AI STUDIO - Startup (PowerShell)"
Write-Host "============================================"
Write-Host ""

# 1) Pre-requisitos
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { Fail "Python nao encontrado no PATH. Instala Python 3.10+ e corre setup.bat." }
if (-not (Get-Command node -ErrorAction SilentlyContinue))   { Fail "Node.js nao encontrado no PATH. Instala Node 18+ e corre setup.bat." }
Write-Host "[ok] Python e Node encontrados."

# 2) venv
$venvPython = Join-Path $root "backend\.venv\Scripts\python.exe"
if (-not (Test-Path $venvPython)) {
    Write-Host "[aviso] backend\.venv nao existe. A correr setup.bat automaticamente..."
    Start-Process -FilePath "$root\setup.bat" -Wait -NoNewWindow
    if (-not (Test-Path $venvPython)) { Fail "setup.bat nao conseguiu criar o ambiente virtual." }
}

# 3) dependencias Python
& $venvPython -c "import fastapi, uvicorn, pydantic, multipart, requests" 2>$null
if ($LASTEXITCODE -ne 0) {
    Write-Host "[aviso] Dependencias Python em falta. A instalar automaticamente (apenas wheels pre-compiladas)..."
    & $venvPython -m pip install --upgrade pip | Out-Null
    & $venvPython -m pip install --only-binary=:all: -r "$root\backend\requirements.txt"
    if ($LASTEXITCODE -ne 0) {
        Fail "Nao foi possivel instalar as dependencias Python usando apenas wheels pre-compiladas para esta versao de Python (o JARVIS nunca tenta compilar via Rust/MSVC). Corre setup.bat para a mensagem completa e a recomendacao de instalar Python 3.12 x64."
    }
}
Write-Host "[ok] Dependencias Python prontas."

# 4) dependencias frontend
$nodeModules = Join-Path $root "frontend\node_modules"
if (-not (Test-Path $nodeModules)) {
    Write-Host "[aviso] frontend\node_modules em falta. A instalar automaticamente..."
    Push-Location "$root\frontend"
    npm install
    if ($LASTEXITCODE -ne 0) { Pop-Location; Fail "Falha ao instalar dependencias do frontend." }
    Pop-Location
}
Write-Host "[ok] Dependencias do frontend prontas."

# 5) .env
$envFile = Join-Path $root ".env"
if (-not (Test-Path $envFile)) {
    Copy-Item "$root\.env.example" $envFile
    Write-Host "[ok] .env criado a partir de .env.example."
}
Write-Host ""

# 6) portas livres
function Test-PortFree($port) {
    $conns = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($conns) {
        foreach ($c in $conns) {
            $proc = Get-Process -Id $c.OwningProcess -ErrorAction SilentlyContinue
            Write-Host "  porta $port em uso por PID $($c.OwningProcess) ($($proc.ProcessName))"
        }
        return $false
    }
    return $true
}

Write-Host "[portas] A verificar porta 8000 (backend)..."
if (-not (Test-PortFree 8000)) { Fail "A porta 8000 ja esta em uso (ver acima). Fecha esse processo e tenta outra vez." }

Write-Host "[portas] A verificar porta 5173 (frontend)..."
if (-not (Test-PortFree 5173)) { Fail "A porta 5173 ja esta em uso (ver acima). Fecha esse processo e tenta outra vez." }
Write-Host ""

# 7) iniciar backend e aguardar /health real
Write-Host "[backend] A iniciar backend (porta 8000)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\backend'; .\.venv\Scripts\Activate.ps1; uvicorn app.main:app --host 127.0.0.1 --port 8000"

Write-Host "[backend] A aguardar que o backend responda em /health (ate 45s)..."
$deadline = (Get-Date).AddSeconds(45)
$backendOk = $false
while ((Get-Date) -lt $deadline) {
    try {
        $resp = Invoke-WebRequest -Uri "http://127.0.0.1:8000/health" -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -eq 200) { $backendOk = $true; break }
    } catch { Start-Sleep -Milliseconds 800 }
}
if (-not $backendOk) { Fail "O backend nao respondeu a tempo. Ve a janela do backend para o erro real. O frontend NAO vai arrancar." }
Write-Host "[ok] Backend em execucao e saudavel."
Write-Host ""

# 8) iniciar frontend e aguardar resposta real
Write-Host "[frontend] A iniciar frontend (porta 5173)..."
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root\frontend'; npm run dev"

Write-Host "[frontend] A aguardar que o Vite responda (ate 45s)..."
$deadline = (Get-Date).AddSeconds(45)
$frontendOk = $false
while ((Get-Date) -lt $deadline) {
    try {
        $resp = Invoke-WebRequest -Uri "http://localhost:5173" -UseBasicParsing -TimeoutSec 3
        if ($resp.StatusCode -eq 200) { $frontendOk = $true; break }
    } catch { Start-Sleep -Milliseconds 800 }
}
if (-not $frontendOk) { Fail "O frontend nao respondeu a tempo. Ve a janela do frontend para o erro real. O navegador NAO vai abrir." }
Write-Host "[ok] Frontend em execucao."
Write-Host ""

# 9) so agora abrir o navegador
Start-Process "http://localhost:5173"

Write-Host "============================================"
Write-Host "  JARVIS AI STUDIO em execucao."
Write-Host "  Backend:  http://localhost:8000  (docs em /docs)"
Write-Host "  Frontend: http://localhost:5173"
Write-Host "============================================"
