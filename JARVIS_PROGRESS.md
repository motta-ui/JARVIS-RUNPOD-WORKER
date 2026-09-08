# JARVIS AI STUDIO — PROGRESS (checklist oficial, 30 etapas)

Última atualização: 2026-09-08. Ver `JARVIS_SESSION_HANDOFF.md` para o contexto completo de cada item concluído.

Convenção: `[x]` concluído e comprovado com evidência real (job_id, arquivo, log, teste). `[ ]` pendente — nunca marcar como concluído sem evidência real.

## Validação de infraestrutura e runtime real

- [x] 1. Localizar/clonar o repositório real (`motta-ui/JARVIS-RUNPOD-WORKER`) no Windows — nenhuma das pastas antigas no Desktop era um clone git real; clonado de verdade.
- [x] 2. Testar SSH real ao Pod RunPod existente (RTX 4090)
- [x] 3. Inspecionar o runtime real do Pod (GPU, driver, CUDA, PyTorch, Docker, processos, portas) antes de qualquer alteração — só leitura
- [x] 4. Corrigir `JARVIS_WAN_DIR` no `jarvis_worker/app.py` para o path real (`/workspace/Wan2GP`, era um palpite antigo)
- [x] 5. Sincronizar `jarvis_worker/` para o Pod (`/workspace/jarvis_worker`, no volume persistente)
- [x] 6. Subir o Worker FastAPI real no Pod (`127.0.0.1:7271`, no venv já existente do Wan2GP — zero dependência nova instalada)
- [x] 7. Expor o Worker via proxy nginx **já existente** na imagem (`:7270 -> :7271`), sem abrir porta nova nem tocar em config
- [x] 8. Validar `GET /health` real (direto e via proxy)
- [x] 9. Validar `GET /models` real (catálogo real de ~200 modelos do WanGP)
- [x] 10. Confirmar que o Worker coexiste com o Wan2GP original (Gradio :7860/:7862) sem conflito

## T2V real

- [x] 11. T2V real disparado diretamente no Worker (`model_type=t2v_1.3B`) — download real dos pesos + geração real na RTX 4090
- [x] 12. Configurar o JARVIS Studio localmente (backend + frontend, venv + npm install)
- [x] 13. Conectar o Studio ao Worker real via túnel SSH local (`127.0.0.1:7270`), sem expor nova porta na RunPod
- [x] 14. Corrigir ineficiência real encontrada (`CloudWorkerEngine.health()` fazia 26 chamadas redundantes) — cache compartilhado de 5s
- [x] 15. T2V real disparado pelo JARVIS Studio (`POST /api/jobs`, job `70b341ed-...`, engine `wan`, model `t2v_1.3B`)
- [x] 16. Job aparece corretamente no sistema de jobs do Studio, com progresso acompanhável
- [x] 17. Download real do MP4 pelo Studio (via `/outputs/{path}` do Worker)
- [x] 18. Vídeo real aparece na Gallery do Studio
- [x] 19. Vídeo confirmado como MP4 válido (assinatura `ftyp isom`) e reproduzido no navegador

## I2V real

- [x] 20. I2V real disparado pelo JARVIS Studio via preset ("Light I2V 8GB", `model=i2v_nvfp4`, job `80ad13dd-...`), com imagem de referência real enviada e usada na geração
- [x] 21. MP4 real do I2V confirmado em disco (3.249.778 bytes)

## Código e repositório

- [x] 22. Código relevante commitado (`ff44258`, `12dc4d3`) e enviado para `origin/claude/jarvis-multimodal-integration-dis74f`
- [x] 23. `npm run build` do frontend passa sem erros
- [x] 24. Testes relevantes do backend passam (`test_backend.py`, `test_cloud.py` — casos ligados ao Cloud Worker)
- [x] 25. Nenhum secret, token, modelo, output ou vídeo commitado — token do Worker só em config local gitignored

## Pendente — próximas etapas (ordem definida)

- [ ] 26. **AUDIO REAL** ← próxima etapa imediata
- [ ] 27. MOTION REAL
- [ ] 28. END FRAME / CONTINUE reais
- [ ] 29. LORA real (hoje `CloudWorkerEngine.get_capabilities()` reporta `lora: False` deliberadamente)
- [ ] 30. IMAGE REFERENCES completo no Image Studio (drag/drop, capacidade por modelo, multi-referência até 5, histórico/projeto) + PRESETS/WORKFLOWS completos (200+ ainda `executable: False`) + BOOTSTRAP automático + POD automático (criação) + RESULTADOS (execução e upload automático) + AUTO-DESTRUCTION do Pod + REBUILD TEST (runtime do zero num Pod novo) + FINAL (arquitetura efêmera completa: criar → preparar → baixar modelos → executar → entregar → destruir)
