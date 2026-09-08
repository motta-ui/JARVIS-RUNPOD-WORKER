#!/usr/bin/env python3
"""
Testes da camada WorkerConnection / Cloud Connection — corre
diretamente em Python, sem precisar do servidor FastAPI no ar. Usa
servidores HTTP reais em localhost (http.server da stdlib) para os
testes de ONLINE/OFFLINE/ERROR — não são simulações, são pedidos HTTP
verdadeiros a um servidor a correr de facto, só que na tua própria
máquina em vez de na cloud.

Uso:
    python scripts/test_cloud.py
"""
import importlib
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app import database as db  # noqa: E402
from app.cloud import worker_connection as wc  # noqa: E402

PASSED, FAILED = [], []


def check(name, fn):
    try:
        fn()
        PASSED.append(name)
        print(f"[PASS] {name}")
    except Exception as e:
        FAILED.append((name, str(e)))
        print(f"[FAIL] {name}: {e}")


class _HealthHandler(BaseHTTPRequestHandler):
    """Worker falso mas real (HTTP genuíno em localhost) para os testes."""
    response_body = {"engine": "ltx2-worker", "version": "0.1.0", "gpu": "RTX 4090"}
    response_status = 200

    def do_GET(self):
        if self.path == "/health":
            if self.response_status >= 400:
                self.send_response(self.response_status)
                self.end_headers()
                return
            body = json.dumps(self.response_body).encode()
            self.send_response(self.response_status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, *args):
        pass


def start_fake_worker(status=200, body=None):
    handler = type("Handler", (_HealthHandler,), {
        "response_status": status,
        "response_body": body or _HealthHandler.response_body,
    })
    server = HTTPServer(("127.0.0.1", 0), handler)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, port


def main():
    db.init_db()

    # --- 1. Salvar configuração --------------------------------------------
    def t1_save_configuration():
        result = wc.update_connection(
            provider="runpod", worker_url="http://127.0.0.1:9001", worker_port=9001, worker_name="Pod Teste",
        )
        assert result["provider"] == "runpod"
        assert result["worker_url"] == "http://127.0.0.1:9001"
        assert result["worker_name"] == "Pod Teste"
        fetched = wc.get_connection()
        assert fetched["worker_url"] == "http://127.0.0.1:9001"

    # --- 2. Alterar Worker URL (mantendo os restantes campos) ---------------
    def t2_change_worker_url():
        before = wc.get_connection()
        after = wc.update_connection(worker_url="http://127.0.0.1:9002")
        assert after["worker_url"] == "http://127.0.0.1:9002"
        assert after["worker_port"] == before["worker_port"], "porta não devia ter mudado"
        assert after["worker_name"] == before["worker_name"], "nome não devia ter mudado"

    # --- 3. Reiniciar backend e recuperar configuração -----------------------
    def t3_survives_restart():
        wc.update_connection(worker_url="http://127.0.0.1:9003", worker_name="Sobrevive Restart")
        # simula um restart real do processo: limpar qualquer estado e
        # reimportar os módulos - a config tem de vir só da BD, não de
        # memória.
        importlib.reload(db)
        importlib.reload(wc)
        recovered = wc.get_connection()
        assert recovered["worker_url"] == "http://127.0.0.1:9003"
        assert recovered["worker_name"] == "Sobrevive Restart"

    # --- 4. Worker ONLINE (servidor HTTP real) -------------------------------
    def t4_worker_online():
        server, port = start_fake_worker(200, {"engine": "wan-worker", "version": "1.2.3", "gpu": "A100"})
        try:
            r = wc.test_connection(worker_url=f"http://127.0.0.1:{port}")
            assert r["status"] == "ONLINE", r
            assert r["worker_info"]["engine"] == "wan-worker"
            assert r["worker_info"]["gpu"] == "A100"
            persisted = wc.get_connection()
            assert persisted["status"] == "ONLINE"
            assert persisted["last_health_check"] is not None
            assert persisted["worker_info"]["engine"] == "wan-worker"
        finally:
            server.shutdown()

    # --- 5. Worker OFFLINE (nada a ouvir na porta) ---------------------------
    def t5_worker_offline():
        r = wc.test_connection(worker_url="http://127.0.0.1:1")
        assert r["status"] == "OFFLINE", r
        assert r["error"]
        persisted = wc.get_connection()
        assert persisted["status"] == "OFFLINE"

    # --- 6. Endpoint inválido (URL vazio / erro HTTP do worker) --------------
    def t6_invalid_endpoint_empty_url():
        r = wc.test_connection(worker_url="")
        assert r["status"] == "OFFLINE"
        assert "Nenhum Worker URL" in r["error"]

    def t6b_invalid_endpoint_http_error():
        server, port = start_fake_worker(500)
        try:
            r = wc.test_connection(worker_url=f"http://127.0.0.1:{port}")
            assert r["status"] == "ERROR", r
            assert "500" in r["error"] or "erro HTTP" in r["error"].lower()
        finally:
            server.shutdown()

    # --- 7. Trocar de endpoint (ex.: destruir Pod, criar outro) --------------
    def t7_switch_endpoint():
        server_a, port_a = start_fake_worker(200, {"engine": "worker-a"})
        server_b, port_b = start_fake_worker(200, {"engine": "worker-b"})
        try:
            r_a = wc.test_connection(worker_url=f"http://127.0.0.1:{port_a}")
            assert r_a["worker_info"]["engine"] == "worker-a"
            wc.update_connection(worker_url=f"http://127.0.0.1:{port_a}")

            # "destruiu o pod A, criou um novo B" - troca só de endereço
            r_b = wc.test_connection(worker_url=f"http://127.0.0.1:{port_b}")
            assert r_b["worker_info"]["engine"] == "worker-b"
            wc.update_connection(worker_url=f"http://127.0.0.1:{port_b}")

            final = wc.get_connection()
            assert final["worker_url"] == f"http://127.0.0.1:{port_b}"
            assert final["worker_info"]["engine"] == "worker-b"
        finally:
            server_a.shutdown()
            server_b.shutdown()

    # --- 8. Mock Engine não quebra com Cloud offline --------------------------
    def t8_mock_engine_unaffected_by_offline_cloud():
        wc.update_connection(worker_url="http://127.0.0.1:1")  # garantidamente inatingível
        wc.test_connection()  # confirma OFFLINE
        assert wc.get_connection()["status"] == "OFFLINE"

        # o Mock Engine tem de continuar a funcionar perfeitamente
        import uuid
        from app.engines.mock.adapter import MockEngine

        eng = MockEngine()
        jid = str(uuid.uuid4())
        ts = db.now_iso()
        with db.db_session() as conn:
            conn.execute(
                "INSERT INTO jobs (id, engine, model, mode, kind, prompt, parameters, status, progress, created_at, updated_at) "
                "VALUES (?, 'mock', 'jarvis-demo-t2v', 't2v', 'video', 'teste com cloud offline', '{}', 'QUEUED', 0, ?, ?)",
                (jid, ts, ts),
            )
        eng.generate(jid, {"duration_seconds": 2})
        status = None
        for _ in range(30):
            time.sleep(0.3)
            status = eng.get_status(jid)
            if status["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
                break
        assert status["status"] == "COMPLETED", f"Mock Engine falhou com Cloud offline: {status}"

    # --- extra: has_online_worker() nunca troca engine sozinho ---------------
    def t9_has_online_worker_is_read_only():
        server, port = start_fake_worker(200)
        try:
            wc.update_connection(worker_url=f"http://127.0.0.1:{port}")
            wc.test_connection()
            assert wc.has_online_worker() is True
            # confirmar que isto e' so' informativo - nao existe nenhuma
            # ligacao no codigo entre has_online_worker() e a resolucao
            # de engine dos presets (preset_registry.resolve_runtime_engine
            # continua a nao chamar isto)
            import inspect
            from app.registry import preset_registry
            src = inspect.getsource(preset_registry.resolve_runtime_engine)
            assert "has_online_worker" not in src and "worker_connection" not in src, \
                "resolve_runtime_engine não deve depender do Cloud nesta etapa"
        finally:
            server.shutdown()

    def t10_providers_list_available():
        providers = wc.list_providers()
        ids = {p["id"] for p in providers}
        assert "runpod" in ids
        assert {"tensordock", "vagon", "local"}.issubset(ids), "arquitetura devia estar preparada para os outros providers"

    checks = [
        ("1. Salvar configuração", t1_save_configuration),
        ("2. Alterar Worker URL (mantém os restantes campos)", t2_change_worker_url),
        ("3. Reiniciar backend e recuperar configuração", t3_survives_restart),
        ("4. Worker ONLINE (servidor HTTP real)", t4_worker_online),
        ("5. Worker OFFLINE (porta sem nada a ouvir)", t5_worker_offline),
        ("6. Endpoint inválido — URL vazio", t6_invalid_endpoint_empty_url),
        ("6b. Endpoint inválido — erro HTTP do Worker", t6b_invalid_endpoint_http_error),
        ("7. Trocar de endpoint (destruir Pod, criar outro)", t7_switch_endpoint),
        ("8. Mock Engine não quebra com Cloud offline", t8_mock_engine_unaffected_by_offline_cloud),
        ("9. has_online_worker() é só informativo, não troca engine sozinho", t9_has_online_worker_is_read_only),
        ("10. Lista de providers preparada (runpod/tensordock/vagon/local)", t10_providers_list_available),
    ]

    for name, fn in checks:
        check(name, fn)

    print(f"\nResultado: {len(PASSED)} passou / {len(FAILED)} falhou (de {len(checks)})")
    if FAILED:
        for name, err in FAILED:
            print(f"  - {name}: {err}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
