from fastapi import APIRouter, HTTPException

from ..cloud import worker_connection as wc
from ..schemas import CloudConnectionUpdate, CloudConnectionTest

router = APIRouter(prefix="/api/cloud", tags=["cloud"])


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
