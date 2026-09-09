"""
UTILITY RESOLVER

Resolve os utilitários/controlos (Ctrl Video, Frame Inject, End Frame) e
os parâmetros avançados (RIFLEx, upsampling, self refiner, film grain,
prompt enhancer, ...) — só habilita o que o pacote de referência
(JARVIS_WORKFLOW_PARITY_PACK/workflows/utilities_and_controls.json)
documenta como suportado pela família do modelo, nunca "porque existe
na UI".

Ctrl Video — flags reais (LTX2), preservados literalmente do pacote:
  PVG = Human Motion   OVG = Pose Align   DVG = Depth   EVG = Canny
  VG  = Raw Format     V&G = HDR          KFI = Frame/Inject control
  V   = memória de vídeo (Story AV / JoyAI Control Video Memory)

Frame Inject — tipos: KI (fundo+sujeitos) | I (só sujeitos).

IMPORTANTE (confirmado diretamente em wgp.py no Pod, grep de
"in video_prompt_type"): TODOS estes códigos (Ctrl Video E Frame
Inject) são letras dentro do MESMO campo real do Wan2GP,
`video_prompt_type` — não existe `ctrl_video_prompt_type` nem
`inject_video_prompt_type` como campos próprios no motor (esses são só
nomes internos da API do ACS, remapeados antes de chamar o Wan2GP). O
motor testa cada letra com `"X" in video_prompt_type` (membership,
independente de posição) — por isso é seguro tratar o valor como um
CONJUNTO de caracteres e unir letras (ex.: "I" de Frame Inject + "V" de
Continue), nunca concatenar às cegas. `&` é literal (flag HDR, sem
significado posicional) — confirmado pelo próprio comentário do pacote
("V=video guide presente, &=HDR output, G=guide denoising ativo").
"""

CONTROL_VIDEO_FLAGS = {
    "human_motion": "PVG",
    "pose_align": "OVG",
    "depth": "DVG",
    "canny": "EVG",
    "ic_raw": "VG",
    "hdr": "V&G",
    "frame_inject_control": "KFI",
    "video_memory": "V",
}

FRAME_INJECT_TYPES = {"background_and_subjects": "KI", "subjects_only": "I"}

# Famílias com advanced settings auditados (LTX2, ver
# workflows/utilities_and_controls.json do pacote). Outras famílias não
# têm estas regras confirmadas — o resolver não deixa passar nada para
# elas em vez de assumir que se comportam como o LTX2.
_ADVANCED_SUPPORTED_BY_FAMILY = {
    "ltx2": {
        "RIFLEx_setting": {0, 1, 2},  # nome real em wgp.py (capitalização importa: RIFLEx, não riflex)
        "temporal_upsampling": {"", "rife2", "rife4"},
        "self_refiner_setting": {0, 1, 2},
        "spatial_upsampling": {"", "lanczos", "flashvsr", "flashvsr2pass"},
        "force_fps": {"", "8", "16", "24"},
        "prompt_enhancer": {"", "T", "TI", "T1", "TI1"},
        "guidance_phases_override": {"auto", 1, 2},
        # faixa contínua (0.0-1.0), validada por range em vez de conjunto
        "film_grain_intensity": (0.0, 1.0),
        "film_grain_saturation": (0.0, 1.0),
    },
}


def _family_for_model(model_id: str) -> str | None:
    if model_id and model_id.startswith("ltx2_22B"):
        return "ltx2"
    return None


def resolve_control_video(model_id: str, control_video_option: str | None, has_ctrl_video: bool) -> dict:
    """Traduz a opção de Ctrl Video da UI (data/control_video.json) para as
    letras reais que entram em `video_prompt_type`. Devolve conflict em
    vez de inventar um flag para uma opção desconhecida, e nunca define
    o flag sem o vídeo real."""
    result = {"video_prompt_type_letters": "", "conflicts": []}
    if not control_video_option:
        return result
    if not has_ctrl_video:
        result["conflicts"].append(f"Ctrl Video '{control_video_option}' pedido sem vídeo de controlo real — ignorado.")
        return result
    flag = CONTROL_VIDEO_FLAGS.get(control_video_option)
    if not flag:
        result["conflicts"].append(f"Opção de Ctrl Video '{control_video_option}' desconhecida — ignorada.")
        return result
    result["video_prompt_type_letters"] = flag
    return result


def resolve_frame_inject(frame_inject_mode: str | None, ref_count: int) -> dict:
    """Mesmo campo real (`video_prompt_type`) — "I"/"K" são letras, não um
    campo próprio (confirmado: `inject_video_prompt_type` não existe em
    wgp.py)."""
    result = {"video_prompt_type_letters": "", "conflicts": []}
    if not frame_inject_mode:
        return result
    flag = FRAME_INJECT_TYPES.get(frame_inject_mode)
    if not flag:
        result["conflicts"].append(f"Modo de Frame Inject '{frame_inject_mode}' desconhecido — ignorado.")
        return result
    if ref_count < 1:
        result["conflicts"].append("Frame Inject pedido sem nenhuma imagem de referência — ignorado.")
        return result
    result["video_prompt_type_letters"] = flag
    return result


def merge_video_prompt_type(*letter_groups: str) -> str:
    """Une vários grupos de letras (Ctrl Video + Frame Inject + auto_payload
    de LoRA) num único valor de `video_prompt_type` — conjunto de
    caracteres, a ordem não importa para o motor (só faz `"X" in valor`)."""
    chars: set[str] = set()
    for group in letter_groups:
        chars |= set(group or "")
    return "".join(sorted(chars))


def resolve_advanced(model_id: str, advanced: dict | None) -> dict:
    """Filtra `advanced` (settings avançadas vindas da UI) para só as que a
    família do modelo suporta de facto, com o valor dentro do domínio
    documentado. Nunca deixa passar uma opção só porque a UI a mostra."""
    advanced = advanced or {}
    result = {"applied": {}, "rejected": {}}
    family = _family_for_model(model_id)
    supported = _ADVANCED_SUPPORTED_BY_FAMILY.get(family, {})
    if not supported:
        if advanced:
            result["rejected"] = {k: "família de modelo sem advanced settings auditados" for k in advanced}
        return result

    for key, value in advanced.items():
        domain = supported.get(key)
        if domain is None:
            result["rejected"][key] = "não suportado por esta família de modelo"
            continue
        if isinstance(domain, tuple):
            lo, hi = domain
            try:
                ok = lo <= float(value) <= hi
            except (TypeError, ValueError):
                ok = False
            if not ok:
                result["rejected"][key] = f"fora do intervalo [{lo}, {hi}]"
                continue
        elif value not in domain:
            result["rejected"][key] = f"valor '{value}' fora do domínio suportado {sorted(domain, key=str)}"
            continue
        result["applied"][key] = value
    return result
