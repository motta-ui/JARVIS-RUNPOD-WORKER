"""
WORKFLOW REGISTRY

Duas fontes, ambas marcadas como NÃO executáveis (executable=False):

1. "preset_config" — os 200 ficheiros reais em workflow_configs/
   (config_importer.py). São ficheiros de CONFIGURAÇÃO do Wan2GP, não
   grafos executáveis — nunca fingimos o contrário.
2. "placeholder" — os workflows demo do JARVIS
   (data/registry/workflows/mock/*.json), usados pelos 4 presets
   "JARVIS Demo (Mock)".

Um workflow verdadeiramente executável (ex.: grafo ComfyUI real) fica
para o futuro: esta arquitetura só precisa apontar `source_type` e
`executable` corretamente para que ninguém tente "correr" um destes
por engano.
"""
import json
from functools import lru_cache
from pathlib import Path

from ..config import DATA_DIR
from . import config_importer

WORKFLOWS_DIR = DATA_DIR / "registry" / "workflows"


@lru_cache
def _load_placeholders() -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not WORKFLOWS_DIR.exists():
        return out
    for path in sorted(WORKFLOWS_DIR.rglob("*.json")):
        rel = str(path.relative_to(WORKFLOWS_DIR))
        data = json.loads(path.read_text(encoding="utf-8"))
        wf_id = path.stem
        out[wf_id] = {
            "id": wf_id,
            "name": data.get("description", wf_id),
            "engine_id": data.get("engine", "mock"),
            "preset_id": None,
            "source_type": "placeholder",
            "source_file": rel,
            "executable": False,
            "input_mapping": {},
            "output_mapping": {},
            "parameters": {},
        }
    return out


def _from_imported_model(m: dict) -> dict:
    return {
        "id": m["workflow_id"],
        "name": m["name"],
        "engine_id": m["engine_id"],
        "preset_id": None,
        "source_type": "preset_config",
        "source_file": m["config_source"],
        "executable": False,
        "input_mapping": {},
        "output_mapping": {},
        "parameters": m["defaults"],
    }


def get_workflow(workflow_id: str | None) -> dict | None:
    if not workflow_id:
        return None
    placeholders = _load_placeholders()
    if workflow_id in placeholders:
        return placeholders[workflow_id]
    m = config_importer.get_imported_model(workflow_id)
    if m:
        return _from_imported_model(m)
    return None


def list_workflows(engine_id: str | None = None) -> list[dict]:
    out = list(_load_placeholders().values())
    out += [_from_imported_model(m) for m in config_importer.list_imported_models()]
    if engine_id:
        out = [w for w in out if w["engine_id"] == engine_id]
    return out
