from fastapi import APIRouter, HTTPException

from ..config import (
    DATA_DIR, load_formats, load_quality_presets, load_steps_options,
    load_control_video_options, load_advanced_fields, load_video_modes, load_studio_config,
)
from ..registry import model_registry
import json

router = APIRouter(prefix="/api", tags=["models", "config"])


@router.get("/models")
def list_models(category: str | None = None, engine_id: str | None = None,
                 capability: str | None = None, status: str | None = None, query: str | None = None,
                 kind: str | None = None):
    # 'kind' mantido por compatibilidade com chamadas antigas (== category)
    return model_registry.search_models(
        category=category or kind, engine_id=engine_id, capability=capability, status=status, query=query,
    )


@router.get("/models/{model_id}")
def get_model(model_id: str):
    model = model_registry.get_model(model_id)
    if not model:
        raise HTTPException(404, f"Modelo '{model_id}' não encontrado")
    return model


@router.get("/models/{model_id}/capabilities")
def get_model_capabilities(model_id: str):
    model = model_registry.get_model(model_id)
    if not model:
        raise HTTPException(404, f"Modelo '{model_id}' não encontrado")
    return {"model_id": model_id, "capabilities": model.get("capabilities", [])}


@router.get("/models/{model_id}/defaults")
def get_model_defaults(model_id: str):
    model = model_registry.get_model(model_id)
    if not model:
        raise HTTPException(404, f"Modelo '{model_id}' não encontrado")
    return {"model_id": model_id, "defaults": model.get("defaults", {})}


@router.get("/config/studio/{kind}")
def get_studio_config(kind: str):
    """Configuração completa (modos, zonas de referência, addons, campos
    extra) de um studio — video/image/audio/motion. Tudo vem do backend."""
    return load_studio_config(kind)


@router.get("/config/formats")
def get_formats():
    return load_formats()


@router.get("/config/quality-presets")
def get_quality_presets():
    return load_quality_presets()


@router.get("/config/steps")
def get_steps():
    return load_steps_options()


@router.get("/config/control-video")
def get_control_video():
    return load_control_video_options()


@router.get("/config/advanced-fields")
def get_advanced_fields():
    return load_advanced_fields()


@router.get("/config/video-modes")
def get_video_modes():
    return load_video_modes()


@router.get("/config/addons")
def get_addons():
    path = DATA_DIR / "addons.json"
    return json.loads(path.read_text(encoding="utf-8"))
