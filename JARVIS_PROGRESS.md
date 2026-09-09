# JARVIS AI STUDIO — PROGRESS (checklist oficial)

Última atualização: 2026-09-09. Ver `JARVIS_SESSION_HANDOFF.md` para o contexto completo de cada item.

Convenção: `[x]` concluído e comprovado com evidência real (job_id, arquivo, log, teste). `[ ]` pendente — nunca marcar como concluído sem evidência real.

**⚠️ Itens 1-30 da versão anterior deste arquivo (2026-09-08) descreviam a reimplementação do zero, que foi abandonada.** Esse trabalho está preservado na branch `backup/studio-reimplementation-before-acs-adoption`, mas não é mais o caminho ativo do projeto. Checklist abaixo reflete o estado real: adoção do ACS comercial do usuário, rodando com execução 100% remota no RunPod.

## Adoção do ACS real

- [x] 1. Identificar que `ACS_NUCLEO.zip` é o produto comercial real do usuário (ACS Studio / AI Cinematic Studio Unlimited), confirmado byte-a-byte contra a instalação `C:\ACS Unlimited\`
- [x] 2. Backup do trabalho anterior na branch `backup/studio-reimplementation-before-acs-adoption` (commit `af0e44f`)
- [x] 3. Importar `acs_api.py`, `acs_wan_client.py`, `acs_wansession_path.py` e `frontend/` reais para `studio/backend/`
- [x] 4. Adaptar `acs_wan_client.py` para falar com o Worker remoto (`X-Jarvis-Token`, upload/download, polling assíncrono) em vez do Gradio local
- [x] 5. Corrigir upload de arquivos locais antes da geração (`_upload_local_files()`, chamado no ponto real onde `acs_api.py` monta as settings — não no wrapper que nunca era chamado)
- [x] 6. Corrigir LoRAs escolhidas manualmente sendo enviadas como filename puro (sem URL) — resolvidas via `_LORAS_URL_CACHE` antes do envio ao Worker
- [x] 7. Corrigir download de arquivos com espaço no nome (URL-encoding em `acs_wan_client.py::_download()`)
- [x] 8. Ativar modo dev (bypass de licença legítimo, já existente no próprio ACS) via `.dev_mode` + `version.json`, sem phone-home
- [x] 9. Provisionar `wan2gp_local/` (profiles, cache de URLs de LoRA, ffmpeg, etc. — sem `ckpts/`/`models/`, pois geração é 100% remota)
- [x] 10. Reescrever `studio/README.md` para a arquitetura real (era só a reimplementação abandonada)

## Validação real — Cinematic Pro (LTX2)

- [x] 11. T2V real disparado pela UI real do ACS (`/studio/video/`), executado no Worker/Pod, vídeo confirmado
- [x] 12. I2V real (`image_prompt_type='S'`) confirmado — imagem de referência de fato usada, não descartada
- [x] 13. FLF real (`image_prompt_type='SE'`) confirmado
- [x] 14. Continue real (`image_prompt_type='V'`) confirmado
- [x] 15. LoRA escolhida manualmente pelo usuário: resolvida pra URL real, baixada no Pod, aplicada (log de confirmação real do Wan2GP)
- [x] 16. Confirmado que LoRAs "receita" baked-in por modelo (ex.: 4 LoRAs do `vace_14B_cocktail`) são carregadas sempre pelo Wan2GP, direto do `model_def`, independente de `activated_loras` — nada é perdido quando o usuário não toca no painel de LoRA
- [x] 17. Confirmado o mesmo mecanismo pro LTX2 (`_append_system_lora`: HDR, union-control, outpaint, inpaint, ingredients, id — todos automáticos por flag)
- [x] 18. Diagnosticado erro real do usuário (multi-prompt parsing por linhas em branco) — não é bug, é uso incorreto do formato de prompt
- [x] 19. Diagnosticada causa raiz completa de `RuntimeError: LTX2 LoRA preprocessing dropped ... audio_context, video_context` — lacuna pré-existente em `LORA_CAPABILITIES` do ACS original (não é bug do pipeline remoto) — ver PENDÊNCIA #1 no handoff

## Código e repositório

- [x] 20. Código commitado e enviado (`b053334`, `8d015f2`, `9e4c7c1`) para `origin/claude/jarvis-multimodal-integration-dis74f`
- [x] 21. Nenhum secret, token, modelo, `wan2gp_local/` ou output commitado (`.gitignore` atualizado)
- [x] 22. Working tree limpo ao final da sessão de 2026-09-09

## Pendente — próximas etapas

- [ ] 23. **Resolver PENDÊNCIA #1** (decisão do usuário sobre adicionar `hdr-scene-emb` em `LORA_CAPABILITIES`) — primeira coisa a fazer na próxima sessão
- [ ] 24. Áudio real (TTS / audio-driven generation)
- [ ] 25. Testar modelos fora da família Cinematic Pro/LTX2 (outros modelos Wan de vídeo, modelos de imagem, modelos de áudio)
- [ ] 26. Motion real
- [ ] 27. Resiliência total do túnel SSH (ainda cai ocasionalmente mesmo com keepalive)
- [ ] 28. Bootstrap automático do runtime num Pod novo, do zero (hoje foi tudo manual, reaproveitando um Pod já existente)
- [ ] 29. Arquitetura efêmera completa (criar Pod → preparar → baixar modelos → executar → entregar → destruir) — não é o foco atual, mas é o objetivo final do projeto
