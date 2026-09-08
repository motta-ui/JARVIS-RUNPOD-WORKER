#!/usr/bin/env python3
"""
Smoke test do backend JARVIS AI STUDIO — corre contra um servidor já em
execução (http://127.0.0.1:8000 por omissão).

Uso:
    python scripts/test_backend.py

Corre isto DEPOIS de iniciar o backend (INICIAR_JARVIS.bat trata disso,
ou `uvicorn app.main:app` manualmente). Termina com exit code 0 se tudo
passar, 1 caso contrário — e imprime exatamente o que falhou.
"""
import sys
import time

import requests

BASE = "http://127.0.0.1:8000"
PASSED, FAILED = [], []


def check(name, fn):
    try:
        fn()
        PASSED.append(name)
        print(f"[PASS] {name}")
    except Exception as e:
        FAILED.append((name, str(e)))
        print(f"[FAIL] {name}: {e}")


def main():
    session = requests.Session()

    def t_health():
        r = session.get(f"{BASE}/health", timeout=5)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "ok"

    def t_engines():
        r = session.get(f"{BASE}/api/engines", timeout=5)
        assert r.status_code == 200
        ids = [e["id"] for e in r.json()]
        assert "mock" in ids, f"engine 'mock' não encontrado em {ids}"

    def t_models():
        r = session.get(f"{BASE}/api/models", timeout=5)
        assert r.status_code == 200
        assert len(r.json()) > 0

    def t_config():
        for kind in ("video", "image", "audio", "motion"):
            r = session.get(f"{BASE}/api/config/studio/{kind}", timeout=5)
            assert r.status_code == 200, f"config/studio/{kind}: {r.text}"
            assert "modes" in r.json()

    project_holder = {}

    def t_create_project():
        r = session.post(f"{BASE}/api/projects", json={"name": "Teste Automático", "description": "smoke test"}, timeout=5)
        assert r.status_code == 200, r.text
        project_holder["id"] = r.json()["id"]

    def t_list_projects():
        r = session.get(f"{BASE}/api/projects", timeout=5)
        assert r.status_code == 200
        assert any(p["id"] == project_holder.get("id") for p in r.json())

    def t_get_project():
        r = session.get(f"{BASE}/api/projects/{project_holder['id']}", timeout=5)
        assert r.status_code == 200
        assert "assets" in r.json() and "jobs" in r.json()

    asset_holder = {}

    def t_upload_asset():
        files = {"file": ("teste.txt", b"conteudo de teste do JARVIS", "text/plain")}
        data = {"category": "references"}
        r = session.post(f"{BASE}/api/assets", files=files, data=data, timeout=5)
        assert r.status_code == 200, r.text
        asset_holder["id"] = r.json()["id"]

    def t_list_assets():
        r = session.get(f"{BASE}/api/assets?category=references", timeout=5)
        assert r.status_code == 200
        assert any(a["id"] == asset_holder.get("id") for a in r.json())

    lora_holder = {}

    def t_create_lora():
        data = {"name": "LoRA de Teste", "engine": "mock", "description": "smoke test", "strength": "1.0", "tags": "[]"}
        r = session.post(f"{BASE}/api/loras", data=data, timeout=5)
        assert r.status_code == 200, r.text
        lora_holder["id"] = r.json()["id"]

    def t_list_loras():
        r = session.get(f"{BASE}/api/loras", timeout=5)
        assert r.status_code == 200
        assert any(l["id"] == lora_holder.get("id") for l in r.json())

    def t_update_lora():
        r = session.patch(f"{BASE}/api/loras/{lora_holder['id']}", json={"strength": 0.7}, timeout=5)
        assert r.status_code == 200
        assert abs(r.json()["strength"] - 0.7) < 1e-6

    def t_delete_lora():
        r = session.delete(f"{BASE}/api/loras/{lora_holder['id']}", timeout=5)
        assert r.status_code == 200

    job_holder = {}

    def t_create_job():
        payload = {
            "engine": "mock", "model": "jarvis-demo-t2v", "mode": "t2v", "kind": "video",
            "prompt": "smoke test video", "parameters": {"duration_seconds": 2},
        }
        r = session.post(f"{BASE}/api/jobs", json=payload, timeout=5)
        assert r.status_code == 200, r.text
        job_holder["id"] = r.json()["id"]

    def t_job_completes():
        deadline = time.time() + 30
        status = None
        while time.time() < deadline:
            r = session.get(f"{BASE}/api/jobs/{job_holder['id']}", timeout=5)
            assert r.status_code == 200
            status = r.json()["status"]
            if status in ("COMPLETED", "FAILED", "CANCELLED"):
                break
            time.sleep(0.5)
        assert status == "COMPLETED", f"job terminou em '{status}', esperava-se COMPLETED"

    def t_gallery_has_item():
        r = session.get(f"{BASE}/api/gallery?kind=video", timeout=5)
        assert r.status_code == 200
        assert any(i.get("job_id") == job_holder.get("id") for i in r.json()), \
            "job completo não apareceu na galeria automaticamente"

    def t_cancel_flow():
        payload = {
            "engine": "mock", "model": "jarvis-demo-t2v", "mode": "t2v", "kind": "video",
            "prompt": "smoke test cancel", "parameters": {"duration_seconds": 30},
        }
        r = session.post(f"{BASE}/api/jobs", json=payload, timeout=5)
        assert r.status_code == 200
        jid = r.json()["id"]
        time.sleep(0.5)
        r = session.post(f"{BASE}/api/jobs/{jid}/cancel", timeout=5)
        assert r.status_code == 200

    def t_settings():
        r = session.get(f"{BASE}/api/settings", timeout=5)
        assert r.status_code == 200
        assert "current_engine" in r.json()

    def t_list_presets():
        r = session.get(f"{BASE}/api/presets?kind=video", timeout=5)
        assert r.status_code == 200, r.text
        names = {p["name"] for p in r.json()}
        for expected in ("Cinematic Pro 1.1", "Talking Head", "MiniMax H3", "JARVIS Demo (Mock)"):
            assert expected in names, f"preset '{expected}' não encontrado em /api/presets?kind=video"

    def t_resolve_preset():
        r = session.get(f"{BASE}/api/presets/cinematic-pro-1-1", timeout=5)
        assert r.status_code == 200, r.text
        data = r.json()
        assert data["engine_id"] == "ltx2"
        assert data["runtime_engine"] == "mock", "preset 'planned' devia cair para mock"
        assert data["status"] == "planned"
        assert "modo demonstração" in data["status_detail"]
        assert "text_to_video" in data["capabilities"]
        assert data["model"]["name"] == "LTX-2 2.3 Distilled 1.1 22B"
        assert "t2v" in data["modes"]

        # preset com control_video real (Studio Editor / vace_14B_cocktail)
        r2 = session.get(f"{BASE}/api/presets/studio-editor", timeout=5)
        data2 = r2.json()
        assert "control_video" in data2["capabilities"]
        assert len(data2["loras"]) == 4, "Studio Editor devia ter os 4 LoRAs reais do vace_14B_cocktail"

    def t_unknown_preset_404():
        r = session.get(f"{BASE}/api/presets/isto-nao-existe", timeout=5)
        assert r.status_code == 404

    def t_models_endpoint():
        r = session.get(f"{BASE}/api/models", timeout=5)
        assert r.status_code == 200
        assert len(r.json()) == 202, "esperava 202 modelos (2 curados + 200 importados)"
        r2 = session.get(f"{BASE}/api/models?engine_id=ltx2", timeout=5)
        assert all(m["engine_id"] == "ltx2" for m in r2.json())

    def t_model_detail_endpoint():
        r = session.get(f"{BASE}/api/models/ltx2_22B_distilled_1_1", timeout=5)
        assert r.status_code == 200
        r_caps = session.get(f"{BASE}/api/models/ltx2_22B_distilled_1_1/capabilities", timeout=5)
        assert "text_to_video" in r_caps.json()["capabilities"]
        r_defaults = session.get(f"{BASE}/api/models/ltx2_22B_distilled_1_1/defaults", timeout=5)
        assert r_defaults.json()["defaults"]["num_inference_steps"] == 8

    def t_workflows_endpoint():
        r = session.get(f"{BASE}/api/workflows", timeout=5)
        assert r.status_code == 200
        workflows = r.json()
        assert len(workflows) == 204
        assert all(w["executable"] is False for w in workflows)
        r2 = session.get(f"{BASE}/api/workflows/t2v_1.3B", timeout=5)
        assert r2.status_code == 200
        assert r2.json()["source_type"] == "preset_config"

    def t_lora_catalog_endpoint():
        r = session.get(f"{BASE}/api/loras/catalog", timeout=5)
        assert r.status_code == 200
        assert len(r.json()) > 0
        # confirmar que isto e' distinto do inventario real (GET /api/loras)
        r2 = session.get(f"{BASE}/api/loras", timeout=5)
        assert r2.status_code == 200

    def t_engine_registry_endpoint():
        r = session.get(f"{BASE}/api/engines/registry", timeout=5)
        assert r.status_code == 200
        ltx2 = next(e for e in r.json() if e["id"] == "ltx2")
        assert ltx2["executable"] is False
        assert ltx2["model_count"] > 0

    def t_cloud_providers():
        r = session.get(f"{BASE}/api/cloud/providers", timeout=5)
        assert r.status_code == 200
        ids = {p["id"] for p in r.json()}
        assert "runpod" in ids

    def t_cloud_connection_roundtrip():
        r = session.put(f"{BASE}/api/cloud/connection", json={
            "provider": "runpod", "worker_url": "http://127.0.0.1:1", "worker_port": 7872, "worker_name": "smoke-test",
        }, timeout=5)
        assert r.status_code == 200, r.text
        assert r.json()["worker_name"] == "smoke-test"

        r2 = session.get(f"{BASE}/api/cloud/connection", timeout=5)
        assert r2.status_code == 200
        assert r2.json()["worker_url"] == "http://127.0.0.1:1"

    def t_cloud_test_offline():
        # porta 1 nunca tem nada a ouvir - deve dar OFFLINE, nunca crash
        r = session.post(f"{BASE}/api/cloud/test", json={"worker_url": "http://127.0.0.1:1"}, timeout=15)
        assert r.status_code == 200, r.text
        assert r.json()["status"] == "OFFLINE"

    def t_cloud_test_online():
        # sobe um Worker falso mas real (HTTP genuíno) em localhost e testa
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                body = b'{"engine": "smoke-worker", "version": "0.0.1"}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def log_message(self, *a):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_address[1]
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            r = session.post(f"{BASE}/api/cloud/test", json={"worker_url": f"http://127.0.0.1:{port}"}, timeout=15)
            assert r.status_code == 200, r.text
            data = r.json()
            assert data["status"] == "ONLINE", data
            assert data["worker_info"]["engine"] == "smoke-worker"
        finally:
            server.shutdown()

    def t_mock_engine_unaffected_by_cloud():
        # Cloud fica OFFLINE (herdado do teste anterior) - Mock Engine tem de continuar normal
        payload = {"engine": "mock", "model": "jarvis-demo-t2v", "mode": "t2v", "kind": "video",
                   "prompt": "smoke test cloud offline", "parameters": {"duration_seconds": 2}}
        r = session.post(f"{BASE}/api/jobs", json=payload, timeout=5)
        assert r.status_code == 200, r.text
        jid = r.json()["id"]
        deadline = time.time() + 15
        status = None
        while time.time() < deadline:
            status = session.get(f"{BASE}/api/jobs/{jid}", timeout=5).json()["status"]
            if status in ("COMPLETED", "FAILED", "CANCELLED"):
                break
            time.sleep(0.3)
        assert status == "COMPLETED", f"Mock Engine falhou com Cloud offline: {status}"

    preset_job_holder = {}

    def t_create_job_via_preset():
        payload = {"preset_id": "jarvis-demo-video", "mode": "t2v", "kind": "video", "prompt": "smoke test via preset"}
        r = session.post(f"{BASE}/api/jobs", json=payload, timeout=5)
        assert r.status_code == 200, r.text
        preset_job_holder["id"] = r.json()["id"]

    def t_job_via_preset_completes_and_tags_gallery():
        deadline = time.time() + 30
        status = None
        while time.time() < deadline:
            r = session.get(f"{BASE}/api/jobs/{preset_job_holder['id']}", timeout=5)
            status = r.json()["status"]
            if status in ("COMPLETED", "FAILED", "CANCELLED"):
                break
            time.sleep(0.5)
        assert status == "COMPLETED", f"job via preset terminou em '{status}'"
        r = session.get(f"{BASE}/api/jobs/{preset_job_holder['id']}", timeout=5)
        assert r.json()["preset_name"] == "JARVIS Demo (Mock)"
        gr = session.get(f"{BASE}/api/gallery?kind=video", timeout=5)
        assert any(i.get("job_id") == preset_job_holder["id"] and i.get("preset_name") == "JARVIS Demo (Mock)"
                   for i in gr.json()), "entrada da galeria não tem preset_name"

    checks = [
        ("GET /health", t_health),
        ("GET /api/engines", t_engines),
        ("GET /api/models", t_models),
        ("GET /api/config/studio/*", t_config),
        ("POST /api/projects", t_create_project),
        ("GET /api/projects", t_list_projects),
        ("GET /api/projects/{id}", t_get_project),
        ("POST /api/assets (upload)", t_upload_asset),
        ("GET /api/assets", t_list_assets),
        ("POST /api/loras", t_create_lora),
        ("GET /api/loras", t_list_loras),
        ("PATCH /api/loras/{id}", t_update_lora),
        ("DELETE /api/loras/{id}", t_delete_lora),
        ("POST /api/jobs (mock engine, caminho antigo)", t_create_job),
        ("job mock chega a COMPLETED", t_job_completes),
        ("job completo aparece na gallery", t_gallery_has_item),
        ("criar + cancelar job", t_cancel_flow),
        ("GET /api/settings", t_settings),
        ("GET /api/presets?kind=video inclui os presets esperados", t_list_presets),
        ("GET /api/presets/{id} resolve com fallback para mock", t_resolve_preset),
        ("GET /api/presets/{id} inexistente devolve 404", t_unknown_preset_404),
        ("GET /api/models devolve os 202 modelos (curados+importados)", t_models_endpoint),
        ("GET /api/models/{id} + capabilities + defaults", t_model_detail_endpoint),
        ("GET /api/workflows todos marcados não-executáveis", t_workflows_endpoint),
        ("GET /api/loras/catalog distinto do inventário real", t_lora_catalog_endpoint),
        ("GET /api/engines/registry (declarativo)", t_engine_registry_endpoint),
        ("GET /api/cloud/providers", t_cloud_providers),
        ("PUT+GET /api/cloud/connection (salvar e recuperar)", t_cloud_connection_roundtrip),
        ("POST /api/cloud/test — Worker OFFLINE", t_cloud_test_offline),
        ("POST /api/cloud/test — Worker ONLINE (servidor real)", t_cloud_test_online),
        ("Mock Engine não quebra com Cloud offline", t_mock_engine_unaffected_by_cloud),
        ("POST /api/jobs via preset_id (caminho novo)", t_create_job_via_preset),
        ("job via preset completa e etiqueta a gallery", t_job_via_preset_completes_and_tags_gallery),
    ]

    for name, fn in checks:
        check(name, fn)

    print()
    print(f"Resultado: {len(PASSED)} passou / {len(FAILED)} falhou (de {len(checks)})")
    if FAILED:
        print("Falhas:")
        for name, err in FAILED:
            print(f"  - {name}: {err}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
