#!/usr/bin/env python3
"""
Testes do sistema de Registry (MODEL/ENGINE/WORKFLOW/LORA/PRESET) —
corre diretamente em Python, sem precisar do servidor no ar nem de
fastapi/pydantic instalados. Cobre os 14 pontos pedidos:

 1. O Registry carrega corretamente.
 2. O backend fornece os presets.
 3. O frontend não possui lista hardcoded (verificado por grep, não aqui).
 4. Selecionar um preset carrega a sua configuração.
 5. Trocar de preset atualiza as capabilities.
 6. O botão T2V resolve o workflow correto.
 7. O botão I2V resolve o workflow correto.
 8. End Frame só aparece quando suportado.
 9. Continue só aparece quando suportado.
10. Audio só aparece quando suportado.
11. LoRAs são associados corretamente.
12. Presets sem workflow executável são marcados como não executáveis.
13. O Registry continua a funcionar depois de "reiniciar" o backend.
14. A V1 existente (engine/model explícitos, sem preset_id) continua a funcionar.

Uso:
    cd backend
    python ../scripts/test_registry.py
"""
import importlib
import json
import sys
import time
import uuid
from pathlib import Path
from types import SimpleNamespace

BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
sys.path.insert(0, str(BACKEND_DIR))

from app import database as db  # noqa: E402
from app.registry import (  # noqa: E402
    model_registry, workflow_registry, lora_catalog, preset_registry, engine_registry, config_importer,
)
from app.engines.registry import get_engine  # noqa: E402

PASSED, FAILED = [], []


def check(name, fn):
    try:
        fn()
        PASSED.append(name)
        print(f"[PASS] {name}")
    except Exception as e:
        FAILED.append((name, str(e)))
        print(f"[FAIL] {name}: {e}")


def job_create(preset_id=None, **kw):
    """Réplica mínima da lógica de routers/jobs.py:create_job, sem FastAPI."""
    payload = SimpleNamespace(
        project_id=None, preset_id=preset_id, engine=kw.get("engine"), model=kw.get("model"),
        mode=kw.get("mode", "t2v"), kind=kw.get("kind", "video"), prompt=kw.get("prompt", ""),
        parameters=kw.get("parameters", {}),
    )
    parameters = dict(payload.parameters)
    engine_id, model_id, kind = payload.engine, payload.model, payload.kind
    preset_name = None

    if payload.preset_id:
        resolved = preset_registry.resolve_preset(payload.preset_id)
        if not resolved:
            raise ValueError(f"preset '{payload.preset_id}' não encontrado")
        preset_name = resolved["name"]
        kind = resolved["category"]
        engine_id = resolved["runtime_engine"]
        model_id = resolved["model"]["id"] if resolved.get("model") else resolved["id"]
        for k, v in (resolved.get("defaults") or {}).items():
            parameters.setdefault(k, v)

    engine = get_engine(engine_id)
    if not engine:
        raise ValueError(f"engine '{engine_id}' não encontrado")
    ok, err = engine.validate_request(parameters)
    if not ok:
        raise ValueError(err)

    jid = str(uuid.uuid4())
    ts = db.now_iso()
    with db.db_session() as conn:
        conn.execute(
            "INSERT INTO jobs (id, project_id, engine, model, mode, kind, prompt, parameters, "
            "status, progress, preset_id, preset_name, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (jid, None, engine_id, model_id, payload.mode, kind, payload.prompt,
             json.dumps(parameters), "QUEUED", 0.0, payload.preset_id, preset_name, ts, ts),
        )
    engine.generate(jid, parameters)
    return jid


def wait_job(job_id, engine_id="mock", timeout=15):
    deadline = time.time() + timeout
    engine = get_engine(engine_id)
    status = {"status": "UNKNOWN"}
    while time.time() < deadline:
        status = engine.get_status(job_id)
        if status["status"] in ("COMPLETED", "FAILED", "CANCELLED"):
            break
        time.sleep(0.2)
    return status


EXPECTED_NAMES = [
    "Cinematic Lite", "Cinematic Pro 1.1", "Cinematic Pro Full", "Light 8GB",
    "Light I2V 8GB", "Studio AI I2V", "Talking Head", "Infinite Talk",
    "Studio Editor", "Director Vision", "Director Vision Lite", "Human Studio",
    "Infinite Motion", "Cinematic EditAnything", "Cinematic Edit", "MiniMax H3",
]


def main():
    db.init_db()

    # --- 1. Registry carrega corretamente -------------------------------
    def t1_registry_loads():
        models = model_registry.list_models()
        assert len(models) == 202, f"esperava 202 modelos (2 curados + 200 importados), veio {len(models)}"
        workflows = workflow_registry.list_workflows()
        assert len(workflows) == 204, f"esperava 204 workflows (4 placeholders + 200 importados), veio {len(workflows)}"
        loras = lora_catalog.list_catalog()
        assert len(loras) > 0, "catálogo de LoRAs vazio"
        engines = engine_registry.list_engines()
        assert len(engines) > 0, "engine registry vazio"

    # --- 2. Backend fornece os presets -----------------------------------
    def t2_presets_available():
        presets = preset_registry.list_presets()
        assert len(presets) == 20
        names = {p["name"] for p in presets}
        missing = [n for n in EXPECTED_NAMES if n not in names]
        assert not missing, f"presets em falta: {missing}"

    # (3 é verificado por grep no frontend, não em python)

    # --- 4. Selecionar um preset carrega a sua configuração --------------
    def t4_select_preset_loads_config():
        r = preset_registry.resolve_preset("cinematic-pro-1-1")
        assert r is not None
        assert r["model"]["name"] == "LTX-2 2.3 Distilled 1.1 22B"
        assert r["engine_id"] == "ltx2"
        assert r["config_source"] == "video/ltx2_22B_distilled_1_1.json"
        assert r["defaults"]["num_inference_steps"] == 8

    # --- 5. Trocar de preset atualiza as capabilities ---------------------
    def t5_capabilities_differ_per_preset():
        light = preset_registry.resolve_preset("light-8gb")
        editor = preset_registry.resolve_preset("studio-editor")
        assert light["capabilities"] != editor["capabilities"]
        assert "control_video" not in light["capabilities"]
        assert "control_video" in editor["capabilities"]

    # --- 6/7. Botões T2V e I2V resolvem o workflow correto -----------------
    def t6_t2v_button_resolves_correct_workflow():
        r = preset_registry.resolve_generation_mode("light-8gb", "t2v")
        assert r is not None
        assert r["workflow_id"] == "t2v_1.3B"
        assert r["engine_id"] == "mock"  # runtime (wan ainda não tem adapter)

    def t7_i2v_button_resolves_correct_workflow():
        r = preset_registry.resolve_generation_mode("studio-ai-i2v", "i2v")
        assert r is not None
        assert r["workflow_id"] == "i2v_720p"
        wf = workflow_registry.get_workflow(r["workflow_id"])
        assert wf["source_type"] == "preset_config"

    def t7b_unsupported_mode_returns_none():
        # light-8gb (t2v_1.3B) não suporta i2v - resolve_generation_mode deve devolver None
        r = preset_registry.resolve_generation_mode("light-8gb", "i2v")
        assert r is None, "preset sem suporte a i2v não devia resolver o modo"

    def t_regression_cinematic_pro_1_1_keeps_all_v1_modes():
        """Regressão reportada: Cinematic Pro 1.1 só mostrava Texto->Vídeo
        depois da migração para o Registry. Corrigido agregando capabilities
        por família de arquitetura (ltx2_22B) - ver config_importer.py."""
        r = preset_registry.resolve_preset("cinematic-pro-1-1")
        for expected_mode in ("t2v", "i2v", "end_frame", "continue"):
            assert expected_mode in r["modes"], f"regressão: modo '{expected_mode}' voltou a desaparecer"
        assert "audio_to_video" in r["capabilities"] or "audio_output" in r["capabilities"]
        # a ausência de adapter executável (status='planned') NUNCA deve
        # remover modos - só afeta runtime_engine/status_detail
        assert r["status"] == "planned"
        assert r["runtime_engine"] == "mock"
        assert len(r["modes"]) >= 4, "modos não podem ter sido removidos pela falta de adapter"

    # --- 8. End Frame só aparece quando suportado ---------------------------
    def t8_end_frame_only_when_supported():
        minimax = preset_registry.resolve_preset("minimax-h3")
        assert "end_frame" in minimax["modes"], "MiniMax H3 devia suportar end_frame"
        light = preset_registry.resolve_preset("light-8gb")
        assert "end_frame" not in light["modes"], "Light 8GB não devia ter end_frame"

    # --- 9. Continue só aparece quando suportado -----------------------------
    def t9_continue_only_when_supported():
        infinite_talk = preset_registry.resolve_preset("infinite-talk")
        assert "continue" in infinite_talk["modes"], "Infinite Talk devia suportar continue"
        light = preset_registry.resolve_preset("light-8gb")
        assert "continue" not in light["modes"], "Light 8GB (Wan 1.3B, sem siblings i2v/continue) não devia ter continue"

    # --- 10. Audio só aparece quando suportado --------------------------------
    def t10_audio_only_when_supported():
        talking_head = preset_registry.resolve_preset("talking-head")
        assert "audio_to_video" in talking_head["capabilities"]
        light = preset_registry.resolve_preset("light-8gb")
        assert "audio_to_video" not in light["capabilities"]
        assert "audio_output" not in light["capabilities"]

    # --- 11. LoRAs são associados corretamente ---------------------------------
    def t11_loras_associated_correctly():
        se = preset_registry.resolve_preset("studio-editor")
        assert len(se["loras"]) == 4
        ids = {l["id"] for l in se["loras"]}
        assert "DetailEnhancerV1" in ids
        for l in se["loras"]:
            assert l["installed"] is False  # BD vazia neste teste - nunca finge instalado
        # preset sem loras reais deve devolver lista vazia, nao inventada
        light = preset_registry.resolve_preset("light-8gb")
        assert light["loras"] == []

    def t11b_lora_compatibility_check():
        se = preset_registry.resolve_preset("studio-editor")
        lora_id = se["loras"][0]["id"]
        assert lora_catalog.is_compatible(lora_id, "wan") is True
        assert lora_catalog.is_compatible(lora_id, "flux") is False
        assert lora_catalog.is_compatible("isto-nao-existe", "wan") is False

    # --- 12. Presets sem workflow executável marcados como não executáveis ------
    def t12_workflows_marked_non_executable():
        all_workflows = workflow_registry.list_workflows()
        assert len(all_workflows) > 0
        non_executable = [w for w in all_workflows if w["executable"] is False]
        assert len(non_executable) == len(all_workflows), "existe workflow marcado executável sem o ser"
        preset_configs = [w for w in all_workflows if w["source_type"] == "preset_config"]
        assert len(preset_configs) == 200
        for w in preset_configs:
            assert w["executable"] is False

    # --- 13. Registry continua a funcionar depois de "reiniciar" o backend ------
    def t13_registry_survives_restart():
        # limpar todas as caches (lru_cache) e módulos - simula um restart real do processo
        for mod in (model_registry, workflow_registry, lora_catalog, preset_registry, engine_registry, config_importer):
            for name in dir(mod):
                attr = getattr(mod, name)
                if hasattr(attr, "cache_clear"):
                    attr.cache_clear()
        importlib.reload(config_importer)
        importlib.reload(model_registry)
        importlib.reload(workflow_registry)
        importlib.reload(lora_catalog)
        importlib.reload(preset_registry)
        importlib.reload(engine_registry)

        presets_after = preset_registry.list_presets()
        assert len(presets_after) == 20
        r = preset_registry.resolve_preset("cinematic-pro-1-1")
        assert r["model"]["name"] == "LTX-2 2.3 Distilled 1.1 22B"

    # --- 14. V1 existente continua a funcionar (sem preset_id) -------------------
    def t14_legacy_path_still_works():
        jid = job_create(engine="mock", model="jarvis-demo-t2v", mode="t2v", kind="video", prompt="legacy v1")
        status = wait_job(jid)
        assert status["status"] == "COMPLETED", status
        with db.db_session() as conn:
            row = dict(conn.execute("SELECT preset_id FROM jobs WHERE id=?", (jid,)).fetchone())
        assert row["preset_id"] is None

    def t14b_job_via_new_preset_path_still_works():
        jid = job_create(preset_id="jarvis-demo-video", mode="t2v", prompt="teste demo via preset")
        status = wait_job(jid)
        assert status["status"] == "COMPLETED", status

    def t_mock_accepts_all_resolved_modes():
        """O Mock Engine deve aceitar TODOS os modos que o preset resolve,
        para validar a interface antes dos adapters reais existirem."""
        preset = preset_registry.resolve_preset("cinematic-pro-1-1")
        for mode in preset["modes"]:
            resolved_mode = preset_registry.resolve_generation_mode("cinematic-pro-1-1", mode)
            assert resolved_mode is not None, f"modo '{mode}' não resolveu"
            assert resolved_mode["engine_id"] == "mock"
            assert "Mock" in resolved_mode["execution_status"] or "Workflow preparado" in resolved_mode["execution_status"]
            jid = job_create(preset_id="cinematic-pro-1-1", mode=mode, prompt=f"teste modo {mode}")
            status = wait_job(jid)
            assert status["status"] == "COMPLETED", f"modo '{mode}': {status}"

    def t_resolve_generation_mode_unsupported_returns_none():
        r = preset_registry.resolve_generation_mode("light-8gb", "continue")
        assert r is None, "Light 8GB não suporta continue - resolve_generation_mode devia devolver None"

    def t14c_unknown_preset_rejected():
        try:
            job_create(preset_id="nao-existe-mesmo", mode="t2v")
            raise AssertionError("deveria ter levantado ValueError")
        except ValueError:
            pass

    checks = [
        ("1. Registry carrega corretamente (models/workflows/loras/engines)", t1_registry_loads),
        ("2. Backend fornece os 20 presets, incluindo os 16 pedidos", t2_presets_available),
        ("4. Selecionar um preset carrega a configuração completa", t4_select_preset_loads_config),
        ("5. Trocar de preset atualiza as capabilities", t5_capabilities_differ_per_preset),
        ("6. Botão T2V resolve o workflow correto", t6_t2v_button_resolves_correct_workflow),
        ("7. Botão I2V resolve o workflow correto", t7_i2v_button_resolves_correct_workflow),
        ("7b. Modo não suportado devolve None (não inventa)", t7b_unsupported_mode_returns_none),
        ("REGRESSÃO: Cinematic Pro 1.1 mantém t2v/i2v/end_frame/continue", t_regression_cinematic_pro_1_1_keeps_all_v1_modes),
        ("8. End Frame só aparece quando suportado", t8_end_frame_only_when_supported),
        ("9. Continue só aparece quando suportado", t9_continue_only_when_supported),
        ("10. Audio só aparece quando suportado", t10_audio_only_when_supported),
        ("11. LoRAs são associados corretamente", t11_loras_associated_correctly),
        ("11b. Verificação de compatibilidade de LoRA", t11b_lora_compatibility_check),
        ("12. Workflows importados marcados como não executáveis", t12_workflows_marked_non_executable),
        ("13. Registry sobrevive a um 'restart' (cache limpa + reload)", t13_registry_survives_restart),
        ("14. V1 (sem preset_id) continua 100% funcional", t14_legacy_path_still_works),
        ("14b. Caminho novo (com preset_id) funcional", t14b_job_via_new_preset_path_still_works),
        ("Mock Engine aceita todos os modos resolvidos do preset (t2v/i2v/end_frame/continue)", t_mock_accepts_all_resolved_modes),
        ("resolve_generation_mode devolve None para modo não suportado", t_resolve_generation_mode_unsupported_returns_none),
        ("14c. Preset inexistente é rejeitado com erro claro", t14c_unknown_preset_rejected),
    ]

    for name, fn in checks:
        check(name, fn)

    print(f"\nResultado: {len(PASSED)} passou / {len(FAILED)} falhou (de {len(checks)})")
    if FAILED:
        for name, err in FAILED:
            print(f"  - {name}: {err}")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
