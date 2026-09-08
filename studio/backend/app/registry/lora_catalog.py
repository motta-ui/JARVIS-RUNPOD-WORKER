"""
LORA REGISTRY (catálogo)

O catálogo é construído automaticamente a partir dos URLs de LoRA REAIS
encontrados nos ficheiros de configuração importados
(config_importer.py) — nada inventado, cada entrada corresponde a um
ficheiro .safetensors referenciado por pelo menos um preset real.

Isto é DIFERENTE da tabela `loras` na base de dados, que é o
inventário real do que o utilizador já instalou (upload próprio,
gerido em routers/loras.py). resolve_preset_loras() junta as duas
coisas: diz quais LoRAs um preset recomenda E se o utilizador já os
tem instalados — nunca finge que estão instalados quando não estão.
"""
import re
from functools import lru_cache
from urllib.parse import urlparse

from . import config_importer


def _lora_id_from_url(url: str) -> str:
    filename = urlparse(url).path.rsplit("/", 1)[-1]
    return re.sub(r"\.safetensors$", "", filename)


@lru_cache
def list_catalog() -> list[dict]:
    catalog: dict[str, dict] = {}
    for m in config_importer.list_imported_models():
        for url in m.get("loras", []):
            if not isinstance(url, str) or not url:
                continue
            lid = _lora_id_from_url(url)
            entry = catalog.setdefault(lid, {
                "id": lid,
                "name": lid.replace("_", " "),
                "url": url,
                "compatible_engines": set(),
                "compatible_models": set(),
            })
            entry["compatible_engines"].add(m["engine_id"])
            entry["compatible_models"].add(m["id"])

    out = []
    for entry in catalog.values():
        out.append({
            "id": entry["id"],
            "name": entry["name"],
            "url": entry["url"],
            "compatible_engines": sorted(entry["compatible_engines"]),
            "compatible_models": sorted(entry["compatible_models"]),
            "strength_default": 1.0,
            "strength_min": 0.0,
            "strength_max": 2.0,
        })
    return sorted(out, key=lambda e: e["id"])


def get_catalog_entry(lora_id: str) -> dict | None:
    return next((entry for entry in list_catalog() if entry["id"] == lora_id), None)


def is_compatible(lora_id: str, engine_id: str) -> bool:
    """Usado para impedir/alertar quando um LoRA incompatível é escolhido."""
    entry = get_catalog_entry(lora_id)
    if not entry:
        return False
    return engine_id in entry["compatible_engines"]


def loras_for_model(model: dict) -> list[dict]:
    """Deriva a lista de referências LoRA (id/strength) diretamente dos
    dados reais do modelo — usado quando um preset não define a sua
    própria lista de LoRAs, para nunca inventar associações."""
    urls = model.get("loras") or []
    multipliers = model.get("loras_multipliers") or []
    refs = []
    for i, url in enumerate(urls):
        if not isinstance(url, str) or not url:
            continue
        strength = multipliers[i] if i < len(multipliers) and isinstance(multipliers[i], (int, float)) else 1.0
        refs.append({"id": _lora_id_from_url(url), "strength": strength, "required": True})
    return refs


def resolve_preset_loras(preset_lora_refs: list[dict]) -> list[dict]:
    """Junta cada referência (id/strength/required) com o catálogo e com
    o inventário real do utilizador — nunca finge que um LoRA
    recomendado já está instalado."""
    from .. import database as db

    with db.db_session() as conn:
        installed_names = {row["name"] for row in conn.execute("SELECT name FROM loras WHERE active=1")}

    resolved = []
    for ref in preset_lora_refs or []:
        entry = get_catalog_entry(ref.get("id")) or {}
        resolved.append({
            "id": ref.get("id"),
            "name": entry.get("name", ref.get("id")),
            "url": entry.get("url"),
            "strength": ref.get("strength", entry.get("strength_default", 1.0)),
            "required": bool(ref.get("required", False)),
            "installed": entry.get("name") in installed_names if entry else False,
        })
    return resolved
