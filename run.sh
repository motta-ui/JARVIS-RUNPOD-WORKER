#!/usr/bin/env bash
set -e
/start.sh &
sleep 3
export PYTHONPATH="/app:/workspace/JARVIS:/workspace/JARVIS/jarvis_worker:/workspace/JARVIS/wan2gp_upstream:${PYTHONPATH:-}"
exec uvicorn jarvis_worker.app:app --host 0.0.0.0 --port 7872
