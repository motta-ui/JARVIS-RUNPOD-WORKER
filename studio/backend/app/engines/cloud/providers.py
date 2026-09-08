"""
Stubs de providers de GPU cloud. Nenhum está implementado — só a
arquitetura, para não criar dependência de um único fornecedor.
Implementar create_instance/deploy/health/destroy_instance quando o
Cloud Worker avançar para lá do estado de arquitetura.
"""
from typing import Any

from .base import CloudProvider


class RunPodProvider(CloudProvider):
    id = "runpod"
    name = "RunPod"

    def create_instance(self, spec: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("RunPodProvider ainda não está implementado.")

    def deploy(self, instance_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def health(self, instance_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def destroy_instance(self, instance_id: str) -> bool:
        raise NotImplementedError


class TensorDockProvider(CloudProvider):
    id = "tensordock"
    name = "TensorDock"

    def create_instance(self, spec: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("TensorDockProvider ainda não está implementado.")

    def deploy(self, instance_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def health(self, instance_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def destroy_instance(self, instance_id: str) -> bool:
        raise NotImplementedError


class VagonProvider(CloudProvider):
    id = "vagon"
    name = "Vagon"

    def create_instance(self, spec: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError("VagonProvider ainda não está implementado.")

    def deploy(self, instance_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def health(self, instance_id: str) -> dict[str, Any]:
        raise NotImplementedError

    def destroy_instance(self, instance_id: str) -> bool:
        raise NotImplementedError


PROVIDERS = {
    "runpod": RunPodProvider,
    "tensordock": TensorDockProvider,
    "vagon": VagonProvider,
}
