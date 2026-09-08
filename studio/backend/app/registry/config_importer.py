"""
CONFIG IMPORTER

Lê os ficheiros de configuração reais em
backend/app/data/registry/workflow_configs/ — fornecidos pelo
utilizador como SOURCE DATA. São ficheiros de configuração/preset do
projeto open-source Wan2GP (autor DeepBeepMeep), que referenciam
checkpoints publicamente disponíveis no Hugging Face (LTX-2, Wan2.1/
2.2, HunyuanVideo, Flux, Qwen-Image, ACE-Step, etc.) — não são
segredo comercial nem DRM de ninguém.

Cada ficheiro é uma CONFIGURAÇÃO, não um workflow executável:
source_type="preset_config", executable=False sempre. Fica pronto
para no futuro associar um workflow executável real (grafo ComfyUI ou
pipeline nativo) a cada um.

REGRA DE OURO: nada aqui é inventado. name/architecture/description/
URLs/loras/parâmetros vêm literalmente do campo correspondente no
ficheiro. As únicas inferências feitas (engine_id, capabilities) são
heurísticas documentadas a partir de sinais reais presentes no próprio
ficheiro (nome, arquitetura, descrição, campos presentes) — nunca a
partir de nada externo ou suposto.
"""
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from ..config import DATA_DIR

CONFIGS_DIR = DATA_DIR / "registry" / "workflow_configs"

# Campos que são só exemplos de utilização, não parâmetros por omissão -
# nunca vão para "defaults".
_NON_DEFAULT_FIELDS = {"model", "prompt", "alt_prompt"}

_ENGINE_PATTERNS = [
    (r"^ltx2", "ltx2"),
    (r"^ltxv", "ltx"),
    (r"^hunyuan", "hunyuan"),
    (r"^longcat", "longcat"),
    (r"^magi", "magi"),
    (r"^ace_step", "ace_step"),
    (r"^flux", "flux"),
    (r"^qwen_image", "qwen_image"),
    (r"^qwen3_tts", "qwen_tts"),
    (r"^z_image", "z_image"),
    (r"^ideogram", "ideogram"),
    (r"^hidream", "hidream"),
    (r"^krea", "krea"),
    (r"^kiwi_edit", "kiwi"),
    (r"^ovi", "ovi"),
    (r"^lucy_edit", "lucy_edit"),
    (r"^chrono_edit", "chrono_edit"),
    (r"^stable_audio", "stable_audio"),
    (r"^chatterbox", "chatterbox"),
    (r"^index_tts", "index_tts"),
    (r"^omnivoice", "omnivoice"),
    (r"^heartmula", "heartmula"),
    (r"^kugelaudio", "kugelaudio"),
    (r"^dramabox", "dramabox"),
    (r"^scenema", "scenema"),
    (r"(t2v|i2v|ti2v|vace|flf2v|phantom|sky_df|recam|fun_inp|standin|wanmove|vista4d|multitalk|infinitetalk)", "wan"),
]


def _infer_engine_id(architecture: str, filename: str) -> str:
    """Família do engine, inferida do prefixo real da arquitetura/nome do
    ficheiro (ex.: 'ltx2_22B' -> 'ltx2'). Nunca implica que o engine está
    implementado/executável — ver engine_registry.py para isso."""
    key = f"{architecture} {filename}".lower()
    for pattern, engine_id in _ENGINE_PATTERNS:
        if re.search(pattern, key):
            return engine_id
    return "other"


def _infer_param_count(architecture: str, filename: str) -> str | None:
    """Extrai algo como '14B'/'1.3B'/'22B' literalmente do nome/arquitetura,
    quando presente — não é uma estimativa, é o que já está no texto."""
    m = re.search(r"(\d+(?:\.\d+)?B)", f"{architecture} {filename}")
    return m.group(1) if m else None


def _infer_capabilities(category: str, architecture: str, filename: str, description: str, raw: dict) -> list[str]:
    """Heurística documentada a partir de sinais reais no próprio ficheiro.
    Nunca declara uma capability sem um sinal concreto para ela."""
    key = f"{architecture} {filename}".lower()
    desc = (description or "").lower()
    model_block = raw.get("model", {}) if isinstance(raw.get("model"), dict) else {}
    caps: set[str] = set()

    if category == "video" or category == "other":
        has_core_mode = False
        if "flf2v" in key:
            caps.update({"image_to_video", "end_frame"})
            has_core_mode = True
        if re.search(r"\bi2v\b", key) or "image-to-video" in desc or "image 2 video" in desc:
            caps.add("image_to_video")
            has_core_mode = True
        if re.search(r"\bt2v\b", key) or "text-to-video" in desc or "text 2 video" in desc:
            caps.add("text_to_video")
            has_core_mode = True
        if "vace" in key:
            caps.update({"control_video", "reference_images", "injected_frames", "video_to_video"})
            has_core_mode = True
        if "multitalk" in key or "avatar" in key or "infinitetalk" in key or "fantasy" in key:
            caps.add("audio_to_video")
            has_core_mode = True
        if "infinitetalk" in key or "longcat_video" in key:
            caps.add("video_continuation")
        if "edit" in key or "edit" in desc:
            caps.add("video_to_video")
            has_core_mode = True
        if "outpaint" in desc:
            caps.add("outpainting")
        if "inpaint" in desc:
            caps.add("inpainting")
        # sinais de descrição em texto livre (descobertos ao inspecionar as
        # variantes irmãs da mesma arquitetura - ex.: ltx2_19B.json descreve
        # explicitamente o que a família ltx2 suporta, mesmo quando uma
        # variante especifica (ex.: distilled) tem uma descrição mais curta)
        if "start/end keyframe" in desc or "start and end keyframe" in desc or "start/end frame" in desc:
            caps.update({"image_to_video", "end_frame"})
            has_core_mode = True
        if "sliding-window continuation" in desc or "sliding window continuation" in desc:
            caps.add("video_continuation")
        if "audio soundtrack" in desc or "audio prompt" in desc:
            caps.update({"audio_to_video", "audio_output"})
        if not has_core_mode:
            # sem sinal explicito de t2v/i2v/vace/edit no nome ou descricao -
            # todo checkpoint de video base gera a partir de texto, por isso
            # text_to_video e a base segura (nunca reivindica i2v sem sinal).
            caps.add("text_to_video")
    elif category == "image":
        if "edit" in key or "kontext" in key or "control" in key:
            caps.add("image_to_image")
            if "control" in key:
                caps.add("control_image")
        else:
            caps.add("text_to_image")
        if model_block.get("reference_image_enabled"):
            caps.add("reference_images")
    elif category == "audio":
        caps.add("audio_output")
        if raw.get("audio_prompt_type"):
            caps.add("reference_images")

    if isinstance(model_block.get("loras"), list) and model_block.get("loras"):
        caps.add("lora")
    if isinstance(raw.get("loras_multipliers"), list) and raw.get("loras_multipliers"):
        caps.add("lora")
    if "sliding_window_size" in raw or "sliding_window_overlap" in raw:
        caps.add("sliding_window")

    return sorted(caps)


def _parse_file(path: Path, category: str) -> dict[str, Any]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    model_block = raw.get("model", {}) if isinstance(raw.get("model"), dict) else {}
    architecture = model_block.get("architecture", path.stem)
    name = model_block.get("name", path.stem)
    description = model_block.get("description", "")

    urls = model_block.get("URLs")
    if isinstance(urls, str):
        urls = [urls]  # alguns ficheiros usam URLs como alias textual (ex.: "t2v")
    elif not isinstance(urls, list):
        urls = []

    loras = model_block.get("loras", [])
    if not isinstance(loras, list):
        loras = []

    defaults = {k: v for k, v in raw.items() if k not in _NON_DEFAULT_FIELDS}

    rel_path = str(path.relative_to(CONFIGS_DIR))
    engine_id = _infer_engine_id(architecture, path.stem)
    param_count = _infer_param_count(architecture, path.stem)
    capabilities = _infer_capabilities(category, architecture, path.stem, description, raw)

    return {
        "id": path.stem,
        "name": name,
        "category": category,
        "engine_id": engine_id,
        "model_id": path.stem,
        "checkpoint": architecture,
        "workflow_id": path.stem,
        "config_source": rel_path,
        "capabilities": capabilities,
        "loras": loras,
        "loras_multipliers": model_block.get("loras_multipliers", raw.get("loras_multipliers", [])),
        "defaults": defaults,
        "requirements": {"gpu_required": True, "param_count": param_count},
        "description": description,
        "checkpoint_urls": urls,
        "status": "available",  # ficheiro de configuração real, presente no registry
    }


@lru_cache
def _load_all() -> list[dict]:
    if not CONFIGS_DIR.exists():
        return []
    out = []
    for category_dir in sorted(CONFIGS_DIR.iterdir()):
        if not category_dir.is_dir():
            continue
        category = category_dir.name
        for path in sorted(category_dir.glob("*.json")):
            try:
                out.append(_parse_file(path, category))
            except Exception:
                # um ficheiro malformado nunca deve derrubar o resto do registry
                continue
    _apply_family_capabilities(out)
    return out


def _apply_family_capabilities(entries: list[dict]) -> None:
    """Agrega capabilities por família de arquitetura (campo 'checkpoint').

    Motivo real, não estético: variantes irmãs do MESMO checkpoint (ex.:
    'ltx2_22B' tem a variante 'Dev' e a 'Distilled') partilham a mesma
    arquitetura subjacente, mas nem todos os ficheiros de configuração
    repetem a descrição completa das capacidades — um ficheiro 'Dev' pode
    descrever "Supports start/end keyframes and sliding-window
    continuation" enquanto o ficheiro 'Distilled' irmão só descreve o que
    é diferente nele (LoRAs automáticos), sem repetir o resto. Sem esta
    agregação, a variante 'Distilled' perderia modos que a arquitetura
    genuinamente suporta — foi exatamente isto que aconteceu com
    "Cinematic Pro 1.1" (ltx2_22B_distilled_1_1), reportado como regressão.

    Isto SÓ afeta 'capabilities' (o que aparece como modo/controlo na UI).
    'defaults', 'loras' e 'checkpoint_urls' NUNCA são agregados entre
    ficheiros — continuam estritamente os do ficheiro exato, para nunca
    fingir que uma variante tem parâmetros ou LoRAs de outra.
    """
    by_arch: dict[str, set[str]] = {}
    for e in entries:
        by_arch.setdefault(e["checkpoint"], set()).update(e["capabilities"])
    for e in entries:
        e["capabilities"] = sorted(by_arch[e["checkpoint"]])


def list_imported_models() -> list[dict]:
    return list(_load_all())


def get_imported_model(model_id: str) -> dict | None:
    for m in _load_all():
        if m["id"] == model_id:
            return m
    return None
