"""
acs_api_1177.py — ACS Studio API Bridge  [1177 DEV STACK]
Versão: 0.6.7-1177

Ponte entre o frontend e o backend Wan2GP 11.77 (Gradio).
Stack isolada — não afeta a DEV estável (AiStudio_Beta_v01).
NÃO buildar. NÃO instalar. Apenas DEV e testes.

Iniciar:
  python acs_api_1177.py --port 8010

Portas (stack 1177 DEV):
  Gradio (Wan2GP 11.77) → localhost:7871
  ACS API 1177          → localhost:8010

Changelog v0.6.8-1177 (Pre-Build34, 2026-05-29):
  - FIX-API-03 / LORA-DOD: LoRA on-demand download antes de enfileirar geração
    Fluxo: arquivo ausente → busca URL em _LORAS_URL_CACHE → download streaming
    → progresso visível em /status (status="downloading_lora") → geração normal
    Sem URL → error_code="lora_not_installed" (erro amigável, sem geração silenciosa)
  - NOVO: jobs[job_id]["status"] = "downloading_lora" durante download LoRA
    progress = 0-50% durante download, step mostra GB/s e ETA

Changelog v0.6.7-1177 (Pre-Build34, 2026-05-29):
  - NOVO: _LORAS_URL_CACHE — loading de loras_url_cache.json (gerado pelo Wan2GP)
    Contém URLs HuggingFace para LoRAs não instalados localmente
  - FIX: /loras endpoint — merge filesystem + url_cache para catálogo completo
    Fase 1: arquivos presentes em disco (downloaded: True)
    Fase 2: entradas url_cache não presentes (downloaded: False, download_url: URL)
    Resultado: 8 LoRAs LTX2 visíveis no dropdown mesmo sem arquivos locais

Changelog v0.5.2:
  - NOVO: MODELS dict agora inclui heartmula_oss_3b, kugelaudio_0_open, qwen3_tts_base
    base_type e model_id validados via Gradio /change_model_family('tts') endpoint
  - NOVO: _AUDIO_CUSTOM_SETTINGS_ORDER agora inclui kugelaudio_0_open e qwen3_tts_base
    mapeamento de auto_split_every_s → custom_setting_1 validado via handlers
  - NOVO: AudioGenerateRequest.num_inference_steps (-1 = usa default do modelo)
    Turbo models (ace_step_v1_5, ace_step_v1_5_xl) usam 8 steps por default
    Non-turbo / TTS sem inference_steps: 60 (ignorado pelo handler)
  - NOVO: default_steps por modelo no MODELS dict para referência e resolução
  - FIX: POST /upload/audio adicionado como alias de /upload-audio
    (frontend usa /upload/audio; causava 404 silencioso em uploads de voz)

Changelog v0.5.1:
  - NOVO: POST /generate/audio — geração de áudio via ACE-Step v1/v1.5 e outros modelos TTS
    Pipeline completo de 9 passos (mirror do _generate_background para áudio):
    browser_session → change_model_family → change_model_base_types → change_model
    → change_resolution_group → save_inputs → validate_wizard_prompt
    → process_prompt_and_add_tasks → prepare_generate_video → process_tasks
  - FIX: Adicionado PASSO 4.5 change_resolution_group("480p") após change_model no path de áudio
    Sem este passo, sample_solver ficava em estado inconsistente (value='euler', choices=[''])
    causando ValueError no save_inputs: "Value: euler is not in the list of choices: ['']"
  - NOVO: _AUDIO_OUTPUT_EXTS para detectar wav/mp3/flac/aac/m4a/ogg no polling de output
  - NOVO: Timeout de 3600s para áudio (cobre download inicial de ~6 GB de pesos do modelo)
  - FIX: /file/{filename} agora serve audio/* mime types corretos (audio/wav, audio/mpeg, etc.)
  - FIX: /outputs lista também arquivos de áudio (.wav .mp3 .flac .aac .m4a .ogg)

Changelog v0.3.0:
  - FIX CRÍTICO: image_prompt_type agora é computado por modo em vez de "" fixo
    Antes: image_prompt_type="" sempre → Wan2GP ignorava start frame e rodava T2V
    Agora: "S" para I2V, "SE" para FLF, "V" para Continue, "" para T2V/T2I
  - FIX: gallery_tab=0.0 para todos os modos de vídeo/imagem
    Antes: gallery_tab=1.0 para I2V → definia last_was_audio=True (errado)
    Agora: gallery_tab só controla last_was_audio; modo real vem do image_prompt_type
  - NOVO: modo "flf" (First-Last Frame) — image_prompt_type="SE"
  - NOVO: guidance_scale e motion_amplitude em GenerateRequest
  - NOVO: funções wrapper por modo (_build_t2v_params, _build_i2v_params, etc.)
  - _IMAGE_PROMPT_TYPE: mapa canônico generation_mode → flags Wan2GP

Changelog v0.2.0:
  - _generate_background: fluxo completo de 9 passos (engenharia reversa do botão GERAR)
  - Cada job usa client Gradio isolado (sessão própria)
  - Polling de output detecta arquivo gerado e atualiza status
  - /outputs lista imagens (.jpg .png) e vídeos (.mp4 .webp)
  - MODELS dict com family/base_type/model_id para seleção correta
"""

import asyncio
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

# ── UTF-8 stdout/stderr (evita charmap crash em Windows com redirecionamento) ──
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# ── ACS Logger (Fase A) ───────────────────────────────────────────────────────
# Import fail-safe: se o logger não estiver presente, a API continua normalmente.
try:
    import acs_logger as _acs_log
    _LOG_ENABLED = True
except ImportError:
    _acs_log = None
    _LOG_ENABLED = False
# ─────────────────────────────────────────────────────────────────────────────

import httpx
import uvicorn
from fastapi import FastAPI, BackgroundTasks, HTTPException, Request, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse, Response
from fastapi.staticfiles import StaticFiles
from gradio_client import Client
try:
    from gradio_client import handle_file as _gradio_handle_file
    _HAS_HANDLE_FILE = True
except ImportError:
    _HAS_HANDLE_FILE = False

def _wrap_file(path: str):
    """Empacota um path local no formato File/Image do Gradio client."""
    if not path:
        return None
    if os.getenv("ACS_USE_WANSESSION", "") == "1":  # [WANSESSION-B] cano novo quer caminho puro
        return path
    if _HAS_HANDLE_FILE:
        return _gradio_handle_file(path)
    return {"path": path}

def _wrap_gallery_item(path: str):
    """Empacota path no formato GalleryImage que Gradio/pydantic valida:
    {"image": FileData} para imagens, {"video": FileData} para vídeos.
    """
    if not path:
        return None
    fd = _wrap_file(path)
    ext = Path(path).suffix.lower()
    if ext in (".mp4", ".webm", ".mov"):
        return {"video": fd}
    return {"image": fd}
from pydantic import BaseModel

# ──────────────────────────────────────────────
# CONFIG — paths portáteis (sem hardcode de DEV)
# ──────────────────────────────────────────────
_WAN_PORT   = int(os.getenv("ACS_WAN_PORT", "7871"))   # [PORT-CFG] porta do Wan2GP — env override p/ rodar instância de teste paralela ao DEV
GRADIO_URL  = f"http://localhost:{_WAN_PORT}"    # Wan2GP 11.77 — porta configurável (default 7871)

# [12.24-API] O WanGP 12.24 renomeou api_names do Gradio (sufixo _target + prepare_generate_media).
# Env-gated: default = nomes do 11.77 (DEV intocado). Com ACS_GRADIO_API_V2=1 usa os do 12.24.
_API_V2 = os.getenv("ACS_GRADIO_API_V2", "") == "1"
_API_CHANGE_MODEL        = "/change_model_from_target"      if _API_V2 else "/change_model"
_API_CHANGE_MODEL_FAMILY = "/change_model_family_target"    if _API_V2 else "/change_model_family"
_API_CHANGE_BASE_TYPES   = "/change_model_base_types_target" if _API_V2 else "/change_model_base_types"
_API_PREPARE_GENERATE    = "/prepare_generate_media"        if _API_V2 else "/prepare_generate_video"

# [WANSESSION] Transporte novo (WanGPSession via worker HTTP) — FLAG-GATED.
# Default OFF → todo o caminho Gradio acima fica 100% intacto (zero regressão).
# ACS_USE_WANSESSION=1 ativa o transporte novo (Mudanças #2/#3 leem essa flag).
_USE_WANSESSION = os.getenv("ACS_USE_WANSESSION", "") == "1"
WAN = None
if _USE_WANSESSION:
    _app_dir = str(Path(__file__).resolve().parent)
    if _app_dir not in sys.path:
        sys.path.insert(0, _app_dir)
    from acs_wan_client import WanClient
    WAN = WanClient(f"http://127.0.0.1:{os.getenv('ACS_WAN_WORKER_PORT', '7872')}")

class _StubGradioClient:
    """[WANSESSION-B] No-op no lugar do gradio_client quando a flag está ON.
    Os PASSOs 1-4.5 chamam isto (não fazem nada) e o _save_kw é montado normal;
    o desvio WanGPSession (após o _save_kw) gera e retorna antes do submit real."""
    def predict(self, *a, **k): return None
    def submit(self, *a, **k):  return self
    def result(self, *a, **k):  return None
    def status(self, *a, **k):  return None
    def done(self):             return True
    def cancel(self, *a, **k):  return None

def find_free_port(start: int = 8010, max_tries: int = 20) -> int:
    """Probe ports without SO_REUSEADDR -- on Windows that flag allows double-bind."""
    for port in range(start, start + max_tries):
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.bind(("127.0.0.1", port))
                return port
        except OSError:
            continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _parse_port_arg() -> int:
    """Read --port N / --port=N from sys.argv; fall back to find_free_port."""
    argv = sys.argv[1:]
    for i, arg in enumerate(argv):
        if arg in ("--port", "-p") and i + 1 < len(argv):
            try:
                return int(argv[i + 1])
            except ValueError:
                pass
        if arg.startswith("--port="):
            try:
                return int(arg.split("=", 1)[1])
            except ValueError:
                pass
    return find_free_port(8010)


API_PORT    = _parse_port_arg()

# ── Base directory: sempre relativo ao próprio acs_api.py ──────────────────
# Funciona em: DEV, build ZIP, installer (C:\ACS Unlimited\app\), etc.
BASE_DIR   = Path(__file__).resolve().parent

# ── WAN2GP_DIR auto-detection ──────────────────────────────────────────────
# acs_api.py lives in app/ ; Wan2GP lives in data/wan2gp/ (one level up).
# Priority:
#   1. ACS_WAN2GP_DIR env var (explicit override — highest priority)
#   2. BASE_DIR.parent / "data" / "wan2gp"   ← installed layout
#   3. BASE_DIR / "Wan2GP_Dev"               ← dev symlink / legacy fallback
_WAN2GP_CANDIDATES = [
    BASE_DIR.parent / "data" / "wan2gp",   # installed: {root}/data/wan2gp
    BASE_DIR / "Wan2GP_Dev",               # dev symlink
]
WAN2GP_DIR = Path(os.getenv(
    "ACS_WAN2GP_DIR",
    str(next((p for p in _WAN2GP_CANDIDATES if p.exists()), _WAN2GP_CANDIDATES[0]))
))

# ── Frontend: tenta caminhos em ordem (build primeiro, DEV fallback) ────────
_FRONTEND_CANDIDATES = [
    BASE_DIR / "frontend",              # BUILD / installer
    BASE_DIR / "prototype",             # DEV
    BASE_DIR / "prototype" / "studio",  # DEV legacy
]
PROTOTYPE_DIR = next((p for p in _FRONTEND_CANDIDATES if p.exists()), None)
if PROTOTYPE_DIR is None:
    _tried = ", ".join(str(p) for p in _FRONTEND_CANDIDATES)
    raise RuntimeError(f"Frontend directory not found. Tried: {_tried}")

# ── Paths derivados — todos relativos a BASE_DIR / WAN2GP_DIR ──────────────
OUTPUTS_DIR      = Path(os.getenv("ACS_OUTPUTS_DIR",  str(WAN2GP_DIR / "outputs")))
TEMP_DIR         = Path(os.getenv("ACS_TEMP_DIR",     str(BASE_DIR   / "temp_refs")))
LORAS_DIR        = Path(os.getenv("ACS_LORAS_DIR",    str(WAN2GP_DIR / "loras")))
PROFILES_DIR     = Path(os.getenv("ACS_PROFILES_DIR", str(WAN2GP_DIR / "profiles")))

# Shared JSON written by the ACS tqdm hook in Wan2GP (shared/ffmpeg_setup.py).
# Contains real download progress; ACS reads it during polling.
# Root detection: in BUILD, acs_api.py is in {root}/app/ ; in DEV, at {root}/.
# Both the API and the Wan2GP hook must resolve to the same root for the file to match.
_ACS_DL_ROOT = BASE_DIR.parent if (BASE_DIR.parent / "version.json").exists() else BASE_DIR
_DL_PROGRESS_PATH = _ACS_DL_ROOT / "acs_dl_progress.json"
_DL_STALE_SEC = 8.0   # (legado — não mais usado como corte rígido; ver B39-BLOCK-002)
# [B39-BLOCK-002] Histerese de progresso de download: julgar pelos BYTES, não pelo relógio.
# O xet baixa em rajadas → o JSON fica segundos sem ser reescrito entre rajadas, mas o
# download segue vivo. Antes, o corte por mtime stale (>8s) fazia o HUD piscar "finalizando"
# e o watchdog contar timeout falso. Agora mantemos o último estado bom enquanto os MB sobem.
_DL_DEAD_SEC     = 1800.0 # [B39-BLOCK-003] active=true mas downloaded_mb congelado por este tempo = morto.
                          # Subido 300→1800: a autoridade de morte é o watchdog (_dl_stall) que mede bytes
                          # reais; aqui só evitamos HUD preso para sempre se o processo morrer com active=true.
_DL_MIN_DELTA_MB = 0.05   # incremento mínimo de MB para contar como progresso real
_DL_STALE_MTIME  = 120.0  # [B39-BLOCK-002b] se o JSON não é reescrito há mais que isto, NÃO há
                          # download ativo (rejeita arquivo STALE de sessão antiga interrompida →
                          # evita HUD fantasma). 120s cobre gaps entre rajadas do xet sem cortar vivo.
_dl_hold_last_mb    = -1.0   # último downloaded_mb visto (histerese)
_dl_hold_progress_t = 0.0    # time.time() da última vez que os MB subiram de verdade
_dl_hold_data       = None   # último dict de progresso válido (segurado durante rajadas)

# [ERR-10] Limpeza de download fantasma no boot.
# Este módulo é importado uma única vez quando o acs_api sobe. Nesse instante NENHUM
# download conduzido pelo ACS pode estar ativo (ainda não há jobs). Logo, um
# acs_dl_progress.json existente é SEMPRE órfão de uma sessão anterior interrompida
# (ex.: app morto durante download → active=true nunca fechado). O read-guard por mtime
# (120s) e por bytes (DEAD_SEC) já o neutraliza, mas resta uma janela: reabrir e gerar
# em <120s após um crash-durante-download faz o watchdog pausar achando que baixa e só
# abortar após 30min. Apagar o órfão no boot fecha essa janela de vez. Fail-safe total.
try:
    if _DL_PROGRESS_PATH.exists():
        _DL_PROGRESS_PATH.unlink()
        print(f"[ACS API][ERR-10] acs_dl_progress.json órfão removido no boot: {_DL_PROGRESS_PATH}")
except Exception as _e_dlclean:
    print(f"[ACS API][ERR-10] aviso ao limpar download órfão (não crítico): {_e_dlclean}")

# ── Config files ────────────────────────────────────────────────────────────
WAN2GP_CONFIG_PATH    = Path(os.getenv("ACS_WAN2GP_CONFIG", str(WAN2GP_DIR  / "wgp_config.json")))
WAN2GP_CONFIG_BACKUP_DIR = WAN2GP_CONFIG_PATH.parent / ".config_backups"
ACS_CONFIG_PATH       = Path(os.getenv("ACS_CONFIG",        str(BASE_DIR    / "acs_config.json")))

print(f"[ACS API] BASE_DIR    : {BASE_DIR}")
print(f"[ACS API] FRONTEND    : {PROTOTYPE_DIR}")
print(f"[ACS API] WAN2GP_DIR  : {WAN2GP_DIR}")
print(f"[ACS API] OUTPUTS_DIR : {OUTPUTS_DIR}")

# ── Dev environment detection ──────────────────────────────────────────────
# _is_dev_environment() returns True ONLY when running in the real development tree.
# Two independent condition sets — either satisfies the check:
#
#   SET B (path-based, primary for canonical dev tree):
#     .dev_mode sentinel + recognized dev path (e.g. aistudio_beta_v01)
#
#   SET A (explicit, for non-canonical dev paths):
#     ACS_DEV_MODE=1 env var + .dev_mode + (channel=="dev") + not install path
#
# Security: .dev_mode is NEVER packaged in the installer (enforced by
# tools/pre_build_check.py). Install paths are explicitly excluded.
# ACS_DEV_MODE=1 env var alone is NOT enough — requires both sentinel + channel.
_PROJECT_ROOT = BASE_DIR.parent if (BASE_DIR.parent / "version.json").exists() else BASE_DIR

# Paths that are always PRODUCTION — cannot be mistaken for DEV
_INSTALL_PATH_PATTERNS = (
    "acs unlimited", "program files", "programfiles",
    "appdata/local/programs", "acs_full_test",
)

# Canonical dev path patterns — root must contain one of these
_DEV_PATH_PATTERNS = (
    "aistudio_beta_v01",   # C:\AiStudio_Beta_v01 — canonical dev tree (stable)
    "aistudio_1177_dev",   # C:\AiStudio_1177_DEV — Wan2GP 11.77 isolated dev stack
)


def _is_dev_environment() -> bool:
    """
    Detect whether this is the real development environment.

    Returns True if EITHER condition set is fully satisfied:

    SET B — path-based (covers any launcher, no env var required):
      1. Root is NOT an install/production path
      2. .dev_mode sentinel file exists at project root (NEVER in installer)
      3. Project root contains a recognized dev path pattern (e.g. aistudio_beta_v01)

    SET A — explicit (for non-canonical or CI environments):
      1. Root is NOT an install/production path
      2. .dev_mode sentinel file exists at project root
      3. ACS_DEV_MODE=1 env var is set (dev launchers always set this)
      4. version.json channel == "dev"

    Design notes:
      - .dev_mode sentinel is the primary security gate — never shipped in installer
      - Path pattern recognition covers canonical dev tree without requiring env var
      - Set A provides explicit opt-in for non-standard dev setups
      - Production installs are positively excluded via path patterns
      - No single condition (env var, path, channel, sentinel) is sufficient alone
    [Build25] Relaxed: channel=="dev" no longer required when path is canonical DEV tree
    """
    root_lo = str(_PROJECT_ROOT).replace("\\", "/").lower()

    # SHARED GUARD 1: Must NOT be inside a known production install path.
    # This is checked first — an install path can never be DEV regardless.
    for pat in _INSTALL_PATH_PATTERNS:
        if pat in root_lo:
            return False

    # SHARED GUARD 2: .dev_mode sentinel must exist at project root.
    # This file is NEVER shipped in the installer (enforced by pre_build_check.py).
    # Without it, neither set can succeed.
    marker = _PROJECT_ROOT / ".dev_mode"
    if not marker.exists():
        return False

    # SET B: path-based recognition — no env var required.
    # Canonical dev tree (e.g. C:\AiStudio_Beta_v01) + sentinel = DEV.
    for pat in _DEV_PATH_PATTERNS:
        if pat in root_lo:
            return True

    # SET A: explicit opt-in — requires env var + channel.
    # For non-canonical paths (CI, custom dev layouts, etc.)
    if os.getenv("ACS_DEV_MODE", "0") != "1":
        return False

    vj = _PROJECT_ROOT / "version.json"
    if vj.exists():
        try:
            import json as _vj
            channel = _vj.loads(vj.read_text(encoding="utf-8-sig")).get("channel", "")
            if channel == "dev":
                return True
        except Exception:
            pass

    return False

_IS_DEV = _is_dev_environment()
if _IS_DEV:
    print("[ACS API] DEV ENVIRONMENT DETECTED — license bypass active")
    print("[ACS API] STACK: 1177 DEV (Wan2GP 11.77 | API :8010 | Wan :7871)")
else:
    print("[ACS API] PRODUCTION MODE — license enforcement active")

# ── Integrity state: set at startup, checked on every /generate ────────────
_INTEGRITY_OK = True          # bool — flipped to False if verify_manifest() finds errors
_INTEGRITY_ERRORS = []        # list[str] — populated with error descriptions

# ──────────────────────────────────────────────
# APP
# ──────────────────────────────────────────────
app = FastAPI(
    title="ACS Studio API",
    description="Ponte local entre o frontend ACS e o backend Wan2GP",
    version="0.6.3",
    docs_url="/docs" if _IS_DEV else None,
    redoc_url="/redoc" if _IS_DEV else None,
    openapi_url="/openapi.json" if _IS_DEV else None,
)

app.add_middleware(
    CORSMiddleware,
    # SECURITY: não usar allow_origins=["*"] — restringe a loopback apenas.
    # O frontend é servido pelo mesmo processo (same-origin); CORS só é necessário
    # para o Gradio proxy em :7871 e eventuais tabs abertas no browser externo.
    allow_origins=[
        f"http://127.0.0.1:{API_PORT}",
        "http://localhost:8010",
        "http://127.0.0.1:7871",   # Gradio 1177 — usado pelo proxy /gradio/
        "http://localhost:7871",
    ],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Middleware: desabilita cache para arquivos do studio (desenvolvimento)
# ATENÇÃO: NÃO usa BaseHTTPMiddleware — causa deadlock com FileResponse em arquivos grandes.
# Usa middleware ASGI puro (sem buffering de response body).
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.datastructures import MutableHeaders

# Extensões de assets imutáveis (cache longo)
_IMMUTABLE_EXTS = {".woff2", ".woff", ".ttf", ".otf", ".eot",
                   ".png", ".jpg", ".jpeg", ".gif", ".svg", ".ico",
                   ".webp", ".avif"}
# Extensões versionadas — cacheáveis se URL tiver ?v=
_VERSIONED_EXTS = {".js", ".css"}

class NoCacheMiddleware:
    """Cache seletivo para /studio/* — ASGI puro, sem buffering do body.

    Regras:
    - Fontes / imagens  → cache 1 ano (imutáveis; só mudam com rename)
    - JS / CSS com ?v=  → cache 1 dia  (version param já faz cache-bust)
    - HTML e resto      → no-cache     (sempre fresh)
    """
    def __init__(self, app: ASGIApp):
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path  = scope.get("path", "")
        query = scope.get("query_string", b"").decode()

        if not path.startswith("/studio/"):
            await self.app(scope, receive, send)
            return

        dot   = path.rfind(".")
        ext   = path[dot:].lower() if dot != -1 else ""

        if ext in _IMMUTABLE_EXTS:
            cache_header = "public, max-age=31536000, immutable"
        elif ext in _VERSIONED_EXTS and "v=" in query:
            cache_header = "public, max-age=86400"   # 1 dia; ?v= faz bust
        else:
            cache_header = "no-cache, no-store, must-revalidate"

        async def send_with_cache(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers["Cache-Control"] = cache_header
                if cache_header.startswith("no-cache"):
                    headers["Pragma"]  = "no-cache"
                    headers["Expires"] = "0"
            await send(message)

        await self.app(scope, receive, send_with_cache)

app.add_middleware(NoCacheMiddleware)


# ──────────────────────────────────────────────
# LICENSE GATE
# Lê cache local assinado (HMAC). Sem rede — o launcher valida online.
# Bloqueia /generate/* com HTTP 403 se licença ausente ou inválida.
# ──────────────────────────────────────────────
def _seclog(event: str, **kw) -> None:
    """Fire-and-forget security log. Never raises."""
    try:
        import sys as _sys
        # tools/ can be at BASE_DIR/tools (DEV flat) or BASE_DIR.parent/tools (production layout)
        _tools = next(
            (p for p in [BASE_DIR / "tools", BASE_DIR.parent / "tools"] if p.is_dir()),
            BASE_DIR / "tools",
        )
        if str(_tools) not in _sys.path:
            _sys.path.insert(0, str(_tools))
        import acs_security_log as _sl
        if event.startswith("LIC_"):
            _sl.license_event(event, **kw)
        else:
            _sl.security_event(event, **kw)
    except Exception:
        pass


def _stable_device_id_persisted() -> str:
    """[FIX-DEVICEID] Lê o device-id ESTÁVEL persistido por acs_license_real
    (%APPDATA%\\ACS Unlimited\\device.id, senão license.dat), com HMAC. Retorna ""
    se nada confiável. Mantém _lic_ok() consistente com o id congelado — sem isso
    o MAC volátil daria device_mismatch e bloquearia o cliente legítimo."""
    try:
        import json as _j, hmac as _h, hashlib as _hs2
        from pathlib import Path as _P
        _KEY = bytes(b ^ 0xd7 for b in (
            b'\x96\x94\x84\x88\x82\x99\x9b\x9e\x9a\x9e\x83\x92\x93'
            b'\x88\x94\x96\x94\x9f\x92\x88\x9f\x9a\x96\x94\x88\x81'
            b'\xe6\x88\x95\x92\x83\x96\x88\xe5\xe7\xe5\xe1'))
        def _sig_ok(raw):
            sig = raw.get("sig", "")
            canonical = _j.dumps({k: v for k, v in raw.items() if k != "sig"},
                                 sort_keys=True, separators=(",", ":"))
            expected = _h.new(_KEY, canonical.encode("utf-8"), _hs2.sha256).hexdigest()
            return raw.get("device_id") and _h.compare_digest(expected, sig)
        base = _P(os.environ.get("APPDATA", str(_P.home()))) / "ACS Unlimited"
        for fp in (base / "device.id", base / "license.dat"):
            try:
                if fp.exists():
                    raw = _j.loads(fp.read_text(encoding="utf-8"))
                    if _sig_ok(raw):
                        return raw["device_id"]
            except Exception:
                continue
    except Exception:
        pass
    return ""


def _compute_device_id() -> str:
    """Inline replica of acs_license_real.get_device_hash(). Returns 64-char hex.
    [FIX-DEVICEID] Prefere o device-id ESTÁVEL persistido (congelado); só calcula
    do MAC volátil como último recurso (mesmo algoritmo de antes — backward-compat).
    Must match acs_license_real exactly:
      - MAC: uuid.UUID(int=uuid.getnode()).hex[-12:].upper()  (NOT hex(uuid.getnode()))
      - host: socket.gethostname()                            (NOT platform.node())
      - vol:  ctypes GetVolumeInformationW → 8-char hex       (NOT PowerShell Get-Volume UniqueId)
    Bug fixed Build 34: was using hex(uuid.getnode()) + PowerShell UniqueId — both wrong.
    """
    _stable = _stable_device_id_persisted()
    if _stable:
        return _stable
    try:
        import hashlib as _hs, platform as _pl, socket as _sk, uuid as _uu, ctypes as _ct
        mac = _uu.UUID(int=_uu.getnode()).hex[-12:].upper()
        hostname = _sk.gethostname()
        machine = _pl.machine()
        system = _pl.system()
        try:
            _vol = _ct.c_ulong(0)
            _ct.windll.kernel32.GetVolumeInformationW(
                "C:\\", None, 0, _ct.byref(_vol), None, None, None, 0)
            vol_serial = f"{_vol.value:08X}"
        except Exception:
            vol_serial = "00000000"
        raw = f"mac:{mac}|host:{hostname}|vol:{vol_serial}|os:{system}-{machine}"
        return _hs.sha256(raw.encode("utf-8")).hexdigest()
    except Exception:
        return ""


def _compute_legacy_device_id() -> str:
    """
    Inline replica of acs_license.get_device_id() — 16-char HMAC fingerprint.
    Used to verify license caches activated with the legacy (Build <25) algorithm.
    The legacy algorithm uses: HMAC(salt, MachineGuid|hostname|volume_serial_ctypes)
    and returns the first 16 hex chars of the HMAC digest.
    Never raises.
    """
    try:
        import winreg as _wr, ctypes as _ct, socket as _sk, hmac as _h, hashlib as _hs
        # MachineGuid from registry (same as acs_license._machine_guid)
        try:
            _rk = _wr.OpenKey(_wr.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography")
            _guid, _ = _wr.QueryValueEx(_rk, "MachineGuid")
            _wr.CloseKey(_rk)
        except Exception:
            _guid = "fallback-guid"
        # Volume serial via ctypes GetVolumeInformationW (same as acs_license._volume_serial)
        try:
            _vs = _ct.c_ulong(0)
            _ct.windll.kernel32.GetVolumeInformationW(
                "C:\\", None, 0, _ct.byref(_vs), None, None, None, 0)
            _vol = str(_vs.value)
        except Exception:
            _vol = "0"
        _host = _sk.gethostname()
        _raw = f"{_guid}|{_host}|{_vol}"
        # Same salt as acs_license.get_device_id (XOR-obfuscated)
        _salt = bytes(b ^ 0xb2 for b in b'\xf3\xf1\xe1\xed\xf6\xf7\xe4\xed\xe1\xf3\xfe\xe6\xed\xe4\x83')
        return _h.new(_salt, _raw.encode("utf-8"), _hs.sha256).hexdigest()[:16]
    except Exception:
        return ""


# [TRIAL-GATE Peça 2] Estado verificado da licença (plano + features), atualizado
# a cada _lic_ok() bem-sucedido. Fonte: o cache HMAC-assinado (futuramente, o token
# assinado do servidor). Lido pelo endpoint /license/features e pelo enforcement (Peça 3).
_LIC_STATE: dict = {"plan": "", "features": {}, "expires_at": ""}


def _lic_ok() -> bool:
    """
    Fast, in-process license check.
    Reads the HMAC-signed cache that acs_license.py writes after online validation.
    Returns True only if: file exists + HMAC valid + not expired.
    Logs all outcomes to license.log via acs_security_log.
    Never raises — returns False on any error.
    """
    # DEV bypass: only active when _is_dev_environment() is True.
    # Requires marker file + channel=dev + not installed build layout.
    if _IS_DEV:
        _seclog("LIC_DEV_BYPASS")
        return True
    try:
        import json as _j, hmac as _h, hashlib as _hs, datetime as _dt
        from pathlib import Path as _P
        # Runtime key derivation — not stored as plaintext string
        _KEY = bytes(b ^ 0xd7 for b in (
            b'\x96\x94\x84\x88\x82\x99\x9b\x9e\x9a\x9e\x83\x92\x93'
            b'\x88\x94\x96\x94\x9f\x92\x88\x9f\x9a\x96\x94\x88\x81'
            b'\xe6\x88\x95\x92\x83\x96\x88\xe5\xe7\xe5\xe1'))
        cp = _P(os.environ.get("APPDATA", str(_P.home()))) / "ACS Unlimited" / "license.dat"
        if not cp.exists():
            print(f"[SECURITY BLOCK] reason=license_missing path={cp}")
            _seclog("LIC_FAIL", reason="license_missing")
            return False
        raw = _j.loads(cp.read_text(encoding="utf-8"))
        sig = raw.pop("sig", "")
        canonical = _j.dumps({k: v for k, v in raw.items()},
                              sort_keys=True, separators=(",", ":"))
        expected = _h.new(_KEY, canonical.encode("utf-8"), _hs.sha256).hexdigest()
        raw["sig"] = sig
        if not _h.compare_digest(expected, sig):
            print(f"[SECURITY BLOCK] reason=hmac_mismatch")
            _seclog("LIC_FAIL", reason="hmac_mismatch")
            return False                              # tampered or wrong key
        exp = _dt.datetime.fromisoformat(raw.get("expires_at", "2000-01-01T00:00:00"))
        if _dt.datetime.utcnow() > exp:
            print(f"[SECURITY BLOCK] reason=expired expires_at={raw.get('expires_at')}")
            _seclog("LIC_FAIL", reason="expired", expires_at=raw.get("expires_at"))
            return False
        # Clock skew: if last_check is more than 1h in the future, warn
        last_check_str = raw.get("last_check", "")
        if last_check_str:
            try:
                lc = _dt.datetime.fromisoformat(last_check_str.replace("Z", ""))
                delta = (lc - _dt.datetime.utcnow()).total_seconds()
                if delta > 3600:
                    _seclog("CLOCK_SKEW_WARN", delta_s=round(delta, 1))
            except Exception:
                pass
        # Device ID HARD check — block on mismatch to prevent license portability.
        # Two algorithms coexist:
        #   64-char: acs_license_real.get_device_hash() — SHA256 of mac|host|vol|os
        #   16-char: acs_license.get_device_id()        — HMAC of MachineGuid|host|vol (legacy)
        # The legacy prefix-match (startswith) was incorrect — SHA256 ≠ HMAC[:16].
        # Fix: for 16-char stored IDs, verify using the legacy HMAC algorithm directly.
        stored_device = raw.get("device_id", "")
        if stored_device:
            if len(stored_device) == 64:
                # Modern 64-char device_id — verify with SHA256 algorithm
                current_device = _compute_device_id()
                if current_device and stored_device != current_device:
                    print(f"[SECURITY BLOCK] reason=device_mismatch stored={stored_device[:8]}... current={current_device[:8]}...")
                    _seclog("LIC_FAIL", reason="device_mismatch",
                            stored=stored_device[:8] + "…",
                            current=current_device[:8] + "…")
                    return False
            elif len(stored_device) == 16:
                # Legacy 16-char device_id — verify with HMAC algorithm
                legacy_device = _compute_legacy_device_id()
                if legacy_device and stored_device != legacy_device:
                    print(f"[SECURITY BLOCK] reason=device_mismatch_legacy stored={stored_device} current={legacy_device}")
                    _seclog("LIC_FAIL", reason="device_mismatch_legacy",
                            stored=stored_device,
                            current=legacy_device)
                    return False
                # If legacy_device is empty (exception in computation), allow — fail-open
                # on device binding rather than blocking a legitimate user
            else:
                print(f"[SECURITY BLOCK] device_id_unknown_format len={len(stored_device)}")
                _seclog("LIC_BLOCK", reason="device_id_unknown_format",
                        stored_len=len(stored_device))
                return False
        plan = raw.get("plan", "")
        device_hint = stored_device[:8] if stored_device else ""
        # [TRIAL-GATE Peça 2] guarda o estado verificado (plano+features) p/ o gating
        global _LIC_STATE
        _LIC_STATE = {
            "plan":       plan,
            "features":   raw.get("features", {}) or {},
            "expires_at": raw.get("expires_at", ""),
        }
        _seclog("LIC_OK", plan=plan, device=device_hint)
        return True
    except Exception as _exc:
        _seclog("LIC_FAIL", reason=f"exception:{type(_exc).__name__}")
        return False

def _require_license():
    """
    Raise HTTP 503 if integrity check failed, or 403 if license is invalid.
    Call at start of each /generate endpoint.
    DEV environment bypasses both checks.
    """
    # DEV bypass — never block generation in the real dev environment
    if _IS_DEV:
        return
    if not _INTEGRITY_OK:
        raise HTTPException(
            status_code=503,
            detail={
                "error":   "integrity_failed",
                "message": "Arquivos críticos foram alterados. "
                           "Reinstale o ACS ou execute o repair.",
                "files":   _INTEGRITY_ERRORS,
            }
        )
    if not _lic_ok():
        raise HTTPException(
            status_code=403,
            detail={
                "error":   "license_required",
                "message": "Licença ACS Unlimited inválida ou ausente. "
                           "Ative sua licença no launcher.",
            }
        )


# [TRIAL-GATE Peça 2] Features do plano ativo (fonte: estado verificado por _lic_ok).
_DEV_FEATURES = {"image": True, "video": True, "audio": True, "motion": True,
                 "advanced": True, "unlimited": True}

# [TRIAL-GATE] Mapa CANÔNICO plano->features na API. NÃO confiar no 'features' do cache:
# o _resolve_features (cliente) podia gravar tudo False (bug da lista do servidor) → 403 em
# tudo. O PLANO ('trial'/'pro'/'ultimate') é confiável → derivamos as features daqui.
# Isso conserta caches já corrompidos SEM precisar re-ativar.
_PLAN_FEATURES = {
    "trial":    {"image": True, "video": True, "audio": False, "motion": False, "advanced": False,
                 "video_models": ["Light 8GB", "Light I2V 8GB", "Cinematic Lite"]},
    "pro":      {"image": True, "video": True, "audio": True, "motion": True, "advanced": True},
    "ultimate": {"image": True, "video": True, "audio": True, "motion": True, "advanced": True},
    "dev":      dict(_DEV_FEATURES),
}


def _current_license() -> dict:
    """Retorna {plan, features, expires_at}. Features derivadas do PLANO (canônico)."""
    if _IS_DEV:
        return {"plan": "dev", "features": dict(_DEV_FEATURES), "expires_at": ""}
    _lic_ok()  # refresca _LIC_STATE a partir do cache assinado
    plan = _LIC_STATE.get("plan", "")
    feats = _PLAN_FEATURES.get(plan)              # deriva do plano (confiável)
    if feats is None:                              # plano desconhecido → fallback cache → vazio
        feats = _LIC_STATE.get("features") or {}
    return {
        "plan":       plan,
        "features":   dict(feats),
        "expires_at": _LIC_STATE.get("expires_at", ""),
    }


def _current_features() -> dict:
    return _current_license()["features"]


def _require_feature(*, kind: str, model: str = None, resolution: str = None,
                     audio_prompt_type: str = None):
    """[TRIAL-GATE Peça 3] Bloqueio REAL por plano. Chamar nos /generate, após _require_license().
    kind: 'image' | 'video' | 'audio'. DEV e cache sem features = fail-open (não quebra pago)."""
    if _IS_DEV:
        return
    feats = _current_features()
    if not feats:
        return  # cache antigo/desconhecido sem features → não bloquear usuário legítimo

    def _deny(error: str, **extra):
        raise HTTPException(status_code=403,
                            detail={"error": error, "upgrade": True, **extra})

    # 1. Tipo de geração liberado no plano? (image/video/audio)
    if feats.get(kind, True) is False:
        _deny("feature_locked", feature=kind,
              message=f"O recurso '{kind}' é exclusivo do plano Full. Faça upgrade.")

    # 2. Talking head / motion via áudio guiando o vídeo (audio_prompt_type contém 'A')
    if kind == "video" and audio_prompt_type and "A" in str(audio_prompt_type) \
            and feats.get("motion", True) is False:
        _deny("feature_locked", feature="motion",
              message="Talking head (áudio como guia) é exclusivo do plano Full.")

    # 3. (Resolução NÃO é limitada no trial — decisão Luigi 2026-06-05: imagem/vídeo em
    #     resolução normal. O trial é limitado pelos MODELOS de vídeo + áudio/motion, não por res.)

    # 4. [ERR-12] Modelo premium fora da lista do plano — vale p/ VÍDEO e IMAGEM.
    #    Um modelo de FAMÍLIA de vídeo (ltx2/wan/hunyuan/...) fora da lista do plano
    #    é bloqueado mesmo em modo t2i (imagem) — senão o trial geraria imagem com
    #    Cinematic Pro Full/1.1 pela aba vídeo (modo Texto→Imagem), furando o gate.
    #    Modelos de imagem reais (flux/flux2/z_image) NÃO são de família de vídeo →
    #    continuam liberados no trial. Pro/Ultimate não têm 'video_models' → bloco inerte.
    allowed = feats.get("video_models")
    if allowed and model and model not in allowed:
        _VIDEO_FAMILIES = ("ltx", "wan", "hunyuan", "magi", "longcat")
        _fam = MODELS.get(model, {}).get("family", "")
        if any(_fam.startswith(f) for f in _VIDEO_FAMILIES):
            _deny("model_locked", model=model, allowed=allowed,
                  message=f"O modelo '{model}' é exclusivo do plano Full.")


# ──────────────────────────────────────────────
# ESTADO DAS GERAÇÕES EM MEMÓRIA
# ──────────────────────────────────────────────
jobs: dict[str, dict] = {}
# Semáforo: garante 1 geração Wan2GP por vez — jobs adicionais aguardam na fila
# Wan2GP não suporta paralelismo real; geração simultânea causa race condition nos outputs
_generation_lock = threading.Semaphore(1)

# ── IMG-PERF: rastreia último modelo carregado para detectar cache hit ──────
# Permite distinguir CACHE_HIT (<2s), WARM_RELOAD (2-8s), COLD_LOAD (>8s)
_LAST_LOADED_MODEL_ID: dict = {"id": None, "at": 0.0}

# ── [ERR-09] Auto-restart do motor na troca de família/modelo ───────────────
# Gradio 4.x congela as choices do dropdown model_choice no boot do motor. Trocar
# pra um modelo de outra família/base falha ("X is not in the list of choices").
# Solução: o acs_api reinicia o motor (com last_model_type=alvo) antes de gerar.
# Env-gated por _API_V2 → comportamento 11.77 inalterado.
_ENGINE_BOOT_MODEL: dict = {"id": None}   # modelo com que o motor está bootado
_WANSESSION_FAMILY: dict = {"current": None}  # [FIX-22B 2026-06-28] família do worker WanSession
# Onde o launcher grava runtime/wgp.pid; o acs_api usa pra coordenar o restart.
_RUNTIME_DIR = Path(os.getenv("ACS_RUNTIME_DIR", str(_PROJECT_ROOT / "runtime")))

def _port_is_up() -> bool:
    try:
        socket.create_connection(("127.0.0.1", _WAN_PORT), timeout=1).close(); return True
    except Exception:
        return False

def _gradio_app_ready() -> bool:
    """Gradio REALMENTE pronto = serve /config (app + fila inicializados), não só a
    porta TCP aberta. A porta abre ANTES do app/fila — submeter a geração pesada nessa
    janela faz a tarefa ficar presa na fila e nunca executar (hang da troca-de-família)."""
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{_WAN_PORT}/config", timeout=4) as r:
            return r.status == 200 and len(r.read(64)) > 0
    except Exception:
        return False

def _wait_engine_back(drop_first: bool = True) -> bool:
    """Espera o motor cair (se drop_first) e voltar TOTALMENTE pronto (gradio servindo,
    não só a porta) — senão a 1ª geração após o restart trava na fila do gradio."""
    if drop_first:
        for _ in range(20):                       # até ~40s p/ o launcher matar
            if not _port_is_up(): break
            time.sleep(2)
    # 1) porta TCP de pé
    port_ok = False
    for _ in range(140):                          # até ~280s
        if _port_is_up(): port_ok = True; break
        time.sleep(2)
    if not port_ok:
        return False
    # 2) gradio app+fila REALMENTE prontos (a fila pesada só roda depois disto)
    for _ in range(60):                           # até ~120s além da porta
        if _gradio_app_ready():
            # [DROPDOWN-SETTLE] 8s→15s: após /config 200 o Gradio ainda está construindo as UIs
            # dos modelos (inclui o dropdown sample_solver via extra_model_def do handler). Com 8s
            # a 1ª geração pegava o dropdown ainda vazio (choices=['']) => "euler not in choices".
            time.sleep(15)                         # settle p/ a UI/dropdowns terminarem de montar
            print("[ACS API] [ERR-09] gradio pronto (app servindo /config) + settle 15s")
            return True
        time.sleep(2)
    time.sleep(15)                                # fallback: porta ok mas /config não respondeu
    return True

def _standalone_restart_engine(model_id: str) -> bool:
    """[fallback SEM launcher — só teste isolado] mata a porta e sobe o motor direto."""
    try:
        cfg = json.loads(WAN2GP_CONFIG_PATH.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        cfg = {}
    cfg["last_model_type"] = model_id
    try:
        WAN2GP_CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception as e:
        print(f"[ACS API] [ERR-09] não consegui gravar last_model_type: {e}"); return False
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
        for ln in out.splitlines():
            if f":{_WAN_PORT} " in ln and "LISTENING" in ln:
                subprocess.run(["taskkill", "/PID", ln.split()[-1], "/F"], capture_output=True)
    except Exception as e:
        print(f"[ACS API] [ERR-09] kill standalone aviso: {e}")
    time.sleep(3)
    wgp_python = os.getenv("ACS_WGP_PYTHON", "") or sys.executable
    args = [wgp_python, "-u", str(WAN2GP_DIR / "wgp.py"), "--server-port", str(_WAN_PORT),
            "--profile", "5", "--attention", "sdpa", "--perc-reserved-mem-max", "0.2"]
    try:
        subprocess.Popen(args, cwd=str(WAN2GP_DIR), env=os.environ.copy(),
                         stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                         creationflags=0x08000000)
    except Exception as e:
        print(f"[ACS API] [ERR-09] falha ao subir motor: {e}"); return False
    return _wait_engine_back(drop_first=False)

def _request_launcher_engine_switch(model_id: str) -> bool:
    """Pede ao LAUNCHER pra reiniciar o motor com model_id (ele dona o processo e tem
    o watchdog — se o acs_api matasse o motor, o launcher dispararia EVT_CRASH e travaria
    o app). Escreve runtime/wgp_switch.json e espera o motor voltar. Sem launcher
    (teste isolado, ACS_STANDALONE_ENGINE=1) reinicia direto."""
    standalone = os.getenv("ACS_STANDALONE_ENGINE", "") == "1"
    pidfile = _RUNTIME_DIR / "wgp.pid"
    if standalone or not pidfile.exists():
        return _standalone_restart_engine(model_id)
    try:
        _RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        (_RUNTIME_DIR / "wgp_switch.json").write_text(
            json.dumps({"model": model_id}), encoding="utf-8")
    except Exception as e:
        print(f"[ACS API] [ERR-09] não consegui escrever pedido de troca: {e}"); return False
    return _wait_engine_back(drop_first=True)

def _restart_wansession_worker() -> bool:
    """[FIX-22B 2026-06-28] Mata e sobe o worker WanSession (troca de família corrompe CUDA)."""
    _wport = int(os.getenv("ACS_WAN_WORKER_PORT", "7872"))
    try:
        out = subprocess.run(["netstat", "-ano"], capture_output=True, text=True).stdout
        for ln in out.splitlines():
            if f":{_wport} " in ln and "LISTENING" in ln:
                subprocess.run(["taskkill", "/PID", ln.split()[-1], "/F"], capture_output=True)
    except Exception as e:
        print(f"[ACS API] [WANSESSION-RESTART] kill aviso: {e}")
    time.sleep(3)
    _py = os.getenv("ACS_WGP_PYTHON", "") or sys.executable
    _wan_dir = os.getenv("ACS_WAN_DIR", str(WAN2GP_DIR))
    _worker_script = Path(_wan_dir) / "acs_wan_worker.py"
    _env = os.environ.copy()
    _env["ACS_WAN_DIR"] = _wan_dir
    _env["HF_HUB_DISABLE_XET"] = "1"
    try:
        subprocess.Popen([_py, str(_worker_script)],
                         cwd=str(_worker_script.parent), env=_env,
                         stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT,
                         creationflags=0x08000000)
    except Exception as e:
        print(f"[ACS API] [WANSESSION-RESTART] falha ao subir worker: {e}"); return False
    for _ in range(60):
        try:
            r = requests.get(f"http://127.0.0.1:{_wport}/health", timeout=2)
            if r.status_code == 200:
                print(f"[ACS API] [WANSESSION-RESTART] worker pronto em :{_wport}")
                return True
        except Exception:
            pass
        time.sleep(2)
    print(f"[ACS API] [WANSESSION-RESTART] TIMEOUT esperando worker"); return False


def _ensure_engine_model(model_id: str) -> None:
    """Garante que o motor está bootado com model_id; senão pede restart (ERR-09)."""
    if _USE_WANSESSION:
        family = None
        for m in MODELS.values():
            if m.get("model_id") == model_id or m.get("base_type") == model_id:
                family = m.get("family"); break
        if family and _WANSESSION_FAMILY["current"] and family != _WANSESSION_FAMILY["current"]:
            print(f"[ACS API] [WANSESSION-RESTART] troca família {_WANSESSION_FAMILY['current']} → {family}")
            _restart_wansession_worker()
        _WANSESSION_FAMILY["current"] = family
        return
    if not _API_V2 or not model_id:
        return
    if _ENGINE_BOOT_MODEL["id"] is None:
        # lazy-init: o launcher bootou o motor com o last_model_type do config
        try:
            cfg = json.loads(WAN2GP_CONFIG_PATH.read_text(encoding="utf-8", errors="replace"))
            _ENGINE_BOOT_MODEL["id"] = cfg.get("last_model_type")
        except Exception:
            pass
    if model_id == _ENGINE_BOOT_MODEL["id"]:
        return  # já está no modelo certo — nada a fazer
    print(f"[ACS API] [ERR-09] troca {_ENGINE_BOOT_MODEL['id']} -> {model_id}: pedindo restart ao launcher")
    if _request_launcher_engine_switch(model_id):
        _ENGINE_BOOT_MODEL["id"] = model_id
        _LAST_LOADED_MODEL_ID["id"] = None   # força change_model a recarregar
        print(f"[ACS API] [ERR-09] motor pronto com {model_id}")
    else:
        print(f"[ACS API] [ERR-09] AVISO: motor não confirmou troca para {model_id}")


def new_client() -> Client:
    """Cria um novo client Gradio com sessão isolada por job."""
    return Client(GRADIO_URL, verbose=False)


# ──────────────────────────────────────────────
# MODELOS
# ── Conversão de duração: segundos → video_length (frames) ─────────────────
# Wan2GP usa video_length (frames) para modelos de vídeo.
# duration_seconds é IGNORADO para vídeo — usado apenas em modelos TTS/áudio.
# Fórmula: round(secs * fps / latent_size) * latent_size + 1
# ─────────────────────────────────────────────────────────────────────────────
_MODEL_FAMILY_FRAME_PARAMS = {
    # family  → (fps, latent_size, min_frames, sliding_window_size, sliding_window_overlap)
    "ltx2":   (24, 8, 17, 481, 17),
    "ltx":    (24, 8, 17, 481, 17),
    "wan":    (16, 4,  5,  81,  5),
    "wan2_2": (16, 4,  5,  81,  5),
    "hunyuan":(25, 4,  5, 241,  9),
    "flux2":  (None, None, None, None, None),   # imagem — n/a
    "flux":   (None, None, None, None, None),
}

def _seconds_to_video_length(duration_secs: int, model_name: str) -> int:
    """Converte duração em segundos para video_length (frames) compatível com Wan2GP.

    Usa fps e latent_size do model family para calcular o valor alinhado mínimo:
        video_length = round(secs * fps / latent_size) * latent_size + 1

    Fallback seguro para famílias desconhecidas: 81 frames (~3.4s a 24fps).
    """
    model_info = MODELS.get(model_name, {})
    family = model_info.get("family", "")
    params = _MODEL_FAMILY_FRAME_PARAMS.get(family)
    if params is None or params[0] is None:
        return 81   # imagem ou família desconhecida — valor neutro
    fps, latent_size, min_frames = params[0], params[1], params[2]
    raw = duration_secs * fps
    aligned = round(raw / latent_size) * latent_size + 1
    return max(min_frames, aligned)


def _get_sliding_window_params(model_name: str) -> tuple:
    """Retorna (sliding_window_size, sliding_window_overlap) corretos para o modelo.

    Valores documentados nos settings JSON de cada modelo (ltx2: 481/17, wan: 81/5, etc).
    Fallback para (81, 5) em famílias desconhecidas — valor neutro/seguro.
    """
    model_info = MODELS.get(model_name, {})
    family = model_info.get("family", "")
    params = _MODEL_FAMILY_FRAME_PARAMS.get(family)
    if params is None or params[3] is None:
        return (81, 5)   # fallback neutro
    return (params[3], params[4])   # (sliding_window_size, sliding_window_overlap)


def _sliding_overlap_for(model_name: str, generation_mode: str, duration_secs) -> int:
    """Overlap de janela CIENTE DO MODO. Em i2v/flf/continue (há source frame), quando o
    vídeo cabe em UMA janela o motor exige overlap<=1 ('Windows Frames Overlap must be at
    most 1'). Em t2v ou vídeos longos (multi-janela) mantém o overlap da família.
    [NEXTGEN 2026-06-27] corrige GEN_ERROR em todos os i2v curtos."""
    size, overlap = _get_sliding_window_params(model_name)
    _mi  = MODELS.get(model_name, {})
    _fam = _mi.get("family", ""); _mid = _mi.get("model_id", "")
    # Modelos i2v-nativos (i2v/fun_inp) + arquitetura magi têm overlap_max=1 no motor →
    # clampa p/ não estourar 'Windows Frames Overlap must be at most 1'. Preserva t2v e
    # Continue (Estender). [proper fix futuro: ler bound do motor — plataforma stability].
    if (generation_mode in ("i2v", "flf") or "magi" in _fam or "magi" in _mid
            or _fam in ("wan2_2",) or "i2v_2_2" in _mid or _mid in ("i2v", "fun_inp_1.3B")):
        return min(overlap, 1)
    return overlap


_DEF_PARAM_CACHE = {}
def _def_param(model_id: str, key: str, fallback):
    """[NEXTGEN 2026-06-27] Lê um parametro do DEF do modelo no motor (anti-adivinhacao:
    usa o valor do Gradio, nao hardcoded). Ex: flux2_dev embedded_guidance_scale=4 vs distilled=1.
    Cacheado. Fallback se nao achar."""
    ck = (model_id, key)
    if ck in _DEF_PARAM_CACHE:
        return _DEF_PARAM_CACHE[ck]
    val = fallback
    try:
        _wan = os.environ.get("ACS_WAN_DIR", "")
        _p = os.path.join(_wan, "defaults", f"{model_id}.json")
        _d = json.load(open(_p, encoding="utf-8"))
        _m = _d.get("model", {})
        # params ficam no TOPO do def (irmaos de "model"); fallback p/ dentro de "model"
        for _src in (_d, _m):
            if isinstance(_src, dict) and key in _src:
                val = type(fallback)(_src[key]) if fallback is not None else _src[key]
                break
    except Exception:
        val = fallback
    _DEF_PARAM_CACHE[ck] = val
    return val


def _get_inject_video_prompt_type(model_name: str, ui_flag: str = "") -> str:
    """Retorna o video_prompt_type correto para frame/image injection no modelo.

    Cada modelo usa flags diferentes para injetar frames/imagens de referência:
    - LTX2 (ltx2_22B, distilled 1.1): "KFI" — custom_frames_injection via guide_custom_choices
    - VACE (vace_14B, vace_14B_2_2): "FI"  — positioned frames via image_ref_choices
    - Flux2 (flux2_klein_4b/9b, flux2_dev, pi_flux2): respeita ui_flag ("KI" | "I")
        flux_handler.py line 172-180: image_ref_choices nativo do Flux Klein/Kontext.
        Não há tradução — a UI manda a flag final que vai direto em video_prompt_type.
    - Outros modelos: "" — não suportam image_refs

    Referência:
      ltx2_handler.py line 308: guide_custom_choices [("Inject Frames", "KFI")]
      wan_handler.py  line 604: image_ref_choices    [("Positioned Frames...", "FI")]
      flux_handler.py line 172:  image_ref_choices   [("...", "KI"), ("...", "I")]
    """
    model_info = MODELS.get(model_name, {})
    family     = model_info.get("family", "")
    base_type  = model_info.get("base_type", "")
    if family == "ltx2":
        return "KFI"
    if "vace" in base_type.lower():
        return "FI"
    if family == "flux2" and ui_flag in ("KI", "I"):
        return ui_flag
    # wan_i2v, animate, hunyuan, ltxv, flux genérico (Photo Real) — sem suporte
    return ""


def _compute_frames_positions(n_frames: int, video_length: int) -> str:
    """Calcula posições de injeção equidistantes para n_frames num vídeo de video_length frames.

    Retorna string no formato Wan2GP: "N1 N2 N3 ..." onde cada Ni é 1-indexed.
    Posições são distribuídas uniformemente com margem nos extremos.

    Exemplo: n=3, v=81 → step=81/4=20.25 → "20 40 61"
    """
    if n_frames <= 0 or video_length <= 0:
        return ""
    step = video_length / (n_frames + 1)
    positions = []
    for i in range(1, n_frames + 1):
        pos = max(1, min(video_length - 1, round(step * i)))
        positions.append(pos)
    return " ".join(str(p) for p in positions)

# Mapeamento: nome UI → {family, base_type, model_id, image_mode, type}
#   family    = argumento de /change_model_family
#   base_type = argumento de /change_model_base_types (2º param)
#   model_id  = argumento de /change_model e /process_prompt_and_add_tasks
#   image_mode: 1 = imagem, 0 = vídeo (para save_inputs)
#
# TESTADOS E CONFIRMADOS: Flux Fast, Flux Balanced, Flux Cinematic.
# (valide também Flux 2 Dev antes de usar em produção).
# Os demais modelos têm mapeamento preliminar — validar antes de usar.
# ──────────────────────────────────────────────
MODELS = {
    # ── Testado e confirmado ─────────────────
    # NOTA sample_solver: NÃO definir "euler" aqui.
    # O PASSO 4.5 (change_resolution_group) já reseta o componente sample_solver
    # do Gradio para choices=[''] antes do save_inputs. Enviar "euler" causaria
    # ValueError: "Value: euler is not in the list of choices: ['']".
    # O valor correto após o reset é sempre "" (string vazia).
    # Histórico: "euler" foi adicionado para contornar contaminação de sessão BF16,
    # mas o PASSO 4.5 torna esse contorno desnecessário e incorreto.
    "Flux Fast": {
        "family":        "flux2",
        "base_type":     "flux2_klein_4b",
        "model_id":      "flux2_klein_4b",
        "image_mode":    1,
        "type":          "Image",
        "desc":          "Flux Fast — 4B INT8, ultra rápido (~3 GB VRAM)",
        "default_steps": 4,
        "tested":        True,
    },
    "Flux Balanced": {
        "family":        "flux2",
        "base_type":     "flux2_klein_9b",
        "model_id":      "flux2_klein_9b",
        "image_mode":    1,
        "type":          "Image",
        "desc":          "Flux Balanced — 9B INT8, qualidade/velocidade (~6 GB VRAM)",
        "default_steps": 4,
        "tested":        True,
    },
    # [NEXTGEN 2026-06-27] Flux Pro = flux2_dev (o modelo PESADO) — o tier "Pro" que faltava.
    # flux2_dev.json existe no motor; baixa sob demanda (modelo grande, mais lento, maxima qualidade).
    "Flux Pro": {
        "family":             "flux2",
        "base_type":          "flux2_dev",
        "model_id":           "flux2_dev",
        "image_mode":         1,
        "type":               "Image",
        "desc":               "Flux Pro — Flux 2 Dev, maxima qualidade (modelo pesado)",
        "default_steps":      28,
        "tested":             False,
        "download_on_demand": True,
    },
    # ── Flux Cinematic: DESABILITADO na 11.77 ──────────────────────
    # flux2_klein_9b_bf16 foi removido do Wan2GP 11.77 (não existe defaults/flux2_klein_9b_bf16.json).
    # change_model("flux2_klein_9b_bf16") falharia com model not found.
    # Reativar quando 11.77 tiver suporte ao BF16 full precision via model_id dedicado.
    # Alternativa futura: mapear para flux2_klein_9b + profile override para forçar BF16.
    "Flux Cinematic": {
        "family":        "flux2",
        "base_type":     "flux2_klein_9b",
        "model_id":      "flux2_klein_9b_bf16",  # ID removido no 11.77 — desabilitado
        "image_mode":    1,
        "type":          "Image",
        "desc":          "Flux Cinematic — BF16 full precision (Em breve — requer 11.77 BF16 support)",
        "default_steps": 4,
        "tested":        False,
        "disabled":      True,   # [11.77] flux2_klein_9b_bf16 não existe — não expor na UI
    },
    # ── FP8-KV: NÃO APROVADO para produção ──────────────────────
    # flux2_klein_9b_fp8kv falhou em geração (forrtl error 200, sem output).
    # VRAM peak anômalo: 3 541 MB para modelo de 9.14 GB → código de inferência
    # FP8 KV-cache não implementado para Flux2 no Wan2GP atual.
    # Manter JSON em defaults/ mas não registrar no MODELS enquanto não houver suporte.
    # ─────────────────────────────────────────────────────────────
    # ── Mapeamento preliminar (não testados) ─
    # [2026-06-21] Photo Real REMOVIDO: mapeava p/ flux1 ("flux") = sem suporte/não
    # instalado → travava sem output e segurava o lock 1200s. Não estava no frontend.
    # ── Vídeo — instalados em ckpts/ ────────────────────────────
    # base_type = argumento p/ change_model_base_types (choices disponíveis no Gradio)
    # model_id  = argumento p/ change_model (variante específica)
    #
    # NÃO INSTALADO: ltx-2-19b-distilled_Q4_K_M.gguf
    # Wan2GP tem ckpts/ltx-2-19b-distilled_Q4_K_M.gguf.lock → auto-download no 1º uso
    # download_on_demand=True: FIX-API-02 permite passagem; Wan2GP faz download automático
    # timeout PASSO 10: 3600s (cobre download ~16 GB + geração)
    "Cinematic Lite": {
        "family":           "ltx2",
        "base_type":        "ltx2_19B",
        "model_id":         "ltx2_distilled_gguf_q4_k_m",
        "image_mode":       0,
        "type":             "Video",
        "performance":      "fast",          # tier comercial: fast / balanced / pro
        "desc":             "LTX 2.0 19B — leve e rápido (~6-8 GB VRAM)",
        "default_steps":    8,
        "tested":           True,
        "installed":        False,           # arquivo não presente em ckpts/
        "download_on_demand": True,          # [ETAPA-2] Wan2GP .lock file presente → auto-download
        "download_gb":      16,
        "supports_i2v":     True,
        "supports_audio":   True,
    },
    # INSTALADO: ltx-2.3-22b-distilled-1.1_diffusion_model_quanto_bf16_int8.safetensors
    "Cinematic Pro 1.1": {
        "family":        "ltx2",
        "base_type":     "ltx2_22B",
        "model_id":      "ltx2_22B_distilled_1_1",
        "image_mode":    0,
        "type":          "Video",
        "performance":   "balanced",      # tier comercial: fast / balanced / pro
        "desc":          "LTX 2.3 22B Distilled 1.1 — rápido",
        "default_steps": 8,   # [BUILD25] 6→8: alinha com Wan2GP (validate_generative_settings força 8 para distilled)
        "tested":        True,
        "supports_i2v":  True,
        "supports_audio": True,
    },
    # [FIX-22B 2026-06-28] Distilled 1.1 cabe em 16 GB; Dev puro dá OOM.
    # Gradio do Luigi usa ltx2_22B_distilled_1_1 (wgp_config last_model_per_type).
    "Cinematic Pro Full": {
        "family":        "ltx2",
        "base_type":     "ltx2_22B_distilled_1_1",
        "model_id":      "ltx2_22B_distilled_1_1",
        "image_mode":    0,
        "type":          "Video",
        "performance":   "pro",
        "desc":          "LTX 2.3 22B Distilled 1.1 — qualidade máxima",
        "default_steps": 8,
        "tested":        True,
        "supports_i2v":  True,
        "supports_audio": True,
    },
    # [LIGHT-8GB] WAN 2.1 1.3B — único modelo de vídeo LEVE de verdade (~6-8 GB VRAM).
    # Pesquisa oficial: todos os LTX são >=13B (não cabem em 8GB); WAN 1.3B é o canônico "GPU-poor".
    # def: Wan2GP_Dev/defaults/t2v_1.3B.json ("Wan2.1 Text2video 1.3B", arch t2v_1.3B).
    "Light 8GB": {
        "family":             "wan",
        "base_type":          "t2v_1.3B",
        "model_id":           "t2v_1.3B",
        "image_mode":         0,
        "type":               "Video",
        "performance":        "fast",
        "desc":               "WAN 2.1 1.3B — vídeo leve e rápido, roda em ~6-8 GB VRAM",
        "default_steps":      20,
        "tested":             True,
        "installed":          False,
        "download_on_demand": True,
        "download_gb":        3,
        "supports_i2v":       False,
        "supports_audio":     False,
    },
    # [LIGHT-8GB] Fun InP 1.3B — I2V leve (~6 GB). Doc oficial Wan2GP GETTING_STARTED:
    # recomendado para 6-8 GB ("Fast image animation"). def: defaults/fun_inp_1.3B.json (arch fun_inp_1.3B).
    "Light I2V 8GB": {
        "family":             "wan",
        "base_type":          "fun_inp_1.3B",
        "model_id":           "fun_inp_1.3B",
        "image_mode":         0,
        "type":               "Video",
        "performance":        "fast",
        "desc":               "Wan Fun InP 1.3B — animar imagem (I2V) leve, ~6 GB VRAM",
        "default_steps":      20,
        "tested":             True,   # libera acesso na UI; validação no 6-8GB pendente
        "installed":          False,
        "download_on_demand": True,
        "download_gb":        3,
        "supports_i2v":       True,
        "supports_audio":     False,
    },
    # INSTALADO: wan2.1_image2video_480p_14B_quanto_mbf16_int8.safetensors
    # WAN oculto do selector principal por decisão de produto (foco LTX)
    "Studio AI I2V": {
        "family":        "wan",
        "base_type":     "i2v",
        "model_id":      "i2v",
        "image_mode":    0,
        "type":          "Video",
        "desc":          "WAN 2.1 I2V — imagem para vídeo",
        "default_steps": 20,
        "tested":        False,
        "supports_i2v":  True,
        "supports_audio": False,
    },
    # ── MOTION TAB — Talking Head / Avatar ──────────────────────────────────
    # base_type="multitalk" — parent independente na hierarquia Gradio (NÃO filho de i2v).
    # Requer: wan2.1_image2video_480p_14B_quanto_mbf16_int8.safetensors (base i2v)
    #         + módulo multitalk (baixado automaticamente pelo Wan2GP na 1ª vez).
    "Talking Head": {
        "family":        "wan",
        "base_type":     "multitalk",
        "model_id":      "multitalk",
        "image_mode":    0,
        "type":          "Video",
        "desc":          "Wan2.1 MultiTalk — talking head com sincronismo de voz",
        "default_steps": 20,
        "tested":        False,
        "supports_i2v":  True,
        "supports_audio": True,
        "motion_tab":    True,
    },
    "Infinite Talk": {
        "family":        "wan",
        "base_type":     "infinitetalk",
        "model_id":      "infinitetalk",
        "image_mode":    0,
        "type":          "Video",
        "desc":          "Wan2.1 InfiniteTalk — conversa longa com múltiplas cenas",
        "default_steps": 20,
        "tested":        False,
        "supports_i2v":  True,
        "supports_audio": True,
        "motion_tab":    True,
    },
    # INSTALADO: wan2.2_animate_14B_quanto_bf16_int8.safetensors
    "Studio Editor": {
        "family":        "wan2_2",
        "base_type":     "wan2_2",
        "model_id":      "i2v_2_2",
        "image_mode":    0,
        "type":          "Video",
        "desc":          "Wan2.2",
        "default_steps": 20,
        "tested":        False,
    },
    "Director Vision": {
        "family":        "hunyuan",
        "base_type":     "hunyuan",
        "model_id":      "hunyuan",
        "image_mode":    0,
        "type":          "Video",
        "desc":          "HunyuanVideo",
        "default_steps": 30,
        "tested":        False,
    },
    "Director Vision Lite": {
        "family":        "hunyuan_1_5",
        "base_type":     "hunyuan_1_5",
        "model_id":      "hunyuan_1_5",
        "image_mode":    0,
        "type":          "Video",
        "desc":          "HunyuanVideo 1.5",
        "default_steps": 20,
        "tested":        False,
    },
    "Cinematic Light": {
        "family":        "ltxv",
        "base_type":     "ltxv",
        "model_id":      "ltxv",
        "disabled":      True,   # [NEXTGEN 2026-06-27] ltxv nao existe no motor 12.281 (LTX virou ltx2_*) -> ocultado ate remapear
        "image_mode":    0,
        "type":          "Video",
        "desc":          "LTX Video 1",
        "default_steps": 20,
        "tested":        False,
    },
    "Z-Image Turbo": {
        "family":     "z_image",
        "base_type":  "z_image",
        "model_id":   "z_image",
        "image_mode": 1,
        "type":       "Image",
        "desc":       "Z-Image Turbo 6B — ultra rápido",
        "default_steps": 8,
        "tested":     True,
    },
    # [12.281] 2 modelos novos do update (imagem text-to-image). model_id = nome do defaults/*.json.
    "Krea 2 Turbo": {
        "family":        "krea2",
        "base_type":     "krea2_turbo",
        "model_id":      "krea2_turbo",
        "image_mode":    1,
        "type":          "Image",
        "desc":          "Krea 2 Turbo — imagem estética, rápido (8 steps)",
        "default_steps": 8,
        "tested":        True,
    },
    "Krea 2 RAW": {
        "family":        "krea2",
        "base_type":     "krea2_raw",
        "model_id":      "krea2_raw",
        "image_mode":    1,
        "type":          "Image",
        "desc":          "Krea 2 RAW — imagem estética, qualidade máxima (52 steps)",
        "default_steps": 52,
        "tested":        True,
    },
    "Creative Canvas": {
        "family":     "kandinsky5",
        "base_type":  "kandinsky5",
        "model_id":   "kandinsky5",
        "disabled":   True,   # [NEXTGEN 2026-06-27] kandinsky5 removido do motor 12.281 -> ocultado
        "image_mode": 1,
        "type":       "Image",
        "desc":       "Kandinsky 5",
        "tested":     False,
    },
    "Human Studio": {
        "family":     "magi_human",
        "base_type":  "magi_human",
        "model_id":   "magi_human",
        "image_mode": 0,
        "type":       "Video",
        "desc":       "Magi Human",
        "tested":     False,
    },
    "Infinite Motion": {
        "family":     "longcat",
        "base_type":  "longcat",
        "model_id":   "longcat_video",
        "image_mode": 0,
        "type":       "Video",
        "desc":       "LongCat",
        "tested":     False,
    },
    # ── Áudio (TTS / Music) — family="tts", image_mode=2 ────────────────────
    # Instalados em Wan2GP_Dev/models/TTS/
    # Referência: ace_step_handler.py, chatterbox_handler.py, index_tts2_handler.py
    "ace_step_v1": {
        "family":        "tts",
        "base_type":     "ace_step_v1",
        "model_id":      "ace_step_v1",
        "image_mode":    2,        # 2 = audio-only (interno ACS)
        "type":          "Audio",
        "desc":          "ACE-Step v1.0 3.5B — música (Lyrics → Audio)",
        "default_steps": 60,       # Fonte: ace_step_handler.py update_default_settings
        "tested":        False,
    },
    "ace_step_v1_5": {
        "family":        "tts",
        "base_type":     "ace_step_v1_5",
        "model_id":      "ace_step_v1_5",
        "image_mode":    2,
        "type":          "Audio",
        "desc":          "ACE-Step v1.5 Turbo 2B — música com caption e cover",
        "default_steps": 8,        # Turbo: lock_inference_steps=True, default=8
        "tested":        False,
    },
    "ace_step_v1_5_xl": {
        "family":        "tts",
        "base_type":     "ace_step_v1_5_xl",
        "model_id":      "ace_step_v1_5_xl",
        "image_mode":    2,
        "type":          "Audio",
        "desc":          "ACE-Step v1.5 XL Turbo 4B — música de alta qualidade",
        "default_steps": 8,        # Turbo: lock_inference_steps=True, default=8
        "tested":        False,
    },
    "chatterbox": {
        "family":        "tts",
        "base_type":     "chatterbox",
        "model_id":      "chatterbox",
        "image_mode":    2,
        "type":          "Audio",
        "desc":          "Chatterbox — TTS multilingual com clonagem de voz",
        "default_steps": 60,       # inference_steps=False (valor ignorado pelo handler)
        "tested":        False,
    },
    "index_tts2": {
        "family":        "tts",
        "base_type":     "index_tts2",
        "model_id":      "index_tts2",
        "image_mode":    2,
        "type":          "Audio",
        "desc":          "IndexTTS2 — TTS de alta qualidade",
        "default_steps": 60,       # inference_steps=False (valor ignorado pelo handler)
        "tested":        False,
    },
    "heartmula_oss_3b": {
        "family":        "tts",
        "base_type":     "heartmula_oss_3b",
        "model_id":      "heartmula_oss_3b",
        "image_mode":    2,
        "type":          "Audio",
        "desc":          "HeartMuLa 3B — geração de música com letras",
        "default_steps": 60,       # inference_steps=False (valor ignorado pelo handler)
        "tested":        False,
    },
    "kugelaudio_0_open": {
        "family":        "tts",
        "base_type":     "kugelaudio_0_open",
        "model_id":      "kugelaudio_0_open",
        "image_mode":    2,
        "type":          "Audio",
        "desc":          "KugelAudio 0 Open 7B — TTS difusão de alta qualidade",
        "default_steps": 60,       # valor a confirmar após teste
        "tested":        False,
    },
    "qwen3_tts_base": {
        "family":        "tts",
        "base_type":     "qwen3_tts_base",
        "model_id":      "qwen3_tts_base",
        "image_mode":    2,
        "type":          "Audio",
        "desc":          "Qwen3 TTS 1.7B — TTS multilingual com clonagem de voz",
        "default_steps": 60,       # inference_steps=False (valor ignorado pelo handler)
        "tested":        False,
    },
}

# [12.24-MODELS] Modelos novos do WanGP 12.24 — registrados SÓ quando _API_V2 (instância ISO 12.24).
# DEV 11.77 (sem ACS_GRADIO_API_V2) NÃO os enxerga → frontend/geração do DEV inalterados.
# Regra de mapeamento (derivada das defs): base_type = architecture, model_id = nome do arquivo def, family = group/família.
_NEW_1224_MODELS = {
    "Cinematic EditAnything": {   # ltx2_22B_edit_anything (distilled 1.1 = rápido) — reusa base ltx2_22B
        "family": "ltx2", "base_type": "ltx2_22B_edit_anything",
        "model_id": "ltx2_22B_distilled_1_1_edit_anything",
        "image_mode": 0, "type": "Video", "performance": "balanced",
        "desc": "Edição de vídeo por referência (LTX2 EditAnything)",
        "default_steps": 8, "sample_solver": "",  # distilled → solver vazio (distilled_8_steps); euler quebra (choices=[''])
        "needs_image_ref": True,   # [12.24] edição ref-V2V: ref vai em image_refs (senão "must provide Image Reference")
        "tested": True, "supports_i2v": True,
    },
    "Cinematic Edit": {           # Bernini-R 1.3B (leve) — edição v2v com ref
        "family": "wan2_2", "base_type": "bernini_1.3B", "model_id": "bernini_1.3B",
        "image_mode": 0, "type": "Video", "performance": "pro",
        "desc": "Edição de vídeo com imagem de referência (Bernini-R)",
        "default_steps": 40, "sample_solver": "unipc",
        "needs_image_ref": True,   # [12.24] Bernini VI: ref vai em image_refs
        "tested": True, "supports_i2v": True,
    },
    # [NEXTGEN 2026-06-27] Bernini-R 14B (Wan2.2) — o grande/incrivel. v2v ou novo com refs.
    # v2v+ref = 15 steps + guidance (sem lora); v2v+lightning lora = 4 steps (lora baixa sob demanda).
    "Cinematic Edit Pro": {
        "family": "wan2_2", "base_type": "bernini", "model_id": "bernini",
        "image_mode": 0, "type": "Video", "performance": "pro",
        "desc": "Edicao Pro (Bernini-R 14B) — modifica video existente ou cria com referencias",
        "default_steps": 15, "sample_solver": "unipc",
        "needs_image_ref": True,
        "tested": False, "supports_i2v": True,
        "download_on_demand": True,
    },
    "Multi-Personagem": {         # [2026-06-26] ltx2_22B_msr — referência multi-personagem por IMAGEM (MSR LoRA)
        "family": "ltx2", "base_type": "ltx2_22B_msr", "model_id": "ltx2_22B_msr",
        "image_mode": 0, "type": "Video", "performance": "pro",
        "desc": "Vários personagens de fotos de referência (sobe 2-5 imagens: fundo + até 4 sujeitos)",
        "default_steps": 8, "sample_solver": "",   # distilled → solver vazio (distilled_8_steps)
        "needs_image_ref": True,    # refs vão em image_refs; modo (Background+Subjects=KI / Subjects=I) via video_prompt_type
        "msr_mode": "KI",           # default: Background + até 4 Subjects (motor default)
        "tested": True, "supports_i2v": False,   # [MSR 06-28] tested=True habilita a seleção na UI
    },
    "Typography Image": {         # Ideogram v4 — imagem com texto/tipografia
        "family": "ideogram4", "base_type": "ideogram4_turbotime", "model_id": "ideogram4_turbotime",
        # [2026-06-21] TURBO TIME: 1 transformer só (sem Unconditional/uncond), no-guidance, 8 steps.
        # ideogram4 FULL tem 2 transformers (14.7GB) que NÃO cabem em 16GB => swap 138s/passo (~27min).
        # TurboTime = 1 transformer (~7.3GB) cabe folgado => rápido. Mesmo peso fp8 já baixado.
        "image_mode": 1, "type": "Image", "performance": "balanced",
        "desc": "Imagem com tipografia/texto (Ideogram v4 Turbo) — usar enhancer",
        "default_steps": 8, "sample_solver": "euler",  # distilled 8-step, no-guidance
        "tested": True,
    },
    "Story AV": {                 # JoyAI-Echo — vídeo+áudio multi-cena
        "family": "ltx2", "base_type": "joyai_echo", "model_id": "joyai_echo",
        "image_mode": 0, "type": "Video", "performance": "pro",
        "desc": "Histórias áudio+vídeo multi-cena (JoyAI-Echo)",
        "default_steps": 8, "sample_solver": "euler",
        "tested": True, "supports_audio": True, "supports_i2v": True,   # [2026-06-21] verificado: gera vídeo+áudio; Start Image (image_prompt_type "S") aplica na janela 1 (joyai_echo.py:93)
    },
    "Character Animate": {        # SCAIL-2 — animação de personagem
        "family": "wan", "base_type": "scail2_14B", "model_id": "scail2_14B",
        "image_mode": 0, "type": "Video", "performance": "pro",
        "desc": "Animação de personagem (pose+mask+ref) — SCAIL-2",
        "default_steps": 40,
        "tested": True,   # [2026-06-21] validado: gera GPU 100%, saída real c/ áudio; hang troca-família corrigido
    },
    "Music Studio": {             # Stable Audio 3 small — música/loops
        "family": "tts", "base_type": "stable_audio3_small", "model_id": "stable_audio3_small",
        "image_mode": 2, "type": "Audio", "performance": "balanced",
        "desc": "Música/loops/SFX (Stable Audio 3)",
        "default_steps": 8, "sample_solver": "pingpong",
        "tested": True,
    },
}
for _m in _NEW_1224_MODELS.values():
    _m.setdefault("first_use_dl", True)  # [12.24] baixam no 1º uso → timeout 3600s (NÃO usar installed:False, que BLOQUEIA a geração)
if _API_V2 or _USE_WANSESSION:
    MODELS.update(_NEW_1224_MODELS)

# Grupos de resolução do Wan2GP (mirrors de group_thresholds em wgp.py)
_RES_GROUP_THRESHOLDS = [
    ("256p",  448  * 256),
    ("320p",  448  * 448),
    ("384p",  512  * 512),
    ("480p",  832  * 624),
    ("540p",  960  * 544),
    ("720p",  1024 * 1024),
    ("1080p", 1920 * 1088),
    ("1440p", 2560 * 1440),
    ("2160p", 3840 * 2176),
]

def _get_guidance_phases(model_name: str) -> int:
    """
    Retorna guidance_phases correto para o modelo.

    LTX2 (família ltx2): 2 → habilita pipeline two-stage da distilled/dev pipeline.
      Stage 1: roda em resolução METADE (mais rápido — attention é O(n²))
      Stage 2: denoising em resolução COMPLETA (3 steps ~"3/3 denoise" no Gradio)

    PROVA: ltx2_handler.py L.86/L.643 define guidance_phases=2 como padrão.
           ltx2.py L.1233: skip_stage_2 = guide_phases <= 1
           distilled.py L.398-399: Stage1 usa width//2, height//2 se skip_stage_2=False
           Enviar 1 → Stage 1 em resolução completa → 3.7× mais lento por step.

    Outros modelos: 1 (guidance_max_phases=0 no model_def → clampa para 1 internamente).
    """
    _minfo = MODELS.get(model_name, {})
    family = _minfo.get("family", "")
    # [STORY-AV-ALIGN 2026-07-04] JoyAI-Echo recomenda guidance_phases=1 (estabilidade da
    # memoria multi-janela = default do Gradio para joyai_echo, confirmado via view_api).
    # Choosable: guidance_phases_override != -1 ainda forca o valor que o cliente escolher.
    if _minfo.get("base_type") == "joyai_echo":
        return 1
    if family == "ltx2":
        return 2  # [G1-PERF] two-stage: Stage1 half-res + Stage2 full-res denoise
    return 1


def _resolution_group(res_str: str) -> str:
    """Retorna o grupo de resolução Wan2GP para uma string 'WxH'."""
    try:
        w, h = map(int, res_str.split("x"))
        px = w * h
        for group, threshold in _RES_GROUP_THRESHOLDS:
            if px <= threshold:
                return group
        return "2160p"
    except Exception:
        return "720p"


# Mapa resolução UI → string Gradio
# Resoluções de vídeo válidas Wan2GP 11.77 por grupo (auditado):
#   256p: 448x256, 256x448, 320x320
#   320p: 576x320, 320x576, 448x448
#   384p: 672x384, 384x672, 512x512
#   480p: 832x480, 480x832, 832x624, 624x832, 720x720
#   540p: 960x544, 544x960
#   720p: 1280x720, 720x1280, 1024x1024, 960x960, 1104x832, 832x1104, 1280x544, 544x1280
#   1080p: 1920x1088, 1088x1920, 1920x832, 832x1920
#   1440p: 2560x1440, 1440x2560 (+ variantes 4:3, 3:2, 1:1, 21:9)
RESOLUTION_MAP = {
    "480p":  "832x480",
    "720p":  "1280x720",
    "1080p": "1920x1088",
    "1440p": "2560x1440",
    # Resoluções de imagem quadrada
    "1:1":   "1024x1024",
    "512":   "512x512",    # válido: 384p (Flux image)
    "1024":  "1024x1024",
    # Aliases para resoluções removidas no Wan2GP 11.77 — redireciona para válida mais próxima
    # 512x288 (16:9 320p) foi removida → 576x320 é a válida 16:9 do grupo 320p
    "512x288": "576x320",
    "288x512": "320x576",  # portrait equivalente
}


# ──────────────────────────────────────────────
# SCHEMAS
# ──────────────────────────────────────────────
class GenerateRequest(BaseModel):
    prompt: str
    model: str = "Flux Balanced"
    resolution: str = "1024x1024"       # string direta "WxH" ou chave do RESOLUTION_MAP
    duration: int = 5                   # segundos (vídeo)
    negative_prompt: str = ""
    steps: int = 4
    seed: int = -1                      # -1 = aleatório
    # ── Modo de geração ─────────────────────────────────────────────
    generation_mode: str = "t2v"        # "t2v" | "i2v" | "flf" | "continue" | "t2i"
    # ── Referências ─────────────────────────────────────────────────
    ref_image_path: str = ""            # start frame: I2V / FLF / image_refs
    ref_inject_paths: list[str] = []   # Frame Inject multi-slot (T2V)
    frames_positions: str = ""          # [FIX-INJECT] posições manuais "0 24 48" (vazio = auto)
    end_image_path: str = ""            # end frame: FLF
    ctrl_video_path: str = ""           # video source: Continue / control video
    ctrl_image_path: str = ""           # control image path (pose/inpaint)
    # ── Parâmetros de injeção/controle ──────────────────────────────
    inject_video_prompt_type: str = ""  # "" | "KI" | "I"  → ref images
    msr_mode: str = ""                  # [MSR] "KI"=Fundo+Sujeitos | "I"=só Sujeitos; vazio=default do modelo
    ctrl_video_prompt_type: str = ""    # "" | "PVG"=Human Motion | "OVG"=PoseAlign | "DVG"=Depth | "EVG"=Canny | "VG"=RawFormat | "V&G"=HDR | "KFI"=InjectFrames | "V"=JoyAI Control Video Memory (motor mapeia V→V1)
    joyai_control_memory_positions: str = ""  # JoyAI Control Video Memory: "2s,8s" ou "man=2s,woman=8s" (máx 60s; vazio=auto não-silêncio) → custom_settings
    # [TRIM-VÍDEO 2026-06-26] corte por frames (settings padrão do motor, _settings.json)
    keep_frames_video_guide:  str = ""  # control video: ""=todos, "1"=1º, "a:b"=range, espaço separa, -1=último
    keep_frames_video_source: str = ""  # continue video: inteiro (vazio=todos, negativo corta do fim)
    force_control_video_trim: int = 0   # [CAP-AUDIO] 1 = "Capped By: Control Length" (motor: "|" no video_prompt_type)
    source_strength: float = 1.0        # input_video_strength (0–1)
    # ── Qualidade / movimento ────────────────────────────────────────
    guidance_scale: float = 5.0         # CFG scale (5.0 padrão para vídeo, 3.5 para flux)
    motion_amplitude: float = 1.0       # Amplitude de movimento (0.0–2.0, padrão 1.0)
    # ── Áudio ───────────────────────────────────────────────────────
    audio_prompt_type: str = ""         # "" | "A" | "A1OF" | "K" | "2" | "B" (dual-speaker MultiTalk)
    audio_path: str = ""                # path do arquivo de áudio — audio_guide (conditioning)
    audio_source_path: str = ""         # path do arquivo de áudio — audio_source (mux direto, sem AI)
    audio_scale: float = 1.0           # Prompt Audio Strength 0–1 (LTX-2 conditioning strength)
    audio_guidance_scale: int = 4       # Audio CFG scale (hardcoded=4 no Wan2GP, exposto para controle)
    audio_path2: str = ""               # segundo áudio — segundo falante (MultiTalk dual-speaker)
    speakers_locations: str = ""        # bboxes dual speaker: "0:45 55:100" (padrão Wan2GP)
    seedvc_voice_sample: str = ""       # SeedVC: target voice WAV (audio_prompt_type="V")
    seedvc_voice_sample2: str = ""      # SeedVC: segundo falante voice WAV (dual-speaker)
    mmaudio: int = 0                    # 0=desabilitado, 1=MMAudio (gera áudio AI pós-geração)
    mux_audio_path: str = ""            # [AUDIO-FIX 06-28] api-interno: áudio (control video original) p/ muxar no output pós-geração
    prompt_enhancer: str = "T"         # "" = off, "T" = enhance from text, "TI" = text+image, "T1" = Prompt Relay (timed segments), "TI1" = Prompt Relay + image
    # ── LoRAs ───────────────────────────────────────────────────────
    loras_choices: list = []
    loras_multipliers: str = ""
    # ── Advanced Mode 11.77 ─────────────────────────────────────────
    riflex_setting:           int = 0   # 0=off, 1=on, 2=extended (vídeos longos)
    temporal_upsampling:      str = ""  # ""|"rife2"|"rife4" — dobrar/quadruplicar FPS
    self_refiner_setting:     int = 0   # 0=off, 1=básico, 2=extended (11.77+)
    spatial_upsampling:       str = ""  # ""|"lanczos"|"flashvsr"|"flashvsr2pass" (LTX 11.77)
    guidance_phases_override: int = -1  # -1=auto, 1=single-stage, 2=two-stage (LTX2)
    force_fps:                str = ""  # ""|"8"|"16"|"24" — força FPS de saída
    # ── Film Grain [FIX-BLOCKER-02] ─────────────────────────────────────
    film_grain_intensity:     float = 0.0  # 0.0–1.0; 0=sem grain
    film_grain_saturation:    float = 0.5  # 0.0–1.0; saturação do grain


# ──────────────────────────────────────────────
# [1177] BREAKING CHANGE MIGRATION HELPERS
# MMAudio_setting (int, v11.52) → postprocess_audio (str, v11.77)
# ──────────────────────────────────────────────
_MMAUDIO_INT_TO_POSTPROCESS: dict[int, str] = {
    0: "",               # desabilitado
    1: "mmaudio",        # MMAudio (gera áudio AI pós-geração)
    2: "custom",         # Custom audio post-processing
    3: "control",        # Control audio
}

def _mmaudio_to_postprocess(value: int) -> str:
    """Converte MMAudio_setting int (v11.52) para postprocess_audio str (v11.77)."""
    return _MMAUDIO_INT_TO_POSTPROCESS.get(int(value), "")


# ──────────────────────────────────────────────
# AUDIO — Mapeamento custom_setting_N por modelo
# ──────────────────────────────────────────────
# Mapeia a ordem dos custom settings de cada modelo TTS
# para os slots custom_setting_1..5 do save_inputs Gradio.
# Referência: ACE_STEP15_CUSTOM_SETTINGS, CHATTERBOX_CUSTOM_SETTINGS
_AUDIO_CUSTOM_SETTINGS_ORDER: dict[str, list[str]] = {
    # Fonte: ACE_STEP15_CUSTOM_SETTINGS (ace_step_handler.py) — ordem dos slots
    "ace_step_v1_5":    ["bpm", "keyscale", "timesignature", "language"],
    "ace_step_v1_5_xl": ["bpm", "keyscale", "timesignature", "language"],
    # Fonte: CHATTERBOX_CUSTOM_SETTINGS (chatterbox_handler.py)
    "chatterbox":       ["exaggeration", "pace"],
    # Fonte: KUGELAUDIO_CUSTOM_SETTINGS (kugelaudio_handler.py)
    "kugelaudio_0_open": ["auto_split_every_s"],
    # Fonte: QWEN3_TTS_CUSTOM_SETTINGS (qwen3_handler.py)
    "qwen3_tts_base":   ["auto_split_every_s"],
    # ace_step_v1:    sem custom settings
    # heartmula_oss_3b: sem custom settings no model_def
    # index_tts2:     INDEX_TTS2_CUSTOM_SETTINGS = [] (auto_split injetado internamente)
}

def _build_audio_custom_slots(base_type: str, custom_settings: dict) -> list[str]:
    """Mapeia custom_settings dict para lista de 5 strings (custom_setting_1..5).

    Usa a ordem definida em _AUDIO_CUSTOM_SETTINGS_ORDER para cada modelo.
    Slots não preenchidos ficam como string vazia "".
    """
    order = _AUDIO_CUSTOM_SETTINGS_ORDER.get(base_type, [])
    slots = [""] * 5
    for i, key in enumerate(order[:5]):
        val = custom_settings.get(key)
        if val is not None:
            slots[i] = str(val)
    return slots


class AudioGenerateRequest(BaseModel):
    """Schema para geração de áudio (TTS / Music) via modelos TTS do Wan2GP."""
    model: str = "ace_step_v1"          # chave do MODELS dict
    prompt: str = ""                    # letras / texto a falar
    alt_prompt: str = ""                # Music Caption / Emotion / Tags
    seed: int = -1                      # -1 = aleatório
    num_generations: int = 1            # repeat_generation
    duration_seconds: float = 20.0     # duração em segundos
    temperature: float = 1.0           # temperatura de amostragem
    guidance_scale: float = 7.0        # CFG scale
    audio_prompt_type: str = ""        # "" | "A" | "B" | "AB" (cover/timbre)
    audio_guide: str = ""              # path: áudio de referência (Source Audio)
    audio_guide2: str = ""             # path: segundo áudio de referência
    audio_scale: float = 0.5           # Prompt Audio Strength
    top_k: int = 50
    top_p: float = 0.9
    alt_guidance_scale: float = 2.5    # LM Guidance (CFG) para ace_step_v1_5
    num_inference_steps: int = -1      # -1 = usa default do modelo (MODELS["default_steps"])
    model_mode: Optional[str] = None   # model-specific mode (LM Chain of Thought, etc.)
    custom_settings: dict = {}         # {bpm, keyscale, timesignature, language, exaggeration, pace}


# ──────────────────────────────────────────────
# UPLOAD SIZE LIMITS — SECURITY HOTFIX
# Impacto na geração: ZERO (só afeta recebimento de ficheiros de referência/áudio)
# ──────────────────────────────────────────────
_MAX_REF_IMAGE_BYTES = 25  * 1024 * 1024   # 25 MB  — imagens de referência
_MAX_REF_VIDEO_BYTES = 500 * 1024 * 1024   # 500 MB — vídeos de referência
_MAX_AUDIO_BYTES     = 100 * 1024 * 1024   # 100 MB — áudio
_UPLOAD_CHUNK        = 1   * 1024 * 1024   # 1 MB chunk de leitura

_UPLOAD_VIDEO_SUFFIXES = {".mp4", ".webm", ".mov"}


async def _read_limited(file: UploadFile, max_bytes: int) -> bytes:
    """
    Lê UploadFile em chunks de 1 MB com limite de tamanho.
    Lança HTTPException 400 se o arquivo exceder max_bytes.
    Nunca carrega > max_bytes+1 MB na memória ao mesmo tempo.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(_UPLOAD_CHUNK)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            mb = max_bytes // (1024 * 1024)
            raise HTTPException(
                status_code=400,
                detail=f"Arquivo muito grande. Limite: {mb} MB.",
            )
        chunks.append(chunk)
    return b"".join(chunks)


# ──────────────────────────────────────────────
# ENDPOINTS
# ──────────────────────────────────────────────

# ── Dev / Internal tools (gated — requires _is_dev_environment() == True) ─────

if _IS_DEV:

    @app.post("/api/dev/reset-license")
    def dev_reset_license():
        """
        Dev-only: remove todos os caches de licença locais para simular instalação limpa.

        Apaga:
          %APPDATA%\\ACS Unlimited\\license.dat   (acs_license_real.py)
          %APPDATA%\\ACS Studio\\license.dat      (license_cache.py — versão anterior)
          ROOT/user/license/license.json          (cache do launcher)

        Usar apenas para testes internos. Não exposto na UI de produção.
        """
        import shutil
        appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        removed = []
        errors  = []

        targets = [
            appdata / "ACS Unlimited" / "license.dat",
            appdata / "ACS Studio"    / "license.dat",
            BASE_DIR.parent / "user" / "license" / "license.json",
            BASE_DIR.parent / "user" / "license" / "license.dat",
        ]

        for t in targets:
            try:
                if t.exists():
                    t.unlink()
                    removed.append(str(t))
            except Exception as e:
                errors.append(f"{t}: {e}")

        print(f"[DEV] reset-license: removed={removed}, errors={errors}")
        return {
            "removed": removed,
            "errors":  errors,
            "message": f"Cache removido ({len(removed)} arquivo(s)). Reinicie o launcher para testar licença limpa."
        }

    @app.get("/api/dev/license-cache-paths")
    def dev_license_cache_paths():
        """Dev-only: mostra onde os caches de licença estão e se existem."""
        appdata = Path(os.environ.get("APPDATA", str(Path.home() / "AppData" / "Roaming")))
        paths = {
            "acs_unlimited": str(appdata / "ACS Unlimited" / "license.dat"),
            "acs_studio_legacy": str(appdata / "ACS Studio" / "license.dat"),
            "user_license_json": str(BASE_DIR.parent / "user" / "license" / "license.json"),
        }
        return {p: {"path": v, "exists": Path(v).exists()} for p, v in paths.items()}


# ── [TRIAL-GATE Peça 2] Licença/features p/ o frontend gatear (read-only) ────
@app.get("/license/features")
def license_features():
    """Plano + features do usuário atual. Para o frontend mostrar/travar o que é do plano.
    Enforcement REAL fica no /generate (Peça 3) — isto é só UX/upsell."""
    return _current_license()


# ── Appearance settings (ui_scale, theme) ────────────────────────────────────

_SETTINGS_PATH = BASE_DIR.parent / "user" / "settings" / "settings.json"
_SETTINGS_DEFAULTS = {
    "_comment": "ACS Studio user settings — auto-generated on first launch",
    "_version": "1.0",
    "last_tab": "image",
    "sidebar_collapsed": False,
    "theme": "dark",
    "ui_scale": 100,   # 90 | 100 | 110 | 125
}


def _load_settings() -> dict:
    try:
        if _SETTINGS_PATH.exists():
            data = json.loads(_SETTINGS_PATH.read_text(encoding="utf-8"))
            for k, v in _SETTINGS_DEFAULTS.items():
                data.setdefault(k, v)
            return data
    except Exception:
        pass
    return dict(_SETTINGS_DEFAULTS)


def _save_settings(data: dict) -> None:
    _SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _SETTINGS_PATH.write_text(json.dumps(data, indent=4, ensure_ascii=False),
                               encoding="utf-8")


@app.get("/api/appearance")
def get_appearance():
    """Retorna configurações de aparência (ui_scale, theme)."""
    cfg = _load_settings()
    return {
        "ui_scale": cfg.get("ui_scale", 100),
        "theme":    cfg.get("theme",    "dark"),
    }


@app.post("/api/appearance")
async def save_appearance(request: Request):
    """
    Salva configurações de aparência.
    Body JSON: {"ui_scale": 100}  (90 | 100 | 110 | 125)
    Retorna {"ok": true, "message": "..."}
    """
    try:
        body = await request.json()
    except Exception:
        return {"ok": False, "error": "invalid JSON"}

    cfg = _load_settings()
    changed = []

    if "ui_scale" in body:
        scale = int(body["ui_scale"])
        if scale not in (90, 100, 110, 125):
            return {"ok": False, "error": f"ui_scale inválido: {scale}. Use 90, 100, 110 ou 125."}
        cfg["ui_scale"] = scale
        changed.append(f"ui_scale={scale}")

    if "theme" in body:
        cfg["theme"] = str(body["theme"])
        changed.append(f"theme={body['theme']}")

    _save_settings(cfg)
    print(f"[ACS API] appearance updated: {', '.join(changed)}")
    return {
        "ok": True,
        "message": f"Aparência salva ({', '.join(changed)}). Reabrir o ACS para aplicar ui_scale.",
        "ui_scale": cfg["ui_scale"],
        "theme":    cfg["theme"],
    }


@app.get("/health")
def health():
    """Verifica se a API e o Gradio estão acessíveis (TCP ping, < 5ms)."""
    import socket
    try:
        s = socket.create_connection(("127.0.0.1", _WAN_PORT), timeout=2.0)
        s.close()
        return {"status": "ok", "gradio": GRADIO_URL, "api": f"localhost:{API_PORT}"}
    except OSError:
        return {"status": "degraded", "error": "Motor de IA não acessível"}


@app.get("/health/watchdog")
def health_watchdog():
    """Retorna o último status gravado pelo acs_watchdog.py."""
    status_path = BASE_DIR / "user" / "temp" / "watchdog_status.json"
    if not status_path.exists():
        return {"status": "no_data", "detail": "Watchdog não está em execução ou ainda não gravou status."}
    try:
        data = json.loads(status_path.read_text(encoding="utf-8"))
        return {"status": "ok", "watchdog": data}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@app.post("/upload-ref")
async def upload_ref(file: UploadFile = File(...)):
    """Recebe imagem ou vídeo de referência, salva em temp_refs/ e retorna o path.
    Limite: 25 MB para imagens, 500 MB para vídeos de referência.
    """
    _t_upload_start = time.time()
    TEMP_DIR.mkdir(exist_ok=True)
    suffix = Path(file.filename).suffix.lower() or ".jpg"
    allowed = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".mp4", ".webm", ".mov")
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail=f"Formato não suportado: {suffix}")
    # SECURITY: limitar tamanho antes de escrever no disco
    max_bytes = _MAX_REF_VIDEO_BYTES if suffix in _UPLOAD_VIDEO_SUFFIXES else _MAX_REF_IMAGE_BYTES
    content = await _read_limited(file, max_bytes)
    dest = TEMP_DIR / f"ref_{uuid.uuid4().hex[:10]}{suffix}"
    with open(dest, "wb") as f:
        f.write(content)
    media_type = "video" if suffix in _UPLOAD_VIDEO_SUFFIXES else "image"
    _t_upload_done = time.time()
    _upload_ms = (_t_upload_done - _t_upload_start) * 1000
    print(
        f"[ACS API] Ref {media_type} salvo: {dest} ({len(content):,} bytes)"
        f" | [IMG-PERF] T7_upload_ref: {_upload_ms:.1f}ms"
        f"  size={len(content):,}B  type={suffix}"
    )
    return {"path": str(dest), "filename": file.filename, "type": media_type}


@app.post("/upload-audio")
@app.post("/upload/audio")   # alias — frontend usa /upload/audio
async def upload_audio(file: UploadFile = File(...)):
    """Recebe arquivo de áudio, salva em temp_refs/ e retorna o path.
    Limite: 100 MB.
    """
    TEMP_DIR.mkdir(exist_ok=True)
    suffix = Path(file.filename).suffix.lower() or ".mp3"
    allowed = (".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a", ".opus", ".wma")
    if suffix not in allowed:
        raise HTTPException(status_code=400, detail=f"Formato de áudio não suportado: {suffix}")
    # SECURITY: limitar tamanho antes de escrever no disco
    content = await _read_limited(file, _MAX_AUDIO_BYTES)
    dest = TEMP_DIR / f"audio_{uuid.uuid4().hex[:10]}{suffix}"
    with open(dest, "wb") as f:
        f.write(content)
    print(f"[ACS API] Áudio salvo: {dest} ({len(content):,} bytes)")
    return {"path": str(dest), "filename": file.filename}


@app.get("/models")
def list_models(type: str = "all"):
    """
    Lista os modelos disponíveis com seus metadados.
    ?type=image  → só modelos de imagem
    ?type=video  → só modelos de vídeo
    ?type=all    → todos (padrão)
    """
    result = []
    for name, v in MODELS.items():
        # [11.77] Não expor modelos desabilitados na UI
        if v.get("disabled", False):
            continue
        if type != "all" and v["type"].lower() != type.lower():
            continue
        entry = {
            "id":                 name,
            "family":             v["family"],
            "model_id":           v["model_id"],
            "type":               v["type"],
            "desc":               v["desc"],
            "image_mode":         v["image_mode"],
            "default_steps":      v.get("default_steps", 20),
            "tested":             v.get("tested", False),
            "installed":          v.get("installed", True),
            "download_on_demand": v.get("download_on_demand", False),  # [ETAPA-2]
            "performance":        v.get("performance", ""),  # "fast"|"balanced"|"pro"|""
        }
        if "download_gb" in v:
            entry["download_gb"] = v["download_gb"]
        result.append(entry)
    return {"models": result}


# LORAS_DIR e PROFILES_DIR definidos no bloco CONFIG acima (BASE_DIR-relative)

# ── FIX BUILD 34: LoRA URL cache — catálogo de download on-demand ──────────
# loras_url_cache.json é gerado pelo Wan2GP e contém URLs HuggingFace para cada LoRA.
# Permite mostrar catálogo visual mesmo quando arquivos não estão baixados localmente.
_LORAS_URL_CACHE_PATH = WAN2GP_DIR / "loras_url_cache.json"
_LORAS_URL_CACHE: dict[str, str] = {}
try:
    if _LORAS_URL_CACHE_PATH.exists():
        _LORAS_URL_CACHE = json.loads(_LORAS_URL_CACHE_PATH.read_text(encoding="utf-8"))
        print(f"[ACS API] loras_url_cache: {len(_LORAS_URL_CACHE)} entries loaded")
    else:
        print(f"[ACS API] loras_url_cache: not found at {_LORAS_URL_CACHE_PATH}")
except Exception as _e:
    print(f"[ACS API] loras_url_cache load error: {_e}")

# [SCAIL2-FUSIONX] garante a URL da lora FusionX no cache p/ AUTO-DOWNLOAD no cliente
# (LORA-DOD ~4585). Pasta wan_i2v (LORA_DIR_MAP scail2_14B). Ref: defaults/i2v_fusionix.json.
_FUSIONX_LORA_URL = "https://huggingface.co/DeepBeepMeep/Wan2.1/resolve/main/loras_accelerators/Wan2.1_I2V_14B_FusionX_LoRA.safetensors"
_LORAS_URL_CACHE.setdefault("loras\\wan_i2v\\Wan2.1_I2V_14B_FusionX_LoRA.safetensors", _FUSIONX_LORA_URL)
_LORAS_URL_CACHE.setdefault("loras/wan_i2v/Wan2.1_I2V_14B_FusionX_LoRA.safetensors", _FUSIONX_LORA_URL)

_LIGHTX2_LORA_URL = "https://huggingface.co/DeepBeepMeep/Wan2.1/resolve/main/loras_accelerators/Wan21_I2V_14B_lightx2v_cfg_step_distill_lora_rank64.safetensors"
_LORAS_URL_CACHE.setdefault("loras\\wan_i2v\\Wan21_I2V_14B_lightx2v_cfg_step_distill_lora_rank64.safetensors", _LIGHTX2_LORA_URL)
_LORAS_URL_CACHE.setdefault("loras/wan_i2v/Wan21_I2V_14B_lightx2v_cfg_step_distill_lora_rank64.safetensors", _LIGHTX2_LORA_URL)

_EDITANY_LORA_URL = "https://huggingface.co/DeepBeepMeep/LTX-2/resolve/main/edit_anything_reference_v0.1_r128_ref_adaln_proj-role_embedding-ref_attn-ref_visual_proj.standard.safetensors"
_LORAS_URL_CACHE.setdefault("loras\\ltx2\\edit_anything_reference_v0.1_r128_ref_adaln_proj-role_embedding-ref_attn-ref_visual_proj.standard.safetensors", _EDITANY_LORA_URL)
_LORAS_URL_CACHE.setdefault("loras/ltx2/edit_anything_reference_v0.1_r128_ref_adaln_proj-role_embedding-ref_attn-ref_visual_proj.standard.safetensors", _EDITANY_LORA_URL)

_MSR_LORA_URL = "https://huggingface.co/DeepBeepMeep/LTX-2/resolve/main/loras/LTX-2.3-Licon-MSR-V1.safetensors"
_LORAS_URL_CACHE.setdefault("loras\\ltx2\\LTX-2.3-Licon-MSR-V1.safetensors", _MSR_LORA_URL)
_LORAS_URL_CACHE.setdefault("loras/ltx2/LTX-2.3-Licon-MSR-V1.safetensors", _MSR_LORA_URL)

_HDR_SCENE_LORA_URL = "https://huggingface.co/DeepBeepMeep/LTX-2/resolve/main/ltx-2.3-22b-ic-lora-hdr-scene-emb.safetensors"
_LORAS_URL_CACHE.setdefault("loras\\ltx2\\ltx-2.3-22b-ic-lora-hdr-scene-emb.safetensors", _HDR_SCENE_LORA_URL)
_LORAS_URL_CACHE.setdefault("loras/ltx2/ltx-2.3-22b-ic-lora-hdr-scene-emb.safetensors", _HDR_SCENE_LORA_URL)

# ── Nomes comerciais dos LoRAs ──────────────────────────────────────────────
# Chave: stem do ficheiro (sem extensão)
# Valor: {"label": "Nome Comercial", "desc": "descrição curta"}
# ───────────────────────────────────────────────────────────────────────────
LORA_DISPLAY_NAMES: dict[str, dict] = {
    # ── [12.25] LTX2 — componentes auto-aplicados (nome comercial em vez do técnico) ──
    "edit_anything_reference_v0.1_r128_ref_adaln_proj-role_embedding-ref_attn-ref_visual_proj.standard":
        {"label": "Edição com Referência (EditAnything)",
         "desc":  "Componente do modelo Cinematic EditAnything — aplicado automaticamente"},
    # [NAMING 2026-06-26] estes mostravam o nome técnico cru (ltx/lora) — nomes comerciais:
    "ltx-2.3-22b-ic-lora-hdr-scene-emb":
        {"label": "HDR Cinematic · Cena",
         "desc":  "Componente do HDR Cinematic — aplicado automaticamente"},
    "LTX-2.3-Licon-MSR-V1":
        {"label": "Multi-Personagem",
         "desc":  "Componente do modelo Multi-Personagem — referência multi-personagem por imagem"},
    # ── Flux 2 Klein — Image ─────────────────────────────────────────────────
    "Klein-consistency":
        {"label": "Consistency",
         "desc":  "Consistência de personagem e estilo entre gerações"},
    "Flux2-Klein-9B-consistency-V2":
        {"label": "Consistency V2",
         "desc":  "Consistência aprimorada — segunda geração do Klein Consistency"},
    "f2k_consist_20260225":
        {"label": "Consistency Pro",
         "desc":  "Consistência de personagem e estilo — versão atualizada, compatível com 4B e 9B"},
    "bfs_head_v1_flux-klein_9b_step3500_rank128":
        {"label": "Head Swap",
         "desc":  "Troca de rosto preservando iluminação e perspectiva da cena"},
    "flux-2-klein-9B-360-erp-outpaint-lora_V1":
        {"label": "360° Panorama",
         "desc":  "Projeção equiretangular para imagens panorâmicas e ambientes 360° imersivos"},
    # ── LTX 2.3 22B ─────────────────────────────────────────────────────────
    "Ltx2.3-Licon-VBVR-I2V-96000-R32":
        {"label": "Motion Intelligence",
         "desc":  "Melhora movimento, consistência temporal e entendimento de prompt (LTX-2). Todos os modos."},
    "id-lora-celebvhq-ltx2.3":
        {"label": "ID Portrait",
         "desc":  "Identidade facial preservada em I2V — também activa talking head via audio_prompt_type=A1OF"},
    "ltx-2.3-22b-distilled-lora-384":
        {"label": "Turbo Render",
         "desc":  "Inferência rápida em 8 steps — LoRA de distilação (v1.0)"},
    "ltx-2.3-22b-distilled-lora-384-1.1":
        {"label": "Turbo Render 1.1",
         "desc":  "Inferência rápida em 8 steps — LoRA de distilação (v1.1, recomendado)"},
    "ltx-2.3-22b-ic-lora-hdr-0.9":
        {"label": "HDR Cinematic",
         "desc":  "Vídeo HDR 16-bit com transforms LogC3 — requer Ctrl Video SDR + flag V&G"},
    "ltx-2.3-22b-ic-lora-outpaint":
        {"label": "Scene Expander",
         "desc":  "Expande o canvas além dos limites do frame original — requer ctrl_video com região de expansão"},
    "ltx-2.3-22b-ic-lora-union-control-ref0.5":
        {"label": "Director Control",
         "desc":  "Controlo estrutural via Canny edges, Depth map ou OpenPose sobre vídeo de guia"},
    "omninft-ltx2.3-22b-rl-lora-r32":
        {"label": "AV Quality Boost",
         "desc":  "Melhora qualidade de movimento e sincronismo audio-vídeo — RL fine-tuning para LTX 2.3 22B"},
    # ── Wan I2V 14B — Character Animate / Motion ─────────────────────────────
    "Wan2.1_I2V_14B_FusionX_LoRA":
        {"label": "FusionX 10",
         "desc":  "Acelera e melhora qualidade de animação — 10 steps com movimentos fluídos"},
    "Wan21_I2V_14B_lightx2v_cfg_step_distill_lora_rank64":
        {"label": "Light X2",
         "desc":  "Distilação leve para animação 2x mais rápida com qualidade preservada"},
}

# ── Capabilities por LoRA (filename com extensão → metadata) ─────────────────
# type:
#   "normal"  → usuário escolhe livremente; ACS nunca altera payload automaticamente
#   "special" → requer workflow específico; ACS pode aplicar auto_payload ou bloquear
#
# Regras de payload:
#   auto_payload_required=False → ACS não toca no payload
#   auto_payload_required=True  → ACS aplica auto_payload APENAS se o campo estiver vazio
#
# incompatible_modes → lista de modos de geração onde este LoRA não funciona
# ─────────────────────────────────────────────────────────────────────────────
LORA_CAPABILITIES: dict[str, dict] = {
    # ── LTX 2.3 — Normal LoRAs (usuário usa livremente) ─────────────────────
    "ltx-2.3-22b-distilled-lora-384.safetensors": {
        "type":                  "normal",
        "commercial_name":       "Turbo Render",
        "allowed_modes":         ["t2v", "i2v", "flf", "continue"],
        "incompatible_modes":    [],
        "auto_payload_required": False,
        "auto_payload":          {},
        "warning_message":       "",
    },
    "ltx-2.3-22b-distilled-lora-384-1.1.safetensors": {
        "type":                  "normal",
        "commercial_name":       "Turbo Render 1.1",
        "allowed_modes":         ["t2v", "i2v", "flf", "continue"],
        "incompatible_modes":    [],
        "auto_payload_required": False,
        "auto_payload":          {},
        "warning_message":       "",
    },
    "id-lora-celebvhq-ltx2.3.safetensors": {
        "type":                  "normal",
        "commercial_name":       "ID Portrait",
        "allowed_modes":         ["t2v", "i2v", "flf", "continue"],
        "incompatible_modes":    [],
        "auto_payload_required": False,
        "auto_payload":          {},
        "warning_message":       "",
    },
    # ── LTX 2.3 — Special LoRAs (IC-LoRA: exigem workflow específico) ────────
    "ltx-2.3-22b-ic-lora-hdr-0.9.safetensors": {
        "type":                  "special",
        "commercial_name":       "HDR Cinematic",
        # Requer vídeo SDR como guia → modo I2V com Ctrl Video.
        # A flag "&" em video_prompt_type ativa hdr_enabled=True no pipeline LTX2.
        # Sem "&": hdr_enabled=False → skip_audio=False → ltx2.py:1431 audio check → return None.
        # auto_payload: se ctrl_video_prompt_type estiver vazio, ACS força "V&G"
        # (V=video guide presente, &=HDR output, G=guide denoising ativo)
        # NOTA: ctrl_video_path DEVE ser fornecido pelo usuário (vídeo SDR como entrada).
        "allowed_modes":         ["i2v"],
        "incompatible_modes":    ["t2v", "flf", "continue"],
        "requires_ctrl_video":   True,
        "auto_payload_required": True,
        "auto_payload":          {"ctrl_video_prompt_type": "V&G"},
        "warning_message":       "HDR Cinematic requer vídeo SDR como Ctrl Video (modo I2V). ACS aplica ctrl_video_prompt_type='V&G' automaticamente.",
    },
    "ltx-2.3-22b-ic-lora-outpaint.safetensors": {
        "type":                  "special",
        "commercial_name":       "Scene Expander",
        "allowed_modes":         ["i2v", "flf"],
        "incompatible_modes":    ["t2v"],
        "auto_payload_required": False,
        "auto_payload":          {},
        # NOTA: Outpainting completo requer video_guide_outpainting + video_guide_outpainting_ratio
        # (parâmetros não expostos na API actual — roadmap P3).
        # Como user LoRA em I2V/FLF: carrega e gera output válido; sem expansão activa.
        "warning_message":       "Scene Expander: funcionalidade completa de outpainting requer Ctrl Video com região de expansão (P3). Em I2V/FLF carrega como LoRA de textura.",
    },
    "ltx-2.3-22b-ic-lora-union-control-ref0.5.safetensors": {
        "type":                  "special",
        "commercial_name":       "Director Control",
        "allowed_modes":         ["t2v", "i2v"],
        "incompatible_modes":    [],
        "auto_payload_required": False,
        "auto_payload":          {},
        # Para usar o sistema IC interno do Wan2GP: fornecer ctrl_video_path + ctrl_video_prompt_type
        # com flag 11.77: "EVG" (Canny), "DVG" (Depth), "PVG" (Human Motion), "OVG" (PoseAlign).
        # Ex: ctrl_video_prompt_type="EVG" → canny edges extraídas do ctrl_video automaticamente.
        # Sem ctrl_video: carrega como LoRA de qualidade genérico.
        "warning_message":       "Director Control: adicione Ctrl Video com flag de controlo (EVG=Canny, DVG=Depth, PVG=HumanMotion, OVG=PoseAlign) para activar IC-LoRA de guia estrutural.",
    },
    # [ENG-REVERSA] Wan2GP preset "VBVR LoRA - Video Reasoning": NÃO é IC-LoRA
    # (is_ic_lora_filename=False), não precisa de control-video/frame. É LoRA de MELHORIA
    # ("Enhanced Complex Prompt Understanding, Improved Motion Dynamics & Temporal Consistency").
    # Funciona em qualquer modo só ativando — corrigido de "special/i2v" para "normal/todos".
    "Ltx2.3-Licon-VBVR-I2V-96000-R32.safetensors": {
        "type":                  "normal",
        "commercial_name":       "Motion Intelligence",
        "allowed_modes":         ["t2v", "i2v", "flf", "continue"],
        "incompatible_modes":    [],
        "auto_payload_required": False,
        "auto_payload":          {},
        "warning_message":       "",
    },
    # ── LTX 2.3 — RL Quality LoRAs (melhoria geral, user-selectable) ──────────
    "omninft-ltx2.3-22b-rl-lora-r32.safetensors": {
        "type":                  "normal",
        "commercial_name":       "AV Quality Boost",
        "allowed_modes":         ["t2v", "i2v", "flf", "continue"],
        "incompatible_modes":    [],
        "auto_payload_required": False,
        "auto_payload":          {},
        "warning_message":       "",
    },
}

# Mapa model_id → subpasta de LoRAs (quando diferente)
LORA_DIR_MAP = {
    "flux2_dev":       "flux2",     # flux2_dev compartilha loras com flux2
    "flux2_klein_9b":  "flux2_klein_9b",   # motor: flux_handler.py:300
    "flux2_klein_4b":  "flux2_klein_4b",   # motor: flux_handler.py:298
    "flux2":           "flux2",
    "wan_i2v":    "wan_i2v",   # Wan I2V tem pasta própria
    "scail2_14B": "wan_i2v",   # SCAIL-2 usa loras/wan_i2v (= get_lora_dir, wan_handler.py:150-151) p/ FusionX etc.
    "multitalk":     "wan_i2v",   # [NEXTGEN] Talking usa o mesmo acelerador wan i2v (FusionX)
    "infinitetalk":  "wan_i2v",   # [NEXTGEN] idem
    "wan_5B":     "wan",       # Wan 5B usa pasta wan
    "wan_1.3B":   "wan",
    # family → pasta (quando chamado com family ao invés de model_id)
    "ltx2":       "ltx2",
    "ltxv":       "ltxv",
    "hunyuan":    "hunyuan",
    "hunyuan_1_5":"hunyuan_1_5",
}

@app.get("/presets")
def list_presets():
    """
    Lista presets disponíveis:
    1. Profiles do Wan2GP (profiles/*/*.json) — presets salvos no Wan2GP
    2. Auto-presets dos LoRAs instalados por modelo
    """
    presets = []

    # ── 1. Wan2GP profiles ─────────────────────────────────────
    if PROFILES_DIR.exists():
        for json_file in sorted(PROFILES_DIR.rglob("*.json")):
            folder = json_file.parent.name  # ex: "flux", "wan_2_2"
            try:
                data = json.loads(json_file.read_text(encoding="utf-8", errors="replace"))
                loras_raw = data.get("activated_loras", [])
                # activated_loras pode ser lista de URLs ou stems
                lora_names = []
                for l in loras_raw:
                    # Pega o stem do filename da URL ou string direta
                    stem = Path(l.split("/")[-1]).stem if "/" in l else Path(l).stem
                    lora_names.append(stem)
                presets.append({
                    "name":             json_file.stem,
                    "source":           "wan2gp",
                    "model_folder":     folder,
                    "steps":            data.get("num_inference_steps"),
                    "guidance_scale":   data.get("guidance_scale"),
                    "loras":            lora_names,
                    "loras_multipliers": data.get("loras_multipliers", ""),
                    "resolution":       data.get("resolution"),
                    "prompt":           data.get("prompt", ""),
                })
            except Exception as e:
                print(f"[ACS API] preset parse error {json_file}: {e}")

    # ── 2. Auto-presets por LoRA instalado ─────────────────────
    # Cria um preset rápido para cada LoRA de modelos de imagem
    IMAGE_LORA_FOLDERS = {
        "flux2_klein_9b": {"family": "flux2", "performance": "balanced"},
        "flux2_klein_4b": {"family": "flux2", "performance": "fast"},
        "flux2_dev":      {"family": "flux2", "performance": "pro"},
        "z_image":        {"family": "z_image", "performance": "fast"},
        "flux2":          {"family": "flux2", "performance": "balanced"},
        "flux":           {"family": "flux2", "performance": "balanced"},
    }
    for folder_name, meta in IMAGE_LORA_FOLDERS.items():
        lora_dir = LORAS_DIR / folder_name
        if not lora_dir.exists():
            continue
        for sf in sorted(lora_dir.glob("*.safetensors")):
            presets.append({
                "name":             sf.stem,
                "source":           "lora",
                "model_folder":     folder_name,
                "family":           meta["family"],
                "performance":      meta["performance"],
                "steps":            None,
                "loras":            [sf.stem],
                "loras_multipliers": "1.0",
                "resolution":       None,
                "prompt":           "",
            })

    return {"presets": presets}


@app.get("/loras")
def list_loras(model_id: str = "flux2_klein_9b"):
    """Lista LoRAs disponíveis para um model_id específico.

    Resolução: nome UI → model_id interno → family → pasta de LoRAs.
    O frontend envia o value do <option> que é o nome UI (ex: "Cinematic Pro 1.1").
    Tentativa 1: LORA_DIR_MAP[model_id]  (ex: "flux2_dev" → "flux2")
    Tentativa 2: LORA_DIR_MAP[family]    (ex: "ltx2" → "ltx2")
    Fallback:    model_id como pasta      (ex: "flux2_klein_9b" → pasta própria)

    FIX BUILD 34: merge filesystem + loras_url_cache.json para mostrar catálogo
    mesmo quando arquivos não estão baixados localmente. Campo "downloaded" indica
    se o arquivo existe no disco. download_url permite download on-demand.
    """
    model_info  = MODELS.get(model_id, {})
    family      = model_info.get("family", "")
    folder_name = (
        LORA_DIR_MAP.get(model_id)      # nome UI direto no map (raro)
        or LORA_DIR_MAP.get(model_info.get("base_type", ""))   # [NEXTGEN] base_type (scail2_14B→wan_i2v)
        or LORA_DIR_MAP.get(model_info.get("model_id", ""))    # [NEXTGEN] model_id do motor
        or LORA_DIR_MAP.get(family)     # family no map (caso ltx2, hunyuan…)
        or model_id                     # fallback: pasta com mesmo nome do model_id
    )
    lora_dir = LORAS_DIR / folder_name
    loras_list = []

    # ── 1. Arquivos presentes no filesystem ────────────────────────────────────
    found_filenames: set[str] = set()
    if lora_dir.exists():
        for f in sorted(lora_dir.glob("*.safetensors")):
            found_filenames.add(f.name)
            meta  = LORA_DISPLAY_NAMES.get(f.stem, {})
            cap   = LORA_CAPABILITIES.get(f.name, {})
            # URL do cache (pode existir mesmo para arquivos presentes)
            cache_key    = f"loras\\{folder_name}\\{f.name}"
            download_url = _LORAS_URL_CACHE.get(cache_key, "")
            loras_list.append({
                "name":                  f.stem,
                "filename":              f.name,
                "label":                 meta.get("label", f.stem),
                "desc":                  meta.get("desc", ""),
                "size_mb":               round(f.stat().st_size / 1024 / 1024, 1),
                "downloaded":            True,
                "download_url":          download_url,
                # ── Capability fields ────────────────────────────────────────
                "type":                  cap.get("type", "normal"),
                "commercial_name":       cap.get("commercial_name", meta.get("label", f.stem)),
                "allowed_modes":         cap.get("allowed_modes", []),
                "incompatible_modes":    cap.get("incompatible_modes", []),
                "auto_payload_required": cap.get("auto_payload_required", False),
                "warning_message":       cap.get("warning_message", ""),
            })

    # ── 2. Catálogo do url_cache — LoRAs disponíveis mas não baixados ──────────
    # Prefixo esperado no cache: "loras\<folder_name>\"
    cache_prefix = f"loras\\{folder_name}\\"
    for cache_key, download_url in sorted(_LORAS_URL_CACHE.items()):
        if not cache_key.startswith(cache_prefix):
            continue
        fname = Path(cache_key).name
        if fname in found_filenames:
            continue  # já incluído acima (downloaded=True)
        stem = Path(fname).stem
        meta  = LORA_DISPLAY_NAMES.get(stem, {})
        cap   = LORA_CAPABILITIES.get(fname, {})
        loras_list.append({
            "name":                  stem,
            "filename":              fname,
            "label":                 meta.get("label", cap.get("commercial_name", stem)),
            "desc":                  meta.get("desc", ""),
            "size_mb":               None,   # desconhecido — não baixado
            "downloaded":            False,
            "download_url":          download_url,
            # ── Capability fields ─────────────────────────────────────────
            "type":                  cap.get("type", "normal"),
            "commercial_name":       cap.get("commercial_name", meta.get("label", stem)),
            "allowed_modes":         cap.get("allowed_modes", []),
            "incompatible_modes":    cap.get("incompatible_modes", []),
            "auto_payload_required": cap.get("auto_payload_required", False),
            "warning_message":       cap.get("warning_message", ""),
        })

    return {
        "model_id": model_id,
        "family":   family,
        "folder":   folder_name,
        "loras":    loras_list,
    }


@app.get("/loras/capabilities")
def list_lora_capabilities():
    """Retorna o mapa completo de capabilities por LoRA.

    Usado pelo frontend para mostrar avisos, bloquear combos inválidos
    e aplicar auto-payload antes de submeter a geração.
    """
    return {"capabilities": LORA_CAPABILITIES}


@app.get("/resolutions")
def list_resolutions():
    """Lista as resoluções disponíveis."""
    return {
        "resolutions": list(RESOLUTION_MAP.keys()),
        "default": "1024x1024",
    }


# ──────────────────────────────────────────────
# SCHEMAS ESPECÍFICOS POR MODO
# Cada wrapper tem só os campos que fazem sentido para aquele modo.
# O campo "model" padrão é "Cinematic Pro 1.1" (ltx2, testado, rápido).
# ──────────────────────────────────────────────

_VIDEO_DEFAULTS = dict(
    model             = "Cinematic Pro 1.1",
    resolution        = "832x480",
    duration          = 3,
    steps             = 6,
    seed              = -1,
    negative_prompt   = "",
    guidance_scale    = 5.0,
    motion_amplitude  = 1.0,
    loras_choices     = [],
    loras_multipliers = "",
)


class T2VRequest(BaseModel):
    prompt:            str
    model:             str   = "Cinematic Pro 1.1"
    resolution:        str   = "832x480"
    duration:          int   = 3
    steps:             int   = 6
    seed:              int   = -1
    negative_prompt:   str   = ""
    guidance_scale:    float = 5.0
    motion_amplitude:  float = 1.0
    loras_choices:     list  = []
    loras_multipliers: str   = ""
    # ── Addons ──────────────────────────────────────────────────
    inject_video_prompt_type: str = ""  # Frame Inject: "KI" | "I"
    ref_image_path:           str = ""  # imagem de referência (inject) — slot 1
    ref_inject_paths: list[str] = []   # Frame Inject multi-slot (até 3 imagens)
    msr_mode:                 str = ""  # [MSR] "KI"=Fundo+Sujeitos | "I"=só Sujeitos; vazio=default do modelo
    frames_positions:         str = ""  # [FIX-INJECT] posições manuais "0 24 48" (vazio = auto-equidistante)
    ctrl_video_path:          str = ""  # Ctrl Video: path do vídeo de controlo
    ctrl_video_prompt_type:   str = ""  # "PVG"|"OVG"|"DVG"|"EVG"|"VG"|"V&G"|"KFI"|"V"=Memória de Vídeo (Story AV)
    joyai_control_memory_positions: str = ""  # Story AV Control Video Memory: "2s,8s" ou "ana=2s,leo=8s" (máx 60s)
    keep_frames_video_guide:  str = ""  # [TRIM-VÍDEO] control video: ""=todos, "1", "a:b", espaço, -1=último
    keep_frames_video_source: str = ""  # [TRIM-VÍDEO] continue video: inteiro (negativo corta do fim)
    force_control_video_trim: int = 0   # [CAP-AUDIO] 1 = cortar no fim do áudio/control ("|")
    # ── Áudio ───────────────────────────────────────────────────
    audio_prompt_type:   str   = ""   # "" | "A" | "A1OF" | "K" | "2"
    audio_path:          str   = ""   # audio_guide — conditioning LTX-2
    audio_source_path:   str   = ""   # audio_source — mux ffmpeg direto (sem AI)
    audio_scale:         float = 1.0  # Prompt Audio Strength 0–1
    audio_guidance_scale: int  = 4    # Audio CFG scale
    prompt_enhancer:          str   = "T"  # "" = off, "T" = enhance, "TI" = text+image, "T1" = Prompt Relay, "TI1" = Relay+image
    guidance_phases_override: int   = -1   # -1 = auto (_get_guidance_phases); 1|2 = força valor
    # ── Advanced Mode 11.77 ─────────────────────────────────────
    riflex_setting:           int   = 0    # 0=off, 1=on, 2=extended (vídeos longos)
    temporal_upsampling:      str   = ""   # ""|"rife2"|"rife4" — dobrar/quadruplicar FPS
    self_refiner_setting:     int   = 0    # 0=off, 1=básico, 2=extended (11.77+)
    spatial_upsampling:       str   = ""   # ""|"lanczos"|"flashvsr"|"flashvsr2pass" (LTX 11.77)
    force_fps:                str   = ""   # ""|"8"|"16"|"24" — força FPS de saída
    # ── Film Grain [FIX-BLOCKER-02] ─────────────────────────────
    film_grain_intensity:     float = 0.0  # 0.0–1.0 (slider max=1); 0=sem grain
    film_grain_saturation:    float = 0.5  # 0.0–1.0; saturação do grain


class I2VRequest(BaseModel):
    prompt:            str
    ref_image_path:    str              # start frame — obrigatório
    model:             str   = "Cinematic Pro 1.1"
    resolution:        str   = "832x480"
    duration:          int   = 3
    steps:             int   = 6
    seed:              int   = -1
    negative_prompt:   str   = ""
    guidance_scale:    float = 5.0
    motion_amplitude:  float = 1.0
    source_strength:   float = 1.0    # input_video_strength para I2V (0–1)
    mmaudio:           int   = 0      # [AUDIO-FIX 06-28] trilha: 0=auto (reusa áudio do ctrl-video se houver), 1=IA(mmaudio), 2=custom, 3=control
    loras_choices:     list  = []
    loras_multipliers: str   = ""
    # ── Addon Ctrl Video ────────────────────────────────────────
    ctrl_video_path:          str = ""  # vídeo de controlo (addon, zone-ctrl)
    ctrl_video_prompt_type:   str = ""  # "PVG"|"OVG"|"DVG"|"EVG"|"VG"|"V&G"|"KFI" (11.77 LTX2 flags)
    keep_frames_video_guide:  str = ""  # [TRIM-VÍDEO] control video: ""=todos, "1", "a:b", espaço, -1=último
    keep_frames_video_source: str = ""  # [TRIM-VÍDEO] continue video: inteiro (negativo corta do fim)
    force_control_video_trim: int = 0   # [CAP-AUDIO] 1 = cortar no fim do áudio/control ("|")
    # ── Addon Frame Inject ──────────────────────────────────────
    inject_video_prompt_type: str       = ""  # "" | "KI" | "I"
    ref_inject_paths:         list[str] = []  # frames injectados (slots 2, 3, 4…)
    frames_positions:         str       = ""  # [FIX-INJECT] posições manuais "0 24 48" (vazio = auto)
    # ── Áudio ───────────────────────────────────────────────────
    audio_prompt_type:   str   = ""   # "" | "A" | "A1OF" | "K" | "2"
    audio_path:          str   = ""   # audio_guide — conditioning LTX-2
    audio_source_path:   str   = ""   # audio_source — mux ffmpeg direto (sem AI)
    audio_scale:         float = 1.0  # Prompt Audio Strength 0–1
    audio_guidance_scale: int  = 4    # Audio CFG scale
    audio_path2:          str   = ""   # segundo áudio — segundo falante (MultiTalk)
    speakers_locations:   str   = ""   # bboxes "0:45 55:100" para dual speaker
    seedvc_voice_sample:  str   = ""   # SeedVC: target voice WAV (audio_prompt_type="V")
    seedvc_voice_sample2: str   = ""   # SeedVC: segundo falante voice WAV
    prompt_enhancer:          str   = "T"  # "" = off, "T" = enhance, "TI" = text+image, "T1" = Prompt Relay, "TI1" = Relay+image
    guidance_phases_override: int   = -1   # -1 = auto (_get_guidance_phases); 1|2 = força valor
    # ── Advanced Mode 11.77 ─────────────────────────────────────
    riflex_setting:           int   = 0    # 0=off, 1=on, 2=extended (vídeos longos)
    temporal_upsampling:      str   = ""   # ""|"rife2"|"rife4" — dobrar/quadruplicar FPS
    self_refiner_setting:     int   = 0    # 0=off, 1=básico, 2=extended (11.77+)
    spatial_upsampling:       str   = ""   # ""|"lanczos"|"flashvsr"|"flashvsr2pass" (LTX 11.77)
    force_fps:                str   = ""   # ""|"8"|"16"|"24" — força FPS de saída
    # ── Film Grain [FIX-BLOCKER-02] ─────────────────────────────
    film_grain_intensity:     float = 0.0  # 0.0–1.0 (slider max=1); 0=sem grain
    film_grain_saturation:    float = 0.5  # 0.0–1.0; saturação do grain


class FLFRequest(BaseModel):
    prompt:            str
    ref_image_path:    str              # start frame — obrigatório
    end_image_path:    str              # end frame — obrigatório
    model:             str   = "Cinematic Pro 1.1"
    resolution:        str   = "832x480"
    duration:          int   = 3
    steps:             int   = 6
    seed:              int   = -1
    negative_prompt:   str   = ""
    guidance_scale:    float = 5.0
    motion_amplitude:  float = 1.0
    loras_choices:     list  = []
    loras_multipliers: str   = ""
    # ── Áudio ───────────────────────────────────────────────────
    audio_prompt_type:   str   = ""   # "" | "A" | "A1OF" | "K" | "2"
    audio_path:          str   = ""   # audio_guide — conditioning LTX-2
    audio_source_path:   str   = ""   # audio_source — mux ffmpeg direto (sem AI)
    audio_scale:         float = 1.0  # Prompt Audio Strength 0–1
    audio_guidance_scale: int  = 4    # Audio CFG scale
    prompt_enhancer:          str   = "T"  # "" = off, "T" = enhance, "TI" = text+image, "T1" = Prompt Relay, "TI1" = Relay+image
    guidance_phases_override: int   = -1   # -1 = auto (_get_guidance_phases); 1|2 = força valor
    # ── Advanced Mode 11.77 ─────────────────────────────────────
    riflex_setting:           int   = 0    # 0=off, 1=on, 2=extended (vídeos longos)
    temporal_upsampling:      str   = ""   # ""|"rife2"|"rife4" — dobrar/quadruplicar FPS
    self_refiner_setting:     int   = 0    # 0=off, 1=básico, 2=extended (11.77+)
    spatial_upsampling:       str   = ""   # ""|"lanczos"|"flashvsr"|"flashvsr2pass" (LTX 11.77)
    force_fps:                str   = ""   # ""|"8"|"16"|"24" — força FPS de saída
    # ── Film Grain [FIX-BLOCKER-02] ─────────────────────────────
    film_grain_intensity:     float = 0.0  # 0.0–1.0 (slider max=1); 0=sem grain
    film_grain_saturation:    float = 0.5  # 0.0–1.0; saturação do grain


class ContinueRequest(BaseModel):
    prompt:            str
    ctrl_video_path:   str              # vídeo fonte — obrigatório
    model:             str   = "Cinematic Pro 1.1"
    resolution:        str   = "832x480"
    duration:          int   = 3
    steps:             int   = 6
    seed:              int   = -1
    negative_prompt:   str   = ""
    source_strength:   float = 0.85    # input_video_strength: quão próximo do original
    end_image_path:    str   = ""      # end frame opcional
    guidance_scale:    float = 5.0
    motion_amplitude:  float = 1.0
    loras_choices:     list  = []
    loras_multipliers: str   = ""
    # ── Áudio ───────────────────────────────────────────────────
    audio_prompt_type:   str   = ""   # "" | "A" | "A1OF" | "K" | "2"
    audio_path:          str   = ""   # audio_guide — conditioning LTX-2
    audio_source_path:   str   = ""   # audio_source — mux ffmpeg direto (sem AI)
    audio_scale:         float = 1.0  # Prompt Audio Strength 0–1
    audio_guidance_scale:     int   = 4    # Audio CFG scale
    prompt_enhancer:          str   = "T"  # "" = off, "T" = enhance, "TI" = text+image, "T1" = Prompt Relay, "TI1" = Relay+image
    guidance_phases_override: int   = -1   # -1 = auto (_get_guidance_phases); 1|2 = força valor
    # ── Advanced Mode 11.77 ─────────────────────────────────────
    riflex_setting:           int   = 0    # 0=off, 1=on, 2=extended (vídeos longos)
    temporal_upsampling:      str   = ""   # ""|"rife2"|"rife4" — dobrar/quadruplicar FPS
    self_refiner_setting:     int   = 0    # 0=off, 1=básico, 2=extended (11.77+)
    spatial_upsampling:       str   = ""   # ""|"lanczos"|"flashvsr"|"flashvsr2pass" (LTX 11.77)
    force_fps:                str   = ""   # ""|"8"|"16"|"24" — força FPS de saída
    # ── Film Grain [FIX-BLOCKER-02] ─────────────────────────────
    film_grain_intensity:     float = 0.0  # 0.0–1.0 (slider max=1); 0=sem grain
    film_grain_saturation:    float = 0.5  # 0.0–1.0; saturação do grain


def _new_job(prompt: str, model: str, mode: str) -> str:
    """Cria entrada no dict jobs e retorna job_id."""
    job_id = str(uuid.uuid4())[:8]
    jobs[job_id] = {
        "id":         job_id,
        "status":     "queued",
        "progress":   0,
        "step":       "",
        "prompt":     prompt,
        "model":      model,
        "mode":       mode,
        "created_at": time.time(),
        "output":     None,
        "error":      None,
    }
    return job_id


# ──────────────────────────────────────────────
# WRAPPERS POR MODO — /generate/{mode}
# Schemas limpos, sem campos irrelevantes.
# Internamente convertem para GenerateRequest e chamam _generate_background.
# ──────────────────────────────────────────────

@app.post("/generate/t2v")
def generate_t2v(req: T2VRequest, background_tasks: BackgroundTasks):
    """Text to Video — sem condicionamento de imagem."""
    _require_license()
    _require_feature(kind="video", model=req.model, resolution=req.resolution,
                     audio_prompt_type=getattr(req, "audio_prompt_type", ""))
    _vl_debug = _seconds_to_video_length(req.duration, req.model)
    print(f"[ACS DUR-DEBUG] /generate/t2v recebido: duration={req.duration}s model='{req.model}' -> video_length={_vl_debug}f")
    job_id = _new_job(req.prompt, req.model, "t2v")
    full   = GenerateRequest(
        generation_mode          = "t2v",
        prompt                   = req.prompt,
        model                    = req.model,
        resolution               = req.resolution,
        duration                 = req.duration,
        steps                    = req.steps,
        seed                     = req.seed,
        negative_prompt          = req.negative_prompt,
        guidance_scale           = req.guidance_scale,
        motion_amplitude         = req.motion_amplitude,
        loras_choices            = req.loras_choices,
        loras_multipliers        = req.loras_multipliers,
        inject_video_prompt_type = req.inject_video_prompt_type,
        ref_image_path           = req.ref_image_path,
        ref_inject_paths         = req.ref_inject_paths,
        msr_mode                 = req.msr_mode,
        frames_positions         = req.frames_positions,
        ctrl_video_path          = req.ctrl_video_path,
        ctrl_video_prompt_type   = req.ctrl_video_prompt_type,
        joyai_control_memory_positions = req.joyai_control_memory_positions,
        keep_frames_video_guide  = req.keep_frames_video_guide,
        keep_frames_video_source = req.keep_frames_video_source,
        force_control_video_trim = req.force_control_video_trim,
        audio_prompt_type        = req.audio_prompt_type,
        audio_path               = req.audio_path,
        audio_source_path        = req.audio_source_path,
        audio_scale              = req.audio_scale,
        audio_guidance_scale     = req.audio_guidance_scale,
        prompt_enhancer          = req.prompt_enhancer,
        # ── Advanced Mode 11.77 ─────────────────────────────────────
        riflex_setting           = req.riflex_setting,
        temporal_upsampling      = req.temporal_upsampling,
        self_refiner_setting      = req.self_refiner_setting,
        spatial_upsampling        = req.spatial_upsampling,
        guidance_phases_override  = req.guidance_phases_override,
        force_fps                 = req.force_fps,
        # ── Film Grain [FIX-BLOCKER-02] ─────────────────────────────
        film_grain_intensity      = req.film_grain_intensity,
        film_grain_saturation     = req.film_grain_saturation,
    )
    background_tasks.add_task(_generate_background, job_id, full)
    return {"job_id": job_id, "status": "queued", "mode": "t2v"}


@app.post("/generate/i2v")
def generate_i2v(req: I2VRequest, background_tasks: BackgroundTasks):
    """Image to Video — start frame obrigatório (image_prompt_type='S').
    Suporta addons: Frame Inject (image_refs) e Ctrl Video (video_guide).
    """
    _require_license()
    _require_feature(kind="video", model=req.model, resolution=req.resolution,
                     audio_prompt_type=getattr(req, "audio_prompt_type", ""))
    job_id = _new_job(req.prompt, req.model, "i2v")
    # [AUDIO-FIX 06-28] O motor (Scail2 pose / SAM3) QUEBRA ("FieldsBuilder finalized") se o vídeo
    # de controle tem trilha de áudio; e o cano-novo (WanGPSession) pula o post-proc de áudio do motor.
    # Então: (1) tira o áudio do control p/ o motor (temp video-only = evita o crash) e
    # (2) guarda o original em _mux_audio p/ muxar no output depois (ver finalização do job).
    _ctrl_in   = req.ctrl_video_path or ""
    _mux_audio = ""
    if _ctrl_in and os.path.exists(_ctrl_in):
        try:
            import subprocess as _sp0
            _ffp0 = str(WAN2GP_DIR / "ffmpeg_bins" / "ffprobe.exe")
            if _sp0.run([_ffp0,"-v","error","-select_streams","a","-show_entries","stream=index","-of","csv=p=0",_ctrl_in], capture_output=True, text=True).stdout.strip():
                _ffm0 = str(WAN2GP_DIR / "ffmpeg_bins" / "ffmpeg.exe")
                _stripped0 = _ctrl_in + ".noaudio.mp4"
                if _sp0.run([_ffm0,"-y","-i",_ctrl_in,"-an","-c:v","copy",_stripped0], capture_output=True, text=True).returncode == 0 and os.path.exists(_stripped0):
                    _mux_audio = _ctrl_in       # original (com áudio) p/ o mux
                    _ctrl_in   = _stripped0     # video-only p/ o motor (evita o crash)
                    print("[AUDIO-FIX] control video tinha audio -> stripped p/ o motor; audio guardado p/ mux")
        except Exception as _e0:
            print(f"[AUDIO-FIX] strip control audio falhou: {_e0}")
    full   = GenerateRequest(
        generation_mode          = "i2v",
        prompt                   = req.prompt,
        model                    = req.model,
        resolution               = req.resolution,
        duration                 = req.duration,
        steps                    = req.steps,
        seed                     = req.seed,
        negative_prompt          = req.negative_prompt,
        ref_image_path           = req.ref_image_path,
        guidance_scale           = req.guidance_scale,
        motion_amplitude         = req.motion_amplitude,
        source_strength          = req.source_strength,
        loras_choices            = req.loras_choices,
        loras_multipliers        = req.loras_multipliers,
        ctrl_video_path          = _ctrl_in,
        ctrl_video_prompt_type   = req.ctrl_video_prompt_type,
        keep_frames_video_guide  = req.keep_frames_video_guide,
        keep_frames_video_source = req.keep_frames_video_source,
        force_control_video_trim = req.force_control_video_trim,
        inject_video_prompt_type = req.inject_video_prompt_type,
        ref_inject_paths         = req.ref_inject_paths,
        frames_positions         = req.frames_positions,
        audio_prompt_type        = req.audio_prompt_type,
        audio_path               = req.audio_path,
        audio_source_path        = req.audio_source_path,
        audio_scale              = req.audio_scale,
        audio_guidance_scale     = req.audio_guidance_scale,
        audio_path2              = req.audio_path2,
        speakers_locations       = req.speakers_locations,
        seedvc_voice_sample      = req.seedvc_voice_sample,
        seedvc_voice_sample2     = req.seedvc_voice_sample2,
        prompt_enhancer          = req.prompt_enhancer,
        # ── Advanced Mode 11.77 ─────────────────────────────────────
        riflex_setting           = req.riflex_setting,
        temporal_upsampling      = req.temporal_upsampling,
        self_refiner_setting      = req.self_refiner_setting,
        spatial_upsampling        = req.spatial_upsampling,
        guidance_phases_override  = req.guidance_phases_override,
        force_fps                 = req.force_fps,
        # ── Film Grain [FIX-BLOCKER-02] ─────────────────────────────
        film_grain_intensity      = req.film_grain_intensity,
        film_grain_saturation     = req.film_grain_saturation,
        mux_audio_path            = _mux_audio,
    )
    background_tasks.add_task(_generate_background, job_id, full)
    return {"job_id": job_id, "status": "queued", "mode": "i2v"}


@app.post("/generate/flf")
def generate_flf(req: FLFRequest, background_tasks: BackgroundTasks):
    """First-Last Frame — start + end frame obrigatórios (image_prompt_type='SE')."""
    _require_license()
    _require_feature(kind="video", model=req.model, resolution=req.resolution,
                     audio_prompt_type=getattr(req, "audio_prompt_type", ""))
    job_id = _new_job(req.prompt, req.model, "flf")
    full   = GenerateRequest(
        generation_mode      = "flf",
        prompt               = req.prompt,
        model                = req.model,
        resolution           = req.resolution,
        duration             = req.duration,
        steps                = req.steps,
        seed                 = req.seed,
        negative_prompt      = req.negative_prompt,
        ref_image_path       = req.ref_image_path,
        end_image_path       = req.end_image_path,
        guidance_scale       = req.guidance_scale,
        motion_amplitude     = req.motion_amplitude,
        loras_choices        = req.loras_choices,
        loras_multipliers    = req.loras_multipliers,
        audio_prompt_type    = req.audio_prompt_type,
        audio_path           = req.audio_path,
        audio_source_path    = req.audio_source_path,
        audio_scale          = req.audio_scale,
        audio_guidance_scale = req.audio_guidance_scale,
        prompt_enhancer      = req.prompt_enhancer,
        # ── Advanced Mode 11.77 ─────────────────────────────────────
        riflex_setting       = req.riflex_setting,
        temporal_upsampling  = req.temporal_upsampling,
        self_refiner_setting      = req.self_refiner_setting,
        spatial_upsampling        = req.spatial_upsampling,
        guidance_phases_override  = req.guidance_phases_override,
        force_fps                 = req.force_fps,
        # ── Film Grain [FIX-BLOCKER-02] ─────────────────────────────
        film_grain_intensity      = req.film_grain_intensity,
        film_grain_saturation     = req.film_grain_saturation,
    )
    background_tasks.add_task(_generate_background, job_id, full)
    return {"job_id": job_id, "status": "queued", "mode": "flf"}


@app.post("/generate/continue")
def generate_continue(req: ContinueRequest, background_tasks: BackgroundTasks):
    """Continue Video — video fonte obrigatório (image_prompt_type='V')."""
    _require_license()
    _require_feature(kind="video", model=req.model, resolution=req.resolution,
                     audio_prompt_type=getattr(req, "audio_prompt_type", ""))
    job_id = _new_job(req.prompt, req.model, "continue")
    full   = GenerateRequest(
        generation_mode      = "continue",
        prompt               = req.prompt,
        model                = req.model,
        resolution           = req.resolution,
        duration             = req.duration,
        steps                = req.steps,
        seed                 = req.seed,
        negative_prompt      = req.negative_prompt,
        ctrl_video_path      = req.ctrl_video_path,
        end_image_path       = req.end_image_path,
        source_strength      = req.source_strength,
        guidance_scale       = req.guidance_scale,
        motion_amplitude     = req.motion_amplitude,
        loras_choices        = req.loras_choices,
        loras_multipliers    = req.loras_multipliers,
        audio_prompt_type    = req.audio_prompt_type,
        audio_path           = req.audio_path,
        audio_source_path    = req.audio_source_path,
        audio_scale          = req.audio_scale,
        audio_guidance_scale = req.audio_guidance_scale,
        prompt_enhancer      = req.prompt_enhancer,
        # ── Advanced Mode 11.77 ─────────────────────────────────────
        riflex_setting       = req.riflex_setting,
        temporal_upsampling  = req.temporal_upsampling,
        self_refiner_setting      = req.self_refiner_setting,
        spatial_upsampling        = req.spatial_upsampling,
        guidance_phases_override  = req.guidance_phases_override,
        force_fps                 = req.force_fps,
        # ── Film Grain [FIX-BLOCKER-02] ─────────────────────────────
        film_grain_intensity      = req.film_grain_intensity,
        film_grain_saturation     = req.film_grain_saturation,
    )
    background_tasks.add_task(_generate_background, job_id, full)
    return {"job_id": job_id, "status": "queued", "mode": "continue"}


@app.post("/generate")
def generate(req: GenerateRequest, background_tasks: BackgroundTasks):
    """
    Endpoint genérico — suporta todos os modos via generation_mode.
    Prefer os endpoints específicos (/generate/t2v, /generate/i2v, etc.)
    para schemas mais limpos.
    """
    _require_license()
    # [ERR-12] passa o model: bloqueia modelo premium de vídeo usado via modo t2i (imagem)
    _require_feature(kind="image", model=req.model, resolution=req.resolution)
    _t1_recv = time.time()
    job_id = _new_job(req.prompt, req.model, req.generation_mode)
    # Persiste T1 para _generate_background medir lock-wait overhead
    jobs[job_id]["t1_request"] = _t1_recv
    if req.generation_mode == "t2i":
        print(
            f"[IMG-PERF] T1_request_received  job={job_id}"
            f"  model={req.model}  res={req.resolution}"
            f"  seed={req.seed}  steps={req.steps}"
            f"  enhancer={repr(req.prompt_enhancer)}"
            f"  inject={repr(req.inject_video_prompt_type or '')}"
            f"  ctrl={repr(req.ctrl_video_prompt_type or '')}"
            f"  ref={'yes' if req.ref_inject_paths else 'no'}"
            f"  ctrl_img={'yes' if req.ctrl_image_path else 'no'}"
            f"  loras={req.loras_choices}"
        )
    background_tasks.add_task(_generate_background, job_id, req)
    return {"job_id": job_id, "status": "queued"}


@app.post("/generate/audio")
def generate_audio(req: AudioGenerateRequest, background_tasks: BackgroundTasks):
    """
    Geração de áudio (TTS / Music) via modelos TTS do Wan2GP.
    Suporta: ACE-Step v1/v1.5/v1.5 XL, Chatterbox, IndexTTS2.
    gallery_tab=1.0 → gen["last_was_audio"]=True → saída em audio_save_path.
    """
    _require_license()
    _require_feature(kind="audio")
    model_info = MODELS.get(req.model)
    if not model_info:
        raise HTTPException(status_code=400, detail=f"Modelo desconhecido: {req.model}")
    if model_info.get("image_mode") != 2:
        raise HTTPException(status_code=400, detail=f"Modelo '{req.model}' não é de áudio. Use /generate/ para vídeo/imagem.")
    job_id = _new_job(req.prompt, req.model, "audio")
    background_tasks.add_task(_generate_audio_background, job_id, req)
    return {"job_id": job_id, "status": "queued", "mode": "audio"}


def _is_download_step(step: str) -> bool:
    """True se o step indica download ativo — espelha _isDownloadStep() do video.js."""
    return isinstance(step, str) and step.lower().startswith("baixando")


def _read_dl_progress() -> dict | None:
    """
    Lê acs_dl_progress.json escrito pelo hook tqdm do Wan2GP.

    [B39-BLOCK-002] Julga o download pelos BYTES (downloaded_mb), não pelo relógio.
    O xet baixa em RAJADAS: o JSON fica vários segundos sem ser reescrito entre
    rajadas, mas o download segue vivo. Cortar por mtime stale (comportamento antigo)
    fazia o HUD piscar entre "finalizando" e o ETA, e fazia o watchdog de geração
    contar timeout falso. Agora mantemos o último estado bom enquanto os MB sobem;
    só desistimos após _DL_DEAD_SEC sem progresso real de bytes.

    Retorna None se:
      - arquivo ausente
      - campo active=False (hook fechou = download concluído/encerrado)
      - campos obrigatórios ausentes
      - download CONGELADO: active=true mas downloaded_mb parado por > _DL_DEAD_SEC
    FAIL-SAFE: nunca levanta exceção. Em erro transitório de leitura (ex: JSON sendo
    reescrito), segura o último estado bom se ainda dentro da janela de vida.
    """
    global _dl_hold_last_mb, _dl_hold_progress_t, _dl_hold_data
    now = time.time()
    try:
        if not _DL_PROGRESS_PATH.exists():
            _dl_hold_last_mb = -1.0
            _dl_hold_progress_t = 0.0
            _dl_hold_data = None
            return None
        # [B39-BLOCK-002b] Guarda STALE por mtime: se o arquivo não é reescrito há mais de
        # _DL_STALE_MTIME, NÃO há download ativo escrevendo nele. Rejeita um acs_dl_progress.json
        # antigo (active=true nunca fechado de uma sessão interrompida) que senão apareceria como
        # download fantasma. Janela generosa (120s) para não cortar download vivo em rajadas.
        try:
            if now - _DL_PROGRESS_PATH.stat().st_mtime > _DL_STALE_MTIME:
                _dl_hold_last_mb = -1.0
                _dl_hold_progress_t = 0.0
                _dl_hold_data = None
                return None
        except Exception:
            pass
        with open(_DL_PROGRESS_PATH, "r", encoding="utf-8") as _f:
            data = json.load(_f)
        # active=False explícito = hook fechou = download terminou/encerrou
        if not data.get("active"):
            _dl_hold_last_mb = -1.0
            _dl_hold_progress_t = 0.0
            _dl_hold_data = None
            return None
        # Sanidade: campos obrigatórios presentes
        if data.get("percent") is None or data.get("downloaded_mb") is None:
            return None
        _cur_mb = float(data.get("downloaded_mb") or 0.0)
        # B39-BLOCK-002: rastrear progresso por bytes (não por mtime/relógio)
        if _dl_hold_last_mb < 0 or _cur_mb > _dl_hold_last_mb + _DL_MIN_DELTA_MB:
            _dl_hold_last_mb = _cur_mb
            _dl_hold_progress_t = now
        # Download congelado de verdade (active=true porém sem novos bytes) → morto
        if _dl_hold_progress_t and (now - _dl_hold_progress_t) > _DL_DEAD_SEC:
            return None
        # Sanitiza filename — NUNCA expor nomes técnicos ao frontend
        _raw = str(data.get("filename") or "")
        _lo = _raw.lower()
        if any(_lo.endswith(e) for e in (".safetensors", ".ckpt", ".bin", ".pt", ".pth")):
            if "lora" in _lo:
                data["filename"] = "Estilos"
            else:
                data["filename"] = "Modelos IA"
        elif any(_lo.endswith(e) for e in (".json", ".yaml", ".yml", ".txt")):
            data["filename"] = "Dependências"
        else:
            data["filename"] = "Componentes"
        _dl_hold_data = data
        return data
    except Exception:
        # Leitura transitória falhou (ex: JSON sendo reescrito no meio).
        # Segura o último estado bom enquanto dentro da janela de vida → HUD não pisca.
        if _dl_hold_data is not None and _dl_hold_progress_t \
                and (now - _dl_hold_progress_t) <= _DL_DEAD_SEC:
            return _dl_hold_data
        return None


@app.get("/debug/last-image-payload")
def debug_last_image_payload():
    """Retorna o último payload de geração de imagem com timers completos.
    Arquivo: acs_last_image_payload.json — atualizado após cada geração de imagem.
    """
    try:
        import json as _json
        _p = Path(__file__).parent / "acs_last_image_payload.json"
        if not _p.exists():
            return {"status": "not_found", "detail": "Nenhuma geração de imagem ainda."}
        data = _json.loads(_p.read_text(encoding="utf-8"))
        return {"status": "ok", "payload": data}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@app.get("/debug/last-gradio-payload")
def debug_last_gradio_payload():
    """Retorna o último payload completo enviado ao Gradio save_inputs.
    Arquivo: acs_last_gradio_payload.json — atualizado após cada geração.
    """
    try:
        import json as _json
        _p = Path(__file__).parent / "acs_last_gradio_payload.json"
        if not _p.exists():
            return {"status": "not_found", "detail": "Nenhuma geração ainda."}
        data = _json.loads(_p.read_text(encoding="utf-8"))
        return {"status": "ok", "payload": data}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}


@app.get("/status/{job_id}")
def get_status(job_id: str):
    """Retorna o status de uma geração, incluindo progresso real de download."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    # Fix C1: excluir futures Gradio (não-serializáveis) da resposta
    _INTERNAL_KEYS = {"cm_job", "gen_job"}
    resp = {k: v for k, v in jobs[job_id].items() if k not in _INTERNAL_KEYS}

    # Adiciona campo download{} ao status.
    # O download Wan2GP acontece DENTRO de process_tasks (load_models → download_models),
    # enquanto o step ACS já avançou para "PASSO 10: verificando outputs".
    # Por isso: sempre verifica _read_dl_progress() durante status generating/running —
    # a função já filtra stale (>5s) e active=False, então é seguro chamar sempre.
    _status = jobs[job_id].get("status", "")
    if _status in ("running", "generating"):
        dl = _read_dl_progress()
        resp["download"] = dl if dl else {"active": False}
    elif _status == "downloading_lora":
        # [B38-001] LoRA DOD: expor progresso estruturado ao frontend
        resp["download"] = {
            "active":        True,
            "filename":      jobs[job_id].get("lora_dl_name", ""),
            "percent":       jobs[job_id].get("lora_dl_pct", 0),
            "downloaded_mb": jobs[job_id].get("lora_dl_done_mb", 0),
            "total_mb":      jobs[job_id].get("lora_dl_total_mb", 0),
            "speed_mbps":    jobs[job_id].get("lora_dl_speed", 0),
            "eta_sec":       jobs[job_id].get("lora_dl_eta_s", None),
        }
    else:
        resp["download"] = {"active": False}

    # [F11 SELF-LEARNING] chokepoint unico: TODO job que virou erro alimenta o aprendizado 1x
    # (assina o erro, compara com o que ja aconteceu, sabe build/gpu/solucao). O ACS APRENDE.
    if jobs[job_id].get("status") in ("error", "failed") and not jobs[job_id].get("_learned"):
        try:
            import acs_self_learning as _sl
            _sl.learn(jobs[job_id].get("error", ""), model=jobs[job_id].get("model", ""), build="Build48")
        except Exception:
            pass
        jobs[job_id]["_learned"] = True

    return resp


@app.get("/status")
def list_jobs():
    """Lista todos os jobs ativos."""
    _INTERNAL_KEYS = {"cm_job", "gen_job"}
    safe = [{k: v for k, v in j.items() if k not in _INTERNAL_KEYS} for j in jobs.values()]
    return {"jobs": safe}


@app.post("/cancel/{job_id}")
def cancel_job(job_id: str):
    """Cancela uma geração em andamento."""
    if job_id not in jobs:
        raise HTTPException(status_code=404, detail="Job não encontrado")
    jobs[job_id]["status"] = "cancelled"

    # Fix C2: cancelar futures Gradio ativos se existirem — nunca levanta exceção
    cm_job = jobs[job_id].get("cm_job")
    if cm_job is not None:
        try:
            cm_job.cancel()
            print(f"[ACS API] /cancel {job_id} | cm_job.cancel() OK")
        except Exception as e:
            print(f"[ACS API] /cancel {job_id} | cm_job.cancel() falhou: {e}")

    gen_job = jobs[job_id].get("gen_job")
    if gen_job is not None:
        try:
            gen_job.cancel()
            print(f"[ACS API] /cancel {job_id} | gen_job.cancel() OK")
        except Exception as e:
            print(f"[ACS API] /cancel {job_id} | gen_job.cancel() falhou: {e}")

    # Mantém tentativa de abort_generation via novo cliente (fallback para Wan2GP)
    try:
        c = new_client()
        c.predict(api_name="/abort_generation")
    except Exception:
        pass

    return {"job_id": job_id, "status": "cancelled"}


@app.get("/outputs")
def list_outputs(type: str = None, limit: int = 30):
    """Lista os arquivos gerados com metadados.
    Params opcionais:
      ?type=video|image|audio  — filtra por tipo (sem param = todos os tipos)
      ?limit=N                 — cap por tipo; default=30; sem params = comportamento original
    Exemplos:
      /outputs                        → até 30 vídeos + 30 imagens + 30 áudios (comportamento original)
      /outputs?type=video&limit=200   → até 200 vídeos, sem imagens/áudios
    """
    if not OUTPUTS_DIR.exists():
        return {"outputs": []}

    video_pats = ["*.mp4", "*.webp"]
    image_pats = ["*.jpg", "*.jpeg", "*.png"]
    audio_pats = ["*.wav", "*.mp3", "*.flac", "*.aac", "*.m4a", "*.ogg"]

    def _collect(pats, cap):
        files = []
        for pat in pats:
            files.extend(OUTPUTS_DIR.glob(pat))
        return sorted(files, key=lambda f: f.stat().st_mtime, reverse=True)[:cap]

    # Quando ?type= é fornecido, aplica limit ao tipo pedido e ignora os demais
    if type == "video":
        all_files = _collect(video_pats, limit)
    elif type == "image":
        all_files = _collect(image_pats, limit)
    elif type == "audio":
        all_files = _collect(audio_pats, limit)
    else:
        # Sem ?type: comportamento original — 30 por tipo (limit ignorado para segurança)
        all_files = _collect(video_pats, 30) + _collect(image_pats, 30) + _collect(audio_pats, 30)
        all_files = sorted(all_files, key=lambda f: f.stat().st_mtime, reverse=True)

    results = []
    for f in all_files:
        stem = f.stem
        parts = stem.split("_", 2)
        prompt_clean = parts[2].replace("_", " ") if len(parts) >= 3 else stem
        prompt_clean = prompt_clean[:60] + ("…" if len(prompt_clean) > 60 else "")

        date_match = re.match(r"(\d{4}-\d{2}-\d{2})-(\d{2})h(\d{2})m", stem)
        date_str = (
            f"{date_match.group(1)} {date_match.group(2)}:{date_match.group(3)}"
            if date_match else ""
        )

        ext = f.suffix.lower()
        if ext in (".mp4", ".webp"):
            media_type = "video"
        elif ext in (".wav", ".mp3", ".flac", ".aac", ".m4a", ".ogg"):
            media_type = "audio"
        else:
            media_type = "image"

        results.append({
            "name":       f.name,
            "title":      prompt_clean,
            "date":       date_str,
            "url":        f"/file/{f.name}",
            "type":       media_type,
            "size_mb":    round(f.stat().st_size / 1024 / 1024, 2),
            "created":    f.stat().st_mtime,
        })
    return {"outputs": results}


# ══════════════════════════════════════════════
# DELETE /outputs/{filename} — remove arquivo gerado com segurança
# Whitelist de extensões + canonical path check (bloqueia ../, fora de OUTPUTS_DIR)
# ══════════════════════════════════════════════
_ALLOWED_DELETE_EXTS = {
    ".mp4", ".webp", ".jpg", ".jpeg", ".png",
    ".wav", ".mp3", ".flac", ".aac", ".m4a", ".ogg",
}

@app.delete("/outputs/{filename}")
def delete_output(filename: str):
    """Deleta um arquivo de output. Valida que o path está dentro de OUTPUTS_DIR
    e que a extensão é uma das geradas pelo Wan2GP. Bloqueia path traversal."""
    # [FIX-FILE] Bloqueia separadores de caminho mas permite ".." no nome do arquivo
    if not filename or "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido")

    f = OUTPUTS_DIR / filename
    # 2) Canonical path check — garante que está dentro de OUTPUTS_DIR
    try:
        f_resolved        = f.resolve(strict=False)
        outputs_resolved  = OUTPUTS_DIR.resolve(strict=False)
        if f_resolved.parent != outputs_resolved:
            raise HTTPException(status_code=403, detail="Path fora do diretório autorizado")
    except (OSError, ValueError):
        raise HTTPException(status_code=400, detail="Path inválido")

    # 3) Arquivo existe e é arquivo real
    if not f.exists():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    if not f.is_file():
        raise HTTPException(status_code=400, detail="Não é um arquivo")

    # 4) Extensão na whitelist
    if f.suffix.lower() not in _ALLOWED_DELETE_EXTS:
        raise HTTPException(status_code=403, detail="Extensão não permitida")

    # 5) Deletar
    try:
        f.unlink()
        print(f"[ACS API] /outputs/delete: {filename} removido")
        return {"status": "ok", "deleted": filename}
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"Erro ao deletar: {e}")


@app.get("/file/{filename}")
def get_file(filename: str, download: bool = False):
    """Serve um arquivo gerado (imagem, vídeo ou áudio).
    SECURITY: bloqueia path traversal — só serve de OUTPUTS_DIR ou TEMP_DIR.
    [B38-007v2] Parâmetro ?download=1: adiciona Content-Disposition: attachment
    para forçar download nativo no pywebview/WebView2.
    Sem ?download=1: comportamento inalterado (inline/stream).
    """
    # [FIX-FILE] Bloqueia separadores mas permite ".." no nome (resolve() é a defesa real)
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido")
    f_resolved = (OUTPUTS_DIR / filename).resolve()
    _base_out  = OUTPUTS_DIR.resolve()
    _base_tmp  = TEMP_DIR.resolve()
    if not (str(f_resolved).startswith(str(_base_out)) or
            str(f_resolved).startswith(str(_base_tmp))):
        raise HTTPException(status_code=403, detail="Acesso negado")
    if not f_resolved.exists():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    ext = f_resolved.suffix.lower()
    media_types = {
        ".mp4": "video/mp4", ".webp": "image/webp",
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac",
        ".aac": "audio/aac", ".m4a": "audio/mp4", ".ogg": "audio/ogg",
    }
    mt = media_types.get(ext, "application/octet-stream")
    headers = {}
    if download:
        # [FIX-DL-UTF8] RFC 6266: fallback ASCII + filename* UTF-8 encoded
        import urllib.parse as _ulp
        _ascii_name = filename.encode("ascii", "ignore").decode("ascii").replace('"', '_').replace("'", '_') or "download"
        _utf8_name = _ulp.quote(filename, safe="")
        headers["Content-Disposition"] = f'attachment; filename="{_ascii_name}"; filename*=UTF-8\'\'{_utf8_name}'
    return FileResponse(str(f_resolved), media_type=mt, headers=headers)

# Alias para compatibilidade com código anterior
@app.get("/video/{filename}")
def get_video(filename: str):
    return get_file(filename)


# ── [FIX-GALERIA] Miniatura JPG (poster) p/ vídeos ──────────────────────────
# Os mp4 do motor têm o moov atom no FIM (sem faststart) → o <video> não renderiza
# o 1º frame como miniatura em vários navegadores/WebView2 = THUMB PRETA. Solução:
# a galeria usa <video poster="/thumb/..."> — este endpoint gera o poster via ffmpeg
# (1 frame), cacheia, e serve como JPG (imagem renderiza sempre, independe de codec).
_THUMB_DIR  = TEMP_DIR / "_thumbs"
_FFMPEG_BIN = str(WAN2GP_DIR / "ffmpeg_bins" / "ffmpeg.exe")

@app.get("/thumb/{filename}")
def get_thumb(filename: str):
    if "/" in filename or "\\" in filename:
        raise HTTPException(status_code=400, detail="Nome de arquivo inválido")
    src = (OUTPUTS_DIR / filename).resolve()
    if not str(src).startswith(str(OUTPUTS_DIR.resolve())) or not src.exists():
        raise HTTPException(status_code=404, detail="Arquivo não encontrado")
    # imagens já são o próprio poster
    if src.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"):
        return FileResponse(str(src))
    try:
        _THUMB_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    thumb = _THUMB_DIR / (filename + ".jpg")
    # (re)gera se faltar ou se o vídeo for mais novo que o cache
    if (not thumb.exists()) or (thumb.stat().st_mtime < src.stat().st_mtime):
        try:
            subprocess.run(
                [_FFMPEG_BIN, "-y", "-ss", "0.5", "-i", str(src),
                 "-frames:v", "1", "-vf", "scale=320:-2", "-q:v", "5", str(thumb)],
                capture_output=True, timeout=30, creationflags=0x08000000)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"thumb falhou: {e}")
    if not thumb.exists():
        raise HTTPException(status_code=404, detail="poster não gerado")
    return FileResponse(str(thumb), media_type="image/jpeg")


# ══════════════════════════════════════════════
# SETTINGS — leitura e escrita do wgp_config.json
# ══════════════════════════════════════════════

import datetime

# WAN2GP_CONFIG_PATH, WAN2GP_CONFIG_BACKUP_DIR, ACS_CONFIG_PATH
# definidos no bloco CONFIG acima (BASE_DIR-relative)

# Versões do sistema (atualizadas a cada release)
_ACS_VERSION    = "0.6.6-1177"
_WAN2GP_VERSION = "12.25"
_MMGP_VERSION   = "3.7.6"

# ── Detecção de Triton (executada uma vez no startup, resultado cacheado) ─────

def _detect_triton_status() -> dict:
    """
    Detecta a disponibilidade e compatibilidade do Triton para torch.compile.
    Retorna dict com status, version, compile_safe e message.

    status values:
      "missing"      — triton não instalado
      "incompatible" — triton instalado mas com erro de import ou JIT
      "ok"           — triton funcional

    compile_safe: True apenas se status == "ok"
    """
    import importlib.util
    spec = importlib.util.find_spec("triton")
    if spec is None:
        return {
            "status":       "missing",
            "version":      None,
            "compile_safe": False,
            "message":      (
                "Triton não está instalado. "
                "torch.compile(backend='inductor') falhará — "
                "a opção 'Compilar Transformer' está bloqueada."
            ),
        }
    try:
        import triton  # noqa: F401
        version = getattr(triton, "__version__", "unknown")
        try:
            import triton.language as tl  # noqa: F401
            return {
                "status":       "ok",
                "version":      version,
                "compile_safe": True,
                "message":      f"Triton {version} instalado e funcional. Compile Transformer disponível.",
            }
        except Exception as exc:
            return {
                "status":       "incompatible",
                "version":      version,
                "compile_safe": False,
                "message":      (
                    f"Triton {version} instalado, mas falhou ao carregar triton.language: {exc}. "
                    "torch.compile pode não funcionar corretamente."
                ),
            }
    except Exception as exc:
        return {
            "status":       "incompatible",
            "version":      None,
            "compile_safe": False,
            "message":      f"Triton encontrado mas falhou ao importar: {exc}.",
        }


# Cache: detectado uma vez no carregamento do módulo (startup da API)
_TRITON_STATUS: dict = _detect_triton_status()


# ── Detecção de GPU / Modo Compatibilidade (Turing / RTX 20xx) ────────────────
#
# Problema: SageAttention + Triton kernels falham em GPUs com compute capability < 8.0
# (RTX 2060 Super, RTX 2070, RTX 2080, Quadro RTX, etc — arquitetura Turing, SM75).
# Erro típico: "TritonGPUAccelerateMatmul" / "Pass pipeline failed" / "MLIR pass pipeline"
#
# O Wan2GP tem guards em sage2_core.py (is_sage2_supported → cc >= 8.0) e em
# attention.py (get_supported_attention_modes), mas o setup.py pode auto-configurar
# "sage" para RTX 20xx SEM verificar compute capability. Resultado: crash silencioso.
#
# Solução: detectar GPU no startup da ACS API e auto-corrigir wgp_config.json.

def _detect_gpu_info() -> dict:
    """Detecta GPUs via nvidia-smi. Retorna info + flag de modo compatibilidade.

    compatibility_mode = True se compute capability < 8.0 (Turing ou anterior).
    Nesse caso, SageAttention/Triton/int8 kernels devem ser desabilitados.
    """
    try:
        import subprocess as _sp
        result = _sp.run(
            ["nvidia-smi", "--query-gpu=name,compute_cap", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            gpus = []
            for line in result.stdout.strip().splitlines():
                parts = [p.strip() for p in line.split(",")]
                if len(parts) >= 2:
                    name = parts[0]
                    cc = parts[1]
                    try:
                        cc_major, cc_minor = int(cc.split(".")[0]), int(cc.split(".")[1])
                    except (ValueError, IndexError):
                        cc_major, cc_minor = 0, 0
                    gpus.append({
                        "name": name,
                        "compute_capability": cc,
                        "cc_major": cc_major,
                        "cc_minor": cc_minor,
                    })
            if gpus:
                primary = gpus[0]
                _cc_maj = primary["cc_major"]
                _cc_min = primary["cc_minor"]
                # [FIX-COMPAT-SM86] Ampere consumer (sm_80-sm_86: RTX 3060/3070/3080/3090)
                # crasha sage2 por limite de shared memory (139KB > 101KB).
                # sage2 real exige Ada sm_89+ ou Hopper sm_90+.
                _is_ampere_consumer = (_cc_maj == 8 and _cc_min <= 6)
                compat = _cc_maj < 8 or _is_ampere_consumer
                _sage2_ok = _cc_maj >= 9 or (_cc_maj == 8 and _cc_min >= 9)
                return {
                    "gpus": gpus,
                    "primary": primary,
                    "compatibility_mode": compat,
                    "sage2_supported": _sage2_ok,
                    "sage_safe": _sage2_ok,
                    "triton_safe": _cc_maj >= 8 and not _is_ampere_consumer,
                    "reason": (
                        f"GPU {primary['name']} (SM{_cc_maj}{_cc_min}) — "
                        "SageAttention/Triton incompatíveis, usando SDPA"
                    ) if compat else "",
                }
    except Exception as exc:
        print(f"[ACS COMPAT] nvidia-smi falhou: {exc}")
    # Fallback: assume compatível se não consegue detectar
    return {
        "gpus": [],
        "primary": None,
        "compatibility_mode": False,
        "sage2_supported": True,
        "sage_safe": True,
        "triton_safe": True,
        "reason": "",
    }


_GPU_INFO: dict = _detect_gpu_info()

if _GPU_INFO["primary"]:
    _gpu_p = _GPU_INFO["primary"]
    print(f"[ACS COMPAT] GPU: {_gpu_p['name']} | CC {_gpu_p['compute_capability']} | "
          f"compat_mode={'ON' if _GPU_INFO['compatibility_mode'] else 'OFF'}")
else:
    print("[ACS COMPAT] GPU não detectada (nvidia-smi indisponível)")


def _enforce_gpu_compatibility():
    """Auto-corrige wgp_config.json se GPU não suporta sage/triton/int8.

    Chamada uma vez no startup. Faz backup antes de alterar.
    Garante que alunos com RTX 20xx não fiquem com config incompatível
    herdada de setup.py ou de um PC anterior.
    """
    if not _GPU_INFO["compatibility_mode"]:
        return  # GPU Ampere+ — tudo liberado

    config = _read_wan2gp_config()
    if not config:
        return

    changes = []

    # attention_mode: sage/sage2/sage3/radial → sdpa
    attn = config.get("attention_mode", "")
    if attn in ("sage", "sage2", "sage3", "radial"):
        config["attention_mode"] = "sdpa"
        changes.append(f"attention_mode: '{attn}' → 'sdpa'")

    # compile: transformer → "" (Triton compile falha em SM75)
    compile_mode = config.get("compile", "")
    if compile_mode:
        config["compile"] = ""
        changes.append(f"compile: '{compile_mode}' → '' (desabilitado)")

    # enable_int8_kernels: 1 → 0 (quanto_int8_triton.py rejeita CC < 8)
    int8k = config.get("enable_int8_kernels", 0)
    if int8k:
        config["enable_int8_kernels"] = 0
        changes.append("enable_int8_kernels: 1 → 0")

    if not changes:
        print("[ACS COMPAT] wgp_config.json já está compatível com esta GPU")
        return

    # Backup + patch
    _backup_config()
    try:
        WAN2GP_CONFIG_PATH.write_text(json.dumps(config, indent=4), encoding="utf-8")
    except Exception as exc:
        print(f"[ACS COMPAT] ERRO ao gravar wgp_config.json: {exc}")
        return

    _gpu_name = _GPU_INFO["primary"]["name"] if _GPU_INFO["primary"] else "?"
    _cc = _GPU_INFO["primary"]["compute_capability"] if _GPU_INFO["primary"] else "?"
    print(f"[ACS COMPAT] ════════════════════════════════════════════════")
    print(f"[ACS COMPAT] MODO COMPATIBILIDADE ATIVADO")
    print(f"[ACS COMPAT] GPU: {_gpu_name} (compute capability {_cc})")
    print(f"[ACS COMPAT] Ajustes em wgp_config.json:")
    for c in changes:
        print(f"[ACS COMPAT]   -> {c}")
    print(f"[ACS COMPAT] Backup salvo em {WAN2GP_CONFIG_BACKUP_DIR}")
    print(f"[ACS COMPAT] ════════════════════════════════════════════════")


# [FIX-COMPAT-ORDER] chamada movida p/ DEPOIS de _read_wan2gp_config + _backup_config


# ── Detecção de erros fatais em wan2gp.log (Triton/SageAttention crash) ────────
#
# Padrões que indicam crash de Triton/Sage em GPUs incompatíveis.
# Quando detectados durante PASSO 10 (polling de output), a geração é marcada
# como "error" imediatamente em vez de esperar o timeout de 600-1200s.

import re as _re

_FATAL_LOG_PATTERNS = [
    _re.compile(r"TritonGPUAccelerateMatmul", _re.IGNORECASE),
    _re.compile(r"Pass pipeline failed", _re.IGNORECASE),
    _re.compile(r"MLIR pass pipeline", _re.IGNORECASE),
    _re.compile(r"sageattention.*error|error.*sageattention", _re.IGNORECASE),
    _re.compile(r"Unsupported CUDA architecture.*sm7", _re.IGNORECASE),
    _re.compile(r"triton.*compilation.*failed|compilation.*triton.*failed", _re.IGNORECASE),
    # [FIX-FAST-FAIL] Gradio dropdown validation errors — detectar imediatamente em vez de
    # aguardar 1200s de timeout. Cobre: sample_solver inválido, resolução inválida, etc.
    _re.compile(r"Value:.*is not in the list of choices", _re.IGNORECASE),
    _re.compile(r"gradio\.exceptions\.Error.*not in the list", _re.IGNORECASE),
]

# [FIX-LOG-PATH] Procurar wan2gp.log em múltiplos locais — o caminho varia por instalação.
# AiStudio_1177_DEV usa logs/ na raiz com stderr do Wan2GP em wan_1177_err.log.
_WAN2GP_LOG_PATH = BASE_DIR / "logs" / "wan_1177_err.log"          # DEV stack (AiStudio_1177_DEV)
if not _WAN2GP_LOG_PATH.exists():
    _WAN2GP_LOG_PATH = BASE_DIR.parent / "user" / "logs" / "wan2gp.log"  # produção legado
if not _WAN2GP_LOG_PATH.exists():
    _WAN2GP_LOG_PATH = WAN2GP_DIR / ".." / "user" / "logs" / "wan2gp.log"


def _scan_log_for_fatal_errors(since_time: float = None, last_n_lines: int = 50,
                                log_start_offset: int = 0) -> str | None:
    """Lê wan2gp.log e verifica padrões fatais.

    Retorna mensagem de erro amigável se padrão fatal encontrado, None caso contrário.

    Args:
        since_time: (não usado — placeholder para compatibilidade futura)
        last_n_lines: quantas linhas verificar a partir de log_start_offset (default 50)
        log_start_offset: byte offset do qual ler — só verifica linhas NOVAS desde o início
            do job. Evita false-positives de erros de sessões anteriores que ainda estão
            no final do arquivo. [FIX-LOG-ANCHOR]
    """
    try:
        if not _WAN2GP_LOG_PATH.exists():
            return None
        with open(_WAN2GP_LOG_PATH, "rb") as _lf:
            _lf.seek(log_start_offset)
            _new_bytes = _lf.read()
        if not _new_bytes:
            return None  # nenhum conteúdo novo desde o início do job
        text = _new_bytes.decode("utf-8", errors="replace")
        lines = text.splitlines()
        tail = lines[-last_n_lines:] if len(lines) > last_n_lines else lines
        for line in tail:
            for pattern in _FATAL_LOG_PATTERNS:
                if pattern.search(line):
                    _msg = line.strip()[:250]
                    if "not in the list of choices" in line:
                        return f"Parâmetro inválido para o modelo (Gradio validation): {_msg}"
                    return (
                        "GPU/driver incompatível com otimizações avançadas (SageAttention/Triton). "
                        f"Erro detectado: {_msg}"
                    )
    except Exception:
        pass
    return None


# Subset de chaves expostas ao frontend (excluem internos, last_*, deepy_*)
_EXPOSED_SETTINGS = {
    # Performance / Hardware
    "attention_mode", "profile", "video_profile", "image_profile", "audio_profile",
    "transformer_quantization", "text_encoder_quantization",
    "enable_int8_kernels", "enable_4k_resolutions", "boost",
    "max_reserved_loras",
    # Avançado — Compilação, VAE, Preload, Engines
    "compile", "transformer_dtype_policy",
    "vae_precision", "vae_config",
    "lm_decoder_engine",
    "preload_model_policy", "preload_in_VRAM",
    # Paths / Output
    "save_path", "image_save_path", "audio_save_path", "loras_root",
    # Codec / Container
    "video_output_codec", "hdr_video_crf", "video_container", "embed_source_images",
    "image_output_codec", "audio_output_codec", "audio_stand_alone_output_codec",
    # MMAudio
    "mmaudio_mode", "mmaudio_persistence",
    # Prompt Enhancer
    "prompt_enhancer_temperature", "prompt_enhancer_top_p", "prompt_enhancer_randomize_seed",
    # Interface / UX
    "UI_theme", "queue_color_scheme", "process_queues_when_browser_unfocused",
    "notification_sound_enabled", "notification_sound_volume", "display_stats",
    # Misc safe
    "save_queue_if_crash", "keep_intermediate_sliding_windows",
}

# ── Fase 1: subset base de keys seguras (sem impacto em GPU/VRAM) ───────────
_PHASE1_WRITABLE = {
    # Pastas de saída
    "save_path", "image_save_path", "audio_save_path", "loras_root",
    # Codec / Container
    "video_output_codec", "video_container",
    "image_output_codec",
    "audio_output_codec", "audio_stand_alone_output_codec",
    # Notificações
    "notification_sound_enabled", "notification_sound_volume",
    # UI / Fila
    "display_stats",
    "process_queues_when_browser_unfocused",
    "save_queue_if_crash",
    # Prompt Enhancer
    "prompt_enhancer_temperature", "prompt_enhancer_top_p",
    "prompt_enhancer_randomize_seed",
    # Metadados
    "embed_source_images",
    "keep_intermediate_sliding_windows",
}

# ── Fase 2: Fase 1 + keys de performance (requerem restart do Wan2GP) ───────
_PHASE2_WRITABLE = _PHASE1_WRITABLE | {
    # Perfis de memória
    "video_profile", "image_profile", "audio_profile",
    # Atenção
    "attention_mode",
    # Quantização (desbloqueada na Fase 2)
    "transformer_quantization", "text_encoder_quantization",
    # Kernels
    "enable_int8_kernels",
    "boost",
    # MMAudio
    "mmaudio_mode", "mmaudio_persistence",
    # Interface Wan2GP
    "UI_theme", "queue_color_scheme",
    # Codec HDR
    "hdr_video_crf",
    # Avançado — Compilação, VAE, Preload, Engines
    "compile", "transformer_dtype_policy",
    "vae_precision", "vae_config",
    "lm_decoder_engine",
    "preload_model_policy", "preload_in_VRAM",
}

# ── Settings que exigem reinicialização do Wan2GP ────────────────────────────
_REQUIRES_RESTART_WAN2GP = {
    "attention_mode", "transformer_quantization", "text_encoder_quantization",
    "enable_int8_kernels", "profile", "video_profile", "image_profile", "audio_profile",
    "enable_4k_resolutions", "boost", "vae_config",
    # Avançado — Compilação, VAE, Preload, Engines (todos requerem restart)
    "compile", "transformer_dtype_policy",
    "vae_precision",
    "lm_decoder_engine",
    "preload_model_policy", "preload_in_VRAM",
}

# ── Settings que exigem reinicialização do ACS Studio ────────────────────────
_REQUIRES_RESTART_ACS: set = set()  # reservado para Fase futura

# Regras de validação: key → {"type", "values"?, "min"?, "max"?}
_VALIDATION_RULES: dict[str, dict] = {
    "attention_mode":               {"type": "enum",  "values": ["auto","sdpa","flash","sage","sage2","xformers"]},
    "profile":                      {"type": "enum",  "values": [1, 2, 3, 3.5, 4, 4.5, 5]},
    "video_profile":                {"type": "enum",  "values": [1, 2, 3, 3.5, 4, 4.5, 5]},
    "image_profile":                {"type": "enum",  "values": [1, 2, 3, 3.5, 4, 4.5, 5]},
    "audio_profile":                {"type": "number","min": 0, "max": 10},
    "transformer_quantization":     {"type": "enum",  "values": ["int8","fp8","bf16"]},
    "text_encoder_quantization":    {"type": "enum",  "values": ["int8","fp8","bf16"]},
    "enable_int8_kernels":          {"type": "bool"},
    "enable_4k_resolutions":        {"type": "bool"},
    "boost":                        {"type": "bool"},
    "max_reserved_loras":           {"type": "number","min": -1, "max": 64},
    "save_path":                    {"type": "path"},
    "image_save_path":              {"type": "path"},
    "audio_save_path":              {"type": "path"},
    "loras_root":                   {"type": "path"},
    "video_output_codec":           {"type": "enum",  "values": ["libx264_8","libx264_10","libx265_8","libx265_10","prores_4444","prores_422"]},
    "hdr_video_crf":                {"type": "number","min": 0, "max": 51},
    "video_container":              {"type": "enum",  "values": ["mp4","mkv","mov"]},
    "embed_source_images":          {"type": "bool"},
    "image_output_codec":           {"type": "enum",  "values": ["jpeg_95","jpeg_85","jpeg_75","png","webp_95","webp_80"]},
    "audio_output_codec":           {"type": "enum",  "values": ["aac_128","aac_192","aac_256","mp3_192","mp3_320","opus_128"]},
    "audio_stand_alone_output_codec": {"type": "enum","values": ["wav","mp3","aac","flac","ogg"]},
    "mmaudio_mode":                 {"type": "enum",  "values": [0, 1, 2]},
    "mmaudio_persistence":          {"type": "enum",  "values": [1, 2]},
    "prompt_enhancer_temperature":  {"type": "number","min": 0.0, "max": 2.0},
    "prompt_enhancer_top_p":        {"type": "number","min": 0.0, "max": 1.0},
    "prompt_enhancer_randomize_seed": {"type": "bool"},
    "UI_theme":                     {"type": "enum",  "values": ["default","dark","light","soft","glass"]},
    "queue_color_scheme":           {"type": "enum",  "values": ["pastel","dark","bright"]},
    "process_queues_when_browser_unfocused": {"type": "bool"},
    "notification_sound_enabled":   {"type": "bool"},
    "notification_sound_volume":    {"type": "number","min": 0, "max": 100},
    "display_stats":                {"type": "bool"},
    "save_queue_if_crash":          {"type": "bool"},
    "keep_intermediate_sliding_windows": {"type": "bool"},
    # Avançado — Compilação, VAE, Preload, Engines
    "compile":                     {"type": "enum",  "values": ["", "transformer"]},
    "transformer_dtype_policy":    {"type": "enum",  "values": ["", "bf16", "fp16"]},
    "vae_precision":               {"type": "enum",  "values": ["16", "32"]},
    "vae_config":                  {"type": "enum",  "values": [0, 1, 2]},
    "lm_decoder_engine":           {"type": "enum",  "values": ["", "legacy", "cg", "vllm"]},
    "preload_in_VRAM":             {"type": "bool"},
    "preload_model_policy":        {"type": "array", "allowed": ["P", "S", "U"]},
}

# Defaults de restauração (mesmos valores que o Wan2GP usa se o arquivo não existe)
_DEFAULT_SETTINGS: dict = {
    "attention_mode": "auto",
    "profile": 4, "video_profile": 4, "image_profile": 2, "audio_profile": 2,
    "transformer_quantization": "int8", "text_encoder_quantization": "int8",
    "enable_int8_kernels": 1, "enable_4k_resolutions": 0, "boost": 1,
    "max_reserved_loras": -1,
    "save_path": "outputs", "image_save_path": "outputs",
    "audio_save_path": "outputs", "loras_root": "loras",
    "video_output_codec": "libx264_8", "hdr_video_crf": 8,
    "video_container": "mp4", "embed_source_images": False,
    "image_output_codec": "jpeg_95",
    "audio_output_codec": "aac_128", "audio_stand_alone_output_codec": "wav",
    "mmaudio_mode": 0, "mmaudio_persistence": 1,
    "prompt_enhancer_temperature": 0.6, "prompt_enhancer_top_p": 0.9,
    "prompt_enhancer_randomize_seed": True,
    "UI_theme": "default", "queue_color_scheme": "pastel",
    "process_queues_when_browser_unfocused": 1,
    "notification_sound_enabled": 1, "notification_sound_volume": 50,
    "display_stats": 0, "save_queue_if_crash": 1,
    "keep_intermediate_sliding_windows": 1,
    # Avançado — Compilação, VAE, Preload, Engines
    "compile": "",
    "transformer_dtype_policy": "",
    "vae_precision": "16",
    "vae_config": 0,
    "lm_decoder_engine": "",
    "preload_in_VRAM": 0,
    "preload_model_policy": [],
}

# Defaults do acs_config.json — 1177 DEV stack
_ACS_CONFIG_DEFAULTS: dict = {
    "api_port": 8010,
    "gradio_url": "http://localhost:7871",
    "auto_open_browser": False,
    "log_level": "info",
    "output_limit": 200,
    "generation_timeout_s": 1200,
    "audio_timeout_s": 3600,
    "gallery_limit": 100,
    "dev_mode": False,
    "update_base_url": "",
    "update_channel": "stable",
}


def _read_acs_config() -> dict:
    """Lê acs_config.json com fallback para defaults se inválido ou ausente."""
    try:
        if ACS_CONFIG_PATH.exists():
            data = json.loads(ACS_CONFIG_PATH.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                # Merge: defaults como base, valores salvos sobrescrevem
                return {**_ACS_CONFIG_DEFAULTS, **data}
    except Exception:
        pass
    return dict(_ACS_CONFIG_DEFAULTS)


def _read_wan2gp_config() -> dict:
    """Lê wgp_config.json e retorna como dict. Retorna {} em caso de erro."""
    try:
        if WAN2GP_CONFIG_PATH.is_file():
            return json.loads(WAN2GP_CONFIG_PATH.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def _validate_setting(key: str, value) -> tuple[bool, str]:
    """Valida um valor para um setting específico. Retorna (ok, mensagem_erro)."""
    rule = _VALIDATION_RULES.get(key)
    if rule is None:
        return False, f"Setting '{key}' não é permitido."

    kind = rule["type"]

    if kind == "enum":
        if value not in rule["values"]:
            return False, f"'{key}' aceita apenas: {rule['values']}. Recebido: {repr(value)}"
        return True, ""

    if kind == "bool":
        if value not in (0, 1, True, False):
            return False, f"'{key}' deve ser 0/1 ou true/false."
        return True, ""

    if kind == "number":
        try:
            num = float(value)
        except (TypeError, ValueError):
            return False, f"'{key}' deve ser numérico."
        lo, hi = rule.get("min"), rule.get("max")
        if lo is not None and num < lo:
            return False, f"'{key}' mínimo é {lo}. Recebido: {num}"
        if hi is not None and num > hi:
            return False, f"'{key}' máximo é {hi}. Recebido: {num}"
        return True, ""

    if kind == "path":
        try:
            p = Path(str(value)).expanduser()
            p.mkdir(parents=True, exist_ok=True)
            if not os.access(str(p), os.W_OK):
                return False, f"'{key}': pasta sem permissão de escrita: {p}"
        except Exception as exc:
            return False, f"'{key}': caminho inválido — {exc}"
        return True, ""

    if kind == "array":
        if not isinstance(value, list):
            return False, f"'{key}' deve ser uma lista. Recebido: {type(value).__name__}"
        allowed = rule.get("allowed", [])
        if allowed:
            for item in value:
                if item not in allowed:
                    return False, f"'{key}': item inválido '{item}'. Aceita: {allowed}"
        return True, ""

    return True, ""


def _backup_config() -> str | None:
    """Cria backup de wgp_config.json em .config_backups/. Retorna nome do backup."""
    try:
        if not WAN2GP_CONFIG_PATH.is_file():
            return None
        WAN2GP_CONFIG_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        dst = WAN2GP_CONFIG_BACKUP_DIR / f"wgp_config.{ts}.json"
        shutil.copy2(str(WAN2GP_CONFIG_PATH), str(dst))
        # Manter apenas 10 backups mais recentes
        backups = sorted(WAN2GP_CONFIG_BACKUP_DIR.glob("wgp_config.*.json"))
        for old in backups[:-10]:
            old.unlink(missing_ok=True)
        return dst.name
    except Exception:
        return None


# [FIX-COMPAT-ORDER] Executar no startup — DEPOIS das definições de _read_wan2gp_config e _backup_config
_enforce_gpu_compatibility()


# ── GET /version ────────────────────────────────────────────────────────────

@app.get("/version")
def get_version():
    """Retorna versões dos componentes do sistema."""
    return {
        "acs_api":  _ACS_VERSION,
        "wan2gp":   _WAN2GP_VERSION,
        "mmgp":     _MMGP_VERSION,
        "config_path": str(WAN2GP_CONFIG_PATH),
        "config_exists": WAN2GP_CONFIG_PATH.is_file(),
    }


# ── GET /config/triton-status ────────────────────────────────────────────────

@app.get("/config/triton-status")
def get_triton_status():
    """
    Retorna o status do Triton detectado no startup da API.
    Usado pelo frontend para determinar se 'Compile Transformer' pode ser ativado.
    """
    return _TRITON_STATUS


# ── GET /config/gpu-info ──────────────────────────────────────────────────────

@app.get("/config/gpu-info")
def get_gpu_info():
    """
    Retorna informação da GPU + status do modo compatibilidade.

    compatibility_mode=true indica GPU Turing/anterior (CC < 8.0):
      - SageAttention desabilitado
      - Triton compile desabilitado
      - INT8 kernels desabilitados
      - Usando SDPA (PyTorch native attention)

    Usado pelo frontend para:
      - Mostrar aviso ao aluno sobre modo compatibilidade
      - Bloquear opções de sage/sage2 no settings
      - Ajustar expectativas de performance
    """
    return {
        **_GPU_INFO,
        "triton": _TRITON_STATUS,
    }


# ── GET /config/disk-space ──────────────────────────────────────────────────

@app.get("/config/disk-space")
def get_disk_space():
    """
    Retorna espaço livre em disco na partição onde ficam os checkpoints.
    Usado pelo frontend para avisar antes de downloads grandes.
    """
    try:
        target = WAN2GP_DIR if WAN2GP_DIR.exists() else BASE_DIR
        usage = shutil.disk_usage(target)
        return {
            "free_gb":  round(usage.free / (1024 ** 3), 1),
            "total_gb": round(usage.total / (1024 ** 3), 1),
            "used_gb":  round(usage.used / (1024 ** 3), 1),
            "path":     str(target),
        }
    except Exception as e:
        return {"free_gb": None, "error": str(e)}


# ── GET /config ─────────────────────────────────────────────────────────────

@app.get("/config")
def get_config():
    """Lê wgp_config.json e retorna o subset seguro de settings expostos."""
    raw = _read_wan2gp_config()
    if not raw:
        return JSONResponse(
            status_code=503,
            content={"error": "Não foi possível ler wgp_config.json", "path": str(WAN2GP_CONFIG_PATH)}
        )
    # Retorna apenas keys expostas, com fallback para defaults
    settings = {}
    for key in _EXPOSED_SETTINGS:
        settings[key] = raw.get(key, _DEFAULT_SETTINGS.get(key))
    return {
        "settings": settings,
        "validation_rules": _VALIDATION_RULES,
        "requires_restart": list(_REQUIRES_RESTART_WAN2GP),
        "defaults": _DEFAULT_SETTINGS,
        "config_path": str(WAN2GP_CONFIG_PATH),
        "last_backup": _latest_backup_name(),
    }


def _latest_backup_name() -> str | None:
    if WAN2GP_CONFIG_BACKUP_DIR.exists():
        backups = sorted(WAN2GP_CONFIG_BACKUP_DIR.glob("wgp_config.*.json"))
        return backups[-1].name if backups else None
    return None


# ── POST /config/update ──────────────────────────────────────────────────────

class ConfigUpdateRequest(BaseModel):
    settings: dict  # {key: value, ...}

@app.post("/config/update")
def update_config(req: ConfigUpdateRequest):
    """Valida, faz backup e escreve settings em wgp_config.json."""
    updates = req.settings

    # 1. Rejeitar keys fora da whitelist Fase 2
    disallowed = [k for k in updates if k not in _PHASE2_WRITABLE]
    if disallowed:
        raise HTTPException(422, detail=f"Settings não permitidos: {disallowed}")

    # 2. Validar cada valor
    errors = {}
    for key, val in updates.items():
        ok, msg = _validate_setting(key, val)
        if not ok:
            errors[key] = msg
    if errors:
        raise HTTPException(422, detail={"validation_errors": errors})

    # 2b. Safety check: compile requer Triton funcional
    if "compile" in updates and updates["compile"] != "":
        if not _TRITON_STATUS.get("compile_safe", False):
            raise HTTPException(422, detail={
                "triton_blocked": True,
                "message": (
                    f"compile='{updates['compile']}' requer Triton funcional. "
                    f"Status atual: {_TRITON_STATUS.get('status', 'unknown')}. "
                    f"{_TRITON_STATUS.get('message', '')} "
                    "Desative 'Compilar Transformer' ou instale o Triton compatível."
                ),
                "triton_status": _TRITON_STATUS,
            })

    # 2c. Safety check: modo compatibilidade bloqueia sage/sage2/compile
    if _GPU_INFO.get("compatibility_mode", False):
        _blocked = {}
        if "attention_mode" in updates and updates["attention_mode"] in ("sage", "sage2", "sage3", "radial"):
            _blocked["attention_mode"] = (
                f"'{updates['attention_mode']}' não é compatível com esta GPU "
                f"({_GPU_INFO['primary']['name']}, compute capability {_GPU_INFO['primary']['compute_capability']}). "
                "Use 'sdpa' ou 'auto'."
            )
        if "compile" in updates and updates["compile"] != "":
            _blocked["compile"] = (
                f"Triton compile não é compatível com esta GPU "
                f"({_GPU_INFO['primary']['name']}). Desative 'Compilar Transformer'."
            )
        if "enable_int8_kernels" in updates and updates["enable_int8_kernels"]:
            _blocked["enable_int8_kernels"] = (
                f"INT8 Triton kernels não são compatíveis com esta GPU "
                f"({_GPU_INFO['primary']['name']}). Mantenha desabilitado."
            )
        if _blocked:
            raise HTTPException(422, detail={
                "compatibility_blocked": True,
                "message": "Modo compatibilidade ativo — configurações bloqueadas para esta GPU.",
                "blocked_settings": _blocked,
                "gpu_info": _GPU_INFO,
            })

    # 3. Ler config atual
    current = _read_wan2gp_config()
    if not current:
        raise HTTPException(503, detail="Não foi possível ler wgp_config.json")

    # 4. Backup antes de qualquer escrita
    backup_name = _backup_config()
    if backup_name is None:
        raise HTTPException(500, detail="Falha ao criar backup — operação cancelada")

    # 5. Aplicar updates
    current.update(updates)

    # 6. Escrever JSON
    try:
        WAN2GP_CONFIG_PATH.write_text(
            json.dumps(current, indent=4, ensure_ascii=False),
            encoding="utf-8"
        )
    except Exception as exc:
        # Restaurar backup automaticamente
        backup_path = WAN2GP_CONFIG_BACKUP_DIR / backup_name
        if backup_path.exists():
            shutil.copy2(str(backup_path), str(WAN2GP_CONFIG_PATH))
        raise HTTPException(500, detail=f"Erro ao gravar arquivo: {exc}")

    # 7. Calcular quais mudanças exigem restart e de qual serviço
    wan2gp_restart = [k for k in updates if k in _REQUIRES_RESTART_WAN2GP]
    acs_restart    = [k for k in updates if k in _REQUIRES_RESTART_ACS]
    restart_needed = wan2gp_restart + acs_restart

    if wan2gp_restart:
        restart_type = "wan2gp"
    elif acs_restart:
        restart_type = "acs"
    else:
        restart_type = None

    if wan2gp_restart:
        msg_suffix = f"Reinicie o Wan2GP para aplicar: {wan2gp_restart}"
    elif acs_restart:
        msg_suffix = f"Reinicie o ACS Studio para aplicar: {acs_restart}"
    else:
        msg_suffix = ""

    print(f"[ACS Settings] {len(updates)} setting(s) gravado(s): "
          f"{list(updates.keys())} | restart_type={restart_type} | backup: {backup_name}")

    return {
        "ok": True,
        "restart_required": len(restart_needed) > 0,
        "restart_type": restart_type,
        "status": "ok",
        "updated": list(updates.keys()),
        "backup": backup_name,
        "requires_restart": restart_needed,
        "message": f"{len(updates)} setting(s) salvo(s). " + msg_suffix,
    }


# ── POST /config/validate-path ───────────────────────────────────────────────

class ValidatePathRequest(BaseModel):
    path: str

@app.post("/config/validate-path")
def validate_path(req: ValidatePathRequest):
    """Verifica se um caminho existe e tem permissão de escrita."""
    try:
        p = Path(req.path).expanduser().resolve()
        exists = p.exists()
        writable = os.access(str(p), os.W_OK) if exists else False
        # Tenta criar se não existe
        if not exists:
            try:
                p.mkdir(parents=True, exist_ok=True)
                exists = True
                writable = True
            except Exception as exc:
                return {"valid": False, "exists": False, "writable": False,
                        "resolved": str(p), "error": str(exc)}
        return {"valid": writable, "exists": exists, "writable": writable,
                "resolved": str(p), "error": None}
    except Exception as exc:
        return {"valid": False, "exists": False, "writable": False,
                "resolved": req.path, "error": str(exc)}


# ── POST /config/backup ───────────────────────────────────────────────────────

@app.post("/config/backup")
def create_backup():
    """Cria backup manual de wgp_config.json."""
    name = _backup_config()
    if name is None:
        raise HTTPException(500, detail="Falha ao criar backup")
    return {
        "status": "ok",
        "backup": name,
        "path": str(WAN2GP_CONFIG_BACKUP_DIR / name),
    }


# ── GET /config/acs ───────────────────────────────────────────────────────────

@app.get("/config/acs")
def get_acs_config():
    """Retorna o conteúdo atual de acs_config.json (com fallback para defaults)."""
    return {"ok": True, "config": _read_acs_config(), "defaults": _ACS_CONFIG_DEFAULTS}


# ── POST /config/acs/update ───────────────────────────────────────────────────

class AcsConfigUpdateRequest(BaseModel):
    config: dict  # {key: value, ...}  — subset ou total

@app.post("/config/acs/update")
def update_acs_config(req: AcsConfigUpdateRequest):
    """Valida e grava atualizações em acs_config.json (escrita atômica)."""
    updates = req.config

    # 1. Aceitar apenas keys conhecidas
    disallowed = [k for k in updates if k not in _ACS_CONFIG_DEFAULTS]
    if disallowed:
        raise HTTPException(422, detail=f"Keys desconhecidas em acs_config: {disallowed}")

    # 2. Ler config atual (com fallback)
    current = _read_acs_config()

    # 3. Aplicar updates
    current.update(updates)

    # 4. Escrever com padrão atômico (temp → replace)
    tmp_path = ACS_CONFIG_PATH.with_suffix(".json.tmp")
    try:
        tmp_path.write_text(
            json.dumps(current, indent=4, ensure_ascii=False),
            encoding="utf-8"
        )
        # replace() é atômico em NTFS dentro do mesmo volume
        tmp_path.replace(ACS_CONFIG_PATH)
    except Exception as exc:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise HTTPException(500, detail=f"Erro ao gravar acs_config.json: {exc}")

    print(f"[ACS Config] {len(updates)} key(s) atualizada(s): {list(updates.keys())}")

    return {
        "ok": True,
        "updated": list(updates.keys()),
        "config": current,
        "message": f"{len(updates)} configuração(ões) do ACS salva(s).",
    }


# ── GET /config/backups ───────────────────────────────────────────────────────

@app.get("/config/backups")
def list_backups():
    """Lista backups disponíveis de wgp_config.json."""
    if not WAN2GP_CONFIG_BACKUP_DIR.exists():
        return {"backups": []}
    backups = sorted(WAN2GP_CONFIG_BACKUP_DIR.glob("wgp_config.*.json"), reverse=True)
    result = []
    for b in backups[:20]:
        stat = b.stat()
        result.append({
            "name": b.name,
            "size_kb": round(stat.st_size / 1024, 1),
            "created": datetime.datetime.fromtimestamp(stat.st_mtime).isoformat(),
        })
    return {"backups": result}


# ──────────────────────────────────────────────────────────────────────────────
# AUTO-UPDATE (FASE 7) — check + download + signal pro launcher
# ──────────────────────────────────────────────────────────────────────────────

_ACS_VERSION_STR = "0.7.0"

def _read_local_version() -> dict:
    out = {"build": 0, "version": _ACS_VERSION_STR}
    try:
        vj = json.loads((_PROJECT_ROOT / "version.json").read_text(encoding="utf-8-sig"))
        out["build"] = int(vj.get("build", 0) or 0)
        out["version"] = vj.get("version", _ACS_VERSION_STR)
    except Exception:
        pass
    return out

_UPDATE_STATE: dict = {"phase": "idle", "pct": 0, "msg": "", "error": "", "build": 0}
_UPDATE_LOCK = threading.Lock()
_UPDATE_FILE_RE = re.compile(r"^[A-Za-z0-9._-]+\.zip$")

def _set_update_state(**kw):
    with _UPDATE_LOCK:
        _UPDATE_STATE.update(kw)

def _do_update_download(base: str, channel: str):
    import urllib.request as _u
    import urllib.parse as _up
    import hashlib
    try:
        _set_update_state(phase="checking", pct=2, msg="Verificando versão...", error="")
        with _u.urlopen(_u.Request(f"{base}/latest?channel={_up.quote(channel)}",
                                   headers={"User-Agent": "ACS-installer"}), timeout=15) as r:
            manifest = json.loads(r.read().decode("utf-8", "replace"))

        _sig_on = False
        _usign = None
        try:
            import sys as _s2
            for _tp in (str(BASE_DIR / "tools"), str(BASE_DIR.parent / "tools")):
                if _tp not in _s2.path:
                    _s2.path.insert(0, _tp)
            import acs_update_sign as _usign
            _sig_on = _usign.signing_enabled()
        except Exception as _esig:
            print(f"[ACS UPDATE] módulo de assinatura indisponível: {_esig}")
        if _sig_on:
            try:
                _sig_ok = _usign.verify_manifest(manifest)
            except Exception as _ve:
                _sig_ok = False
                print(f"[ACS UPDATE] erro ao verificar assinatura: {_ve}")
            if not _sig_ok:
                _set_update_state(phase="error", error="Assinatura do servidor inválida — atualização recusada por segurança.")
                print("[ACS UPDATE] assinatura do manifesto INVÁLIDA — abortado")
                return

        file = str(manifest.get("file", ""))
        sha_expected = str(manifest.get("sha256", "")).lower()
        to_build = int(manifest.get("build", 0) or 0)
        size_expected = int(manifest.get("size", 0) or 0)
        if not _UPDATE_FILE_RE.match(file):
            _set_update_state(phase="error", error="Nome de arquivo inválido no servidor.")
            return
        if len(sha_expected) != 64:
            _set_update_state(phase="error", error="Servidor sem SHA256 — instalação abortada por segurança.")
            return

        dl_dir = _PROJECT_ROOT / "user" / "temp" / "updates"
        dl_dir.mkdir(parents=True, exist_ok=True)
        zip_path = dl_dir / file

        dl_url = f"{base}/download/{_up.quote(file)}"
        _set_update_state(phase="downloading", pct=5, msg="Baixando atualização...", build=to_build)
        MAX_BYTES = 800 * 1024 * 1024
        h = hashlib.sha256()
        got = 0
        with _u.urlopen(_u.Request(dl_url, headers={"User-Agent": "ACS-installer"}), timeout=60) as resp:
            total = int(resp.headers.get("Content-Length", size_expected or 0) or 0)
            with open(zip_path, "wb") as f:
                while True:
                    chunk = resp.read(262144)
                    if not chunk:
                        break
                    got += len(chunk)
                    if got > MAX_BYTES:
                        raise ValueError("Arquivo excede o limite de segurança (800 MB).")
                    f.write(chunk)
                    h.update(chunk)
                    if total:
                        _set_update_state(pct=5 + int(got / total * 80), msg=f"Baixando... {got // 1024 // 1024} MB")

        sha_actual = h.hexdigest().lower()
        if sha_actual != sha_expected:
            try: zip_path.unlink()
            except Exception: pass
            _set_update_state(phase="error", error="Verificação de integridade (SHA256) falhou — download descartado.")
            return

        _set_update_state(phase="verified", pct=90, msg="Integridade OK. Preparando instalação...")
        _RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        (_RUNTIME_DIR / "acs_update.json").write_text(
            json.dumps({"zip": str(zip_path), "to_build": to_build,
                        "to_version": manifest.get("version", "")}, ensure_ascii=False),
            encoding="utf-8",
        )
        _set_update_state(phase="ready_restart", pct=100,
                          msg="Atualização pronta. O Studio vai reiniciar para concluir.")
        print(f"[ACS UPDATE] pedido escrito: {_RUNTIME_DIR / 'acs_update.json'} (build {to_build})")
    except Exception as exc:
        _set_update_state(phase="error", error=f"Falha ao baixar atualização: {exc}")
        print(f"[ACS UPDATE] erro no download: {exc}")


@app.get("/update/check")
def update_check():
    import urllib.request as _u
    import urllib.parse as _up

    cfg = _read_acs_config()
    base = (cfg.get("update_base_url") or "").strip().rstrip("/")
    channel = (cfg.get("update_channel") or "stable").strip()
    loc = _read_local_version()

    if not base:
        return {
            "configured": False, "update_available": False,
            "local_build": loc["build"], "local_version": loc["version"],
            "reason": "Canal de atualização não configurado.",
        }
    if not (base.startswith("https://") or base.startswith("http://")):
        return {
            "configured": False, "update_available": False,
            "local_build": loc["build"], "local_version": loc["version"],
            "error": "update_base_url inválida (precisa começar com https://).",
        }

    url = f"{base}/latest?channel={_up.quote(channel)}"
    try:
        req = _u.Request(url, headers={"User-Agent": f"ACS/{loc['version']}"})
        with _u.urlopen(req, timeout=10) as r:
            remote = json.loads(r.read().decode("utf-8", "replace"))
    except Exception as exc:
        return {
            "configured": True, "update_available": False,
            "local_build": loc["build"], "local_version": loc["version"],
            "error": f"Não foi possível consultar o servidor de atualização: {exc}",
        }

    remote_build = int(remote.get("build", 0) or 0)
    return {
        "configured": True,
        "update_available": remote_build > loc["build"],
        "local_build": loc["build"], "local_version": loc["version"],
        "remote_build": remote_build,
        "remote_version": remote.get("version"),
        "channel": channel,
        "notes": remote.get("notes", ""),
        "mandatory": bool(remote.get("mandatory", False)),
        "size": remote.get("size"),
        "sha256": remote.get("sha256"),
        "file": remote.get("file"),
        "url": remote.get("url"),
        "date": remote.get("date"),
    }


@app.post("/update/install")
def update_install():
    cfg = _read_acs_config()
    base = (cfg.get("update_base_url") or "").strip().rstrip("/")
    channel = (cfg.get("update_channel") or "stable").strip()
    if not (base.startswith("https://") or base.startswith("http://")):
        return {"started": False, "error": "Canal de atualização não configurado."}

    with _UPDATE_LOCK:
        if _UPDATE_STATE.get("phase") in ("downloading", "checking", "verified"):
            return {"started": False, "error": "Uma instalação já está em andamento.", "phase": _UPDATE_STATE["phase"]}
        _UPDATE_STATE.update({"phase": "starting", "pct": 0, "msg": "Iniciando...", "error": "", "build": 0})

    threading.Thread(target=_do_update_download, args=(base, channel), daemon=True).start()
    return {"started": True}


@app.get("/update/status")
def update_status():
    with _UPDATE_LOCK:
        return dict(_UPDATE_STATE)


# ──────────────────────────────────────────────
# MAPEAMENTO DE MODOS — flags Wan2GP por generation_mode
#
# O Wan2GP usa três strings de flags concatenadas para controlar o modo:
#   image_prompt_type : "S"=start frame, "E"=end frame, "SE"=FLF, "V"=video source
#   video_prompt_type : "V"=control video, "G"=denoising, "I"=ref images, "F"=frame injection
#   audio_prompt_type : "A"=audio guide, "B"=2nd audio, "R"=rhythm, "K"=ctrl video audio
#
# NÃO usar gallery_tab para controlar o modo — ele só seta gen["last_was_audio"]
# O modo REAL é determinado pelo image_prompt_type no state (via save_inputs).
# ──────────────────────────────────────────────
_IMAGE_PROMPT_TYPE: dict[str, str] = {
    "t2v":      "",    # Text to Video — sem condicionamento de imagem
    "i2v":      "S",   # Image to Video — start frame
    "flf":      "SE",  # First-Last Frame — start + end frame
    "continue": "V",   # Continue Video — video source como contexto
    "t2i":      "",    # Text to Image — image_mode=1 controla; prompt type vazio
}

# gallery_tab: só controla gen["last_was_audio"] em process_prompt_and_add_tasks.
# Para geração de vídeo/imagem: sempre 0.0 (galeria de vídeo).
# Para geração com audio output: 1.0 (galeria de áudio).
_GALLERY_TAB_VIDEO = 0.0
_GALLERY_TAB_AUDIO = 1.0


# ──────────────────────────────────────────────
# WRAPPERS POR MODO — retornam dict com params específicos de cada modo
# para uso no save_inputs call.
# ──────────────────────────────────────────────

def _build_t2v_params(req: GenerateRequest) -> dict:
    """Text to Video — sem condicionamento de imagem ou vídeo.
    [12.24] Modelos de edição por referência (EditAnything/Bernini) exigem a imagem
    de referência em image_refs (a 'Image Reference' do workflow de edição ref-V2V)."""
    _img_refs = []
    if MODELS.get(req.model, {}).get("needs_image_ref") and req.ref_inject_paths:
        _img_refs = [_wrap_gallery_item(p) for p in req.ref_inject_paths if p]
    return {
        "image_prompt_type":    "",
        "image_start_param":    [],
        "image_end_param":      [],
        "video_source_param":   None,
        "input_video_strength": 1.0,
        "gallery_tab":          _GALLERY_TAB_VIDEO,
        "image_refs_param":     _img_refs,
    }


def _build_i2v_params(req: GenerateRequest) -> dict:
    """Image to Video — start frame obrigatório (image_prompt_type='S').

    Suporta addons:
    - Frame Inject: image_refs_param = inject images (slots 2, 3, 4…)
        * LTX2:  video_prompt_type = "KFI" + frames_positions computado
        * VACE:  video_prompt_type = "FI"  + frames_positions computado
        * Outros: inject não suportado — image_refs_param fica vazio
      O start frame NÃO vai para image_refs — apenas os slots extras.
      image_prompt_type permanece "S" (sem flags extras de inject).
    - Ctrl Video: ctrl_video_path → video_guide (não video_source)
      video_prompt_type já inclui ctrl_video_prompt_type via campo global.
    """
    # image_prompt_type: apenas "S" — o inject fica em video_prompt_type
    ipt = "S"

    # image_refs: frames inject (slots 2, 3, 4… — SEM o start frame)
    # Só usa inject se o modelo suportar via _get_inject_video_prompt_type
    model_inject_type = _get_inject_video_prompt_type(req.model) if req.inject_video_prompt_type else ""

    if model_inject_type and req.ref_inject_paths:
        image_refs = [_wrap_gallery_item(p) for p in req.ref_inject_paths if p]
    else:
        image_refs = []
        model_inject_type = ""   # garante que video_prompt_type não inclui flags de inject

    return {
        "image_prompt_type":    ipt,
        "image_start_param":    [_wrap_gallery_item(req.ref_image_path)] if req.ref_image_path else [],
        "image_end_param":      [],
        "video_source_param":   None,
        "input_video_strength": float(req.source_strength),
        "gallery_tab":          _GALLERY_TAB_VIDEO,
        "image_refs_param":     image_refs,
        "model_inject_type":    model_inject_type,   # "KFI", "FI" ou ""
    }


def _build_flf_params(req: GenerateRequest) -> dict:
    """First-Last Frame — start + end frame (image_prompt_type='SE')."""
    return {
        "image_prompt_type":    "SE",
        "image_start_param":    [_wrap_gallery_item(req.ref_image_path)] if req.ref_image_path else [],
        "image_end_param":      [_wrap_gallery_item(req.end_image_path)] if req.end_image_path else [],
        "video_source_param":   None,
        "input_video_strength": 1.0,
        "gallery_tab":          _GALLERY_TAB_VIDEO,
        "image_refs_param":     [],
    }


def _build_continue_params(req: GenerateRequest) -> dict:
    """Continue Video — video source como contexto (image_prompt_type='V').

    video_source é um gr.Video no Wan2GP → espera VideoData: {"video": FileData}
    NÃO passar FileData direto (causa ValidationError: Field 'video' required).
    """
    # gr.Video espera {"video": FileData}, não FileData direto
    vs = _wrap_gallery_item(req.ctrl_video_path) if req.ctrl_video_path else None
    # _wrap_gallery_item já retorna {"video": fd} para extensões .mp4/.webm/.mov
    return {
        "image_prompt_type":    "V",
        "image_start_param":    [],
        "image_end_param":      [_wrap_gallery_item(req.end_image_path)] if req.end_image_path else [],
        "video_source_param":   vs,
        "input_video_strength": float(req.source_strength),
        "gallery_tab":          _GALLERY_TAB_VIDEO,
        "image_refs_param":     [],
    }


def _build_t2i_params(req: GenerateRequest) -> dict:
    """Text to Image — image_mode=1 no MODELS dict já controla; prompt type vazio."""
    return {
        "image_prompt_type":    "",
        "image_start_param":    [],
        "image_end_param":      [],
        "video_source_param":   None,
        "input_video_strength": 1.0,
        "gallery_tab":          _GALLERY_TAB_VIDEO,
        "image_refs_param":     [],
    }


def _build_control_params(req: GenerateRequest) -> dict:
    """Control Video / V2V — video_prompt_type controla o tipo de controle.
    Usado quando ctrl_video_path + ctrl_video_prompt_type estão presentes.
    """
    return {
        "image_prompt_type":    "",
        "image_start_param":    [],
        "image_end_param":      [],
        "video_source_param":   None,
        "input_video_strength": float(req.source_strength),
        "gallery_tab":          _GALLERY_TAB_VIDEO,
        "image_refs_param":     [],
    }


_MODE_BUILDERS = {
    "t2v":      _build_t2v_params,
    "i2v":      _build_i2v_params,
    "flf":      _build_flf_params,
    "continue": _build_continue_params,
    "t2i":      _build_t2i_params,
}


# ──────────────────────────────────────────────
# LÓGICA DE GERAÇÃO — FLUXO COMPLETO 9 PASSOS
# Reproduz exatamente o fluxo do botão GERAR do Wan2GP
# Confirmado via test_generate_original_flow.py em 2026-05-10
# ──────────────────────────────────────────────
def _snapshot_outputs() -> set:
    """Retorna set com nomes dos arquivos atuais em outputs."""
    if not OUTPUTS_DIR.exists():
        return set()
    return {f.name for f in OUTPUTS_DIR.iterdir() if f.is_file()}


def _is_transient_output(name: str) -> bool:
    """Retorna True para arquivos transitórios criados pelo Wan2GP durante o mux.

    Arquivos transitórios conhecidos em outputs/:
      *_tmp.mp4  — vídeo sem áudio gravado antes do mux (wgp.py L6969/L5230)
      tmp*.wav   — áudio interno do LTX2/MMAudio gravado antes do mux
                   (wgp.py L6987-6988: tmp{time_flag}.wav, ex: tmp2026-05-12-23h36m10s.wav)
                   Existe por ~1-2s; deletado após combine_and_concatenate (L7009).

    Sem esse filtro, _wait_new_output detecta o tmp*.wav como "novo output",
    retorna antes do .mp4 final aparecer e falha com
    "Nenhum arquivo do tipo esperado (vídeo (.mp4))".
    """
    lower = name.lower()
    return (
        lower.endswith("_tmp.mp4")
        or (lower.startswith("tmp") and lower.endswith(".wav"))
    )


def _safe_mtime(path) -> float:
    """Retorna st_mtime do arquivo ou 0.0 se não existir (FileNotFoundError)."""
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def _wait_new_output(
    before: set,
    timeout: int = 60,
    job_id: str = None,
    job_start_time: float = None,
    require_suffix: str | list[str] | None = None,
    multi_window: bool = False,
) -> list:
    """Polling até aparecer arquivo novo ou timeout.
    Intervalo: 2s (mais responsivo que 3s anterior).

    Ignora arquivos transitórios via _is_transient_output():
      *_tmp.mp4  — vídeo sem áudio (mux em andamento)
      tmp*.wav   — áudio interno do LTX2/MMAudio (gravado antes do mux final)
    O arquivo final (sem _tmp, sem tmp*.wav) é gerado logo depois.

    require_suffix (opcional):
      Quando definido, só retorna arquivos com esse(s) sufixo(s).
      Aceita str (ex: ".mp4") ou lista (ex: [".mp4", ".mov", ".mkv"]).
      Arquivos com outras extensões (ex: .wav standalone do AI Soundtrack) são
      ignorados no polling e NÃO disparam retorno antecipado.
      Fix [PASSO10-WAV]: I2V + AI Soundtrack gera .wav antes do .mp4 →
      sem este filtro, _wait_new_output retorna o .wav e PASSO 10 falha.
      Fix [PASSO10-CONTAINER]: suporta múltiplos containers (mp4/mov/mkv).

    Fix B — file-size stability check:
      Quando candidatos são encontrados, aguarda 0.5s e verifica se o tamanho
      permanece igual e > 0. Arquivos ainda sendo escritos têm tamanho crescente
      ou zero → ignorados, polling continua normalmente.
      Latência extra: +0.5s apenas no ciclo em que o arquivo aparece (irrelevante
      frente a gerações de 40s–20min).

    Fix C3 — early exit por cancelamento:
      Se job_id for passado, verifica a cada ciclo se o job foi cancelado.
      Retorna [] imediatamente, liberando o _generation_lock sem esperar timeout.

    Fix T10-A — job_start_time gate (orphan rejection):
      Se job_start_time for passado, candidatos cujo mtime < job_start_time - 1.0s
      são ignorados e o polling continua. A tolerância de 1s cobre:
        - Latência de escrita em NTFS
        - Discrepâncias de clock entre processos
      Arquivos legítimos aparecem sempre DEPOIS de PASSO 9 (≥10s após lock),
      portanto nunca são rejeitados erroneamente.

    Fix COMPAT — fatal log scan:
      A cada ~10s, verifica wan2gp.log para erros fatais de Triton/SageAttention.
      Se encontrado, marca o job como "error" e retorna [] imediatamente.
      Evita polling infinito em GPUs incompatíveis (RTX 20xx).
    """
    elapsed = 0
    interval = 0.5  # [C4-PERF] reduzido de 2 → 0.5 (build25: 4x mais responsivo)
    mtime_floor = (job_start_time - 1.0) if job_start_time is not None else None
    _log_scan_interval = 10  # verificar log a cada ~10s (20 ciclos a 0.5s)
    # [FIX-LOG-ANCHOR] Marcar posição do log no início do job — só escanear linhas NOVAS.
    # Sem isso, erros de sessões anteriores (ex: "Value: not in choices" de jobs anteriores)
    # disparam false-positive no scan e matam o job imediatamente após ~10s de PASSO 10.
    try:
        _log_anchor = _WAN2GP_LOG_PATH.stat().st_size if _WAN2GP_LOG_PATH.exists() else 0
    except Exception:
        _log_anchor = 0

    # [B39-BLOCK-001] Watchdog separado para Download On Demand.
    # Enquanto há download DOD ativo (modelo baixando), o tempo NÃO é contado contra
    # o budget de geração (`elapsed`/`timeout`). Isso evita falso timeout de 1200s na
    # primeira geração de cada família em instalação limpa (DOD de vários GB).
    #   - _DL_MAX_S:   limite total de download (cobre modelos ~18GB em rede lenta)
    #   - _DL_STALL_S: se o download NÃO avançar por este tempo → falha controlada
    # [B39-BLOCK-003] Regra de produto: o timeout de GERAÇÃO não pode contar enquanto
    # o sistema baixa modelo necessário (incl. modelos de máscara sam/matanyone que
    # baixam ANTES do modelo principal). Separa TEMPO DE PAREDE de TEMPO EFETIVO DE
    # GERAÇÃO: enquanto download ativo (ou dentro do grace pós-download), 'elapsed' NÃO
    # incrementa. Grace cobre os gaps entre modelos e o carregamento inicial. Um stall
    # separado (bytes congelados) detecta download realmente travado, com mensagem própria.
    _DL_MAX_S   = 7200    # 2h máximo de download total (cobre ~18GB em rede lenta)
    _DL_STALL_S = 900     # 15min sem AVANÇO de bytes = download travado (não "geração travada")
    _DL_GRACE_S = 60.0    # grace pós-download antes de voltar a contar timeout de geração
    _dl_elapsed = 0.0     # tempo acumulado em estado de download
    _dl_last_mb = -1.0    # último downloaded_mb visto
    _dl_stall   = 0.0     # tempo sem progresso real de bytes
    _dl_grace   = 0.0     # grace remanescente após o último download ativo

    def _gen_watch_tick() -> str:
        """Decide se o ciclo conta contra o budget de geração.
        Retorna: 'abort' (download morto/excedido — job já marcado erro),
                 'downloading' (pausar — NÃO contar elapsed), 'count' (contar elapsed)."""
        nonlocal _dl_elapsed, _dl_last_mb, _dl_stall, _dl_grace
        _dl = _read_dl_progress()
        if _dl and _dl.get("active"):
            _dl_grace = _DL_GRACE_S
            _dl_elapsed += interval
            _cur_mb = _dl.get("downloaded_mb", 0) or 0
            if _cur_mb > _dl_last_mb + 0.5:      # avançou ≥0.5MB → progresso real
                _dl_last_mb = _cur_mb
                _dl_stall   = 0.0
            else:
                _dl_stall  += interval
            if _dl_stall >= _DL_STALL_S:
                if job_id and job_id in jobs:
                    _msg = ("O download do modelo está muito lento ou foi interrompido. "
                            "Verifique sua conexão de internet e tente novamente.")
                    jobs[job_id]["status"] = "error"
                    jobs[job_id]["error"]  = _msg
                    jobs[job_id]["_abort_dod"] = _msg   # [B39-BLOCK-003] caller usa msg de conexão (não timeout)
                print(f"[ACS API] job {job_id} | DOD travado {int(_dl_stall)}s sem progresso de bytes — abortando")
                return "abort"
            if _dl_elapsed >= _DL_MAX_S:
                if job_id and job_id in jobs:
                    _msg = "O download do modelo excedeu o tempo máximo permitido (2h)."
                    jobs[job_id]["status"] = "error"
                    jobs[job_id]["error"]  = _msg
                    jobs[job_id]["_abort_dod"] = _msg   # [B39-BLOCK-003] caller usa esta msg, não o timeout genérico
                print(f"[ACS API] job {job_id} | DOD excedeu {_DL_MAX_S}s — abortando")
                return "abort"
            if int(_dl_elapsed) % 20 == 0:
                print(
                    f"[ACS API] baixando modelo... {int(_dl_elapsed)}s "
                    f"(DOD ativo — geração PAUSADA) "
                    f"{_cur_mb:.0f}/{_dl.get('total_mb', 0):.0f}MB"
                )
            return "downloading"
        if _dl_grace > 0:
            _dl_grace -= interval         # grace pós-download / ponte entre modelos
            return "downloading"
        return "count"

    while elapsed < timeout:
        # Fix C3: sair imediatamente se o job foi cancelado — libera o lock
        if job_id and jobs.get(job_id, {}).get("status") == "cancelled":
            print(f"[ACS API] job {job_id} | _wait_new_output abortado por cancelamento")
            return []

        # Fix GRADIO-ERR: sair imediatamente se _wait_gradio_signal detectou erro Wan2GP
        # (OOM, invalid param, etc.) — evita polling de 1200s quando nenhum arquivo virá.
        if job_id and jobs.get(job_id, {}).get("_abort_passo10"):
            print(f"[ACS API] job {job_id} | _wait_new_output abortado por erro Gradio/Wan2GP")
            return []

        # Fix COMPAT: verificar wan2gp.log para erros fatais a cada ~10s
        # [FIX-LOG-ANCHOR] Passa offset inicial para ignorar erros de sessões anteriores
        if elapsed > 0 and elapsed % _log_scan_interval == 0:
            _fatal = _scan_log_for_fatal_errors(log_start_offset=_log_anchor)
            if _fatal:
                print(f"[ACS COMPAT] job {job_id} | ERRO FATAL no log: {_fatal}")
                if job_id and job_id in jobs:
                    jobs[job_id]["status"] = "error"
                    jobs[job_id]["error"] = _fatal
                return []

        current = _snapshot_outputs()
        new = current - before
        real_new = {f for f in new if not _is_transient_output(f)}
        if real_new:
            # Fix T10-A: rejeitar arquivos cujo mtime seja anterior ao início do job
            if mtime_floor is not None:
                before_gate = {f for f in real_new if _safe_mtime(OUTPUTS_DIR / f) < mtime_floor}
                if before_gate:
                    print(
                        f"[ACS API] job {job_id} | T10-A: {len(before_gate)} orphan(s) ignorado(s) "
                        f"(mtime < {mtime_floor:.3f}): {before_gate}"
                    )
                real_new -= before_gate
            if real_new:
                # [PASSO10-WAV] Fix: filtrar por extensão esperada antes do check de estabilidade.
                # Se require_suffix definido, ignorar arquivos com outra extensão (ex: .wav
                # standalone do AI Soundtrack que aparece antes do .mp4 final).
                # Polling continua até o arquivo com o sufixo correto aparecer.
                if require_suffix:
                    # [PASSO10-CONTAINER] require_suffix pode ser str ou list[str]
                    _accepted = (
                        {require_suffix.lower()} if isinstance(require_suffix, str)
                        else {s.lower() for s in require_suffix}
                    )
                    suffix_filtered = {f for f in real_new
                                       if Path(f).suffix.lower() in _accepted}
                    if not suffix_filtered:
                        # Novos arquivos existem mas nenhum tem o sufixo esperado — continua polling
                        skipped_types = {Path(f).suffix.lower() for f in real_new}
                        print(
                            f"[ACS API] job {job_id} | PASSO10-WAV: {len(real_new)} novo(s) ignorado(s) "
                            f"(sufixos aceitos={_accepted}, tipos encontrados={skipped_types}) "
                            f"— aguardando {_accepted} ..."
                        )
                        time.sleep(interval)
                        # [B39-BLOCK-003] respeitar pausa de download também neste ramo
                        _st = _gen_watch_tick()
                        if _st == "abort":
                            return []
                        if _st == "count":
                            elapsed += interval
                        continue
                    real_new = suffix_filtered

                # Fix B: verificar estabilidade de tamanho antes de aceitar
                stable = set()
                for f in real_new:
                    try:
                        size1 = (OUTPUTS_DIR / f).stat().st_size
                        time.sleep(0.5)
                        size2 = (OUTPUTS_DIR / f).stat().st_size
                        if size1 == size2 and size1 > 0:
                            stable.add(f)
                    except FileNotFoundError:
                        pass  # arquivo transitório que sumiu entre os dois checks — ignorar
                if stable:
                    if multi_window:
                        # [MULTI-CENA] NÃO retorna na 1ª janela (sliding window salva progressivo:
                        # 3s,6s,9s...15s). Espera o Gradio sinalizar conclusão TOTAL e então pega o
                        # arquivo MAIOR (= vídeo final concatenado de todas as cenas). Sem isto o
                        # polling "vencia" e pegava a cena 1 (3s) — bug do Story AV multi-cena.
                        if job_id and jobs.get(job_id, {}).get("_gradio_done"):
                            def _sz(f):
                                try: return (OUTPUTS_DIR / f).stat().st_size
                                except Exception: return 0
                            best = max(stable, key=_sz)
                            print(f"[ACS API] job {job_id} | MULTI-CENA: {len(stable)} janelas salvas, "
                                  f"pegando o MAIOR (final): {best}")
                            return [best]
                        # gradio ainda gerando próximas janelas — continua polling
                    else:
                        return sorted(stable)
                # tamanho instável ou 0 em todos os candidatos — continua polling
        time.sleep(interval)

        # [B39-BLOCK-003] Decisão única de timing: pausa 100% durante download (incl.
        # gaps entre modelos via grace). Bookkeeping de download/stall/max no helper.
        _st = _gen_watch_tick()
        if _st == "abort":
            return []
        if _st == "downloading":
            continue                   # NÃO incrementa 'elapsed' — budget preservado
        # _st == "count": sem download ativo e fora do grace → watchdog normal
        elapsed += interval
        if elapsed % 20 == 0:
            print(f"[ACS API] aguardando output... {elapsed}s/{timeout}s")
    # [MULTI-CENA] fallback no timeout: se o Gradio nunca sinalizou mas há janelas salvas,
    # devolve o MAIOR arquivo novo (vídeo final) em vez de vazio.
    if multi_window and job_id:
        _final_new = {f for f in (_snapshot_outputs() - before) if not _is_transient_output(f)}
        if require_suffix:
            _acc = {require_suffix.lower()} if isinstance(require_suffix, str) else {s.lower() for s in require_suffix}
            _final_new = {f for f in _final_new if Path(f).suffix.lower() in _acc}
        if _final_new:
            def _sz2(f):
                try: return (OUTPUTS_DIR / f).stat().st_size
                except Exception: return 0
            return [max(_final_new, key=_sz2)]
    return []


# ── [FIX-PROMPT] Sanitiza caracteres invisíveis que quebram o streaming do Gradio ──
# U+2028/U+2029/U+0085/U+000B/U+000C são "quebras de linha" para str.splitlines() do
# Python. O gradio_client faz parsing do SSE linha-a-linha (client.py:stream_messages);
# esses chars partem o JSON no meio → "Unterminated string" → validate_wizard_prompt e
# save_inputs falham → "deu erro" ao gerar. Vêm colados ao copiar prompt de site/Word.
# Também causam o "charmap codec can't encode  " ao salvar o payload (cp1252).
# Troca por '\n' (seguro em cp1252); separadores de controle viram espaço; BOM removido.
_PROMPT_BAD_CHARS = {0x2028: "\n", 0x2029: "\n", 0x0085: "\n",
                     0x000B: "\n", 0x000C: "\n", 0x001C: " ",
                     0x001D: " ", 0x001E: " ", 0x001F: " ", 0xFEFF: ""}

def _sanitize_prompt(s):
    """Remove caracteres invisíveis que quebram o SSE/JSON do Gradio. Idempotente."""
    if not isinstance(s, str):
        return s
    return s.translate(_PROMPT_BAD_CHARS)


def _generate_background(job_id: str, req: GenerateRequest):
    """
    Executa o fluxo completo de geração via API Gradio.
    9 passos que reproduzem o botão GERAR do Wan2GP.

    Fluxo mapeado de wgp.py (engenharia reversa):
      generate_btn.click → init_generate
      generate_trigger.change → validate_wizard_prompt → save_inputs
        → process_prompt_and_add_tasks → prepare_generate_video
        → process_tasks (geração real)
    """
    # [FIX-PROMPT] limpa   e afins ANTES de qualquer chamada Gradio (quebram o JSON)
    try:
        req.prompt = _sanitize_prompt(req.prompt)
        if getattr(req, "negative_prompt", None):
            req.negative_prompt = _sanitize_prompt(req.negative_prompt)
    except Exception as _e:
        print(f"[ACS API] [FIX-PROMPT] aviso ao sanitizar: {_e}")

    # [WANSESSION-B] Caminho novo NÃO desvia mais aqui no topo. Ele deixa a função
    # montar o _save_kw COMPLETO (122 campos) e desvia logo depois (antes do submit
    # Gradio), com o client em modo stub. Paridade total, reaproveitando a lógica.

    def _step(step: str, progress: int):
        jobs[job_id]["step"] = step
        jobs[job_id]["progress"] = progress
        print(f"[ACS API] job {job_id} | {step}")

    def _fail(msg: str, exc: Exception = None, error_code: str = ""):
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = f"{msg}: {exc}" if exc else msg
        if error_code:
            jobs[job_id]["error_code"] = error_code  # [ETAPA-2] código estruturado para o frontend
        print(f"[ACS API] ERRO job {job_id}: {msg}" + (f" — {exc}" if exc else ""))
        # [F11 SELF-LEARNING] o ACS APRENDE com o erro (nao so registra): assina, compara, sabe se ja aconteceu
        try:
            import acs_self_learning as _sl
            _sl.learn(jobs[job_id]["error"], model=getattr(req, "model", ""), build="Build48")
        except Exception:
            pass
        # ── ACS Logger: registra o erro estruturado (fail-safe) ───────────────
        if _LOG_ENABLED:
            try:
                _stage = "GENERATE_IMAGE" if req.generation_mode in ("t2i",) else "GENERATE_VIDEO"
                _acs_log.log(
                    stage=_stage,
                    level="ERROR",
                    message_friendly=f"Erro na geração: {msg}",
                    message_tech=f"{msg}: {exc}" if exc else msg,
                    exc=exc,
                    job_id=job_id,
                )
            except Exception:
                pass  # NUNCA propagar — o log não pode travar a geração
        # ─────────────────────────────────────────────────────────────────────

    _lock_acquired = False  # flag para finally saber se precisa liberar o lock

    try:
        # ── Resolve modelo ────────────────────────────────────
        model_info = MODELS.get(req.model)
        if not model_info:
            _fail(f"Modelo desconhecido: {req.model}")
            return

        # [FIX-API-01] Bloquear modelos desabilitados antes de enfileirar
        if model_info.get("disabled", False):
            _fail(f"Modelo '{req.model}' está desabilitado nesta versão e não pode ser usado.")
            return

        # [FIX-API-02 / ETAPA-2] Distingue "inexistente" de "não instalado":
        #   inexistente      → installed=False, download_on_demand=False/absent
        #                       Wan2GP não tem .lock file → auto-download impossível
        #                       BLOQUEIA: retorna erro "model_not_installed"
        #   nao_instalado    → installed=False, download_on_demand=True
        #                       Wan2GP tem .lock file → auto-download no 1º uso
        #                       PERMITE: PASSO 9 roda com timeout 3600s
        if model_info.get("installed") is False:
            if not model_info.get("download_on_demand", False):
                _fail(
                    f"Modelo '{req.model}' não está disponível nesta instalação. "
                    f"Download necessário (~{model_info.get('download_gb', '?')} GB) — "
                    f"reinstale o ACS ou aguarde versão futura.",
                    error_code="model_not_installed",
                )
                return
            # download_on_demand=True → continua; Wan2GP fará download automático

        family      = model_info["family"]
        base_type   = model_info["base_type"]
        model_id    = model_info["model_id"]
        image_mode  = model_info["image_mode"]
        # [SCAIL2-LIGHTX2V 06-28] ENGENHARIA REVERSA do vídeo REAL do Luigi (settings gravados no mp4
        # do DEV): scail2 rápido E bom = lora LIGHTX2V cfg-step-distill rank64 + 4 passos + guidance 1
        # + sample_solver unipc. (A FusionX anterior era acelerador de wan i2v COMUM, incompatível com
        # a arquitetura scail2 → deixava rápido mas LIXO. A lightx2v é a certa, destila em 4 passos.)
        if base_type == "scail2_14B":
            _lx2v = "Wan21_I2V_14B_lightx2v_cfg_step_distill_lora_rank64.safetensors"
            _cur_loras = list(getattr(req, "loras_choices", None) or [])
            if _lx2v not in _cur_loras:
                _mult = str(getattr(req, "loras_multipliers", "") or "").strip()
                _cur_loras.append(_lx2v)
                req.loras_choices     = _cur_loras
                req.loras_multipliers = (_mult + " 1").strip() if _mult else "1"
            req.steps          = 4
            req.guidance_scale = 1.0
            try: req.sample_solver = "unipc"
            except Exception: pass
            if not getattr(req, "ctrl_video_prompt_type", ""):
                req.ctrl_video_prompt_type = "V1"
            print("[ACS API] [SCAIL2] lightx2v + 4 passos + guidance 1 + unipc + video_guide (= config do Gradio do Luigi)")
        # [TALKING-FUSIONX] Multitalk/Infinitetalk auto-aplicam a FusionX (mesmo acelerador wan i2v):
        # 8 passos + guidance 1 = muito mais rapido (era ~15min/3.88s). FusioniX/Causvid = aceleradores wan oficiais.
        elif base_type in ("multitalk", "infinitetalk"):
            _fx_lora = "Wan2.1_I2V_14B_FusionX_LoRA.safetensors"
            _cur_loras = list(getattr(req, "loras_choices", None) or [])
            if _fx_lora not in _cur_loras:
                _mult = str(getattr(req, "loras_multipliers", "") or "").strip()
                _cur_loras.append(_fx_lora)
                req.loras_choices     = _cur_loras
                req.loras_multipliers = (_mult + " 1").strip() if _mult else "1"
            req.steps          = 8
            req.guidance_scale = 1.0
            print(f"[ACS API] [TALKING-FUSIONX] acelerador aplicado: {_fx_lora} + 8 passos + guidance 1")
        # [STORY-AV 06-28] JoyAI-Echo (ltx2): a lora VBVR (Ltx2.3-Licon-VBVR-I2V-96000-R32) E o "MOTION
        # INTELLIGENCE" do modelo — ESSENCIAL, nao acelerador opcional (info do Luigi). + 8 passos + guidance 1.
        # Metadata verificada do mp4 do Luigi: num_inference_steps=8, guidance_scale=1.0, activated_loras=VBVR,
        # multi_prompts_gen_type=PW (PW ja tratado em L5466). Lora em loras/ltx2 (copiada do DEV).
        elif base_type == "joyai_echo":
            _vbvr = "Ltx2.3-Licon-VBVR-I2V-96000-R32.safetensors"
            _cur_loras = list(getattr(req, "loras_choices", None) or [])
            if _vbvr not in _cur_loras:
                _mult = str(getattr(req, "loras_multipliers", "") or "").strip()
                _cur_loras.append(_vbvr)
                req.loras_choices     = _cur_loras
                req.loras_multipliers = (_mult + " 1").strip() if _mult else "1"
            req.steps          = 8
            req.guidance_scale = 1.0
            # [STORY-AV-ALIGN 2026-07-04] alinhar com o gabarito Gradio (joyai_echo defaults via view_api):
            # audio_guidance_scale 1.0 (ACS mandava 4). guidance_phases=1 via _get_guidance_phases (memoria).
            req.audio_guidance_scale = 1.0
            print("[ACS API] [STORY-AV] VBVR motion intelligence + 8 passos + guidance 1 + audio_guid 1.0 (= config do Gradio do Luigi)")
        # sample_solver: varia por família no Wan2GP 11.77:
        #   - flux/z_image/flux2: choices inclui "" → padrão seguro → usar ""
        #   - wan/multitalk/infinitetalk/wan2_2/hunyuan: choices=['euler','heun','pingpong'] → "" inválido
        #   - ltx2/ltx SEM LoRA: PASSO 4.5 reseta choices=[''] → usar ""
        #   - ltx2/ltx COM IC-LoRA: Wan2GP 11.77 muda choices=['euler','heun','pingpong']
        #     → "" inválido → usar "euler" [FIX-LTX-LORA]
        # Pode ser sobrescrito por model_info["sample_solver"] para modelos específicos.
        _has_lora = bool(getattr(req, "loras_choices", None))
        _ltx_with_lora = family in {"ltx2", "ltx"} and _has_lora

        # [FIX-API-03 / LORA-DOD] Verificar existência dos arquivos LoRA + download on-demand
        # Fluxo para cada LoRA solicitado:
        #   1. Arquivo existe no disco → continua normalmente
        #   2. Arquivo ausente + URL em _LORAS_URL_CACHE → download streaming com progresso
        #      status="downloading_lora" visível via /status; após download → continua geração
        #   3. Arquivo ausente + sem URL → _fail(error_code="lora_not_installed")
        # GARANTE: Wan2GP nunca recebe LoRA ausente — sem falha silenciosa.
        if _has_lora:
            _lora_folder = (
                LORA_DIR_MAP.get(model_id)
                or LORA_DIR_MAP.get(family)
                or model_id
            )
            _lora_dir = LORAS_DIR / _lora_folder

            for _lora_fn in list(req.loras_choices or []):
                if not _lora_fn:
                    continue
                _lora_path = _lora_dir / _lora_fn
                if _lora_path.exists():
                    continue  # LoRA presente no disco — sem acção

                # LoRA ausente: verificar URL de download no cache
                # Chave no cache usa separador Windows (backslash) conforme loras_url_cache.json
                _cache_key_win  = f"loras\\{_lora_folder}\\{_lora_fn}"
                _cache_key_unix = f"loras/{_lora_folder}/{_lora_fn}"
                _dl_url = (
                    _LORAS_URL_CACHE.get(_cache_key_win)
                    or _LORAS_URL_CACHE.get(_cache_key_unix)
                )
                _cap        = LORA_CAPABILITIES.get(_lora_fn, {})
                _commercial = _cap.get("commercial_name", _lora_fn)

                if not _dl_url:
                    _fail(
                        f"LoRA '{_commercial}' não está instalado e não tem URL de download conhecida. "
                        f"Por favor reinstale o ACS Studio.",
                        error_code="lora_not_installed",
                    )
                    return

                # ─── Download on-demand ─────────────────────────────────────────
                _lora_dir.mkdir(parents=True, exist_ok=True)
                _tmp_path  = _lora_path.with_suffix(".tmp")
                _dl_start  = time.time()
                print(f"[ACS API] [LORA-DOD] Iniciando download: '{_lora_fn}'")
                print(f"[ACS API] [LORA-DOD] URL: {_dl_url}")

                try:
                    with httpx.stream(
                        "GET", _dl_url,
                        follow_redirects=True,
                        timeout=httpx.Timeout(connect=30.0, read=None, write=None, pool=None),
                    ) as _resp:
                        _resp.raise_for_status()
                        _total_b = int(_resp.headers.get("content-length", 0))
                        _total_gb = _total_b / 1e9 if _total_b else 0
                        _done    = 0

                        with open(_tmp_path, "wb") as _fh:
                            for _chunk in _resp.iter_bytes(chunk_size=1024 * 1024):  # 1 MB chunks
                                if not _chunk:
                                    continue
                                _fh.write(_chunk)
                                _done += len(_chunk)

                                # Verificar cancelamento durante download
                                if jobs[job_id].get("status") == "cancelled":
                                    print(f"[ACS API] [LORA-DOD] Download cancelado pelo usuário: {_lora_fn}")
                                    _tmp_path.unlink(missing_ok=True)
                                    return

                                # Actualizar progresso no job
                                _elapsed   = max(0.1, time.time() - _dl_start)
                                _speed_mbs = (_done / 1e6) / _elapsed
                                _pct       = int(_done * 100 / _total_b) if _total_b else 0
                                _eta_s     = int((_total_b - _done) / 1e6 / _speed_mbs) if (_total_b and _speed_mbs > 0) else 0
                                jobs[job_id]["status"]   = "downloading_lora"
                                jobs[job_id]["progress"] = max(2, _pct // 2)  # 0→50 durante download
                                jobs[job_id]["step"] = (
                                    f"Baixando LoRA '{_commercial}': {_pct}% "
                                    f"({_done/1e9:.2f}/{_total_gb:.2f} GB) "
                                    f"@ {_speed_mbs:.1f} MB/s"
                                    + (f" — ETA {_eta_s}s" if _eta_s > 0 else "")
                                )
                                # [B38-001] Campos estruturados para get_status() → frontend
                                jobs[job_id]["lora_dl_name"]    = _commercial
                                jobs[job_id]["lora_dl_pct"]     = _pct
                                jobs[job_id]["lora_dl_done_mb"] = round(_done / 1e6, 1)
                                jobs[job_id]["lora_dl_total_mb"]= round(_total_b / 1e6, 1) if _total_b else 0
                                jobs[job_id]["lora_dl_speed"]   = round(_speed_mbs, 2)
                                jobs[job_id]["lora_dl_eta_s"]   = _eta_s if _eta_s > 0 else None

                    # Download completo — rename atômico (.tmp → .safetensors)
                    _tmp_path.rename(_lora_path)
                    _dl_total_s = time.time() - _dl_start
                    _file_gb    = _lora_path.stat().st_size / 1e9
                    print(
                        f"[ACS API] [LORA-DOD] Download concluído: '{_lora_fn}' "
                        f"{_file_gb:.2f} GB em {_dl_total_s:.1f}s "
                        f"({_file_gb*1024/_dl_total_s:.1f} MB/s médio)"
                    )
                    jobs[job_id]["status"]   = "queued"
                    jobs[job_id]["step"]     = (
                        f"LoRA '{_commercial}' baixado ({_dl_total_s:.0f}s, {_file_gb:.2f} GB). "
                        f"Aguardando geração..."
                    )
                    jobs[job_id]["progress"] = 0

                except Exception as _dl_err:
                    _tmp_path.unlink(missing_ok=True)
                    _fail(
                        f"Falha ao baixar LoRA '{_commercial}': {_dl_err}",
                        error_code="lora_download_failed",
                    )
                    return
                # ─── fim download on-demand ────────────────────────────────────

        # ── LoRA Capabilities: auto-payload + validação de modo ───────────
        # Regra 1 — auto-payload (SOMENTE para LoRAs especiais com auto_payload_required=True):
        #   Aplica campos obrigatórios no req se ainda estiverem vazios.
        #   Ex: HDR IC-LoRA → inject_video_prompt_type="V&G"
        # Regra 2 — validação de modo:
        #   Bloqueia combos inválidos ANTES da geração.
        #   Ex: HDR IC-LoRA + modo t2v → erro claro.
        _req_mode = getattr(req, "generation_mode", "")  # "" para wrapper-mode implícito
        for _lora_fn in list(getattr(req, "loras_choices", []) or []):
            _cap = LORA_CAPABILITIES.get(_lora_fn)
            if not _cap:
                continue  # LoRA desconhecido → trata como normal, sem alteração
            # Regra 2: bloquear modo incompatível
            _incompat = _cap.get("incompatible_modes", [])
            if _req_mode and _req_mode in _incompat:
                _name = _cap.get("commercial_name", _lora_fn)
                _allowed = _cap.get("allowed_modes", [])
                _fail(
                    f"LoRA '{_name}' não é compatível com modo '{_req_mode}'. "
                    f"Modos suportados: {_allowed}. "
                    f"{'Motivo: ' + _cap.get('warning_message','') if _cap.get('warning_message') else ''}"
                )
                return
            # Regra 1: auto-payload para LoRAs especiais
            if _cap.get("auto_payload_required") and _cap.get("auto_payload"):
                for _k, _v in _cap["auto_payload"].items():
                    _current = getattr(req, _k, None)
                    if not _current:   # só aplica se campo vazio/None
                        try:
                            setattr(req, _k, _v)
                            print(f"[ACS API] LoRA auto-payload: {_lora_fn} → {_k}={_v!r}")
                        except Exception:
                            pass  # campo somente-leitura → ignora silenciosamente
        _WAN_EULER_FAMILIES = {"wan", "multitalk", "infinitetalk", "wan2_2", "hunyuan",
                               "hunyuan_1_5", "longcat", "magi_human"}
        _model_sample_solver = model_info.get(
            "sample_solver",
            "euler" if (family in _WAN_EULER_FAMILIES or _ltx_with_lora) else ""
        )

        # ── Resolve resolução ─────────────────────────────────
        # Aceita chave do mapa ("720p", "1:1") ou string direta ("1280x720", "720x1280")
        resolution = RESOLUTION_MAP.get(req.resolution, req.resolution)
        if image_mode == 1:
            # Imagem: normaliza apenas se alguma dimensão for menor que 512 (inválida).
            # Limite artificial max(w,h) > 2048 removido — Wan2GP suporta 2K/4K nativamente.
            if "x" in resolution:
                w, h = map(int, resolution.split("x"))
                if w < 512 or h < 512:
                    resolution = "1024x1024"
            elif "p" in resolution:
                resolution = "1024x1024"
        # Vídeo: usa a resolução como fornecida (já vem em formato WxH correto do frontend)

        # ── IMG-PERF: recupera T1 (timestamp de entrada do /generate endpoint) ──
        _t1 = jobs[job_id].get("t1_request", time.time())
        _is_image_job = (image_mode == 1)

        # Enquanto aguarda o lock: status amigável visível no frontend
        jobs[job_id]["status"]   = "queued"
        jobs[job_id]["step"]     = "Aguardando na fila..."
        jobs[job_id]["progress"] = 0
        print(f"[ACS API] job {job_id} | aguardando lock de geração")
        # [B38-LOCK-FIX] acquire com timeout — evita starvation quando outro job
        # (ex.: WAN preso em PASSO 10) retém o lock indefinidamente. Sem isto, o
        # job ficava em "queued" até o watchdog de 1200/3600s do job preso disparar.
        if not _generation_lock.acquire(timeout=20):
            _fail(
                "Sistema ocupado processando outra geração. Tente novamente em instantes.",
                error_code="generation_busy",
            )
            return
        _lock_acquired = True

        # Fix T10-A: registrar instante real de início (após lock) — usado como gate de mtime
        job_start_time = time.time()
        jobs[job_id]["job_start_time"] = job_start_time

        # ── [PERF-TIMER / IMG-PERF] Instrumentação T0-T17 ───────
        _perf_t0 = job_start_time
        _perf_prev_t = [job_start_time]
        _perf_prev_label = ["T_lock"]
        _perf_prefix = "[IMG-PERF]" if _is_image_job else "[PERF-TIMER]"
        def _perf_ts(label: str):
            now = time.time()
            delta = now - _perf_prev_t[0]
            total = now - _perf_t0
            print(f"{_perf_prefix} {_perf_prev_label[0]}->{label}: {delta:.3f}s | +lock={total:.3f}s")
            _perf_prev_t[0] = now
            _perf_prev_label[0] = label

        # ── IMG-PERF: closure de checkpoint absoluto ─────────────
        # Registra timestamp absoluto + delta do checkpoint anterior.
        _img_perf: dict = {}
        def _ip(label: str, extra: str = ""):
            if not _is_image_job:
                return
            now = time.time()
            _img_perf[label] = now
            keys = list(_img_perf.keys())
            delta_prev = (now - _img_perf[keys[-2]]) if len(keys) > 1 else 0.0
            total_lock = now - _perf_t0
            total_t1   = now - _t1
            print(f"[IMG-PERF] {label}: Δ={delta_prev:.3f}s | +lock={total_lock:.3f}s | +T1={total_t1:.3f}s{(' | '+extra) if extra else ''}")

        if _is_image_job:
            _lock_wait = job_start_time - _t1
            print(
                f"[IMG-PERF] START  job={job_id}"
                f"  model={req.model}  res={req.resolution}"
                f"  lock_wait={_lock_wait:.3f}s"
                f"  checkpoint_last={_LAST_LOADED_MODEL_ID.get('id','none')}"
            )
            _img_perf["T_lock"] = job_start_time
        else:
            print(f"[PERF-TIMER] START job={job_id} T1_lock_acquired")

        # T12-CP1: job cancelado enquanto aguardava na fila não deve iniciar geração
        if jobs[job_id].get("status") == "cancelled":
            print(f"[ACS API] job {job_id} | cancelado na fila — liberando lock")
            return

        jobs[job_id]["status"] = "running"
        _step("Iniciando geração...", 5)

        # [ERR-09] garante o motor bootado com o modelo certo (reinicia se trocou de família)
        _ensure_engine_model(model_id)

        # Snapshot tirado DENTRO do lock — garante que não há outro job gerando
        before = _snapshot_outputs()

        # ── Cria client isolado para este job ─────────────────
        # [WANSESSION-B] flag ON → stub no-op (não fala com Gradio); a geração é
        # feita pelo desvio WanGPSession após o _save_kw (122 campos completos).
        client = _StubGradioClient() if _USE_WANSESSION else new_client()
        _perf_ts("T2_new_client")

        # ────────────────────────────────────────────────────────
        # PASSO 1: Inicializar sessão
        # ────────────────────────────────────────────────────────
        _step("PASSO 1: browser_session_started", 8)
        try:
            client.predict(api_name="/browser_session_started")
        except Exception as e:
            print(f"[ACS API] browser_session_started aviso (não crítico): {e}")
        time.sleep(0.1)  # [C2-PERF] 0.5→0.1 — fire-and-forget state call
        _perf_ts("T3_passo1_browser")
        _ip("T2_browser_session_started")

        # ────────────────────────────────────────────────────────
        # PASSO 2: Selecionar família de modelos
        # ────────────────────────────────────────────────────────
        _step(f"PASSO 2: change_model_family('{family}')", 12)
        try:
            client.predict(family, api_name=_API_CHANGE_MODEL_FAMILY)
        except Exception as e:
            print(f"[ACS API] change_model_family aviso: {e}")
        time.sleep(0.1)  # [C2-PERF] 0.3→0.1 — state update, sem side-effects
        _perf_ts("T4_passo2_family")
        _ip("T3_change_model_family")

        # ────────────────────────────────────────────────────────
        # PASSO 3: Selecionar base type (Modo na UI)
        # ────────────────────────────────────────────────────────
        _step(f"PASSO 3: change_model_base_types('{family}', '{base_type}')", 16)
        try:
            client.predict(family, base_type, api_name=_API_CHANGE_BASE_TYPES)
        except Exception as e:
            print(f"[ACS API] change_model_base_types aviso: {e}")
        time.sleep(0.1)  # [C2-PERF] 0.3→0.1 — state update
        _perf_ts("T5_passo3_base_types")
        _ip("T4_change_model_base_types")

        # ────────────────────────────────────────────────────────
        # PASSO 4: Selecionar modelo específico → seta state["model_type"]
        # ────────────────────────────────────────────────────────
        # Monta video_prompt_type: ctrl video sempre vai para o início,
        # inject type correto para o modelo (ex: "KFI" para LTX2, "FI" para VACE).
        # Para modelos sem suporte a inject, _get_inject_video_prompt_type retorna "".
        # NOTA: para I2V o model_inject_type é calculado dentro de _build_i2v_params
        # (depois que mode_p está disponível). Por enquanto inicializa como str vazio.
        video_prompt_type = req.ctrl_video_prompt_type  # ctrl inject se houver; inject será adicionado depois

        # ── Resolve parâmetros por modo de geração ──────────────
        generation_mode = req.generation_mode  # "t2v"|"i2v"|"flf"|"continue"|"t2i"
        print(f"[ACS API] job {job_id} | modo={generation_mode} | ref={req.ref_image_path or 'none'} | end={req.end_image_path or 'none'}")

        # ── Valida refs obrigatórios por modo ─────────────────
        if generation_mode == "i2v" and not req.ref_image_path:
            _fail("Modo I2V requer imagem de referência (start frame). Faça upload na zona de referência.")
            return
        if generation_mode == "flf":
            if not req.ref_image_path:
                _fail("Modo FLF requer imagem inicial (start frame). Faça upload na zona de referência.")
                return
            if not req.end_image_path:
                _fail("Modo FLF requer imagem final (end frame). Faça upload na zona de referência.")
                return
        if generation_mode == "continue" and not req.ctrl_video_path:
            _fail("Modo Continue requer vídeo fonte. Faça upload na zona de referência.")
            return

        # ── Verifica se os arquivos existem ───────────────────
        for label, path in [
            ("ref",   req.ref_image_path),
            ("end",   req.end_image_path),
            ("ctrl",  req.ctrl_video_path),
            ("audio", req.audio_path),
        ]:
            if path and not Path(path).exists():
                _fail(f"Arquivo {label} não encontrado: {path}")
                return

        # [KI-018] ctrl_video_path com flag de controlo DEVE ser vídeo (MP4/WebM/MOV).
        # Passar JPG/PNG como ctrl_video com flags EVG/DVG/PVG/OVG/VG/V&G causa
        # save_inputs falha: Wan2GP video_guide component rejeita formato não-video.
        _VIDEO_CTRL_EXTS = {".mp4", ".webm", ".mov"}
        if req.ctrl_video_path and req.ctrl_video_prompt_type:
            _ctrl_ext = Path(req.ctrl_video_path).suffix.lower()
            if _ctrl_ext not in _VIDEO_CTRL_EXTS:
                _fail(
                    f"ctrl_video_path deve ser um vídeo MP4/WebM/MOV quando ctrl_video_prompt_type está definido. "
                    f"Extensão recebida: '{_ctrl_ext}'. "
                    f"Imagens (JPG/PNG) não são suportadas como Ctrl Video — forneça um vídeo gerado."
                )
                return

        # [FIX-OVG] OVG (Pose Align) usa o preprocessor "pose_align" (wgp.py:4241
        # process_map "O"->"pose_align") que EXIGE um sujeito de referência para
        # alinhar (ref_pose_tensor, wgp.py:6977). Em t2v puro (sem ref) não há alvo
        # → o Wan2GP trava silenciosamente (sem output, sem log, ~600s). Confirmado
        # por teste: OVG roda OK em i2v+referência. Bloqueio com mensagem clara.
        # PVG (Human Motion, "pose") funciona normalmente em t2v.
        if req.ctrl_video_prompt_type == "OVG" and not req.ref_image_path:
            _fail(
                "OVG (Pose Align) requer modo Imagem→Vídeo com imagem de referência "
                "(a pessoa a ser animada). Para texto→vídeo use PVG (Movimento Humano), "
                "ou adicione uma imagem de referência."
            )
            return

        # ── Monta parâmetros de modo via builders ──────────────
        # Cada builder retorna: image_prompt_type, image_start_param,
        # image_end_param, video_source_param, input_video_strength, gallery_tab
        builder = _MODE_BUILDERS.get(generation_mode, _build_t2v_params)
        mode_p  = builder(req)

        image_prompt_type_param    = mode_p["image_prompt_type"]
        image_start_param          = mode_p["image_start_param"]
        image_end_param            = mode_p["image_end_param"]
        video_source_param         = mode_p["video_source_param"]
        input_video_strength_param = mode_p["input_video_strength"]
        gallery_tab                = mode_p["gallery_tab"]

        # ── Image refs e video_prompt_type final ──────────────────
        # Regras por modo:
        # - I2V: _build_i2v_params determina o model_inject_type correto (ex: "KFI")
        #   image_refs já estão em mode_p["image_refs_param"]
        # - T2V + inject: usa paths de ref_inject_paths; inject type é model-specific
        # - FLF: sem inject → image_refs vazio
        # - Continue/T2I: sem inject

        _computed_vl = _seconds_to_video_length(req.duration, req.model)

        if generation_mode == "i2v":
            # model_inject_type vem do builder (já computado em _build_i2v_params)
            model_inject_type = mode_p.get("model_inject_type", "")
            image_refs_param  = mode_p["image_refs_param"]
            # video_prompt_type = inject_type + ctrl_type
            video_prompt_type = model_inject_type + req.ctrl_video_prompt_type

            # Inject foi pedido mas modelo não suporta → erro amigável
            if req.inject_video_prompt_type and req.ref_inject_paths and not model_inject_type:
                _fail(f"Frame Injection não suportado neste modelo ({req.model}). "
                      f"Use Cinematic Pro 1.1 ou Cinematic Pro Full para injeção de frames.")
                return

        elif (generation_mode == "t2v" and req.inject_video_prompt_type and req.ref_inject_paths
              and model_info.get("base_type") != "ltx2_22B_msr"):
            # T2V + inject: determina o tipo correto para o modelo
            # [MSR-BRANCH-ORDER 2026-07-03] guard != ltx2_22B_msr: o frontend do MSR auto-ativa o
            # addon frame-inj -> envia inject_video_prompt_type="KI", o que sequestrava o MSR para
            # ESTE branch (montava video_prompt_type="KFI"+frames_positions). Sem o guard, o branch
            # MSR abaixo (base_type==ltx2_22B_msr) NUNCA era alcancado. Com o guard, o MSR cai no
            # branch dele e monta "KI" puro (= gabarito Gradio: KI, sem F, sem frames_positions).
            model_inject_type = _get_inject_video_prompt_type(req.model)
            if model_inject_type:
                paths = req.ref_inject_paths if req.ref_inject_paths else (
                    [req.ref_image_path] if req.ref_image_path else []
                )
                image_refs_param = [_wrap_gallery_item(p) for p in paths if p]
                video_prompt_type = model_inject_type + req.ctrl_video_prompt_type
            else:
                # Modelo não suporta inject → erro amigável
                _fail(f"Frame Injection não suportado neste modelo ({req.model}). "
                      f"Use Cinematic Pro 1.1 ou Cinematic Pro Full para injeção de frames.")
                return
            model_inject_type = _get_inject_video_prompt_type(req.model) if image_refs_param else ""

        elif generation_mode == "t2i" and req.inject_video_prompt_type and req.ref_inject_paths:
            # T2I + inject (Image tab): Flux2 usa flag direta da UI ("KI"/"I")
            # via image_refs nativo do Flux Klein/Kontext.
            model_inject_type = _get_inject_video_prompt_type(req.model, req.inject_video_prompt_type)
            if not model_inject_type:
                _fail(f"Reference Images não suportado neste modelo ({req.model}). "
                      f"Use Flux Fast, Flux Balanced ou Flux Cinematic.")
                return
            image_refs_param = [_wrap_gallery_item(p) for p in req.ref_inject_paths if p]
            video_prompt_type = model_inject_type + req.ctrl_video_prompt_type
        else:
            # [12.24] modelos de edição por referência (EditAnything/Bernini, needs_image_ref):
            # a imagem de referência vai em image_refs (senão "must provide Image Reference").
            if MODELS.get(req.model, {}).get("needs_image_ref") and req.ref_inject_paths:
                image_refs_param = [_wrap_gallery_item(p) for p in req.ref_inject_paths if p]
            else:
                image_refs_param  = []
            model_inject_type = ""
            # Fix 2: PV/MV requerem ctrl_image_path (imagem de controle da aba Image).
            # ctrl_video_path é sempre vazio para jobs de imagem — não usar como check.
            # Sem imagem de controle → falha imediata em vez de timeout 600s no PASSO 10.
            if image_mode == 1 and req.ctrl_video_prompt_type in ("PV", "MV") and not req.ctrl_image_path:
                _mode = {"PV": "Transfer Human Pose", "MV": "Perform Inpainting"}.get(
                            req.ctrl_video_prompt_type, req.ctrl_video_prompt_type)
                _fail(f"Modo '{_mode}' requer imagem de controle. Adicione uma imagem de controle.")
                return
            video_prompt_type = req.ctrl_video_prompt_type

        # ── Calcula frames_positions para inject posicionado (flag "F") ──
        # Usado por LTX2 ("KFI") e VACE ("FI") que contêm "F" no inject type
        if image_refs_param and "F" in (video_prompt_type or ""):
            # [FIX-INJECT] Se o usuário forneceu posições manuais, usa-as (normaliza
            # vírgulas→espaços e ignora vazios). Senão, mantém o auto-equidistante.
            _user_pos = (req.frames_positions or "").replace(",", " ").split()
            if _user_pos:
                # [FIX-INDEX 2026-06-26] UI do ACS é 0-indexed (placeholder "0 24 48"); o motor
                # é 1-indexed (1=1º frame, L=último; ltx2 infos.py). Manual "0" dava
                # "Invalid Frame Position Value '0'". Converte +1; preserva "L"/"l".
                def _to_1idx(p):
                    if p.lower() == "l":
                        return "L"
                    try:
                        return str(int(p) + 1)
                    except ValueError:
                        return p
                frames_positions_val = " ".join(_to_1idx(p) for p in _user_pos)
                print(f"[FIX-INJECT] frames_positions manual (0idx->1idx): '{frames_positions_val}' "
                      f"(imgs={len(image_refs_param)}, video_length={_computed_vl})")
            else:
                frames_positions_val = _compute_frames_positions(
                    n_frames=len(image_refs_param),
                    video_length=_computed_vl,
                )
        else:
            frames_positions_val = ""

        # Áudio — resolução final dos parâmetros
        audio_guide_param       = _wrap_file(req.audio_path) if req.audio_path else None
        audio_prompt_type_param = req.audio_prompt_type or ""

        # ── [AUDIO PIPELINE] log ──────────────────────────────
        # M2-FIX: "B" = dual-speaker MultiTalk (2 áudios separados, um por falante)
        # Antes: "B" não estava mapeado → mux_mode/audio_output_mode aparecia como "none"
        # nas logs de jobs dual-speaker — confuso e parecia indicar erro.
        _apt = audio_prompt_type_param
        _mux = (
            "ai_generated"           if (_apt == "" and not req.audio_source_path) else
            "passthrough"            if (_apt == "A")   else
            "dual_speaker_multitalk" if (_apt == "B")   else   # M2-FIX
            "voice_id_lora"          if (_apt == "A1OF") else
            "ctrl_audio"             if (_apt == "K")   else
            "ctrl_gen_audio"         if (_apt == "2")   else
            "ffmpeg_direct"          if req.audio_source_path else
            "none"
        )
        _ao = (
            "ai_soundtrack"       if (_apt == "" and not req.audio_source_path) else
            "passthrough_mp3"     if (_apt == "A" and req.audio_path) else
            "dual_speaker_guided" if (_apt == "B" and req.audio_path and req.audio_path2) else  # M2-FIX
            "voice_lora_gen"      if (_apt == "A1OF") else
            "ctrl_audio_copy"     if (_apt == "K") else
            "ctrl_driven_gen"     if (_apt == "2") else
            "ffmpeg_mux"          if req.audio_source_path else
            "none"
        )
        print(
            f"\n[AUDIO PIPELINE] job {job_id}\n"
            f"  audio_prompt_type    = \"{_apt}\"\n"
            f"  audio_guide          = {req.audio_path or 'None'}\n"
            f"  audio_source         = {req.audio_source_path or 'None'}\n"
            f"  audio_scale          = {req.audio_scale}\n"
            f"  audio_guidance_scale = {req.audio_guidance_scale}\n"
            f"  mux_mode             = {_mux}\n"
            f"  audio_output_mode    = {_ao}\n"
            f"  model_supports_audio = {MODELS.get(req.model, {}).get('supports_audio', False)}\n"
        )

        _model_family = MODELS.get(req.model, {}).get("family", "unknown")

        # Log no formato padrão (debug técnico)
        print(f"[ACS API] job {job_id} | image_prompt_type='{image_prompt_type_param}' | gallery_tab={gallery_tab}"
              f" | start={'ok' if image_start_param else '--'}"
              f" | end={'ok' if image_end_param else '--'}"
              f" | video_source={'ok' if video_source_param else '--'}"
              f" | inject={model_inject_type or 'none'} n_refs={len(image_refs_param)}"
              f" | frames_positions='{frames_positions_val}'"
              f" | video_prompt_type='{video_prompt_type}'"
              f" | duration={req.duration}s -> video_length={_computed_vl}f")

        # Log Image Control (diagnóstico T2I — confirma se Control da aba Image
        # entrega ctrl_video_prompt_type + image_guide ao Wan2GP)
        if generation_mode == "t2i":
            _mi = MODELS.get(req.model, {})
            _image_guide_sent = bool(req.ctrl_image_path)
            print(f"[IMAGE CONTROL] job_id={job_id}"
                  f" | generation_mode=t2i"
                  f" | ctrl_video_prompt_type='{req.ctrl_video_prompt_type}'"
                  f" | ctrl_image_path_present={bool(req.ctrl_image_path)}"
                  f" | image_guide_sent={_image_guide_sent}"
                  f" | model={req.model}"
                  f" | base_type={_mi.get('base_type', '')}"
                  f" | family={_mi.get('family', 'unknown')}")

        # Log Frame Injection (formato legível / monitoramento)
        if image_refs_param and model_inject_type:
            _n_refs = len(image_refs_param)
            _out_expected = "single_video" if "F" in (video_prompt_type or "") else "style_refs"
            print(f"[FRAME INJECT] model_type={_model_family}"
                  f" | video_prompt_type={video_prompt_type}"
                  f" | number_of_image_refs={_n_refs}"
                  f" | frames_positions={frames_positions_val or 'none'}"
                  f" | generation_mode={generation_mode}"
                  f" | output_expected={_out_expected}")

        # ── PASSO 4: change_model ─────────────────────────────────
        # Usa submit() em vez de predict() para poder monitorar duração.
        # Se demorar > 15s: modelo sendo preparado pela primeira vez.
        # Se demorar > 120s: modelo sendo baixado do servidor.
        # Progresso mantido em 20 (honesto — sem percentual inventado).
        _step("Iniciando modelo...", 20)
        _perf_ts("T6_change_model_START")
        # ── IMG-PERF: checkpoint cache detection ─────────────────
        _cm_start_abs = time.time()
        _is_same_checkpoint = (_LAST_LOADED_MODEL_ID.get("id") == model_id)
        _time_since_last_load = _cm_start_abs - _LAST_LOADED_MODEL_ID.get("at", 0.0)
        if _is_image_job:
            print(
                f"[IMG-PERF] T_change_model_START  model_id={model_id}"
                f"  same_as_last={'YES' if _is_same_checkpoint else 'NO'}"
                f"  last_model={_LAST_LOADED_MODEL_ID.get('id', 'none')}"
                f"  time_since_last={_time_since_last_load:.1f}s"
            )
        try:
            _cm_job   = client.submit(model_id, api_name=_API_CHANGE_MODEL)
            jobs[job_id]["cm_job"] = _cm_job   # Fix C1: expõe future para /cancel
            _cm_start = time.time()
            while not _cm_job.done():
                _elapsed = time.time() - _cm_start
                if _elapsed > 120:
                    _step("Baixando modelo do servidor", 20)
                elif _elapsed > 15:
                    _step("Preparando modelo pela primeira vez...", 20)
                time.sleep(0.2)  # [C1-PERF] reduzido de 2 → 0.2 (igual ao staging)
            _cm_job.result()   # levanta excecao se Gradio reportou erro
            jobs[job_id].pop("cm_job", None)   # modelo carregado — future não mais necessário
        except Exception as e:
            print(f"[ACS API] ERRO TECNICO change_model job={job_id} model_id={model_id}: {e}")
            _fail("Erro ao preparar modelo", e)
            return
        _perf_ts("T7_change_model_DONE")
        # ── IMG-PERF: classificar resultado do change_model ──────
        _cm_elapsed = time.time() - _cm_start_abs
        _cache_result = (
            "CACHE_HIT"    if _cm_elapsed < 2.0 else
            "WARM_RELOAD"  if _cm_elapsed < 8.0 else
            "COLD_LOAD"
        )
        _LAST_LOADED_MODEL_ID["id"] = model_id
        _LAST_LOADED_MODEL_ID["at"] = time.time()
        if _is_image_job:
            print(
                f"[IMG-PERF] T_change_model_DONE  elapsed={_cm_elapsed:.3f}s"
                f"  result={_cache_result}"
                f"  same_checkpoint={_is_same_checkpoint}"
            )
        time.sleep(0.2)  # [C2-PERF] 0.5→0.2 — modelo já carregado, settle mínimo

        # ────────────────────────────────────────────────────────
        # NOTE: fill_inputs was tested here (PASSO 3.6) and proven INEFFECTIVE.
        # Gradio 4.x gr.update() returned by API calls does NOT persist server-side
        # component choices. The Dropdown choices for sample_solver remain [''] for
        # all sessions when Wan2GP was started with Flux (no sample_solvers).
        # ROOT FIX is in ltx2_handler.py validate_generative_settings:
        #   "" sample_solver → treated as "euler" for ltx2_22B dev model.
        # ────────────────────────────────────────────────────────
        # PASSO 4.5: change_resolution_group → garante que o dropdown de
        # resolução mostra o grupo correto antes do save_inputs.
        # Ex: "1024x1024" → grupo "720p"; "1920x1088" → grupo "1080p"
        # ────────────────────────────────────────────────────────
        res_group = _resolution_group(resolution)
        _step(f"PASSO 4.5: change_resolution_group('{res_group}')", 22)
        try:
            client.predict(res_group, api_name="/change_resolution_group")
        except Exception as e:
            print(f"[ACS API] change_resolution_group aviso (não crítico): {e}")
        time.sleep(0.1)  # [C2-PERF] 0.3→0.1 — state update
        _perf_ts("T8_passo45_res_group")
        _ip("T5_change_resolution_group")

        # ────────────────────────────────────────────────────────
        # PASSO 5: save_inputs → seta state["all_settings"][model_type]
        # CRÍTICO: usa submit().result() para bypassar validação client-side.
        # Todos os 110 parâmetros devem ser fornecidos com tipos exatos
        # conforme flux2_klein_9b_settings.json (int onde JSON tem int, etc.)
        # ────────────────────────────────────────────────────────
        # ── IMG-PERF T6: medir tempo de preparação/wrapping de imagens ─
        _t_preprocess = time.time()
        _step("PASSO 5: save_inputs (110 params)", 28)
        # ── ACS-ERR-0041: sample_solver resiliente ────────────────────────────
        # O Gradio valida sample_solver contra as choices do Dropdown ANTES de
        # executar save_inputs. Quando o modelo anterior tinha sample_solvers
        # definidos (ex: Wan → ['unipc','euler',...]) e o modelo atual tem
        # sample_solvers=None (ex: Flux), o Dropdown ainda mostra as choices
        # antigas. Enviando "" falha com "not in list of choices".
        # Fix: se o 1º attempt falhar por choice inválida, parseia as choices
        # do erro e reenvia com o valor mais adequado. Máximo 1 retry — sem loop.
        # ─────────────────────────────────────────────────────────────────────
        # [TURBOTIME] Ideogram v4 Turbo Time é DISTILLED no-guidance: o model def exige
        # guidance_scale=0, flow_shift=1.0, guidance_phases=0. O ACS mandava genéricos
        # (guidance=5, flow_shift=5) => imagem PRETA (NaN). Aqui forço os valores do model def
        # (igual ao Gradio nativo). Para os demais modelos nada muda.
        _img_guidance    = req.guidance_scale
        _img_flow_shift  = 5.0
        _img_guid_phases = (req.guidance_phases_override
                            if getattr(req, "guidance_phases_override", -1) > 0
                            else _get_guidance_phases(req.model))
        if model_info.get("base_type") == "ideogram4_turbotime":
            _img_guidance, _img_flow_shift, _img_guid_phases = 0.0, 1.0, 0
            print(f"[ACS API] [TURBOTIME] override no-guidance: guidance=0 flow_shift=1 phases=0")
        # [STORY-AV MULTI-CENA] JoyAI/Story AV usa parágrafos como CENAS (sliding windows). O ACS
        # mandava "FG" => split_prompt_units retorna [prompt_inteiro] = 1 cena so (saia 3s de 5x3s).
        # "PW" = P(cada paragrafo = janela) + W(sliding window) => as 5 cenas geram em sequencia.
        # Validos: {FG,G,PG,W,PW} (prompt_parser.normalize_multi_prompts_mode).
        _img_mp_gen_type = "FG"
        if model_info.get("base_type") == "joyai_echo":
            _img_mp_gen_type = "PW"
            print("[ACS API] [STORY-AV] multi_prompts_gen_type=PW (multi-cena por paragrafo)")
        _save_kw = dict(
            # ── Identificação ──────────────────────────────
            target            = "state",
            image_mask_guide  = None,
            lset_name         = "",
            client_id         = "",
            image_mode        = image_mode,      # int: 1=imagem, 0=vídeo
            # ── Texto ──────────────────────────────────────
            prompt            = req.prompt,
            alt_prompt        = "",
            negative_prompt   = req.negative_prompt,
            # ── Resolução ──────────────────────────────────
            resolution        = resolution,
            # ── Duração / frames ───────────────────────────
            video_length      = _seconds_to_video_length(req.duration, req.model),
            duration_seconds  = 0.0,
            pause_seconds     = 0,
            batch_size        = 1,
            seed              = req.seed,
            force_fps         = getattr(req, "force_fps", ""),   # [ADV-1177] ""|"8"|"16"|"24"
            # ── Steps / guidance ───────────────────────────
            num_inference_steps  = req.steps,
            guidance_scale       = _img_guidance,        # [TURBOTIME] 0 p/ no-guidance; req.guidance_scale p/ resto
            guidance2_scale      = 5,
            guidance3_scale      = 5,
            switch_threshold     = 0,
            switch_threshold2    = 0,
            guidance_phases      = _img_guid_phases,      # [TURBOTIME] 0 p/ distilled; auto p/ resto
            model_switch_phase   = 1,
            alt_guidance_scale   = 1.0,
            alt_scale            = 0.0,
            audio_guidance_scale = req.audio_guidance_scale,
            audio_scale          = req.audio_scale,
            flow_shift           = _img_flow_shift,       # [TURBOTIME] 1.0 p/ Ideogram turbo; 5.0 p/ resto
            # sample_solver: valor inicial; pode ser corrigido pelo fallback abaixo
            sample_solver        = _model_sample_solver,
            # [NEXTGEN] lê o embedded_guidance do DEF do motor (flux2_dev=4, distilled=1) — não hardcoda
            # [STORY-AV-ALIGN 2026-07-04] joyai_echo: 6.0 = default do Gradio (view_api). Testar impacto.
            embedded_guidance_scale = (6.0 if model_info.get("base_type") == "joyai_echo"
                                       else _def_param(model_info.get("model_id", ""), "embedded_guidance_scale", 1.0)),
            repeat_generation    = 1,
            multi_prompts_gen_type  = _img_mp_gen_type,   # [STORY-AV] "PW" p/ multi-cena; "FG" p/ resto
            multi_images_gen_type   = 0,
            skip_steps_cache_type   = "",
            skip_steps_multiplier   = 1.75,
            skip_steps_start_step_perc = 0,
            # ── LoRAs ──────────────────────────────────────
            loras_choices     = req.loras_choices,
            loras_multipliers = req.loras_multipliers,
            # ── Imagem / Vídeo source ──────────────────────
            image_prompt_type = image_prompt_type_param,
            image_start       = image_start_param,
            image_end         = image_end_param,
            model_mode        = None,
            video_source      = video_source_param,
            keep_frames_video_source  = "",
            input_video_strength      = input_video_strength_param,
            video_guide_outpainting   = "#",
            video_guide_outpainting_ratio = "",
            video_prompt_type = video_prompt_type,
            image_refs        = image_refs_param,
            frames_positions  = frames_positions_val,
            # FIX-BUG-VG: gr.Video espera {"video": FileData}, não FileData direto.
            # _wrap_file() produz FileData → ValidationError "Field 'video' required".
            # _wrap_gallery_item() produz {"video": FileData} para .mp4/.webm/.mov.
            video_guide       = _wrap_gallery_item(req.ctrl_video_path) if (req.ctrl_video_path and req.ctrl_video_prompt_type) else None,
            image_guide       = _wrap_file(req.ctrl_image_path) if req.ctrl_image_path else None,
            keep_frames_video_guide = "",
            denoising_strength  = 1.0,
            masking_strength    = 0.25,
            video_mask          = None,
            image_mask          = None,
            control_net_weight  = 1,
            control_net_weight2 = 1,
            control_net_weight_alt = 1,
            motion_amplitude    = req.motion_amplitude,
            mask_expand         = 0,
            # ── Áudio ──────────────────────────────────────
            audio_guide        = audio_guide_param,
            audio_guide2       = _wrap_file(req.audio_path2) if req.audio_path2 else None,
            custom_guide       = None,
            audio_source       = _wrap_file(req.audio_source_path) if req.audio_source_path else None,
            # [1177-FIX] seedvc params MUST be at idx 66-67 (after audio_source, before audio_prompt_type)
            # Wgp.py save_inputs signature: ...audio_source, seedvc_voice_sample, seedvc_voice_sample2, audio_prompt_type...
            # Previously placed after MMAudio_neg_prompt → all params from idx 66 shifted by +2 → server crash
            seedvc_voice_sample   = _wrap_file(req.seedvc_voice_sample)  if getattr(req, "seedvc_voice_sample",  "") else None,
            seedvc_voice_sample2  = _wrap_file(req.seedvc_voice_sample2) if getattr(req, "seedvc_voice_sample2", "") else None,
            audio_prompt_type  = audio_prompt_type_param,
            # M1-FIX: só aplica fallback "0:45 55:100" para dual-speaker (audio_path2 presente).
            # Antes: req.speakers_locations or "0:45 55:100" sempre enviava "0:45 55:100"
            # mesmo para single-speaker (quando req.speakers_locations == ""), o que é
            # semanticamente errado (Wan2GP ignora, mas confunde logs e pode causar problema
            # em versões futuras do Wan2GP que validem o campo para single-speaker também).
            speakers_locations = req.speakers_locations if req.speakers_locations else ("0:45 55:100" if req.audio_path2 else ""),
            # ── Sliding window ─────────────────────────────
            sliding_window_size      = _get_sliding_window_params(req.model)[0],
            sliding_window_overlap   = _sliding_overlap_for(req.model, getattr(req, "generation_mode", ""), getattr(req, "duration", 5)),
            sliding_window_color_correction_strength = 0,
            sliding_window_overlap_noise             = 0,
            sliding_window_discard_last_frames       = 0,
            image_refs_relative_size = 50,
            remove_background_images_ref = 0,
            # ── Upsampling / grain ─────────────────────────
            temporal_upsampling  = getattr(req, "temporal_upsampling", ""),   # [ADV-1177] ""|"rife2"|"rife4"
            spatial_upsampling   = getattr(req, "spatial_upsampling", ""),   # [ADV-1177] ""|"lanczos"|"flashvsr"|"flashvsr2pass"
            film_grain_intensity  = getattr(req, "film_grain_intensity",  0),   # [FIX-BLOCKER-02] user value
            film_grain_saturation = getattr(req, "film_grain_saturation", 0.5), # [FIX-BLOCKER-02] user value
            # ── Audio post-processing [1177: postprocess_audio substitui MMAudio_setting] ──
            postprocess_audio     = "" if _USE_WANSESSION else _mmaudio_to_postprocess(req.mmaudio),  # [AUDIO-FIX 06-28] cano-novo pula o post-proc do motor (quebra c/ "control"); áudio entra via mux api-side
            MMAudio_prompt        = "",
            MMAudio_neg_prompt    = "",
            # ── Misc avançado ──────────────────────────────
            RIFLEx_setting     = getattr(req, "riflex_setting", 0),          # [ADV-1177] 0|1|2
            NAG_scale          = 1,
            NAG_tau            = 3.5,
            NAG_alpha          = 0.5,
            perturbation_switch = 0,
            perturbation_layers = [9],
            perturbation_start_perc = 10,
            perturbation_end_perc   = 90,
            apg_switch         = 0,
            cfg_star_switch    = 0,
            cfg_zero_step      = -1,
            prompt_enhancer    = req.prompt_enhancer,
            min_frames_if_references = 1,
            override_profile   = -1,
            override_attention = "",
            temperature        = 0.8,
            custom_setting_1   = "",
            custom_setting_2   = "",
            custom_setting_3   = "",
            custom_setting_4   = "",
            custom_setting_5   = "",
            top_p              = 0.9,
            top_k              = 50,
            self_refiner_setting = getattr(req, "self_refiner_setting", 0), # [ADV-1177] 0|1|2
            self_refiner_f_uncertainty      = 0.0,
            self_refiner_certain_percentage = 0.999,
            output_filename    = "",
            mode               = "",
            api_name           = "/save_inputs",
        )
        # [12.24-API] Migração da assinatura do save_inputs (11.77 → 12.24). Env-gated.
        # 12.24 removeu MMAudio_*/seedvc_* e adicionou postprocess_audio_*/replace_voice_*/
        # custom_setting_(dropdown|slider)_1..5 + sliding_window_trim_first_frames.
        if _API_V2:
            _mm_p  = _save_kw.pop("MMAudio_prompt", "")
            _mm_np = _save_kw.pop("MMAudio_neg_prompt", "")
            _vs1   = _save_kw.pop("seedvc_voice_sample", None)
            _vs2   = _save_kw.pop("seedvc_voice_sample2", None)
            _save_kw.update({
                "postprocess_audio_prompt": _mm_p,
                "postprocess_audio_neg_prompt": _mm_np,
                "replace_voice_method": "",
                "replace_voice_sample": _vs1,
                "replace_voice_sample2": _vs2,
                "sliding_window_trim_first_frames": 0,
            })
            for _i in range(1, 6):
                _save_kw[f"custom_setting_dropdown_{_i}"] = None   # default real do 12.24 (Dropdown sem choices)
                _save_kw[f"custom_setting_slider_{_i}"]   = 0
            # [IDEOGRAM-NaN] mu/std do Ideogram sao SLIDERS (slider_1=mu idx0, slider_2=std idx1).
            # O loop acima zera tudo => std=0; ideogram_std tem min=0.1 e o scheduler divide por std
            # => 0 => NaN => imagem PRETA (o 'invalid value in cast' do log). Valores do handler:
            # ideogram4_handler.py L30/31 (mu default 0.0/0.5, std default 1.75). TurboTime: mu=0.5.
            if model_info.get("family") == "ideogram4":
                _save_kw["custom_setting_slider_1"] = 0.5    # ideogram_mu
                _save_kw["custom_setting_slider_2"] = 1.75   # ideogram_std (NUNCA 0 => NaN)
                print("[ACS API] [IDEOGRAM] mu/std sliders setados: 0.5/1.75 (evita NaN/preto)")
            # [SCAIL2-POSE] Character Animate: RAW preprocessing (default) deforma as extremidades
            # (a mão vira blob/smearing no movimento). POSE extrai o esqueleto 3D => movimento limpo,
            # sem a aparência do control video interferir. scail2_animate_preprocessing é o 1º custom
            # setting (index 0, dropdown) => custom_setting_dropdown_1. Valores: "raw"|"pose"
            # (Wan2GP_Dev/models/wan/scail2/__init__.py:20-21). image_ref_keyword_content fica no
            # default "human character" (text slot, nao precisa setar).
            if model_info.get("base_type") == "scail2_14B":
                _save_kw["custom_setting_dropdown_1"] = "raw"   # [FIX 06-28] o Luigi usa "Use Raw Control Video Content" (=raw); o smearing era a lora nao aplicar, nao o raw
                # [SCAIL2-KEYWORD 2026-07-04] image_ref_keyword_content (custom_setting_1, text slot) guia
                # o SAM 3 na extracao da mascara da pessoa de referencia. O default do motor "human character"
                # NAO segmenta (SCAIL-2 falha "could not extract the image reference mask"); a doc do motor
                # (scail2/__init__.py:82) exige "person"/"woman"/"man". O campo e oculto em V1 (visivel so em "I"),
                # entao o cliente nunca o preenche -> ACS envia "person" por padrao. PROVADO: 3 imagens falhavam.
                _save_kw["custom_setting_1"] = "person"
                print("[ACS API] [SCAIL2] animate_preprocessing=raw + image_ref_keyword=person (SAM3 mask)")
        # ── IMG-PERF T6: preprocess elapsed (wrap_file + dict build) ─
        if _is_image_job:
            _t_preprocess_done = time.time()
            _preprocess_ms = (_t_preprocess_done - _t_preprocess) * 1000
            _has_ctrl_img  = bool(req.ctrl_image_path)
            _has_ref_imgs  = bool(image_refs_param)
            print(
                f"[IMG-PERF] T6_preprocess_image: {_preprocess_ms:.1f}ms"
                f"  ctrl_image={_has_ctrl_img}"
                f"  ref_images={_has_ref_imgs}  n_refs={len(image_refs_param)}"
                f"  note: wrap_file_only (no PIL/resize in ACS)"
            )
            _ip("T6_preprocess_image",
                f"ctrl={'yes' if _has_ctrl_img else 'no'} refs={len(image_refs_param)}")
        # [WANSESSION-B] _save_kw COMPLETO aqui (122 campos, toda a lógica do ACS).
        # Flag ON → arquivos/modos via build_core_settings (TESTADO, caminho puro) +
        # toggles escalares do _save_kw (paridade Gradio). GERA e RETORNA (pula o
        # submit/process_tasks/polling Gradio abaixo).
        if _USE_WANSESSION and WAN is not None:
            import os as _os
            from acs_wansession_path import build_core_settings, run_with_live_progress, _upload_local_files
            try:
                _reqd = req.model_dump() if hasattr(req, "model_dump") else req.dict()
                try: _reqd["video_length"] = _seconds_to_video_length(req.duration, req.model)
                except Exception: pass
                # [FIX-RES-WANSESSION] resolve labels ("480p") → WxH ("832x480")
                _rr = _reqd.get("resolution", "")
                if _rr in RESOLUTION_MAP:
                    _reqd["resolution"] = RESOLUTION_MAP[_rr]
                _mt = model_info.get("model_id", "")
                _wan_settings = build_core_settings(_reqd, _mt)          # arquivos/modos (testado)
                # [JARVIS-RUNPOD] Worker é remoto (Pod) — sobe cada referência local
                # (image_start/image_end/video_guide/video_source/audio_guide/...)
                # antes de gerar, porque um path local do Windows não existe no Pod.
                _wan_settings = _upload_local_files(WAN, _wan_settings)
                _GRADIO_ONLY = {"target", "image_mask_guide", "lset_name", "client_id", "api_name", "mode"}
                _FILE_KEYS = {"image_start", "image_end", "image_refs", "image_guide", "video_guide",
                              "video_source", "video_mask", "image_mask", "audio_guide", "audio_guide2",
                              "audio_source", "custom_guide"}
                for _k, _v in _save_kw.items():     # enriquece com toggles escalares = paridade Gradio
                    if _k not in _GRADIO_ONLY and _k not in _FILE_KEYS and _k not in _wan_settings:
                        _wan_settings[_k] = _v
                # [FIX-DIVERG 2026-06-26] model-aware: deixa o DEFAULT DO MOTOR vencer nos campos
                # que o ACS estava sobrescrevendo com hardcode stale (guidance2/3, perturbation,
                # masking). Adapter faz merge sobre get_default_settings → remover = usar default
                # correto do modelo. Preserva intencionais: sample_solver (euler ltx2_22B), PW (Story AV).
                for _ko in ("guidance2_scale", "guidance3_scale", "perturbation_layers",
                            "perturbation_start_perc", "perturbation_end_perc", "masking_strength"):
                    _wan_settings.pop(_ko, None)
                if _wan_settings.get("multi_prompts_gen_type") == "FG":  # FG=default nao-intencional; PW preserva
                    _wan_settings.pop("multi_prompts_gen_type", None)
                try:  # guidance: so envia se o usuario MEXEU (!=5 default); senao motor decide (0 distilled/1 ltx2)
                    if abs(float(_reqd.get("guidance_scale", 5)) - 5.0) < 1e-6:
                        _wan_settings.pop("guidance_scale", None)
                except Exception: pass
                # [MSR 2026-06-26] Multi-Personagem (ltx2_22B_msr): força o modo de referência por
                # IMAGEM (KI=Background+Subjects / I=Subjects). As fotos chegam em image_refs (via
                # ref_inject_paths→image_refs em build_core_settings). Sem isto o video_prompt_type
                # ficaria vazio e o MSR LoRA não receberia as referências de personagem.
                if model_info.get("base_type") == "ltx2_22B_msr":
                    # [MSR 06-28] modo selecionável pelo usuário (KI=Fundo+Sujeitos / I=só Sujeitos);
                    # fallback ao default do modelo. Antes forçava sempre "KI" ignorando a escolha.
                    _msr = (str(_reqd.get("msr_mode", "") or "")).strip().upper()
                    if _msr not in ("KI", "I"):
                        _msr = model_info.get("msr_mode", "KI")
                    _wan_settings["video_prompt_type"] = _msr
                # [JOYAI-CTRLMEM 2026-06-26] JoyAI Control Video Memory: semeia memória nomeada de
                # personagem/voz a partir de um Control Video (com áudio) ANTES da 1ª janela — é o
                # "multi-frames de referência" do multi-cena. Motor exige video_prompt_type contendo
                # "V" (mapeia p/ V1) + posições em custom_settings[joyai_control_memory_positions]
                # ("2s,8s" ou "man=2s,woman=8s"; vazio=auto não-silêncio). O Control Video chega em
                # video_guide (via ctrl_video_path+ctrl_video_prompt_type="V" em build_core_settings).
                if model_info.get("base_type") == "joyai_echo" and "V" in (_reqd.get("ctrl_video_prompt_type", "") or ""):
                    _vpt = _wan_settings.get("video_prompt_type", "") or ""
                    if "V" not in _vpt:
                        _wan_settings["video_prompt_type"] = _vpt + "V"
                    _cs = _wan_settings.get("custom_settings")
                    if not isinstance(_cs, dict):
                        _cs = {}
                    _cs["joyai_control_memory_positions"] = _reqd.get("joyai_control_memory_positions", "") or ""
                    _wan_settings["custom_settings"] = _cs
                # [CAP-AUDIO 2026-06-26] "Capped By: Control Length" do Gradio = "|" no video_prompt_type
                # (change_force_control_video_trim wgp.py:10939). O motor então faz control_video_trim
                # → video_length_limited_by_audio (wgp.py:6829,6871): o vídeo termina junto com o áudio/
                # control (Talking Head sem padding mudo no fim). Replica fielmente: remove "|" e re-adiciona.
                if int(_reqd.get("force_control_video_trim", 0) or 0) == 1:
                    _vpt_cap = (_wan_settings.get("video_prompt_type", "") or "").replace("|", "")
                    _wan_settings["video_prompt_type"] = _vpt_cap + "|"
                jobs[job_id]["status"] = "generating"; jobs[job_id]["progress"] = 50
                _r = run_with_live_progress(jobs, job_id, lambda: WAN.generate(_mt, _wan_settings))
                if not _r.get("ok"):
                    _err = _r.get("error", "erro no Motor de IA")
                    # [DOD-UX 2026-06-27] falha de download de modelo → mensagem comercial amigável
                    # (não a URL crua do HuggingFace, que vaza ltx/wan + confunde o cliente).
                    _el = str(_err).lower()
                    if ("huggingface.co" in _el or "could not be downloaded" in _el
                            or ("resolve/main" in _el) or (".safetensors" in _el and "download" in _el)):
                        _err = (f'O modelo "{req.model}" ainda não está instalado. Ele é baixado '
                                "automaticamente no primeiro uso (requer internet). Aguarde o download "
                                "concluir e gere novamente.")
                    try:
                        import acs_self_learning as _sl
                        _sl.learn(str(_err), model=getattr(req, "model", ""), build="Build48")
                    except Exception:
                        pass
                    jobs[job_id]["status"] = "error"; jobs[job_id]["error"] = _err; return
                _p = _r["path"]; _fn = _os.path.basename(_p)
                _sz = round(_os.path.getsize(_p) / 1024 / 1024, 2) if _os.path.exists(_p) else 0
                # [AUDIO-MUX 06-28 / WANSESSION] cano-novo pula o post-proc de áudio do motor → vídeo mudo.
                # Se o endpoint i2v guardou o áudio do control video (mux_audio_path, após strip), muxa agora.
                try:
                    _mxa = getattr(req, "mux_audio_path", "") or ""
                    if _mxa and _os.path.exists(_mxa) and _os.path.exists(_p):
                        import subprocess as _sp3
                        _ffm3 = str(WAN2GP_DIR / "ffmpeg_bins" / "ffmpeg.exe")
                        _ffp3 = str(WAN2GP_DIR / "ffmpeg_bins" / "ffprobe.exe")
                        _a_in  = _sp3.run([_ffp3,"-v","error","-select_streams","a","-show_entries","stream=index","-of","csv=p=0",_mxa], capture_output=True, text=True).stdout.strip()
                        _a_out = _sp3.run([_ffp3,"-v","error","-select_streams","a","-show_entries","stream=index","-of","csv=p=0",_p], capture_output=True, text=True).stdout.strip()
                        if _a_in and not _a_out:
                            _mux_tmp = _p + ".muxed.mp4"
                            _rr = _sp3.run([_ffm3,"-y","-i",_p,"-i",_mxa,"-map","0:v","-map","1:a:0","-c:v","copy","-c:a","aac","-shortest",_mux_tmp], capture_output=True, text=True)
                            if _rr.returncode == 0 and _os.path.exists(_mux_tmp):
                                _os.replace(_mux_tmp, _p)
                                _sz = round(_os.path.getsize(_p) / 1024 / 1024, 2)
                                print(f"[AUDIO-MUX] [WANSESSION] audio do control muxado em {_fn}")
                            else:
                                print(f"[AUDIO-MUX] [WANSESSION] falhou rc={_rr.returncode}: {_rr.stderr[:160]}")
                except Exception as _eMux:
                    print(f"[AUDIO-MUX] [WANSESSION] erro: {_eMux}")
                jobs[job_id]["status"] = "done"; jobs[job_id]["progress"] = 100; jobs[job_id]["step"] = "concluído"
                # [ESTENDER 2026-06-27] expõe o caminho local do output → o botão "Estender vídeo"
                # usa ele como vídeo-fonte (modo Continue) sem precisar re-upload.
                jobs[job_id]["output"] = {"filename": _fn, "url": f"/file/{_fn}", "size_mb": _sz, "path": _p}
                print(f"[ACS API] [WANSESSION] job {job_id} CONCLUIDO: {_fn} ({_sz} MB)")
            except Exception as _e:
                _emsg = str(_e)
                _el2 = _emsg.lower()
                if "already has a generation in progress" in _el2 or ("500" in _emsg and "internal server error" in _el2):
                    _emsg = ("O motor ainda está processando uma geração anterior (possivelmente "
                             "baixando o modelo). Aguarde a conclusão e tente novamente.")
                else:
                    _emsg = f"Motor de IA: {_e}"
                jobs[job_id]["status"] = "error"; jobs[job_id]["error"] = _emsg
                print(f"[ACS API] [WANSESSION] ERRO job {job_id}: {_e}")
                try:
                    import acs_self_learning as _sl
                    _sl.learn(str(_e), model=getattr(req, "model", ""), build="Build48")
                except Exception:
                    pass
            return
        try:
            job_save = client.submit(**_save_kw)
            try:
                job_save.result()
            except Exception as _e_save:
                _err_save = str(_e_save)
                if "is not in the list of choices" in _err_save:
                    # ── Fallback ACS-ERR-0041 / ACS-ERR-0041-B ────────────────
                    # Parseia as choices válidas do erro e reenvia — 1 retry, sem loop.
                    # Detecta se o erro é para resolution (WxH) ou sample_solver.
                    _m_choices = re.search(r"list of choices:\s*\[([^\]]+)\]", _err_save)
                    _m_failing = re.search(r"Value:\s*(\S+)\s+is not in the list", _err_save)
                    if _m_choices:
                        _valid = [c.strip().strip("'\"") for c in _m_choices.group(1).split(",")]
                        _failing_val = _m_failing.group(1).strip("'\"") if _m_failing else ""

                        # ── ACS-ERR-0041-B: resolução inválida para o grupo atual ──
                        # Quando Wan2GP 11.77 remove uma resolução (ex: 512x288 → 576x320),
                        # o erro reporta o valor da resolução enviada, não do sample_solver.
                        # Detecta: failing_val tem formato WxH numérico.
                        _is_res_error = bool(re.match(r"^\d+x\d+$", _failing_val))
                        if _is_res_error and _failing_val == _save_kw.get("resolution", ""):
                            # Escolhe a resolução mais próxima em aspect ratio
                            try:
                                _req_w, _req_h = map(int, _failing_val.split("x"))
                                _req_ar = _req_w / max(_req_h, 1)
                            except Exception:
                                _req_ar = 1.0
                            def _ar_dist(res_str):
                                try:
                                    _w, _h = map(int, res_str.split("x"))
                                    return abs(_w / max(_h, 1) - _req_ar)
                                except Exception:
                                    return 999.0
                            _fb_res = min(_valid, key=_ar_dist) if _valid else _valid[0]
                            _orig_res = _save_kw["resolution"]
                            print(
                                f"[ACS API] resolution fallback applied (ACS-ERR-0041-B): "
                                f"'{_orig_res}' -> '{_fb_res}' "
                                f"choices={_valid} job={job_id}"
                            )
                            _save_kw["resolution"] = _fb_res
                            job_save = client.submit(**_save_kw)
                            job_save.result()   # se falhar de novo → propaga
                        else:
                            # ── ACS-ERR-0041: sample_solver inválido ──────────────
                            # Preferência: euler → unipc → dpm++ → primeiro da lista.
                            # [JOYAI] dropdown vazio choices=[''] => _fb_solver="" (único válido no
                            # dropdown). O handler (ltx2_handler ACS-FIX-SOLVER v2) trata ""→euler p/
                            # TODO LTX2_22B_CLASS (joyai incluso). Antes meu elif forçava euler aqui
                            # e o Gradio recusava de novo — removido.
                            _fb_solver = next(
                                (c for c in ("euler", "unipc", "dpm++") if c in _valid),
                                _valid[0] if _valid else "",
                            )
                            _orig_solver = _save_kw["sample_solver"]
                            print(
                                f"[ACS API] sample_solver fallback applied: "
                                f"'{_orig_solver}' -> '{_fb_solver}' "
                                f"choices={_valid} job={job_id}"
                            )
                            # Log INFO (fail-safe)
                            if _LOG_ENABLED:
                                try:
                                    _acs_log.log(
                                        stage="GENERATE_IMAGE" if req.generation_mode == "t2i" else "GENERATE_VIDEO",
                                        level="INFO",
                                        message_friendly=(
                                            f"sample_solver fallback aplicado: "
                                            f"'{_orig_solver}' -> '{_fb_solver}'"
                                        ),
                                        message_tech=(
                                            f"sample_solver fallback applied: "
                                            f"'{_orig_solver}' -> '{_fb_solver}' "
                                            f"choices={_valid} model={req.model}"
                                        ),
                                        job_id=job_id,
                                    )
                                except Exception:
                                    pass
                            # Retry com valor corrigido — SEM LOOP
                            _save_kw["sample_solver"] = _fb_solver
                            job_save = client.submit(**_save_kw)
                            job_save.result()   # se falhar de novo → propaga para outer except
                    else:
                        raise _e_save      # choices não parseáveis → propaga
                else:
                    raise _e_save          # erro diferente → propaga
        except Exception as e:
            _fail("save_inputs falhou", e)
            return
        _perf_ts("T9_passo5_save_inputs")
        _ip("T8_save_inputs")
        # ── [PERF-DEBUG] Dump payload para diagnóstico ─────────────
        try:
            import json as _json
            _payload_log = {k: (str(v) if not isinstance(v, (str, int, float, bool, list, type(None))) else v)
                            for k, v in _save_kw.items() if k != "api_name"}
            _payload_log["__job_id"] = job_id
            _payload_log["__model"] = req.model
            _payload_log["__resolution_sent"] = resolution
            _payload_path = Path(__file__).parent / "acs_last_gradio_payload.json"
            _payload_path.write_text(_json.dumps(_payload_log, indent=2, ensure_ascii=False))
            print(f"[PERF-DEBUG] Payload salvo em: {_payload_path}")
        except Exception as _pe:
            print(f"[PERF-DEBUG] Erro ao salvar payload: {_pe}")
        # ── IMG-PERF: salva payload específico de imagem ─────────
        if _is_image_job:
            try:
                _img_payload = {
                    "__schema": "acs_image_payload_v1",
                    "__job_id":             job_id,
                    "__timestamp":          time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    # ── Parâmetros ACS (o que o frontend enviou) ──
                    "acs_model":            req.model,
                    "acs_resolution":       req.resolution,
                    "acs_resolution_resolved": resolution,
                    "acs_steps":            req.steps,
                    "acs_seed":             req.seed,
                    "acs_prompt_enhancer":  req.prompt_enhancer,
                    "acs_inject_type":      req.inject_video_prompt_type or "",
                    "acs_ctrl_type":        req.ctrl_video_prompt_type or "",
                    "acs_ctrl_image_present": bool(req.ctrl_image_path),
                    "acs_ref_image_present":  bool(req.ref_inject_paths),
                    "acs_loras":            req.loras_choices,
                    "acs_loras_multipliers": req.loras_multipliers,
                    # ── Parâmetros Gradio (o que foi enviado ao Wan2GP) ──
                    "gradio_model_id":      model_id,
                    "gradio_base_type":     base_type,
                    "gradio_family":        family,
                    "gradio_image_mode":    image_mode,
                    "gradio_video_prompt_type": video_prompt_type,
                    "gradio_image_prompt_type": image_prompt_type_param,
                    "gradio_image_refs_count":  len(image_refs_param),
                    "gradio_guidance_phases": _get_guidance_phases(req.model),
                    "gradio_prompt_enhancer": req.prompt_enhancer,
                    # ── Checkpoint / cache info ──
                    "checkpoint_model_id":        model_id,
                    "checkpoint_same_as_last":    _is_same_checkpoint,
                    "checkpoint_last_model":      _LAST_LOADED_MODEL_ID.get("id", "none"),
                    "checkpoint_change_elapsed_s": round(_cm_elapsed, 3),
                    "checkpoint_result":          _cache_result,
                    # ── Full Gradio save_inputs payload ──
                    "gradio_save_inputs": {
                        k: (str(v) if not isinstance(v, (str, int, float, bool, list, type(None))) else v)
                        for k, v in _save_kw.items() if k != "api_name"
                    },
                }
                _img_payload_path = Path(__file__).parent / "acs_last_image_payload.json"
                _img_payload_path.write_text(
                    _json.dumps(_img_payload, indent=2, ensure_ascii=False)
                )
                print(f"[IMG-PERF] Payload salvo: {_img_payload_path}")
            except Exception as _ipe:
                print(f"[IMG-PERF] Erro ao salvar image payload: {_ipe}")
        time.sleep(0.1)  # [C2-PERF] 0.3→0.1 — save_inputs é síncrono, resultado já aplicado

        # ────────────────────────────────────────────────────────
        # PASSO 6: validate_wizard_prompt → seta state["validate_success"] = 1
        # wizard_prompt_activated="off" → bypass wizard, validate_success=1
        # ────────────────────────────────────────────────────────
        _step("PASSO 6: validate_wizard_prompt", 40)
        try:
            client.predict(
                "off",        # wizard_prompt_activated != "on" → validate_success = 1
                "",           # wizard_variables_names
                req.prompt,   # prompt
                "",           # wizard_prompt
                # param_5..param_14 — variáveis do wizard (todas vazias)
                "", "", "", "", "", "", "", "", "", "",
                api_name="/validate_wizard_prompt"
            )
        except Exception as e:
            _fail("validate_wizard_prompt falhou", e)
            return
        # [C2-PERF] validate retorna valor — sem sleep necessário (era 0.2s)
        _perf_ts("T10_passo6_validate")
        _ip("T9_validate_prompt")

        # ────────────────────────────────────────────────────────
        # PASSO 7: process_prompt_and_add_tasks → adiciona à fila
        #
        # current_gallery_tab APENAS seta gen["last_was_audio"] = (tab == 1)
        # NÃO é o seletor de modo — o modo vem do image_prompt_type no state.
        # Usar gallery_tab=0.0 para todos os modos de vídeo/imagem.
        # Usar gallery_tab=1.0 apenas se o output for audio puro.
        # ────────────────────────────────────────────────────────
        # [12.24-SYNC] Re-assertar base_type ANTES do process_prompt. No 12.24 o change_model
        # (PASSO 4) reverte as choices do dropdown model_choice; sem isto, sub-variantes como
        # ltx2_22B_edit_anything falham no PASSO 7 ("model not in choices"). Idempotente —
        # também limpa contaminação de troca de família/base_type (ataca o ERR-09).
        if _API_V2:
            try:
                client.predict(family, base_type, api_name=_API_CHANGE_BASE_TYPES)
                time.sleep(0.1)
            except Exception as _e_reassert:
                print(f"[ACS API] re-assert base_type (PASSO 7) aviso: {_e_reassert}")
        _step(f"PASSO 7: process_prompt_and_add_tasks (tab={gallery_tab}, image_prompt_type='{image_prompt_type_param}')", 50)
        try:
            client.predict(
                gallery_tab,  # current_gallery_tab — só controla last_was_audio
                model_id,     # model_choice — deve = state["model_type"]
                api_name="/process_prompt_and_add_tasks"
            )
        except Exception as e:
            _fail("process_prompt_and_add_tasks falhou", e)
            return
        _perf_ts("T11_passo7_process_prompt")

        # ────────────────────────────────────────────────────────
        # PASSO 8: prepare_generate_video (atualiza botões na UI)
        # ────────────────────────────────────────────────────────
        _step("PASSO 8: prepare_generate_video", 55)
        try:
            client.predict(api_name=_API_PREPARE_GENERATE)
        except Exception as e:
            print(f"[ACS API] prepare_generate_video aviso (não crítico): {e}")
        time.sleep(0.1)  # [C2-PERF] 0.3→0.1 — prepare é síncrono
        _perf_ts("T12_passo8_prepare")
        _ip("T10_prepare_generate")

        # ────────────────────────────────────────────────────────
        # PASSO 9: process_tasks → GERAÇÃO REAL
        # Submitamos e colocamos gen_job.result() em thread daemon para não
        # bloquear: o Gradio às vezes não sinaliza conclusão mesmo com
        # arquivo já salvo. Polling de arquivo roda em paralelo e vence.
        # ────────────────────────────────────────────────────────
        # T12-CP2: cancel durante PASSOs 1–8 (carregamento de modelo) não deve iniciar geração real
        if jobs[job_id].get("status") == "cancelled":
            print(f"[ACS API] job {job_id} | cancelado antes da geração")
            return

        # Status amigável: se modelo não instalado, avisa que download vai acontecer
        # NOTA: download_gb no MODELS dict é estimativa manual — NÃO usar aqui.
        # Tamanho real exige HF Hub API (ver DOWNLOAD_PROGRESS_REPORT.md).
        _is_installed  = model_info.get("installed", True)
        _model_family  = model_info.get("family", "")
        # [FIX-HF_XET] ltx2 baixa componentes auxiliares (text encoder, VAE, T5) via
        # HuggingFace mesmo quando o modelo principal (safetensors) está instalado.
        # Sem hf_xet → HTTP fallback → 16+ GB podem levar > 20 min → timeout de 1200s dispara.
        # Usar timeout de 3600s para toda a família ltx2 independente de _is_installed.
        _needs_hf_download = not _is_installed or _model_family.startswith("ltx2") or model_info.get("first_use_dl", False)  # [12.24] modelos novos baixam no 1º uso → 3600s
        if not _is_installed:
            _step("Baixando modelos necessários", 55)
        elif _needs_hf_download:
            _step("PASSO 9: process_tasks (iniciando — pode baixar componentes HF)", 60)
        else:
            _step("PASSO 9: process_tasks (gerando...)", 60)
        jobs[job_id]["status"] = "generating"

        gen_job = client.submit(api_name="/process_tasks")
        jobs[job_id]["gen_job"] = gen_job   # Fix C1: expõe future para /cancel
        _perf_ts("T13_passo9_process_tasks_SUBMIT")
        _ip("T11_process_tasks")

        # Thread daemon: aguarda sinal Gradio (pode nunca chegar — tudo bem)
        # Fix GRADIO-ERR: se Wan2GP retornar erro (OOM, invalid param, etc.),
        # seta jobs[job_id]["_abort_passo10"] = True para que _wait_new_output
        # aborte imediatamente em vez de esperar o timeout de 1200s.
        # [FIX-HF_XET] Usar 3600s para modelos que fazem download via HF
        _gradio_timeout = (7200 if model_info.get("first_use_dl") else 3600) if _needs_hf_download else 700
        def _wait_gradio_signal():
            try:
                gen_job.result(timeout=_gradio_timeout)
                print(f"[ACS API] job {job_id} | process_tasks: Gradio sinalizou conclusão")
                if job_id in jobs:
                    jobs[job_id]["_gradio_done"] = True   # [MULTI-CENA] sinal de conclusão TOTAL (todas as janelas)
            except Exception as e:
                err_str = str(e)
                print(f"[ACS API] job {job_id} | process_tasks gradio signal: {err_str}")
                # Fix GRADIO-ERR: propagar erro Wan2GP para abortar PASSO 10
                # Distinguir erro real (Wan2GP OOM/crash) de timeout normal do Future.
                # "encountered an error" → mensagem padrão de erro de geração do Wan2GP.
                # "GradioError" / "Error" em e.__class__ → Gradio propagou exceção do backend.
                _is_real_error = (
                    "encountered an error" in err_str
                    or "unsufficient RAM" in err_str
                    or "insufficient RAM" in err_str
                    or "GradioError" in type(e).__name__
                    or "AppError" in type(e).__name__
                    or "Error" in type(e).__name__
                ) and "timeout" not in err_str.lower() and "TimeoutError" not in type(e).__name__
                if _is_real_error and job_id in jobs:
                    print(f"[ACS API] job {job_id} | GRADIO-ERR: abortando PASSO 10 — {err_str[:200]}")
                    jobs[job_id]["_abort_passo10"] = err_str  # armazena msg para erro final

        t_gradio = threading.Thread(target=_wait_gradio_signal, daemon=True)
        t_gradio.start()

        # ── [G3-HUD] Thread: monitora progresso tqdm real do Gradio ─────────
        # gen_job.status() retorna StatusUpdate com progress_data[] (ProgressUpdate).
        # Cada ProgressUpdate: .index (step atual), .length (total steps).
        # Stage 1: total=num_steps (8). Stage 2 denoise: total=3.
        # Calcula speed (s/step) entre steps consecutivos.
        # Atualiza jobs[job_id]: gen_step, gen_total, gen_stage, gen_speed_sps.
        def _monitor_gen_progress():
            _mon_step  = [None]
            _mon_t     = [time.time()]
            _first_step_at = [None]   # [IMG-PERF] T12: timestamp do primeiro step
            _last_step_at  = [None]   # [IMG-PERF] T13: timestamp do último step visto
            while not gen_job.done():
                try:
                    st = gen_job.status()
                    if st and st.progress_data:
                        pu = st.progress_data[0]  # primeiro tqdm bar (o relevante)
                        idx   = getattr(pu, "index",  None)
                        total = getattr(pu, "length", None)
                        if idx is not None and total is not None and int(total) > 0:
                            idx, total = int(idx), int(total)
                            if idx != _mon_step[0]:
                                now   = time.time()
                                speed = round(now - _mon_t[0], 2) if _mon_step[0] is not None else None
                                _mon_t[0]    = now
                                _mon_step[0] = idx
                                jobs[job_id]["gen_step"]      = idx
                                jobs[job_id]["gen_total"]     = total
                                jobs[job_id]["gen_speed_sps"] = speed
                                # Stage 1 = total matches inference steps (≥4); Stage 2 = total≤3
                                jobs[job_id]["gen_stage"]     = 2 if total <= 3 else 1
                                print(f"[GEN-PROG] job={job_id} "
                                      f"step={idx}/{total} stage={jobs[job_id]['gen_stage']} "
                                      f"speed={speed}s/step")
                                # ── IMG-PERF T12/T13 ──────────────────────
                                if _is_image_job:
                                    if _first_step_at[0] is None and idx >= 1:
                                        _first_step_at[0] = now
                                        jobs[job_id]["t12_first_step"] = now
                                        _elapsed_t12 = now - _perf_t0
                                        _elapsed_t12_t1 = now - _t1
                                        print(
                                            f"[IMG-PERF] T12_first_step"
                                            f"  step={idx}/{total}"
                                            f"  +lock={_elapsed_t12:.3f}s"
                                            f"  +T1={_elapsed_t12_t1:.3f}s"
                                            f"  setup_overhead={_elapsed_t12:.3f}s"
                                        )
                                    _last_step_at[0] = now
                                    jobs[job_id]["t13_last_step"]     = now
                                    jobs[job_id]["t13_last_step_idx"] = idx
                            else:
                                # Total pode mudar entre Stage1→Stage2 sem idx mudar
                                jobs[job_id]["gen_total"] = total
                                jobs[job_id]["gen_stage"] = 2 if total <= 3 else 1
                except Exception:
                    pass
                time.sleep(0.4)
        threading.Thread(target=_monitor_gen_progress, daemon=True).start()

        # ────────────────────────────────────────────────────────
        # PASSO 10: Detectar arquivo gerado (polling paralelo)
        # Não espera o Gradio sinalizar — detecta o arquivo diretamente.
        # Timeout de 10 min para modelos grandes/vídeos longos.
        # ────────────────────────────────────────────────────────
        # Timeout: 1200s para modelos instalados (exceto ltx2), 3600s caso contrário
        #   - Modelo não instalado: download de 10-20 GB pode levar 30+ min
        #   - [FIX-HF_XET] ltx2: componentes auxiliares baixados via HF no 1º uso
        #   - Image 2K/4K: Flux 2 Klein 9B leva ~780s para gerar 2560x1440
        _output_timeout = (7200 if model_info.get("first_use_dl") else 3600) if _needs_hf_download else 1200
        _step("PASSO 10: verificando outputs", 90)

        # [FIX-HF_XET] Thread: monitora wan2gp.log durante PASSO 10 para detectar
        # download HuggingFace ativo e atualizar status do job com mensagem útil.
        # Não aborta — apenas informa. Substitui silêncio de 1200s por mensagem "Baixando...".
        _HF_DL_LOG_PATTERNS = [
            "hf_xet package is not installed",
            "Falling back to regular HTTP download",
            "Downloading",
            "huggingface.co",
        ]
        _hf_dl_flagged = [False]  # flag mutable para closure
        def _monitor_hf_download():
            try:
                _anchor = _WAN2GP_LOG_PATH.stat().st_size if _WAN2GP_LOG_PATH.exists() else 0
            except Exception:
                _anchor = 0
            while not gen_job.done() and job_id in jobs and jobs[job_id].get("status") == "generating":
                time.sleep(10)
                try:
                    if not _WAN2GP_LOG_PATH.exists():
                        continue
                    with open(_WAN2GP_LOG_PATH, "rb") as _hf_lf:
                        _hf_lf.seek(_anchor)
                        _new = _hf_lf.read().decode("utf-8", errors="replace")
                    if any(pat in _new for pat in _HF_DL_LOG_PATTERNS):
                        if not _hf_dl_flagged[0]:
                            _hf_dl_flagged[0] = True
                            _xet_msg = (
                                "⬇ Baixando modelo via HTTP (primeira vez — pode demorar 10-30 min)."
                                " Instale hf_xet para acelerar downloads futuros."
                            )
                            print(f"[ACS API] job {job_id} | HF-DOWNLOAD detectado: {_xet_msg}")
                            jobs[job_id]["step"] = _xet_msg
                        # Continua monitorando para eventual conclusão
                except Exception:
                    pass
        threading.Thread(target=_monitor_hf_download, daemon=True).start()
        # [PASSO10-WAV] Para jobs de vídeo (image_mode=0), filtrar por extensões de vídeo.
        # Evita falso-negativo quando AI Soundtrack salva .wav standalone antes do vídeo final.
        # [PASSO10-CONTAINER] Aceitar todos os containers configuráveis: mp4/mov/mkv.
        # O container exato depende do setting global video_container do WanGP —
        # aceitar todos garante que PASSO 10 funciona independente do container selecionado.
        # Para imagem (image_mode=1), não restringir (retorna jpg/png).
        _req_suffix = [".mp4", ".mov", ".mkv"] if image_mode == 0 else None
        new_files = _wait_new_output(before, timeout=_output_timeout, job_id=job_id, job_start_time=job_start_time, require_suffix=_req_suffix,
                                     multi_window=(_img_mp_gen_type == "PW"))   # [MULTI-CENA] Story AV: espera todas as janelas + pega o final
        _perf_ts("T17_output_detected")
        _t14_abs = time.time()
        print(f"[PERF-TIMER] TOTAL job={job_id} from T1_lock to T17_output: {_t14_abs-_perf_t0:.1f}s")
        # ── IMG-PERF: T13 final step + T14 output + TOTAL summary ─
        if _is_image_job:
            _t12_ts  = jobs[job_id].get("t12_first_step")
            _t13_ts  = jobs[job_id].get("t13_last_step")
            _t13_idx = jobs[job_id].get("t13_last_step_idx", "?")
            _inference_s = round(_t13_ts - _t12_ts, 3) if (_t12_ts and _t13_ts) else None
            _setup_s     = round(_t12_ts - _perf_t0, 3) if _t12_ts else None
            _total_lock  = round(_t14_abs - _perf_t0, 3)
            _total_t1    = round(_t14_abs - _t1, 3)
            if _t13_ts:
                print(
                    f"[IMG-PERF] T13_final_step"
                    f"  step_idx={_t13_idx}"
                    f"  +lock={(_t13_ts-_perf_t0):.3f}s"
                    f"  +T1={(_t13_ts-_t1):.3f}s"
                )
            print(
                f"[IMG-PERF] T14_output_saved"
                f"  +lock={_total_lock:.3f}s"
                f"  +T1={_total_t1:.3f}s"
            )
            print(
                f"\n[IMG-PERF] ═══ TOTAL BREAKDOWN job={job_id} ═══\n"
                f"  T1→lock          (queue_wait)     : {(job_start_time-_t1):.3f}s\n"
                f"  lock→new_client                   : {_img_perf.get('T2_browser_session_started', _perf_t0) - _perf_t0:.3f}s\n"  # noqa
                f"  T2→T3 (browser_session+family)    : (see above lines)\n"
                f"  T_change_model                    : {_cm_elapsed:.3f}s  ({_cache_result})\n"
                f"  T5→T11 (setup_after_model)        : {(_img_perf.get('T11_process_tasks',_t14_abs) - _img_perf.get('T5_change_resolution_group',_perf_t0)):.3f}s\n"  # noqa
                f"  T11→T12 (submit→first_step)       : {((_t12_ts or _t14_abs) - _img_perf.get('T11_process_tasks',_perf_t0)):.3f}s\n"  # noqa
                f"  T12→T13 (inference_only)          : {_inference_s if _inference_s is not None else '?'}s\n"
                f"  T13→T14 (finalize+file_detect)    : {((_t14_abs - (_t13_ts or _t14_abs))):.3f}s\n"
                f"  TOTAL from lock                   : {_total_lock:.3f}s\n"
                f"  TOTAL from T1 (request_received)  : {_total_t1:.3f}s\n"
                f"  setup_overhead (lock→first_step)  : {_setup_s if _setup_s is not None else '?'}s\n"
                f"  change_model share                : {round(100*_cm_elapsed/_total_lock, 1) if _total_lock else '?'}%\n"
                f"═══════════════════════════════════════"
            )
            # Atualiza acs_last_image_payload.json com timings finais
            try:
                import json as _json
                _img_payload_path = Path(__file__).parent / "acs_last_image_payload.json"
                if _img_payload_path.exists():
                    _existing = _json.loads(_img_payload_path.read_text(encoding="utf-8"))
                    _existing["perf_timers"] = {
                        "T1_request_received_abs":  _t1,
                        "T_lock_acquired_abs":       job_start_time,
                        "T_lock_wait_s":             round(job_start_time - _t1, 3),
                        "T_change_model_s":          round(_cm_elapsed, 3),
                        "T_change_model_result":     _cache_result,
                        "T_change_model_same_checkpoint": _is_same_checkpoint,
                        "T12_first_step_s_from_lock": _setup_s,
                        "T13_last_step_s_from_lock":  round(_t13_ts - _perf_t0, 3) if _t13_ts else None,
                        "T_inference_s":              _inference_s,
                        "T14_output_s_from_lock":     _total_lock,
                        "T14_output_s_from_T1":       _total_t1,
                        "setup_overhead_s":           _setup_s,
                        "img_perf_checkpoints":       {k: round(v - _t1, 3) for k, v in _img_perf.items()},
                    }
                    _img_payload_path.write_text(
                        _json.dumps(_existing, indent=2, ensure_ascii=False)
                    )
                    print(f"[IMG-PERF] Payload atualizado com timers: {_img_payload_path}")
            except Exception as _tpe:
                print(f"[IMG-PERF] Erro ao atualizar payload com timers: {_tpe}")

        # T12-CP3: evita cancelled→done, output parcial na galeria e sobrescrita de status
        if jobs[job_id].get("status") == "cancelled":
            print(f"[ACS API] job {job_id} | cancelado — ignorando output detectado")
            return

        if new_files:
            # Filtra por tipo esperado: vídeo (.mp4) ou imagem (.jpg/.png)
            # Ignora .wav e outros arquivos gerados por MMAudio em paralelo
            if image_mode == 0:
                preferred = [f for f in new_files if Path(f).suffix.lower() == ".mp4"]
            else:
                preferred = [f for f in new_files
                             if Path(f).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]
            # Sem fallback perigoso — tipo inesperado = falha limpa, não captura arquivo errado
            if not preferred:
                tipo = "imagem (.jpg/.png)" if image_mode else "vídeo (.mp4)"
                _fail(f"Nenhum arquivo do tipo esperado ({tipo}) encontrado após geração")
                return
            candidates = preferred

            # Pega o mais recente entre os candidatos
            newest = sorted(
                candidates,
                key=lambda n: (OUTPUTS_DIR / n).stat().st_mtime,
                reverse=True
            )[0]
            path = OUTPUTS_DIR / newest
            size_mb = round(path.stat().st_size / 1024 / 1024, 2)

            jobs[job_id]["status"]   = "done"
            jobs[job_id]["progress"] = 100
            jobs[job_id]["step"]     = "concluído"
            jobs[job_id]["output"]   = {
                "filename": newest,
                "url":      f"/file/{newest}",
                "size_mb":  size_mb,
            }
            print(f"[ACS API] job {job_id} CONCLUIDO: {newest} ({size_mb} MB)")

            # [AUDIO-MUX 06-28] O cano-novo (WanGPSession) pula o post-proc de áudio do motor →
            # vídeo sai MUDO. Se pediram reusar o áudio do vídeo de controle (mmaudio=3, ex.: Scail2)
            # e o output não tem áudio, muxa o áudio do control video direto (ffmpeg, -c:v copy = rápido).
            try:
                _ctrl_v = getattr(req, "mux_audio_path", "") or ""
                if _ctrl_v and os.path.exists(_ctrl_v):
                    import subprocess as _sp2
                    _ffm  = str(WAN2GP_DIR / "ffmpeg_bins" / "ffmpeg.exe")
                    _ffp2 = str(WAN2GP_DIR / "ffmpeg_bins" / "ffprobe.exe")
                    _actrl = _sp2.run([_ffp2,"-v","error","-select_streams","a","-show_entries","stream=index","-of","csv=p=0",_ctrl_v], capture_output=True, text=True).stdout.strip()
                    _aout  = _sp2.run([_ffp2,"-v","error","-select_streams","a","-show_entries","stream=index","-of","csv=p=0",str(path)], capture_output=True, text=True).stdout.strip()
                    if _actrl and not _aout:
                        _tmp = str(path) + ".muxed.mp4"
                        _r = _sp2.run([_ffm,"-y","-i",str(path),"-i",_ctrl_v,"-map","0:v","-map","1:a:0","-c:v","copy","-c:a","aac","-shortest",_tmp], capture_output=True, text=True)
                        if _r.returncode == 0 and os.path.exists(_tmp):
                            os.replace(_tmp, str(path))
                            print(f"[AUDIO-MUX] audio do control video muxado em {newest}")
                        else:
                            print(f"[AUDIO-MUX] falhou rc={_r.returncode}: {_r.stderr[:160]}")
            except Exception as _e:
                print(f"[AUDIO-MUX] erro: {_e}")

            # ── [AUDIO PIPELINE] output log ───────────────────────
            _out_path = OUTPUTS_DIR / newest
            try:
                import subprocess as _sp, json as _json
                _ffp = str(WAN2GP_DIR / "ffmpeg_bins" / "ffprobe.exe")
                _raw = _sp.check_output(
                    [_ffp, "-v","quiet","-print_format","json","-show_streams","-show_format", str(_out_path)],
                    stderr=_sp.DEVNULL)
                _fi  = _json.loads(_raw)
                _streams = _fi.get("streams", [])
                _astr  = [s for s in _streams if s.get("codec_type") == "audio"]
                _vstr  = [s for s in _streams if s.get("codec_type") == "video"]
                _has_a = bool(_astr)
                _codec = _astr[0].get("codec_name","?") if _has_a else "—"
                _sr    = _astr[0].get("sample_rate","?") if _has_a else "—"
                _ch    = _astr[0].get("channels","?") if _has_a else "—"
                _adur  = _astr[0].get("duration","?") if _has_a else "—"
                _n_str = len(_streams)
                print(
                    f"[AUDIO PIPELINE] output {newest}\n"
                    f"  audio_detected = {'YES' if _has_a else 'NO'}\n"
                    f"  num_streams    = {_n_str}  ({len(_vstr)} video + {len(_astr)} audio)\n"
                    f"  codec          = {_codec}\n"
                    f"  sample_rate    = {_sr} Hz\n"
                    f"  channels       = {_ch}\n"
                    f"  audio_duration = {_adur} s\n"
                )
            except Exception as _e:
                print(f"[AUDIO PIPELINE] ffprobe erro: {_e}")
        else:
            # [B39-BLOCK-003] Download travado/excedido tem PRIORIDADE: mensagem de CONEXÃO,
            # nunca "Timeout: nenhum vídeo gerado" (que confunde — não era a geração travada).
            _dod_err = jobs.get(job_id, {}).get("_abort_dod")
            # Fix GRADIO-ERR: se abortado por erro Wan2GP, reportar a mensagem real
            _abort_err = jobs.get(job_id, {}).get("_abort_passo10")
            if _dod_err and isinstance(_dod_err, str):
                _fail(_dod_err)
            elif _abort_err and isinstance(_abort_err, str):
                _fail(f"Erro no Motor de IA: {_abort_err}")
            elif jobs.get(job_id, {}).get("_abort_passo10"):
                # flag está definida mas sem mensagem — recuperar da última sinalização
                _fail(
                    "Erro de geração no Motor de IA (RAM/VRAM insuficiente ou parâmetro inválido).\n"
                    "Tente uma resolução menor ou um perfil mais leve.\n"
                    "Consulte os logs do sistema para detalhes."
                )
            else:
                # Timeout genuíno: collect last lines from wan2gp.log to help diagnose
                _wgp_log_tail = ""
                try:
                    _wgp_log_path = BASE_DIR.parent / "user" / "logs" / "wan2gp.log"
                    if not _wgp_log_path.exists():
                        _wgp_log_path = BASE_DIR / ".." / "user" / "logs" / "wan2gp.log"
                    if _wgp_log_path.exists():
                        _lines = _wgp_log_path.read_text(encoding="utf-8", errors="replace").splitlines()
                        _tail  = _lines[-20:] if len(_lines) >= 20 else _lines
                        _wgp_log_tail = "\n\nÚltimas linhas do log:\n" + "\n".join(_tail)
                except Exception:
                    pass
                _tipo = "imagem" if image_mode else "vídeo"
                _fail(
                    f"Timeout: nenhum {_tipo} gerado após {_output_timeout}s.\n"
                    f"Consulte os logs do sistema para detalhes."
                    + _wgp_log_tail
                )

    except Exception as e:
        _fail("Erro inesperado no background", e)
    finally:
        # Fix C1: limpar futures do dict — evita referências antigas após job terminal
        jobs[job_id].pop("cm_job", None)
        jobs[job_id].pop("gen_job", None)
        if _lock_acquired:
            _generation_lock.release()
            print(f"[ACS API] job {job_id} | lock liberado")


# ──────────────────────────────────────────────
# GERAÇÃO DE ÁUDIO — fluxo 9 passos (TTS / Music)
# Adaptado de _generate_background para modelos da família "tts".
# Diferenças: gallery_tab=1.0, video_length=0, duration_seconds real,
# detecção de .wav/.mp3/.flac em outputs.
# ──────────────────────────────────────────────
_AUDIO_OUTPUT_EXTS = {".wav", ".mp3", ".flac", ".aac", ".m4a", ".ogg"}

def _generate_audio_background(job_id: str, req: AudioGenerateRequest):
    """
    Executa geração de áudio via API Gradio (modelos TTS / ACE-Step).
    Segue os mesmos 9 passos do _generate_background mas com params de áudio.
    """
    # [FIX-PROMPT] limpa   e afins ANTES de qualquer chamada Gradio (quebram o JSON)
    try:
        req.prompt = _sanitize_prompt(req.prompt)
        if getattr(req, "negative_prompt", None):
            req.negative_prompt = _sanitize_prompt(req.negative_prompt)
    except Exception as _e:
        print(f"[ACS AUDIO] [FIX-PROMPT] aviso ao sanitizar: {_e}")

    # [WANSESSION #3-audio] Caminho NOVO (flag ON): pula o balé Gradio de áudio.
    if _USE_WANSESSION and WAN is not None:
        import os as _os
        from acs_wansession_path import run_wansession_audio, run_with_live_progress
        try:
            jobs[job_id]["status"]   = "generating"
            jobs[job_id]["progress"] = 50
            _reqd = req.model_dump() if hasattr(req, "model_dump") else req.dict()
            _mt   = (MODELS.get(req.model) or {}).get("model_id", "")
            _r    = run_with_live_progress(jobs, job_id,
                        lambda: run_wansession_audio(WAN, _reqd, _mt))
            if not _r.get("ok"):
                jobs[job_id]["status"] = "error"
                jobs[job_id]["error"]  = _r.get("error", "erro no Motor de IA")
                return
            _p  = _r["path"]; _fn = _os.path.basename(_p)
            _sz = round(_os.path.getsize(_p) / 1024 / 1024, 2) if _os.path.exists(_p) else 0
            jobs[job_id]["status"]   = "done"
            jobs[job_id]["progress"] = 100
            jobs[job_id]["step"]     = "concluído"
            jobs[job_id]["output"]   = {"filename": _fn, "url": f"/file/{_fn}", "size_mb": _sz}
            print(f"[ACS AUDIO] [WANSESSION] job {job_id} CONCLUIDO: {_fn} ({_sz} MB)")
        except Exception as _e:
            jobs[job_id]["status"] = "error"
            jobs[job_id]["error"]  = f"Motor de IA: {_e}"
            print(f"[ACS AUDIO] [WANSESSION] ERRO job {job_id}: {_e}")
        return

    def _step(step: str, progress: int):
        jobs[job_id]["step"] = step
        jobs[job_id]["progress"] = progress
        print(f"[ACS AUDIO] job {job_id} | {step}")

    def _fail(msg: str, exc: Exception = None):
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"] = f"{msg}: {exc}" if exc else msg
        print(f"[ACS AUDIO] ERRO job {job_id}: {msg}" + (f" — {exc}" if exc else ""))

    _lock_acquired = False  # flag para finally saber se precisa liberar o lock

    try:
        # ── Resolve modelo ────────────────────────────────────
        model_info = MODELS.get(req.model)
        if not model_info:
            _fail(f"Modelo desconhecido: {req.model}")
            return
        if model_info.get("image_mode") != 2:
            _fail(f"Modelo '{req.model}' não é um modelo de áudio. Use /generate/ para vídeo/imagem.")
            return

        family    = model_info["family"]   # "tts"
        base_type = model_info["base_type"]
        model_id  = model_info["model_id"]

        # ── Resolve num_inference_steps ───────────────────────
        # -1 = usa default do modelo; caso contrário usa o valor pedido
        _num_steps = req.num_inference_steps
        if _num_steps < 1:
            _num_steps = model_info.get("default_steps", 60)

        # ── Verifica arquivos de referência ───────────────────
        for label, path in [("audio_guide", req.audio_guide), ("audio_guide2", req.audio_guide2)]:
            if path and not Path(path).exists():
                _fail(f"Arquivo {label} não encontrado: {path}")
                return

        # ── Custom settings → slots custom_setting_1..5 ──────
        cs_slots = _build_audio_custom_slots(base_type, req.custom_settings)

        # ── model_mode: None ou int/str dependendo do modelo ─
        # ace_step_v1_5 aceita int (0=default), outros: None
        _model_mode = None
        if req.model_mode is not None:
            try:
                _model_mode = int(req.model_mode)
            except (ValueError, TypeError):
                _model_mode = req.model_mode

        # Enquanto aguarda o lock: status amigável visível no frontend
        jobs[job_id]["status"]   = "queued"
        jobs[job_id]["step"]     = "Aguardando na fila..."
        jobs[job_id]["progress"] = 0
        print(f"[ACS AUDIO] job {job_id} | aguardando lock de geração")
        # [B38-LOCK-FIX] acquire com timeout — evita starvation (mesmo motivo do path imagem/vídeo)
        if not _generation_lock.acquire(timeout=20):
            _fail("Sistema ocupado processando outra geração. Tente novamente em instantes.")
            return
        _lock_acquired = True

        # Fix T10-A: registrar instante real de início (após lock) — usado como gate de mtime
        job_start_time = time.time()
        jobs[job_id]["job_start_time"] = job_start_time

        jobs[job_id]["status"] = "running"
        _step("Iniciando geração...", 5)

        # [ERR-09] garante o motor bootado com o modelo certo (reinicia se trocou de família)
        _ensure_engine_model(model_id)

        # Snapshot tirado DENTRO do lock — garante que não há outro job gerando
        before = _snapshot_outputs()

        client = new_client()

        # ── PASSO 1: browser_session_started ─────────────────
        _step("PASSO 1: browser_session_started", 8)
        try:
            client.predict(api_name="/browser_session_started")
        except Exception as e:
            print(f"[ACS AUDIO] browser_session_started aviso: {e}")
        time.sleep(0.1)  # [C2-PERF AUDIO] 0.5→0.1 — fire-and-forget state call

        # ── PASSO 2: change_model_family("tts") ───────────────
        _step(f"PASSO 2: change_model_family('{family}')", 12)
        try:
            client.predict(family, api_name=_API_CHANGE_MODEL_FAMILY)
        except Exception as e:
            print(f"[ACS AUDIO] change_model_family aviso: {e}")
        time.sleep(0.1)  # [C2-PERF AUDIO] 0.3→0.1 — state update, sem side-effects

        # ── PASSO 3: change_model_base_types ─────────────────
        _step(f"PASSO 3: change_model_base_types('{family}', '{base_type}')", 16)
        try:
            client.predict(family, base_type, api_name=_API_CHANGE_BASE_TYPES)
        except Exception as e:
            print(f"[ACS AUDIO] change_model_base_types aviso: {e}")
        time.sleep(0.1)  # [C2-PERF AUDIO] 0.3→0.1 — state update

        # ── PASSO 4: change_model ─────────────────────────────
        _step(f"PASSO 4: change_model('{model_id}')", 20)
        try:
            client.predict(model_id, api_name=_API_CHANGE_MODEL)
        except Exception as e:
            _fail("change_model falhou", e)
            return
        time.sleep(0.2)  # [C2-PERF AUDIO] 0.8→0.2 — modelo já carregado, settle mínimo

        # ── PASSO 4.5: change_resolution_group ───────────────
        # Necessário para estabilizar o estado Gradio após change_model.
        # Sem esta chamada, sample_solver pode ficar em estado inconsistente
        # (value="euler", choices=[""]) causando erro de validação no save_inputs.
        # Áudio usa 832x480 → grupo "480p".
        _step("PASSO 4.5: change_resolution_group('480p')", 24)
        try:
            client.predict("480p", api_name="/change_resolution_group")
        except Exception as e:
            print(f"[ACS AUDIO] change_resolution_group aviso (não crítico): {e}")
        time.sleep(0.1)  # [C2-PERF AUDIO] 0.3→0.1 — state update

        # ── PASSO 5: save_inputs (áudio) ──────────────────────
        _step("PASSO 5: save_inputs (áudio)", 28)
        _audio_guide_param  = _wrap_file(req.audio_guide)  if req.audio_guide  else None
        _audio_guide2_param = _wrap_file(req.audio_guide2) if req.audio_guide2 else None

        print(
            f"\n[AUDIO GENERATE] job {job_id}\n"
            f"  model            = {req.model}\n"
            f"  prompt_length    = {len(req.prompt)}\n"
            f"  alt_prompt       = {req.alt_prompt[:60] if req.alt_prompt else 'none'}\n"
            f"  duration         = {req.duration_seconds}s\n"
            f"  seed             = {req.seed}\n"
            f"  temperature      = {req.temperature}\n"
            f"  guidance_scale   = {req.guidance_scale}\n"
            f"  audio_prompt_type= {req.audio_prompt_type}\n"
            f"  audio_guide      = {req.audio_guide or 'none'}\n"
            f"  audio_guide2     = {req.audio_guide2 or 'none'}\n"
            f"  audio_scale      = {req.audio_scale}\n"
            f"  top_k            = {req.top_k}\n"
            f"  top_p            = {req.top_p}\n"
            f"  alt_guidance     = {req.alt_guidance_scale}\n"
            f"  model_mode       = {_model_mode}\n"
            f"  custom_slots     = {cs_slots}\n"
        )
        _audio_save_kw = dict(
                target            = "state",
                image_mask_guide  = None,
                lset_name         = "",
                client_id         = "",
                image_mode        = 0,           # áudio: image_mode=0 (Wan2GP usa audio_only flag)
                prompt            = req.prompt,
                alt_prompt        = req.alt_prompt,
                negative_prompt   = "",
                resolution        = "832x480",   # valor neutro — áudio ignora resolução
                video_length      = 0,           # CRÍTICO: 0 para áudio
                duration_seconds  = float(req.duration_seconds),
                pause_seconds     = 0,
                batch_size        = 1,
                seed              = req.seed,
                force_fps         = "",
                num_inference_steps      = _num_steps,  # default por modelo: v1.0=60, v1.5 Turbo=8
                guidance_scale           = req.guidance_scale,
                guidance2_scale          = 5,
                guidance3_scale          = 5,
                switch_threshold         = 0,
                switch_threshold2        = 0,
                guidance_phases          = 1,
                model_switch_phase       = 1,
                alt_guidance_scale       = req.alt_guidance_scale,
                alt_scale                = 0.0,
                audio_guidance_scale     = 4,
                audio_scale              = req.audio_scale,
                flow_shift               = 5.0,
                sample_solver            = MODELS.get(req.model, {}).get("sample_solver", ""),  # [BUG-04] TTS/ACE-Step→"" ; [12.24] Stable Audio 3 precisa "pingpong" (lido do MODELS)
                embedded_guidance_scale  = 1.0,
                repeat_generation        = req.num_generations,
                multi_prompts_gen_type   = "FG",
                multi_images_gen_type    = 0,
                skip_steps_cache_type    = "",
                skip_steps_multiplier    = 1.75,
                skip_steps_start_step_perc = 0,
                loras_choices            = [],
                loras_multipliers        = "",
                image_prompt_type        = "",   # sem condicionamento de imagem
                image_start              = [],
                image_end                = [],
                model_mode               = _model_mode,
                video_source             = None,
                keep_frames_video_source = "",
                input_video_strength     = 1.0,
                video_guide_outpainting  = "#",
                video_guide_outpainting_ratio = "",
                video_prompt_type        = "",
                image_refs               = [],
                frames_positions         = "",
                video_guide              = None,
                image_guide              = None,
                keep_frames_video_guide  = "",
                denoising_strength       = 1.0,
                masking_strength         = 0.25,
                video_mask               = None,
                image_mask               = None,
                control_net_weight       = 1,
                control_net_weight2      = 1,
                control_net_weight_alt   = 1,
                motion_amplitude         = 1.0,
                mask_expand              = 0,
                audio_guide              = _audio_guide_param,
                audio_guide2             = _audio_guide2_param,
                custom_guide             = None,
                audio_source             = None,
                # [1177-FIX] seedvc params at correct idx 66-67 (after audio_source)
                seedvc_voice_sample      = None,
                seedvc_voice_sample2     = None,
                audio_prompt_type        = req.audio_prompt_type,
                speakers_locations       = "0:45 55:100",
                sliding_window_size      = 81,
                sliding_window_overlap   = 5,
                sliding_window_color_correction_strength = 0,
                sliding_window_overlap_noise             = 0,
                sliding_window_discard_last_frames       = 0,
                image_refs_relative_size = 50,
                remove_background_images_ref = 0,
                temporal_upsampling      = getattr(req, "temporal_upsampling",  ""),
                spatial_upsampling       = getattr(req, "spatial_upsampling",   ""),
                film_grain_intensity     = getattr(req, "film_grain_intensity",  0),    # [FIX-BLOCKER-02]
                film_grain_saturation    = getattr(req, "film_grain_saturation", 0.5),  # [FIX-BLOCKER-02]
                postprocess_audio        = "",    # [1177] substitui MMAudio_setting
                MMAudio_prompt           = "",
                MMAudio_neg_prompt       = "",
                RIFLEx_setting           = 0,
                NAG_scale                = 1,
                NAG_tau                  = 3.5,
                NAG_alpha                = 0.5,
                perturbation_switch      = 0,
                perturbation_layers      = [9],
                perturbation_start_perc  = 10,
                perturbation_end_perc    = 90,
                apg_switch               = 0,
                cfg_star_switch          = 0,
                cfg_zero_step            = -1,
                prompt_enhancer          = "T",
                min_frames_if_references = 1,
                override_profile         = -1,
                override_attention       = "",
                temperature              = req.temperature,
                custom_setting_1         = cs_slots[0],
                custom_setting_2         = cs_slots[1],
                custom_setting_3         = cs_slots[2],
                custom_setting_4         = cs_slots[3],
                custom_setting_5         = cs_slots[4],
                top_p                    = req.top_p,
                top_k                    = req.top_k,
                self_refiner_setting     = 0,
                self_refiner_f_uncertainty      = 0.0,
                self_refiner_certain_percentage = 0.999,
                output_filename          = "",
                mode                     = "",
                api_name                 = "/save_inputs",
        )
        # [12.24-API] migração da assinatura do save_inputs (áudio) — espelha o caminho de vídeo.
        if _API_V2:
            _amm_p  = _audio_save_kw.pop("MMAudio_prompt", "")
            _amm_np = _audio_save_kw.pop("MMAudio_neg_prompt", "")
            _avs1   = _audio_save_kw.pop("seedvc_voice_sample", None)
            _avs2   = _audio_save_kw.pop("seedvc_voice_sample2", None)
            _audio_save_kw.update({
                "postprocess_audio_prompt": _amm_p,
                "postprocess_audio_neg_prompt": _amm_np,
                "replace_voice_method": "",
                "replace_voice_sample": _avs1,
                "replace_voice_sample2": _avs2,
                "sliding_window_trim_first_frames": 0,
            })
            for _i in range(1, 6):
                _audio_save_kw[f"custom_setting_dropdown_{_i}"] = None
                _audio_save_kw[f"custom_setting_slider_{_i}"]   = 0
        # ── ACS-ERR-0041 resilience para áudio ────────────────────────────────
        # Mesmo padrão do handler de vídeo/imagem: se sample_solver inválido para
        # o modelo atual, parseia choices do erro e reenvia. 1 retry, sem loop.
        # Causa: após Wan model ("euler"), Gradio state persiste choices antigas.
        # Audio TTS usa "" normalmente; se por alguma razão choices=['euler',...],
        # o fallback seleciona "euler" (preferência) → sem falha silenciosa.
        try:
            job_save = client.submit(**_audio_save_kw)
            try:
                job_save.result()
            except Exception as _e_save:
                _err_save = str(_e_save)
                if "is not in the list of choices" in _err_save:
                    # [BUG-AUDIO-01] Detecta QUAL dropdown falhou: model_mode (idioma TTS de voz)
                    # ou sample_solver. Regex aceita choices VAZIO [] ([^\]]* em vez de +).
                    # O valor que falhou distingue: token de solver vs código de idioma (ex.: "pt").
                    _m_choices = re.search(r"list of choices:\s*\[([^\]]*)\]", _err_save)
                    _m_failing = re.search(r"Value:\s*(\S+)\s+is not in the list", _err_save)
                    if _m_choices is not None:
                        _valid = [c.strip().strip("'\"") for c in _m_choices.group(1).split(",") if c.strip()]
                        _failing_val = _m_failing.group(1).strip("'\"") if _m_failing else ""
                        _SOLVER_TOKENS = {"", "euler", "unipc", "dpm++", "res2s", "heun", "pingpong"}
                        if _failing_val and _failing_val not in _SOLVER_TOKENS:
                            # ── BUG-AUDIO-01: dropdown de idioma (model_mode) inválido ──
                            # Ocorre em chatterbox/qwen/index/kugel. O frontend envia o CÓDIGO
                            # ISO ("pt"), mas o Wan2GP espera o NOME completo ("portuguese").
                            # Estratégia: 1) mapeia código→nome se estiver nas choices;
                            #             2) senão "auto"; 3) senão 1º choice; 4) None se vazio.
                            _LANG_MAP = {
                                "pt": "portuguese", "en": "english", "es": "spanish",
                                "fr": "french", "de": "german", "it": "italian",
                                "ja": "japanese", "ko": "korean", "zh": "chinese",
                                "ru": "russian", "ar": "arabic", "hi": "hindi",
                                "nl": "dutch", "pl": "polish", "tr": "turkish",
                                "sv": "swedish", "da": "danish", "fi": "finnish",
                                "no": "norwegian", "el": "greek", "he": "hebrew",
                                "ms": "malay", "sw": "swahili",
                            }
                            _mapped = _LANG_MAP.get(_failing_val.lower())
                            if _mapped and _mapped in _valid:
                                _fb_mm = _mapped
                            elif "auto" in _valid:
                                _fb_mm = "auto"
                            else:
                                _fb_mm = _valid[0] if _valid else None
                            print(
                                f"[ACS AUDIO] model_mode fallback (BUG-AUDIO-01): "
                                f"'{_failing_val}' -> {_fb_mm!r} choices={_valid} job={job_id}"
                            )
                            _audio_save_kw["model_mode"] = _fb_mm
                            job_save = client.submit(**_audio_save_kw)
                            job_save.result()  # se falhar de novo → propaga
                        else:
                            # ── ACS-ERR-0041: sample_solver inválido ──
                            _fb_solver = next(
                                (c for c in ("", "euler", "unipc", "dpm++") if c in _valid),
                                _valid[0] if _valid else "",
                            )
                            _orig_solver = _audio_save_kw["sample_solver"]
                            print(
                                f"[ACS AUDIO] sample_solver fallback (ACS-ERR-0041): "
                                f"'{_orig_solver}' -> '{_fb_solver}' "
                                f"choices={_valid} job={job_id}"
                            )
                            _audio_save_kw["sample_solver"] = _fb_solver
                            job_save = client.submit(**_audio_save_kw)
                            job_save.result()  # se falhar de novo → propaga
                    else:
                        raise _e_save  # choices não parseáveis → propaga
                else:
                    raise _e_save  # erro diferente → propaga
        except Exception as e:
            import traceback as _tb
            print(f"[ACS AUDIO] save_inputs ERRO COMPLETO:\n{_tb.format_exc()}")
            _fail("save_inputs (áudio) falhou", e)
            return
        time.sleep(0.1)  # [C2-PERF AUDIO] 0.3→0.1 — save_inputs é síncrono (.result() já esperou)

        # ── PASSO 6: validate_wizard_prompt ──────────────────
        _step("PASSO 6: validate_wizard_prompt", 40)
        try:
            client.predict(
                "off", "", req.prompt,
                "", "", "", "", "", "", "", "", "", "", "",
                api_name="/validate_wizard_prompt"
            )
        except Exception as e:
            _fail("validate_wizard_prompt falhou", e)
            return
        # [C2-PERF AUDIO] validate retorna valor — sem sleep necessário (era 0.2s)

        # ── PASSO 7: process_prompt_and_add_tasks (tab=1.0 → áudio) ──
        _step("PASSO 7: process_prompt_and_add_tasks (gallery_tab=1.0)", 50)
        try:
            client.predict(
                _GALLERY_TAB_AUDIO,   # gallery_tab=1.0 → gen["last_was_audio"]=True
                model_id,
                api_name="/process_prompt_and_add_tasks"
            )
        except Exception as e:
            _fail("process_prompt_and_add_tasks falhou", e)
            return

        # ── PASSO 8: prepare_generate_video ──────────────────
        _step("PASSO 8: prepare_generate_video", 55)
        try:
            client.predict(api_name=_API_PREPARE_GENERATE)
        except Exception as e:
            print(f"[ACS AUDIO] prepare_generate_video aviso: {e}")
        time.sleep(0.1)  # [C2-PERF AUDIO] 0.3→0.1 — prepare é síncrono

        # ── PASSO 9: process_tasks → geração real ────────────
        _step("PASSO 9: process_tasks (gerando áudio...)", 60)
        jobs[job_id]["status"] = "generating"

        gen_job = client.submit(api_name="/process_tasks")

        # Timeout longo: cobre download inicial do modelo (~20 min para 6 GB)
        # + carregamento em VRAM (~2 min) + geração real (~1-3 min).
        # Após o primeiro download, chamadas subsequentes levam apenas 2-5 min.
        _AUDIO_WAIT_TIMEOUT = 3600   # 1 hora — first-time download seguro
        _GRADIO_SIGNAL_TIMEOUT = _AUDIO_WAIT_TIMEOUT + 60  # margem extra

        def _wait_gradio_signal():
            try:
                gen_job.result(timeout=_GRADIO_SIGNAL_TIMEOUT)
                print(f"[ACS AUDIO] job {job_id} | process_tasks: Gradio sinalizou conclusão")
            except Exception as e:
                err_str = str(e)
                print(f"[ACS AUDIO] job {job_id} | process_tasks signal: {err_str}")
                # [FIX-AUDIO-GRADIO-ERR] Espelha o caminho de vídeo (GRADIO-ERR): se o
                # Wan2GP/ACE-Step retornar erro (ex.: "Prompt text cannot be empty",
                # OOM, parâmetro inválido), aborta o PASSO 10 em vez de esperar 1h por
                # um arquivo que nunca virá (app parecia travado pro aluno).
                _is_real_error = (
                    "encountered an error" in err_str
                    or "cannot be empty" in err_str
                    or "unsufficient RAM" in err_str
                    or "insufficient RAM" in err_str
                    or "ValueError" in err_str
                    or "GradioError" in type(e).__name__
                    or "AppError" in type(e).__name__
                    or "Error" in type(e).__name__
                ) and "timeout" not in err_str.lower() and "TimeoutError" not in type(e).__name__
                if _is_real_error and job_id in jobs:
                    print(f"[ACS AUDIO] job {job_id} | GRADIO-ERR: abortando PASSO 10 — {err_str[:200]}")
                    jobs[job_id]["_abort_passo10"] = err_str

        t_gradio = threading.Thread(target=_wait_gradio_signal, daemon=True)
        t_gradio.start()

        # ── PASSO 10: detectar arquivo de áudio gerado ────────
        # Polling a cada 2s; timeout cobre download + carga + geração
        _step("PASSO 10: aguardando arquivo de áudio", 90)
        # [FIX-AUDIO-SUFFIX] Passa require_suffix para ignorar arquivos de vídeo (.mp4/.mov)
        # que podem aparecer no OUTPUTS_DIR durante a geração de áudio (jobs de vídeo simultâneos
        # ou jobs pendentes do Gradio completando). Sem este filtro, _wait_new_output retorna
        # o .mp4 imediatamente e o handler falha com "nenhum arquivo de áudio encontrado".
        new_files = _wait_new_output(before, timeout=_AUDIO_WAIT_TIMEOUT, job_id=job_id, job_start_time=job_start_time, require_suffix=list(_AUDIO_OUTPUT_EXTS))

        if new_files:
            # Filtra por extensões de áudio — sem fallback perigoso
            audio_files = [f for f in new_files if Path(f).suffix.lower() in _AUDIO_OUTPUT_EXTS]
            if not audio_files:
                _fail("Nenhum arquivo de áudio (.wav/.mp3/.flac) encontrado após geração")
                return
            candidates = audio_files

            newest = sorted(
                candidates,
                key=lambda n: (OUTPUTS_DIR / n).stat().st_mtime,
                reverse=True
            )[0]
            path    = OUTPUTS_DIR / newest
            size_mb = round(path.stat().st_size / 1024 / 1024, 3)

            jobs[job_id]["status"]   = "done"
            jobs[job_id]["progress"] = 100
            jobs[job_id]["step"]     = "concluído"
            jobs[job_id]["output"]   = {
                "filename": newest,
                "url":      f"/file/{newest}",
                "size_mb":  size_mb,
            }
            print(f"[ACS AUDIO] job {job_id} CONCLUIDO: {newest} ({size_mb} MB)")
        else:
            # [FIX-AUDIO-GRADIO-ERR] Se o PASSO 10 abortou por erro do Wan2GP/ACE-Step,
            # mostrar a causa real (ex.: tags/prompt vazios) em vez de "timeout" genérico.
            _abort_msg = jobs.get(job_id, {}).get("_abort_passo10")
            if _abort_msg:
                _fail(f"A geração de áudio falhou: {str(_abort_msg)[:300]}")
            else:
                _fail("Timeout: nenhum arquivo de áudio encontrado após a geração")

    except Exception as e:
        _fail("Erro inesperado na geração de áudio", e)
    finally:
        if _lock_acquired:
            _generation_lock.release()
            print(f"[ACS AUDIO] job {job_id} | lock liberado")


# ──────────────────────────────────────────────
# PROXY GRADIO — /gradio/* → localhost:7871/*  (Wan2GP 11.77)
# Mesmo origem = JS pode acessar iframe DOM
# ──────────────────────────────────────────────
_http_client = httpx.AsyncClient(base_url=GRADIO_URL, timeout=300.0, follow_redirects=True)


@app.api_route("/gradio/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH", "HEAD", "OPTIONS"])
async def proxy_gradio(path: str, request: Request):
    url = f"{GRADIO_URL}/{path}"
    qs  = request.url.query
    if qs:
        url += f"?{qs}"

    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in ("host", "content-length", "transfer-encoding")}

    body = await request.body()
    resp = await _http_client.request(
        method=request.method, url=url, headers=headers, content=body,
    )

    resp_headers = dict(resp.headers)
    resp_headers.pop("content-encoding", None)
    resp_headers.pop("transfer-encoding", None)

    content_type = resp.headers.get("content-type", "")

    if "text/html" in content_type or "javascript" in content_type:
        text = resp.text
        text = text.replace('src="/', 'src="/gradio/')
        text = text.replace("src='/", "src='/gradio/")
        text = text.replace('href="/', 'href="/gradio/')
        text = text.replace("href='/", "href='/gradio/")
        text = text.replace('"/gradio_api', '"/gradio/gradio_api')
        text = text.replace("'/gradio_api", "'/gradio/gradio_api")
        body = text.encode("utf-8")
        resp_headers.pop("content-length", None)
        resp_headers["content-length"] = str(len(body))
        return Response(content=body, status_code=resp.status_code,
                        headers=resp_headers, media_type=content_type)

    if "text/event-stream" in content_type:
        async def event_stream():
            async for chunk in resp.aiter_bytes():
                yield chunk
        resp_headers.pop("content-length", None)
        return StreamingResponse(event_stream(), status_code=resp.status_code,
                                 headers=resp_headers, media_type=content_type)

    return Response(content=resp.content, status_code=resp.status_code,
                    headers=resp_headers, media_type=content_type)


# ──────────────────────────────────────────────
# FRONTEND ESTATICO — deve ser o ULTIMO mount
# API routes acima têm prioridade automaticamente
# ──────────────────────────────────────────────
app.mount("/", StaticFiles(directory=str(PROTOTYPE_DIR), html=True), name="frontend")


# ──────────────────────────────────────────────
# ENTRY POINT
# ──────────────────────────────────────────────
if __name__ == "__main__":
    import json as _json
    print("=" * 60)
    print(" ACS Unlimited API v0.7.0  [Build 48 WanSession]")
    print(" Port     : " + str(API_PORT))
    print(" Frontend : http://localhost:" + str(API_PORT))
    print(f" Motor IA : WanSession :{os.getenv('ACS_WAN_WORKER_PORT', '7872')}")
    print(" Outputs  : " + str(OUTPUTS_DIR))
    if _IS_DEV:
        print(" Docs     : http://localhost:" + str(API_PORT) + "/docs")
    else:
        print(" Docs     : disabled (production)")
    print("=" * 60)
    print(" Modos: t2v | i2v | flf | continue | t2i")
    # Write runtime/acs_runtime.json so launcher/bat scripts can find the live port
    try:
        _rt_dir = BASE_DIR / "runtime"
        _rt_dir.mkdir(parents=True, exist_ok=True)
        _rt_data = {
            "acs_api_port": API_PORT,
            "acs_api_url":  "http://127.0.0.1:" + str(API_PORT),
            "wan2gp_port":  7871,    # 1177 DEV stack
            "studio_url":   "http://127.0.0.1:" + str(API_PORT) + "/studio/image/",
            "health_url":   "http://127.0.0.1:" + str(API_PORT) + "/health",
        }
        (_rt_dir / "acs_runtime.json").write_text(
            _json.dumps(_rt_data, indent=2), encoding="utf-8"
        )
        print("[runtime] acs_runtime.json written -> port " + str(API_PORT))
    except Exception as _e:
        print("[runtime] WARNING: could not write acs_runtime.json: " + str(_e))
    print(" Fix v0.3: image_prompt_type correto por modo (era '' fixo)")
    print(" Fix v0.3: gallery_tab=0.0 para vídeo (era 1.0 para i2v — errado)")
    print("=" * 60)

    # ── Auto-open browser (reads auto_open_browser from acs_config.json) ──
    _cfg = _read_acs_config()
    if _cfg.get("auto_open_browser", True):
        import threading, webbrowser
        _studio_url = "http://127.0.0.1:" + str(API_PORT) + "/studio/image/"
        def _open_browser():
            import time
            time.sleep(2)  # give uvicorn a moment to bind
            print("[browser] Opening " + _studio_url)
            webbrowser.open(_studio_url)
        threading.Thread(target=_open_browser, daemon=True).start()
    else:
        print("[browser] auto_open_browser = false, skipping")

    # ── Startup integrity check (ENFORCED — blocks /generate on failure) ──
    # _INTEGRITY_OK / _INTEGRITY_ERRORS are module-level; no 'global' needed
    # because this block runs at module scope (not inside a function).
    try:
        import sys as _sys
        # tools/ can be at BASE_DIR/tools (DEV flat) or BASE_DIR.parent/tools (production layout)
        _tools = next(
            (p for p in [BASE_DIR / "tools", BASE_DIR.parent / "tools"] if p.is_dir()),
            BASE_DIR / "tools",
        )
        if str(_tools) not in _sys.path:
            _sys.path.insert(0, str(_tools))
        from acs_integrity import verify_manifest
        _ir = verify_manifest()
        if _ir.errors:
            _INTEGRITY_OK = False
            _INTEGRITY_ERRORS = list(_ir.errors)
            print(f"[integrity] CRITICAL: {_ir.errors}")
            print("[integrity] Generation BLOCKED — critical files modified.")
            print("[integrity] Reinstall or run the repair tool.")
        elif _ir.warnings:
            print(f"[integrity] Warnings: {_ir.warnings}")
        else:
            print("[integrity] All files verified OK.")
    except Exception as _ie:
        print(f"[integrity] Check skipped: {_ie}")
        # If we can't verify, allow but log — don't break first run / dev env

    if os.getenv("ACS_SMOKE_EXIT") == "1":
        print("ACS_SMOKE_PREFLIGHT_OK", flush=True)
        sys.exit(0)

    if os.getenv("ACS_NO_BROWSER") == "1":
        print("[browser] ACS_NO_BROWSER=1 — headless, skipping")

    uvicorn.run(app, host="127.0.0.1", port=API_PORT, log_level="info")

