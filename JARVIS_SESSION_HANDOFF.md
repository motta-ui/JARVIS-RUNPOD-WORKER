# JARVIS AI STUDIO — SESSION HANDOFF

Última atualização: 2026-09-09 (sessão de adoção do ACS real + investigação de LoRAs/utilitários)

**⚠️ Este arquivo substitui por completo a versão de 2026-09-08.** A arquitetura mudou de raiz nesta sessão: a reimplementação do zero (CloudWorkerEngine, `t2v_1.3B`, Studio próprio) foi **abandonada e preservada só como backup** — ver seção "O que mudou" abaixo. O projeto agora roda o **ACS real** (produto comercial do usuário) contra o Worker no RunPod.

## Estado atual — resumo de 1 parágrafo

O backend real do ACS (`studio/backend/acs_api.py`, importado byte-a-byte de `C:\ACS Unlimited\app\acs_api.py`) roda no Windows do usuário, mas em vez de gerar localmente (sem GPU), fala com o Worker (`jarvis_worker/`) que roda no Pod RunPod (RTX 4090) via túnel SSH, e o Worker executa o Wan2GP real (`/workspace/Wan2GP`, upstream `deepbeepmeep/Wan2GP`). Frontend real do ACS também importado (`studio/backend/frontend/`, servido em `/studio/*` — a raiz `/` é um protótipo decorativo, **não usar**). T2V, I2V, FLF (first-last-frame) e Continue já testados de ponta a ponta e reais, no modelo Cinematic Pro (família LTX2). LoRAs do usuário (escolhidas manualmente na UI) e LoRAs "receita" (baked-in em cada `defaults/*.json` do Wan2GP) confirmadas como preservadas corretamente — nada foi simplificado.

## O que mudou nesta sessão (contexto p/ não se perder)

1. Usuário revelou que já tem um produto comercial pronto, o **ACS** (`ACS_NUCLEO.zip`, instalado em `C:\ACS Unlimited\`), e pediu para adotarmos ele de verdade em vez de continuar reimplementando do zero.
2. Estratégia escolhida pelo usuário: (1) fazer backup do trabalho já feito, (2) adotar o ACS real.
3. Backup preservado na branch `backup/studio-reimplementation-before-acs-adoption` (aponta pro commit `af0e44f`). **Não deletar essa branch.**
4. `acs_api.py`, `acs_wan_client.py`, `acs_wansession_path.py` e `frontend/` foram trazidos do ACS real e adaptados minimamente (ver "Modificações feitas no ACS" abaixo) para falar com o Worker remoto em vez de rodar tudo local.
5. Motivo documentado pelo próprio usuário para todo o sistema de LoRAs/utilitários existir: *"rodar só os modelos sozinhos o vídeo não sai legal... criei LoRAs e outros utilitários para imagens, vídeos e áudio pro final sair tudo profissional"* — ou seja, **a exigência #1 do projeto é: nunca simplificar/perder LoRAs ou utilitários de nenhum modelo.**

## Arquitetura atual

```
Windows (sem GPU)
  ACS Studio real — backend (acs_api.py, porta 8011 nesta sessão) + frontend real (/studio/*)
        ↓ (ACS_USE_WANSESSION=1 → acs_wan_client.py → WanClient)
  Túnel SSH local 127.0.0.1:7270 -> Pod
        ↓
  nginx do Pod (proxy pré-existente, :7270 -> :7271, reaproveitado — nunca abrimos porta nova)
        ↓
  JARVIS Worker (FastAPI, /workspace/jarvis_worker, 127.0.0.1:7271 dentro do Pod)
        ↓
  Wan2GP real (/workspace/Wan2GP, deepbeepmeep/Wan2GP, commit 362c3467a)
        ↓
  RTX 4090 (24GB VRAM)
        ↓
  MP4/imagem/áudio real → baixado via /upload-ref (entrada) e /outputs (saída)
```

## Runtime desta sessão (Pod específico — pode não existir mais amanhã)

| Item | Valor |
|---|---|
| Pod usado nesta sessão | `213.173.109.159`, SSH porta `17040` — **verificar se ainda está ativo antes de reusar**; se não, achar o Pod atual no dashboard RunPod |
| Wan2GP (path no Pod) | `/workspace/Wan2GP` |
| Worker (path no Pod) | `/workspace/jarvis_worker` |
| Worker — porta interna | `127.0.0.1:7271` |
| Proxy nginx do Pod (reaproveitado) | `:7270 -> :7271` |
| Log do Worker no Pod | `/workspace/jarvis_worker.log` |
| Token do Worker | variável de ambiente `JARVIS_WORKER_TOKEN` do processo uvicorn no Pod — ler com `cat /proc/<pid>/environ \| tr '\0' '\n' \| grep TOKEN` (pid do `uvicorn app:app --port 7271`, achar com `ps aux`). **Nunca commitado.** |
| ACS backend local (Windows) | porta `8011` nesta sessão (porta `8010` está ocupada por uma cópia real e separada do ACS instalada em `C:\ACS Unlimited\` — **não tocar nela**) |
| Log do ACS local (Windows) | `%TEMP%\acs_apiN.log` (N incrementa a cada restart — usar o mais recente) |
| Env vars necessárias p/ rodar o backend adotado | `ACS_USE_WANSESSION=1`, `ACS_WAN_WORKER_PORT=7270`, `ACS_WORKER_TOKEN=<token do Worker>`, `ACS_DEV_MODE=1`, `ACS_OUTPUTS_DIR=studio/backend/outputs`, `ACS_WAN2GP_DIR=studio/backend/wan2gp_local` (ver `studio/README.md`) |
| Branch Git | `claude/jarvis-multimodal-integration-dis74f` |
| Branch de backup (reimplementação antiga) | `backup/studio-reimplementation-before-acs-adoption` (commit `af0e44f`) |
| Commits importantes desta sessão | `b053334` (adoção do ACS real), `8d015f2` (provisiona `wan2gp_local/`, reescreve README), `9e4c7c1` (resolve URLs de LoRA + log de settings finais) |

## Modificações feitas no ACS real (todas mínimas e aditivas)

- `acs_api.py`: chamada a `_upload_local_files()` logo após `build_core_settings()` (~linha 5999-6003) para subir arquivos locais (imagem/vídeo/áudio de referência) ao Worker antes de gerar — sem isso, o Worker recebia paths do Windows e dava `FileNotFoundError`.
- `acs_api.py`: resolução de `activated_loras` (filename → URL real via `_LORAS_URL_CACHE`) logo depois (~linha 6004-6024) — sem isso, o Worker recebia só o nome do arquivo e não sabia de onde baixar.
- `acs_api.py`: log de debug antes de `WAN.generate()` imprimindo as configs de qualidade/utilitários enviadas (RIFLEx, self refiner, spatial upsampling, film grain, prompt enhancer, LoRAs) — usado pra verificação, pode manter.
- `acs_wan_client.py`: adaptado de `http://127.0.0.1:7872` (Gradio local) pra falar com o Worker via `X-Jarvis-Token`, com upload/download e polling assíncrono de `/run_task`.
- `acs_wansession_path.py`: adicionada `_upload_local_files()` (função auxiliar, chamada pelo `acs_api.py` acima).
- `.dev_mode` + `version.json` (`channel: dev`): ativam o bypass de licença **legítimo e já existente no próprio ACS** (não é hack — é um modo dev documentado no próprio código, sem phone-home).

**Nada na lógica de negócio original (workflows, LoRAs, utilitários, validações, `LORA_CAPABILITIES`) foi alterado.** Só a camada de transporte (onde os bytes são gerados) foi trocada de local pra remota.

## O que foi validado de verdade nesta sessão

- **T2V/I2V/FLF/Continue reais**, família Cinematic Pro (LTX2), disparados pela UI real do ACS (`/studio/video/`), executados no Worker/Pod, vídeo final baixado e confirmado.
- **`image_prompt_type` correto por modo** (`S`=i2v, `SE`=flf, `V`=continue) — bug crítico que existia na reimplementação antiga (perdia `image_start`/`image_end` silenciosamente) **não existe** no ACS real; `acs_wansession_path.py::build_core_settings()` já mapeia certo.
- **LoRA escolhida manualmente pelo usuário**: resolvida pra URL real, baixada no Pod (~6s pra 1,23GB via link direto, vs 74s+ que levaria no Windows), aplicada de fato (log `Lora '...' was loaded in model ...` confirmado).
- **LoRAs "receita" baked-in de cada modelo** (ex.: as 4 LoRAs do `vace_14B_cocktail`/Studio Editor, multiplicadores `[1,0.5,0.5,0.5]`): confirmado via leitura direta do `wgp.py` (linha ~7028) que são carregadas **sempre**, direto do `model_def`, **independente** do que vem em `activated_loras` — não são perdidas mesmo que o Worker reporte `activated_loras: []` no `/default_settings`. Mecanismo confirmado também pro LTX2 (`_append_system_lora` em `models/ltx2/ltx2.py:1244`, aplica HDR/union-control/outpaint/inpaint/ingredients/id automaticamente conforme flags).
- **Multi-prompt parsing**: erro real do usuário (`multi_prompts_gen_type='PG' parses this prompt into 11 separate generation requests`) diagnosticado como uso incorreto (linhas em branco no prompt viram seções separadas) — não é bug, é comportamento documentado do Wan2GP (`shared/utils/prompt_parser.py`).
- **Bug real encontrado e diagnosticado (não corrigido, ver "Pendência #1" abaixo)**: `RuntimeError: LTX2 LoRA preprocessing dropped 2 unmatched keys for model 'ltx2_22B': audio_context, video_context` — causa raiz 100% identificada, confirmada **pré-existente no ACS original** (`C:\ACS Unlimited\app\acs_api.py`, mesmas linhas), não é bug introduzido pelo pipeline remoto.

## PENDÊNCIA #1 — decisão do usuário, retomar amanhã exatamente aqui

**Contexto completo do bug (para não precisar reinvestigar):**

O usuário selecionou manualmente, no painel de LoRAs da UI real, a combinação `ic-lora-union-control-ref0.5` + `ic-lora-hdr-scene-emb` (sem configurar `video_prompt_type`). A LoRA `ic-lora-hdr-scene-emb.safetensors` é documentada no próprio código do ACS (`acs_api.py` linha 2174-2176) como **"Componente do HDR Cinematic — aplicado automaticamente"** — ou seja, não deveria ser selecionável isolada. Ela só funciona quando `video_prompt_type` recebe o caractere `&` (`VIDEO_PROMPT_HDR_OUTPUT_FLAG`, confirmado em `shared/utils/hdr.py:13`), que ativa o branch de condicionamento `audio_context`/`video_context` no transformer do LTX2.

O ACS tem um guard real (`LORA_CAPABILITIES`, `acs_api.py` ~linha 5240) que faz auto-payload dessa flag — **mas só está cadastrado pro arquivo `ltx-2.3-22b-ic-lora-hdr-0.9.safetensors`** (linha 2271), não pro `ic-lora-hdr-scene-emb.safetensors` que o usuário escolheu. Por isso o guard não dispara, a flag não é setada, e o Wan2GP recusa corretamente a combinação com o erro acima.

**Confirmado byte-a-byte**: essa mesma lacuna existe em `C:\ACS Unlimited\app\acs_api.py` (instalação original, local, sem RunPod) — mesmas linhas. **Não é bug do pipeline remoto, é uma lacuna pré-existente no ACS original.**

**Pergunta feita ao usuário, ainda sem resposta**: adicionar uma entrada de `LORA_CAPABILITIES` para `ic-lora-hdr-scene-emb` (mesmo auto-payload da `hdr-0.9`), fechando a lacuna também no ACS original — ou manter 100% idêntico ao original (aceitando essa limitação como está, já que a exigência do usuário é paridade exata)?

**Ação de amanhã**: perguntar ao usuário essa decisão pendente antes de qualquer outra coisa relacionada a LoRAs, e agir de acordo com a resposta.

## O que ainda NÃO foi testado

- Áudio real (TTS, audio-driven generation)
- Modelos fora da família Cinematic Pro/LTX2 (outros modelos de vídeo Wan, modelos de imagem, modelos de áudio)
- Motion real
- Reconexão do túnel SSH após queda (mitigado com `-o ServerAliveInterval=20 -o ServerAliveCountMax=3`, mas ainda cai ocasionalmente — usuário já teve 2 quedas reais nesta sessão)
- Bootstrap automático do runtime num Pod novo do zero (o Pod desta sessão foi montado manualmente, passo a passo)
- Criação/destruição automática de Pod (arquitetura efêmera completa, ver README antigo — ainda não é o foco atual)

## Regras importantes (não esquecer)

- **Não recriar outro JARVIS.** Projeto real vive em `C:\Users\Emanoel motta\Desktop\JARVIS-RUNPOD-WORKER`. Pastas antigas no Desktop (`JARVIS_RUNPOD_WORKER_V1-V6` etc.) não são este projeto.
- **Não tocar na instalação separada `C:\ACS Unlimited\`** — é o produto real do usuário, rodando com processo próprio na porta 8010. Usamos ela só como referência de leitura (comparação de código), nunca modificamos nem paramos.
- **Nunca simplificar workflows/LoRAs/utilitários por modelo.** Essa é a exigência #1, repetida várias vezes pelo usuário. Qualquer mudança nessa área precisa ser validada contra o `acs_api.py` original antes de ir pra produção.
- **Nunca commitar**: tokens, `wan2gp_local/` (dados locais, ~300MB+), outputs, `.env`.
- Raiz `/` do frontend é decorativa — a UI real fica em `/studio/*`.

## Próxima sessão — checklist de retomada

1. Ler este arquivo e `JARVIS_PROGRESS.md`.
2. `git status` / `git log` na branch `claude/jarvis-multimodal-integration-dis74f` — deve estar limpo (estava limpo ao final desta sessão, tudo commitado e no push).
3. Resolver a **PENDÊNCIA #1** com o usuário (decisão sobre `LORA_CAPABILITIES`/`hdr-scene-emb`) antes de seguir.
4. Verificar se o Pod `213.173.109.159:17040` ainda existe; se não, localizar o Pod atual e resubir o túnel SSH + confirmar `/health` do Worker.
5. Resubir o ACS backend local (env vars da tabela acima) e confirmar `/studio/video/` funcionando de ponta a ponta antes de continuar.
6. Depois disso, seguir pra o que ainda não foi testado (lista acima) — sugestão: áudio real, depois outros modelos fora do LTX2.
