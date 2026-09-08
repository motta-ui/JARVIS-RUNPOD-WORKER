import atexit
import os
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

WAN_DIR = Path(os.getenv("JARVIS_WAN_DIR", "/workspace/JARVIS/wan2gp_upstream")).resolve()
OUTPUT_DIR = Path(os.getenv("JARVIS_OUTPUT_DIR", "/workspace/outputs")).resolve()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
if str(WAN_DIR) not in sys.path:
    sys.path.insert(0, str(WAN_DIR))

from acs_wan_adapter import WanAdapter

app = FastAPI(title="JARVIS RunPod Worker", version="6.0.0")
TOKEN = os.getenv("JARVIS_WORKER_TOKEN", "").strip()

_lock = threading.Lock()
_adapter_lock = threading.Lock()
_adapter = None
_job = {
    "job_id": None, "status": "idle", "progress": 0, "phase": "idle",
    "output": None, "error": None, "model_type": None,
}


class RunTask(BaseModel):
    model_type: str
    settings: dict[str, Any] = Field(default_factory=dict)


def auth(token: str | None) -> None:
    if TOKEN and token != TOKEN:
        raise HTTPException(status_code=401, detail="invalid token")


def get_adapter() -> WanAdapter:
    global _adapter
    if _adapter is None:
        with _adapter_lock:
            if _adapter is None:
                _adapter = WanAdapter(
                    WAN_DIR,
                    output_dir=OUTPUT_DIR,
                    cli_args=("--attention", "sdpa", "--perc-reserved-mem-max", "0.5"),
                )
    return _adapter


def set_job(**values: Any) -> None:
    with _lock:
        _job.update(values)


class WorkerCallbacks:
    def on_progress(self, update) -> None:
        try:
            set_job(
                progress=max(0, min(100, int(getattr(update, "progress", 0)))),
                phase=str(getattr(update, "phase", "") or "inference"),
            )
        except Exception:
            pass

    def on_status(self, text) -> None:
        try:
            text = str(text or "").strip()
            if text:
                set_job(phase=text)
        except Exception:
            pass

    def on_stream(self, line) -> None:
        # Keep the HTTP API quiet; detailed WanGP logs remain in the container log.
        pass

    def on_error(self, error) -> None:
        try:
            set_job(error=str(getattr(error, "message", error)))
        except Exception:
            pass


def worker(job_id: str, model_type: str, settings: dict[str, Any]) -> None:
    try:
        set_job(job_id=job_id, status="running", progress=0,
                phase="loading_model", model_type=model_type,
                output=None, error=None)
        result = get_adapter().generate(
            model_type=model_type,
            overrides=settings,
            callbacks=WorkerCallbacks(),
        )
        if not result.get("ok"):
            raise RuntimeError(result.get("error", "WanGP generation failed"))
        files = result.get("generated_files") or []
        output = result.get("path") or (files[0] if files else None)
        if not output:
            raise RuntimeError("WanGP completed without returning an output path")
        set_job(status="completed", progress=100, phase="done", output=str(output), error=None)
    except Exception as exc:
        set_job(status="failed", phase="error", error=f"{type(exc).__name__}: {exc}")


@app.get("/health")
def health():
    return {
        "ok": True,
        "engine": "jarvis-wangp-worker",
        "version": "6.0.0",
        "wan_dir": str(WAN_DIR),
        "wan_exists": WAN_DIR.exists(),
        "output_dir": str(OUTPUT_DIR),
        "output_exists": OUTPUT_DIR.exists(),
    }


@app.get("/models")
def models(x_jarvis_token: str | None = Header(default=None)):
    auth(x_jarvis_token)
    try:
        return {"ok": True, "models": get_adapter().list_models()}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@app.get("/default_settings/{model_type:path}")
def default_settings(model_type: str, x_jarvis_token: str | None = Header(default=None)):
    auth(x_jarvis_token)
    try:
        return {"ok": True, "model_type": model_type, "settings": get_adapter().default_settings(model_type)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@app.get("/schema/{model_type:path}")
def schema(model_type: str, x_jarvis_token: str | None = Header(default=None)):
    auth(x_jarvis_token)
    try:
        return {"ok": True, **get_adapter().model_schema(model_type)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@app.get("/availability/{model_type:path}")
def availability(model_type: str, x_jarvis_token: str | None = Header(default=None)):
    auth(x_jarvis_token)
    try:
        return {"ok": True, **get_adapter().availability(model_type)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"{type(exc).__name__}: {exc}")


@app.get("/progress")
def progress(x_jarvis_token: str | None = Header(default=None)):
    auth(x_jarvis_token)
    with _lock:
        return dict(_job)


@app.post("/run_task")
def run_task(task: RunTask, x_jarvis_token: str | None = Header(default=None)):
    auth(x_jarvis_token)
    with _lock:
        if _job["status"] == "running":
            raise HTTPException(status_code=409, detail="worker busy")
        job_id = str(uuid.uuid4())
        _job.update(job_id=job_id, status="queued", progress=0, phase="queued",
                    output=None, error=None, model_type=task.model_type)
    threading.Thread(target=worker, args=(job_id, task.model_type, task.settings), daemon=True).start()
    return {"job_id": job_id, "status": "queued"}


def _close():
    global _adapter
    if _adapter is not None:
        try:
            _adapter.close()
        except Exception:
            pass
        _adapter = None

atexit.register(_close)
