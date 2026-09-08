"""
Configuração central do JARVIS AI STUDIO.
Nada de específico de engine deve viver aqui — apenas paths, constantes
globais e carregamento dos ficheiros de configuração em data/.
"""
import json
import os
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent
DATA_DIR = BACKEND_DIR / "app" / "data"

# Diretorias de trabalho (persistentes, fora do código)
OUTPUTS_DIR = ROOT_DIR / "outputs"
PROJECTS_DIR = ROOT_DIR / "projects"
ASSETS_DIR = ROOT_DIR / "assets"
LORAS_DIR = ROOT_DIR / "loras"
DB_PATH = ROOT_DIR / "data" / "jarvis.db"

for d in (OUTPUTS_DIR, PROJECTS_DIR, ASSETS_DIR, LORAS_DIR, DB_PATH.parent):
    d.mkdir(parents=True, exist_ok=True)

# .env simples (sem dependências externas)
ENV_PATH = ROOT_DIR / ".env"
_ENV = {}
if ENV_PATH.exists():
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        _ENV[k.strip()] = v.strip()


def get_env(key: str, default: str = "") -> str:
    return os.environ.get(key, _ENV.get(key, default))


def _load_json(name: str):
    path = DATA_DIR / name
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def load_formats():
    """Matriz de formato -> resoluções. Configurável, não hardcoded na UI."""
    return _load_json("formats.json")


def load_quality_presets():
    return _load_json("quality_presets.json")


def load_steps_options():
    return _load_json("steps.json")


def load_control_video_options():
    return _load_json("control_video.json")


def load_advanced_fields():
    return _load_json("advanced_fields.json")


def load_video_modes():
    return _load_json("video_modes.json")


def load_studio_config(kind: str):
    """Configuração de um studio (video/image/audio/motion): modos, zonas de
    referência e campos extra. Tudo aqui é dado, não lógica — a UI só desenha
    o que este JSON descrever."""
    return _load_json(f"studio_{kind}.json")


def load_loras_dir():
    return LORAS_DIR


def to_media_url(path: str | None, base_dir: Path, url_prefix: str) -> str | None:
    """Turns an absolute file path saved under `base_dir` into the relative
    URL the frontend can actually load (base_dir is mounted as static files
    in main.py). Returns None for paths outside base_dir instead of
    guessing/inventing a URL that wouldn't resolve."""
    if not path:
        return None
    try:
        rel = Path(path).resolve().relative_to(base_dir.resolve())
    except ValueError:
        return None
    return f"{url_prefix}/{rel.as_posix()}"


CORS_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]
APP_NAME = "JARVIS AI STUDIO"
APP_VERSION = "0.1.0"
