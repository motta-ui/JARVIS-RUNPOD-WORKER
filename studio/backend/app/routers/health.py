from fastapi import APIRouter
from ..config import APP_NAME, APP_VERSION

router = APIRouter(tags=["health"])


@router.get("/health")
def health():
    return {"status": "ok", "app": APP_NAME, "version": APP_VERSION}
