@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo ============================================
echo   JARVIS AI STUDIO - Setup
echo ============================================
echo A correr em: %cd%
echo.

rem --- 1. Node/npm -----------------------------------------------------
where node >nul 2>nul
if errorlevel 1 (
    echo [ERRO] Node.js nao encontrado no PATH.
    echo        Instala Node.js 18+ de https://nodejs.org/
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('node --version 2^>^&1') do echo [ok] Node %%v encontrado

where npm >nul 2>nul
if errorlevel 1 (
    echo [ERRO] npm nao encontrado no PATH ^(normalmente vem com o Node.js^).
    pause
    exit /b 1
)
for /f "tokens=*" %%v in ('npm --version 2^>^&1') do echo [ok] npm %%v encontrado
echo.

rem --- 2. Escolher a versao de Python a usar ----------------------------
rem JARVIS recomenda Python 3.12 x64: e a versao com melhor cobertura de
rem "wheels" pre-compiladas para as dependencias (fastapi/pydantic). Usar
rem uma versao sem wheel obriga o pip a compilar pydantic-core a partir de
rem Rust, o que exige o Visual Studio Build Tools - MSVC / link.exe - algo
rem que uma instalacao normal do JARVIS nao deve exigir.
echo [python] A escolher a versao de Python...
set "PYCMD="
set "PYVER_FOUND="

where py >nul 2>nul
if not errorlevel 1 (
    py -3.12 -c "import sys" >nul 2>nul
    if not errorlevel 1 (
        set "PYCMD=py -3.12"
        echo [ok] Python 3.12 encontrado via 'py launcher' - vai ser usado ^(recomendado^).
    )
)

if not defined PYCMD (
    where python >nul 2>nul
    if errorlevel 1 (
        echo [ERRO] Python nao encontrado no PATH.
        echo        Instala Python 3.12 x64 de https://www.python.org/downloads/release/python-3120/
        pause
        exit /b 1
    )
    for /f "tokens=2 delims= " %%v in ('python --version 2^>^&1') do set "PYVER_FOUND=%%v"
    for /f "tokens=1,2 delims=." %%a in ("!PYVER_FOUND!") do (
        set "PYMAJOR=%%a"
        set "PYMINOR=%%b"
    )
    set "PYCMD=python"

    rem usar uma flag explicita em vez de encadear "if...if...else" -
    rem encadeamentos de IF sem esta flag podem nao disparar nenhum dos
    rem ramos em cmd.exe, o que esconderia o aviso silenciosamente.
    set "PY_COMPATIBLE=0"
    if "!PYMAJOR!"=="3" (
        if !PYMINOR! GEQ 10 if !PYMINOR! LEQ 12 set "PY_COMPATIBLE=1"
    )

    if "!PY_COMPATIBLE!"=="1" (
        echo [ok] Python !PYVER_FOUND! encontrado e e compativel.
    ) else (
        echo [AVISO] ================================================================
        echo [AVISO] So foi encontrado Python !PYVER_FOUND! no PATH. O JARVIS recomenda
        echo [AVISO] Python 3.12 x64.
        echo [AVISO]
        echo [AVISO] Versoes muito recentes ^(3.13+^) ou antigas ^(^< 3.10^) podem nao ter
        echo [AVISO] "wheels" pre-compiladas para todas as dependencias ^(ex.: pydantic-
        echo [AVISO] core^), o que obrigaria o pip a compilar a partir do codigo-fonte em
        echo [AVISO] Rust - e isso exige o Visual Studio Build Tools ^(MSVC / link.exe^),
        echo [AVISO] que normalmente NAO esta instalado numa maquina normal.
        echo [AVISO]
        echo [AVISO] Este setup NUNCA tenta compilar a partir do codigo-fonte - se nao
        echo [AVISO] houver wheel disponivel para a tua versao de Python, o passo
        echo [AVISO] seguinte vai falhar com uma mensagem clara ^(nao com um erro
        echo [AVISO] obscuro do MSVC^).
        echo [AVISO]
        echo [AVISO] Recomendado: instala Python 3.12 x64 de
        echo [AVISO]   https://www.python.org/downloads/release/python-3120/
        echo [AVISO] e corre este setup.bat outra vez.
        echo [AVISO] ================================================================
        echo.
    )
)
echo.

rem --- 3. Diretorios necessarios ----------------------------------------
echo [dirs] A garantir diretorios de dados...
if not exist "data"     mkdir "data"
if not exist "outputs"  mkdir "outputs"
if not exist "projects" mkdir "projects"
if not exist "assets"   mkdir "assets"
if not exist "loras"    mkdir "loras"
echo [ok] Diretorios prontos.
echo.

rem --- 4. Ambiente virtual Python (idempotente) --------------------------
echo [venv] A verificar backend\.venv...
if exist "backend\.venv\Scripts\python.exe" (
    echo [ok] .venv ja existe, a reaproveitar.
    for /f "tokens=*" %%v in ('backend\.venv\Scripts\python.exe --version 2^>^&1') do echo       versao do .venv: %%v
    echo       ^(se quiseres forcar a versao recomendada ^(3.12^), apaga backend\.venv e corre setup.bat outra vez^)
) else (
    echo       a criar .venv com: !PYCMD!...
    !PYCMD! -m venv backend\.venv
    if errorlevel 1 (
        echo [ERRO] Falha ao criar o ambiente virtual Python.
        pause
        exit /b 1
    )
    echo [ok] .venv criado.
)
echo.

rem --- 5. Dependencias Python: SO com wheels pre-compiladas --------------
rem --only-binary=:all: e o que garante que nunca se tenta compilar Rust/
rem MSVC - se nao houver wheel, o pip falha imediatamente com uma mensagem
rem clara, em vez de tentar compilar e falhar de forma obscura no link.exe.
echo [pip] A verificar dependencias Python...
backend\.venv\Scripts\python.exe -c "import fastapi, uvicorn, pydantic, multipart, requests" >nul 2>nul
if errorlevel 1 (
    echo       algo em falta, a instalar a partir de backend\requirements.txt ^(apenas wheels pre-compiladas^)...
    backend\.venv\Scripts\python.exe -m pip install --upgrade pip >nul
    backend\.venv\Scripts\python.exe -m pip install --only-binary=:all: -r backend\requirements.txt
    if errorlevel 1 (
        echo.
        echo [ERRO] ================================================================
        echo [ERRO] Nao foi possivel instalar as dependencias Python usando apenas
        echo [ERRO] pacotes pre-compilados ^("wheels"^) para esta versao de Python.
        echo [ERRO]
        echo [ERRO] O JARVIS instala DELIBERADAMENTE so com wheels e nunca tenta
        echo [ERRO] compilar a partir do codigo-fonte ^(isso exigiria o Visual Studio
        echo [ERRO] Build Tools / Rust / MSVC^, que normalmente nao esta instalado^).
        echo [ERRO]
        echo [ERRO] Solucao recomendada:
        echo [ERRO]   1. Instala Python 3.12 x64 de
        echo [ERRO]      https://www.python.org/downloads/release/python-3120/
        echo [ERRO]   2. Apaga a pasta backend\.venv
        echo [ERRO]   3. Corre setup.bat outra vez
        echo [ERRO] ================================================================
        pause
        exit /b 1
    )
    echo [ok] Dependencias Python instaladas.
) else (
    echo [ok] Dependencias Python ja presentes, nada a instalar.
)
echo.

rem --- 6. SQLite (builtin do Python, so confirmar que funciona) ----------
echo [sqlite] A confirmar SQLite...
backend\.venv\Scripts\python.exe -c "import sqlite3; sqlite3.connect(':memory:'); print('sqlite3 OK, versao', sqlite3.sqlite_version)"
if errorlevel 1 (
    echo [ERRO] SQLite nao esta a funcionar neste Python. Isto e muito invulgar - reinstala o Python.
    pause
    exit /b 1
)
echo.

rem --- 7. Dependencias frontend (so instala se node_modules faltar) ------
echo [npm] A verificar dependencias do frontend...
if exist "frontend\node_modules" (
    echo [ok] frontend\node_modules ja existe, a saltar instalacao.
    echo      ^(para forcar reinstalacao, apaga frontend\node_modules e corre setup.bat outra vez^)
) else (
    echo       a instalar dependencias do frontend...
    pushd frontend
    call npm install
    if errorlevel 1 (
        echo [ERRO] Falha ao instalar dependencias do frontend.
        popd
        pause
        exit /b 1
    )
    popd
    echo [ok] Dependencias do frontend instaladas.
)
echo.

rem --- 8. .env ------------------------------------------------------------
echo [env] A verificar .env...
if exist ".env" (
    echo [ok] .env ja existe, mantido sem alteracoes.
) else (
    copy .env.example .env >nul
    echo [ok] .env criado a partir de .env.example.
    echo      Edita .env se quiseres usar o MiniMax ^(MINIMAX_API_KEY^).
)
echo.

echo ============================================
echo   Setup concluido com sucesso!
echo   Corre INICIAR_JARVIS.bat para abrir o JARVIS.
echo ============================================
pause
