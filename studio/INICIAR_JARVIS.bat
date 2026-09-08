@echo off
setlocal
cd /d "%~dp0"

echo ============================================
echo   JARVIS AI STUDIO - Startup
echo ============================================
echo.

rem --- 1. Pre-requisitos --------------------------------------------
where python >nul 2>nul
if errorlevel 1 (
    echo [ERRO] Python nao encontrado no PATH. Instala Python 3.10+ e corre setup.bat.
    pause
    exit /b 1
)
where node >nul 2>nul
if errorlevel 1 (
    echo [ERRO] Node.js nao encontrado no PATH. Instala Node 18+ e corre setup.bat.
    pause
    exit /b 1
)
echo [ok] Python e Node encontrados.

rem --- 2. backend\.venv existe? Se nao, corre o setup ------------------
if not exist "backend\.venv\Scripts\python.exe" (
    echo [aviso] backend\.venv nao existe. A correr setup.bat automaticamente...
    call setup.bat
    if not exist "backend\.venv\Scripts\python.exe" (
        echo [ERRO] setup.bat nao conseguiu criar o ambiente virtual. Ve o erro acima.
        pause
        exit /b 1
    )
)

rem --- 3. Dependencias Python instaladas? Se nao, instala automaticamente
backend\.venv\Scripts\python.exe -c "import fastapi, uvicorn, pydantic, multipart, requests" >nul 2>nul
if errorlevel 1 (
    echo [aviso] Dependencias Python em falta. A instalar automaticamente ^(apenas wheels pre-compiladas^)...
    backend\.venv\Scripts\python.exe -m pip install --upgrade pip >nul
    backend\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r backend\requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERRO] Nao foi possivel instalar as dependencias Python usando apenas
        echo [ERRO] wheels pre-compiladas para esta versao de Python ^(o JARVIS nunca
        echo [ERRO] tenta compilar via Rust/MSVC^). Corre setup.bat para a mensagem
        echo [ERRO] completa e a recomendacao de instalar Python 3.12 x64.
        pause
        exit /b 1
    )
)
echo [ok] Dependencias Python prontas.

rem --- 4. frontend\node_modules existe? Se nao, instala automaticamente
if not exist "frontend\node_modules" (
    echo [aviso] frontend\node_modules em falta. A instalar automaticamente...
    pushd frontend
    call npm install
    if errorlevel 1 (
        echo [ERRO] Falha ao instalar dependencias do frontend.
        popd
        pause
        exit /b 1
    )
    popd
)
echo [ok] Dependencias do frontend prontas.

rem --- 5. .env existe? -------------------------------------------------
if not exist ".env" (
    copy .env.example .env >nul
    echo [ok] .env criado a partir de .env.example.
)
echo.

rem --- 6. Portas 8000 e 5173 livres? -----------------------------------
echo [portas] A verificar porta 8000 ^(backend^)...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\check_port.ps1" -Port 8000
if errorlevel 1 (
    echo [ERRO] A porta 8000 ja esta em uso por outro processo ^(ver acima^).
    echo        Fecha esse processo ou muda a porta do backend, depois tenta outra vez.
    pause
    exit /b 1
)

echo [portas] A verificar porta 5173 ^(frontend^)...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\check_port.ps1" -Port 5173
if errorlevel 1 (
    echo [ERRO] A porta 5173 ja esta em uso por outro processo ^(ver acima^).
    echo        Fecha esse processo ou muda a porta do frontend, depois tenta outra vez.
    pause
    exit /b 1
)
echo.

rem --- 7. Iniciar backend e aguardar /health real ----------------------
echo [backend] A iniciar backend (porta 8000)...
start "JARVIS Backend" cmd /k "cd /d "%~dp0backend" && call .venv\Scripts\activate.bat && uvicorn app.main:app --host 127.0.0.1 --port 8000"

echo [backend] A aguardar que o backend responda em /health (ate 45s)...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\wait_for_url.ps1" -Url "http://127.0.0.1:8000/health" -TimeoutSeconds 45
if errorlevel 1 (
    echo [ERRO] O backend nao respondeu a tempo. Ve a janela "JARVIS Backend" para o erro real.
    echo        O frontend NAO vai arrancar enquanto o backend nao estiver de pe.
    pause
    exit /b 1
)
echo [ok] Backend em execucao e saudavel.
echo.

rem --- 8. Iniciar frontend e aguardar resposta real ---------------------
echo [frontend] A iniciar frontend (porta 5173)...
start "JARVIS Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo [frontend] A aguardar que o Vite responda (ate 45s)...
powershell -NoProfile -ExecutionPolicy Bypass -File "scripts\wait_for_url.ps1" -Url "http://localhost:5173" -TimeoutSeconds 45
if errorlevel 1 (
    echo [ERRO] O frontend nao respondeu a tempo. Ve a janela "JARVIS Frontend" para o erro real.
    echo        O navegador NAO vai abrir enquanto o Vite nao estiver de pe.
    pause
    exit /b 1
)
echo [ok] Frontend em execucao.
echo.

rem --- 9. So agora abrir o navegador ------------------------------------
start "" "http://localhost:5173"

echo ============================================
echo   JARVIS AI STUDIO em execucao.
echo   Backend:  http://localhost:8000  ^(docs em /docs^)
echo   Frontend: http://localhost:5173
echo.
echo   Fecha as duas janelas de terminal para parar o JARVIS.
echo ============================================
pause
