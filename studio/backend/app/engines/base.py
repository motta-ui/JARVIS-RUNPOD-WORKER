"""
BaseEngine: contrato que todo adapter de engine deve implementar.

Nenhuma lógica específica de um engine (MiniMax, LTX, Wan, etc.) deve
viver fora do respetivo adapter. O frontend e o resto do backend só
falam com esta interface.
"""
from abc import ABC, abstractmethod
from typing import Any


class BaseEngine(ABC):
    """Contrato comum a todos os adapters de engine."""

    id: str = "base"
    name: str = "Base Engine"

    @abstractmethod
    def get_capabilities(self) -> dict[str, Any]:
        """Devolve as capacidades reais suportadas por este engine.
        Nunca deve declarar suporte que a API/engine não tem de facto."""
        raise NotImplementedError

    @abstractmethod
    def validate_request(self, job_params: dict[str, Any]) -> tuple[bool, str | None]:
        """Valida os parâmetros do job contra as capacidades do engine.
        Devolve (valido, mensagem_erro)."""
        raise NotImplementedError

    @abstractmethod
    def upload(self, file_path: str) -> str:
        """Envia um asset (imagem/vídeo/áudio) para o engine, devolve uma referência."""
        raise NotImplementedError

    @abstractmethod
    def generate(self, job_id: str, job_params: dict[str, Any]) -> None:
        """Inicia a geração de forma assíncrona. Deve atualizar o job na BD
        conforme o progresso evolui."""
        raise NotImplementedError

    @abstractmethod
    def get_status(self, job_id: str) -> dict[str, Any]:
        """Devolve o estado atual do job."""
        raise NotImplementedError

    @abstractmethod
    def cancel(self, job_id: str) -> bool:
        """Cancela um job em curso."""
        raise NotImplementedError

    @abstractmethod
    def get_output(self, job_id: str) -> str | None:
        """Devolve o path do output final, se existir."""
        raise NotImplementedError

    @abstractmethod
    def health(self) -> dict[str, Any]:
        """Estado de saúde/conectividade do engine."""
        raise NotImplementedError
