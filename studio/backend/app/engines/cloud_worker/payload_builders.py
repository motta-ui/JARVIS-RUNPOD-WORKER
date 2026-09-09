"""
PAYLOAD BUILDERS (extras por workflow)

O upload de referências e a tradução para os campos reais do Wan2GP
(image_start, image_end, image_refs, video_guide, video_source,
audio_guide) e as letras de activação (image_prompt_type/
video_prompt_type/audio_prompt_type) já são feitos por
CloudWorkerEngine._resolve_zone_uploads() — lógica real, já testada em
produção (T2V/I2V reais via Studio), e que este módulo reaproveita em
vez de duplicar.

O que falta por workflow, e que este módulo acrescenta em cima dessa
base já correcta, são os campos que só existem em workflows específicos
e que _resolve_zone_uploads() não conhece: motion_amplitude/prompt
enhancer do Image Motion, os campos de áudio do Talking Image/Infinite
Talk, e o default de video_prompt_type do Character Animate. Cada
workflow continua com o seu próprio contrato (a função correspondente
abaixo), só partilhando o helper de merge de video_prompt_type.

Nomes de campo confirmados directamente em wgp.py no Pod (grep de
ocorrências reais): motion_amplitude, audio_guidance_scale, audio_scale,
speakers_locations, audio_guide2, image_refs, video_prompt_type. Campos
que a API do ACS usa mas o Wan2GP NÃO conhece (ctrl_video_prompt_type,
inject_video_prompt_type, ref_inject_paths, riflex_setting em minúsculas)
foram corrigidos para os nomes reais (video_prompt_type, image_refs,
RIFLEx_setting) — ver registry/utility_resolver.py.
"""
from typing import Any

from ...registry.utility_resolver import merge_video_prompt_type


def apply_image_motion_extras(job_params: dict[str, Any], settings: dict[str, Any]) -> None:
    if job_params.get("motion_amplitude") is not None:
        settings["motion_amplitude"] = job_params["motion_amplitude"]
    if job_params.get("prompt") and not settings.get("prompt_enhancer"):
        # regra do pacote (image_motion.json): "prompt_enhancer": "T when prompt is present"
        settings["prompt_enhancer"] = "T"


def apply_talking_image_extras(job_params: dict[str, Any], settings: dict[str, Any]) -> None:
    if settings.get("audio_guide"):
        settings.setdefault("audio_prompt_type", job_params.get("audio_prompt_type", "A"))
    if job_params.get("audio2_path") or job_params.get("audio_path2"):
        settings["audio_guide2"] = job_params.get("audio2_path") or job_params.get("audio_path2")
        settings.setdefault("speakers_locations", job_params.get("speakers_locations", "0:45 55:100"))
    if job_params.get("audio_guidance_scale") is not None:
        settings["audio_guidance_scale"] = job_params["audio_guidance_scale"]
    if job_params.get("audio_scale") is not None:
        settings["audio_scale"] = job_params["audio_scale"]


def apply_infinite_talk_extras(job_params: dict[str, Any], settings: dict[str, Any], scene_refs: list[str]) -> None:
    if scene_refs:
        existing_refs = settings.get("image_refs") or []
        settings["image_refs"] = [*existing_refs, *scene_refs]
        settings["video_prompt_type"] = merge_video_prompt_type(settings.get("video_prompt_type", ""), "KI")
    apply_talking_image_extras(job_params, settings)


def apply_character_animate_extras(model_id: str | None, settings: dict[str, Any]) -> None:
    if not settings.get("video_prompt_type") and model_id == "scail2_14B":
        # [ACS SCAIL2] default do próprio motor quando video_prompt_type vem
        # vazio para este modelo específico — documentado no pacote como "V1".
        settings["video_prompt_type"] = "V1"


WORKFLOW_EXTRAS = {
    "image_motion": lambda job_params, settings, **_: apply_image_motion_extras(job_params, settings),
    "talking_image": lambda job_params, settings, **_: apply_talking_image_extras(job_params, settings),
    "infinite_talk": lambda job_params, settings, scene_refs=(), **_: apply_infinite_talk_extras(job_params, settings, list(scene_refs)),
    "character_animate": lambda job_params, settings, model_id=None, **_: apply_character_animate_extras(model_id, settings),
}


def apply_workflow_extras(workflow_id: str, job_params: dict[str, Any], settings: dict[str, Any],
                           model_id: str | None = None, scene_refs: list[str] | None = None) -> None:
    fn = WORKFLOW_EXTRAS.get(workflow_id)
    if fn:
        fn(job_params, settings, model_id=model_id, scene_refs=scene_refs or [])
