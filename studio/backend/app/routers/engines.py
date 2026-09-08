from fastapi import APIRouter
from ..engines.registry import list_engines, persist_engine_snapshot
from ..registry import engine_registry

router = APIRouter(prefix="/api/engines", tags=["engines"])


@router.get("")
def get_engines():
    engines = list_engines()
    try:
        persist_engine_snapshot()
    except Exception:
        pass
    return engines


@router.get("/registry")
def get_engine_registry():
    """ENGINE REGISTRY declarativo — catálogo de famílias de engine (ltx2,
    wan, hunyuan, ...), a maioria sem adapter executável ainda. Diferente
    de GET /api/engines acima, que só lista os adapters REALMENTE
    executáveis (mock, minimax)."""
    return engine_registry.list_engines()
