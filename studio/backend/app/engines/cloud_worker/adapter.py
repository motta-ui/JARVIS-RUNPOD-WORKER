"""
CloudWorkerEngine — real adapter between JARVIS Studio and the JARVIS
RunPod Worker (jarvis-runpod-worker repo), a thin HTTP bridge over the
real Wan2GP engine (WanGPSession).

  JARVIS STUDIO -> this adapter -> Cloud Worker (/run_task) -> RunPod GPU
  -> WanGPSession -> Wan2GP model (model_type) -> generated file
  -> Worker /outputs/{path} -> this adapter downloads it -> JARVIS Gallery

One instance of this class is registered under EVERY WanGP model-family id
that engine_registry.py knows about (wan, ltx2, ltx, hunyuan, longcat,
magi, ovi, lucy_edit, chrono_edit, flux, qwen_image, z_image, ideogram,
hidream, krea, kiwi, ace_step, stable_audio, chatterbox, index_tts,
omnivoice, qwen_tts, heartmula, kugelaudio, dramabox, scenema, other) —
see engines/registry.py. This is not 26 different engines: it is the SAME
Cloud Worker and the SAME /run_task contract for all of them, because
config_importer.py's model_id is literally the Wan2GP model_type (the
stem of the file in 06_ALL_WANGP_DEFAULTS / workflow_configs/), confirmed
1:1 for all ~200 imported models across video/image/audio/motion. Only
.id/.name change per registration, purely for the UI; generate() behaves
identically regardless of which family id routed the job here — the
model_type is read from the job row (jobs.model), not from self.id.

Worker HTTP contract (jarvis-runpod-worker/jarvis_worker/app.py):
  GET  /health
  GET  /models
  GET  /default_settings/{model_type}
  POST /run_task              {model_type, settings} -> {job_id, status}
  GET  /progress                                      -> current job state
  POST /cancel/{job_id}
  POST /upload-ref             (multipart file) -> {path, filename, type}
  POST /upload-audio            (multipart file) -> {path, filename, type}
  GET  /outputs/{path}          (download, supports nested paths)

Real Wan2GP settings field names for file attachments — ground truth is
JARVIS_MODULE_WORKFLOWS_REFERENCE/05_COMMON/wgp.py (the actual upstream
Wan2GP engine source), specifically the ATTACHMENT_KEYS list and
validate_settings(). Never invented:
  image_start, image_end : single reference image path (i2v / end frame)
  image_refs              : list of reference image paths (multi-ref/inject)
  video_guide              : control video path
  video_source              : source video path (continuation)
  audio_guide                : audio conditioning path (lip-sync / TTS voice)

Studio's own reference_zones (backend/app/data/studio_<kind>.json) map onto
these attachment fields as follows:
  start_image                              -> image_start
  end_frame                                 -> image_end        (+ "E" in image_prompt_type)
  reference_image / _2 / _3,
  inject_frame_2 / _3, additional_frames     -> image_refs[]      (+ "I" in video_prompt_type)
  control_video                              -> video_guide       (+ video_prompt_type = control-video code)
  reference_video (continue mode)             -> video_source      (+ "V" in image_prompt_type)
  audio / reference_audio                     -> audio_guide       (+ "A" in audio_prompt_type)

wgp.py's validate_settings() SILENTLY DISCARDS an attachment whose
activation letter is missing (e.g. audio_guide is set to None unless "A"
is in audio_prompt_type) — so the flags above are not cosmetic, they are
required. Each one set here has direct textual evidence in wgp.py (see
ATTACHMENT_KEYS, and the "if 'A' in audio_prompt_type" / "if 'I' in
video_prompt_type" / "if 'V' in image_prompt_type" / the "End Image(s)"
Gradio label tied to "E" in image_prompt_type). The full per-model-family
letter grammar (S/V/L for image_prompt_type, K/F/Y/W/Z for video_prompt_type,
B/X/K for audio_prompt_type, ...) is not fully documented in the available
source and is NOT reverse-engineered here — this adapter only adds the
letters it has verified, and otherwise unions them onto the model's own
get_default_settings() flags rather than overwriting/inventing a baseline.

control_video_option (Studio's data/control_video.json ids) -> WanGP
video_prompt_type code: verified directly from
01_VIDEO/frontend/index.html's ctrl-select options (Canny=EVG,
Profundidade=DVG, Movimento Humano=PVG, Pose Align=OVG, IC Bruto=VG,
HDR=V&G, Animar Personagem=V1), also documented in 00_WORKFLOW_MAP.md.

Workflow/LoRA/utility resolution (JARVIS_WORKFLOW_PARITY_PACK, 2026-09-09):
`_run()` resolves, in order, the logical workflow (registry/
workflow_resolver.py — e.g. Image Motion routes to i2v or flf depending
on end_frame presence), the LoRAs (registry/lora_resolver.py — real
`activated_loras`/`loras_multipliers` for standalone LTX2 LoRAs, verified
against models/ltx2/ltx2_handler.py and ltx2.py on the real Pod; LoRAs
the Wan2GP engine manages internally via flags are never listed there),
and the advanced settings (registry/utility_resolver.py — gated per
model family, only fields audited against the real wgp.py go through).
`get_capabilities()["lora"]` is real (True) for the ltx2 family; other
families still don't have an audited LoRA capability file, so they keep
returning conflicts instead of guessing.
"""
from __future__ import annotations

import json
import mimetypes
import threading
import time
from pathlib import Path
from typing import Any

from ..base import BaseEngine
from ...config import OUTPUTS_DIR
from ...cloud import worker_connection as wc
from ... import database as db
from ...registry import workflow_resolver, lora_resolver, utility_resolver
from .payload_builders import apply_workflow_extras

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

REQUEST_TIMEOUT = 20
UPLOAD_TIMEOUT = 300
DOWNLOAD_TIMEOUT = 900
POLL_INTERVAL_SECONDS = 2
MAX_WAIT_SECONDS = 45 * 60

# All ~26 CloudWorkerEngine instances (one per WanGP model family, see
# registry.py) point at the exact same Cloud Worker connection, so their
# health() would otherwise make that many identical, sequential /health
# requests every time something like GET /api/engines lists them all --
# harmless against a fast local fake worker, but ~15s against a real
# remote Worker over a network hop (confirmed against the live RunPod Pod).
# Shared, short-TTL cache keyed by base URL so a burst of calls collapses
# into one real request.
_HEALTH_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_HEALTH_CACHE_TTL_SECONDS = 5.0

AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a", ".opus", ".wma"}

SINGLE_IMAGE_ZONES = {"start_image": "image_start", "end_frame": "image_end"}
LIST_IMAGE_ZONES = (
    "reference_image", "reference_image_2", "reference_image_3",
    "inject_frame_2", "inject_frame_3", "additional_frames",
)
VIDEO_ZONES = {"control_video": "video_guide", "reference_video": "video_source"}
AUDIO_ZONES = ("audio", "reference_audio")  # both map to audio_guide — first one present wins

CONTROL_VIDEO_CODES = {
    "canny": "EVG", "depth": "DVG", "human_motion": "PVG", "pose_align": "OVG",
    "ic_raw": "VG", "hdr": "V&G", "animate_character": "V1",
}


class CloudWorkerEngine(BaseEngine):
    def __init__(self, engine_id: str, name: str):
        self.id = engine_id
        self.name = name
        self._jobs: dict[str, dict[str, Any]] = {}

    # -- BaseEngine ------------------------------------------------------

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "t2v": True, "i2v": True, "t2i": True, "i2i": True,
            "audio": True, "music": True, "speech": True,
            "motion": True, "control_video": True, "frame_injection": True,
            "reference_generation": True,
            # Resolução real de LoRA (registry/lora_resolver.py) só está
            # auditada para a família ltx2_22B* por agora — outras famílias
            # continuam sem tradução real (ver histórico deste ficheiro).
            "lora": self.id == "ltx2",
            "requires_cloud_worker": True,
        }

    def validate_request(self, job_params: dict[str, Any]) -> tuple[bool, str | None]:
        if not HAS_REQUESTS:
            return False, "Dependência 'requests' não instalada (ver backend/requirements.txt)."
        if not wc.get_worker_base_url():
            return False, ("Nenhum Cloud Worker configurado. Liga um Worker em "
                            "Sistema -> Cloud antes de gerar com este engine.")
        return True, None

    def upload(self, file_path: str) -> str:
        base = wc.get_worker_base_url()
        if not base:
            raise RuntimeError("Nenhum Cloud Worker configurado.")
        return self._upload_to_worker(base, self._headers(), Path(file_path))

    def generate(self, job_id: str, job_params: dict[str, Any]) -> None:
        self._jobs[job_id] = {"status": "QUEUED", "progress": 0.0}
        threading.Thread(target=self._run, args=(job_id, job_params), daemon=True).start()

    def get_status(self, job_id: str) -> dict[str, Any]:
        return self._jobs.get(job_id, {"status": "UNKNOWN", "progress": 0.0})

    def cancel(self, job_id: str) -> bool:
        info = self._jobs.get(job_id) or {}
        worker_job_id = info.get("worker_job_id")
        base = wc.get_worker_base_url()
        if base and worker_job_id and HAS_REQUESTS:
            try:
                requests.post(f"{base}/cancel/{worker_job_id}", headers=self._headers(), timeout=REQUEST_TIMEOUT)
            except Exception:
                pass  # o Worker pode estar inacessível — ainda assim marcamos CANCELLED do lado do Studio
        self._jobs[job_id] = {**info, "status": "CANCELLED"}
        with db.db_session() as conn:
            conn.execute(
                "UPDATE jobs SET status=?, completed_at=?, updated_at=? WHERE id=?",
                ("CANCELLED", db.now_iso(), db.now_iso(), job_id),
            )
        return True

    def get_output(self, job_id: str) -> str | None:
        return self._jobs.get(job_id, {}).get("output")

    def health(self) -> dict[str, Any]:
        base = wc.get_worker_base_url()
        if not base:
            return {"online": False, "detail": "Nenhum Cloud Worker configurado (ver Sistema -> Cloud)."}
        if not HAS_REQUESTS:
            return {"online": False, "detail": "Dependência 'requests' em falta."}

        cached = _HEALTH_CACHE.get(base)
        now = time.time()
        if cached and now - cached[0] < _HEALTH_CACHE_TTL_SECONDS:
            return cached[1]

        try:
            r = requests.get(f"{base}/health", headers=self._headers(), timeout=REQUEST_TIMEOUT)
            r.raise_for_status()
            result = {"online": True, "detail": f"Worker ligado em {base}."}
        except Exception as e:
            result = {"online": False, "detail": f"Worker não respondeu ({base}): {e}"}
        _HEALTH_CACHE[base] = (now, result)
        return result

    # -- internos ----------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        token = wc.get_worker_token()
        return {"X-Jarvis-Token": token} if token else {}

    def _set_job(self, job_id: str, **fields):
        self._jobs[job_id] = {**self._jobs.get(job_id, {}), **fields}
        db_fields = {k: v for k, v in fields.items() if k not in ("worker_job_id", "output")}
        if not db_fields:
            return
        cols = ", ".join(f"{k}=?" for k in db_fields)
        with db.db_session() as conn:
            conn.execute(
                f"UPDATE jobs SET {cols}, updated_at=? WHERE id=?",
                (*db_fields.values(), db.now_iso(), job_id),
            )

    def _upload_to_worker(self, base: str, headers: dict, local_path: Path) -> str:
        if not local_path.is_file():
            raise RuntimeError(f"Referência não encontrada em disco: {local_path}")
        suffix = local_path.suffix.lower()
        endpoint = "/upload-audio" if suffix in AUDIO_EXTS else "/upload-ref"
        mime = mimetypes.guess_type(local_path.name)[0] or "application/octet-stream"
        with open(local_path, "rb") as f:
            r = requests.post(
                f"{base}{endpoint}", headers=headers,
                files={"file": (local_path.name, f, mime)}, timeout=UPLOAD_TIMEOUT,
            )
        r.raise_for_status()
        return r.json()["path"]

    def _resolve_zone_uploads(self, base: str, headers: dict, job_params: dict[str, Any]) -> dict[str, Any]:
        """Faz upload real de cada referência local para o Worker e traduz as
        reference_zones do Studio para os campos reais do Wan2GP. Devolve o
        dict de settings já com os *_add (letras de ativação a unir com os
        defaults reais do modelo em _run(), nunca a inventar a base)."""
        settings: dict[str, Any] = {}
        image_prompt_type_add = ""
        video_prompt_type_add = ""
        audio_prompt_type_add = ""

        for zone_key, field in SINGLE_IMAGE_ZONES.items():
            local_path = job_params.get(zone_key)
            if not local_path:
                continue
            settings[field] = self._upload_to_worker(base, headers, Path(local_path))
            if zone_key == "end_frame":
                image_prompt_type_add += "E"

        image_refs = [
            self._upload_to_worker(base, headers, Path(job_params[zone_key]))
            for zone_key in LIST_IMAGE_ZONES if job_params.get(zone_key)
        ]
        if image_refs:
            settings["image_refs"] = image_refs
            video_prompt_type_add += "I"

        for zone_key, field in VIDEO_ZONES.items():
            local_path = job_params.get(zone_key)
            if not local_path:
                continue
            settings[field] = self._upload_to_worker(base, headers, Path(local_path))
            if zone_key == "reference_video":
                image_prompt_type_add += "V"

        for zone_key in AUDIO_ZONES:
            local_path = job_params.get(zone_key)
            if not local_path:
                continue
            settings["audio_guide"] = self._upload_to_worker(base, headers, Path(local_path))
            audio_prompt_type_add += "A"
            break  # "audio" e "reference_audio" mapeiam ao mesmo campo — não sobrepor

        control_option = job_params.get("control_video_option")
        if control_option and job_params.get("control_video"):
            code = CONTROL_VIDEO_CODES.get(control_option)
            if code:
                settings["video_prompt_type"] = code  # modo completo — substitui, não acumula

        settings["_image_prompt_type_add"] = image_prompt_type_add
        settings["_video_prompt_type_add"] = video_prompt_type_add
        settings["_audio_prompt_type_add"] = audio_prompt_type_add
        return settings

    def _download_output(self, base: str, headers: dict, job_id: str, worker_output: dict) -> Path:
        rel = worker_output.get("output_relpath")
        source = worker_output.get("output")
        if not rel:
            raise RuntimeError(
                f"O Worker devolveu um output fora do seu OUTPUT_DIR ({source!r}) — "
                "não é possível transferi-lo via /outputs/{path}."
            )
        out_dir = OUTPUTS_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        dest = out_dir / Path(rel).name
        r = requests.get(f"{base}/outputs/{rel}", headers=headers, stream=True, timeout=DOWNLOAD_TIMEOUT)
        r.raise_for_status()
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=1 << 20):
                if chunk:
                    f.write(chunk)
        return dest

    def _insert_gallery_item(self, job_id: str, job_row: dict, job_params: dict, output_path: Path) -> None:
        import uuid as _uuid
        ts = db.now_iso()
        with db.db_session() as conn:
            conn.execute(
                "INSERT INTO gallery_items (id, project_id, job_id, kind, file_path, prompt, engine, "
                "model, parameters, seed, duration_seconds, resolution, preset_id, preset_name, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(_uuid.uuid4()), job_row.get("project_id"), job_id, job_row.get("kind"), str(output_path),
                    job_row.get("prompt"), job_row.get("engine"), job_row.get("model"),
                    job_row.get("parameters"), job_params.get("seed"),
                    job_params.get("duration_seconds"), job_params.get("resolution"),
                    job_row.get("preset_id"), job_row.get("preset_name"),
                    ts,
                ),
            )

    def _run(self, job_id: str, job_params: dict[str, Any]) -> None:
        try:
            with db.db_session() as conn:
                row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            job_row = db.row_to_dict(row) if row else {}
            model_type = job_row.get("model")
            if not model_type:
                raise RuntimeError("Job sem model associado — não é possível saber que model_type submeter ao Worker.")

            base = wc.get_worker_base_url()
            if not base:
                raise RuntimeError("Nenhum Cloud Worker configurado (Sistema -> Cloud).")
            headers = self._headers()

            self._set_job(job_id, status="RUNNING", started_at=db.now_iso())

            # --- 1. Resolver o WORKFLOW LÓGICO (nunca um payload genérico) ---
            mode = job_row.get("mode") or ""
            workflow_id, workflow_warnings = workflow_resolver.resolve_workflow(mode, job_params)
            missing = workflow_resolver.check_required_inputs(workflow_id, {
                k: bool(job_params.get(k)) for k in (
                    "start_image", "end_frame", "reference_image", "reference_video",
                    "control_video", "audio", "prompt",
                )
            })
            if missing:
                raise RuntimeError(
                    f"Workflow '{workflow_id}' (mode '{mode}') sem input(s) obrigatório(s): {', '.join(missing)}."
                )

            settings: dict[str, Any] = {}
            if job_params.get("prompt"):
                settings["prompt"] = job_params["prompt"]
            if job_params.get("negative_prompt"):
                settings["negative_prompt"] = job_params["negative_prompt"]
            if job_params.get("resolution"):
                settings["resolution"] = job_params["resolution"]
            if job_params.get("seed") is not None:
                settings["seed"] = job_params["seed"]
            steps = job_params.get("steps")
            if steps not in (None, "", "Auto"):
                try:
                    settings["num_inference_steps"] = int(steps)
                except (TypeError, ValueError):
                    pass
            if job_params.get("source_strength") is not None:
                settings["input_video_strength"] = job_params["source_strength"]  # Continue: preserve do pacote
            if job_params.get("guidance_scale") is not None:
                settings["guidance_scale"] = job_params["guidance_scale"]
            # 'extra' continua um escape-hatch cru (ex.: video_length) — só
            # 'advanced' passa pelo gate real de capability (ver abaixo).
            for key, val in (job_params.get("extra") or {}).items():
                if val not in (None, ""):
                    settings[key] = val

            zone_settings = self._resolve_zone_uploads(base, headers, job_params)
            prompt_type_adds = {
                "image_prompt_type": zone_settings.pop("_image_prompt_type_add", ""),
                "video_prompt_type": zone_settings.pop("_video_prompt_type_add", ""),
                "audio_prompt_type": zone_settings.pop("_audio_prompt_type_add", ""),
            }
            control_video_type_set = "video_prompt_type" in zone_settings
            settings.update(zone_settings)

            if any(prompt_type_adds.values()):
                model_defaults: dict[str, Any] = {}
                try:
                    r = requests.get(f"{base}/default_settings/{model_type}", headers=headers, timeout=REQUEST_TIMEOUT)
                    r.raise_for_status()
                    model_defaults = r.json().get("settings") or {}
                except Exception:
                    pass  # sem defaults do Worker — as flags ainda assim são acrescentadas a partir de ""
                for key, add in prompt_type_adds.items():
                    if not add:
                        continue
                    if key == "video_prompt_type" and control_video_type_set:
                        continue  # já é um código de modo completo (control_video_option) — não misturar letras
                    base_value = str(settings.get(key, model_defaults.get(key, "")) or "")
                    settings[key] = "".join(sorted(set(base_value) | set(add)))

            # --- 2. Resolver UTILITÁRIOS (advanced settings, gate real por família) ---
            advanced_resolution = utility_resolver.resolve_advanced(model_type, job_params.get("advanced"))
            settings.update(advanced_resolution["applied"])
            utility_conflicts = list(workflow_warnings) + [
                f"advanced '{k}' rejeitado: {why}" for k, why in advanced_resolution["rejected"].items()
            ]

            # --- 3. Resolver LORAS (nunca reenviar a lista crua da UI) ---
            # allowed_modes/incompatible_modes no catálogo de LoRAs são os
            # modos REAIS do Wan2GP (t2v/i2v/flf/continue) — usar o
            # workflow_id já resolvido, nunca o `mode` do JARVIS (ex.:
            # "image_motion" não existe nesse vocabulário).
            lora_resolution = lora_resolver.resolve_loras(
                model_id=model_type,
                mode=workflow_id,
                user_selection=job_params.get("loras_selection") or [],
                available_inputs={"has_ctrl_video": bool(job_params.get("control_video"))},
            )
            utility_conflicts += lora_resolution["conflicts"] + lora_resolution["controls_needed"]
            for key, value in lora_resolution["extra_settings"].items():
                if key == "video_prompt_type":
                    existing = str(settings.get("video_prompt_type", ""))
                    settings["video_prompt_type"] = "".join(sorted(set(existing) | set(str(value))))
                else:
                    settings[key] = value

            # --- 3b. Extras específicos do workflow (Image Motion, Talking
            # Image, Infinite Talk, Character Animate) sobre a base já
            # correcta acima ---
            apply_workflow_extras(workflow_id, job_params, settings, model_id=model_type)

            # --- 4. Persistir exactamente o que foi resolvido/enviado (reprodutibilidade) ---
            self._set_job(job_id, resolution_snapshot=json.dumps({
                "workflow_id": workflow_id, "mode": mode, "model_type": model_type,
                "loras_applied": lora_resolution["applied"], "loras_automatic": lora_resolution["automatic"],
                "conflicts": utility_conflicts, "seed": settings.get("seed"),
                "settings_sent": {k: v for k, v in settings.items() if k not in ("prompt",)},
            }, default=str))

            self._set_job(job_id, progress=0.02)

            resp = requests.post(
                f"{base}/run_task", headers=headers,
                json={"model_type": model_type, "settings": settings}, timeout=REQUEST_TIMEOUT,
            )
            resp.raise_for_status()
            worker_job_id = resp.json()["job_id"]
            self._jobs[job_id]["worker_job_id"] = worker_job_id
            with db.db_session() as conn:
                conn.execute(
                    "UPDATE jobs SET worker_job_id=?, updated_at=? WHERE id=?",
                    (worker_job_id, db.now_iso(), job_id),
                )

            elapsed = 0
            while elapsed < MAX_WAIT_SECONDS:
                if self._jobs.get(job_id, {}).get("status") == "CANCELLED":
                    return
                time.sleep(POLL_INTERVAL_SECONDS)
                elapsed += POLL_INTERVAL_SECONDS
                try:
                    r = requests.get(f"{base}/progress", headers=headers, timeout=REQUEST_TIMEOUT)
                    r.raise_for_status()
                    prog = r.json()
                except Exception:
                    continue
                if prog.get("job_id") != worker_job_id:
                    continue
                status = prog.get("status")
                if status in ("queued", "running"):
                    self._set_job(job_id, status="PROCESSING",
                                   progress=min(0.95, (prog.get("progress") or 0) / 100))
                elif status == "completed":
                    local_output = self._download_output(base, headers, job_id, prog)
                    ts = db.now_iso()
                    self._set_job(job_id, status="COMPLETED", progress=1.0,
                                   output_path=str(local_output), completed_at=ts)
                    self._jobs[job_id]["output"] = str(local_output)
                    self._insert_gallery_item(job_id, job_row, job_params, local_output)
                    return
                elif status in ("failed", "cancelled"):
                    err = prog.get("error") or f"Worker reportou status '{status}'"
                    final = "FAILED" if status == "failed" else "CANCELLED"
                    self._set_job(job_id, status=final, error=err, completed_at=db.now_iso())
                    return
            self._set_job(job_id, status="FAILED", error="timeout a aguardar o Cloud Worker", completed_at=db.now_iso())
        except Exception as e:  # noqa: BLE001 — qualquer falha (rede, upload, Worker) marca FAILED, nunca crasha a app
            self._set_job(job_id, status="FAILED", error=str(e), completed_at=db.now_iso())
