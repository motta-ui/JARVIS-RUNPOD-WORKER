"""
MockEngine: adapter DEMO que simula geração sem GPU e sem internet.

Serve para o JARVIS funcionar de ponta a ponta (fila de jobs, progresso,
cancelamento, output, galeria) em qualquer um dos 4 módulos (video,
image, audio, motion) antes de qualquer engine real estar ligado.
Os engines reais seguem o mesmo contrato em engines/<nome>/adapter.py.
"""
import json
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from ..base import BaseEngine
from ...config import OUTPUTS_DIR
from ... import database as db

# quanto tempo (em passos de 0.3s) uma geração demo demora, por kind
STEPS_BY_KIND = {"video": 16, "image": 6, "audio": 10, "motion": 12}

OUTPUT_EXT = {"video": "mp4", "image": "png", "audio": "wav", "motion": "mp4"}


class MockEngine(BaseEngine):
    id = "mock"
    name = "JARVIS Mock Engine (Demo)"

    def __init__(self):
        self._jobs: dict[str, dict[str, Any]] = {}

    def get_capabilities(self) -> dict[str, Any]:
        return {
            "t2v": True, "i2v": True, "t2i": True, "i2i": True,
            "audio": True, "music": True, "sfx": True, "speech": True,
            "motion": True, "lora": True, "control_video": True,
            "frame_injection": True, "batch": True,
            "max_duration_seconds": 120,
        }

    def validate_request(self, job_params: dict[str, Any]) -> tuple[bool, str | None]:
        duration = job_params.get("duration_seconds")
        if duration and (duration < 1 or duration > 120):
            return False, "Duração fora do intervalo permitido (1-120s)."
        return True, None

    def upload(self, file_path: str) -> str:
        return f"mock-upload://{Path(file_path).name}"

    def generate(self, job_id: str, job_params: dict[str, Any]) -> None:
        self._jobs[job_id] = {"status": "QUEUED", "progress": 0.0}
        threading.Thread(target=self._run, args=(job_id, job_params), daemon=True).start()

    def _run(self, job_id: str, job_params: dict[str, Any]) -> None:
        with db.db_session() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        job_row = db.row_to_dict(row) if row else {}
        kind = job_row.get("kind") or "video"
        steps = STEPS_BY_KIND.get(kind, 12)

        with db.db_session() as conn:
            conn.execute(
                "UPDATE jobs SET status=?, started_at=?, updated_at=? WHERE id=?",
                ("RUNNING", db.now_iso(), db.now_iso(), job_id),
            )

        for i in range(1, steps + 1):
            # verificar cancelamento antes E depois do sleep — cancel() pode
            # chegar a meio do sleep, por isso reverificar é obrigatório
            # para não reescrever CANCELLED com PROCESSING por cima.
            if self._jobs.get(job_id, {}).get("status") == "CANCELLED":
                return
            time.sleep(0.3)
            if self._jobs.get(job_id, {}).get("status") == "CANCELLED":
                return
            progress = i / steps
            self._jobs[job_id] = {"status": "PROCESSING", "progress": progress}
            with db.db_session() as conn:
                conn.execute(
                    "UPDATE jobs SET status=?, progress=?, updated_at=? WHERE id=? AND status != 'CANCELLED'",
                    ("PROCESSING", progress, db.now_iso(), job_id),
                )

        # última verificação antes de gravar o output — se foi cancelado
        # entre o último passo e aqui, não sobrescrever.
        if self._jobs.get(job_id, {}).get("status") == "CANCELLED":
            return

        ext = OUTPUT_EXT.get(kind, "bin")
        out_dir = OUTPUTS_DIR / job_id
        out_dir.mkdir(parents=True, exist_ok=True)
        out_file = out_dir / f"output.{ext}.txt"
        out_file.write_text(
            f"JARVIS AI STUDIO - output DEMO ({kind}, modo mock, sem GPU)\n"
            f"job_id={job_id}\nparametros={job_params}\n",
            encoding="utf-8",
        )

        ts = db.now_iso()
        self._jobs[job_id] = {"status": "COMPLETED", "progress": 1.0, "output": str(out_file)}
        with db.db_session() as conn:
            updated = conn.execute(
                "UPDATE jobs SET status=?, progress=?, output_path=?, completed_at=?, updated_at=? "
                "WHERE id=? AND status != 'CANCELLED'",
                ("COMPLETED", 1.0, str(out_file), ts, ts, job_id),
            )
            if updated.rowcount == 0:
                return  # foi cancelado mesmo à última da hora — não registar na galeria
            # regista no histórico/galeria automaticamente
            conn.execute(
                "INSERT INTO gallery_items (id, project_id, job_id, kind, file_path, prompt, engine, "
                "model, parameters, seed, duration_seconds, resolution, preset_id, preset_name, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(uuid.uuid4()), job_row.get("project_id"), job_id, kind, str(out_file),
                    job_row.get("prompt"), job_row.get("engine"), job_row.get("model"),
                    job_row.get("parameters"), (job_params or {}).get("seed"),
                    (job_params or {}).get("duration_seconds"), (job_params or {}).get("resolution"),
                    job_row.get("preset_id"), job_row.get("preset_name"),
                    ts,
                ),
            )

    def get_status(self, job_id: str) -> dict[str, Any]:
        return self._jobs.get(job_id, {"status": "UNKNOWN", "progress": 0.0})

    def cancel(self, job_id: str) -> bool:
        self._jobs[job_id] = {"status": "CANCELLED", "progress": 0.0}
        with db.db_session() as conn:
            conn.execute(
                "UPDATE jobs SET status=?, completed_at=?, updated_at=? WHERE id=?",
                ("CANCELLED", db.now_iso(), db.now_iso(), job_id),
            )
        return True

    def get_output(self, job_id: str) -> str | None:
        return self._jobs.get(job_id, {}).get("output")

    def health(self) -> dict[str, Any]:
        return {"online": True, "detail": "Mock engine sempre disponível (sem GPU, sem internet)."}
