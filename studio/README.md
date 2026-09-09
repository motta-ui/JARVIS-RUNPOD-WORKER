# JARVIS AI STUDIO — o ACS real, rodando no RunPod

**Atualizado em 2026-09-09.** Este README substitui a versão anterior, que
descrevia uma reimplementação do zero (registry/resolvers próprios) que já
não existe neste branch — preservada em
`backup/studio-reimplementation-before-acs-adoption` caso precise consultar.

## O que é isto de verdade

O JARVIS Studio **é** o ACS Studio real do utilizador (o mesmo produto
instalado em `C:\ACS Unlimited\`) — mesmo backend (`acs_api.py`, 7400
linhas), mesmo frontend real (`/studio/video/`, `/studio/image/`,
`/studio/audio/`, `/studio/motion/`, `/studio/gallery/`, ...). A única
diferença é onde a geração acontece:

```
Windows (sem GPU)                          RunPod (RTX 4090)
──────────────────                         ──────────────────
studio/backend/frontend/  (interface)
        ↓
acs_api.py  (mesmo código do ACS real)
        ↓
acs_wan_client.py  (adaptado — ver abaixo)
        ↓
túnel SSH local :7270 ──────────────────→  nginx :7270 → Worker :7271
                                                              ↓
                                                        Wan2GP real (wgp.py)
                                                              ↓
                                                          RTX 4090
```

O `C:\ACS Unlimited\` real (instalado, licenciado, com Wan2GP LOCAL) continua
intocado e a correr na porta **8010**, se estiver ativo — esta instância de
dev usa a porta **8011** para nunca conflitar.

## Por que o backend é idêntico ao ACS real

`studio/backend/acs_api.py`, `acs_wansession_path.py` e o frontend em
`studio/backend/frontend/` foram copiados diretamente de
`C:\ACS Unlimited\app\` e conferidos byte a byte — são o mesmo código, não
uma reconstrução. Só `acs_wan_client.py` foi genuinamente adaptado, porque o
original assume o Worker na mesma máquina (chamada bloqueante, paths
locais). Ver o cabeçalho desse ficheiro para o histórico completo da
adaptação.

## Licenciamento

Nenhum crack, nenhum bypass escondido. Usa o **modo DEV já documentado no
próprio `acs_api.py`** (`_is_dev_environment()`): três ficheiros/env vars
que o produto real já reconhece como "isto é uma instalação de
desenvolvimento, não vendida":

- `studio/backend/.dev_mode` (sentinel — nunca existe num instalador real)
- `studio/backend/version.json` com `{"channel": "dev"}`
- env var `ACS_DEV_MODE=1`

Nenhum servidor de licença (`license.acsstudio.com`,
`acs-license-backend.onrender.com`) é contactado nesta instância.

## Como arrancar

### 1. Túnel SSH até ao Worker no Pod (precisa disto ANTES do backend)

O túnel morre de vez em quando (idle timeout) — se a geração der
`Nenhuma conexão pôde ser feita`, é quase sempre isto. Reconectar:

```powershell
ssh -i "C:\Users\<user>\.ssh\jarvis_claude" -p <porta_ssh_do_pod> -N `
  -L 7270:127.0.0.1:7270 `
  -o StrictHostKeyChecking=accept-new -o BatchMode=yes `
  -o ServerAliveInterval=20 -o ServerAliveCountMax=3 `
  root@<ip_do_pod>
```

Confirmar: `curl http://127.0.0.1:7270/health` deve devolver
`{"ok":true,"engine":"jarvis-wangp-worker",...}`.

### 2. Variáveis de ambiente + arrancar o backend

```powershell
$env:ACS_USE_WANSESSION = "1"              # ativa o transporte real (não Gradio local)
$env:ACS_WAN_WORKER_PORT = "7270"          # porta do túnel acima
$env:ACS_WORKER_TOKEN = "<token do Worker>" # ver jarvis_worker no Pod / X-Jarvis-Token
$env:ACS_DEV_MODE = "1"
$env:ACS_OUTPUTS_DIR = "studio/backend/outputs"
$env:ACS_WAN2GP_DIR  = "studio/backend/wan2gp_local"   # ver secção abaixo

cd studio/backend
.venv\Scripts\python.exe acs_api.py --port 8011
```

Abrir `http://127.0.0.1:8011/studio/video/` (ou `/studio/index.html` para o
seletor). **A página raiz (`http://127.0.0.1:8011/`) é um protótipo
decorativo** (`index.html` + `app.js`) — as abas lá não mudam nada real, e o
botão GERAR manda sempre um payload fixo de imagem. Usar sempre `/studio/*`.

## `wan2gp_local/` — dados leves copiados do install real (não commitados)

`studio/backend/wan2gp_local/` **não vai para o git** (ver `.gitignore`) —
é local, provisionado a partir de `C:\ACS Unlimited\data\wan2gp\`:

```powershell
$SRC = "C:\ACS Unlimited\data\wan2gp"
$DST = "studio\backend\wan2gp_local"
Copy-Item "$SRC\profiles" "$DST\profiles" -Recurse
Copy-Item "$SRC\loras_url_cache.json","$SRC\loras_url_cache_v2.json","$SRC\envs.json","$SRC\plugins.json" "$DST\"
Copy-Item "$SRC\ffmpeg_bins" "$DST\ffmpeg_bins" -Recurse
```

**Deliberadamente NÃO copiado**: `ckpts/` (~3.2GB de pesos de modelo) e
`models/` (código-fonte do Wan2GP) — inúteis aqui porque esta máquina não
tem GPU; a geração real acontece inteiramente no Worker remoto, que já tem
os seus próprios pesos/código no Pod. Copiar só serviria para preencher o
disco sem nenhum benefício.

O que isto ativa:
- `/loras` mostra o catálogo real de LoRAs (nome → URL Hugging Face) mesmo
  sem nenhum `.safetensors` baixado localmente.
- Remux de áudio local via `ffmpeg_bins/ffmpeg.exe` (operação de CPU, não
  precisa de GPU) para os fluxos que combinam vídeo gerado + áudio.
- Dropdown de presets (`profiles/`) no Video/Image Studio.

## Testado de verdade (via UI real, não só curl)

- T2V, I2V, FLF (start+end frame), Continue — todos via `POST /generate/*`
  com `image_prompt_type` correto por modo (`S`/`SE`/`V` — ver bug abaixo).
- Clicar GERAR na UI real (`/studio/video/`) → job real → download real →
  preview real embutido na página.

### Bug real encontrado e corrigido: `image_prompt_type` ausente

A reimplementação antiga (agora só na branch de backup) nunca setava a
letra `S` em `image_prompt_type`. Sem ela, `wgp.py` **zera `image_start`
por completo** (linha ~1340: `else: image_start = None`) — e sem
`S`/`V`/`L`, a letra `E` (end frame) também é removida (linha ~1344). Ou
seja: gerações "I2V"/"FLF" feitas por esse código antigo **ignoravam
silenciosamente a imagem de referência e rodavam como T2V puro**, mesmo
"completando com sucesso". O `acs_wansession_path.py` real já corrige isto
por construção (`{"i2v": "S", "flf": "SE", "continue": "V", ...}`) — é
literalmente um bug que o próprio changelog do ACS documenta ter
encontrado e corrigido antes.

## Problemas conhecidos / não testados

- Página raiz (`/`) é decorativa, não funcional — ver acima.
- Áudio e Imagem através deste stack (Worker remoto): payload/rota existem
  mas não foram testados ponta a ponta nesta sessão.
- `/loras` e o dropdown de presets dependem de `wan2gp_local/` estar
  provisionado (ver secção acima) — sem isso, ficam vazios (honesto, não
  falsifica catálogo).
- O túnel SSH cai por inatividade de tempos em tempos — usar
  `ServerAliveInterval`/`ServerAliveCountMax` (já na secção 1) reduz isso,
  mas não elimina. Se a geração falhar com erro de conexão, é o primeiro
  sítio a verificar (`curl http://127.0.0.1:7270/health`).
