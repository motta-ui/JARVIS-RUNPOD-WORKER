JARVIS RUNPOD WORKER V6

V6 is a thin HTTP bridge over the current WanGP Python API.
It reuses the V5 image, so no dependency reinstall is needed.

Image: motta010203/jarvis-worker:v6
HTTP: 7872
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
