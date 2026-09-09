#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
acs_wan_client.py — LADO acs_api: cliente HTTP do worker.
SUBSTITUI o gradio_client. É isto que o _generate_background passa a chamar,
no lugar dos 10 PASSOs + save_inputs posicional + process_tasks + polling.

Usa APENAS stdlib (urllib) — o runtime leve não tem 'requests'.

[JARVIS-RUNPOD 2026-09-09] Adaptado para o Worker real do projeto JARVIS
(jarvis_worker/app.py), que roda num RunPod remoto, não na mesma máquina:

  1. Header de auth renomeado para X-Jarvis-Token (nome real do Worker;
     era X-ACS-Token, herdado de quando o worker rodava localmente).
  2. generate() deixou de ser 1 POST bloqueante. O /run_task do Worker
     é assíncrono (devolve job_id na hora) — generate() agora faz
     POST /run_task, espera via GET /progress (mesma lógica já validada
     em studio/backend antigo, engines/cloud_worker/adapter.py), e só
     então devolve {ok, path, ...}.
  3. Novo passo: download real do arquivo — o Worker está num Pod remoto,
     o "path" que ele devolve é um caminho REMOTO (/workspace/outputs/...).
     generate() baixa via GET /outputs/{path} para OUTPUTS_DIR local antes
     de devolver, porque todo o resto do acs_api.py (outputs/, /file/,
     /thumb/) espera um path LOCAL de verdade.

Nada disto muda o contrato que o acs_api.py já conhece (generate() continua
devolvendo {ok, path, media_type, error}) — só o que acontece por dentro.
"""
from __future__ import annotations
import json as _json, mimetypes, os, time, urllib.request, urllib.error, urllib.parse
from pathlib import Path

import httpx


class WanClient:
    def __init__(self, base: str = "http://127.0.0.1:7872", gen_timeout: int = 10800,
                 outputs_dir: str | Path | None = None, poll_interval: float = 2.0):
        self.base = base.rstrip("/")
        self.gen_timeout = gen_timeout
        self.poll_interval = poll_interval
        self._token = os.environ.get("ACS_WORKER_TOKEN", "")
        self._headers = {"X-Jarvis-Token": self._token} if self._token else {}
        self.outputs_dir = Path(outputs_dir or os.environ.get("ACS_OUTPUTS_DIR", "outputs")).resolve()
        self.outputs_dir.mkdir(parents=True, exist_ok=True)

    def _get(self, path: str, timeout: int = 30, auth: bool = True) -> dict:
        req = urllib.request.Request(f"{self.base}{path}")
        if auth:
            for k, v in self._headers.items():
                req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return _json.loads(r.read().decode("utf-8", "replace"))

    def _post_json(self, path: str, data: dict, timeout: int = 30) -> dict:
        body = _json.dumps(data).encode("utf-8")
        req = urllib.request.Request(f"{self.base}{path}", data=body, method="POST")
        req.add_header("Content-Type", "application/json")
        for k, v in self._headers.items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return _json.loads(r.read().decode("utf-8", "replace"))

    def _download(self, rel_path: str) -> str:
        """Baixa /outputs/{rel_path} do Worker remoto para OUTPUTS_DIR local.
        rel_path é relativo ao OUTPUT_DIR do Worker (output_relpath) — nunca
        um path absoluto do Pod, que não existe nesta máquina."""
        dest = self.outputs_dir / Path(rel_path).name
        quoted = "/".join(urllib.parse.quote(seg) for seg in rel_path.split("/"))
        req = urllib.request.Request(f"{self.base}/outputs/{quoted}")
        for k, v in self._headers.items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=900) as r, open(dest, "wb") as f:
            while True:
                chunk = r.read(1 << 20)
                if not chunk:
                    break
                f.write(chunk)
        return str(dest)

    _AUDIO_EXTS = {".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a", ".opus", ".wma"}

    def upload(self, local_path: str) -> str:
        """Sobe uma referência local (imagem/vídeo/áudio) para o Worker remoto
        e devolve o path REMOTO (dentro de /workspace/refs no Pod). O Worker
        está num Pod real — settings com um path local do Windows (C:/...)
        dão FileNotFoundError lá, porque esse caminho não existe no Pod."""
        p = Path(local_path)
        endpoint = "/upload-audio" if p.suffix.lower() in self._AUDIO_EXTS else "/upload-ref"
        mime = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
        with open(p, "rb") as f:
            r = httpx.post(f"{self.base}{endpoint}", headers=self._headers,
                            files={"file": (p.name, f, mime)}, timeout=120.0)
        r.raise_for_status()
        return r.json()["path"]

    def health(self) -> dict:
        return self._get("/health", auth=False)

    def list_models(self) -> list[str]:
        return self._get("/models", timeout=60)["models"]

    def default_settings(self, model_type: str) -> dict:
        return self._get(f"/default_settings/{model_type}")

    def progress(self) -> dict:
        return self._get("/progress", timeout=10)

    def generate(self, model_type: str, settings: dict) -> dict:
        """Substitui change_model+save_inputs+process_tasks+polling.
        Submete ao Worker remoto, espera terminar, baixa o arquivo real
        para OUTPUTS_DIR local. Retorna {"ok": bool, "path": str, "media_type": ...,
        "error": ...} — o mesmo contrato de sempre, só que path já é local."""
        try:
            submitted = self._post_json(
                "/run_task", {"model_type": model_type, "settings": settings},
                timeout=30,
            )
        except (urllib.error.URLError, urllib.error.HTTPError) as e:
            return {"ok": False, "error": f"Falha ao submeter ao Worker: {e}"}
        job_id = submitted.get("job_id")

        deadline = time.time() + self.gen_timeout
        while time.time() < deadline:
            time.sleep(self.poll_interval)
            try:
                prog = self.progress()
            except Exception:
                continue
            if prog.get("job_id") != job_id:
                continue
            status = prog.get("status")
            if status == "completed":
                rel = prog.get("output_relpath")
                if not rel:
                    return {"ok": False, "error": f"Worker devolveu output fora do OUTPUT_DIR: {prog.get('output')!r}"}
                try:
                    local_path = self._download(rel)
                except Exception as e:
                    return {"ok": False, "error": f"Falha ao baixar output do Worker: {e}"}
                return {"ok": True, "path": local_path, "media_type": None, "fps": None,
                        "generated_files": [local_path]}
            if status in ("failed", "cancelled"):
                return {"ok": False, "error": prog.get("error") or f"Worker reportou status '{status}'"}
            # "queued"/"running" — continua esperando
        return {"ok": False, "error": "timeout a aguardar o Worker"}
