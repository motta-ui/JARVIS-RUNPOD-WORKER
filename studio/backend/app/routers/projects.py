import uuid
from fastapi import APIRouter, HTTPException

from .. import database as db
from ..schemas import ProjectCreate, ProjectUpdate

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.get("")
def list_projects():
    with db.db_session() as conn:
        rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
        return [db.row_to_dict(r) for r in rows]


@router.post("")
def create_project(payload: ProjectCreate):
    pid = str(uuid.uuid4())
    ts = db.now_iso()
    with db.db_session() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, description, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (pid, payload.name, payload.description, ts, ts),
        )
    return {"id": pid, "name": payload.name, "description": payload.description,
            "created_at": ts, "updated_at": ts}


@router.get("/{project_id}")
def get_project(project_id: str):
    with db.db_session() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Projeto não encontrado")
        project = db.row_to_dict(row)
        project["assets"] = [db.row_to_dict(r) for r in conn.execute(
            "SELECT * FROM assets WHERE project_id=?", (project_id,)).fetchall()]
        project["jobs"] = [db.row_to_dict(r) for r in conn.execute(
            "SELECT * FROM jobs WHERE project_id=?", (project_id,)).fetchall()]
        return project


@router.patch("/{project_id}")
def update_project(project_id: str, payload: ProjectUpdate):
    with db.db_session() as conn:
        row = conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Projeto não encontrado")
        name = payload.name if payload.name is not None else row["name"]
        desc = payload.description if payload.description is not None else row["description"]
        conn.execute(
            "UPDATE projects SET name=?, description=?, updated_at=? WHERE id=?",
            (name, desc, db.now_iso(), project_id),
        )
        return db.row_to_dict(conn.execute("SELECT * FROM projects WHERE id=?", (project_id,)).fetchone())


@router.delete("/{project_id}")
def delete_project(project_id: str):
    with db.db_session() as conn:
        conn.execute("DELETE FROM projects WHERE id=?", (project_id,))
    return {"deleted": project_id}
