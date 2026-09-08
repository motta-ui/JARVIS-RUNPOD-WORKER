"""
Registo de engines disponíveis. Para adicionar um novo engine (LTX, Wan,
...), criar uma pasta engines/<nome>/adapter.py com uma classe que herde
de BaseEngine, e registá-la aqui.
"""
import json
import logging

from .base import BaseEngine
from .mock.adapter import MockEngine
from .cloud_worker.adapter import CloudWorkerEngine

logger = logging.getLogger("jarvis.engines")

# Every WanGP model-family id that config_importer.py / engine_registry.py
# know about — all ~200 imported models (video/image/audio/motion) are
# Wan2GP model_types executed through the SAME Cloud Worker /run_task
# contract (see engines/cloud_worker/adapter.py docstring for the full
# rationale and the source evidence). One CloudWorkerEngine instance per
# id below, purely so the UI/registry can show a distinct name per family;
# behavior is identical for all of them.
CLOUD_WORKER_ENGINE_IDS: dict[str, str] = {
    "wan": "Wan 2.1 / 2.2", "ltx2": "LTX-2", "ltx": "LTX-Video",
    "hunyuan": "HunyuanVideo", "longcat": "LongCat", "magi": "Magi",
    "ovi": "Ovi", "lucy_edit": "Lucy Edit", "chrono_edit": "Chrono Edit",
    "flux": "Flux", "qwen_image": "Qwen-Image", "z_image": "Z-Image",
    "ideogram": "Ideogram", "hidream": "HiDream", "krea": "Krea", "kiwi": "Kiwi Edit",
    "ace_step": "ACE-Step", "stable_audio": "Stable Audio", "chatterbox": "Chatterbox",
    "index_tts": "IndexTTS", "omnivoice": "OmniVoice", "qwen_tts": "Qwen3 TTS",
    "heartmula": "HeartMuLa", "kugelaudio": "KugelAudio", "dramabox": "DramaBox Audio",
    "scenema": "Scenema Audio", "other": "Outro (Wan2GP, não classificado)",
}

_ENGINES: dict[str, BaseEngine] = {}


def register_engine(engine: BaseEngine):
    _ENGINES[engine.id] = engine


def get_engine(engine_id: str) -> BaseEngine | None:
    return _ENGINES.get(engine_id)


def list_engines() -> list[dict]:
    out = []
    for eng in _ENGINES.values():
        out.append({
            "id": eng.id,
            "name": eng.name,
            "capabilities": eng.get_capabilities(),
            "health": eng.health(),
        })
    return out


def persist_engine_snapshot():
    """Grava o estado atual dos engines na tabela `engines` (histórico/diagnóstico)."""
    from .. import database as db
    with db.db_session() as conn:
        for eng in _ENGINES.values():
            h = eng.health()
            conn.execute(
                "INSERT INTO engines (id, name, capabilities, online, detail, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(id) DO UPDATE SET name=excluded.name, capabilities=excluded.capabilities, "
                "online=excluded.online, detail=excluded.detail, updated_at=excluded.updated_at",
                (eng.id, eng.name, json.dumps(eng.get_capabilities()), int(bool(h.get("online"))),
                 h.get("detail", ""), db.now_iso()),
            )


# --- registo inicial ---
register_engine(MockEngine())

try:
    from .minimax.adapter import MiniMaxEngine
    register_engine(MiniMaxEngine())
except ImportError as e:
    logger.warning("Adapter MiniMax não registado (dependência em falta): %s", e)

for _engine_id, _engine_name in CLOUD_WORKER_ENGINE_IDS.items():
    register_engine(CloudWorkerEngine(_engine_id, _engine_name))
