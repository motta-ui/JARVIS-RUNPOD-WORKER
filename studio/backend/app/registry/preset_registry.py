"""
PRESET REGISTRY

Um preset ("Cinematic Pro 1.1", "Talking Head", "MiniMax H3", ...) é o
que o utilizador escolhe no Studio. Resolve, por esta ordem:

  PRESET -> ENGINE -> MODEL/CHECKPOINT -> WORKFLOW -> LoRAs -> CAPABILITIES
  -> DEFAULTS -> GENERATION WORKSPACE

O ficheiro presets.json (curado) só guarda a associação
(id/name/category/engine_id/model_id/workflow_id/status) — capabilities,
defaults e LoRAs recomendados são SEMPRE derivados do MODEL REGISTRY
real (config_importer.py), nunca duplicados à mão. Isto garante que o
Studio nunca mostra uma capability que os dados de origem não suportam.

status de um preset:
  - "demo"    -> corre já, a 100%, via o engine mock (sem GPU)
  - "live"    -> corre já, a 100%, via um engine real ligado (ex.: MiniMax)
  - "planned" -> modelo/config real catalogado, mas o engine que o
                 executaria (ltx2/wan/hunyuan/longcat/...) ainda não
                 tem adapter implementado. Ao gerar, cai para o mock
                 em modo demonstração — nunca finge o contrário.
"""
import json
from functools import lru_cache

from ..config import DATA_DIR
from . import model_registry, workflow_registry, lora_catalog

PRESETS_PATH = DATA_DIR / "registry" / "presets.json"

# Tradução de capability (vocabulário real, extraído dos dados) para o
# modo do Studio que ela ativa. Uma capability pode não ter modo
# correspondente (ex.: 'lora', 'sliding_window' são modificadores, não
# modos) - nesse caso fica só disponível como controlo, não como aba.
CAPABILITY_TO_MODE = {
    "text_to_video": "t2v",
    "image_to_video": "i2v",
    "audio_to_video": "i2v",   # modelos de talking head/avatar animam uma imagem com audio
    "end_frame": "end_frame",
    "video_continuation": "continue",
    "text_to_image": "t2i",
    "image_to_image": "i2i",
    "video_to_video": "animate_character",
    "control_video": "animate_character",
    "audio_output": "t2a",    # geração de áudio (música/sfx/voz) — ver studio_audio.json
}


@lru_cache
def _load() -> list[dict]:
    return json.loads(PRESETS_PATH.read_text(encoding="utf-8"))


def list_presets(category: str | None = None) -> list[dict]:
    """Lista resumida (para o dropdown) - não resolve tudo, é mais leve."""
    presets = _load()
    if category:
        presets = [p for p in presets if p["category"] == category]
    out = []
    for p in presets:
        model = model_registry.get_model(p.get("model_id"))
        out.append({
            "id": p["id"],
            "name": p["name"],
            "category": p["category"],
            "engine_id": p["engine_id"],
            "status": p["status"],
            "description": (model or {}).get("description", ""),
        })
    return out


def resolve_runtime_engine(preset: dict) -> str:
    """Devolve o engine que vai REALMENTE executar o job. Se o engine
    pretendido não tiver adapter implementado (ver engines/registry.py),
    cai para 'mock' em vez de falhar ou fingir."""
    from ..engines.registry import get_engine

    if get_engine(preset["engine_id"]):
        return preset["engine_id"]
    return "mock"


def _modes_from_capabilities(capabilities: list[str]) -> list[str]:
    modes = {CAPABILITY_TO_MODE[c] for c in capabilities if c in CAPABILITY_TO_MODE}
    return sorted(modes) if modes else ["t2v"]  # nunca devolver um studio sem nenhum modo


def resolve_preset(preset_id: str) -> dict | None:
    """Resolve um preset por completo: PRESET -> ENGINE -> MODEL ->
    WORKFLOW -> LoRAs -> CAPABILITIES -> DEFAULTS. É isto que
    GET /api/presets/{id} devolve, e o que o Studio usa para configurar
    os controlos."""
    preset = next((p for p in _load() if p["id"] == preset_id), None)
    if not preset:
        return None

    model = model_registry.get_model(preset.get("model_id"))
    workflow = workflow_registry.get_workflow(preset.get("workflow_id"))

    capabilities = list((model or {}).get("capabilities", []))
    defaults = dict((model or {}).get("defaults", {}))
    modes = _modes_from_capabilities(capabilities)

    lora_refs = preset.get("loras")
    if lora_refs is None and model:
        lora_refs = lora_catalog.loras_for_model(model)
    loras = lora_catalog.resolve_preset_loras(lora_refs or [])

    runtime_engine = resolve_runtime_engine(preset)
    status = preset["status"]
    if status == "planned" and runtime_engine != preset["engine_id"]:
        status_detail = (
            f"O engine real '{preset['engine_id']}' ainda não tem adapter implementado. "
            f"A gerar em modo demonstração (engine '{runtime_engine}') para pré-visualizar "
            f"o fluxo e os controlos deste preset."
        )
    elif status == "live":
        status_detail = "Engine real ligado e pronto."
    elif status == "demo":
        status_detail = "Preset de demonstração — corre sem GPU."
    else:
        status_detail = None

    return {
        "id": preset["id"],
        "name": preset["name"],
        "category": preset["category"],
        "engine_id": preset["engine_id"],
        "runtime_engine": runtime_engine,
        "status": status,
        "status_detail": status_detail,
        "model": model,
        "workflow": workflow,
        "capabilities": capabilities,
        "modes": modes,
        "loras": loras,
        "defaults": defaults,
        "requirements": (model or {}).get("requirements", {}),
        "checkpoint": (model or {}).get("checkpoint"),
        "config_source": (model or {}).get("config_source"),
        "description": (model or {}).get("description", ""),
    }


def get_preset_raw(preset_id: str) -> dict | None:
    """Entrada crua do presets.json (sem resolver)."""
    return next((p for p in _load() if p["id"] == preset_id), None)


def resolve_generation_mode(preset_id: str, mode: str) -> dict | None:
    """['botão T2V'/'botão I2V'/'End Frame'/...] -> resolve exatamente qual
    workflow/configuração usar para aquele preset + modo.

    PRESET → CAPABILITIES → MODE REGISTRY → WORKFLOW RESOLUTION

    Devolve None se o preset não suportar o modo pedido (ex.: pedir
    'continue' a um preset sem video_continuation) — a UI nunca deve
    convidar a carregar um botão que resolve para None; é o
    `resolve_preset()["modes"]` que decide quais botões mostrar.

    A ausência de um adapter executável NUNCA remove o modo daqui — só
    afeta `execution_status`, que diz claramente se a execução real já
    está disponível ou se é só pré-visualização em modo Mock."""
    resolved = resolve_preset(preset_id)
    if not resolved or mode not in resolved["modes"]:
        return None

    if resolved["status"] == "planned":
        execution_status = "Workflow preparado — execução real ainda não disponível (a correr em modo Mock)."
    elif resolved["status"] == "live":
        execution_status = "Pronto — engine real ligado."
    else:
        execution_status = "Pronto — modo demonstração (Mock)."

    return {
        "preset_id": preset_id,
        "mode": mode,
        "workflow_id": (resolved["workflow"] or {}).get("id"),
        "engine_id": resolved["runtime_engine"],
        "capabilities": resolved["capabilities"],
        "defaults": resolved["defaults"],
        "execution_status": execution_status,
    }


# alias mantido por compatibilidade com quem já chame o nome curto
resolve_mode = resolve_generation_mode
