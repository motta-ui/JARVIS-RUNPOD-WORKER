import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from .. import database as db
from ..config import ASSETS_DIR, to_media_url

router = APIRouter(prefix="/api/assets", tags=["assets"])

CATEGORIES = {"images", "videos", "audio", "loras", "references"}


def _with_url(asset: dict) -> dict:
    asset["url"] = to_media_url(asset.get("path"), ASSETS_DIR, "/static-assets")
    return asset


@router.get("")
def list_assets(category: str | None = None, project_id: str | None = None, search: str | None = None):
    query = "SELECT * FROM assets WHERE 1=1"
    params = []
    if category:
        query += " AND category=?"
        params.append(category)
    if project_id:
        query += " AND project_id=?"
        params.append(project_id)
    if search:
        query += " AND filename LIKE ?"
        params.append(f"%{search}%")
    query += " ORDER BY created_at DESC"
    with db.db_session() as conn:
        rows = conn.execute(query, params).fetchall()
        return [_with_url(db.row_to_dict(r)) for r in rows]


@router.post("")
async def upload_asset(
    file: UploadFile = File(...),
    category: str = Form(...),
    project_id: str | None = Form(None),
):
    if category not in CATEGORIES:
        raise HTTPException(400, f"Categoria inválida. Use uma de: {sorted(CATEGORIES)}")

    aid = str(uuid.uuid4())
    dest_dir = ASSETS_DIR / category
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest_path = dest_dir / f"{aid}_{file.filename}"

    content = await file.read()
    dest_path.write_bytes(content)

    with db.db_session() as conn:
        conn.execute(
            "INSERT INTO assets (id, project_id, category, filename, path, size_bytes, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (aid, project_id, category, file.filename, str(dest_path), len(content), db.now_iso()),
        )
    return _with_url({
        "id": aid, "filename": file.filename, "category": category,
        "size_bytes": len(content), "path": str(dest_path),
    })


@router.delete("/{asset_id}")
def delete_asset(asset_id: str):
    with db.db_session() as conn:
        row = conn.execute("SELECT * FROM assets WHERE id=?", (asset_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Asset não encontrado")
        try:
            Path(row["path"]).unlink(missing_ok=True)
        except Exception:
            pass
        conn.execute("DELETE FROM assets WHERE id=?", (asset_id,))
    return {"deleted": asset_id}
