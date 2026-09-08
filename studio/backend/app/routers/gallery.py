import json
from pathlib import Path

from fastapi import APIRouter, HTTPException

from .. import database as db
from ..config import OUTPUTS_DIR, to_media_url

router = APIRouter(prefix="/api/gallery", tags=["gallery"])


def _with_urls(item: dict) -> dict:
    item["file_url"] = to_media_url(item.get("file_path"), OUTPUTS_DIR, "/outputs")
    item["thumbnail_url"] = to_media_url(item.get("thumbnail_path"), OUTPUTS_DIR, "/outputs") or item["file_url"]
    return item


@router.get("")
def list_gallery(kind: str | None = None, project_id: str | None = None, favorite: bool | None = None):
    query = "SELECT * FROM gallery_items WHERE 1=1"
    params = []
    if kind and kind != "all":
        query += " AND kind=?"
        params.append(kind)
    if project_id:
        query += " AND project_id=?"
        params.append(project_id)
    if favorite is not None:
        query += " AND favorite=?"
        params.append(1 if favorite else 0)
    query += " ORDER BY created_at DESC"
    with db.db_session() as conn:
        rows = conn.execute(query, params).fetchall()
        items = []
        for r in rows:
            item = db.row_to_dict(r)
            if item.get("parameters"):
                try:
                    item["parameters"] = json.loads(item["parameters"])
                except Exception:
                    pass
            items.append(_with_urls(item))
        return items


@router.patch("/{item_id}/favorite")
def toggle_favorite(item_id: str, favorite: bool):
    with db.db_session() as conn:
        row = conn.execute("SELECT * FROM gallery_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Item não encontrado na galeria")
        conn.execute("UPDATE gallery_items SET favorite=? WHERE id=?", (1 if favorite else 0, item_id))
    return {"id": item_id, "favorite": favorite}


@router.delete("/{item_id}")
def delete_gallery_item(item_id: str):
    with db.db_session() as conn:
        row = conn.execute("SELECT * FROM gallery_items WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Item não encontrado na galeria")
        try:
            if row["file_path"]:
                Path(row["file_path"]).unlink(missing_ok=True)
        except Exception:
            pass
        conn.execute("DELETE FROM gallery_items WHERE id=?", (item_id,))
    return {"deleted": item_id}
