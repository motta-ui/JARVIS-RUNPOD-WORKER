from typing import Any

from fastapi import APIRouter, Body, HTTPException

from ..cloud import worker_connection as wc
from ..engines.cloud.providers import PROVIDERS
from ..schemas import CloudConnectionUpdate, CloudConnectionTest

router = APIRouter(prefix="/api/cloud", tags=["cloud"])


def _provider(provider_id: str):
    cls = PROVIDERS.get(provider_id)
    if not cls:
        raise HTTPException(400, f"Provider '{provider_id}' desconhecido. Válidos: {sorted(PROVIDERS)}")
    return cls()


@router.get("/providers")
def get_providers():
    return wc.list_providers()


@router.get("/connection")
def get_connection():
    return wc.get_connection()


@router.put("/connection")
def put_connection(payload: CloudConnectionUpdate):
    try:
        return wc.update_connection(
            provider=payload.provider,
            worker_url=payload.worker_url,
            worker_port=payload.worker_port,
            worker_name=payload.worker_name,
            worker_token=payload.worker_token,
        )
    except ValueError as e:
        raise HTTPException(400, str(e))


@router.post("/test")
def post_test(payload: CloudConnectionTest | None = None):
    payload = payload or CloudConnectionTest()
    return wc.test_connection(
        provider=payload.provider,
        worker_url=payload.worker_url,
        worker_port=payload.worker_port,
        worker_token=payload.worker_token,
    )


# --- Pod lifecycle (real, provider-backed — hoje só "runpod" está implementado) ---
# Deliberadamente sem valores por omissão perigosos: create_instance exige
# imageName+gpuTypeIds explícitos no corpo do pedido, nunca escolhidos por
# nós (criar um Pod custa dinheiro real ao utilizador). Nenhum destes
# endpoints é chamado automaticamente pelo resto do Studio.

@router.get("/{provider_id}/pods")
def list_pods(provider_id: str):
    try:
        return _provider(provider_id).list_instances()
    except AttributeError:
        raise HTTPException(400, f"Provider '{provider_id}' não suporta listar pods.")
    except Exception as e:
        raise HTTPException(502, f"{type(e).__name__}: {e}")


@router.get("/{provider_id}/pods/{instance_id}")
def get_pod(provider_id: str, instance_id: str):
    try:
        return _provider(provider_id).health(instance_id)
    except Exception as e:
        raise HTTPException(502, f"{type(e).__name__}: {e}")


@router.post("/{provider_id}/pods")
def create_pod(provider_id: str, spec: dict[str, Any] = Body(...)):
    try:
        return _provider(provider_id).create_instance(spec)
    except (ValueError, NotImplementedError) as e:
        raise HTTPException(400, str(e))
    except Exception as e:
        raise HTTPException(502, f"{type(e).__name__}: {e}")


@router.delete("/{provider_id}/pods/{instance_id}")
def destroy_pod(provider_id: str, instance_id: str):
    try:
        ok = _provider(provider_id).destroy_instance(instance_id)
    except Exception as e:
        raise HTTPException(502, f"{type(e).__name__}: {e}")
    if not ok:
        raise HTTPException(502, "Provider recusou o pedido de destruição.")
    return {"destroyed": instance_id}
