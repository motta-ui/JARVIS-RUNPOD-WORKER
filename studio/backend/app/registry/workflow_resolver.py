"""
WORKFLOW RESOLVER

Cada opção/mode do Studio é um WORKFLOW LÓGICO próprio — dois workflows
podem partilhar o mesmo endpoint/engine sem serem o mesmo workflow (ex.:
Image Motion e Talking Image resolvem os dois para o "modo i2v" do
Wan2GP, mas têm inputs obrigatórios e payload completamente diferentes).

Fonte de verdade: JARVIS_WORKFLOW_PARITY_PACK/workflows/*.json.
Nada aqui foi inventado — cada `required_inputs`/`optional_inputs`
reflecte literalmente o ficheiro do pacote com o mesmo `workflow_id`.

IMPORTANTE (regra do pacote, preservada tal e qual):
  Image Motion → referência → parâmetros de movimento →
    se End Frame ativo: FLF, caso contrário: I2V →
    prompt enhancement quando aplicável → demais controlos compatíveis.
  Talking Image, Infinite Talk e Character Animate têm workflow próprio
  — nunca reduzidos a "I2V genérico".
"""
from typing import Any

# workflow_id -> definição. required_inputs/optional_inputs usam as
# chaves de reference_zones já existentes em studio_video.json/
# studio_motion.json (start_image, end_frame, reference_image,
# control_video, reference_video, audio, ...).
WORKFLOWS: dict[str, dict[str, Any]] = {
    "t2v": {
        "name": "Texto -> Vídeo",
        "required_inputs": ["prompt"],
        "optional_inputs": ["control_video", "frame_inject_refs"],
    },
    "i2v": {
        "name": "Imagem -> Vídeo",
        "required_inputs": ["start_image"],
        "optional_inputs": ["prompt", "control_video", "frame_inject_refs", "audio"],
    },
    # chave "end_frame" para bater com o mode já usado por
    # data/studio_video.json e preset_registry.CAPABILITY_TO_MODE — o
    # pacote de referência chama este workflow "flf" (endpoint /generate/flf);
    # mantemos "flf" como alias para o routes_to do Image Motion.
    "end_frame": {
        "name": "FLF / End Frame",
        "required_inputs": ["start_image", "end_frame"],
        "optional_inputs": ["prompt", "control_video"],
    },
    "continue": {
        "name": "Continue",
        "required_inputs": ["reference_video"],
        "optional_inputs": ["end_frame", "prompt"],
        "preserve": ["source_strength", "seed", "guidance_scale", "loras", "advanced"],
    },
    "t2i": {
        "name": "Texto -> Imagem",
        "required_inputs": ["prompt"],
        "optional_inputs": [],
    },
    "animate_character": {
        "name": "Animar Personagem",
        "required_inputs": ["reference_image", "control_video"],
        "optional_inputs": ["prompt"],
    },
    # --- Motion: cada um com workflow próprio, nunca colapsado em "i2v" ---
    "image_motion": {
        "name": "Image Motion",
        "required_inputs": ["start_image"],
        "optional_inputs": ["end_frame", "prompt"],
        "routes_to": {"has_end_frame": "flf", "default": "i2v"},
        "prompt_enhancer_when": "prompt_present",
    },
    "talking_image": {
        "name": "Talking Image",
        "required_inputs": ["start_image", "audio"],
        "optional_inputs": ["audio2"],
        "payload_fields": ["audio_prompt_type", "audio_path", "audio_path2", "speakers_locations",
                            "audio_guidance_scale", "audio_scale"],
    },
    "infinite_talk": {
        "name": "Infinite Talk",
        "required_inputs": ["start_image", "audio"],
        "optional_inputs": ["scene_2", "scene_3", "scene_4"],
        "required_pipeline_flag": {"video_prompt_type_letters": "KI"},
        "payload_fields": ["audio_prompt_type", "audio_path", "audio_guidance_scale", "audio_scale", "ref_inject_paths"],
    },
    "character_animate": {
        "name": "Character Animate",
        "required_inputs": ["reference_image", "control_video"],
        "optional_inputs": [],
        "payload_fields": ["ctrl_video_prompt_type", "ref_image_path", "ctrl_video_path"],
        "model_specific_defaults": {"scail2_14B": {"ctrl_video_prompt_type": "V1"}},
    },
}
WORKFLOWS["flf"] = WORKFLOWS["end_frame"]  # alias: nome do pacote de referência para o mesmo workflow


def get_workflow_def(workflow_id: str) -> dict | None:
    return WORKFLOWS.get(workflow_id)


def resolve_workflow(mode: str, job_params: dict[str, Any]) -> tuple[str, list[str]]:
    """(mode, job_params) -> (workflow_id_resolvido, avisos).

    Para "image_motion", decide entre 'flf' e 'i2v' com base na presença
    real de end_frame — é a ÚNICA lógica de troca de rota que o pacote
    documenta; todos os outros modes resolvem para o seu próprio
    workflow_id 1:1."""
    warnings: list[str] = []
    workflow_def = WORKFLOWS.get(mode)
    if not workflow_def:
        return mode, [f"Modo '{mode}' sem definição de workflow — a passar sem resolução dedicada."]

    routes_to = workflow_def.get("routes_to")
    if routes_to:
        has_end_frame = bool(job_params.get("end_frame"))
        resolved = routes_to["has_end_frame"] if has_end_frame else routes_to["default"]
        return resolved, warnings

    return mode, warnings


def check_required_inputs(workflow_id: str, available: dict[str, bool]) -> list[str]:
    """available: {"start_image": True, "end_frame": False, ...} — devolve
    a lista de inputs obrigatórios que faltam (vazio = pode gerar)."""
    workflow_def = WORKFLOWS.get(workflow_id) or {}
    missing = [key for key in workflow_def.get("required_inputs", []) if not available.get(key)]
    return missing
