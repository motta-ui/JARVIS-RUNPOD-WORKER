#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
acs_wansession_path.py — O caminho NOVO (flag ON), SEPARADO do código Gradio.
O _generate_background desvia pra cá quando ACS_USE_WANSESSION=1. O código Gradio
de hoje fica 100% intocado (só ganha um `if flag: return _run_wansession(...)` no topo).

Mapeia o GenerateRequest → settings (por nome) e chama o worker. Sem Gradio,
sem porta 7871, sem ficha posicional, sem polling de output.
"""
from __future__ import annotations

import os

# req.<campo>  →  nome do campo no motor (settings). NÚCLEO (t2v/t2i/i2v básico).
# Os casos especiais (áudio multi-speaker, control nets, custom slots) são a
# COMPLETUDE da migração + a bateria de regressão do Luigi.
def build_core_settings(req: dict, model_type: str) -> dict:
    s = {
        "prompt":              req.get("prompt", ""),
        "negative_prompt":     req.get("negative_prompt", ""),
        "resolution":          req.get("resolution", "1024x1024"),
        "seed":                req.get("seed", -1),
        "num_inference_steps": req.get("steps", req.get("num_inference_steps", 8)),
        "guidance_scale":      req.get("guidance_scale", 5.0),
        "activated_loras":     req.get("loras_choices", []),   # [FIX-LORA 06-28] o MOTOR lê activated_loras (wgp.py:1063), NAO loras_choices → era por isso que a lora NUNCA aplicava (o borrado, desde sempre). Confirmado com os settings do video do Luigi.
        "loras_choices":       req.get("loras_choices", []),   # mantido p/ compat de diagnostico
        "loras_multipliers":   req.get("loras_multipliers", ""),
    }
    # vídeo: usa o video_length JÁ EM FRAMES (computado pelo acs_api via
    # _seconds_to_video_length). Se não vier, deixa o default do modelo agir.
    if req.get("video_length"):
        s["video_length"] = req["video_length"]
    # imagem de referência (i2v/flf) — caminho local, o worker lê direto (mesma máquina)
    if req.get("ref_image_path"):
        s["image_start"] = req["ref_image_path"]
    if req.get("end_image_path"):
        s["image_end"] = req["end_image_path"]
    # modo → image_prompt_type (i2v=start, flf=start+end, continue=video source)
    _MODE_IPT = {"i2v": "S", "flf": "SE", "continue": "V", "t2v": "", "t2i": ""}
    _ipt = _MODE_IPT.get(req.get("generation_mode", "t2v"), "")
    if _ipt:
        s["image_prompt_type"] = _ipt
    if req.get("ctrl_video_path"):
        # [FIX-CONTROL 2026-06-26] control (canny/depth/motion, tem ctrl_video_prompt_type)
        # vai p/ video_guide (control net); continue/estender vai p/ video_source.
        # Antes mandava SEMPRE video_source → canny/depth não recebiam o control video.
        if req.get("ctrl_video_prompt_type"):
            s["video_guide"] = req["ctrl_video_path"]
        else:
            s["video_source"] = req["ctrl_video_path"]
    # [FIX-INJECT 2026-06-26] imagens de referência do inject (ref_inject_paths) → image_refs.
    # Era dropado (image_refs é file key, excluído do enriquecimento) → inject vinha sem as imagens.
    if req.get("ref_inject_paths"):
        s["image_refs"] = req["ref_inject_paths"]
    # multi-speaker / áudio-guia em vídeo (MultiTalk): vozes + posições
    if req.get("audio_path"):
        s["audio_guide"] = req["audio_path"]
    if req.get("audio_path2"):
        s["audio_guide2"] = req["audio_path2"]
    if req.get("speakers_locations"):
        s["speakers_locations"] = req["speakers_locations"]
    if req.get("audio_prompt_type"):
        s["audio_prompt_type"] = req["audio_prompt_type"]
    # [FIX-FILEKEYS 2026-06-26] control image (t2i control/pose/inpaint) e Custom Soundtrack
    # também eram dropados (file keys excluídos do enriquecimento, não tratados aqui).
    if req.get("ctrl_image_path"):
        s["image_guide"] = req["ctrl_image_path"]
    if req.get("audio_source_path"):
        s["audio_source"] = req["audio_source_path"]
    # [TRIM-VÍDEO 2026-06-26] corte por frames do control/source video (settings padrão do motor;
    # novos no ACS → não vêm no _save_kw, setados aqui). guide="1"/"a:b"/espaço/-1; source=inteiro.
    if req.get("keep_frames_video_guide"):
        s["keep_frames_video_guide"] = req["keep_frames_video_guide"]
    if req.get("keep_frames_video_source"):
        s["keep_frames_video_source"] = req["keep_frames_video_source"]
    # [TALKING-HEAD 2026-06-26] Safety net áudio-driven: em multitalk/infinitetalk a voz é
    # CONDICIONAMENTO de lip-sync. Se veio audio_guide mas audio_prompt_type vazio, o motor
    # gera o lip-sync mas NÃO muxa a voz no mp4 (vídeo mudo — provado pela tela: apt=""→sem
    # áudio, apt="A"→aac 16kHz muxado). Força "A". O frontend já default p/ "A" ao trocar de
    # modelo; isto cobre chamadas de API / sessão restaurada que cheguem sem o flag.
    if model_type in ("multitalk", "infinitetalk") and s.get("audio_guide") and not s.get("audio_prompt_type"):
        s["audio_prompt_type"] = "A"
    s["model_type"] = model_type
    return {k: v for k, v in s.items() if v != "" or k in ("prompt", "negative_prompt")}


# Campos de `settings` (nomes reais Wan2GP) que carregam um path de ARQUIVO
# LOCAL — precisam ser enviados pro Worker remoto antes do /run_task, porque
# o Worker roda num Pod que não vê o disco desta máquina. image_refs é lista.
_FILE_FIELDS = ("image_start", "image_end", "video_guide", "video_source",
                "audio_guide", "audio_guide2", "image_guide", "audio_source")
_FILE_LIST_FIELDS = ("image_refs",)


def _upload_local_files(wan_client, settings: dict) -> dict:
    """Substitui cada path local em `settings` pelo path remoto devolvido
    pelo Worker (upload real via /upload-ref ou /upload-audio). Um valor que
    já não existe como arquivo local (ex.: já é um path remoto) é deixado
    intocado — nunca tenta reenviar o que já está no Worker."""
    for key in _FILE_FIELDS:
        val = settings.get(key)
        if val and os.path.isfile(val):
            settings[key] = wan_client.upload(val)
    for key in _FILE_LIST_FIELDS:
        vals = settings.get(key)
        if isinstance(vals, list) and vals:
            settings[key] = [wan_client.upload(v) if v and os.path.isfile(v) else v for v in vals]
    return settings


def run_wansession_generation(wan_client, req: dict, model_type: str) -> dict:
    """Substitui os 10 PASSOs do balé Gradio por 1 chamada. Retorna {ok, path, error}."""
    settings = build_core_settings(req, model_type)
    settings = _upload_local_files(wan_client, settings)
    return wan_client.generate(model_type, settings)


# ── ÁUDIO (AudioGenerateRequest tem campos próprios) ─────────────────────────
def build_audio_settings(req: dict, model_type: str) -> dict:
    s = {
        "prompt":            req.get("prompt", ""),
        "seed":              req.get("seed", -1),
        "duration_seconds":  req.get("duration_seconds", 20),
        "guidance_scale":    req.get("guidance_scale", 7.0),
        "audio_scale":       req.get("audio_scale", 0.5),
        "repeat_generation": req.get("num_generations", 1),
        "temperature":       req.get("temperature", 1.0),
        "top_k":             req.get("top_k", 50),
        "top_p":             req.get("top_p", 0.9),
        "model_type":        model_type,
    }
    _alt = req.get("alt_prompt", "")
    if _alt:
        s["alt_prompt"] = _alt
    nis = req.get("num_inference_steps", -1)
    if nis and nis > 0:
        s["num_inference_steps"] = nis
    return s


def run_wansession_audio(wan_client, req: dict, model_type: str) -> dict:
    return wan_client.generate(model_type, build_audio_settings(req, model_type))


# ── [A] Barra de progresso: roda a geração numa thread e move a barra ────────
def run_with_live_progress(jobs, job_id, gen_callable, lo: int = 50, hi: int = 95):
    """Executa gen_callable() numa thread e vai subindo jobs[job_id]['progress']
    de lo→hi enquanto gera (estimativa por tempo — a barra MOVE em vez de travar).
    Progresso por step exato (via callbacks do worker) fica como refinamento."""
    import threading, time, os, json as _json, urllib.request
    holder = {}
    def _run():
        try:
            holder["r"] = gen_callable()
        except Exception as e:
            holder["e"] = e
    t = threading.Thread(target=_run, daemon=True)
    t.start()
    # [PROGRESSO-REAL 2026-06-27] lê o % REAL do motor (worker GET /progress, alimentado
    # pelo callbacks.on_progress) em vez de estimar por tempo. Mapeia o 0-100 real do
    # motor pra banda lo-hi da barra. Textos amigáveis (sem termo técnico).
    _wport = os.getenv('ACS_WAN_WORKER_PORT', '7872')
    _wurl = f"http://127.0.0.1:{_wport}/progress"
    _wtoken = os.getenv("ACS_WORKER_TOKEN", "")
    passes = 0          # nº de resets detectados (cada pass de guidance reseta o % do motor)
    prev_real = -1
    half = (hi - lo) / 2.0
    while t.is_alive():
        time.sleep(1.5)
        real = None
        try:
            _req = urllib.request.Request(_wurl)
            if _wtoken:
                _req.add_header("X-ACS-Token", _wtoken)
            with urllib.request.urlopen(_req, timeout=2) as _r:
                real = int((_json.loads(_r.read().decode()) or {}).get("value", 0) or 0)
        except Exception:
            real = None
        # [PROGRESSO-REAL] o % do motor RESETA a cada pass (guidance_phases=2) → detecta a
        # queda grande como "novo pass" e dá meia-banda por pass: pass 1 enche lo→meio,
        # pass 2 enche meio→hi. Sem isto a barra saltava pra 90% no fim do pass 1 e segurava.
        if real is not None and real >= 0:
            if prev_real >= 0 and real + 25 < prev_real:
                passes += 1
            prev_real = real
        seg = min(passes, 1)   # ~2 passes; passes extras (vídeo longo c/ janelas) capam em hi
        if real and real > 0:
            target = lo + int(seg * half + (real / 100.0) * half)
        else:
            target = lo
        if job_id in jobs:
            cur = int(jobs[job_id].get("progress", lo) or lo)
            # avança SUAVE rumo ao alvo (máx +4/tick), NUNCA volta → barra fluida
            new = min(hi, cur + min(4, max(0, target - cur)))
            jobs[job_id]["progress"] = new
            # antes do motor reportar % = ainda carregando o modelo (label honesto, não "Gerando")
            if not (real and real > 0):
                jobs[job_id]["step"] = "Carregando modelo"
            else:
                jobs[job_id]["step"] = "Finalizando…" if new >= hi - 1 else "Gerando…"
    t.join()
    if "e" in holder:
        raise holder["e"]
    return holder.get("r")
