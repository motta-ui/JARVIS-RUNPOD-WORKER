"""
ENGINE REGISTRY (declarativo)

Isto NÃO é o mesmo que engines/registry.py (esse é o registo dos
adapters realmente EXECUTÁVEIS). Isto é o catálogo de famílias de engine
que o Model Registry referencia (ltx2, wan, hunyuan, flux, ...).

Todas as famílias "local-diffusion"/"local-audio" abaixo apontam para o
mesmo adapter executável — "cloud_worker" (engines/cloud_worker/adapter.py,
uma instância CloudWorkerEngine por id) — porque todas correm através do
mesmo JARVIS RunPod Worker / Wan2GP, apenas em model_type diferente.
`executable=True` aqui significa "há um adapter real associado", não
"o Worker está online agora"; isso é o que `GET /api/engines` (health())
reporta em tempo real por cima disto.
"""
from functools import lru_cache

from . import config_importer

# engine_id -> (name, type, adapter executável ou None)
_KNOWN_ENGINES = {
    "mock":         ("JARVIS Mock", "demo",  "mock"),
    "minimax":      ("MiniMax H3", "api",    "minimax"),
    "ltx2":         ("LTX-2", "local-diffusion", "ltx2"),
    "ltx":          ("LTX-Video", "local-diffusion", "ltx"),
    "wan":          ("Wan 2.1 / 2.2", "local-diffusion", "wan"),
    "hunyuan":      ("HunyuanVideo", "local-diffusion", "hunyuan"),
    "longcat":      ("LongCat", "local-diffusion", "longcat"),
    "magi":         ("Magi", "local-diffusion", "magi"),
    "ovi":          ("Ovi", "local-diffusion", "ovi"),
    "lucy_edit":    ("Lucy Edit", "local-diffusion", "lucy_edit"),
    "chrono_edit":  ("Chrono Edit", "local-diffusion", "chrono_edit"),
    "flux":         ("Flux", "local-diffusion", "flux"),
    "qwen_image":   ("Qwen-Image", "local-diffusion", "qwen_image"),
    "z_image":      ("Z-Image", "local-diffusion", "z_image"),
    "ideogram":     ("Ideogram", "local-diffusion", "ideogram"),
    "hidream":      ("HiDream", "local-diffusion", "hidream"),
    "krea":         ("Krea", "local-diffusion", "krea"),
    "kiwi":         ("Kiwi Edit", "local-diffusion", "kiwi"),
    "ace_step":     ("ACE-Step", "local-audio", "ace_step"),
    "stable_audio": ("Stable Audio", "local-audio", "stable_audio"),
    "chatterbox":   ("Chatterbox", "local-audio", "chatterbox"),
    "index_tts":    ("IndexTTS", "local-audio", "index_tts"),
    "omnivoice":    ("OmniVoice", "local-audio", "omnivoice"),
    "qwen_tts":     ("Qwen3 TTS", "local-audio", "qwen_tts"),
    "heartmula":    ("HeartMuLa", "local-audio", "heartmula"),
    "kugelaudio":   ("KugelAudio", "local-audio", "kugelaudio"),
    "dramabox":     ("DramaBox Audio", "local-audio", "dramabox"),
    "scenema":      ("Scenema Audio", "local-audio", "scenema"),
    "other":        ("Outro / não classificado", "local-diffusion", "other"),
}


@lru_cache
def list_engines() -> list[dict]:
    counts: dict[str, int] = {}
    caps: dict[str, set] = {}
    for m in config_importer.list_imported_models():
        eid = m["engine_id"]
        counts[eid] = counts.get(eid, 0) + 1
        caps.setdefault(eid, set()).update(m["capabilities"])

    out = []
    for eid, (name, etype, adapter) in _KNOWN_ENGINES.items():
        out.append({
            "id": eid,
            "name": name,
            "type": etype,
            "capabilities": sorted(caps.get(eid, set())),
            "model_count": counts.get(eid, 0),
            "adapter": adapter,
            "executable": adapter is not None,
        })
    return out


def get_engine_info(engine_id: str) -> dict | None:
    return next((e for e in list_engines() if e["id"] == engine_id), None)
