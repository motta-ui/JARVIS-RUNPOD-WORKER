JARVIS RUNPOD WORKER V6

V6 is a thin HTTP bridge over the current WanGP Python API.

Real deployment (verified against the live Pod, RTX 4090, 2026-09-08):
this worker is NOT a separate Docker image. The Pod already runs a
prebuilt Wan2GP image (deepbeepmeep/Wan2GP, supervisord-managed, Gradio
UI on :7860 proxied at :7862 with basic auth). jarvis_worker/ is instead
synced straight into that same Pod's persistent volume and run as a
plain process inside the Pod's own venv, which already has fastapi/
uvicorn/python-multipart preinstalled — no extra image build/push, no
new container.

  WAN_DIR (real):     /workspace/Wan2GP   (NOT wan2gp_upstream)
  Worker source:       /workspace/jarvis_worker (synced from this repo's
                        jarvis_worker/, persists across Pod restarts)
  Python:              /opt/wan2gp-venv/bin/python (already has the deps)
  Worker HTTP:          127.0.0.1:7271 (loopback only)
  Public HTTP:           :7270 -> reuses the Pod image's existing nginx
                        proxy block labelled "Dockerless CLI FastAPI
                        Server" (see /etc/nginx/nginx.conf on the Pod) --
                        no nginx/supervisor config was touched to add
                        this; the proxy slot already existed, unused.
  Start command:        JARVIS_WAN_DIR=/workspace/Wan2GP
                        JARVIS_OUTPUT_DIR=/workspace/outputs
                        JARVIS_REFS_DIR=/workspace/refs
                        JARVIS_WORKER_TOKEN=<generated, kept out of git>
                        nohup /opt/wan2gp-venv/bin/python -m uvicorn
                        app:app --host 127.0.0.1 --port 7271
                        > /workspace/jarvis_worker.log 2>&1 &

Confirmed end-to-end on the real Pod: GET /health, GET /models (real
~200-model WanGP catalog), and a real POST /run_task (t2v_1.3B, 8 steps,
480x272, 17 frames) that downloaded real weights from Hugging Face and
produced a real .mp4 in /workspace/outputs. No mocks.

SSH: 22
Persistent volume: /workspace

Model coverage: this worker is deliberately model-agnostic. Every request
carries a `model_type` + `settings` payload that is forwarded as-is to
WanGPSession, so it covers every family in the deployed WAN_DIR's model
catalog without any per-mode code in this repo — video (t2v/i2v/flf/vace/
continue), image (flux/z-image/ideogram/krea/...), audio (ace_step/
chatterbox/heartmula/index_tts/kugelaudio/qwen3_tts/stable_audio), and
motion (talking-head/infinite-talk/character-animate) all go through the
same /run_task contract. Mode-to-route translation (e.g. the JARVIS Studio
"Texto -> Video" button vs "Talking Image") is a JARVIS Studio (backend)
concern, not this worker's.

Endpoints:
GET    /health
GET    /models
GET    /default_settings/{model_type}
GET    /schema/{model_type}
GET    /availability/{model_type}
POST   /run_task
GET    /progress                    (current single job, regardless of id)
GET    /status/{job_id}             (404 if job_id isn't the current job)
POST   /cancel/{job_id}             (best-effort; engine_cancelled in the
                                      response reports whether the in-flight
                                      WanGP task actually supported abort)
POST   /upload-ref                  (image/video reference: start/end frame,
                                      control video, character photo, ...)
POST   /upload-audio, /upload/audio (audio reference: TTS voice prompt,
                                      talking-head speaker track, ...)
GET    /outputs                     (?type=video|image|audio, ?limit=N)
GET    /outputs/{filename}          (?download=1 for Content-Disposition)
DELETE /outputs/{filename}
GET    /file/{filename}             (alias: serves from outputs or refs)
GET    /video/{filename}            (alias for /file/{filename})

Uploaded references are written under JARVIS_REFS_DIR (default
/workspace/refs) and generated results under JARVIS_OUTPUT_DIR (default
/workspace/outputs); pass the returned `path` back inside a /run_task
`settings` payload (e.g. as image_refs / video_source / audio_source) to
use an uploaded file in a generation.

This worker runs one job at a time (single global job state, 409 on
/run_task while busy) — that matches WanGP's own single-GPU-process model
and is the same shape acs_wan_worker.py used.

The generation path uses WanGPSession.get_default_settings() and submit_task().
No ACS license bypass or proprietary ACS code is included.
