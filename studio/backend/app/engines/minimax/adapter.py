"""
Adapter MiniMax H3 — integração REAL com a API de vídeo oficial do MiniMax.

Implementado a partir da documentação oficial consultada em:
  https://platform.minimax.io/docs/guides/video-generation
  https://platform.minimax.io/docs/api-reference/video-generation-v2-delete

Fluxo (assíncrono, 3 passos, conforme documentado):
  1. POST /v2/video_generation            -> devolve task_id
  2. GET  /v2/query/video_generation/{id} -> poll do status
  3. task.content.url                      -> download do vídeo (válido ~9h)

Cancelamento: DELETE /v2/video_generation/{task_id}
  - task 'queued'   -> cancela (sem custo)
  - task 'succeeded'/'failed' -> apaga o registo
  - task 'running'  -> a API recusa (não é possível cancelar a meio)

LIMITAÇÃO CONHECIDA E DOCUMENTADA (não inventada): a API de vídeo espera
URLs publicamente acessíveis para imagens/vídeos/áudio de referência
(role=first_frame / last_frame / reference_image / reference_video /
reference_audio). Existe uma API genérica de upload de ficheiros
(/v1/files/upload), mas a documentação pública não confirma o valor de
`purpose` nem o formato de referência compatíveis com o endpoint de
vídeo — por isso este adapter NÃO inventa esse mecanismo. Por agora,
usa URLs já hospedadas (job_params: start_image_url, end_frame_url,
reference_image_urls, reference_video_urls, reference_audio_urls). O
Cloud Worker (arquitetura em engines/cloud/) resolverá isto no futuro
ao hospedar os assets de forma acessível.
"""
import threading
import time
from typing import Any

from ..base import BaseEngine
from ...config import get_env, OUTPUTS_DIR
from ... import database as db

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

DEFAULT_BASE_URL = "https://api.minimax.io"
MODEL_H3 = "MiniMax-H3"
MODEL_H3_MAX = "MiniMax-H3-Max"

POLL_INTERVAL_SECONDS = 10   # recomendado pela documentação oficial
MAX_WAIT_SECONDS = 20 * 60   # timeout de segurança


class MiniMaxEngine(BaseEngine):
    id = "minimax"
    name = "MiniMax H3"

    def __init__(self):
        self.api_key = get_env("MINIMAX_API_KEY", "")
        self.base_url = get_env("MINIMAX_BASE_URL", DEFAULT_BASE_URL)
        self._jobs: dict[str, dict[str, Any]] = {}

    # -- BaseEngine --------------------------------------------------

    def get_capabilities(self) -> dict[str, Any]:
        # Reflete apenas o que a API do MiniMax H3 documenta hoje.
        # NUNCA declarar aqui algo que a API não suporte de facto.
        return {
            "t2v": True,
            "i2v": True,                 # first/last frame
            "reference_generation": True,  # imagens/vídeo/áudio de referência
            "audio": False,               # H3 não expõe geração de áudio isolado por este endpoint
            "custom_lora": False,
            "control_video": False,
            "min_duration_seconds": 4,
            "max_duration_seconds": 15,
            "resolutions": ["768P", "2K"],
        }

    def validate_request(self, job_params: dict[str, Any]) -> tuple[bool, str | None]:
        if not HAS_REQUESTS:
            return False, "Dependência 'requests' não instalada (ver backend/requirements.txt)."
        if not self.api_key:
            return False, "MINIMAX_API_KEY não configurada no .env"
        prompt = job_params.get("prompt", "") or ""
        if len(prompt) > 7000:
            return False, "Prompt excede o limite de 7000 caracteres do MiniMax H3."
        duration = job_params.get("duration_seconds")
        if duration is not None and not (4 <= int(duration) <= 15):
            return False, "MiniMax H3 aceita durações entre 4 e 15 segundos (inteiro)."
        return True, None

    def upload(self, file_path: str) -> str:
        raise RuntimeError(
            "Upload direto de ficheiros locais para o MiniMax H3 não é suportado "
            "por este adapter (ver docstring do módulo). Usa uma URL pública "
            "(start_image_url / end_frame_url / reference_image_urls / "
            "reference_video_urls / reference_audio_urls)."
        )

    def generate(self, job_id: str, job_params: dict[str, Any]) -> None:
        self._jobs[job_id] = {"status": "QUEUED", "progress": 0.0}
        threading.Thread(target=self._run, args=(job_id, job_params), daemon=True).start()

    def get_status(self, job_id: str) -> dict[str, Any]:
        return self._jobs.get(job_id, {"status": "UNKNOWN", "progress": 0.0})

    def cancel(self, job_id: str) -> bool:
        info = self._jobs.get(job_id)
        task_id = info.get("task_id") if info else None
        if task_id:
            try:
                requests.delete(
                    f"{self.base_url}/v2/video_generation/{task_id}",
                    headers=self._headers(), timeout=15,
                )
            except Exception:
                pass  # a API pode recusar se a task já estiver 'running' — não é um erro fatal aqui
        self._jobs[job_id] = {**(info or {}), "status": "CANCELLED"}
        with db.db_session() as conn:
            conn.execute(
                "UPDATE jobs SET status=?, completed_at=?, updated_at=? WHERE id=?",
                ("CANCELLED", db.now_iso(), db.now_iso(), job_id),
            )
        return True

    def get_output(self, job_id: str) -> str | None:
        return self._jobs.get(job_id, {}).get("output")

    def health(self) -> dict[str, Any]:
        if not HAS_REQUESTS:
            return {"online": False, "detail": "Dependência 'requests' em falta."}
        if not self.api_key:
            return {"online": False, "detail": "MINIMAX_API_KEY em falta no .env."}
        return {"online": True, "detail": "MiniMax H3 configurado."}

    # -- internos ------------------------------------------------------

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _build_content(self, job_params: dict[str, Any]) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = [{"type": "text", "text": job_params.get("prompt") or ""}]
        if job_params.get("start_image_url"):
            content.append({"type": "image_url", "image_url": {"url": job_params["start_image_url"]}, "role": "first_frame"})
        if job_params.get("end_frame_url"):
            content.append({"type": "image_url", "image_url": {"url": job_params["end_frame_url"]}, "role": "last_frame"})
        for url in job_params.get("reference_image_urls") or []:
            content.append({"type": "image_url", "image_url": {"url": url}, "role": "reference_image"})
        for url in job_params.get("reference_video_urls") or []:
            content.append({"type": "video_url", "video_url": {"url": url}, "role": "reference_video"})
        for url in job_params.get("reference_audio_urls") or []:
            content.append({"type": "audio_url", "audio_url": {"url": url}, "role": "reference_audio"})
        return content

    def _set_job(self, job_id: str, **fields):
        self._jobs[job_id] = {**self._jobs.get(job_id, {}), **fields}
        cols = ", ".join(f"{k}=?" for k in fields)
        with db.db_session() as conn:
            conn.execute(
                f"UPDATE jobs SET {cols}, updated_at=? WHERE id=?",
                (*fields.values(), db.now_iso(), job_id),
            )

    def _run(self, job_id: str, job_params: dict[str, Any]) -> None:
        try:
            self._set_job(job_id, status="RUNNING", started_at=db.now_iso())

            model = job_params.get("minimax_model") or MODEL_H3
            duration = int(job_params.get("duration_seconds") or 5)
            resolution = job_params.get("resolution_tier") or "768P"
            content = self._build_content(job_params)
            has_image = any(c["type"] == "image_url" for c in content)

            payload: dict[str, Any] = {
                "model": model, "content": content, "duration": duration, "resolution": resolution,
            }
            if not has_image:
                # ratio é obrigatório para t2v puro; com imagem a API assume 'adaptive' sozinha
                payload["ratio"] = job_params.get("format") or "16:9"

            resp = requests.post(f"{self.base_url}/v2/video_generation", headers=self._headers(), json=payload, timeout=30)
            resp.raise_for_status()
            task_id = resp.json()["task_id"]
            self._set_job(job_id, status="PROCESSING", progress=0.05)
            self._jobs[job_id]["task_id"] = task_id

            poll_url = f"{self.base_url}/v2/query/video_generation/{task_id}"
            elapsed, progress = 0, 0.05
            while elapsed < MAX_WAIT_SECONDS:
                time.sleep(POLL_INTERVAL_SECONDS)
                elapsed += POLL_INTERVAL_SECONDS

                if self._jobs.get(job_id, {}).get("status") == "CANCELLED":
                    return

                r = requests.get(poll_url, headers=self._headers(), timeout=30)
                r.raise_for_status()
                task = r.json().get("task", {})
                status = task.get("status")

                if status == "succeeded":
                    video_url = task["content"]["url"]
                    out_dir = OUTPUTS_DIR / job_id
                    out_dir.mkdir(parents=True, exist_ok=True)
                    out_file = out_dir / "output.mp4"
                    with requests.get(video_url, stream=True, timeout=120) as vr:
                        vr.raise_for_status()
                        with open(out_file, "wb") as f:
                            for chunk in vr.iter_content(chunk_size=1 << 20):
                                f.write(chunk)
                    ts = db.now_iso()
                    self._set_job(job_id, status="COMPLETED", progress=1.0, output_path=str(out_file), completed_at=ts)
                    self._jobs[job_id]["output"] = str(out_file)
                    return

                if status in ("failed", "cancelled"):
                    err = str(task.get("error") or status)
                    final = "FAILED" if status == "failed" else "CANCELLED"
                    self._set_job(job_id, status=final, error=err, completed_at=db.now_iso())
                    return

                progress = min(0.92, progress + 0.05)
                self._set_job(job_id, status="PROCESSING", progress=progress)

            self._set_job(job_id, status="FAILED", error="timeout a aguardar resposta do MiniMax H3", completed_at=db.now_iso())

        except Exception as e:  # noqa: BLE001 — qualquer falha de rede/API deve marcar o job como FAILED, nunca travar a app
            self._set_job(job_id, status="FAILED", error=str(e), completed_at=db.now_iso())
