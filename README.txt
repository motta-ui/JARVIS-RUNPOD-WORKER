JARVIS RUNPOD WORKER V6

V6 is a thin HTTP bridge over the current WanGP Python API.
It reuses the V5 image, so no dependency reinstall is needed.

Image: motta010203/jarvis-worker:v6
HTTP: 7872
SSH: 22
Persistent volume: /workspace

Endpoints:
GET  /health
GET  /models
GET  /default_settings/{model_type}
GET  /schema/{model_type}
GET  /availability/{model_type}
GET  /progress
POST /run_task

The generation path uses WanGPSession.get_default_settings() and submit_task().
No ACS license bypass or proprietary ACS code is included.
