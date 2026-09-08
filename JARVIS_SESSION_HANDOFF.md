# JARVIS AI STUDIO — SESSION HANDOFF

Última atualização: 2026-09-08 (sessão de integração real Studio ↔ RunPod)

## Estado atual

**T2V real e I2V real já funcionam de ponta a ponta, disparados pelo próprio JARVIS Studio, sem mock e sem simulação.**

- T2V real: Studio → CloudWorkerEngine → Worker → Wan2GP → RTX 4090 → MP4 → Gallery. Confirmado com job_id, tempo de geração, tamanho do arquivo, assinatura de MP4 válida e reprodução real no navegador.
- I2V real: mesmo caminho, via preset "Light I2V 8GB" (`model=i2v_nvfp4`), com imagem de referência real (`start_image`) enviada e usada de facto. Job completo, arquivo de saída confirmado em disco.
- O Worker real coexiste no mesmo Pod com o Wan2GP original (Gradio, porta 7860/7862) sem conflito — é a sessão headless documentada da própria API do WanGP (`shared/api.py` → `WanGPSession`/`init()`), não um segundo servidor.
- Nenhuma porta nova foi aberta no RunPod; nenhuma config de nginx/supervisor foi alterada. O Worker reaproveita um proxy que já existia na imagem (rotulado "Dockerless CLI FastAPI Server", `:7270 -> :7271`) e que estava livre.

## Arquitetura atual

```
Windows Studio (frontend :5173 + backend :8000)
        ↓
CloudWorkerEngine (studio/backend/app/engines/cloud_worker/adapter.py)
        ↓
Túnel SSH local (127.0.0.1:7270 -> Pod)
        ↓
nginx do Pod (proxy já existente, :7270 -> :7271)
        ↓
JARVIS Worker (FastAPI, /workspace/jarvis_worker, 127.0.0.1:7271 dentro do Pod)
        ↓
Wan2GP real (/workspace/Wan2GP, deepbeepmeep/Wan2GP upstream)
        ↓
RTX 4090 (24GB VRAM)
        ↓
MP4 real
        ↓
Download para studio/outputs/{job_id}/
        ↓
Gallery do Studio (confirmado visualmente no navegador)
```

## Runtime atual (sem tokens/secrets)

| Item | Valor |
|---|---|
| Wan2GP (path real no Pod) | `/workspace/Wan2GP` (deepbeepmeep/Wan2GP, commit `362c3467a...`) |
| Worker (path real no Pod) | `/workspace/jarvis_worker` (sincronizado de `jarvis_worker/` deste repo) |
| Worker — porta interna no Pod | `127.0.0.1:7271` |
| Proxy nginx do Pod (pré-existente, reaproveitado) | `:7270 -> :7271` |
| Acesso do Studio ao Worker | túnel SSH local: `127.0.0.1:7270` (Windows) → Pod `:7270` |
| Studio backend (local) | `http://127.0.0.1:8000` |
| Studio frontend (local) | `http://localhost:5173` |
| Python/venv do Pod (Wan2GP + Worker) | `/opt/wan2gp-venv` — Python 3.11.15 |
| Python/venv do Studio backend (Windows) | `studio/backend/.venv` — Python 3.14.7 |
| GPU | NVIDIA GeForce RTX 4090, 24564 MiB VRAM |
| Driver / CUDA | Driver 580.178.04 / CUDA 13.0 (torch compilado com cu128) |
| PyTorch (no Pod) | `2.10.0+cu128`, `torch.cuda.is_available()=True` |
| Branch Git | `claude/jarvis-multimodal-integration-dis74f` |
| Commits importantes desta sessão | `ff44258` (fix `JARVIS_WAN_DIR` + doc do deployment real), `12dc4d3` (cache de `health()` no CloudWorkerEngine) |

Token do Worker: existe apenas em `studio/data/jarvis.db` (gitignored) e como variável de ambiente no processo do Worker no Pod. **Nunca foi commitado.**

## O que foi validado

**T2V real:**
- Direto no Worker (`POST /run_task`, `model_type=t2v_1.3B`, 8 steps, 480x272, 17 frames) — baixou pesos reais do Hugging Face (~10GB: T5, VAE, checkpoint), gerou `.mp4` real na GPU.
- Disparado pelo Studio (`engine=wan`, `model=t2v_1.3B`, job `70b341ed-8c61-4490-9d86-03d6ea5ec399`) — pesos já em cache, 9,8s de geração, MP4 de 99.798 bytes com assinatura `ftyp isom` válida, item de Gallery `d491760b-9514-48c3-b7c1-5fc9e9c390a7` confirmado visualmente no navegador (thumbnail real + player tocando).

**I2V real:**
- Disparado pelo Studio via preset "Light I2V 8GB" (`model=i2v_nvfp4`), job `80ad13dd-d059-45bf-8d17-1cab1552bc94`, com imagem de referência real (`start_image`) enviada. Completo em ~118s, MP4 real de 3.249.778 bytes confirmado em disco.

**Infra:**
- Git/GitHub reais (clone, branch, commits, push) — sem simulação.
- SSH real ao Pod, inspeção read-only completa antes de qualquer alteração.
- Nenhum segundo Wan2GP instalado — reaproveitada a instalação existente.
- Cache de `health()` implementado (26 instâncias de `CloudWorkerEngine` compartilham uma conexão; sem cache, `GET /api/engines` levava ~15,7s contra o Worker real).
- `npm run build` do frontend passa limpo.
- Suite de testes do backend (`scripts/test_backend.py`, `scripts/test_cloud.py`) passa nos casos relevantes ao Cloud Worker.

## O que NÃO está pronto

- Audio real
- Motion real
- End Frame real
- Continue real
- LoRA real (aplicação de LoRA através do Worker — `get_capabilities()` do `CloudWorkerEngine` já reporta `lora: False` deliberadamente)
- Presets/workflows completos (200+ workflows importados ainda marcados `executable: False`)
- Image Studio com experiência completa de referências de imagem (ver seção dedicada abaixo)
- Gallery/Assets/Projects completamente integrados (histórico e organização por projeto ainda básicos)
- Bootstrap automático do runtime (hoje foi feito manualmente, passo a passo, num Pod já existente)
- Detecção/download automático de modelos sob demanda (hoje cada modelo baixa na primeira geração; falta uma camada de gestão/pré-checagem no Studio)
- Criação automática do Pod (`RunPodProvider.create_instance` já existe no código, mas não foi exercitado nesta sessão)
- Execução automática de jobs de ponta a ponta sem intervenção manual
- Upload automático dos resultados de volta para o Windows (hoje o download já funciona via `/outputs`, mas não há automação de ciclo completo)
- Auto-destruição do Pod
- Arquitetura efêmera completa (criar → preparar → baixar modelos → executar → entregar → destruir)
- Teste de reconstrução do runtime num Pod novo, do zero

### Pendência registrada: Image Studio — referências de imagem

O Image Studio já lista vários modelos, mas ainda não tem a experiência completa de referências. Registrar como requisito futuro:
- referência de imagem (upload real já funciona no fluxo I2V testado hoje — falta generalizar)
- drag & drop / upload no Image Studio
- capacidade de referência por modelo (nem todo modelo aceita imagem de referência)
- distinguir modelos text-only vs. image-reference
- modelos que aceitam múltiplas referências
- integração correta com o Worker/engine para cada caso
- preservar referências no histórico/projeto
- suporte futuro para até 5 imagens de referência quando o modelo suportar

## Próxima etapa

A próxima etapa imediata é: **AUDIO REAL.**

Depois, nesta ordem:
1. Audio real
2. Motion real
3. End Frame / Continue
4. LoRA real
5. Image References (Image Studio completo)
6. Presets/Workflows completos
7. Bootstrap automático
8. Pod automático (criação)
9. Resultados (execução + upload automático)
10. Auto-destruição do Pod
11. Rebuild test (runtime do zero num Pod novo)
12. Final (arquitetura efêmera completa validada)

## Arquitetura efêmera

O Pod atual (RTX 4090) foi usado **apenas para validar** a integração real — não é para ser preservado indefinidamente. O objetivo final do projeto é não depender de um Pod persistente:

```
criar Pod → preparar runtime → baixar modelos necessários → executar → entregar resultado → destruir Pod
```

Isso ainda não foi implementado nem testado (ver "O que NÃO está pronto"). Quando chegar essa etapa, o teste de reconstrução deve provar que o mesmo runtime pode ser recriado do zero num Pod novo, sem depender do Pod atual.

## Regra importante

**Não recriar outro JARVIS.** Continuar no projeto atual (`motta-ui/JARVIS-RUNPOD-WORKER`, branch `claude/jarvis-multimodal-integration-dis74f`). Há várias pastas antigas no Desktop do Windows (`JARVIS_RUNPOD_WORKER_V1` a `V6`, `JARVIS-AI-STUDIO-...` várias versões) que **não são** este projeto — são zips extraídos de tentativas anteriores, sem `.git`. O projeto real vive em `C:\Users\Emanoel motta\Desktop\JARVIS-RUNPOD-WORKER`.

## Regra importante sobre RunPod

**Não instalar uma segunda cópia de Wan2GP** quando uma instalação existente puder ser reutilizada durante a sessão. O Pod atual já tem Wan2GP real funcionando em `/workspace/Wan2GP` — reaproveitar, nunca duplicar.

## Próxima sessão

Amanhã, antes de qualquer implementação nova:
1. Ler este arquivo (`JARVIS_SESSION_HANDOFF.md`) e `JARVIS_PROGRESS.md`.
2. Verificar o estado do Git (`git status`, `git log`) na branch `claude/jarvis-multimodal-integration-dis74f`.
3. Criar um novo Pod/runtime **somente quando necessário** (o Pod de hoje pode já não existir/estar acessível — o objetivo do projeto é justamente não depender dele).
4. Reconstruir o runtime (Wan2GP + Worker) seguindo exatamente os passos já validados nesta sessão (ver "Runtime atual" e os commits `ff44258`/`12dc4d3`).
5. Continuar a partir de **AUDIO REAL**.
