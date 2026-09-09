"""
LORA RESOLVER

Resolve quais LoRAs entram numa geração — nunca reenvia à toa a lista
crua vinda da UI. Fonte de dados: data/registry/lora_capabilities/<family>.json
(capabilities reais extraídas do JARVIS_WORKFLOW_PARITY_PACK e cruzadas
com o código do Wan2GP no Pod — ver o campo "_provenance" de cada
ficheiro e os comentários "engine_managed_note").

Dois tipos de LoRA, tratados de forma completamente diferente:

  engine_managed=True  ("special" ou "distilled-lora"/"id-lora" system):
      O PRÓPRIO Wan2GP baixa e aplica o ficheiro internamente quando os
      flags certos (ctrl_video_prompt_type, guidance_phases, pipeline
      'distilled') estão presentes — confirmado em models/ltx2/ltx2.py
      (_append_system_lora) e models/ltx2/ltx2_handler.py. O resolver
      NUNCA lista estes em activated_loras; só garante os flags/inputs
      que os activam.

  engine_managed=False ("normal", autónomo):
      LoRA real que o Worker tem de listar em activated_loras (a URL
      completa do Hugging Face funciona directamente — confirmado em
      profiles/ltx2_distilled_presets/*.json do próprio Wan2GP) +
      loras_multipliers.

Não empilha automaticamente só porque é "suportado" — respeita
allowed_modes/incompatible_modes/requires_ctrl_video, e nunca aplica um
LoRA 'special' sem o Ctrl Video real que ele exige.
"""
import json
from functools import lru_cache

from ..config import DATA_DIR

CAPABILITIES_DIR = DATA_DIR / "registry" / "lora_capabilities"

# model_id (Wan2GP) -> família de capabilities de LoRA. Só ltx2_22B* está
# coberto por agora (prioridade: Cinematic Pro) — outras famílias devolvem
# resolução vazia em vez de inventar regras que não foram auditadas.
_FAMILY_BY_MODEL_PREFIX = [
    ("ltx2_22B", "ltx2"),
]


def _family_for_model(model_id: str) -> str | None:
    for prefix, family in _FAMILY_BY_MODEL_PREFIX:
        if model_id and model_id.startswith(prefix):
            return family
    return None


@lru_cache
def _load_family(family: str) -> dict:
    path = CAPABILITIES_DIR / f"{family}.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.pop("_provenance", None)
    return data


def list_family_loras(family: str) -> dict:
    """Catálogo completo (filename -> capability dict) de uma família."""
    return dict(_load_family(family))


def _lookup(family: str, lora_ref: str) -> tuple[str, dict] | None:
    """Aceita tanto o filename exato quanto o commercial_name (o que a UI
    mostra) — nunca obriga quem chama a saber o nome técnico do ficheiro."""
    catalog = _load_family(family)
    if lora_ref in catalog:
        return lora_ref, catalog[lora_ref]
    for filename, entry in catalog.items():
        if entry.get("commercial_name") == lora_ref:
            return filename, entry
    return None


def resolve_loras(
    model_id: str,
    mode: str,
    user_selection: list[dict] | None = None,
    available_inputs: dict | None = None,
) -> dict:
    """resolve_loras(model, workflow, user_selection, available_inputs).

    user_selection: [{"id_or_name": "Motion Intelligence", "multiplier": 1.0}, ...]
    available_inputs: {"has_ctrl_video": bool, "ctrl_video_option": "canny"|"depth"|...}

    Devolve sempre (nunca levanta por LoRA desconhecido/incompatível —
    reporta em 'conflicts' em vez de derrubar o job):
      applied:    LoRAs autónomos a listar em activated_loras (com multiplier)
      automatic:  LoRAs engine_managed que vão ser aplicados pelo Wan2GP
                  (informativo — não entram em activated_loras)
      downloads_needed: URLs que ainda precisam de ser baixados (informativo;
                  o Wan2GP baixa sozinho ao ver a URL em activated_loras,
                  isto é só para o Studio poder avisar/acompanhar)
      controls_needed:  Ctrl Video / flags que faltam para os LoRAs pedidos
                  funcionarem de verdade
      conflicts:  mensagens de incompatibilidade (modo errado, LoRA
                  desconhecido, falta Ctrl Video, etc.) — o pedido
                  incompatível é IGNORADO, nunca empilhado às cegas
      extra_settings: dict a fundir nas settings finais (ex.:
                  ctrl_video_prompt_type de um auto_payload_required)
    """
    available_inputs = available_inputs or {}
    result = {
        "applied": [], "automatic": [], "downloads_needed": [],
        "controls_needed": [], "conflicts": [], "extra_settings": {},
    }
    family = _family_for_model(model_id)
    if family is None:
        if user_selection:
            result["conflicts"].append(
                f"Família de LoRA não auditada para model_id='{model_id}' — "
                f"nenhum LoRA foi aplicado (evita empilhar sem fonte de verdade)."
            )
        return result

    has_ctrl_video = bool(available_inputs.get("has_ctrl_video"))
    activated_multipliers: list[str] = []

    for ref in user_selection or []:
        name = ref.get("id_or_name") if isinstance(ref, dict) else ref
        found = _lookup(family, name)
        if not found:
            result["conflicts"].append(f"LoRA '{name}' não encontrado no catálogo da família '{family}'.")
            continue
        filename, entry = found

        if mode in entry.get("incompatible_modes", []):
            result["conflicts"].append(
                f"'{entry['commercial_name']}' é incompatível com o modo '{mode}' — ignorado."
            )
            continue
        if entry.get("allowed_modes") and mode not in entry["allowed_modes"]:
            result["conflicts"].append(
                f"'{entry['commercial_name']}' não suporta o modo '{mode}' — ignorado."
            )
            continue
        if entry.get("requires_ctrl_video") and not has_ctrl_video:
            result["controls_needed"].append(
                f"'{entry['commercial_name']}' precisa de um Ctrl Video real para funcionar — sem ele, ignorado."
            )
            continue

        if entry.get("engine_managed"):
            result["automatic"].append({
                "id": filename, "name": entry["commercial_name"],
                "note": entry.get("engine_managed_note", ""),
            })
        else:
            multiplier = ref.get("multiplier", entry.get("multiplier_default", 1.0)) if isinstance(ref, dict) else entry.get("multiplier_default", 1.0)
            url = entry.get("download_url") or filename
            result["applied"].append({
                "id": filename, "name": entry["commercial_name"],
                "url": url, "multiplier": multiplier,
            })
            result["downloads_needed"].append(url)
            activated_multipliers.append(str(multiplier))

        if entry.get("auto_payload_required"):
            for k, v in entry.get("auto_payload", {}).items():
                existing = result["extra_settings"].get(k, "")
                result["extra_settings"][k] = "".join(sorted(set(str(existing)) | set(str(v)))) if k.endswith("prompt_type") else v

    if result["applied"]:
        result["extra_settings"]["activated_loras"] = [item["url"] for item in result["applied"]]
        result["extra_settings"]["loras_multipliers"] = " ".join(activated_multipliers)

    return result
