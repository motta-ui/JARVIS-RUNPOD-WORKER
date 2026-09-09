// image.js — Image Studio logic
if(!window.playNotifBeep){var _ns=document.createElement("script");_ns.src="/studio/notif.js?v=1";document.head.appendChild(_ns)}
import { checkHealth, startGeneration, uploadRefImage, pollStatus, loadOutputs, fileUrl } from "./api.js";

// ── Resoluções por formato — apenas valores válidos do Wan2GP ──
// Fonte: wgp.py → get_resolution_choices() (sem 4K)
const FORMAT_RES = {
  "1:1": [
    { label: "320 × 320   (256p)",            value: "320x320"   },
    { label: "448 × 448   (320p)",            value: "448x448"   },
    { label: "512 × 512   (384p)",            value: "512x512"   },
    { label: "720 × 720   (480p)",            value: "720x720"   },
    { label: "960 × 960   (720p)",            value: "960x960"   },
    { label: "1024 × 1024 (720p)",            value: "1024x1024" },
    { label: "1440 × 1440 (2K)",              value: "1440x1440" },
    // Sem 4K quadrado — não existe na lista oficial do Wan2GP
  ],
  "16:9": [
    { label: "576 × 320   (320p)",            value: "576x320"   },
    { label: "672 × 384   (384p)",            value: "672x384"   },
    { label: "832 × 480   (480p)",            value: "832x480"   },
    { label: "960 × 544   (540p)",            value: "960x544"   },
    { label: "1280 × 720  (720p)",            value: "1280x720"  },
    { label: "1920 × 1088 (1080p)",           value: "1920x1088" },
    { label: "2560 × 1440 (2K)",              value: "2560x1440" },
  ],
  "9:16": [
    { label: "320 × 576   (320p)",            value: "320x576"   },
    { label: "384 × 672   (384p)",            value: "384x672"   },
    { label: "480 × 832   (480p)",            value: "480x832"   },
    { label: "544 × 960   (540p)",            value: "544x960"   },
    { label: "720 × 1280  (720p)",            value: "720x1280"  },
    { label: "1088 × 1920 (1080p)",           value: "1088x1920" },
    { label: "1440 × 2560 (2K)",              value: "1440x2560" },
  ],
  "4:3": [
    { label: "832 × 624   (480p)",            value: "832x624"  },
    { label: "1104 × 832  (720p)",            value: "1104x832" },
    { label: "1920 × 1440 (2K)",              value: "1920x1440" },
    // Sem 4K 4:3 — não existe na lista oficial do Wan2GP
  ],
  "21:9": [
    { label: "1280 × 544  (720p)",            value: "1280x544" },
    { label: "1920 × 832  (1080p)",           value: "1920x832" },
    { label: "2688 × 1152 (2K)",              value: "2688x1152" },
  ],
};
// Valor padrão por formato
const FORMAT_RES_DEFAULT = {
  "1:1":  "1024x1024",
  "16:9": "1280x720",
  "9:16": "720x1280",
  "4:3":  "1104x832",
  "21:9": "1280x544",
};

// ── Estado ────────────────────────────────────────────────────
let currentFormat      = "1:1";
let currentPerformance = "fast";
let currentResolution  = "1024x1024";
let currentFamily      = "flux2";   // família: "flux2" | "z_image"
let jobId              = null;
let pollTimer          = null;
let generating         = false;

// ── IMG-PERF: coleta de timestamps por geração ────────────────
// Resetado a cada clique em GERAR. Acessível via window._imgPerf no DevTools.
let _imgPerf = null;

// Mapeamento família + performance → model_id do backend
// ── PERF_MODEL_MAP ─────────────────────────────────────────────
// Mapeamento canônico: família + preset → { model: chave do MODELS dict, steps: default }
//
// Regras:
//  - "model" deve existir exatamente no MODELS dict do backend (acs_api.py).
//  - Nunca usar fallback silencioso — chave ausente deve ser tratada explicitamente.
//  - flux2.pro: desabilitado até flux2_dev ser validado no backend.
//  - z_image.bf16: mapeado para Z-Image Turbo com steps intermediários (16).
//    Z-Image Turbo não tem variante BF16; "Cinematic" = qualidade via mais steps.
//
// Mapeamento Visual:
//  Fast      → flux2_klein_4b  (4B INT8,  ~3 GB VRAM)
//  Balanced  → flux2_klein_9b  (9B INT8,  ~6 GB VRAM)
//  Cinematic → flux2_klein_9b_bf16 (9B BF16, ~9 GB VRAM)
//  Pro       → flux2_dev [PENDENTE — botão desabilitado]
const PERF_MODEL_MAP = {
  flux2: {
    fast:     { model: "Flux Fast",      steps: 4  },   // 4B distilled = menor/rápido
    balanced: { model: "Flux Balanced",  steps: 4  },   // 9B = base
    pro:      { model: "Flux Pro",       steps: 28 },   // [NEXTGEN] flux2_dev = pesado/máxima qualidade
  },
  z_image: {
    fast:     { model: "Z-Image Turbo", steps: 8  },
    balanced: { model: "Z-Image Turbo", steps: 12 },
    bf16:     { model: "Z-Image Turbo", steps: 16 }, // Cinematic = mais steps (sem variante BF16 real)
    pro:      { model: "Z-Image Turbo", steps: 20 },
  },
  // [12.26] Ideogram 4 Turbo Time — imagem com tipografia. DISTILLED no-guidance: 8 passos é o
  // ponto de projeto; acima de ~12 só desperdiça tempo (distilled satura). Antes mandava 12-36
  // (do modelo FULL) => 20 passos × 3.4s = 67s à toa. Turbo: 8 passos × ~2s = ~16s.
  ideogram4: {
    fast:     { model: "Typography Image", steps: 6  },
    balanced: { model: "Typography Image", steps: 8  },
    bf16:     { model: "Typography Image", steps: 10 },
    pro:      { model: "Typography Image", steps: 12 },
  },
  // [12.281] Krea 2 — imagem estética. Turbo (distilled, 8 steps)=fast; RAW (52 steps)=qualidade.
  krea2: {
    fast:     { model: "Krea 2 Turbo", steps: 8  },
    balanced: { model: "Krea 2 RAW",   steps: 30 },
    bf16:     { model: "Krea 2 RAW",   steps: 40 },
    pro:      { model: "Krea 2 RAW",   steps: 52 },
  },
};

function resolveModel() {
  const entry = PERF_MODEL_MAP[currentFamily]?.[currentPerformance];
  if (!entry) {
    // Fallback explícito — nunca silencioso.
    // Acontece se Pro for clicado apesar do disabled (improvável) ou se family/perf inválidos.
    console.warn(`[Image] resolveModel: combinação inválida family="${currentFamily}" perf="${currentPerformance}" — usando Balanced fallback`);
    return { model: "Flux Balanced", steps: 4 };
  }
  return entry;
}

// Fila ativa: jobs em andamento/concluídos (para exibir no painel)
const jobQueue = [];
// Fila pendente: jobs aguardando para serem gerados
const pendingQueue = [];

// ── Elementos ─────────────────────────────────────────────────
const promptTA      = document.getElementById("prompt");
const charCount     = document.getElementById("char-count");
const negativeTA    = document.getElementById("negative");
const seedInput     = document.getElementById("seed");
const btnGenerate   = document.getElementById("btn-generate");
const btnAbort      = document.getElementById("btn-abort");
const btnEnqueue    = document.getElementById("btn-enqueue");
const btnQueue      = document.getElementById("btn-queue");
const btnStar       = document.getElementById("btn-star");
const btnLabel      = document.getElementById("btn-label");
const queuePanel    = document.getElementById("queue-panel");
const queueBadge    = document.getElementById("queue-badge");
const queueList     = document.getElementById("queue-list");
const queueClear    = document.getElementById("queue-clear");
const resSelect     = document.getElementById("res-select");
const injectSelect  = document.getElementById("inject-images");
const controlSelect = document.getElementById("control-mode");
const stepsInput    = document.getElementById("steps");
const stepsVal      = document.getElementById("steps-val");
const seedDisplay   = document.getElementById("seed-display");
const seedRandBtn   = document.getElementById("seed-rand-btn");

// Ref image upload
const refUploadGroup = document.getElementById("ref-upload-group");
const refDropzone    = document.getElementById("ref-dropzone");
const refFileInput   = document.getElementById("ref-file-input");
const refDzContent   = document.getElementById("ref-dz-content");
let   refImageFile   = null;
let   refImagePath   = "";

// Control image upload (pose / inpaint)
const ctrlUploadGroup = document.getElementById("ctrl-upload-group");
const ctrlUploadLabel = document.getElementById("ctrl-upload-label");
const ctrlDropzone    = document.getElementById("ctrl-dropzone");
const ctrlFileInput   = document.getElementById("ctrl-file-input");
const ctrlDzContent   = document.getElementById("ctrl-dz-content");
let   ctrlImageFile   = null;
let   ctrlImagePath   = "";

const previewEmpty   = document.getElementById("preview-empty");
const previewLoading = document.getElementById("preview-loading");
const previewImgWrap = document.getElementById("preview-img-wrap");
const previewImg     = document.getElementById("preview-img");
const progressBar    = document.getElementById("progress-bar");
const progressLabel  = document.getElementById("progress-label");
const previewDlSub   = document.getElementById("preview-dl-sub");
const hudMainStatus  = document.getElementById("hud-main-status");
const hudPct         = document.getElementById("hud-pct");
const hudDlCalm      = document.getElementById("hud-dl-calm");

const galleryThumbs  = document.getElementById("gallery-thumbs");

// ── Prompt counter ────────────────────────────────────────────
promptTA?.addEventListener("input", () => {
  charCount.textContent = `${promptTA.value.length} / 12000`;
  saveState();
});

negativeTA?.addEventListener("input", () => saveState());

// ── Resolution select (dinâmico) ─────────────────────────────
function renderResolutions(fmt) {
  const options = FORMAT_RES[fmt] || FORMAT_RES["1:1"];
  const defVal  = FORMAT_RES_DEFAULT[fmt] || options[0].value;

  resSelect.innerHTML = options.map(o =>
    `<option value="${o.value}" ${o.value === defVal ? "selected" : ""}>${o.label}</option>`
  ).join("");

  currentResolution = defVal;
  resSelect.onchange = () => { currentResolution = resSelect.value; saveState(); };
}

// ── Format buttons ────────────────────────────────────────────
document.querySelectorAll(".fmt-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".fmt-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentFormat = btn.dataset.fmt;
    renderResolutions(currentFormat);
    saveState();
  });
});

// Init resolução
renderResolutions(currentFormat);

// ── Modelo dropdown ───────────────────────────────────────────
const modelSelect  = document.getElementById("model-select");
const topbarModel  = document.getElementById("topbar-model");

// FIX BUILD 34: nomes comerciais — sem nomes técnicos para o usuário
const FAMILY_LABELS = { flux2: "Cinematic Image", z_image: "Creative Image", ideogram4: "Typography Image", krea2: "Krea 2 Estético" };
const PERF_LABELS   = { fast: "Fast", balanced: "Balanced", bf16: "Pro", pro: "Pro" };

function updateTopbarModel() {
  if (!topbarModel) return;
  // Topbar exibe nome comercial da família (ex: "Cinematic Image", "Creative Image").
  // [REVERT-B2] Botões de performance mantêm labels simples: Fast | Balanced | Pro.
  const family = FAMILY_LABELS[currentFamily] || currentFamily;
  topbarModel.textContent = family;
}

// Grupos de controle exclusivos do Flux 2 (não suportados pelo Z-Image)
const injectGroup  = injectSelect?.closest(".ctrl-group");
const controlGroup = controlSelect?.closest(".ctrl-group");

function applyFamilyCapabilities() {
  const isFlux2 = currentFamily === "flux2";
  // Mostra inject + control apenas para Flux 2
  if (injectGroup)  injectGroup.style.display  = isFlux2 ? "" : "none";
  if (controlGroup) controlGroup.style.display = isFlux2 ? "" : "none";
  // LoRA panel (#lora-group) fica sempre oculto — visibilidade via painel de presets comerciais apenas.
  // Se escondeu, reseta os selects e limpa imagens
  if (!isFlux2) {
    if (injectSelect)  { injectSelect.value  = ""; refUploadGroup.style.display  = "none"; clearRefImage();  }
    if (controlSelect) { controlSelect.value = ""; ctrlUploadGroup.style.display = "none"; clearCtrlImage(); }
  }
  // [NEXTGEN 2026-06-27] Regra de qualidade por PESO real (não por steps).
  //   • modelo com >1 peso distinto (Turbo vs RAW, Fast vs Balanced, dev/gguf...) → habilita as opções de qualidade;
  //   • modelo com 1 peso só (mesmo modelo em steps diferentes, ex: Z-Image, Typography) → SÓ "Balanced", resto cinza.
  // Fonte de verdade: PERF_MODEL_MAP (nome do modelo = peso). Habilita 1 perf por peso distinto (1ª na ordem).
  const _pm    = PERF_MODEL_MAP[currentFamily] || {};
  const _order = ["fast", "balanced", "pro"];
  const _perfModel = {};
  _order.forEach(p => { if (_pm[p]) _perfModel[p] = _pm[p].model; });
  const _distinct = new Set(Object.values(_perfModel));
  const _enabled  = new Set();
  if (_distinct.size <= 1) {
    // peso único → só Balanced (cai pra Balanced se existir, senão o único perf definido)
    _enabled.add(_pm.balanced ? "balanced" : (_order.find(p => _pm[p]) || "balanced"));
  } else {
    // multi-peso → 1 perf por peso distinto (o primeiro na ordem); duplicados do mesmo peso ficam cinza
    const _seen = new Set();
    _order.forEach(p => { const m = _perfModel[p]; if (m && !_seen.has(m)) { _seen.add(m); _enabled.add(p); } });
  }
  document.querySelectorAll(".perf-btn").forEach(btn => {
    const perf = btn.dataset.perf;
    if (_enabled.has(perf)) { btn.classList.remove("perf-btn-soon"); }
    else { btn.classList.add("perf-btn-soon"); btn.classList.remove("active"); }
  });
  // [NEXTGEN 2026-06-27] 3 botões fixos (Fast/Balanced/Pro). Pro sempre visível; a regra
  // acima já o deixa cinza quando a família não tem variante pesada. (Sem mais bf16 = sem 2º "Pro".)
  // Se a performance atual ficou cinza ao trocar de modelo, cai para um perf habilitado (prefere Balanced)
  if (!_enabled.has(currentPerformance)) {
    currentPerformance = _enabled.has("balanced") ? "balanced" : [..._enabled][0];
    document.querySelectorAll(".perf-btn").forEach(b => b.classList.toggle("active", b.dataset.perf === currentPerformance));
    _syncStepsToPerf?.();
    _updateModelInfo?.();
  }
}

modelSelect?.addEventListener("change", () => {
  currentFamily = modelSelect.value;
  updateTopbarModel();
  applyFamilyCapabilities();
  loadLoras();
  renderPresetDropdown(); // filtra presets pela nova família
  _syncStepsToPerf();    // A3: reseta steps para o default da nova família + performance
  _updateModelInfo();    // A4: atualiza label de modelo no Advanced
  saveState();
});

updateTopbarModel();
applyFamilyCapabilities(); // aplica no init

// ── Performance buttons ───────────────────────────────────────
document.querySelectorAll(".perf-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    if (btn.disabled || btn.classList.contains("perf-btn-soon")) return; // Pro desabilitado
    document.querySelectorAll(".perf-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentPerformance = btn.dataset.perf;
    updateTopbarModel();
    loadLoras(); // recarrega LoRAs pois o model_id pode mudar com a performance
    _syncStepsToPerf();    // A3: atualiza steps ao mudar preset
    _updateModelInfo();    // A4: atualiza label de modelo no Advanced
    renderPresetDropdown(); // filtra presets pela nova performance
    saveState();
  });
});

// ── Steps slider ─────────────────────────────────────────────
stepsInput?.addEventListener("input", () => {
  if (stepsVal) stepsVal.textContent = stepsInput.value;
  saveState();
});

// Sincroniza steps default com o preset de performance atual.
// Chamado ao trocar família ou performance.
// NÃO sobrescreve se o usuário já ajustou manualmente (estado is preserved via saveState).
// Quando troca de preset, atualiza para o default do novo preset.
function _syncStepsToPerf() {
  if (!stepsInput || !stepsVal) return;
  const resolved = PERF_MODEL_MAP[currentFamily]?.[currentPerformance];
  if (!resolved) return;
  stepsInput.value = resolved.steps;
  stepsVal.textContent = resolved.steps;
}

// ── Seed slider + random btn ─────────────────────────────────
let seedValue = -1; // -1 = aleatório

function updateSeedDisplay() {
  if (seedDisplay) seedDisplay.textContent = seedValue === -1 ? "Aleatório" : seedValue;
}

const seedSlider = document.getElementById("seed");
seedSlider?.addEventListener("input", () => {
  seedValue = parseInt(seedSlider.value);
  updateSeedDisplay();
  saveState();
});

seedRandBtn?.addEventListener("click", () => {
  seedValue = -1;
  if (seedSlider) seedSlider.value = 0;
  updateSeedDisplay();
  saveState();
});

updateSeedDisplay();

// ── Prompt Enhancer toggle (Advanced Drawer) ──────────────────
// "" = OFF (default) — prompt enviado exatamente como digitado
// "T" = ON — LLM reescreve o prompt antes da geração
let imagePromptEnhancer = ""; // default OFF

function _initEnhancerPills() {
  // NOTA: seleciona ".adv-enh-pill" — classe definida no HTML e no studio.css.
  // Bug anterior usava ".img-enh-pill" que não existia → zero elementos → nenhum listener.
  document.querySelectorAll(".adv-enh-pill").forEach(pill => {
    pill.addEventListener("click", () => {
      document.querySelectorAll(".adv-enh-pill").forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      imagePromptEnhancer = pill.dataset.enh ?? "";
      _updateEnhancerHint();
      saveState();
    });
  });
  _updateEnhancerHint(); // hint inicial
}

function _updateEnhancerHint() {
  const hint = document.getElementById("img-enh-hint");
  if (!hint) return;
  hint.textContent = imagePromptEnhancer === "T"
    ? "Prompt reescrito por IA antes de gerar"
    : "Prompt enviado exatamente como escrito";
}

// ── LoRAs ─────────────────────────────────────────────────────
const loraGroup   = document.getElementById("lora-group");
const loraList    = document.getElementById("lora-list");
const loraRefresh = document.getElementById("lora-refresh");
let   availableLoras = [];   // [{name, filename, size_mb}]
let   selectedLoras  = [];   // [{name, multiplier}]

// model_id atual baseado em família + performance
function currentModelId() {
  const map = {
    flux2: { fast: "flux2_klein_4b", balanced: "flux2_klein_9b", bf16: "flux2_klein_9b_bf16", pro: "flux2_dev" },
    z_image: { fast: "z_image", balanced: "z_image", pro: "z_image" },
    ideogram4: { fast: "ideogram4", balanced: "ideogram4", bf16: "ideogram4", pro: "ideogram4" },   // [2026-06-21] fp8 (nf4 dava 329s/passo + NaN)
  };
  return map[currentFamily]?.[currentPerformance] ?? "flux2_klein_9b";
}

async function loadLoras() {
  if (!loraList) return { prev: 0, next: 0 };
  loraList.innerHTML = `<span class="lora-empty">Carregando...</span>`;
  const prev = availableLoras.length;
  selectedLoras = [];
  try {
    const r = await fetch(`/loras?model_id=${currentModelId()}`);
    const d = await r.json();
    availableLoras = d.loras || [];
    renderLoraList();
    return { prev, next: availableLoras.length };
  } catch {
    loraList.innerHTML = `<span class="lora-empty">Erro ao carregar Estilos.</span>`;
    return { prev, next: prev };
  }
}

async function refreshLoras() {
  const btn = document.getElementById("btn-refresh-loras");
  if (btn) { btn.disabled = true; btn.textContent = "↻ Atualizando..."; }
  const { prev, next } = await loadLoras();
  renderPresetDropdown();                    // sincroniza presets com availableLoras novo
  if (btn) { btn.disabled = false; btn.textContent = "↻ Atualizar Estilos"; }
  const diff = next - prev;
  let msg;
  if      (diff > 0) msg = `${diff} novo${diff > 1 ? "s" : ""} Estilo${diff > 1 ? "s" : ""} encontrado${diff > 1 ? "s" : ""}`;
  else if (diff < 0) msg = `${Math.abs(diff)} Estilo${Math.abs(diff) > 1 ? "s" : ""} removido${Math.abs(diff) > 1 ? "s" : ""}`;
  else               msg = "Estilos atualizados";
  setStatus(msg, "done");
  setTimeout(hideStatus, 2500);
}

function renderLoraList() {
  if (!loraList) return;
  // O painel #lora-group fica sempre oculto (style="display:none" no HTML).
  // Os checkboxes existem no DOM (invisíveis) — o mecanismo de presets os usa via applyLorasToUI().
  // Não alterar loraGroup.style aqui — visibilidade controlada exclusivamente pelo painel de presets.
  if (!availableLoras.length) {
    loraList.innerHTML = `<span class="lora-empty">Nenhum Estilo instalado para este modelo.</span>`;
    return;
  }
  loraList.innerHTML = availableLoras.map((l, i) => `
    <div class="lora-item" data-idx="${i}">
      <label class="lora-item-top">
        <input type="checkbox" class="lora-cb" data-name="${l.name}" data-idx="${i}" />
        <span class="lora-name">${l.label || l.name}</span>
      </label>
      <div class="lora-slider-row">
        <span class="lora-slider-label">Força</span>
        <input type="range" class="lora-slider" data-idx="${i}"
               min="0" max="2" step="0.05" value="1" />
        <span class="lora-slider-val" id="lora-val-${i}">1.00</span>
      </div>
    </div>`).join("");

  // Checkboxes
  loraList.querySelectorAll(".lora-cb").forEach(cb => {
    cb.addEventListener("change", () => syncSelectedLoras());
  });
  // Sliders de intensidade
  loraList.querySelectorAll(".lora-slider").forEach(sl => {
    const idx = sl.dataset.idx;
    const valEl = document.getElementById(`lora-val-${idx}`);
    sl.addEventListener("input", () => {
      if (valEl) valEl.textContent = parseFloat(sl.value).toFixed(2);
      syncSelectedLoras();
    });
  });
}

function syncSelectedLoras() {
  selectedLoras = [];
  loraList?.querySelectorAll(".lora-cb:checked").forEach(cb => {
    const idx      = cb.dataset.idx;
    const sl       = loraList.querySelector(`.lora-slider[data-idx="${idx}"]`);
    const lora     = availableLoras[parseInt(idx)];
    selectedLoras.push({
      name:       cb.dataset.name,           // stem (sem extensão) — para UI
      filename:   lora?.filename || cb.dataset.name + ".safetensors", // com extensão — para backend
      multiplier: sl ? parseFloat(sl.value) : 1.0,
    });
  });
}

function getLorasPayload() {
  return {
    // Wan2GP CheckboxGroup espera o nome do arquivo COM extensão
    loras_choices:     selectedLoras.map(l => l.filename),
    loras_multipliers: selectedLoras.map(l => l.multiplier.toFixed(2)).join(","),
  };
}

// Aplica LoRAs selecionados (de preset) na UI — aceita stem ou filename
function applyLorasToUI(lorasArr) {
  loraList?.querySelectorAll(".lora-cb").forEach(cb => {
    const cbStem = cb.dataset.name; // stem sem extensão
    const match  = lorasArr.find(l => {
      const s = typeof l === "string" ? l : l.name;
      return s === cbStem || s.replace(/\.safetensors$/i, "") === cbStem;
    });
    cb.checked = !!match;
    if (match) {
      const idx   = cb.dataset.idx;
      const sl    = loraList.querySelector(`.lora-slider[data-idx="${idx}"]`);
      const valEl = document.getElementById(`lora-val-${idx}`);
      const mult  = (typeof match === "object" && match.multiplier) ? match.multiplier : 1.0;
      if (sl)    { sl.value = mult; }
      if (valEl) { valEl.textContent = parseFloat(mult).toFixed(2); }
    }
  });
  syncSelectedLoras();
}

loraRefresh?.addEventListener("click", async () => {
  loraRefresh.style.transition = "transform 0.4s ease";
  loraRefresh.style.transform  = "rotate(360deg)";
  setTimeout(() => { loraRefresh.style.transform = ""; loraRefresh.style.transition = ""; }, 420);
  await refreshLoras();
});

document.getElementById("btn-refresh-loras")?.addEventListener("click", async () => {
  // Anima o ícone oculto junto para consistência interna
  if (loraRefresh) {
    loraRefresh.style.transition = "transform 0.4s ease";
    loraRefresh.style.transform  = "rotate(360deg)";
    setTimeout(() => { loraRefresh.style.transform = ""; loraRefresh.style.transition = ""; }, 420);
  }
  await refreshLoras();
});

// ── Presets ───────────────────────────────────────────────────
const presetSelect   = document.getElementById("preset-select");
const presetApplyBtn = document.getElementById("preset-apply-btn");
const presetSaveBtn  = document.getElementById("preset-save-btn");
const PRESET_KEY     = "acs_studio_presets_v1";
const STATE_KEY      = "acs_image_state_v1";    // Fase 1 — persistência leve
const JOB_STATE_KEY  = "acs:state:image";       // Fase 3 — job/output/error recovery
const JOB_MAX_AGE_MS = 6 * 60 * 60 * 1000;     // 6h — expiração do job salvo

// Presets built-in por família — mapeados para LoRAs instalados
// Nomes comerciais — filenames técnicos (.safetensors) nunca aparecem na UI.
// Mapeamento: name (UI) → loras (stems, sem extensão) → payload usa filename com extensão
const BUILTIN_PRESETS = {
  flux2: [
    {
      name:             "Consistency",
      loras:            ["Klein-consistency"],
      loras_multipliers:"1.0",
      steps:            4,
    },
    {
      name:             "Consistency V2",
      loras:            ["Flux2-Klein-9B-consistency-V2"],
      loras_multipliers:"1.0",
      steps:            4,
    },
    {
      // f2k_consist_20260225 — versão atualizada do Klein-consistency (4B+9B compatível, fev/2026)
      name:             "Consistency Pro",
      loras:            ["f2k_consist_20260225"],
      loras_multipliers:"1.0",
      steps:            4,
    },
    {
      name:             "Head Swap",
      loras:            ["bfs_head_v1_flux-klein_9b_step3500_rank128"],
      loras_multipliers:"1.0",
      steps:            4,
    },
    {
      // flux-2-klein-9B-360-erp-outpaint-lora_V1 — projeção equiretangular / outpainting 360°
      name:             "360° Panorama",
      loras:            ["flux-2-klein-9B-360-erp-outpaint-lora_V1"],
      loras_multipliers:"0.9",
      steps:            8,   // recomendado mais steps para outpaint
    },
  ],
  z_image: [
    // adicionar quando tiver LoRAs de z_image instalados
  ],
};

let allPresets = [];

function loadUserPresets() {
  try { return JSON.parse(localStorage.getItem(PRESET_KEY) || "[]"); }
  catch { return []; }
}
function saveUserPresets(arr) {
  localStorage.setItem(PRESET_KEY, JSON.stringify(arr));
}

// ── State persistence — Fase 1 ────────────────────────────────
// Persiste 11 campos leves (sem imagens, sem base64).
// Chave separada de presets para não colidir.

function saveState() {
  try {
    localStorage.setItem(STATE_KEY, JSON.stringify({
      prompt:       promptTA?.value       ?? "",
      negative:     negativeTA?.value     ?? "",
      family:       currentFamily,
      performance:  currentPerformance,
      format:       currentFormat,
      resolution:   currentResolution,
      steps:        stepsInput ? (parseInt(stepsInput.value) || 4) : 4,
      seed:         seedValue,
      injectImages: injectSelect?.value   ?? "",
      controlMode:  controlSelect?.value  ?? "",
      advOpen:      advBody ? advBody.classList.contains("open") : false,
      enhancer:     imagePromptEnhancer,   // A3: persiste estado do Prompt Enhancer
    }));
  } catch { /* quota exceeded — ignorar silenciosamente */ }
}

function restoreState() {
  let s;
  try { s = JSON.parse(localStorage.getItem(STATE_KEY)); } catch { s = null; }
  if (!s) return; // nenhum estado salvo — manter defaults

  // Prompt e negative
  if (s.prompt   && promptTA)   { promptTA.value  = s.prompt;   if (charCount) charCount.textContent = `${s.prompt.length} / 12000`; }
  if (s.negative && negativeTA)   negativeTA.value = s.negative;

  // Família (model select)
  if (s.family && modelSelect) {
    const opt = [...modelSelect.options].find(o => o.value === s.family);
    if (opt) { modelSelect.value = s.family; currentFamily = s.family; }
  }

  // Performance — valida contra o mapa para evitar tier obsoleto
  if (s.performance && PERF_MODEL_MAP[currentFamily]?.[s.performance]) {
    document.querySelectorAll(".perf-btn").forEach(b => b.classList.toggle("active", b.dataset.perf === s.performance));
    currentPerformance = s.performance;
  }

  // Formato + resolução (formato deve preceder renderResolutions)
  if (s.format && FORMAT_RES[s.format]) {
    document.querySelectorAll(".fmt-btn").forEach(b => b.classList.toggle("active", b.dataset.fmt === s.format));
    currentFormat = s.format;
    renderResolutions(currentFormat); // reconstrói <select> para o formato restaurado
  }
  if (s.resolution && resSelect) {
    const opt = [...resSelect.options].find(o => o.value === s.resolution);
    if (opt) { resSelect.value = s.resolution; currentResolution = s.resolution; }
  }

  // Steps
  if (s.steps && stepsInput) {
    stepsInput.value = s.steps;
    if (stepsVal) stepsVal.textContent = s.steps;
  }

  // Seed
  if (s.seed !== undefined) {
    seedValue = s.seed;
    if (seedSlider) seedSlider.value = s.seed === -1 ? 0 : s.seed;
    updateSeedDisplay();
  }

  // Inject images
  if (s.injectImages !== undefined && injectSelect) {
    const opt = [...injectSelect.options].find(o => o.value === s.injectImages);
    if (opt) {
      injectSelect.value = s.injectImages;
      if (refUploadGroup) refUploadGroup.style.display = s.injectImages ? "flex" : "none";
    }
  }

  // Control mode
  if (s.controlMode !== undefined && controlSelect) {
    const opt = [...controlSelect.options].find(o => o.value === s.controlMode);
    if (opt) {
      controlSelect.value = s.controlMode;
      if (ctrlUploadGroup) ctrlUploadGroup.style.display = s.controlMode ? "flex" : "none";
      if (s.controlMode && ctrlUploadLabel) ctrlUploadLabel.textContent = CTRL_LABELS[s.controlMode] || "Imagem de Controle";
    }
  }

  // Advanced panel aberto/fechado
  if (s.advOpen && advBody) {
    advBody.classList.add("open");
    if (advArrow) advArrow.classList.add("open");
  }

  // A3: restaurar Prompt Enhancer
  if (s.enhancer !== undefined) {
    imagePromptEnhancer = s.enhancer;
    document.querySelectorAll(".adv-enh-pill").forEach(p => {
      p.classList.toggle("active", (p.dataset.enh ?? "") === imagePromptEnhancer);
    });
    _updateEnhancerHint();
  }

  // Atualiza topbar e visibilidade de grupos após restaurar família
  applyFamilyCapabilities();
  updateTopbarModel();
}

// ── Job state persistence — Fase 3 ────────────────────────────
// Persiste job_id ativo para recovery ao voltar para a aba.
// Chave separada de STATE_KEY para não colidir com inputs da Fase 2.

function saveJobState(jId, lastStatus, lastProgress) {
  try {
    const existing = loadJobState();
    const sameJob  = existing?.job_id === jId;
    localStorage.setItem(JOB_STATE_KEY, JSON.stringify({
      job_id:        jId,
      tab:           "image",
      started_at:    sameJob ? (existing.started_at || Date.now()) : Date.now(),
      last_status:   lastStatus  ?? "queued",
      last_progress: lastProgress ?? 0,
      last_output:   sameJob ? (existing.last_output || null) : null,
      last_error:    null,
    }));
  } catch { /* quota exceeded — ignorar */ }
}

function loadJobState() {
  try { return JSON.parse(localStorage.getItem(JOB_STATE_KEY)); }
  catch { return null; }
}

function clearJobState({ output = null, error = null } = {}) {
  try {
    localStorage.setItem(JOB_STATE_KEY, JSON.stringify({
      job_id:        null,
      tab:           "image",
      started_at:    null,
      last_status:   null,
      last_progress: null,
      last_output:   output,
      last_error:    error,
    }));
  } catch { /* quota exceeded — ignorar */ }
}

async function checkJobRecovery() {
  let s;
  try { s = loadJobState(); } catch { return; }
  if (!s) return;

  // Sem job ativo mas há last_output da sessão anterior — exibir
  if (!s.job_id && s.last_output?.url) {
    try { showImage(fileUrl(s.last_output.url), s.last_output.filename, s.last_output.size_mb); }
    catch { /* output pode não existir mais no servidor */ }
    return;
  }

  if (!s.job_id) return;

  // Verificar expiração (6h)
  if (s.started_at && (Date.now() - s.started_at) > JOB_MAX_AGE_MS) {
    clearJobState();
    return;
  }

  // Consultar /status/{job_id}
  let data;
  try {
    const resp = await fetch(`/status/${s.job_id}`);
    if (resp.status === 404) {
      clearJobState();
      return; // servidor reiniciou — silencioso, sem mensagem de erro
    }
    data = await resp.json();
  } catch {
    clearJobState();
    return; // falha de rede — limpar sem quebrar UI
  }

  if (data.status === "done") {
    clearJobState({ output: data.output || null });
    if (data.output?.url) {
      try { showImage(fileUrl(data.output.url), data.output.filename, data.output.size_mb); } catch { }
      setStatus("Imagem pronta ✦ (gerada durante navegação)", "done");
      setTimeout(hideStatus, 5000);
      refreshGallery();
    }
    return;
  }

  if (data.status === "error") {
    clearJobState({ error: data.error || "Erro ao gerar" });
    setStatus("Erro na geração anterior: " + (data.error || "falha desconhecida"), "error");
    setTimeout(hideStatus, 6000);
    return;
  }

  if (data.status === "cancelled") {
    clearJobState();
    return; // silencioso
  }

  // Job ainda ativo (queued / running / generating) — retomar polling
  if (["queued", "running", "generating"].includes(data.status)) {
    jobId = s.job_id;
    setGenerating(true);
    genStartTime = s.started_at || Date.now(); // restaura timer real
    showPreviewState("loading");
    // Restaurar HUD com último estado salvo antes do polling retomar
    if (s.last_progress != null) {
      progressBar.style.width = `${s.last_progress}%`;
      if (hudPct) hudPct.textContent = `${Math.round(s.last_progress)}%`;
    }
    if (s.last_status && hudMainStatus)
      hudMainStatus.textContent = friendlyStep(s.last_status);
    addQueueJob(jobId, data.prompt || "");
    startPolling(jobId);
  }
}

// ── Monta dropdown filtrado pela família atual ────────────────
function renderPresetDropdown() {
  if (!presetSelect) return;

  const builtins = (BUILTIN_PRESETS[currentFamily] || []).map(p => ({ ...p, source: "builtin" }));
  const userAll  = loadUserPresets();
  // Mostra apenas presets do usuário salvos para a família atual
  const userFiltered = userAll.filter(p => !p.family || p.family === currentFamily);

  allPresets = [...userFiltered, ...builtins];

  let html = `<option value="">— Selecionar preset —</option>`;

  if (userFiltered.length) {
    html += `<optgroup label="★ Meus Presets">` +
      userFiltered.map((p, _) => {
        const i = allPresets.indexOf(p);
        return `<option value="${i}">${p.name}</option>`;
      }).join("") + `</optgroup>`;
  }

  if (builtins.length) {
    html += `<optgroup label="⟐ Estilos">` +
      builtins.map(p => {
        const i = allPresets.indexOf(p);
        return `<option value="${i}">${p.name}</option>`;
      }).join("") + `</optgroup>`;
  }

  presetSelect.innerHTML = html;
}

// ── Aplica preset selecionado ─────────────────────────────────
function applyPreset(idx) {
  const p = allPresets[idx];
  if (!p) return;

  if (p.prompt && promptTA) {
    promptTA.value = p.prompt;
    if (charCount) charCount.textContent = `${p.prompt.length} / 12000`;
  }
  if (p.negative && negativeTA) negativeTA.value = p.negative;

  if (p.family && modelSelect && p.family !== currentFamily) {
    modelSelect.value = p.family;
    currentFamily = p.family;
    applyFamilyCapabilities();
  }

  if (p.performance) {
    document.querySelectorAll(".perf-btn").forEach(b => {
      b.classList.toggle("active", b.dataset.perf === p.performance);
    });
    currentPerformance = p.performance;
  }

  if (p.format) {
    document.querySelectorAll(".fmt-btn").forEach(b => {
      b.classList.toggle("active", b.dataset.fmt === p.format);
    });
    currentFormat = p.format;
    renderResolutions(currentFormat);
  }

  if (p.resolution && resSelect) {
    const opt = [...resSelect.options].find(o => o.value === p.resolution);
    if (opt) { resSelect.value = p.resolution; currentResolution = p.resolution; }
  }

  if (p.steps && stepsInput) {
    stepsInput.value = p.steps;
    if (stepsVal) stepsVal.textContent = p.steps;
  }

  if (p.seed !== undefined) {
    seedValue = p.seed;
    if (seedSlider) seedSlider.value = p.seed === -1 ? 0 : p.seed;
    updateSeedDisplay();
  }

  // Aplica LoRAs do preset na lista de checkboxes
  const loraNames = Array.isArray(p.loras) ? p.loras : [];
  const mults     = (p.loras_multipliers || "").split(",").map(v => parseFloat(v) || 1.0);
  const lorasWithMult = loraNames.map((name, i) => ({ name, multiplier: mults[i] ?? 1.0 }));
  if (lorasWithMult.length) applyLorasToUI(lorasWithMult);

  // Reseta slider de intensidade para 1.00
  if (presetIntensity)    presetIntensity.value = 1;
  if (presetIntensityVal) presetIntensityVal.textContent = "1.00";

  updateTopbarModel();
  saveState(); // persiste o estado resultante do preset aplicado
  setStatus(`Preset "${p.name}" aplicado ✦`, "done");
  setTimeout(hideStatus, 2500);
}

presetApplyBtn?.addEventListener("click", () => {
  const val = presetSelect?.value;
  if (!val && val !== "0") {
    setStatus("Selecione um preset primeiro.", "info");
    setTimeout(hideStatus, 2000);
    return;
  }
  applyPreset(parseInt(val));
});

// ── Slider de intensidade do preset ──────────────────────────
const presetIntensity    = document.getElementById("preset-intensity");
const presetIntensityVal = document.getElementById("preset-intensity-val");

presetIntensity?.addEventListener("input", () => {
  const v = parseFloat(presetIntensity.value);
  if (presetIntensityVal) presetIntensityVal.textContent = v.toFixed(2);
  // Aplica a intensidade em todos os LoRAs ativos (vindos do preset)
  selectedLoras.forEach((l, i) => { l.multiplier = v; });
  // Atualiza sliders individuais da lista (se visíveis)
  loraList?.querySelectorAll(".lora-slider").forEach(sl => { sl.value = v; });
  loraList?.querySelectorAll("[id^='lora-val-']").forEach(el => {
    el.textContent = v.toFixed(2);
  });
});

const presetClearBtn = document.getElementById("preset-clear-btn");
presetClearBtn?.addEventListener("click", () => {
  if (presetSelect) presetSelect.value = "";
  loraList?.querySelectorAll(".lora-cb").forEach(cb => { cb.checked = false; });
  syncSelectedLoras();
  if (presetIntensity)    presetIntensity.value = 1;
  if (presetIntensityVal) presetIntensityVal.textContent = "1.00";
  setStatus("Preset limpo.", "info");
  setTimeout(hideStatus, 1800);
});

// ── Salva configuração atual como preset do usuário ───────────
presetSaveBtn?.addEventListener("click", () => {
  const name = prompt("Nome do preset:", "Meu Preset");
  if (!name?.trim()) return;
  const userPresets = loadUserPresets();
  const preset = {
    source:           "user",
    name:             name.trim(),
    family:           currentFamily,
    prompt:           promptTA?.value || "",
    negative:         negativeTA?.value || "",
    performance:      currentPerformance,
    format:           currentFormat,
    resolution:       currentResolution,
    steps:            parseInt(stepsInput?.value ?? "4") || 4,
    seed:             seedValue,
    loras:            selectedLoras.map(l => l.name),
    loras_multipliers:selectedLoras.map(l => l.multiplier.toFixed(2)).join(","),
    savedAt:          Date.now(),
  };
  const existing = userPresets.findIndex(p => p.name === preset.name && p.family === preset.family);
  if (existing >= 0) userPresets[existing] = preset;
  else userPresets.push(preset);
  saveUserPresets(userPresets);
  renderPresetDropdown();
  setStatus(`Preset "${preset.name}" salvo ✦`, "done");
  setTimeout(hideStatus, 2500);
});

// ── Inject Reference Images — mostra/esconde upload ──────────
injectSelect?.addEventListener("change", () => {
  const show = injectSelect.value !== "";
  refUploadGroup.style.display = show ? "flex" : "none";
  if (!show) clearRefImage();
  saveState();
});

// Drop zone — clique
refDropzone?.addEventListener("click", () => refFileInput.click());

// Drop zone — drag
refDropzone?.addEventListener("dragover", e => {
  e.preventDefault();
  refDropzone.classList.add("dz-over");
});
["dragleave", "dragend"].forEach(ev =>
  refDropzone?.addEventListener(ev, () => refDropzone.classList.remove("dz-over"))
);
refDropzone?.addEventListener("drop", e => {
  e.preventDefault();
  refDropzone.classList.remove("dz-over");
  const f = e.dataTransfer.files[0];
  if (f && f.type.startsWith("image/")) setRefImage(f);
});

// Input file
refFileInput?.addEventListener("change", () => {
  const f = refFileInput.files[0];
  if (f) setRefImage(f);
});

function setRefImage(file) {
  refImageFile = file;
  refImagePath = ""; // será preenchido ao gerar

  // Mostra thumbnail
  const reader = new FileReader();
  reader.onload = e => {
    refDropzone.classList.add("has-file");
    refDzContent.innerHTML = `
      <img class="ref-thumb" src="${e.target.result}" alt="referência" />
      <button class="ref-clear" id="ref-clear-btn">✕ Remover</button>`;
    document.getElementById("ref-clear-btn")?.addEventListener("click", ev => {
      ev.stopPropagation();
      clearRefImage();
    });
  };
  reader.readAsDataURL(file);
}

function clearRefImage() {
  refImageFile = null;
  refImagePath = "";
  refDropzone.classList.remove("has-file");
  refFileInput.value = "";
  refDzContent.innerHTML = `
    <span class="ref-dz-icon">⧉</span>
    <span class="ref-dz-label">Clique ou arraste a imagem</span>
    <span class="ref-dz-sub">PNG, JPG, WEBP</span>`;
}

// ── Control Image — mostra/esconde upload + muda label ────────
const CTRL_LABELS = {
  PV: "Imagem de Pose (foto com pessoa)",
  MV: "Imagem para Inpainting (com máscara)",
};

controlSelect?.addEventListener("change", () => {
  const val = controlSelect.value;
  const show = val !== "";
  ctrlUploadGroup.style.display = show ? "flex" : "none";
  if (show) ctrlUploadLabel.textContent = CTRL_LABELS[val] || "Imagem de Controle";
  if (!show) clearCtrlImage();
  saveState();
});

ctrlDropzone?.addEventListener("click", () => ctrlFileInput.click());
ctrlDropzone?.addEventListener("dragover", e => { e.preventDefault(); ctrlDropzone.classList.add("dz-over"); });
["dragleave", "dragend"].forEach(ev =>
  ctrlDropzone?.addEventListener(ev, () => ctrlDropzone.classList.remove("dz-over"))
);
ctrlDropzone?.addEventListener("drop", e => {
  e.preventDefault();
  ctrlDropzone.classList.remove("dz-over");
  const f = e.dataTransfer.files[0];
  if (f && f.type.startsWith("image/")) setCtrlImage(f);
});
ctrlFileInput?.addEventListener("change", () => {
  const f = ctrlFileInput.files[0];
  if (f) setCtrlImage(f);
});

function setCtrlImage(file) {
  ctrlImageFile = file;
  ctrlImagePath = "";
  const reader = new FileReader();
  reader.onload = e => {
    ctrlDropzone.classList.add("has-file");
    ctrlDzContent.innerHTML = `
      <img class="ref-thumb" src="${e.target.result}" alt="controle" />
      <button class="ref-clear" id="ctrl-clear-btn">✕ Remover</button>`;
    document.getElementById("ctrl-clear-btn")?.addEventListener("click", ev => {
      ev.stopPropagation();
      clearCtrlImage();
    });
  };
  reader.readAsDataURL(file);
}

function clearCtrlImage() {
  ctrlImageFile = null;
  ctrlImagePath = "";
  ctrlDropzone.classList.remove("has-file");
  ctrlFileInput.value = "";
  ctrlDzContent.innerHTML = `
    <span class="ref-dz-icon">⧉</span>
    <span class="ref-dz-label">Clique ou arraste a imagem</span>
    <span class="ref-dz-sub">PNG, JPG, WEBP</span>`;
}

// ── Advanced toggle ───────────────────────────────────────────
const advToggle = document.getElementById("adv-toggle");
const advArrow  = document.getElementById("adv-arrow");
const advBody   = document.getElementById("adv-body");
advToggle?.addEventListener("click", () => {
  const open = advBody.classList.toggle("open");
  advArrow.classList.toggle("open", open);
  saveState();
});

// ── ABORT ─────────────────────────────────────────────────────
btnAbort?.addEventListener("click", async () => {
  if (!jobId || !generating) return;
  try {
    await fetch(`/cancel/${jobId}`, { method: "POST" });
  } catch { /* ignora se não tiver endpoint */ }
  clearInterval(pollTimer);
  pollTimer = null;
  setGenerating(false);
  showPreviewState("empty");
  updateQueueJob(jobId, "cancelled");
  setStatus("Geração cancelada.", "info");
  setTimeout(hideStatus, 3000);
  jobId = null;
  clearJobState();
});

// ── FILA (queue panel toggle) ─────────────────────────────────
btnQueue?.addEventListener("click", (e) => {
  e.stopPropagation();
  const isOpen = queuePanel.style.display !== "none";
  queuePanel.style.display = isOpen ? "none" : "block";
});

// Fecha painel ao clicar fora
document.addEventListener("click", (e) => {
  if (!queuePanel.contains(e.target) && e.target !== btnQueue) {
    queuePanel.style.display = "none";
  }
});

// Limpar fila
queueClear?.addEventListener("click", () => {
  const active = jobQueue.filter(j => j.status === "running");
  jobQueue.length = 0;
  active.forEach(j => jobQueue.push(j));
  pendingQueue.length = 0;
  renderQueuePanel();
  updateQueueBadge();
});

// ── +FILA — adiciona prompt atual à fila pendente ─────────────
btnEnqueue?.addEventListener("click", () => {
  const prompt = promptTA?.value?.trim();
  if (!prompt) {
    promptTA.style.borderColor = "rgba(255,70,70,0.5)";
    setTimeout(() => { promptTA.style.borderColor = ""; }, 1500);
    return;
  }
  // Snapshot das configurações atuais
  const { model: snapModel, steps: snapPerfSteps } = resolveModel();
  const snapshot = {
    prompt,
    negative:        negativeTA?.value?.trim() || "",
    model:           snapModel,
    resolution:      currentResolution,
    performance:     currentPerformance,
    steps:           parseInt(stepsInput?.value ?? String(snapPerfSteps)) || snapPerfSteps,
    seed:            seedValue,
    injectImages:    injectSelect?.value  || "",
    controlMode:     controlSelect?.value || "",
    refImageFile:    refImageFile   || null,
    ctrlImageFile:   ctrlImageFile  || null,
    refImagePath:    refImagePath   || "",
    ctrlImagePath:   ctrlImagePath  || "",
    promptEnhancer:  imagePromptEnhancer,  // A3: captura estado atual do enhancer
  };
  pendingQueue.push(snapshot);
  // Adiciona ao painel de fila com status "queued"
  const tempId = `pending-${Date.now()}`;
  jobQueue.unshift({ id: tempId, prompt: prompt.slice(0, 60), status: "queued", progress: 0, _pending: true });
  renderQueuePanel();
  updateQueueBadge();
  setStatus(`Adicionado à fila (${pendingQueue.length} aguardando)`, "done");
  setTimeout(hideStatus, 2500);
  // Se nada gerando, inicia agora
  if (!generating) runNextPending();
});

// ── Helpers de fila ───────────────────────────────────────────
function addQueueJob(id, prompt) {
  jobQueue.unshift({ id, prompt: prompt.slice(0, 60), status: "running", progress: 0 });
  renderQueuePanel();
  updateQueueBadge();
}

function updateQueueJob(id, status, progress) {
  const j = jobQueue.find(x => x.id === id);
  if (!j) return;
  if (status !== undefined) j.status = status;
  if (progress !== undefined) j.progress = progress;
  renderQueuePanel();
  updateQueueBadge();
}

function updateQueueBadge() {
  const active = jobQueue.filter(j => j.status === "running" || j.status === "queued").length;
  if (active > 0) {
    queueBadge.textContent = active;
    queueBadge.style.display = "flex";
  } else {
    queueBadge.style.display = "none";
  }
}

function renderQueuePanel() {
  if (!jobQueue.length) {
    queueList.innerHTML = `<span class="queue-empty">Nenhum job na fila.</span>`;
    return;
  }
  queueList.innerHTML = jobQueue.map(j => {
    const dotClass = j.status === "running"   ? "running"
                   : j.status === "queued"    ? "queued"
                   : j.status === "done"      ? "done"
                   : j.status === "error"     ? "error"
                   : j.status === "cancelled" ? "cancelled"
                   : "";
    const pct = j.progress ? `${Math.round(j.progress)}%` : "";
    const label = j.status === "running"   ? `Gerando… ${pct}`
                : j.status === "queued"    ? "Aguardando…"
                : j.status === "done"      ? "Concluído"
                : j.status === "error"     ? "Erro"
                : j.status === "cancelled" ? "Cancelado"
                : j.status;
    return `
      <div class="queue-item">
        <span class="queue-item-dot ${dotClass}"></span>
        <div class="queue-item-info">
          <span class="queue-item-prompt">${j.prompt}</span>
          <span class="queue-item-status">${label}</span>
        </div>
      </div>`;
  }).join("");
}

// Inicia o próximo job pendente (chamado ao terminar geração ou ao clicar +FILA)
async function runNextPending() {
  if (generating || pendingQueue.length === 0) return;
  const next = pendingQueue.shift();
  // Atualiza o item de fila de "queued" → "running"
  const qItem = jobQueue.find(j => j._pending && j.status === "queued");
  if (qItem) { qItem._pending = false; }

  setGenerating(true);
  showPreviewState("loading");
  setStatus("Iniciando job da fila…", "loading");
  try {
    if (next.refImageFile && next.injectImages) {
      next.refImagePath = await uploadRefImage(next.refImageFile);
    }
    if (next.ctrlImageFile && next.controlMode) {
      next.ctrlImagePath = await uploadRefImage(next.ctrlImageFile);
    }
    const data = await startGeneration(next);
    jobId = data.job_id;
    saveJobState(jobId, "queued", 0);
    if (qItem) { qItem.id = jobId; qItem.status = "running"; }
    addQueueJob(jobId, next.prompt);
    startPolling(jobId);
  } catch (err) {
    console.error("[Queue] erro:", err);
    setStatus("Erro no job da fila.", "error");
    setGenerating(false);
    showPreviewState("empty");
  }
}

// Sidebar nav — agora são <a> links, sem handler JS necessário

// ── GENERATE ─────────────────────────────────────────────────
btnGenerate?.addEventListener("click", async () => {
  if (generating) return;

  // ── IMG-PERF T0: click_generate ──────────────────────────
  _imgPerf = { t0: performance.now() };
  window._imgPerf = _imgPerf;
  console.log(`[IMG-PERF] T0_click_generate  t=${_imgPerf.t0.toFixed(1)}ms`);

  const prompt = promptTA?.value?.trim();
  if (!prompt) {
    promptTA.style.borderColor = "rgba(255,70,70,0.5)";
    promptTA.focus();
    setTimeout(() => { promptTA.style.borderColor = ""; }, 1500);
    return;
  }

  // Validação: inject reference só funciona com flux2 9B ou superior
  if (refImageFile && injectSelect?.value && currentFamily === "flux2" && currentPerformance === "fast") {
    setStatus("Inject Reference requer Balanced ou Pro. Mudando para Balanced...", "info");
    document.querySelectorAll(".perf-btn").forEach(b => {
      b.classList.toggle("active", b.dataset.perf === "balanced");
    });
    currentPerformance = "balanced";
    updateTopbarModel();
    await new Promise(r => setTimeout(r, 800)); // deixa o status ser lido
  }

  setGenerating(true);
  showPreviewState("loading");
  setStatus("Enviando para o backend...", "loading");

  try {
    // Upload imagem de referência (inject)
    if (refImageFile && injectSelect?.value) {
      setStatus("Enviando imagem de referência...", "loading");
      _imgPerf.t_upload_ref_start = performance.now();
      try {
        refImagePath = await uploadRefImage(refImageFile);
        _imgPerf.t_upload_ref_done = performance.now();
        const _refMs = (_imgPerf.t_upload_ref_done - _imgPerf.t_upload_ref_start).toFixed(0);
        console.log(
          `[IMG-PERF] T7_upload_ref: ${_refMs}ms`
          + `  size=${refImageFile.size}B  type=${refImageFile.type}`
        );
      } catch (e) {
        setStatus("Erro ao enviar imagem de referência.", "error");
        setGenerating(false);
        return;
      }
    }

    // Upload imagem de controle (pose / inpaint)
    if (ctrlImageFile && controlSelect?.value) {
      setStatus("Enviando imagem de controle...", "loading");
      _imgPerf.t_upload_ctrl_start = performance.now();
      try {
        ctrlImagePath = await uploadRefImage(ctrlImageFile);
        _imgPerf.t_upload_ctrl_done = performance.now();
        const _ctrlMs = (_imgPerf.t_upload_ctrl_done - _imgPerf.t_upload_ctrl_start).toFixed(0);
        console.log(
          `[IMG-PERF] T7_upload_ctrl: ${_ctrlMs}ms`
          + `  size=${ctrlImageFile.size}B  type=${ctrlImageFile.type}`
        );
      } catch (e) {
        setStatus("Erro ao enviar imagem de controle.", "error");
        setGenerating(false);
        return;
      }
    }

    const { model: resolvedModel, steps: perfSteps } = resolveModel();
    const lorasPayload = getLorasPayload();
    const resolvedSteps = parseInt(stepsInput?.value ?? String(perfSteps)) || perfSteps;

    // ── IMG-PERF: payload audit + T_request_sent ─────────────
    const _payloadDebug = {
      model:      resolvedModel,
      steps:      resolvedSteps,
      resolution: currentResolution,
      seed:       seedValue,
      enhancer:   imagePromptEnhancer,
      inject:     injectSelect?.value  || "",
      ctrl:       controlSelect?.value || "",
      ref_sent:   !!refImagePath,
      ctrl_sent:  !!ctrlImagePath,
      loras:      lorasPayload.loras_choices?.length || 0,
      family:     currentFamily,
      perf:       currentPerformance,
    };
    console.log("[IMG-PERF] PAYLOAD", JSON.stringify(_payloadDebug));
    console.log(`[Image Payload] model="${resolvedModel}" steps=${resolvedSteps} enhancer="${imagePromptEnhancer}" resolution="${currentResolution}" family="${currentFamily}" perf="${currentPerformance}"`);
    window._lastImagePayload = _payloadDebug;
    _imgPerf.t_request_sent = performance.now();
    console.log(`[IMG-PERF] T_request_sent  +T0=${(_imgPerf.t_request_sent - _imgPerf.t0).toFixed(0)}ms`);

    const data = await startGeneration({
      prompt,
      negative:        negativeTA?.value?.trim() || "",
      model:           resolvedModel,
      resolution:      currentResolution,
      performance:     currentPerformance,
      steps:           resolvedSteps,
      seed:            seedValue,
      injectImages:    injectSelect?.value  || "",
      controlMode:     controlSelect?.value || "",
      refImagePath:    refImagePath  || "",
      ctrlImagePath:   ctrlImagePath || "",
      promptEnhancer:  imagePromptEnhancer,  // A3: "" = OFF, "T" = ON
      ...lorasPayload,
    });

    jobId = data.job_id;
    saveJobState(jobId, "queued", 0);

    // ── IMG-PERF: job_id recebido ─────────────────────────────
    _imgPerf.t_job_received = performance.now();
    const _httpMs    = (_imgPerf.t_job_received - _imgPerf.t_request_sent).toFixed(0);
    const _refUpMs   = _imgPerf.t_upload_ref_done
      ? (_imgPerf.t_upload_ref_done - _imgPerf.t_upload_ref_start).toFixed(0) : "—";
    const _ctrlUpMs  = _imgPerf.t_upload_ctrl_done
      ? (_imgPerf.t_upload_ctrl_done - _imgPerf.t_upload_ctrl_start).toFixed(0) : "—";
    const _frontendMs = (_imgPerf.t_job_received - _imgPerf.t0).toFixed(0);
    console.log(
      `[IMG-PERF] T_job_received  HTTP_/generate=${_httpMs}ms`
    );
    console.table({
      "T0→T_request_sent (ms)": (_imgPerf.t_request_sent - _imgPerf.t0).toFixed(0),
      "T7_upload_ref (ms)":     _refUpMs,
      "T7_upload_ctrl (ms)":    _ctrlUpMs,
      "HTTP_POST_/generate (ms)": _httpMs,
      "FRONTEND_TOTAL (ms)":    _frontendMs,
    });

    console.log("[Image Studio] Job:", jobId);
    addQueueJob(jobId, prompt);
    startPolling(jobId);

  } catch (err) {
    console.error("[Image Studio] Erro:", err);
    setStatus("Erro ao conectar com o backend.", "error");
    setGenerating(false);
    showPreviewState("empty");
  }
});

// ── Tradutor de mensagens técnicas → comerciais ───────────────
function friendlyStep(step) {
  if (!step) return "Inicializando...";
  const s = step.toLowerCase();
  if (s.includes("browser_session"))      return "Conectando ao motor de geração...";
  if (s.includes("change_model_family"))  return "Selecionando família de modelos...";
  if (s.includes("change_model_base"))    return "Configurando arquitetura...";
  if (s.includes("change_model("))        return "Carregando modelo de IA...";
  if (s.includes("change_resolution"))    return "Definindo resolução...";
  if (s.includes("save_inputs"))          return "Aplicando configurações...";
  if (s.includes("validate_wizard"))      return "Validando prompt...";
  if (s.includes("process_prompt"))       return "Processando prompt...";
  if (s.includes("process_tasks") || s.includes("gerando")) return "Gerando imagem...";
  if (s.includes("verificando"))          return "Finalizando...";
  if (s.includes("concluido") || s.includes("concluído")) return "Concluído ✦";
  // T11: cold start / loading states — mappings ausentes antes do fallback
  if (s.includes("iniciando geração"))    return "Iniciando...";
  if (s.includes("iniciando modelo"))     return "Carregando modelo de IA...";
  if (s.includes("baixando modelo") || s.includes("baixando modelos")) {
    // Sem tamanho hardcoded — backend não envia mais estimativa manual de GB.
    // Quando progresso real for implementado, virá de data.download.total_bytes.
    return "Baixando modelos necessários...\nIsso pode levar alguns minutos na primeira execução.";
  }
  if (s.includes("preparando modelo"))    return "Preparando modelo pela primeira vez...";
  if (s.includes("prepare_generate"))     return "Preparando geração...";
  return "Processando...";
}

// ── Download progress helpers ─────────────────────────────────
function _fmtSizeImg(mb) {
  if (mb == null) return "";
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${mb.toFixed(0)} MB`;
}
function _fmtEtaImg(sec) {
  if (sec == null || sec <= 0) return null;
  const m = Math.floor(sec / 60);
  const s = String(Math.floor(sec % 60)).padStart(2, "0");
  return `ETA ${m}:${s}`;
}
// Retorna string de stats reais ou null (frontend usa fallback honesto).
function _buildDlSubtextImg(dl) {
  try {
    if (!dl || !dl.active) return null;
    const parts = [];
    if (dl.percent   != null)                        parts.push(`${dl.percent.toFixed(1)}%`);
    if (dl.speed_mbps != null && dl.speed_mbps > 0)  parts.push(`${dl.speed_mbps.toFixed(1)} MB/s`);
    if (dl.downloaded_mb != null && dl.total_mb != null) {
      parts.push(`${_fmtSizeImg(dl.downloaded_mb)} / ${_fmtSizeImg(dl.total_mb)}`);
    } else if (dl.downloaded_mb != null) {
      parts.push(_fmtSizeImg(dl.downloaded_mb));
    }
    const eta = _fmtEtaImg(dl.eta_sec);
    if (eta) parts.push(eta);
    if (parts.length === 0) return null;
    let line = parts.join(" — ");
    // [FASE C / R-19] NÃO exibir nome técnico do modelo no HUD — só %/velocidade/tamanho/ETA.
    return line;
  } catch (_) { return null; }
}

// Stats de download: "99.2% — 10.9 MB/s — 11.7 GB / 11.8 GB — ETA 00:09"
function _buildDlStatsOnly(dl) {
  try {
    if (!dl || !dl.active) return null;
    const parts = [];
    if (dl.percent != null) parts.push(`${dl.percent.toFixed(1)}%`);
    if (dl.speed_mbps != null && dl.speed_mbps > 0)
      parts.push(`${dl.speed_mbps.toFixed(1)} MB/s`);
    if (dl.downloaded_mb != null && dl.total_mb != null)
      parts.push(`${_fmtSizeImg(dl.downloaded_mb)} / ${_fmtSizeImg(dl.total_mb)}`);
    else if (dl.downloaded_mb != null)
      parts.push(_fmtSizeImg(dl.downloaded_mb));
    const eta = _fmtEtaImg(dl.eta_sec);
    if (eta) parts.push(eta);
    return parts.length ? parts.join(" — ") : null;
  } catch { return null; }
}

// ── Timer de geração ─────────────────────────────────────────
const genInfoBar    = document.getElementById("gen-info-bar");
const genInfoStatus = document.getElementById("gen-info-status");
const genInfoTimer  = document.getElementById("gen-info-timer");
let   genTimerInterval = null;
let   genStartTime     = 0;

function startGenTimer() {
  genStartTime = Date.now();
  genInfoBar.style.display = "flex";
  genInfoTimer.textContent = "00:00";
  if (genTimerInterval) clearInterval(genTimerInterval);
  genTimerInterval = setInterval(() => {
    const s = Math.floor((Date.now() - genStartTime) / 1000);
    const mm = String(Math.floor(s / 60)).padStart(2, "0");
    const ss = String(s % 60).padStart(2, "0");
    genInfoTimer.textContent = `${mm}:${ss}`;
  }, 1000);
}

function stopGenTimer() {
  if (genTimerInterval) { clearInterval(genTimerInterval); genTimerInterval = null; }
  setTimeout(() => { genInfoBar.style.display = "none"; }, 3000);
}

function updateGenStatus(step) {
  if (genInfoStatus) genInfoStatus.textContent = friendlyStep(step);
}

// ── Polling ───────────────────────────────────────────────────
function startPolling(id) {
  if (pollTimer) clearInterval(pollTimer); // evita polling duplicado

  pollTimer = setInterval(async () => {
    try {
      const s = await pollStatus(id);
      const { status, step, progress, output, error, download } = s;

      // Progresso real de download — tem prioridade sobre progresso posicional
      const dlSub = _buildDlSubtextImg(download);
      const isDl  = download && download.active;

      if (isDl) {
        // HUD central — download real ativo
        const dlPct   = download.percent != null ? download.percent : 0;
        const dlStats = _buildDlStatsOnly(download);
        progressBar.style.width = `${dlPct}%`;
        if (hudMainStatus) hudMainStatus.textContent = "Baixando modelos necessários";
        if (hudPct)        hudPct.textContent        = `${dlPct.toFixed(1)}%`;
        progressLabel.textContent = "";
        if (previewDlSub)  previewDlSub.textContent  = dlStats || "";
        updateQueueJob(id, "running", dlPct);
      } else {
        if (progress != null) {
          progressBar.style.width = `${progress}%`;
          if (hudPct) hudPct.textContent = `${Math.round(progress)}%`;
          updateQueueJob(id, "running", progress);
        }
        if (step) {
          const friendly = friendlyStep(step);
          if (hudMainStatus) hudMainStatus.textContent = friendly;
          progressLabel.textContent = "";
          updateGenStatus(step);
        }
        if (previewDlSub) previewDlSub.textContent = "";
        if (hudDlCalm)    hudDlCalm.style.display   = "none";
      }

      // Persistir status/progresso atual para recovery (enquanto job ativo)
      // [B38-001] downloading_lora incluído — progresso visível durante LoRA DOD
      if (["queued", "running", "generating", "downloading_lora"].includes(status)) {
        saveJobState(id, status, isDl ? (download.percent ?? 0) : (progress ?? 0));
      }

      if (status === "done") {
        clearInterval(pollTimer);
        pollTimer = null;
        setGenerating(false);
        stopGenTimer();
        updateQueueJob(id, "done", 100);
        clearJobState({ output: output || null });
        if (window.playNotifBeep) playNotifBeep();

        // ── IMG-PERF T14: output received in browser ──────────
        if (_imgPerf) {
          _imgPerf.t14_output_received = performance.now();
          const _totalMs  = (_imgPerf.t14_output_received - _imgPerf.t0).toFixed(0);
          const _totalS   = (_totalMs / 1000).toFixed(2);
          const _frontMs  = _imgPerf.t_job_received
            ? (_imgPerf.t_job_received - _imgPerf.t0).toFixed(0) : "—";
          console.log(
            `[IMG-PERF] T14_output_received`
            + `  TOTAL_FRONTEND=${_totalMs}ms (${_totalS}s)`
            + `  T0→job_id=${_frontMs}ms  job_id→done=${(_imgPerf.t14_output_received - _imgPerf.t_job_received).toFixed(0)}ms`
          );
          console.log(
            `[IMG-PERF] ► To see backend breakdown: server logs [IMG-PERF] lines`
            + ` | curl http://localhost:8000/debug/last-image-payload`
          );
        }

        if (output?.url) {
          showImage(fileUrl(output.url), output.filename, output.size_mb);
          setStatus("Imagem gerada ✦", "done");
          setTimeout(() => hideStatus(), 4000);
          await refreshGallery();
        } else {
          showPreviewState("empty");
          setStatus("Gerado, mas sem arquivo.", "error");
        }
        setTimeout(runNextPending, 800);
      }

      if (status === "error") {
        clearInterval(pollTimer);
        pollTimer = null;
        setGenerating(false);
        stopGenTimer();
        updateQueueJob(id, "error");
        clearJobState({ error: error || "Erro ao gerar" });
        showPreviewState("empty");
        setStatus("Erro ao gerar imagem.", "error");
        setTimeout(runNextPending, 800);
      }

      if (status === "cancelled") {
        clearInterval(pollTimer);
        pollTimer = null;
        setGenerating(false);
        stopGenTimer();
        updateQueueJob(id, "cancelled");
        clearJobState();
        showPreviewState("empty");
        setStatus("Geração cancelada.", "info");
      }

      // 404: job desapareceu do servidor (restart do ACS?) — parar polling imediatamente
      if (status === "not_found") {
        clearInterval(pollTimer);
        pollTimer = null;
        jobId = null;
        setGenerating(false);
        stopGenTimer();
        clearJobState();
        showPreviewState("empty");
        setStatus("Job não encontrado — servidor reiniciado?", "error");
        setTimeout(hideStatus, 5000);
      }

    } catch (e) {
      console.warn("[Image Studio] poll error:", e);
    }
  }, 3000);
}

// ── Preview states ────────────────────────────────────────────
function showPreviewState(state) {
  previewEmpty.style.display   = state === "empty"   ? "flex" : "none";
  previewLoading.style.display = state === "loading" ? "flex" : "none";
  previewImgWrap.style.display = state === "image"   ? "block" : "none";
  if (state === "loading") {
    progressBar.style.width                        = "0%";
    progressLabel.textContent                      = "";
    if (previewDlSub)  previewDlSub.textContent    = "";
    if (hudMainStatus) hudMainStatus.textContent   = "Inicializando...";
    if (hudPct)        hudPct.textContent          = "0%";
    if (hudDlCalm)     hudDlCalm.style.display     = "none";
  }
}

function showImage(url, filename, sizeMb) {
  previewImg.src = url;
  previewImg.alt = filename || "Imagem gerada";
  // [B38-002] onerror: se arquivo não existe mais (reinstall/recovery),
  // restaura hero section e limpa localStorage para evitar loop.
  previewImg.onerror = () => {
    previewImgWrap.style.display = "none";
    previewEmpty.style.display   = "flex";
    try { localStorage.removeItem("acs:state:image"); } catch { /* quota */ }
    previewImg.onerror = null;  // evita disparo recursivo
  };
  previewImgWrap.style.display = "block";
  previewLoading.style.display = "none";
  previewEmpty.style.display   = "none";

  // Botões de ação
  // [B39-003] "Abrir" usa viewer interno (overlay) em vez de window.open(_blank),
  // que em pywebview abriria navegador externo (Edge/Chrome).
  document.getElementById("btn-open").onclick = () => _openInternalViewer(url, "image");
  // [B38-007] fetch/blob — garante download mesmo em pywebview sem Content-Disposition
  document.getElementById("btn-download").onclick = () => _downloadFile(url, filename || "image.jpg");
}

// ── Download helper — B38-007v2 ──────────────────────────────
// window.location + ?download=1 → servidor retorna Content-Disposition: attachment
// WebView2 reconhece o header e aciona download nativo do SO (sem a.click() tricks)
function _downloadFile(url, filename) {
  window.location.href = url + (url.includes("?") ? "&" : "?") + "download=1";
}

// ── Viewer interno — B39-003 + B39-004 ───────────────────────
// Overlay fullscreen dentro da janela pywebview (sem navegador externo).
// B39-004: controles de zoom FIXOS fora da área transformada; zoom por roda,
// pan ao arrastar (zoom>1), reset (botão + duplo-clique). Suporta image/video/audio.
//
// ARQUITETURA (chave do fix): a transform (scale/translate) é aplicada SOMENTE
// no elemento de mídia (#acs-viewer-media). Os controles ficam num container
// IRMÃO (#acs-viewer-bar), nunca dentro do elemento transformado — por isso
// nunca somem nem se movem com o zoom.
function _openInternalViewer(url, kind) {
  const prev = document.getElementById("acs-internal-viewer");
  if (prev) prev.remove();

  const ov = document.createElement("div");
  ov.id = "acs-internal-viewer";
  ov.style.cssText =
    "position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,.93);overflow:hidden;";

  // ── Stage: área que contém a mídia transformada (clip via overflow:hidden) ──
  const stage = document.createElement("div");
  stage.style.cssText =
    "position:absolute;inset:0;display:flex;align-items:center;justify-content:center;overflow:hidden;";

  let media;
  if (kind === "video") {
    media = document.createElement("video");
    media.src = url; media.controls = true; media.autoplay = true;
    media.style.cssText = "max-width:92vw;max-height:88vh;border-radius:8px;";
  } else if (kind === "audio") {
    media = document.createElement("audio");
    media.src = url; media.controls = true; media.autoplay = true;
    media.style.cssText = "width:min(520px,90vw);";
  } else {
    media = document.createElement("img");
    media.src = url;
    media.style.cssText =
      "max-width:92vw;max-height:88vh;border-radius:8px;object-fit:contain;" +
      "transform-origin:center center;will-change:transform;user-select:none;";
  }
  media.id = "acs-viewer-media";
  media.draggable = false;
  stage.appendChild(media);

  // ── Barra de controles FIXA (irmã do stage — fora da transform) ──
  const bar = document.createElement("div");
  bar.id = "acs-viewer-bar";
  bar.style.cssText =
    "position:absolute;top:14px;right:18px;z-index:5;display:flex;gap:8px;" +
    "background:rgba(0,0,0,.55);border:1px solid #333;border-radius:10px;padding:6px 8px;";

  const isImage = (kind !== "video" && kind !== "audio");

  // Estado de zoom/pan (apenas imagem)
  let scale = 1, tx = 0, ty = 0;
  const MIN = 1, MAX = 6, STEP = 0.25;
  function apply() {
    if (!isImage) return;
    media.style.transform = `translate(${tx}px, ${ty}px) scale(${scale})`;
    media.style.cursor = scale > 1 ? "grab" : "default";
  }
  function setScale(next, cx, cy) {
    if (!isImage) return;
    const old = scale;
    scale = Math.min(MAX, Math.max(MIN, next));
    if (scale === MIN) { tx = 0; ty = 0; }       // reset pan ao voltar a 100%
    apply();
    if (scale === old) return;
  }
  function reset() { scale = 1; tx = 0; ty = 0; apply(); }

  function mkBtn(label, title, fn) {
    const b = document.createElement("button");
    b.textContent = label; b.title = title;
    b.style.cssText =
      "min-width:34px;height:34px;font-size:16px;color:#fff;background:rgba(255,255,255,.08);" +
      "border:1px solid #444;border-radius:7px;cursor:pointer;line-height:1;";
    b.addEventListener("click", e => { e.stopPropagation(); fn(); });
    return b;
  }

  if (isImage) {
    bar.appendChild(mkBtn("−", "Zoom out", () => setScale(scale - STEP)));   // −
    bar.appendChild(mkBtn("+", "Zoom in", () => setScale(scale + STEP)));
    bar.appendChild(mkBtn("↺", "Reset zoom", reset));                        // ↺
  }
  const close = () => {
    try { if (media.pause) media.pause(); } catch {}
    ov.remove();
    document.removeEventListener("keydown", onKey);
  };
  bar.appendChild(mkBtn("✕", "Fechar (Esc)", close));                        // ✕

  // ── Zoom pela roda do mouse (apenas imagem) ──
  if (isImage) {
    stage.addEventListener("wheel", e => {
      e.preventDefault();
      setScale(scale + (e.deltaY < 0 ? STEP : -STEP));
    }, { passive: false });

    // ── Duplo-clique reseta ──
    media.addEventListener("dblclick", e => { e.stopPropagation(); reset(); });

    // ── Pan ao arrastar quando zoom > 1 ──
    let dragging = false, sx = 0, sy = 0;
    media.addEventListener("mousedown", e => {
      if (scale <= 1) return;
      dragging = true; sx = e.clientX - tx; sy = e.clientY - ty;
      media.style.cursor = "grabbing"; e.preventDefault();
    });
    window.addEventListener("mousemove", e => {
      if (!dragging) return;
      tx = e.clientX - sx; ty = e.clientY - sy; apply();
    });
    window.addEventListener("mouseup", () => {
      if (dragging) { dragging = false; media.style.cursor = scale > 1 ? "grab" : "default"; }
    });
  }

  // ── Fechar: clique fora (no stage, não na mídia) + Esc ──
  media.addEventListener("click", e => e.stopPropagation());
  stage.addEventListener("click", close);
  const onKey = e => { if (e.key === "Escape") close(); };
  document.addEventListener("keydown", onKey);

  ov.appendChild(stage);
  ov.appendChild(bar);
  document.body.appendChild(ov);
}

// ── UI state ──────────────────────────────────────────────────
function setGenerating(on) {
  generating = on;
  btnGenerate.disabled = on;
  btnGenerate.classList.toggle("generating", on);
  btnLabel.textContent = on ? "GERANDO..." : "GERAR";
  btnStar.style.animation = on ? "spin 1s linear infinite" : "";
  btnAbort.disabled = !on;
  btnAbort.classList.toggle("active", on);
  if (on) startGenTimer();
  updateQueueBadge();
}

// ── Status bar ────────────────────────────────────────────────
const statusBar = document.getElementById("status-bar");
function setStatus(msg, type = "info") {
  statusBar.textContent = msg;
  statusBar.className   = `status-bar visible ${type}`;
}
function hideStatus() {
  statusBar.classList.remove("visible");
}

// ── Gallery strip (thumbnails recentes) ──────────────────────
// Galeria completa está em /studio/gallery
async function refreshGallery() {
  const outputs = await loadOutputs();
  galleryThumbs.innerHTML = "";
  if (!outputs.length) return;

  // Strip: mostra os 20 mais recentes
  outputs.slice(0, 20).forEach(o => {
    const url = fileUrl(o.url);
    const div = document.createElement("div");
    div.className = "gallery-thumb";
    div.title     = o.title || o.name || "";

    const img = document.createElement("img");
    img.src     = url;
    img.alt     = o.title || "";
    img.loading = "lazy";

    img.addEventListener("load", () => {
      const ratio = img.naturalWidth / img.naturalHeight;
      const w = Math.min(Math.max(Math.round(72 * ratio), 44), 136);
      div.style.width = `${w}px`;
    });

    div.appendChild(img);
    img.draggable = false;   // [FIX-DRAG] o drag é do card, não do <img> nativo
    div.draggable = true;
    div.addEventListener("dragstart", e => {
      const payload = JSON.stringify({ url: url, type: "image", name: o.name || "" });
      try { e.dataTransfer.setData("application/x-acs-media", payload); } catch (_) {}
      try { e.dataTransfer.setData("text/plain", payload); } catch (_) {}
      try { e.dataTransfer.setData("text/uri-list", url); } catch (_) {}
      try { e.dataTransfer.effectAllowed = "copy"; } catch (_) {}
    });

    div.addEventListener("click", () => {
      document.querySelectorAll(".gallery-thumb").forEach(t => t.classList.remove("active"));
      div.classList.add("active");
      showImage(url, o.name, o.size_mb);
    });

    galleryThumbs.appendChild(div);
    // Botão delete (compartilhado via gallery-delete.js)
    if (window.attachGalleryDeleteBtn) window.attachGalleryDeleteBtn(div, o.name);
  });
}

// ── Model info display (Advanced Drawer) ─────────────────────
// Mostra o modelo real (chave backend) para auditabilidade.
function _updateModelInfo() {
  const el = document.getElementById("adv-model-info");
  if (!el) return;
  const entry = PERF_MODEL_MAP[currentFamily]?.[currentPerformance];
  if (!entry) { el.textContent = ""; return; }
  // Mapeamento família+preset → model_id real (audit label)
  const MODEL_ID_MAP = {
    flux2: { fast: "flux2_klein_4b", balanced: "flux2_klein_9b", bf16: "flux2_klein_9b_bf16" },
    z_image: { fast: "z_image", balanced: "z_image", bf16: "z_image", pro: "z_image" },
    ideogram4: { fast: "ideogram4_turbotime", balanced: "ideogram4_turbotime", bf16: "ideogram4_turbotime", pro: "ideogram4_turbotime" },
    krea2: { fast: "krea2_turbo", balanced: "krea2_raw", bf16: "krea2_raw", pro: "krea2_raw" },
  };
  const modelId = MODEL_ID_MAP[currentFamily]?.[currentPerformance] ?? entry.model;
  el.textContent = `▸ ${entry.model}  ·  ${modelId}  ·  ${entry.steps} steps default`;
}

// ── Init ──────────────────────────────────────────────────────
// Restaura estado persistido antes das chamadas assíncronas.
// restoreState() roda após todo o setup síncrono do DOM, garantindo que
// elements, PERF_MODEL_MAP e CTRL_LABELS já estão disponíveis.
_initEnhancerPills();  // A3: inicializa listeners dos pills (antes de restoreState para que restore funcione)
restoreState();
_updateModelInfo();    // A4: popula label de modelo no boot

// Paralelo: health + gallery + loras em simultâneo (não dependem uma da outra)
(async () => {
  renderPresetDropdown(); // síncrono — usa currentFamily já restaurado

  // Fase 3: verificar se há job ativo ou output da sessão anterior
  await checkJobRecovery();

  const [healthResult] = await Promise.allSettled([
    checkHealth().then(h => {
      if (h.status === "ok") {
        setStatus("ACS Studio conectado ✦", "done");
        setTimeout(hideStatus, 3000);
      }
    }).catch(() => {
      setStatus("Backend offline. Inicie o acs_api.py.", "error");
    }),
    refreshGallery(),
    loadLoras(),
  ]);

  setInterval(refreshGallery, 15000);  // T-POL: auto-refresh galeria Image a cada 15s
})();

// bfcache guard: limpar timer de polling ao sair da página para evitar polling fantasma
// após restauração de sessão do Chrome (bfcache preserva heap JS incluindo setInterval ativos).
// jobId NÃO é zerado aqui — localStorage é a fonte da verdade para recovery (Fase 3).
window.addEventListener("pagehide", () => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
});
