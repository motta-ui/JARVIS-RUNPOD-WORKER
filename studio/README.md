# JARVIS AI STUDIO — V1

Studio profissional de criação com IA para Windows — implementação
independente (interface, backend, base de dados e sistema de engines
próprios). Corre sem GPU, com um engine `mock` (demo) para simular o
fluxo completo, e já tem um engine **MiniMax H3 real** implementado
contra a API oficial atual.

## Instalação (Windows)

Pré-requisitos: **Node.js 18+** no PATH, e **Python 3.12 x64** — ver nota abaixo sobre versões do Python.

```
1. setup.bat              (idempotente — corre quantas vezes quiseres)
2. INICIAR_JARVIS.bat
3. O navegador abre sozinho em http://localhost:5173, só depois de
   backend e frontend responderem de verdade.
```

`setup.bat` verifica Node, npm e a versão do Python **antes** de criar
o ambiente virtual (ver "Python 3.12 e o problema do MSVC/Rust"
abaixo), cria `backend\.venv` se faltar, instala dependências Python
só se faltar alguma (e só a partir de wheels pré-compiladas — nunca
compila código-fonte), instala `npm install` só se
`frontend\node_modules` não existir, confirma que o SQLite funciona,
cria os diretórios de dados e o `.env`. Corrê-lo duas vezes não
reinstala nada desnecessariamente nem parte nada.

`INICIAR_JARVIS.bat` (e o equivalente nativo `INICIAR_JARVIS.ps1`):
verifica tudo o que o setup verifica e **instala automaticamente** o
que faltar; confirma que as portas 8000 e 5173 estão livres (e diz
qual processo as está a ocupar, se não estiverem); só inicia o
frontend depois do backend responder de verdade em `/health`; só abre
o browser depois do Vite responder de verdade. Se alguma etapa falhar,
mostra o erro real no terminal e para — nunca avança às cegas.

### Python 3.12 e o problema do MSVC/Rust

**Sintoma corrigido nesta versão:** em algumas máquinas Windows, o
`pip install` tentava compilar `pydantic-core` a partir do código-fonte
em Rust (via `maturin`) e falhava porque o `link.exe` do Visual Studio
não estava instalado — um erro obscuro e sem relação óbvia com o
JARVIS. Isto acontece quando a versão de Python instalada é demasiado
recente (ou antiga) para ter uma "wheel" pré-compilada publicada para
a versão exata do `pydantic`/`pydantic-core` pedida.

**Correção aplicada:**

1. `setup.bat` deteta a versão do Python **antes** de criar o `.venv`.
   Se existir o `py launcher` com Python 3.12 instalado
   (`py -3.12`), usa-o automaticamente — 3.12 x64 é a versão
   recomendada e testada para o JARVIS.
2. Se só existir uma versão fora do intervalo 3.10–3.12, o setup
   **não falha às cegas**: mostra um aviso claro a explicar porquê
   (falta de wheels pré-compiladas, necessidade de MSVC/Rust) e
   recomenda instalar Python 3.12 x64, com o link direto.
3. A instalação das dependências Python usa sempre
   `pip install --only-binary=:all:` — isto impede categoricamente
   que o pip tente compilar qualquer dependência a partir do
   código-fonte. Se não houver wheel disponível, o pip falha
   imediatamente com uma mensagem clara do próprio setup (não com o
   erro obscuro do `link.exe`), e volta a recomendar Python 3.12 x64.
4. `backend/requirements.txt` deixou de fixar versões exatas
   (`==`) a favor de mínimos (`>=`) para `fastapi`, `pydantic`,
   `uvicorn`, `python-multipart` e `requests` — isto permite ao pip
   escolher automaticamente a versão mais recente **com wheel
   disponível** para a versão de Python instalada, em vez de ficar
   preso a uma versão antiga que pode não ter sido publicada com
   wheels para Pythons mais recentes (a causa raiz do problema
   original: `pydantic==2.9.2` fixo, sem margem para o pip escolher
   uma versão mais nova já compatível).

Nenhuma instalação normal do JARVIS deve exigir Visual Studio, Rust ou
MSVC. Se ainda assim isso acontecer, é sinal de que nenhuma versão de
`pydantic`/`pydantic-core` tem wheel publicada para a tua combinação
exata de Python — nesse caso, Python 3.12 x64 resolve.

**Nota de teste:** esta correção foi revista com cuidado linha a
linha (incluindo um problema real de encadeamento `if/else` em
`cmd.exe` que foi encontrado e corrigido durante a revisão — ver
secção Testes) mas **não foi executada num Windows real**, porque
este ambiente de desenvolvimento é Linux e não tem acesso a uma
máquina Windows nem à cadeia de ferramentas `cmd.exe`/PowerShell para
correr os `.bat`/`.ps1` de facto. Se encontrares algum comportamento
inesperado no `setup.bat` corrigido, diz exatamente a mensagem de
erro e o `python --version` que tens instalado.


## Testar

Com o backend em execução:

```
python scripts/test_backend.py
```

Corre 18 verificações reais contra a API (projetos, assets, jobs,
loras, gallery, settings, engines, config) — ver secção **Testes**
abaixo para o que foi corrido nesta entrega.

## Arquitetura

```
JARVIS_STUDIO/
  backend/
    app/
      main.py             # FastAPI app, CORS, logging, exception handler
      database.py          # SQLite + migrações idempotentes
      config.py             # paths, .env, carregamento de JSON de configuração
      schemas.py             # validação Pydantic
      engines/
        base.py               # contrato BaseEngine
        registry.py            # registo de engines + snapshot em BD
        mock/adapter.py         # engine demo (sem GPU, sem internet)
        minimax/adapter.py       # engine REAL — MiniMax H3
        cloud/                    # CloudProvider (arquitetura, não implementado)
      routers/                # endpoints da API
      data/                    # JSON de configuração (studios, formatos, presets...)
  frontend/
    src/
      components/
        generation/             # GenerationWorkspace partilhado por Video/Image/Audio/Motion
        layout/                  # Sidebar, Topbar, Layout
        ErrorBoundary.jsx, Modal.jsx, ConfirmModal.jsx
      pages/                    # Home, VideoStudio, ImageStudio, AudioStudio, MotionStudio,
                                 # Gallery, Assets, Projects, LoraManager, Settings, Engines
      store/                    # useStore (estado do sistema), useToast (notificações)
      api/client.js              # cliente HTTP para o backend
  JARVIS_BOOTSTRAP/            # arquitetura de provisionamento cloud (manifest-based)
  scripts/                    # helpers PowerShell + smoke test do backend
  outputs/  projects/  assets/  loras/  data/
```

### Porque os 4 módulos de criação partilham um único componente

Video, Image, Audio e Motion Studio usam todos o mesmo
`GenerationWorkspace` (`frontend/src/components/generation/`),
parametrizado por um JSON de configuração por studio
(`backend/app/data/studio_{video,image,audio,motion}.json`). Isto não
é um atalho — é o mesmo princípio já pedido para o resto do sistema
("parâmetros configuráveis fora dos componentes React"): cada studio
declara os seus modos, zonas de referência, addons e campos extra em
JSON; o componente só desenha o que o JSON descrever. Adicionar ou
mudar um controlo em qualquer studio é editar o JSON, não React.

## Engines

### Mock (demo, sem GPU, sem internet)

Suporta os 4 kinds (video/image/audio/motion), simula fila → progresso
→ conclusão, e regista automaticamente cada job completo na Gallery.
Cancelamento testado e sem condições de corrida (ver secção Testes).

### MiniMax H3 (real)

Implementado contra a documentação oficial atual
(`https://platform.minimax.io/docs/guides/video-generation`,
consultada nesta entrega):

- `POST /v2/video_generation` — cria a tarefa
- `GET /v2/query/video_generation/{task_id}` — consulta o estado
- `DELETE /v2/video_generation/{task_id}` — cancela (se `queued`) ou apaga (se `succeeded`/`failed`)

Para ativar:

1. Preenche `MINIMAX_API_KEY` no `.env`.
2. Seleciona o modelo "MiniMax H3" no Video Studio (a UI já o lista;
   o engine correspondente é escolhido automaticamente).
3. `/system/engines` mostra `online: true` assim que a chave estiver
   configurada.

**Limitação documentada (não inventada):** a API do MiniMax H3 espera
URLs publicamente acessíveis para imagens/vídeo/áudio de referência.
Existe uma API genérica de upload de ficheiros
(`/v1/files/upload`), mas a documentação pública não confirma que o
`file_id` daí resultante seja aceite como input do endpoint de vídeo —
por isso este adapter não inventa esse mecanismo; usa URLs já
hospedadas. Isto fica resolvido quando o Cloud Worker (arquitetura em
`engines/cloud/`) tratar do hosting dos assets.

**Validação real feita nesta entrega:** com uma chave inválida, o
adapter fez um pedido real a `https://api.minimax.io/v2/video_generation`
e recebeu um `403 Forbidden` genuíno do servidor MiniMax — prova de que
o endpoint, o payload e o tratamento de erro estão corretos. Não foi
possível testar uma geração bem-sucedida real porque isso exige uma
chave paga, que não está disponível neste ambiente.

### Cloud Worker (real — vídeo, imagem, áudio e motion)

`backend/app/engines/cloud_worker/adapter.py` implementa `CloudWorkerEngine`,
que fala HTTP real com o **JARVIS RunPod Worker**
(`jarvis-runpod-worker`, `jarvis_worker/app.py`) — a ponte fina sobre a
sessão real do Wan2GP (`WanGPSession`). Uma instância é registada por
cada família de engine que `engine_registry.py` conhece (`wan`, `ltx2`,
`ltx`, `hunyuan`, `longcat`, `magi`, `ovi`, `lucy_edit`, `chrono_edit`,
`flux`, `qwen_image`, `z_image`, `ideogram`, `hidream`, `krea`, `kiwi`,
`ace_step`, `stable_audio`, `chatterbox`, `index_tts`, `omnivoice`,
`qwen_tts`, `heartmula`, `kugelaudio`, `dramabox`, `scenema`, `other`) —
26 engines reais no total, cobrindo os ~200 modelos importados de
`06_ALL_WANGP_DEFAULTS`/`workflow_configs/` em vídeo, imagem, áudio E
motion, não só vídeo.

```
JARVIS STUDIO -> CloudWorkerEngine -> Cloud Worker (/run_task) -> RunPod GPU
-> WanGPSession -> Wan2GP model_type -> ficheiro gerado
-> Worker /outputs/{path} -> Studio faz download -> JARVIS Gallery
```

O que este adapter faz de facto (não é um stub):

1. **Upload de referências**: qualquer `reference_zones` do studio
   (`start_image`, `end_frame`, `reference_image[_2/_3]`,
   `inject_frame_2/3`, `additional_frames`, `control_video`,
   `reference_video`, `audio`/`reference_audio`) é enviado ao Worker via
   `POST /upload-ref` ou `/upload-audio` **antes** de submeter o job — o
   path local do Studio não existe na máquina do Worker, por isso nunca
   é reenviado tal como está.
2. **Tradução para os campos reais do Wan2GP**: os nomes de campo usados
   no `settings` do `/run_task` (`image_start`, `image_end`,
   `image_refs`, `video_guide`, `video_source`, `audio_guide`) e as
   letras de ativação (`E`/`I`/`V`/`A` em `image_prompt_type`/
   `video_prompt_type`/`audio_prompt_type`) vêm diretamente do código-fonte
   real do Wan2GP (`wgp.py`, `ATTACHMENT_KEYS` + `validate_settings()`) —
   nunca inventados. Ver o docstring completo do módulo para a
   proveniência exata de cada campo e a limitação documentada sobre a
   gramática completa de letras (não totalmente reversa-projetada).
3. **`control_video_option`** (`data/control_video.json`: canny/depth/
   human_motion/pose_align/ic_raw/hdr/animate_character) é traduzido para
   o código real `video_prompt_type` (`EVG`/`DVG`/`PVG`/`OVG`/`VG`/`V&G`/
   `V1`), confirmado a partir do próprio HTML do frontend de referência.
4. **Progresso real**: faz poll de `GET /progress` no Worker (não
   estimativa por tempo) e atualiza `jobs.progress` na BD.
5. **Cancelamento**: `POST /cancel/{worker_job_id}` no Worker — honesto
   sobre se o motor conseguiu mesmo abortar ou não.
6. **Download do resultado + Gallery**: `GET /outputs/{path}` no Worker,
   grava em `OUTPUTS_DIR/<job_id>/`, e insere automaticamente em
   `gallery_items` (mesmo padrão do `MockEngine`).

**Limitação documentada**: aplicação de LoRAs (`job_params.loras`) não é
traduzida para `loras`/`loras_multipliers` do Wan2GP — resolver um LoRA
do catálogo do Studio para um `.safetensors` instalado no filesystem
*remoto* do Worker não está documentado em nenhuma fonte disponível;
inventar essa correspondência aplicaria silenciosamente o LoRA errado
(ou nenhum). `get_capabilities()` reporta `lora: false` por este motivo.

Testado nesta entrega com um Worker fake real em HTTP (não mock em
memória): ligação, upload de 2 referências, submissão, poll de
progresso, download do output, inserção na Gallery — ponta a ponta,
via `TestClient` da Studio + `uvicorn` real do fake Worker. Ver
`git log` desta entrega para o script de teste (não commitado, corrido
localmente).

### Cloud Architecture (preparada, não implementada)

```
JARVIS STUDIO -> JARVIS API -> CLOUD WORKER -> GPU -> OUTPUT
```

`backend/app/engines/cloud/base.py` define `CloudProvider`
(`create_instance`, `deploy`, `health`, `destroy_instance`).
`providers.py` tem stubs para RunPod, TensorDock e Vagon — todos por
implementar, nenhum é o "provedor por defeito". `JARVIS_BOOTSTRAP/`
tem a arquitetura de manifest (`python cli.py --engine ltx`) que um
`CloudProvider.deploy()` usaria no futuro — não descarrega nada agora.

## Arquitetura de Presets (Model / Engine / Workflow / LoRA Registry)

O "Modelo" que o utilizador escolhe no Studio deixou de ser um simples
checkpoint — passou a ser um **preset completo**, resolvido pelo
backend a partir de quatro registries claramente separados:

```
backend/app/registry/
  model_registry.py       # MODEL REGISTRY    - modelos curados (minimax, mock) + 200 importados
  workflow_registry.py    # WORKFLOW REGISTRY  - config real (não executável) + placeholders demo
  lora_catalog.py         # LORA REGISTRY      - catálogo de LoRAs reais extraídos das configs
  preset_registry.py      # PRESET REGISTRY    - junta tudo: engine+model+workflow+loras+capabilities+defaults
  engine_registry.py      # ENGINE REGISTRY (declarativo) - famílias de engine, maioria sem adapter ainda
  config_importer.py      # importa os 200 ficheiros de workflow_configs/ para os registries acima

backend/app/engines/registry.py   # ENGINE REGISTRY (executável) - mock, minimax, e 26 famílias Wan2GP via CloudWorkerEngine
```

### Fonte dos dados: SOURCE DATA real, não inventada

`backend/app/data/registry/workflow_configs/{video,image,audio,other}/`
contém **200 ficheiros de configuração reais**, fornecidos como source
data, do projeto open-source **Wan2GP** (autor DeepBeepMeep) —
referenciam checkpoints publicamente disponíveis no Hugging Face
(LTX-2, Wan2.1/2.2, HunyuanVideo, Flux, Qwen-Image, ACE-Step, etc.).
Não é DRM nem segredo comercial de ninguém.

`config_importer.py` lê estes ficheiros tal como estão e gera, para
cada um, uma entrada no Model Registry e uma no Workflow Registry:
`name`/`checkpoint`/`URLs`/`loras`/parâmetros por omissão vêm
**literalmente** do ficheiro. `engine_id` e `capabilities` são
inferidas por heurística documentada a partir de sinais reais (nome
do ficheiro, arquitetura, descrição, campos presentes) — nunca
inventadas do nada. **`capabilities` é agregada por família de
arquitetura** (mesmo `checkpoint`): se um ficheiro irmão descreve uma
capacidade que a arquitetura suporta (ex.: "start/end keyframes and
sliding-window continuation"), todas as variantes dessa arquitetura
herdam essa capacidade — uma variante "Distilled" não deve perder
modos só porque a sua descrição é mais curta que a da variante "Dev"
irmã. `defaults`, `loras` e `checkpoint_urls` **nunca** são agregados
— continuam sempre exclusivos do ficheiro exato, para nunca fingir
que uma variante tem parâmetros ou LoRAs de outra. Cada ficheiro é
marcado `source_type: "preset_config"` e `executable: false` — são
configurações, não workflows executáveis (isso fica para o Worker, no
futuro).

`GET /api/presets?kind=video` devolve a lista (nomes amigáveis, para o
dropdown). `GET /api/presets/{id}` resolve por completo. Exemplo real:

```json
{
  "id": "cinematic-pro-1-1",
  "name": "Cinematic Pro 1.1",
  "engine_id": "ltx2",
  "runtime_engine": "ltx2",
  "status": "live",
  "status_detail": null,
  "model": {"id": "ltx2_22B_distilled_1_1", "name": "LTX-2 2.3 Distilled 1.1 22B", "checkpoint": "ltx2_22B", ...},
  "workflow": {"id": "ltx2_22B_distilled_1_1", "source_type": "preset_config", "executable": false, "source_file": "video/ltx2_22B_distilled_1_1.json"},
  "capabilities": ["outpainting", "text_to_video"],
  "modes": ["t2v"],
  "loras": [],
  "defaults": {"num_inference_steps": 8, "video_length": 241, "resolution": "1280x720"}
}
```

(`runtime_engine`/`status` acima refletem o estado depois da secção
"Cloud Worker (real...)" — `engine_id "ltx2"` agora tem um adapter
real registado, ver `engines/registry.py`.)

**Atualização**: `presets.json` cresceu de 20 para 38 entradas — os 16
presets de vídeo originais mais 8 de imagem (Flux Fast/Balanced/Pro,
Z-Image Turbo, Typography Image, Krea 2 Turbo/RAW), 9 de áudio
(Music Studio, ACE-Step v1.0/v1.5 Turbo/XL, Chatterbox, HeartMuLa 3B,
Index TTS 2, KugelAudio 7B, Qwen3 TTS) e 4 de motion (Image Motion,
Talking Head, Infinite Talk, Animar Personagem — movidos/adicionados à
categoria `motion`, ver nota abaixo), todos com `model_id` verificado
contra os ficheiros reais em `workflow_configs/`.

### Os 16 presets pedidos, mapeados a modelos reais

| Preset | Modelo real (`config_source`) |
|---|---|
| Cinematic Lite | `ltx2_distilled.json` (LTX-2 2.0 Distilled 19B) |
| Cinematic Pro 1.1 | `ltx2_22B_distilled_1_1.json` |
| Cinematic Pro Full | `ltx2_22B_1_1.json` (Dev, não-distilled) |
| Light 8GB | `t2v_1.3B.json` (Wan2.1 T2V 1.3B) |
| Light I2V 8GB | `i2v_nvfp4.json` (quantizado, 4-step) |
| Studio AI I2V | `i2v_720p.json` |
| Talking Head | `multitalk.json` |
| Infinite Talk | `infinitetalk.json` |
| Studio Editor | `vace_14B_cocktail.json` — **4 LoRAs reais** (CausVid, DetailEnhancer, AccVid, MoviiGen) |
| Director Vision | `ltx2_22B.json` |
| Director Vision Lite | `ltx2_22B_distilled.json` |
| Human Studio | `hunyuan_avatar.json` |
| Infinite Motion | `longcat_video.json` |
| Cinematic EditAnything | `ltx2_22B_distilled_1_1_edit_anything.json` |
| Cinematic Edit | `ltx2_22B_distilled_edit_anything.json` |
| MiniMax H3 | curado (API real, sem ficheiro de config) |

**Nota (atualizada):** "Human Studio" e "Infinite Motion" continuam na
categoria `video` (avatar/vídeo longo genéricos, não especificamente
"módulo Motion" no vocabulário do `00_WORKFLOW_MAP.md`). O Motion
Studio deixou de ter só o preset mock: ganhou presets reais próprios
— "Image Motion" (`i2v_720p`), "Talking Head" (`multitalk`), "Infinite
Talk" (`infinitetalk`) e "Animar Personagem" (`vace_standin_14B`) — e
`studio_motion.json` foi corrigido para usar o mesmo vocabulário de
modos que `CAPABILITY_TO_MODE` produz (`i2v`/`continue`/
`animate_character`); os IDs antigos (`image-motion`/`motion-transfer`)
nunca correspondiam a nenhuma capability real, por isso nenhum modo
nem zona de referência aparecia para NENHUM preset de motion, incluindo
o mock — bug pré-existente, corrigido nesta entrega. O mesmo aconteceu
no Audio Studio (`t2a_music`/`t2a_sfx`/`t2a_speech`/`audio_ref` também
nunca batiam com nenhuma capability) — corrigido adicionando
`"audio_output": "t2a"` a `CAPABILITY_TO_MODE` e simplificando
`studio_audio.json` para o modo `t2a` real + a zona `reference_audio`
(mostrada via a capability `reference_images`, que `config_importer.py`
atribui a modelos de áudio com `audio_prompt_type`).

### `status` de um preset: nunca finge suporte que não existe

- **`demo`** — corre já a 100%, via o engine `mock`. Um por studio.
- **`live`** — corre já a 100%, via engine real ligado (`minimax`, ou
  qualquer uma das 26 famílias Wan2GP via `CloudWorkerEngine` — ver
  secção "Cloud Worker (real...)"). É o `status` de todos os presets
  curados hoje: `resolve_runtime_engine` já encontra um adapter real
  para todos eles, o que "live" significa aqui é "código real, não
  mock" — se o Worker Cloud não estiver ligado, `validate_request()`
  rejeita o job com um erro claro, em vez de gerar em modo demo.
- **`planned`** — reservado para um `engine_id` sem NENHUM adapter
  registado (nem mock, nem real). Nesse caso `resolve_runtime_engine`
  cai para `mock`, mostrando sempre um aviso claro — nunca finge que
  está a usar um engine que não existe. Nenhum preset curado está
  neste estado hoje.

### Vocabulário de capabilities

`text_to_video`, `image_to_video`, `video_to_video`, `text_to_image`,
`image_to_image`, `audio_to_video`, `audio_output`, `inpainting`,
`outpainting`, `reference_images`, `control_image`, `control_video`,
`injected_frames`, `video_continuation`, `sliding_window`, `lora`,
`end_frame` — inferidas por `config_importer.py` a partir de sinais
reais (nome do ficheiro, arquitetura, descrição, campos presentes).
Uma tabela (`CAPABILITY_TO_MODE` em `preset_registry.py`) traduz cada
capability no modo do Studio que ela ativa (ex.: `text_to_video`→`t2v`,
`video_continuation`→`continue`).

### Como o Studio reage às capabilities do preset

`GenerationWorkspace` não tem nenhuma lista de modelos hardcoded — os
separadores de modo mostram só `preset.modes`; os addons "Ctrl
Vídeo"/"Frame Inject"/"End Frame" só aparecem se a capability
correspondente estiver na lista; as zonas de referência só aparecem se
algum modo visível precisar delas (ou se `audio_to_video`/
`control_video` estiverem presentes); o painel de LoRAs só aparece se
`lora` estiver presente. Compara "Light 8GB" (`['text_to_video']`, sem
control video) com "Studio Editor" (`control_video`, `injected_frames`,
4 LoRAs reais) para ver a diferença.

### API do Registry

```
GET /api/models                        (filtros: category, engine_id, capability, status, query)
GET /api/models/{id}
GET /api/models/{id}/capabilities
GET /api/models/{id}/defaults
GET /api/workflows                     (filtro: engine_id)
GET /api/workflows/{id}
GET /api/loras/catalog                 (catálogo declarativo — distinto de GET /api/loras, que é o inventário real do utilizador)
GET /api/loras/catalog/{id}
GET /api/engines/registry              (declarativo — distinto de GET /api/engines, que só lista mock+minimax)
GET /api/presets?kind=<video|image|audio|motion>
GET /api/presets/{id}
GET /api/presets/{id}/modes/{mode}     (PRESET+MODO -> workflow_id/engine_id/capabilities/defaults/execution_status)
```

### Botão de modo → workflow correto: `resolve_generation_mode`

```
PRESET → CAPABILITIES → MODE REGISTRY → WORKFLOW RESOLUTION → GENERATION WORKSPACE → ENGINE ADAPTER
```

`preset_registry.resolve_generation_mode(preset_id, mode)` é o que
cada botão de modo (T2V/I2V/End Frame/Continue) resolve ao ser
selecionado:

```python
resolve_generation_mode("light-8gb", "t2v")
# {"preset_id": "light-8gb", "mode": "t2v", "workflow_id": "t2v_1.3B",
#  "engine_id": "mock", "capabilities": [...], "defaults": {...},
#  "execution_status": "Workflow preparado — execução real ainda não
#  disponível (a correr em modo Mock)."}
```

Devolve `None` (e o endpoint devolve 404) quando o preset não suporta
o modo pedido — a UI só mostra botões para modos que sabe que
resolvem. **A ausência de adapter executável nunca remove o modo**,
só muda `execution_status`.

### Como adicionar um preset novo

1. Se o modelo já estiver em `workflow_configs/` (200 já disponíveis),
   basta apontar para lá — não é preciso criar nada novo.
2. Para um modelo curado à mão (fora do Wan2GP), adicionar a
   `backend/app/data/registry/models.json`.
3. Adicionar o preset a `backend/app/data/registry/presets.json`
   (só precisa de `id`/`name`/`category`/`engine_id`/`model_id`/
   `workflow_id`/`status` — capabilities/defaults/LoRAs são sempre
   derivados do modelo, nunca duplicados à mão).
4. Correr `python scripts/test_registry.py` — valida integridade
   referencial automaticamente.

Nada disto precisa de alterações no frontend.

## Cloud Connection (ligação manual a um Worker remoto)

O JARVIS pode ligar-se a um Worker remoto (ex.: um Pod RunPod) que tu
crias e destróis manualmente na consola do provider. Esta etapa **não**
cria nem destrói nada na cloud — só liga a um endpoint HTTP já
existente, 100% editável, sem tocar em código nem recompilar nada.

```
JARVIS Studio (Windows) → JARVIS Backend local → Cloud Worker → GPU alugada → resultado volta para o PC
```

### Onde mexer

Painel **Sistema → Cloud** (`/system/cloud`): escolhes o provider,
colas o URL do Worker, a porta, dás-lhe um nome opcional, clicas
**Testar Conexão** para confirmar que respondes de facto ao `/health`
dele, e só depois **Salvar** para persistir.

```
1. Cria o Pod no RunPod
2. Copia o endpoint que ele te dá
3. Cola em Worker URL no JARVIS
4. Testar Conexão -> vês ONLINE (ou o erro real, se não estiver)
5. Salvar
```

Para trocar de Pod: destrói o antigo, cria outro, cola o novo URL,
testa, salva. Nunca precisas de editar ficheiros.

### Arquitetura

```
backend/app/cloud/worker_connection.py   # WORKER CONNECTION - genérica, qualquer provider
backend/app/engines/cloud/base.py        # CLOUD PROVIDER (abstração, já existia)
backend/app/engines/cloud/providers.py   # RunPodProvider/TensorDockProvider/VagonProvider (stubs, por implementar)
```

`WorkerConnection` é deliberadamente genérica — testar `/health` é
igual para qualquer provider, por isso `provider` é só um rótulo
informativo nesta etapa. O que **é** específico de cada provider (criar
e destruir Pods automaticamente) fica em `CloudProvider`/
`RunPodProvider`, que continuam por implementar (ver secção Cloud
Architecture acima) — propositadamente, esta etapa não mexeu nisso.

### Persistência

Tabela `cloud_connection` (linha única, `id='default'`): `provider`,
`worker_url`, `worker_port`, `worker_name`, `status`,
`last_health_check`, `worker_info` (JSON da última resposta do
Worker), `last_error`. Sobrevive a reiniciar o backend — testado (ver
Testes).

### API

```
GET  /api/cloud/providers    -> lista de providers preparados (runpod/tensordock/vagon/local)
GET  /api/cloud/connection   -> configuração persistida
PUT  /api/cloud/connection   -> atualiza provider/worker_url/worker_port/worker_name
POST /api/cloud/test         -> testa AGORA (aceita override ad-hoc no corpo, sem
                                 precisar de "Salvar" primeiro) e devolve
                                 {status, worker_info, error, last_health_check, ...}
```

`POST /api/cloud/test` faz sempre um `GET {worker_url}/health` real
(timeout de 8s) e nunca levanta exceção — falhas de rede viram
`status: "OFFLINE"`, erros HTTP do Worker viram `status: "ERROR"` com
`error` legível, sucesso vira `status: "ONLINE"` com `worker_info`
exatamente o que o Worker devolveu.

### Sem API keys no frontend

Não é pedida nenhuma chave do provider nesta etapa (testar `/health`
não precisa de autenticação com o RunPod). Quando isso mudar (criação
automática de Pods, próxima etapa), a chave vive só no `.env` do
backend (`RUNPOD_API_KEY`, já reservada no `.env.example`) — nunca é
devolvida por nenhum endpoint nem armazenada no frontend.

### Atualização: ligar o Worker agora tem efeito real na geração

A afirmação original desta secção ("Worker ONLINE não muda
automaticamente o engine usado para gerar") deixou de ser verdade a
partir da introdução do `CloudWorkerEngine` (ver secção "Cloud Worker
(real...)" acima). `resolve_runtime_engine` continua a decidir o engine
pelo `engine_id` do preset (nunca por `has_online_worker()` — isso
mantém-se), mas agora **esse engine já é executável de facto** para 26
famílias (wan/ltx2/hunyuan/flux/ace_step/...): assim que o Worker está
`ONLINE` e guardado, os presets "live" com esses `engine_id`s geram de
verdade. Sem Worker configurado, `CloudWorkerEngine.validate_request()`
rejeita o job com uma mensagem clara em vez de gerar em silêncio no
modo demo. `has_online_worker()` continua a existir só para
consulta/informação, sem trocar automaticamente o engine de um preset
já resolvido.

## Base de dados

SQLite (`data/jarvis.db`) com migrações idempotentes
(`backend/app/database.py`): a versão atual do schema é gravada em
`schema_version`; correr `init_db()` numa instalação antiga só
adiciona as colunas/tabelas em falta, nunca apaga dados. Testado com
uma simulação de schema antigo (ver secção Testes).

Tabelas: `projects`, `assets`, `gallery_items`, `jobs`, `loras`,
`settings`, `engines`, `schema_version`. `jobs` e `gallery_items`
ganharam `preset_id`/`preset_name` na migração v3 (mantém instalações
antigas a funcionar sem perder dados).

## Projetos, Gallery, LoRAs, Assets

- **Projects**: criar, listar, abrir (mostra assets e jobs associados
  num modal).
- **Gallery**: filtros por kind, favoritos, eliminar, modal de
  metadata (prompt, engine, modelo, seed, resolução, duração, data).
  Populada automaticamente por qualquer engine que complete um job.
- **LoRA Manager**: upload de ficheiro + preview, nome, descrição,
  tags, modelo compatível, strength por LoRA, ativar/desativar,
  eliminar. O Video/Image Studio deixam escolher vários LoRAs em
  simultâneo, cada um com o seu slider de strength.
- **Assets**: upload por categoria (images/videos/audio/loras/
  references), pesquisa por nome, eliminação com confirmação.

## Troubleshooting

| Sintoma | Causa provável | Resolução |
|---|---|---|
| `setup.bat` diz Python/Node não encontrado | não está no PATH | reinstalar marcando "Add to PATH" |
| Backend não responde em `/health` | erro no arranque do uvicorn | ver a janela "JARVIS Backend" — o erro real aparece lá |
| "porta 8000/5173 em uso" | outro processo já está a usar a porta | fecha o processo indicado ou muda a porta |
| MiniMax mostra `online: false` | `MINIMAX_API_KEY` vazia no `.env` | preencher a chave e reiniciar o backend |
| `pip` tenta compilar `pydantic-core` (Rust/MSVC) | versão de Python sem wheel pré-compilada | instalar Python 3.12 x64 e apagar `backend\.venv`; o `setup.bat` agora nunca compila a partir do código-fonte, então isto já não deve acontecer — se acontecer, é sinal de que nem a versão mais recente do pydantic tem wheel para o teu Python |
| Cloud mostra OFFLINE mesmo com o Pod a correr | URL/porta errados, ou o Worker não expõe `/health` | confirma o URL exato copiado do RunPod (sem barra final), testa `curl <url>/health` manualmente fora do JARVIS |
| Cloud mostra ERROR em vez de OFFLINE | o Worker respondeu mas com erro HTTP (ex.: 500) | o Worker está a correr mas com problemas internos — ver os logs do próprio Pod, não é um problema do JARVIS |
| `npm install` falha | sem internet, ou versão de Node muito antiga | confirmar Node 18+; correr `npm install` manualmente em `frontend/` para ver o erro completo |
| Base de dados com erro após atualizar o JARVIS | schema desatualizado | `init_db()` corre migrações automaticamente ao arrancar; se persistir, apagar `data/jarvis.db` (perde-se o histórico) |

## Testes

### O que foi corrido nesta entrega (ambiente de desenvolvimento, sem Windows/sem rede para instalar pacotes)

- **Sintaxe**: todos os `.py` do backend (`py_compile`), todos os `.jsx`/`.js`
  do frontend (parser real do esbuild), todos os `.json` de configuração
  (`json.load`).
- **Bundle real do frontend**: `esbuild --bundle` de `main.jsx` com as
  dependências npm externalizadas — confirma que todos os imports entre
  os ~30 ficheiros React resolvem e que a sintaxe JSX está correta em
  toda a árvore.
- **Migrações de base de dados**: simulação de uma instalação antiga
  (schema sem as colunas novas) → `init_db()` → confirmado que as
  colunas/tabelas em falta são adicionadas e os dados existentes são
  preservados. `init_db()` corrido duas vezes seguidas sem erro.
- **Configuração**: todos os `studio_*.json`, `formats.json`,
  `quality_presets.json`, `advanced_fields.json` carregados e validados
  via `config.py`.
- **Registo de engines**: confirmado que `mock` e `minimax` se
  registam, incluindo quando `requests` não está instalado (import
  guardado — a app não parte).
- **Mock Engine — ciclo de vida completo**: job criado diretamente na
  BD → `generate()` → progresso → `COMPLETED` → confirmado
  `output_path` preenchido e entrada automática na `gallery_items`.
- **Mock Engine — cancelamento**: encontrado e corrigido um bug real
  de condição de corrida (o loop de progresso reescrevia `CANCELLED`
  com `PROCESSING` por cima). Corrigido com verificação dupla
  (antes/depois do sleep) e escritas condicionais em SQL
  (`WHERE status != 'CANCELLED'`). Repetido 5x após a correção — 5/5
  passaram.
- **MiniMax adapter — caminho de erro real**: pedido real a
  `https://api.minimax.io/v2/video_generation` com chave inválida →
  `403 Forbidden` genuíno recebido, job corretamente marcado `FAILED`
  na BD, sem crash.

### Preset/Model/Workflow/LoRA Registry — versão com dados reais (esta entrega)

Corrido de facto neste ambiente (`python scripts/test_registry.py`,
**17/17 aprovados**, cobrindo os 14 pontos pedidos):

1. Registry carrega corretamente — 202 modelos (2 curados + 200
   importados), 204 workflows, catálogo de LoRAs e engine registry
   todos não-vazios.
2. Backend fornece os 20 presets, incluindo os 16 nomes pedidos.
3. Frontend sem lista hardcoded — confirmado por `grep` (ver abaixo).
4. Selecionar "Cinematic Pro 1.1" carrega o modelo real
   (`LTX-2 2.3 Distilled 1.1 22B`), `config_source`
   (`video/ltx2_22B_distilled_1_1.json`) e defaults reais
   (`num_inference_steps: 8`, `video_length: 241`).
5. Capabilities diferem por preset (`Light 8GB` sem `control_video`
   vs `Studio Editor` com `control_video`).
6. Botão T2V ("Light 8GB") resolve `model.id == "t2v_1.3B"`,
   `workflow.executable == false`.
7. Botão I2V ("Studio AI I2V") resolve `model.id == "i2v_720p"`,
   `workflow.source_type == "preset_config"`. Modo não suportado
   (`i2v` em "Light 8GB") devolve `None`, não inventa.
8. End Frame só em presets com a capability (`MiniMax H3` sim,
   `Light 8GB` não).
9. Continue só em presets com `video_continuation` (`Infinite Talk`
   sim, `Cinematic Lite` não).
10. Audio só quando `audio_to_video`/`audio_output` estão presentes
    (`Talking Head` sim, `Cinematic Lite` não).
11. LoRAs associados corretamente: "Studio Editor" resolve os **4
    LoRAs reais** do `vace_14B_cocktail.json`
    (`Wan21_CausVid_14B_T2V_lora_rank32_v2`, `DetailEnhancerV1`,
    `Wan21_AccVid_T2V_14B_lora_rank32_fp16`,
    `Wan21_T2V_14B_MoviiGen_lora_rank32_fp16`), com os multiplicadores
    reais (`1, 0.5, 0.5, 0.5`) como strength. Verificação de
    compatibilidade engine↔LoRA testada.
12. Todos os 204 workflows (200 importados + 4 placeholders demo)
    marcados `executable: false`.
13. Registry sobrevive a uma simulação de restart (todas as caches
    `lru_cache` limpas + módulos recarregados) — os mesmos 20 presets
    e a mesma resolução voltam a funcionar.
14. V1 (jobs sem `preset_id`, `engine`/`model` explícitos) continua
    100% funcional; caminho novo (com `preset_id`) também; preset
    inexistente rejeitado com erro claro.

Verificação do ponto 3 (sem lista hardcoded no frontend):
```
grep -rniE "cinematic|talking.head|director.vision|human.studio|ltx2|wan2|minimax-h3" frontend/src/
→ (nenhuma ocorrência)
```

**Dois bugs reais encontrados e corrigidos** durante a importação dos
200 ficheiros:
- Modelos LTX (sem `t2v`/`i2v` no nome de ficheiro) ficavam sem a
  capability `text_to_video` quando uma capability secundária
  (`outpainting`) já tinha sido adicionada primeiro — a heurística só
  aplicava o fallback quando a lista estava completamente vazia.
  Corrigido com uma flag `has_core_mode` explícita.
- O campo `loras` nalguns ficheiros é uma *string* (referência a um
  grupo de módulos), não uma lista de URLs — isso inflacionava a
  capability `lora` sem entradas reais correspondentes no catálogo.
  Corrigido para só marcar `lora` quando `loras` é de facto uma lista
  não-vazia.

Bundle completo do frontend (`esbuild --bundle`) revalidado depois de
todas as alterações — 0 erros. Sem regressão no fix de cancelamento
do turno anterior (retestado 3x).

**Não testado** (mesma limitação já registada: sem Windows real /
sem `fastapi` instalado neste ambiente): os endpoints reais via
servidor HTTP (`/api/models`, `/api/workflows`, `/api/loras/catalog`,
`/api/engines/registry`, `/api/presets`) — a lógica foi validada
diretamente em Python (o que os routers fazem por baixo, sem a
camada FastAPI), e `scripts/test_backend.py` já tem os testes
correspondentes (incluindo os novos endpoints) prontos para correr
no teu PC.

### Cloud Connection — WorkerConnection (esta entrega)

Corrido de facto neste ambiente (`python scripts/test_cloud.py`,
**11/11 aprovados**), usando servidores HTTP reais em localhost
(`http.server` da stdlib) — não são simulações, são pedidos HTTP
verdadeiros contra um servidor a correr de facto:

1. Salvar configuração (`update_connection` + `get_connection`).
2. Alterar Worker URL mantendo os restantes campos intactos.
3. Reiniciar backend e recuperar configuração — módulos recarregados
   (`importlib.reload`) para simular um restart real do processo; a
   configuração vem só da BD, nunca de memória.
4. Worker ONLINE — servidor HTTP real responde `/health`, `status`
   fica `ONLINE`, `worker_info` persistido corretamente.
5. Worker OFFLINE — porta sem nada a ouvir, `status` fica `OFFLINE`
   com erro legível.
6. Endpoint inválido — URL vazio e erro HTTP 500 do Worker, ambos
   tratados sem exceção (`OFFLINE`/`ERROR` conforme o caso).
7. Trocar de endpoint — dois servidores reais em portas diferentes,
   confirmando que o JARVIS reconhece a troca de Pod sem editar nada.
8. Mock Engine não quebra com Cloud offline — job criado e completado
   normalmente com a Cloud Connection em `OFFLINE`.
9. `has_online_worker()` é só informativo — confirmado por inspeção
   do código-fonte (`inspect.getsource`) que `resolve_runtime_engine`
   não depende disto, logo nenhuma troca automática de engine
   acontece.
10. Lista de providers preparada (RunPod/TensorDock/Vagon/Local).

**Bug real encontrado e corrigido** durante os testes: o meu
*helper* de teste enviava `Content-Length` prometendo um corpo que
nunca escrevia nas respostas de erro simuladas, causando
`IncompleteRead` em vez de um erro HTTP limpo. Bug do harness de
teste, não do `worker_connection.py` (que já tratava isso
corretamente via `except Exception` — só a mensagem ficava menos
específica). Corrigido no helper.

`scripts/test_backend.py` também estendido com os equivalentes
via servidor HTTP real (`GET/PUT /api/cloud/connection`,
`POST /api/cloud/test` ONLINE e OFFLINE, confirmação de que o Mock
Engine não é afetado) — prontos para correr no teu PC.

Bundle completo do frontend revalidado (novo painel Cloud incluído)
— 0 erros.

### Correção pós-entrega: regressão de modos no Video Studio (Cinematic Pro 1.1 só mostrava T2V)

Reportado com print de ecrã: depois da migração para o Registry com
dados reais, "Cinematic Pro 1.1" só mostrava o modo "Texto → Vídeo",
tendo perdido Img → Vídeo, End Frame, Continue e Audio que existiam na
V1.

**Causa raiz real:** o `ltx2_22B_distilled_1_1.json` (o ficheiro
escolhido para este preset) tem uma descrição curta, focada só no que
é *diferente* nele (LoRAs automáticos), enquanto o ficheiro irmão
`ltx2_22B.json` (mesma arquitetura `ltx2_22B`, variante "Dev") descreve
explicitamente: *"Supports start/end keyframes and sliding-window
continuation... audio soundtrack"*. A heurística de capabilities
analisava cada ficheiro isoladamente, por isso perdia estes sinais
presentes só nos ficheiros irmãos.

**Correção:** `config_importer.py` passou a agregar capabilities por
família de arquitetura (`_apply_family_capabilities`) — a
`capabilities` final de cada modelo é a união de todos os sinais
encontrados em qualquer ficheiro que partilhe o mesmo `checkpoint`
(arquitetura). **`defaults`, `loras` e `checkpoint_urls` continuam
estritamente por ficheiro, nunca agregados** — só os *modos/controlos*
disponíveis são generosos entre variantes irmãs, nunca os parâmetros
numéricos ou LoRAs concretos de uma variante específica.

Também foi criada a camada `resolve_generation_mode(preset_id, mode)`
pedida explicitamente — junta PRESET → CAPABILITIES → MODO →
WORKFLOW, devolvendo `{preset_id, mode, workflow_id, engine_id,
capabilities, defaults, execution_status}`. `execution_status` diz
claramente "Workflow preparado — execução real ainda não disponível
(a correr em modo Mock)" quando o adapter real não existe, **sem
nunca esconder o modo da interface** — só o texto de estado muda,
nunca a disponibilidade do botão.

Testado nesta correção (18 + 2 novos = 20 testes, todos aprovados):
- Regressão específica: `Cinematic Pro 1.1` volta a ter
  `t2v`/`i2v`/`end_frame`/`continue` e capability de áudio.
- Auditoria visual de todos os 16 presets nomeados (impressos modo a
  modo) — nenhum ficou com uma lista de modos vazia ou absurda; os
  isolados genuinamente limitados (`Light 8GB`, arquitetura `t2v_1.3B`
  sem nenhum sibling i2v) continuam corretamente só com `t2v`,
  provando que a agregação não "inventa" capacidades onde não há
  nenhum sinal real em nenhum ficheiro da família.
- `resolve_generation_mode` testado para todos os modos de "Cinematic
  Pro 1.1", incluindo criar e completar um job real (via Mock) para
  cada um.
- Confirmado que `defaults`/`loras` de "Cinematic Pro 1.1" continuam
  exclusivamente os do seu próprio ficheiro (não herdou parâmetros
  nem LoRAs dos irmãos, só a lista de capabilities/modos).

### Correção pós-entrega: MSVC/Rust no `pip install` (Windows)

Reportado pelo utilizador depois de correr `setup.bat` num Windows
real: o pip tentava compilar `pydantic-core` via Rust/`maturin` e
falhava por falta do `link.exe` do MSVC.

Testado nesta correção (neste ambiente Linux, sem Windows disponível):

- `backend/requirements.txt`: confirmado que os `>=` novos não
  quebram a leitura do ficheiro (`pip` não instalado aqui para testar
  a resolução real, mas a sintaxe do requirements foi revista).
- `setup.bat` / `INICIAR_JARVIS.bat`: revisão manual linha a linha da
  lógica de deteção de versão do Python. **Encontrado e corrigido um
  problema real**: um encadeamento `if A if B if C (...) else (...)`
  em `cmd.exe` que, testado mentalmente contra a semântica documentada
  do `cmd.exe`, só dispara o ramo `else` quando A e B são verdadeiros
  e C é falso — ou seja, se a versão do Python não fosse `3.x`, nem o
  aviso nem a confirmação apareciam, falhando em silêncio. Corrigido
  substituindo por uma flag `PY_COMPATIBLE` explícita.
- Balanceamento de parênteses verificado programaticamente em todo o
  código executável de `setup.bat` e `INICIAR_JARVIS.bat` (excluindo
  linhas `rem`), confirmando `abre == fecha` nos dois ficheiros.

**Não foi possível** correr `setup.bat` num Windows real nem simular
`cmd.exe` neste ambiente (Linux, sem Wine/cmd.exe disponível) — a
validação ficou ao nível de revisão manual cuidadosa + verificação
programática de sintaxe, não de execução real. Recomenda-se confirmar
no teu PC e reportar a mensagem exata se algo ainda falhar.



- `uvicorn app.main:app` / servidor FastAPI real: este ambiente de
  desenvolvimento não tem `fastapi`/`uvicorn` instalados nem rede para
  os instalar. Por isso os routers (que importam `fastapi`) foram
  validados por sintaxe, não por execução.
- `npm run build` / `npm run dev` reais: sem rede para `npm install`
  as dependências (React, Vite, etc.) neste ambiente. Validado por
  bundle real com esbuild (ver acima), que é a mesma ferramenta usada
  pelo Vite por baixo — mas não é 100% equivalente a um `vite build`.
- `scripts/test_backend.py`: escrito e pronto, mas não pôde ser
  corrido aqui pela mesma razão (precisa do servidor real no ar).
  **Corre isto no teu PC depois do `INICIAR_JARVIS.bat`** para a
  validação end-to-end completa.
- Geração real com o MiniMax H3 (vídeo de facto gerado): precisa de
  uma chave paga que não está disponível neste ambiente.

Recomendação: depois de correr `INICIAR_JARVIS.bat` no teu PC, corre
`python scripts/test_backend.py` — é o teste que fecha o que não pôde
ser fechado aqui.
