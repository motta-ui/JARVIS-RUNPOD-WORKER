"""
CloudProvider implementations. RunPodProvider is real (REST API v1,
https://rest.runpod.io/v1) — TensorDock and Vagon remain stubs, no
public API for them was researched/verified for this entry.

RunPod field names below (create_instance's payload, health()'s
response passthrough) are sourced from RunPod's own REST API reference
(docs.runpod.io/api-reference/pods/*, rest.runpod.io/v1/openapi.json) —
never invented. This environment's network egress policy blocks
runpod.io outright (confirmed via the agent proxy's relay-failure log:
403 policy denial on CONNECT to rest.runpod.io:443 and api.runpod.io:443),
so this module could not be exercised against the live API from inside
this session — it was validated from a separate trusted-network Claude
Code Remote session instead (read-only: key validation / listing pods).
"""
from typing import Any

from .base import CloudProvider
from ...config import get_env

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

RUNPOD_REST_BASE = "https://rest.runpod.io/v1"
REQUEST_TIMEOUT = 30
CREATE_TIMEOUT = 90

# Fields accepted as-is by POST /pods (RunPod REST API v1) — passed through
# from spec when present, never defaulted to a guessed value except where
# noted. Source: docs.runpod.io/api-reference/pods/POST/pods.
_CREATE_PASSTHROUGH_FIELDS = (
    "allowedCudaVersions", "cloudType", "computeType", "containerDiskInGb",
    "containerRegistryAuthId", "countryCodes", "cpuFlavorIds", "cpuFlavorPriority",
    "dataCenterIds", "dataCenterPriority", "dockerEntrypoint", "dockerStartCmd",
    "globalNetworking", "gpuCount", "gpuTypeIds", "gpuTypePriority",
    "interruptible", "locked", "minDiskBandwidthMBps", "minDownloadMbps",
    "minRAMPerGPU", "minUploadMbps", "minVCPUPerGPU", "networkVolumeId",
    "ports", "supportPublicIp", "volumeInGb", "volumeMountPath",
)


class RunPodProvider(CloudProvider):
    id = "runpod"
    name = "RunPod"

    def __init__(self):
        self.api_key = get_env("RUNPOD_API_KEY", "")

    def _headers(self) -> dict[str, str]:
        if not self.api_key:
            raise RuntimeError("RUNPOD_API_KEY não configurada no .env do backend.")
        return {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}

    def _require_requests(self):
        if not HAS_REQUESTS:
            raise RuntimeError("Dependência 'requests' não instalada (ver backend/requirements.txt).")

    def create_instance(self, spec: dict[str, Any]) -> dict[str, Any]:
        """Cria um Pod real via POST /pods. `spec` deve incluir pelo menos
        `imageName` e `gpuTypeIds` (lista) — nunca inventamos esses valores
        por omissão, porque escolher a imagem/GPU errada custa dinheiro
        real ao utilizador. `name`/`containerDiskInGb`/`ports`/`env` têm
        defaults razoáveis para o caso de uso do JARVIS Worker."""
        self._require_requests()
        if not spec.get("imageName"):
            raise ValueError("spec.imageName é obrigatório (ex.: 'motta010203/jarvis-worker:v6').")
        if not spec.get("gpuTypeIds"):
            raise ValueError("spec.gpuTypeIds é obrigatório (lista de IDs de GPU aceitáveis).")

        payload: dict[str, Any] = {
            "name": spec.get("name", "jarvis-worker"),
            "imageName": spec["imageName"],
            "gpuTypeIds": spec["gpuTypeIds"],
            "gpuCount": spec.get("gpuCount", 1),
            "cloudType": spec.get("cloudType", "SECURE"),
            "containerDiskInGb": spec.get("containerDiskInGb", 40),
            "ports": spec.get("ports", ["7872/http", "22/tcp"]),
            "env": spec.get("env", {}),
        }
        for key in _CREATE_PASSTHROUGH_FIELDS:
            if key in spec and key not in payload:
                payload[key] = spec[key]

        r = requests.post(f"{RUNPOD_REST_BASE}/pods", headers=self._headers(), json=payload, timeout=CREATE_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        return {"instance_id": data.get("id"), "raw": data}

    def deploy(self, instance_id: str, manifest: dict[str, Any]) -> dict[str, Any]:
        """RunPod não expõe um endpoint REST para 'empurrar' um manifest
        para um Pod já em execução — o software do Pod é definido no
        momento da criação (imageName + dockerStartCmd/env em
        create_instance). Para o JARVIS Worker, 'deploy' já está coberto
        por create_instance(spec) usando a imagem
        'motta010203/jarvis-worker:v6' (ou superior) como imageName; não
        há um segundo passo real a fazer aqui. Ver JARVIS_BOOTSTRAP/ para
        o caso (diferente) de provisionar manualmente via SSH."""
        raise NotImplementedError(
            "RunPod não tem endpoint de deploy pós-criação — defina imageName/dockerStartCmd "
            "em create_instance(spec) em vez de chamar deploy() depois."
        )

    def health(self, instance_id: str) -> dict[str, Any]:
        """GET /pods/{id} — devolve o objeto Pod tal como a API o dá
        (inclui desiredStatus, runtime, etc.); não reformatamos os campos
        para não fingir certeza sobre nomes que não confirmámos ao vivo."""
        self._require_requests()
        r = requests.get(f"{RUNPOD_REST_BASE}/pods/{instance_id}", headers=self._headers(), timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json()

    def destroy_instance(self, instance_id: str) -> bool:
        self._require_requests()
        r = requests.delete(f"{RUNPOD_REST_BASE}/pods/{instance_id}", headers=self._headers(), timeout=REQUEST_TIMEOUT)
        return r.ok

    def list_instances(self) -> list[dict[str, Any]]:
        """GET /pods — não faz parte do contrato CloudProvider (que é
        genérico entre providers), mas é a chamada mais segura para
        validar uma API key (só leitura, não cria nem destrói nada)."""
        self._require_requests()
        r = requests.get(f"{RUNPOD_REST_BASE}/pods", headers=self._headers(), timeout=REQUEST_TIMEOUT)
        r.raise_for_status()
        return r.json()


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
