"""
CloudProvider: abstração para o futuro Cloud Worker.

JARVIS STUDIO -> JARVIS API -> CLOUD WORKER -> GPU -> OUTPUT

Nenhum provedor está implementado nem ligado ainda — isto é só a
arquitetura, para que RunPod/TensorDock/Vagon/outros possam ser
adicionados no futuro sem alterar o resto do sistema. Nada aqui faz
cobrança ou cria GPU real.
"""
from abc import ABC, abstractmethod
from typing import Any


class CloudProvider(ABC):
    id: str = "base"
    name: str = "Base Cloud Provider"

    @abstractmethod
    def create_instance(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Cria uma instância GPU descartável. NÃO IMPLEMENTADO ainda."""
        raise NotImplementedError

    @abstractmethod
    def deploy(self, instance_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
        """Instala dependências/engine/modelos na instância, a partir de um
        manifest (ver JARVIS_BOOTSTRAP/). NÃO IMPLEMENTADO ainda."""
        raise NotImplementedError

    @abstractmethod
    def health(self, instance_id: str) -> dict[str, Any]:
        """Estado da instância."""
        raise NotImplementedError

    @abstractmethod
    def destroy_instance(self, instance_id: str) -> bool:
        """Destrói a instância (para não continuar a faturar)."""
        raise NotImplementedError
