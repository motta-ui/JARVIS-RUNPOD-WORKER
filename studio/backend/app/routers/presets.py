from fastapi import APIRouter, HTTPException

from ..registry import preset_registry

router = APIRouter(prefix="/api/presets", tags=["presets"])


@router.get("")
def list_presets(kind: str | None = None):
    return preset_registry.list_presets(kind)


@router.get("/{preset_id}")
def get_preset(preset_id: str):
    resolved = preset_registry.resolve_preset(preset_id)
    if not resolved:
        raise HTTPException(404, f"Preset '{preset_id}' não encontrado")
    return resolved


@router.get("/{preset_id}/modes/{mode}")
def get_generation_mode(preset_id: str, mode: str):
    """PRESET + MODO -> workflow/engine/capabilities/defaults/execution_status.
    É isto que cada botão de modo (T2V/I2V/End Frame/Continue/...) resolve
    ao ser selecionado. Devolve 404 se o preset não suportar esse modo —
    a UI só deve mostrar botões para modos que já sabe que resolvem."""
    resolved = preset_registry.resolve_generation_mode(preset_id, mode)
    if not resolved:
        raise HTTPException(404, f"Preset '{preset_id}' não suporta o modo '{mode}'")
    return resolved
