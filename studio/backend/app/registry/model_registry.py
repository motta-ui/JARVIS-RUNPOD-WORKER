"""
MODEL REGISTRY

Junta:
1. Os poucos modelos curados à mão (data/registry/models.json) — hoje
   só "minimax-h3" e "jarvis-mock", os dois únicos com engine
   realmente executável.
2. Os 200 modelos importados automaticamente de workflow_configs/
   (config_importer.py) — configurações reais do projeto open-source
   Wan2GP, com engine ainda não executável na maioria (status
   "available" no sentido de "presente no registry", não "corre já
   sem GPU").

Nada aqui é inventado: cada campo vem do ficheiro de origem
(curado ou importado) — ver config_importer.py para a proveniência
exata dos importados.
"""
import json
from functools import lru_cache

from ..config import DATA_DIR
from . import config_importer

MODELS_PATH = DATA_DIR / "registry" / "models.json"


@lru_cache
def _load_curated() -> list[dict]:
    return json.loads(MODELS_PATH.read_text(encoding="utf-8"))


@lru_cache
def list_models() -> list[dict]:
    return list(_load_curated()) + config_importer.list_imported_models()


def get_model(model_id: str) -> dict | None:
    if not model_id:
        return None
    for m in list_models():
        if m["id"] == model_id:
            return m
    return None


def search_models(
    category: str | None = None,
    engine_id: str | None = None,
    capability: str | None = None,
    status: str | None = None,
    query: str | None = None,
) -> list[dict]:
    """Filtros pedidos: nome (query), categoria, engine, capability, status.
    VRAM/disponibilidade ficam por implementar até termos números reais
    por modelo (não vamos inventar estimativas de VRAM)."""
    results = list_models()
    if category:
        results = [m for m in results if m.get("category") == category]
    if engine_id:
        results = [m for m in results if m.get("engine_id") == engine_id]
    if capability:
        results = [m for m in results if capability in m.get("capabilities", [])]
    if status:
        results = [m for m in results if m.get("status") == status]
    if query:
        q = query.lower()
        results = [m for m in results if q in m["name"].lower() or q in m["id"].lower()]
    return results
