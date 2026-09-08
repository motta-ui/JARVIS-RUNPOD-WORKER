import json
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile, File, Form

from .. import database as db
from ..schemas import LoraUpdate
from ..config import LORAS_DIR
from ..registry import lora_catalog

router = APIRouter(prefix="/api/loras", tags=["loras"])


def _serialize(row) -> dict:
    d = db.row_to_dict(row)
    try:
        d["tags"] = json.loads(d.get("tags") or "[]")
    except Exception:
        d["tags"] = []
    d["active"] = bool(d.get("active", 1))
    return d


@router.get("/catalog")
def list_lora_catalog(engine_id: str | None = None):
    """LORA REGISTRY (catálogo) — diferente do inventário abaixo: isto é o
    catálogo de LoRAs conhecidos (extraídos dos ficheiros de configuração
    reais), não o que o utilizador já tem instalado."""
    entries = lora_catalog.list_catalog()
    if engine_id:
        entries = [e for e in entries if engine_id in e["compatible_engines"]]
    return entries


@router.get("/catalog/{lora_id}")
def get_lora_catalog_entry(lora_id: str):
    entry = lora_catalog.get_catalog_entry(lora_id)
    if not entry:
        raise HTTPException(404, f"LoRA '{lora_id}' não encontrado no catálogo")
    return entry


@router.get("")
def list_loras(engine: str | None = None, active_only: bool = False):
    query = "SELECT * FROM loras WHERE 1=1"
    params = []
    if engine:
        query += " AND engine=?"
        params.append(engine)
    if active_only:
        query += " AND active=1"
    query += " ORDER BY created_at DESC"
    with db.db_session() as conn:
        rows = conn.execute(query, params).fetchall()
        return [_serialize(r) for r in rows]


@router.post("")
async def create_lora(
    name: str = Form(...),
    engine: str = Form("mock"),
    compatible_model: str | None = Form(None),
    description: str = Form(""),
    strength: float = Form(1.0),
    tags: str = Form("[]"),
    file: UploadFile | None = File(None),
    preview: UploadFile | None = File(None),
):
    lid = str(uuid.uuid4())
    LORAS_DIR.mkdir(parents=True, exist_ok=True)

    file_path = None
    if file is not None:
        file_path = LORAS_DIR / f"{lid}_{file.filename}"
        file_path.write_bytes(await file.read())

    preview_path = None
    if preview is not None:
        preview_dir = LORAS_DIR / "previews"
        preview_dir.mkdir(parents=True, exist_ok=True)
        preview_path = preview_dir / f"{lid}_{preview.filename}"
        preview_path.write_bytes(await preview.read())

    try:
        tags_list = json.loads(tags) if tags else []
    except Exception:
        tags_list = []

    ts = db.now_iso()
    with db.db_session() as conn:
        conn.execute(
            "INSERT INTO loras (id, name, file_path, engine, compatible_model, preview_path, "
            "description, strength, active, tags, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)",
            (lid, name, str(file_path) if file_path else None, engine, compatible_model,
             str(preview_path) if preview_path else None, description, strength, json.dumps(tags_list), ts),
        )
        row = conn.execute("SELECT * FROM loras WHERE id=?", (lid,)).fetchone()
    return _serialize(row)


@router.patch("/{lora_id}")
def update_lora(lora_id: str, payload: LoraUpdate):
    with db.db_session() as conn:
        row = conn.execute("SELECT * FROM loras WHERE id=?", (lora_id,)).fetchone()
        if not row:
            raise HTTPException(404, "LoRA não encontrado")
        current = _serialize(row)
        updates = payload.dict(exclude_unset=True)
        merged = {**current, **updates}
        conn.execute(
            "UPDATE loras SET name=?, description=?, strength=?, active=?, tags=?, compatible_model=? WHERE id=?",
            (merged["name"], merged.get("description", ""), merged.get("strength", 1.0),
             1 if merged.get("active", True) else 0, json.dumps(merged.get("tags", [])),
             merged.get("compatible_model"), lora_id),
        )
        row = conn.execute("SELECT * FROM loras WHERE id=?", (lora_id,)).fetchone()
    return _serialize(row)


@router.delete("/{lora_id}")
def delete_lora(lora_id: str):
    with db.db_session() as conn:
        row = conn.execute("SELECT * FROM loras WHERE id=?", (lora_id,)).fetchone()
        if not row:
            raise HTTPException(404, "LoRA não encontrado")
        for p in (row["file_path"], row["preview_path"]):
            if p:
                try:
                    Path(p).unlink(missing_ok=True)
                except Exception:
                    pass
        conn.execute("DELETE FROM loras WHERE id=?", (lora_id,))
    return {"deleted": lora_id}
