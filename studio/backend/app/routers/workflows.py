from fastapi import APIRouter, HTTPException

from ..registry import workflow_registry

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@router.get("")
def list_workflows(engine_id: str | None = None):
    return workflow_registry.list_workflows(engine_id=engine_id)


@router.get("/{workflow_id}")
def get_workflow(workflow_id: str):
    wf = workflow_registry.get_workflow(workflow_id)
    if not wf:
        raise HTTPException(404, f"Workflow '{workflow_id}' não encontrado")
    return wf
