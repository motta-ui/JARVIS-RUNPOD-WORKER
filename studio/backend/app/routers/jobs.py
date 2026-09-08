import json
import uuid

from fastapi import APIRouter, HTTPException

from .. import database as db
from ..config import OUTPUTS_DIR, to_media_url
from ..schemas import JobCreate
from ..engines.registry import get_engine
from ..registry import preset_registry

router = APIRouter(prefix="/api/jobs", tags=["jobs"])


def _with_output_url(job: dict) -> dict:
    job["output_url"] = to_media_url(job.get("output_path"), OUTPUTS_DIR, "/outputs")
    return job


@router.get("")
def list_jobs(project_id: str | None = None, status: str | None = None):
    query = "SELECT * FROM jobs WHERE 1=1"
    params = []
    if project_id:
        query += " AND project_id=?"
        params.append(project_id)
    if status:
        query += " AND status=?"
        params.append(status)
    query += " ORDER BY created_at DESC"
    with db.db_session() as conn:
        rows = conn.execute(query, params).fetchall()
        out = []
        for r in rows:
            d = db.row_to_dict(r)
            if d.get("parameters"):
                try:
                    d["parameters"] = json.loads(d["parameters"])
                except Exception:
                    pass
            out.append(_with_output_url(d))
        return out


@router.post("")
def create_job(payload: JobCreate):
    preset = None
    preset_name = None
    kind = payload.kind
    engine_id = payload.engine
    model_id = payload.model
    parameters = dict(payload.parameters)

    if payload.preset_id:
        # --- caminho novo: tudo resolvido a partir do Preset Registry ---
        resolved = preset_registry.resolve_preset(payload.preset_id)
        if not resolved:
            raise HTTPException(404, f"Preset '{payload.preset_id}' não encontrado")
        preset_name = resolved["name"]
        kind = resolved["category"]
        engine_id = resolved["runtime_engine"]
        model_id = resolved["model"]["id"] if resolved.get("model") else resolved["id"]
        # defaults do preset preenchem o que o pedido não especificou
        for k, v in (resolved.get("defaults") or {}).items():
            parameters.setdefault(k, v)
        if resolved.get("status_detail"):
            parameters.setdefault("preset_status_detail", resolved["status_detail"])
    else:
        # --- caminho antigo: engine/model explícitos (mantido por compatibilidade) ---
        if not payload.engine or not payload.model:
            raise HTTPException(400, "É necessário indicar 'preset_id', ou 'engine' e 'model'.")

    engine = get_engine(engine_id)
    if not engine:
        raise HTTPException(400, f"Engine '{engine_id}' não encontrado")

    # engine.generate() só recebe `parameters` (não o JobCreate completo) —
    # garantir que o prompt está lá também, para todo adapter que o leia
    # a partir de job_params (ex.: MiniMax, CloudWorkerEngine) em vez de
    # voltar a consultar a tabela `jobs`.
    parameters.setdefault("prompt", payload.prompt)

    ok, err = engine.validate_request(parameters)
    if not ok:
        raise HTTPException(400, err or "Parâmetros inválidos")

    jid = str(uuid.uuid4())
    ts = db.now_iso()
    with db.db_session() as conn:
        conn.execute(
            "INSERT INTO jobs (id, project_id, engine, model, mode, kind, prompt, parameters, "
            "status, progress, preset_id, preset_name, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (jid, payload.project_id, engine_id, model_id, payload.mode, kind,
             payload.prompt, json.dumps(parameters), "QUEUED", 0.0,
             payload.preset_id, preset_name, ts, ts),
        )

    engine.generate(jid, parameters)
    return {"id": jid, "status": "QUEUED"}


@router.get("/{job_id}")
def get_job(job_id: str):
    with db.db_session() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Job não encontrado")
        job = db.row_to_dict(row)
        if job.get("parameters"):
            try:
                job["parameters"] = json.loads(job["parameters"])
            except Exception:
                pass

        engine = get_engine(job["engine"])
        if engine:
            live = engine.get_status(job_id)
            job.update(live)
        return _with_output_url(job)


@router.post("/{job_id}/cancel")
def cancel_job(job_id: str):
    with db.db_session() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Job não encontrado")
        engine = get_engine(row["engine"])
        if engine:
            engine.cancel(job_id)
    return {"cancelled": job_id}
