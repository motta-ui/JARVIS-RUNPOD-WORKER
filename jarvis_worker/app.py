import atexit
import os
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Header, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

WAN_DIR = Path(os.getenv("JARVIS_WAN_DIR", "/workspace/JARVIS/wan2gp_upstream")).resolve()
OUTPUT_DIR = Path(os.getenv("JARVIS_OUTPUT_DIR", "/workspace/outputs")).resolve()
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
REFS_DIR = Path(os.getenv("JARVIS_REFS_DIR", "/workspace/refs")).resolve()
REFS_DIR.mkdir(parents=True, exist_ok=True)
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
    "output": None, "output_relpath": None, "error": None, "model_type": None,
}


class RunTask(BaseModel):
    model_type: str
    settings: dict[str, Any] = Field(default_factory=dict)


# Reference/output media handling shared by every modality (video, image,
# audio, motion) — WanGP settings for i2v/flf/control-video/talking-head/
# audio-conditioning all take file paths, so uploads and generated outputs
# use the same upload/serve/list plumbing regardless of model family.
_IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_VIDEO_EXTS = {".mp4", ".webm", ".mov"}
_AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a", ".opus", ".wma"}
_MAX_REF_IMAGE_BYTES = 25 * 1024 * 1024
_MAX_REF_VIDEO_BYTES = 500 * 1024 * 1024
_MAX_AUDIO_BYTES = 100 * 1024 * 1024
_MEDIA_TYPES = {
    ".mp4": "video/mp4", ".webm": "video/webm", ".mov": "video/quicktime",
    ".webp": "image/webp", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
    ".png": "image/png", ".bmp": "image/bmp",
    ".wav": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac",
    ".aac": "audio/aac", ".m4a": "audio/mp4", ".ogg": "audio/ogg",
    ".opus": "audio/opus", ".wma": "audio/x-ms-wma",
}


async def _read_limited(file: UploadFile, max_bytes: int) -> bytes:
    chunks = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(status_code=413, detail=f"file exceeds {max_bytes} bytes")
        chunks.append(chunk)
    return b"".join(chunks)


def _media_kind(suffix: str) -> str | None:
    if suffix in _IMAGE_EXTS:
        return "image"
    if suffix in _VIDEO_EXTS:
        return "video"
    if suffix in _AUDIO_EXTS:
        return "audio"
    return None


def _safe_serve(base_dir: Path, rel_path: str) -> Path:
    """Resolves rel_path under base_dir, allowing nested subdirectories
    (WanGP commonly saves outputs under per-run subfolders) while blocking
    traversal: '..' segments are rejected outright, and resolve()+relative_to()
    catches any remaining escape attempt (e.g. via symlinks)."""
    if not rel_path or rel_path.startswith("/") or ".." in Path(rel_path).parts:
        raise HTTPException(status_code=400, detail="invalid path")
    resolved = (base_dir / rel_path).resolve()
    try:
        resolved.relative_to(base_dir)
    except ValueError:
        raise HTTPException(status_code=403, detail="path outside allowed directory")
    if not resolved.exists() or not resolved.is_file():
        raise HTTPException(status_code=404, detail="file not found")
    return resolved


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
                output=None, output_relpath=None, error=None)
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
        output_relpath = None
        try:
            output_relpath = Path(output).resolve().relative_to(OUTPUT_DIR).as_posix()
        except ValueError:
            pass  # output landed outside OUTPUT_DIR — /outputs/{path} can't serve it; output stays absolute-only
        set_job(status="completed", progress=100, phase="done", output=str(output),
                output_relpath=output_relpath, error=None)
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


@app.post("/upload-ref")
async def upload_ref(file: UploadFile = File(...), x_jarvis_token: str | None = Header(default=None)):
    """Accepts an image or video reference (start/end frame, control video,
    character photo, motion-control video, ...) used by i2v/flf/animate/
    character-animate settings across the video and motion modules."""
    auth(x_jarvis_token)
    suffix = Path(file.filename or "").suffix.lower() or ".jpg"
    kind = _media_kind(suffix)
    if kind not in ("image", "video"):
        raise HTTPException(status_code=400, detail=f"unsupported reference format: {suffix}")
    max_bytes = _MAX_REF_VIDEO_BYTES if kind == "video" else _MAX_REF_IMAGE_BYTES
    content = await _read_limited(file, max_bytes)
    dest = REFS_DIR / f"ref_{uuid.uuid4().hex[:10]}{suffix}"
    dest.write_bytes(content)
    return {"path": str(dest), "filename": file.filename, "type": kind}


@app.post("/upload-audio")
@app.post("/upload/audio")
async def upload_audio(file: UploadFile = File(...), x_jarvis_token: str | None = Header(default=None)):
    """Accepts an audio reference (TTS voice prompt, talking-head speaker
    track, audio-conditioning clip, ...) used by the audio and motion
    modules."""
    auth(x_jarvis_token)
    suffix = Path(file.filename or "").suffix.lower() or ".mp3"
    if suffix not in _AUDIO_EXTS:
        raise HTTPException(status_code=400, detail=f"unsupported audio format: {suffix}")
    content = await _read_limited(file, _MAX_AUDIO_BYTES)
    dest = REFS_DIR / f"audio_{uuid.uuid4().hex[:10]}{suffix}"
    dest.write_bytes(content)
    return {"path": str(dest), "filename": file.filename, "type": "audio"}


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
                    output=None, output_relpath=None, error=None, model_type=task.model_type)
    threading.Thread(target=worker, args=(job_id, task.model_type, task.settings), daemon=True).start()
    return {"job_id": job_id, "status": "queued"}


@app.get("/status/{job_id}")
def status(job_id: str, x_jarvis_token: str | None = Header(default=None)):
    auth(x_jarvis_token)
    with _lock:
        if _job.get("job_id") != job_id:
            raise HTTPException(status_code=404, detail="job not found")
        return dict(_job)


@app.post("/cancel/{job_id}")
def cancel_job(job_id: str, x_jarvis_token: str | None = Header(default=None)):
    """Best-effort cancellation of the running job. This worker runs one job
    at a time, so cancelling only ever applies to the current job_id. Whether
    the in-flight WanGP task actually stops depends on submit_task() job
    support for .cancel() — engine_cancelled reports what really happened
    instead of pretending success."""
    auth(x_jarvis_token)
    with _lock:
        if _job.get("job_id") != job_id:
            raise HTTPException(status_code=404, detail="job not found")
        current_status = _job.get("status")
    if current_status not in ("queued", "running"):
        return {"job_id": job_id, "status": current_status, "engine_cancelled": False}
    engine_cancelled = get_adapter().cancel_current()
    if engine_cancelled:
        set_job(status="cancelled", phase="cancelled")
    with _lock:
        return {"job_id": job_id, "status": _job["status"], "engine_cancelled": engine_cancelled}


@app.get("/outputs")
def list_outputs(type: str | None = None, limit: int = 30, x_jarvis_token: str | None = Header(default=None)):
    """Lists generated files across all modalities (video, image, audio —
    motion outputs land in the same video/image extensions). ?type=video|
    image|audio filters; ?limit=N caps the count."""
    auth(x_jarvis_token)
    if type is not None and type not in ("video", "image", "audio"):
        raise HTTPException(status_code=400, detail="type must be one of: video, image, audio")

    video_exts = _VIDEO_EXTS | {".webp"}
    files = [f for f in OUTPUT_DIR.rglob("*") if f.is_file()]
    results = []
    for f in sorted(files, key=lambda item: item.stat().st_mtime, reverse=True):
        suffix = f.suffix.lower()
        kind = "video" if suffix in video_exts else _media_kind(suffix)
        if kind is None:
            continue
        if type is not None and kind != type:
            continue
        stat = f.stat()
        rel = f.relative_to(OUTPUT_DIR).as_posix()
        results.append({
            "name": rel,
            "url": f"/outputs/{rel}",
            "type": kind,
            "size_mb": round(stat.st_size / 1024 / 1024, 2),
            "created": stat.st_mtime,
        })
    return {"outputs": results[:limit]}


@app.get("/outputs/{filename:path}")
def get_output(filename: str, download: bool = False, x_jarvis_token: str | None = Header(default=None)):
    auth(x_jarvis_token)
    resolved = _safe_serve(OUTPUT_DIR, filename)
    media_type = _MEDIA_TYPES.get(resolved.suffix.lower(), "application/octet-stream")
    headers = {"Content-Disposition": f'attachment; filename="{resolved.name}"'} if download else None
    return FileResponse(str(resolved), media_type=media_type, headers=headers)


@app.get("/file/{filename:path}")
def get_file(filename: str, x_jarvis_token: str | None = Header(default=None)):
    """Alias serving from either OUTPUT_DIR (generated results) or REFS_DIR
    (uploaded references), matching the /file/{filename} route documented in
    the workflow map."""
    auth(x_jarvis_token)
    try:
        resolved = _safe_serve(OUTPUT_DIR, filename)
    except HTTPException:
        resolved = _safe_serve(REFS_DIR, filename)
    media_type = _MEDIA_TYPES.get(resolved.suffix.lower(), "application/octet-stream")
    return FileResponse(str(resolved), media_type=media_type)


@app.get("/video/{filename:path}")
def get_video(filename: str, x_jarvis_token: str | None = Header(default=None)):
    return get_file(filename, x_jarvis_token=x_jarvis_token)


@app.delete("/outputs/{filename:path}")
def delete_output(filename: str, x_jarvis_token: str | None = Header(default=None)):
    auth(x_jarvis_token)
    resolved = _safe_serve(OUTPUT_DIR, filename)
    if resolved.suffix.lower() not in _MEDIA_TYPES:
        raise HTTPException(status_code=403, detail="extension not allowed")
    resolved.unlink()
    return {"status": "ok", "deleted": filename}


def _close():
    global _adapter
    if _adapter is not None:
        try:
            _adapter.close()
        except Exception:
            pass
        _adapter = None

atexit.register(_close)
