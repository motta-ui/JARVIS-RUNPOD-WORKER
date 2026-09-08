"""
WORKER CONNECTION

Camada independente do frontend que gere a ligação MANUAL a um Worker
remoto já existente (ex.: um Pod RunPod criado à mão na consola deles).

Esta etapa NÃO cria nem destrói nada na cloud — só guarda um endpoint
HTTP editável e sabe testá-lo via GET /health. Trocar de Worker é
colar um URL novo e clicar "Salvar"; nunca é preciso mexer em código
nem recompilar nada.

Genérico por desenho: nenhum domínio ou mecanismo específico do RunPod
está hardcoded aqui. `provider` é só um rótulo informativo — a lógica
de teste de ligação é a mesma para qualquer provider, porque todos
expõem o Worker da mesma forma (HTTP + /health). A criação/destruição
real de Pods (isso sim específico de cada provider) fica para
`engines/cloud/providers.py`, que continua por implementar.
"""
import json
from urllib.parse import urlparse

from .. import database as db

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

DEFAULT_PORT = 7872
CONNECTION_ID = "default"
HEALTH_TIMEOUT_SECONDS = 8

# Lista de providers preparados na arquitetura — só "runpod" tem uso
# real nesta etapa (ligação manual). Os outros existem para o dropdown
# já não precisar de mudar quando forem implementados.
PROVIDERS = [
    {"id": "runpod", "name": "RunPod", "pod_lifecycle_available": False},
    {"id": "tensordock", "name": "TensorDock", "pod_lifecycle_available": False},
    {"id": "vagon", "name": "Vagon", "pod_lifecycle_available": False},
    {"id": "local", "name": "GPU Local (rede)", "pod_lifecycle_available": False},
]
VALID_PROVIDER_IDS = {p["id"] for p in PROVIDERS}


def list_providers() -> list[dict]:
    return list(PROVIDERS)


def _row_to_dict(row, *, include_token: bool = False) -> dict | None:
    if not row:
        return None
    d = db.row_to_dict(row)
    if d.get("worker_info"):
        try:
            d["worker_info"] = json.loads(d["worker_info"])
        except Exception:
            d["worker_info"] = None
    token = d.pop("worker_token", None)
    if include_token:
        d["worker_token"] = token
    else:
        d["worker_token_set"] = bool(token)
    return d


def get_connection() -> dict:
    """Devolve a configuração persistida (sem o token em claro — ver
    get_worker_token() para uso interno) — cria a linha por omissão
    (OFFLINE, sem Worker) na primeira vez que é pedida."""
    with db.db_session() as conn:
        row = conn.execute("SELECT * FROM cloud_connection WHERE id=?", (CONNECTION_ID,)).fetchone()
        if not row:
            ts = db.now_iso()
            conn.execute(
                "INSERT INTO cloud_connection "
                "(id, provider, worker_url, worker_port, worker_name, status, last_health_check, "
                "worker_info, last_error, worker_token, updated_at) "
                "VALUES (?, 'runpod', NULL, ?, NULL, 'OFFLINE', NULL, NULL, NULL, NULL, ?)",
                (CONNECTION_ID, DEFAULT_PORT, ts),
            )
            row = conn.execute("SELECT * FROM cloud_connection WHERE id=?", (CONNECTION_ID,)).fetchone()
    return _row_to_dict(row)


def get_worker_token() -> str | None:
    """Uso interno (engines/cloud_worker) — nunca exposto pela API."""
    with db.db_session() as conn:
        row = conn.execute("SELECT worker_token FROM cloud_connection WHERE id=?", (CONNECTION_ID,)).fetchone()
    return row["worker_token"] if row and row["worker_token"] else None


def update_connection(provider=None, worker_url=None, worker_port=None, worker_name=None, worker_token=None) -> dict:
    """Persiste os campos editáveis. Só o que for passado (não-None) é
    alterado — os restantes mantêm o valor já guardado."""
    current_raw = get_connection()
    provider = provider if provider is not None else current_raw["provider"]
    worker_url = worker_url if worker_url is not None else current_raw["worker_url"]
    worker_port = worker_port if worker_port is not None else current_raw["worker_port"]
    worker_name = worker_name if worker_name is not None else current_raw["worker_name"]
    if worker_token is None:
        worker_token = get_worker_token()

    if provider not in VALID_PROVIDER_IDS:
        raise ValueError(f"provider '{provider}' desconhecido. Válidos: {sorted(VALID_PROVIDER_IDS)}")

    ts = db.now_iso()
    with db.db_session() as conn:
        conn.execute(
            "UPDATE cloud_connection SET provider=?, worker_url=?, worker_port=?, worker_name=?, "
            "worker_token=?, updated_at=? WHERE id=?",
            (provider, worker_url, worker_port, worker_name, worker_token, ts, CONNECTION_ID),
        )
    return get_connection()


def build_worker_base_url(worker_url: str, worker_port) -> str:
    """Constrói o URL base do Worker (sem trailing slash, sem path).

    - Se worker_url já tem esquema (http://.../https://...), é usado
      tal como está — proxies como o do RunPod já embutem a porta no
      próprio domínio (ex.: https://abc123-7872.proxy.runpod.net);
      reescrever isso quebraria o URL. A porta guardada fica só como
      referência/histórico neste caso.
    - Se for só um host/IP sem esquema (ex.: '192.168.1.50' ou
      'localhost', útil para GPU local em rede), assume-se http:// e a
      porta é anexada explicitamente.
    """
    url = (worker_url or "").strip().rstrip("/")
    if not url:
        raise ValueError("worker_url vazio")
    if "://" not in url:
        port_part = f":{worker_port}" if worker_port else ""
        url = f"http://{url}{port_part}"
    return url


def get_worker_base_url() -> str | None:
    """Usado pelo engine Cloud Worker (engines/cloud_worker) para saber
    para onde enviar /run_task, uploads, etc. Devolve None se não houver
    Worker configurado — nunca inventa um endereço."""
    current = get_connection()
    url = current.get("worker_url")
    if not url:
        return None
    return build_worker_base_url(url, current.get("worker_port"))


def _build_health_url(worker_url: str, worker_port) -> str:
    return f"{build_worker_base_url(worker_url, worker_port)}/health"


def test_connection(provider=None, worker_url=None, worker_port=None, worker_token=None) -> dict:
    """Testa a ligação real ao Worker via GET /health.

    Se provider/worker_url/worker_port forem passados, testa ESSES
    valores (podem ainda não estar guardados — é o que permite colar
    um URL novo e testar antes de "Salvar"). Se omitidos, usa a
    configuração já persistida.

    O resultado (status/last_health_check/worker_info/last_error) é
    sempre persistido — são exatamente os campos "status" e "último
    health check" pedidos como parte da configuração. O worker_url/
    provider testados só passam a ser a configuração guardada quando
    update_connection() for chamado explicitamente (ex.: pelo botão
    "Salvar").

    Nunca levanta exceção — devolve sempre um dict com status e, em
    falha, um erro legível."""
    current = get_connection()
    test_url = worker_url if worker_url is not None else current.get("worker_url")
    test_port = worker_port if worker_port is not None else current.get("worker_port")
    test_token = worker_token if worker_token is not None else get_worker_token()

    if not test_url:
        result = {"status": "OFFLINE", "error": "Nenhum Worker URL configurado.", "worker_info": None}
        _persist_result(result)
        return {**get_connection(), **result}

    if not HAS_REQUESTS:
        result = {"status": "ERROR", "error": "Dependência 'requests' não instalada no backend.", "worker_info": None}
        _persist_result(result)
        return {**get_connection(), **result}

    target = None
    try:
        target = _build_health_url(test_url, test_port)
        headers = {"X-Jarvis-Token": test_token} if test_token else {}
        resp = requests.get(target, headers=headers, timeout=HEALTH_TIMEOUT_SECONDS)
        resp.raise_for_status()
        try:
            info = resp.json()
        except ValueError:
            info = {"raw": resp.text[:500]}
        result = {"status": "ONLINE", "error": None, "worker_info": info}
    except ValueError as e:
        result = {"status": "ERROR", "error": str(e), "worker_info": None}
    except requests.exceptions.Timeout:
        result = {"status": "ERROR", "error": f"Sem resposta (timeout) de {target or test_url}.", "worker_info": None}
    except requests.exceptions.ConnectionError:
        result = {"status": "OFFLINE", "error": f"Não foi possível ligar a {target or test_url}.", "worker_info": None}
    except requests.exceptions.HTTPError as e:
        result = {"status": "ERROR", "error": f"Worker respondeu com erro HTTP: {e}", "worker_info": None}
    except Exception as e:  # nunca deixar isto derrubar a app
        result = {"status": "ERROR", "error": f"Erro inesperado: {e}", "worker_info": None}

    _persist_result(result)
    return {**get_connection(), **result}


def _persist_result(result: dict):
    ts = db.now_iso()
    with db.db_session() as conn:
        conn.execute(
            "UPDATE cloud_connection SET status=?, last_health_check=?, worker_info=?, last_error=?, updated_at=? WHERE id=?",
            (
                result["status"], ts,
                json.dumps(result["worker_info"]) if result.get("worker_info") is not None else None,
                result.get("error"), ts, CONNECTION_ID,
            ),
        )


def has_online_worker() -> bool:
    """Usado por outras partes do sistema para saber se existe um Worker
    remoto disponível. NUNCA usado para substituir automaticamente o
    engine de um preset — essa troca continua a exigir configuração
    explícita (fora do âmbito desta etapa)."""
    return get_connection().get("status") == "ONLINE"
