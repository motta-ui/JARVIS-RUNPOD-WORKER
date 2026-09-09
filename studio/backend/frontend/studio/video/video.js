if(!window.playNotifBeep){var _ns=document.createElement("script");_ns.src="/studio/notif.js?v=1";document.head.appendChild(_ns)}
/* ============================================================
   ACS Studio — Video Module  v29
   Wan2GP params preservados · modo-strip · addons · áudio
   v14: modos roteados para wrappers específicos da API
   v15: I2V cinematic slot — mode-i2v class + CSS targeting
   v16: advanced drawer, frames display, advanced params wired,
        drawer close/toggle, prompt_enhancer toggle
        /generate/t2v · /generate/i2v · /generate/flf · /generate/continue
   v29: LoRA capability system — avisos para LoRAs especiais,
        bloqueio de combos inválidos, Advanced Mode layout reorganizado
============================================================ */

/* ── Mapeamento modo → endpoint wrapper ───────────────────
   Cada modo usa seu endpoint dedicado com schema limpo.
   t2i ainda usa /generate genérico (não tem wrapper próprio).
─────────────────────────────────────────────────────────── */
const MODE_ENDPOINTS = {
  t2v:      "/generate/t2v",
  i2v:      "/generate/i2v",
  flf:      "/generate/flf",
  continue: "/generate/continue",
  t2i:      "/generate",        // fallback: endpoint genérico
  animate:  "/generate/i2v",   // [12.25] Animar Personagem (Scail2) — i2v + V1 + foto pessoa
};

const RES_MATRIX = {
  "9:16":  { fast: "480x832",  balanced: "720x1280",  pro: "1088x1920", "2k": "1440x2560" },
  "16:9":  { fast: "832x480",  balanced: "1280x720",  pro: "1920x1088", "2k": "2560x1440" },
  "1:1":   { fast: "624x624",  balanced: "832x832",   pro: "1024x1024", "2k": "1440x1440" },
  "4:3":   { fast: "832x624",  balanced: "1024x768",  pro: "1280x960"  },
  "21:9":  { fast: "832x352",  balanced: "1280x544",  pro: "1920x816"  },
};

// Opções 2K disponíveis somente para família ltx2 — adicionadas/removidas dinamicamente
// por updateLtx2ResOptions(). Não editar o HTML do res-select para estas opções.
// [PHASE2] Valores agora são WxH diretos (eram "9:16-2k" etc.)
const LTX2_RES_OPTIONS = [
  { value: "1440x2560", label: "2K High VRAM — 1440 × 2560", ratio: "9:16" },
  { value: "2560x1440", label: "2K High VRAM — 2560 × 1440", ratio: "16:9" },
  { value: "1440x1440", label: "2K High VRAM — 1440 × 1440", ratio: "1:1"  },
];

/* ── [PHASE2] Lookup reverso: WxH → ratio ──────────────────
   Construído automaticamente de RES_MATRIX + 2K options.
   Usado por initResSelect() para sincronizar format pills.
─────────────────────────────────────────────────────────── */
const RES_TO_RATIO = (() => {
  const m = {};
  for (const [ratio, qs] of Object.entries(RES_MATRIX)) {
    for (const res of Object.values(qs)) m[res] = ratio;
  }
  m["1440x2560"] = "9:16";
  m["2560x1440"] = "16:9";
  m["1440x1440"] = "1:1";
  return m;
})();

/* ── [PHASE2] Resolução padrão por ratio ───────────────────
   Usada por syncResSelect() quando format pill muda.
─────────────────────────────────────────────────────────── */
const RATIO_DEFAULT_RES = {
  "9:16":  "720x1280",
  "16:9":  "1280x720",
  "1:1":   "832x832",
  "4:3":   "1024x768",
  "21:9":  "1280x544",
};

/* ── [PHASE2] Migração de estado antigo ────────────────────
   Converte "ratio-quality" (ex: "9:16-balanced") → WxH.
─────────────────────────────────────────────────────────── */
function _migrateResValue(oldVal) {
  if (!oldVal || typeof oldVal !== "string") return null;
  if (/^\d+x\d+$/.test(oldVal)) return oldVal;   // já é WxH
  const dash = oldVal.indexOf("-");
  if (dash < 0) return null;
  const ratio   = oldVal.slice(0, dash);
  const quality = oldVal.slice(dash + 1);
  return (RES_MATRIX[ratio] || {})[quality] || null;
}

/* ── Estado ────────────────────────────────────────────── */
let currentMode     = "t2v";
let currentRatio    = "9:16";
let currentQuality  = "balanced";
let currentJobId    = null;
let pollInterval    = null;
const activeAddons  = new Set();   // "end-frame" | "ctrl-video" | "frame-inj"

// Estado LoRA — até 2 LoRAs simultâneos com intensidade individual
let lastVideoOutput = null; // [ESTENDER] último vídeo gerado {url, filename, path} — fonte do botão Estender
let selectedLoras  = [];   // [{filename: string, multiplier: number}]
let availableLoras = [];   // [{name, filename, label, size_mb}] — cache do /loras endpoint

const uploadedPaths = {
  start: null,   // ref / start-frame / source-video
  end:   null,   // end frame addon
  inj2:  null,   // frame inject slot 2
  inj3:  null,   // frame inject slot 3
  ctrl:  null,   // ctrl video (I2V addon — separado do start frame)
  audio: null,   // audio/soundtrack
};

let dynamicInjectPaths = [];   // caminhos para slots inject 4, 5, 6…
let dynamicInjectCount  = 3;   // último número de slot criado

/* ── Persistência de estado (UI State Persistence v1) ──────── */
const VIDEO_STATE_KEY = "acs_video_state_v1";
const VID_JOB_STATE_KEY  = "acs:state:video";
const VID_JOB_MAX_AGE_MS = 6 * 60 * 60 * 1000;  // 6h
let _stateReady = false;   // evita sobrescrever localStorage durante init (antes de restoreState)

/* ── Phase 3: Job State Persistence ────────────────────────── */
function vidSaveJobState(jId, lastStatus, lastProgress) {
  try {
    const ex = vidLoadJobState();
    const same = ex?.job_id === jId;
    localStorage.setItem(VID_JOB_STATE_KEY, JSON.stringify({
      job_id:        jId,
      tab:           "video",
      started_at:    same ? (ex.started_at || Date.now()) : Date.now(),
      last_status:   lastStatus  ?? "queued",
      last_progress: lastProgress ?? 0,
      last_output:   same ? (ex.last_output || null) : null,
      last_error:    null,
    }));
  } catch { }
}

function vidLoadJobState() {
  try { return JSON.parse(localStorage.getItem(VID_JOB_STATE_KEY)); }
  catch { return null; }
}

function vidClearJobState({ output = null, error = null } = {}) {
  try {
    localStorage.setItem(VID_JOB_STATE_KEY, JSON.stringify({
      job_id: null, tab: "video", started_at: null,
      last_status: null, last_progress: null,
      last_output: output, last_error: error,
    }));
  } catch { }
}

async function vidCheckJobRecovery() {
  let s;
  try { s = vidLoadJobState(); } catch { return; }
  if (!s) return;
  // last_output from previous session — show player
  if (!s.job_id && s.last_output?.url) {
    try { showVideoPlayer(s.last_output.url, s.last_output.filename, s.last_output.size_mb); } catch { }
    return;
  }
  if (!s.job_id) return;
  if (s.started_at && (Date.now() - s.started_at) > VID_JOB_MAX_AGE_MS) { vidClearJobState(); return; }
  let data;
  try {
    const resp = await fetch(`/status/${s.job_id}`);
    if (resp.status === 404) { vidClearJobState(); return; }
    data = await resp.json();
  } catch { vidClearJobState(); return; }
  if (data.status === "done") {
    vidClearJobState({ output: data.output || null });
    if (data.output?.url) {
      // [ESTENDER 2026-06-27] guarda o último vídeo (com path local) pro botão Estender
      lastVideoOutput = /\.(mp4|webm|mov)$/i.test(data.output.filename || "") ? data.output : null;
      try { showVideoPlayer(data.output.url, data.output.filename, data.output.size_mb); } catch { }
      loadRecentOutputs();
    }
    return;
  }
  if (data.status === "error") {
    vidClearJobState({ error: data.error || "Erro" });
    progressSetFailed("Erro na geração anterior: " + (data.error || "falha desconhecida"));
    return;
  }
  if (data.status === "cancelled") { vidClearJobState(); return; }
  if (["queued", "running", "generating"].includes(data.status)) {
    currentJobId = s.job_id;
    document.getElementById("btn-generate")?.classList.add("generating");
    const pct = s.last_progress ?? 0;
    progressSetGenerating(pct, s.last_status || "Retomando...", null, null);
    vidShowCanvasHud(pct, s.last_status || "Retomando...", null, null);
    startPolling();
  }
}

/** Aplica modo do Prompt Enhancer: "" = OFF | "T" = Enhance | "T1" = Prompt Relay */
function _setEnhancerMode(el, mode) {
  el.dataset.mode = mode;
  el.classList.toggle("active", mode !== "");
  el.classList.toggle("relay-mode", mode === "T1");
  if (mode === "T1") { el.textContent = "RELAY"; }
  else if (mode === "T") { el.textContent = "ENHANCE"; }
  else { el.textContent = "OFF"; }
  // [PROMPT-RELAY 2026-06-27] tooltip explicativo por modo (helper do formato no RELAY)
  el.title = mode === "T1"
    ? 'Prompt Relay: direcione trechos do tempo do vídeo. Use [início%:fim%]texto. '
      + 'Ex: [0%:50%]dia ensolarado [50%:100%]noite estrelada'
    : mode === "T" ? "Melhora seu prompt automaticamente antes de gerar"
    : "Aprimoramento de prompt desligado";
}

function saveState() {
  if (!_stateReady) return;
  try {
    localStorage.setItem(VIDEO_STATE_KEY, JSON.stringify({
      prompt:        document.getElementById("prompt-input")?.value        ?? "",
      negative:      document.getElementById("negative-input")?.value      ?? "",
      model:         document.getElementById("model-select")?.value        ?? "",
      steps:         document.getElementById("steps-select")?.value        ?? "",
      mode:          currentMode,
      ratio:         currentRatio,
      quality:       currentQuality,
      duration:      parseInt(document.getElementById("dur-slider")?.value  ?? "5")  || 5,
      resolution:    document.getElementById("res-select")?.value           ?? "",
      seed:          parseInt(document.getElementById("seed-input")?.value  ?? "-1") || -1,
      activeAddons:  Array.from(activeAddons),
      selectedLoras: selectedLoras.map(l => ({ filename: l.filename, multiplier: l.multiplier })),
      drawerOpen:    document.getElementById("advanced-drawer")?.classList.contains("open") ?? false,
      enhancer:      document.getElementById("adv-enhancer")?.dataset.mode ?? "",  // [A2] "" | "T" | "T1"
      guidancePhases: document.querySelector(".adv-phase-pill.active")?.dataset.phase ?? "",  // [G2] "" | "1" | "2"
      // [ADV-1177] Advanced Mode selects
      advRiflex:     document.getElementById("adv-riflex")?.value         ?? "0",
      advTemporal:   document.getElementById("adv-temporal")?.value       ?? "",
      advSelfRef:    document.getElementById("adv-self-refiner")?.value   ?? "0",
      advSpatial:    document.getElementById("adv-spatial")?.value        ?? "",
      advFps:        document.getElementById("adv-fps")?.value            ?? "",
    }));
  } catch { /* quota exceeded — ignorar silenciosamente */ }
}

function restoreState() {
  let s;
  try { s = JSON.parse(localStorage.getItem(VIDEO_STATE_KEY)); } catch { s = null; }
  if (!s || typeof s !== "object") return;

  // Prompt
  const promptEl = document.getElementById("prompt-input");
  if (promptEl && typeof s.prompt === "string") {
    promptEl.value = s.prompt;
    const cc = document.getElementById("char-count");
    if (cc) cc.textContent = `${s.prompt.length} / 12000`;
  }

  // Mode pills + cfg select
  if (typeof s.mode === "string" && s.mode) {
    currentMode = s.mode;
    document.querySelectorAll(".mpill[data-mode]").forEach(b => {
      b.classList.toggle("active", b.dataset.mode === currentMode);
    });
    const cfgSel = document.getElementById("mode-select-cfg");
    if (cfgSel) cfgSel.value = currentMode;
  }

  // Format (ratio) pills
  if (typeof s.ratio === "string" && s.ratio) {
    currentRatio = s.ratio;
    document.querySelectorAll(".cfg-fmt-btn[data-ratio]").forEach(b => {
      b.classList.toggle("active", b.dataset.ratio === currentRatio);
    });
  }

  // Quality pills
  if (typeof s.quality === "string" && s.quality) {
    currentQuality = s.quality;
    document.querySelectorAll(".cfg-qpill[data-quality]").forEach(b => {
      b.classList.toggle("active", b.dataset.quality === currentQuality);
    });
  }

  // Duration slider
  if (typeof s.duration === "number" && s.duration > 0) {
    const durEl = document.getElementById("dur-slider");
    if (durEl) {
      durEl.value = s.duration;
      if (_durationDisplayUpdate) _durationDisplayUpdate();
    }
  }

  // [PHASE2] Resolution: migra estado antigo "ratio-quality" → WxH direto
  if (typeof s.resolution === "string" && s.resolution) {
    const resEl = document.getElementById("res-select");
    if (resEl) {
      let resVal = _migrateResValue(s.resolution) || s.resolution;
      if ([...resEl.options].some(o => o.value === resVal)) {
        resEl.value = resVal;
      } else {
        resEl.value = "720x1280";  // fallback seguro
      }
      // Sincroniza format pills a partir da resolução restaurada
      const ratio = RES_TO_RATIO[resEl.value];
      if (ratio) {
        currentRatio = ratio;
        document.querySelectorAll(".cfg-fmt-btn[data-ratio]").forEach(b => {
          b.classList.toggle("active", b.dataset.ratio === currentRatio);
        });
      }
    }
  }

  // Seed input
  if (typeof s.seed === "number") {
    const seedEl = document.getElementById("seed-input");
    if (seedEl) seedEl.value = s.seed >= 0 ? String(s.seed) : "";
  }

  // Active addons Set + pills
  if (Array.isArray(s.activeAddons)) {
    activeAddons.clear();
    s.activeAddons.forEach(a => activeAddons.add(a));
    document.querySelectorAll(".apill[data-addon]").forEach(b => {
      b.classList.toggle("active", activeAddons.has(b.dataset.addon));
    });
    updateAddonSubs();
  }

  // LoRA — restaura novo formato ou migra silenciosamente do formato antigo
  // Nota: loadLoras() já populou #lora-list antes de restoreState() ser chamado
  {
    let lorasToRestore = [];
    if (Array.isArray(s.selectedLoras) && s.selectedLoras.length) {
      // Novo formato: [{filename, multiplier}]
      lorasToRestore = s.selectedLoras;
    } else if (typeof s.appliedLora === "string" && s.appliedLora) {
      // Migração silenciosa do formato antigo (appliedLora + appliedWeight)
      lorasToRestore = [{ filename: s.appliedLora, multiplier: s.appliedWeight ?? 1.0 }];
    }
    // [PERF-FIX v63] NÃO restaura loras salvas AO ABRIR o app: o estado da sessão anterior
    // aplicava loras stale no modelo novo => geração LENTA + mormaço (vs Gradio nativo limpo
    // = 84s p/ 5s). Começa LIMPO; o usuário adiciona manualmente quando quer. Não mexe no
    // save de prompt/aba (sua regra). Ref: cowboy seed192899528 tinha 2 loras + RIFLEx stale.
    void lorasToRestore;  // mantido p/ compat de leitura; intencionalmente NÃO aplicado
  }

  // Negative prompt
  if (typeof s.negative === "string") {
    const negEl = document.getElementById("negative-input");
    if (negEl) negEl.value = s.negative;
  }

  // Model select — restoreState() roda após loadModels() que já populou as options
  if (typeof s.model === "string" && s.model) {
    const selEl = document.getElementById("model-select");
    if (selEl && [...selEl.options].some(o => o.value === s.model)) {
      selEl.value = s.model;
    }
  }

  // Steps select — restaura após modelo (que pode ter setado um default)
  if (typeof s.steps === "string" && s.steps) {
    const stepsEl = document.getElementById("steps-select");
    if (stepsEl && [...stepsEl.options].some(o => o.value === s.steps)) {
      stepsEl.value = s.steps;
    }
  }

  // Advanced drawer open state
  if (s.drawerOpen === true) {
    document.getElementById("advanced-drawer")?.classList.add("open");
    document.querySelectorAll(".ptab").forEach(t => t.classList.remove("active"));
    document.querySelector(".ptab[data-tab='avancado']")?.classList.add("active");
  }

  // [A3] Prompt Enhancer — restaura estado salvo: "" | "T" | "T1"
  {
    const enhEl = document.getElementById("adv-enhancer");
    if (enhEl) {
      // backwards compat: true (bool) → "T"
      const mode = (s.enhancer === true) ? "T" : (s.enhancer || "");
      _setEnhancerMode(enhEl, mode);
    }
  }

  // [G2] Guidance Phases — restaura pill selecionada (default Auto="" quando ausente)
  {
    const savedPhase = typeof s.guidancePhases === "string" ? s.guidancePhases : "";
    document.querySelectorAll(".adv-phase-pill").forEach(pill => {
      const isActive = pill.dataset.phase === savedPhase;
      pill.classList.toggle("active", isActive);
    });
    _updatePhasesHint();
  }

  // [ADV-1177] Advanced Mode selects — restaura valores
  {
    const _setAdv = (id, val, fallback) => {
      const el = document.getElementById(id);
      if (el && val !== undefined && val !== null) el.value = val ?? fallback ?? el.options[0]?.value ?? "";
    };
    // [PERF-FIX v63] NÃO restaura o Modo Avançado AO ABRIR (RIFLEx/temporal/self-refiner/
    // spatial stale = lento + mormaço). Default LIMPO = performance do Gradio nativo.
    // O usuário liga manualmente quando quer (Modo Avançado é manual, escolha dele).
    // RIFLEx ligado em vídeo curto é a causa nº1 do mormaço.
    void s.advRiflex; void s.advTemporal; void s.advSelfRef; void s.advSpatial; void s.advFps;
  }

  // Sync media zones com modo + addons restaurados
  updateMediaZones();
}

/* ── Boot ──────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", async () => {
  initTabs();
  initAdvancedDrawer();
  initI2VStrength();
  initPrompt();
  initDuration();
  initFormat();
  initQuality();
  initModePills();
  initModeCfgSelect();
  initAddonPills();
  initResSelect();
  initRefZone();
  initEndFrameZone();
  initInjectZone2();
  initInjectZone3();
  initCtrlVideoZone();
  initAddFrameBtn();
  initAudioZone();
  initAudioMode();
  initSeedRand();
  initPresetCol();
  initGenerateBtn();
  initAbortBtn();
  await vidCheckJobRecovery();  // Phase 3: restaura job ativo ou último output
  loadModels();          // async — restoreState() chamado dentro após modelos+loras resolverem
  loadRecentOutputs();
  updateMediaZones();   // sync dock class on boot

  // Hooks de persistência para campos não cobertos pelos init* acima
  document.getElementById("steps-select")?.addEventListener("change", saveState);
  document.getElementById("negative-input")?.addEventListener("input", saveState);
  // [ADV-1177] Persistência dos selects do Advanced Drawer
  ["adv-riflex","adv-temporal","adv-self-refiner","adv-spatial","adv-fps"]
    .forEach(id => document.getElementById(id)?.addEventListener("change", saveState));
  // [ADV-1177] Persistência dos selects do Advanced Drawer
  ["adv-riflex","adv-temporal","adv-self-refiner","adv-spatial","adv-fps"]
    .forEach(id => document.getElementById(id)?.addEventListener("change", saveState));
  // model-select: saveState() já é chamado via onModelChange (wired em loadModels)
});

/* ══════════════════════════════════════════════════════
   I2V SOURCE STRENGTH — slider com display ao vivo
══════════════════════════════════════════════════════ */
function initI2VStrength() {
  const slider = document.getElementById("i2v-source-strength");
  const valEl  = document.getElementById("i2v-ss-val");
  if (slider && valEl) {
    slider.addEventListener("input", () => {
      valEl.textContent = parseFloat(slider.value).toFixed(2);
    });
  }
}

/* ══════════════════════════════════════════════════════
   ADVANCED DRAWER — controles Wan2GP
══════════════════════════════════════════════════════ */
function initAdvancedDrawer() {
  // Sliders com display de valor ao vivo
  const sliders = [
    { id: "adv-guidance",  valId: "adv-guidance-val",  decimals: 1 },
    { id: "adv-grain-int", valId: "adv-grain-int-val", decimals: 2 },
    { id: "adv-grain-sat", valId: "adv-grain-sat-val", decimals: 2 },
  ];
  sliders.forEach(({ id, valId, decimals }) => {
    const slider = document.getElementById(id);
    const valEl  = document.getElementById(valId);
    if (slider && valEl) {
      slider.addEventListener("input", () => {
        valEl.textContent = parseFloat(slider.value).toFixed(decimals);
      });
    }
  });

  // Botão fechar
  const closeBtn = document.getElementById("adv-close");
  if (closeBtn) {
    closeBtn.addEventListener("click", () => {
      document.getElementById("advanced-drawer")?.classList.remove("open");
      document.querySelectorAll(".ptab").forEach(t => t.classList.remove("active"));
      document.querySelector(".ptab[data-tab='simples']")?.classList.add("active");
      saveState();
    });
  }

  // Prompt Enhancer — ciclo 3 estados: OFF → ENHANCE → RELAY → OFF
  // "" → "T" → "T1" → "" (salvo em data-mode)
  const enhBtn = document.getElementById("adv-enhancer");
  if (enhBtn) {
    enhBtn.addEventListener("click", () => {
      const cur = enhBtn.dataset.mode || "";
      const next = cur === "" ? "T" : (cur === "T" ? "T1" : "");
      _setEnhancerMode(enhBtn, next);
      // [PROMPT-RELAY] ao ligar o RELAY, mostra o formato (senão o cliente não descobre)
      if (next === "T1" && typeof showToast === "function") {
        showToast("Prompt Relay ligado — direcione trechos: [0%:50%]dia ensolarado [50%:100%]noite estrelada", "info", 6000);
      }
      saveState();
    });
  }

  // [G2] Guidance Phases pills — Auto / 1 Phase / 2 Phases
  document.querySelectorAll(".adv-phase-pill").forEach(pill => {
    pill.addEventListener("click", () => {
      document.querySelectorAll(".adv-phase-pill").forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
      _updatePhasesHint();
      saveState();
    });
  });
}

/** [G2] Atualiza hint text do Guidance Phases conforme pill ativa */
function _updatePhasesHint() {
  const hint = document.getElementById("adv-phases-hint");
  if (!hint) return;
  const active = document.querySelector(".adv-phase-pill.active")?.dataset.phase ?? "";
  const HINTS = {
    "":  "Pipeline automático por modelo",
    "1": "1 fase — Stage 1 full-res (mais lento)",
    "2": "2 fases — Stage 1 half-res + Stage 2 denoise (recomendado)",
  };
  hint.textContent = HINTS[active] ?? "Pipeline automático por modelo";
}

/* ══════════════════════════════════════════════════════
   TABS (Simples / Avançado)
══════════════════════════════════════════════════════ */
function initTabs() {
  document.querySelectorAll(".ptab").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".ptab").forEach(t => t.classList.remove("active"));
      tab.classList.add("active");
      const drawer = document.getElementById("advanced-drawer");
      if (drawer) drawer.classList.toggle("open", tab.dataset.tab === "avancado");
      saveState();
    });
  });
}

/* ══════════════════════════════════════════════════════
   PROMPT
══════════════════════════════════════════════════════ */
function initPrompt() {
  const ta = document.getElementById("prompt-input");
  const cc = document.getElementById("char-count");
  if (ta && cc) {
    ta.addEventListener("input", () => { cc.textContent = `${ta.value.length} / 12000`; saveState(); });
  }
}

/* ══════════════════════════════════════════════════════
   DURAÇÃO — helpers de cálculo de frames
   Espelha _MODEL_FAMILY_FRAME_PARAMS + _seconds_to_video_length do backend.
   Usado apenas para display — o payload continua enviando duration em segundos.
══════════════════════════════════════════════════════ */
const _FAMILY_FRAME_PARAMS = {
  // family       fps  latent  minFrames
  ltx2:        { fps: 24, latent: 8, minFrames: 17 },
  ltx:         { fps: 24, latent: 8, minFrames: 17 },
  ltxv:        { fps: 24, latent: 8, minFrames: 17 },
  wan:         { fps: 16, latent: 4, minFrames:  5 },
  wan2_2:      { fps: 16, latent: 4, minFrames:  5 },
  hunyuan:     { fps: 25, latent: 4, minFrames:  5 },
  hunyuan_1_5: { fps: 25, latent: 4, minFrames:  5 },
};
let _durationDisplayUpdate = null;  // ref exposta para onModelChange

function _calcVideoLength(secs, modelId) {
  const info   = modelsCache.find(m => m.id === modelId);
  const p      = _FAMILY_FRAME_PARAMS[info?.family];
  if (!p) return secs * 24;  // fallback: familia desconhecida
  const raw     = secs * p.fps;
  const aligned = Math.round(raw / p.latent) * p.latent + 1;
  return Math.max(p.minFrames, aligned);
}

function initDuration() {
  const slider   = document.getElementById("dur-slider");
  const label    = document.getElementById("dur-val");
  const framesEl = document.getElementById("dur-frames");
  if (slider && label) {
    const update = () => {
      const s = parseInt(slider.value);
      label.textContent   = `${s}s`;
      if (framesEl) framesEl.textContent = `= ${_calcVideoLength(s, document.getElementById("model-select")?.value || "")}f`;
    };
    _durationDisplayUpdate = update;
    slider.addEventListener("input", update);
    slider.addEventListener("input", saveState);
    update(); // sync on boot
  }
}

/* ══════════════════════════════════════════════════════
   FORMATO — cfg-fmt-btn com ícones
══════════════════════════════════════════════════════ */
function initFormat() {
  document.querySelectorAll(".cfg-fmt-btn[data-ratio]").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".cfg-fmt-btn").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentRatio = btn.dataset.ratio;
      syncResSelect();
      saveState();
    });
  });
}

/* ══════════════════════════════════════════════════════
   QUALIDADE — cfg-qpill (Fast / Balanced / Pro)
   [FIX-BLOCKER-01] Presets implementados — alteram steps e temporal_upsampling.
   Fast:     steps=8  (distilled explícito), sem temporal upsampling
   Balanced: steps=Auto (model.default_steps), sem temporal upsampling
   Pro:      steps=20, temporal_upsampling=rife2
   Resolution continua vindo exclusivamente do res-select.
══════════════════════════════════════════════════════ */
function initQuality() {
  const QUALITY_PRESETS = {
    fast:     { steps: "8",  temporal: ""      },   // 8 steps distilled, sem RIFE
    balanced: { steps: "",   temporal: ""      },   // Auto/model default, sem RIFE
    pro:      { steps: "20", temporal: "rife2" },   // 20 steps + RIFE temporal upsampling
  };

  document.querySelectorAll(".cfg-qpill[data-quality]").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".cfg-qpill").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentQuality = btn.dataset.quality;
      const preset  = QUALITY_PRESETS[currentQuality] || QUALITY_PRESETS.balanced;
      const stepsEl = document.getElementById("steps-select");
      const tempEl  = document.getElementById("adv-temporal");
      if (stepsEl && stepsEl.value !== preset.steps)    stepsEl.value  = preset.steps;
      if (tempEl  && tempEl.value  !== preset.temporal) tempEl.value   = preset.temporal;
      saveState();
    });
  });
}

/* ══════════════════════════════════════════════════════
   MODE PILLS (faixa topo)
══════════════════════════════════════════════════════ */
// [12.25] Seleciona um modelo no dropdown se ele existir (modos dedicados)
function _selectModelIfPresent(modelId) {
  const ms = document.getElementById("model-select");
  if (ms && [...ms.options].some(o => o.value === modelId && !o.disabled)) {
    ms.value = modelId;
    ms.dispatchEvent(new Event("change"));
  }
}

// [12.25] Revela os pills de modo dedicado só quando o modelo correspondente existe
// (env-gated: sem ACS_GRADIO_API_V2 os modelos novos não vêm em /models → pill fica oculto)
function _syncDedicatedModePills() {
  // [12.25] "Animar Personagem" foi MOVIDO pra aba Motion → fica oculto aqui na Vídeo.
  // (a lógica do modo "animate" permanece dormente; o pill/opção nunca aparecem)
  const animate = document.querySelector('.mpill[data-mode="animate"]');
  if (animate) animate.style.display = "none";
  const animateOpt = document.querySelector('#mode-select-cfg option[value="animate"]');
  if (animateOpt) animateOpt.hidden = true;
}

function initModePills() {
  document.querySelectorAll(".mpill[data-mode]").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".mpill[data-mode]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentMode = btn.dataset.mode;
      // [12.25] Modos dedicados auto-selecionam o modelo certo no dropdown
      if (currentMode === "animate") _selectModelIfPresent("Character Animate");
      // sync cfg select
      const cfgSel = document.getElementById("mode-select-cfg");
      if (cfgSel) cfgSel.value = currentMode;
      updateMediaZones();
      saveState();
    });
  });
}

/* ══════════════════════════════════════════════════════
   MODE SELECT (cfg column) — sincroniza com mode pills
══════════════════════════════════════════════════════ */
function initModeCfgSelect() {
  const sel = document.getElementById("mode-select-cfg");
  if (!sel) return;
  sel.addEventListener("change", () => {
    currentMode = sel.value;
    if (currentMode === "animate") _selectModelIfPresent("Character Animate");
    document.querySelectorAll(".mpill[data-mode]").forEach(b => {
      b.classList.toggle("active", b.dataset.mode === currentMode);
    });
    updateMediaZones();
    saveState();
  });
}

/* ══════════════════════════════════════════════════════
   ADDON PILLS
══════════════════════════════════════════════════════ */
function initAddonPills() {
  document.querySelectorAll(".apill[data-addon]").forEach(btn => {
    btn.addEventListener("click", () => {
      const addon = btn.dataset.addon;
      if (activeAddons.has(addon)) {
        activeAddons.delete(addon);
        btn.classList.remove("active");
      } else {
        activeAddons.add(addon);
        btn.classList.add("active");
      }
      updateMediaZones();
      updateAddonSubs();
      saveState();
    });
  });
}

function updateAddonSubs() {
  const ctrlSub = document.getElementById("ctrl-sub");
  const injSub  = document.getElementById("inj-sub");
  if (ctrlSub) ctrlSub.style.display = activeAddons.has("ctrl-video") ? "flex" : "none";
  if (injSub)  injSub.style.display  = activeAddons.has("frame-inj")  ? "flex" : "none";
}

/* ══════════════════════════════════════════════════════
   ATUALIZA ZONAS DE MÍDIA com base no modo + addons
══════════════════════════════════════════════════════ */
function updateMediaZones() {
  const zoneEnd  = document.getElementById("zone-end");
  const zoneRef  = document.getElementById("zone-ref");
  const refLabel = document.getElementById("ref-label");
  const endLabel = zoneEnd?.querySelector(".zone-label");

  // ── End frame zone ─────────────────────────────────────
  // FLF: sempre visível (ambos os frames são obrigatórios)
  // Outros modos: visível apenas se addon "end-frame" ativo
  const showEnd = currentMode === "flf" || currentMode === "continue" || activeAddons.has("end-frame");
  if (zoneEnd) zoneEnd.style.display = showEnd ? "" : "none";

  // Label do end frame: contexto de FLF / Continue / addon
  if (endLabel) {
    if (currentMode === "flf")           endLabel.textContent = "END FRAME (OBRIGATÓRIO)";
    else if (currentMode === "continue") endLabel.textContent = "END FRAME (OPC.)";
    else                                 endLabel.textContent = "END FRAME";
  }

  // ── Ref zone label ─────────────────────────────────────
  if (refLabel) {
    const labels = {
      t2v:      "IMAGEM / VÍDEO DE<br>REFERÊNCIA",
      i2v:      "START FRAME<br>(IMAGEM)",
      flf:      "START FRAME<br>(IMAGEM)",
      continue: "VÍDEO FONTE<br>(CONTINUE)",
      t2i:      "IMAGEM DE<br>REFERÊNCIA",
      animate:  "FOTO DA PESSOA<br>(foto real)",
    };
    // Em T2V os addons mudam o propósito da zona de referência
    // Em I2V os addons são aditivos — zona ref continua sendo START FRAME
    if (currentMode === "t2v" && activeAddons.has("frame-inj")) {
      refLabel.innerHTML = "INJECT 1";
    } else if (currentMode === "t2v" && activeAddons.has("ctrl-video")) {
      refLabel.innerHTML = "CTRL VÍDEO<br>(VÍDEO / IMAGEM)";
    } else {
      refLabel.innerHTML = labels[currentMode] || labels.t2v;
    }
  }

  // Ref zone sempre visível
  if (zoneRef) zoneRef.style.display = "";

  // ── Ctrl Video zone (I2V only) ─────────────────────────
  const zoneCtrl = document.getElementById("zone-ctrl");
  if (zoneCtrl) {
    // [12.25] modo "animate" (Scail2): zona de vídeo de movimento SEMPRE visível
    const showCtrl = (currentMode === "i2v" && activeAddons.has("ctrl-video")) || currentMode === "animate";
    zoneCtrl.style.display = showCtrl ? "" : "none";
    const ctrlLbl = zoneCtrl.querySelector(".zone-label");
    if (ctrlLbl) ctrlLbl.innerHTML = (currentMode === "animate") ? "VÍDEO DE<br>MOVIMENTO" : "CTRL VÍDEO";
  }

  // ── Add Frame button (frame-inj ativo em T2V ou I2V) ───
  const addBtn = document.getElementById("zone-add-inject");
  if (addBtn) {
    const showAdd = activeAddons.has("frame-inj") &&
                    (currentMode === "t2v" || currentMode === "i2v");
    addBtn.style.display = showAdd ? "" : "none";
  }

  // ── Aplica classe de modo + classes de addon no dock ───
  const dock = document.getElementById("gen-dock");
  if (dock) {
    // Remove classes anteriores de modo e addon
    dock.className = dock.className
      .replace(/\bmode-\S+\b/g, "")
      .replace(/\baddon-\S+\b/g, "")
      .trim();
    dock.classList.add(`mode-${currentMode}`);
    // Adiciona uma classe por addon activo (ex: "addon-frame-inj", "addon-ctrl-video")
    activeAddons.forEach(a => dock.classList.add(`addon-${a}`));
  }
}

/* ══════════════════════════════════════════════════════
   RESOLUÇÃO SELECT
   [PHASE2] Valor agora é WxH direto (ex: "1280x720").
   Sincroniza APENAS format pills (ratio via RES_TO_RATIO).
   Quality pills NÃO são sincronizados — são independentes.
══════════════════════════════════════════════════════ */
function initResSelect() {
  const sel = document.getElementById("res-select");
  if (!sel) return;
  sel.addEventListener("change", () => {
    // [PHASE2] Detecta ratio via lookup reverso WxH → ratio
    const ratio = RES_TO_RATIO[sel.value];
    if (ratio) {
      currentRatio = ratio;
      document.querySelectorAll(".cfg-fmt-btn[data-ratio]").forEach(b => {
        b.classList.toggle("active", b.dataset.ratio === currentRatio);
      });
    }
    // [PHASE2] Quality pills NÃO sincronizados — resolução e qualidade são independentes
    saveState();
  });
}

function syncResSelect() {
  // [PHASE2] Chamada por initFormat() quando format pill muda.
  // Define res-select para a resolução padrão do ratio (quality-independente).
  const sel = document.getElementById("res-select");
  if (!sel) return;
  const targetRes = RATIO_DEFAULT_RES[currentRatio] || "720x1280";
  for (const opt of sel.options) {
    if (opt.value === targetRes) { sel.value = targetRes; return; }
  }
}

/* ══════════════════════════════════════════════════════
   SEED RANDOMIZER
══════════════════════════════════════════════════════ */
function initSeedRand() {
  const btn   = document.getElementById("seed-rand");
  const input = document.getElementById("seed-input");
  if (btn && input) {
    btn.addEventListener("click", () => {
      input.value = Math.floor(Math.random() * 2147483647);
      saveState();
    });
    input.addEventListener("change", saveState);
  }
}

/* ══════════════════════════════════════════════════════
   ZONA REF (Start Frame / Source Video)
══════════════════════════════════════════════════════ */
function initRefZone() {
  const zone     = document.getElementById("drop-start");
  const inputEl  = document.getElementById("file-start");
  const clearBtn = document.getElementById("ref-clear");
  if (!zone || !inputEl) return;

  zone.addEventListener("click", e => { if (e.target !== clearBtn) inputEl.click(); });
  inputEl.addEventListener("change", e => {
    if (e.target.files[0]) handleRefFile(e.target.files[0]);
  });
  zone.addEventListener("dragover",  e => { e.preventDefault(); zone.classList.add("drag-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", e => {
    e.preventDefault(); zone.classList.remove("drag-over");
    if (e.dataTransfer.files[0]) handleRefFile(e.dataTransfer.files[0]);
  });
  if (clearBtn) {
    clearBtn.addEventListener("click", e => { e.stopPropagation(); clearRefZone(); });
  }
}

async function handleRefFile(file) {
  showToast(`Carregando ${file.name}…`);
  try {
    const form = new FormData();
    form.append("file", file);
    const res  = await fetch("/upload-ref", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Upload falhou");
    uploadedPaths.start = data.path;
    showRefPreview(file);
    hideToast();
  } catch (err) {
    showToast(`Erro: ${err.message}`, "err");
    setTimeout(hideToast, 3500);
  }
}

function showRefPreview(file) {
  const zone  = document.getElementById("drop-start");
  const thumb = document.getElementById("ref-thumb");
  if (!zone || !thumb) return;
  zone.classList.add("has-file");
  if (file.type.startsWith("image/")) {
    thumb.innerHTML = "";
    thumb.style.cssText = `background-image:url(${URL.createObjectURL(file)});background-size:cover;background-position:center`;
  } else if (file.type.startsWith("video/")) {
    // [FIX-DRAG-PREVIEW] mostra miniatura do vídeo (antes era só um quadrado escuro,
    // dando a impressão de que o arraste não tinha funcionado).
    thumb.style.cssText = "background:#000;overflow:hidden";
    thumb.innerHTML = `<video src="${URL.createObjectURL(file)}" muted playsinline preload="metadata" style="width:100%;height:100%;object-fit:cover"></video>`;
  } else {
    thumb.innerHTML = "";
    thumb.style.cssText = "background:#1a1a1a";
  }
}

function clearRefZone() {
  uploadedPaths.start = null;
  const zone  = document.getElementById("drop-start");
  const thumb = document.getElementById("ref-thumb");
  const input = document.getElementById("file-start");
  if (zone)  zone.classList.remove("has-file");
  // [FIX-CLEAR 2026-06-26] vídeo é mostrado via innerHTML (<video>) — cssText="" sozinho NÃO o
  // remove, deixava a miniatura na tela após o (x). Limpa innerHTML também.
  if (thumb) { thumb.innerHTML = ""; thumb.style.cssText = ""; }
  if (input) input.value = "";
}

/* ══════════════════════════════════════════════════════
   ZONA END FRAME (addon)
══════════════════════════════════════════════════════ */
function initEndFrameZone() {
  const zone     = document.getElementById("drop-end");
  const inputEl  = document.getElementById("file-end");
  const clearBtn = document.getElementById("end-clear");
  if (!zone || !inputEl) return;

  zone.addEventListener("click", e => { if (e.target !== clearBtn) inputEl.click(); });
  inputEl.addEventListener("change", e => {
    if (e.target.files[0]) handleEndFrameFile(e.target.files[0]);
  });
  zone.addEventListener("dragover",  e => { e.preventDefault(); zone.classList.add("drag-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", e => {
    e.preventDefault(); zone.classList.remove("drag-over");
    if (e.dataTransfer.files[0]) handleEndFrameFile(e.dataTransfer.files[0]);
  });
  if (clearBtn) {
    clearBtn.addEventListener("click", e => { e.stopPropagation(); clearEndFrameZone(); });
  }
}

async function handleEndFrameFile(file) {
  showToast(`End frame: ${file.name}…`);
  try {
    const form = new FormData();
    form.append("file", file);
    const res  = await fetch("/upload-ref", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Upload falhou");
    uploadedPaths.end = data.path;
    showEndFramePreview(file);
    hideToast();
  } catch (err) {
    showToast(`Erro: ${err.message}`, "err");
    setTimeout(hideToast, 3500);
  }
}

function showEndFramePreview(file) {
  const zone  = document.getElementById("drop-end");
  const thumb = document.getElementById("end-thumb");
  if (!zone || !thumb) return;
  zone.classList.add("has-file");
  if (file.type.startsWith("image/")) {
    thumb.style.cssText = `background-image:url(${URL.createObjectURL(file)});background-size:cover;background-position:center`;
  } else {
    thumb.style.cssText = "background:#1a1a1a";
  }
}

function clearEndFrameZone() {
  uploadedPaths.end = null;
  const zone  = document.getElementById("drop-end");
  const thumb = document.getElementById("end-thumb");
  const input = document.getElementById("file-end");
  if (zone)  zone.classList.remove("has-file");
  if (thumb) thumb.style.cssText = "";
  if (input) input.value = "";
}

/* ══════════════════════════════════════════════════════
   ZONAS INJECT 2 e 3 (Frame Injection multi-slot)
══════════════════════════════════════════════════════ */
function _makeInjectZoneHandler(dropId, fileId, thumbId, clearId, pathKey) {
  const zone     = document.getElementById(dropId);
  const inputEl  = document.getElementById(fileId);
  const clearBtn = document.getElementById(clearId);
  if (!zone || !inputEl) return;

  async function handleFile(file) {
    showToast(`Inject ${pathKey.slice(-1)}: ${file.name}…`);
    try {
      const form = new FormData();
      form.append("file", file);
      const res  = await fetch("/upload-ref", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload falhou");
      uploadedPaths[pathKey] = data.path;
      // preview
      const thumb = document.getElementById(thumbId);
      if (thumb) thumb.style.cssText = `background-image:url(${URL.createObjectURL(file)});background-size:cover;background-position:center`;
      zone.classList.add("has-file");
      hideToast();
    } catch (err) {
      showToast(`Erro: ${err.message}`, "err");
      setTimeout(hideToast, 3500);
    }
  }

  zone.addEventListener("click", e => { if (e.target !== clearBtn) inputEl.click(); });
  inputEl.addEventListener("change", e => { if (e.target.files[0]) handleFile(e.target.files[0]); });
  zone.addEventListener("dragover",  e => { e.preventDefault(); zone.classList.add("drag-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", e => {
    e.preventDefault(); zone.classList.remove("drag-over");
    if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
  });
  if (clearBtn) {
    clearBtn.addEventListener("click", e => {
      e.stopPropagation();
      uploadedPaths[pathKey] = null;
      const thumb = document.getElementById(thumbId);
      const inp   = document.getElementById(fileId);
      if (zone)  zone.classList.remove("has-file");
      if (thumb) thumb.style.cssText = "";
      if (inp)   inp.value = "";
    });
  }
}

function initInjectZone2() {
  _makeInjectZoneHandler("drop-inj2", "file-inj2", "inj2-thumb", "inj2-clear", "inj2");
}
function initInjectZone3() {
  _makeInjectZoneHandler("drop-inj3", "file-inj3", "inj3-thumb", "inj3-clear", "inj3");
}

/* ══════════════════════════════════════════════════════
   ZONA CTRL VIDEO (I2V addon — slot separado do start)
══════════════════════════════════════════════════════ */
function initCtrlVideoZone() {
  const zone     = document.getElementById("drop-ctrl");
  const inputEl  = document.getElementById("file-ctrl");
  const clearBtn = document.getElementById("ctrl-clear");
  if (!zone || !inputEl) return;

  async function handleFile(file) {
    showToast(`Ctrl video: ${file.name}…`);
    try {
      const form = new FormData();
      form.append("file", file);
      const res  = await fetch("/upload-ref", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload falhou");
      uploadedPaths.ctrl = data.path;
      const thumb = document.getElementById("ctrl-thumb");
      if (thumb) {
        if (file.type.startsWith("image/")) {
          thumb.innerHTML = "";
          thumb.style.cssText = `background-image:url(${URL.createObjectURL(file)});background-size:cover;background-position:center`;
        } else if (file.type.startsWith("video/")) {
          // [FIX-DRAG-PREVIEW] miniatura do vídeo de controle (antes: quadrado escuro)
          thumb.style.cssText = "background:#000;overflow:hidden";
          thumb.innerHTML = `<video src="${URL.createObjectURL(file)}" muted playsinline preload="metadata" style="width:100%;height:100%;object-fit:cover"></video>`;
        } else {
          thumb.innerHTML = "";
          thumb.style.cssText = "background:#1a1a1a";
        }
      }
      zone.classList.add("has-file");
      hideToast();
    } catch (err) {
      showToast(`Erro: ${err.message}`, "err");
      setTimeout(hideToast, 3500);
    }
  }

  zone.addEventListener("click", e => { if (e.target !== clearBtn) inputEl.click(); });
  inputEl.addEventListener("change", e => { if (e.target.files[0]) handleFile(e.target.files[0]); });
  zone.addEventListener("dragover",  e => { e.preventDefault(); zone.classList.add("drag-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", e => {
    e.preventDefault(); zone.classList.remove("drag-over");
    if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
  });
  if (clearBtn) {
    clearBtn.addEventListener("click", e => {
      e.stopPropagation();
      uploadedPaths.ctrl = null;
      const thumb = document.getElementById("ctrl-thumb");
      const inp   = document.getElementById("file-ctrl");
      if (zone)  zone.classList.remove("has-file");
      if (thumb) { thumb.innerHTML = ""; thumb.style.cssText = ""; }  // [FIX-CLEAR] remove <video> do innerHTML
      if (inp)   inp.value = "";
    });
  }
}

/* ══════════════════════════════════════════════════════
   BOTÃO ADD FRAME + ZONAS DINÂMICAS (inject 4, 5, 6…)
══════════════════════════════════════════════════════ */
function _makeDynamicInjectHandler(dropId, fileId, thumbId, clearId, arrIndex) {
  const zone     = document.getElementById(dropId);
  const inputEl  = document.getElementById(fileId);
  const clearBtn = document.getElementById(clearId);
  if (!zone || !inputEl) return;

  async function handleFile(file) {
    showToast(`Inject frame: ${file.name}…`);
    try {
      const form = new FormData();
      form.append("file", file);
      const res  = await fetch("/upload-ref", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload falhou");
      dynamicInjectPaths[arrIndex] = data.path;
      const thumb = document.getElementById(thumbId);
      if (thumb) thumb.style.cssText = `background-image:url(${URL.createObjectURL(file)});background-size:cover;background-position:center`;
      zone.classList.add("has-file");
      hideToast();
    } catch (err) {
      showToast(`Erro: ${err.message}`, "err");
      setTimeout(hideToast, 3500);
    }
  }

  zone.addEventListener("click", e => { if (e.target !== clearBtn) inputEl.click(); });
  inputEl.addEventListener("change", e => { if (e.target.files[0]) handleFile(e.target.files[0]); });
  zone.addEventListener("dragover",  e => { e.preventDefault(); zone.classList.add("drag-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", e => {
    e.preventDefault(); zone.classList.remove("drag-over");
    if (e.dataTransfer.files[0]) handleFile(e.dataTransfer.files[0]);
  });
  if (clearBtn) {
    clearBtn.addEventListener("click", e => {
      e.stopPropagation();
      dynamicInjectPaths[arrIndex] = null;
      const thumb = document.getElementById(thumbId);
      const inp   = document.getElementById(fileId);
      if (zone)  zone.classList.remove("has-file");
      if (thumb) thumb.style.cssText = "";
      if (inp)   inp.value = "";
    });
  }
}

function initAddFrameBtn() {
  const btn = document.getElementById("zone-add-inject");
  if (!btn) return;
  btn.addEventListener("click", () => {
    dynamicInjectCount++;
    const slotNum = dynamicInjectCount;
    const arrIdx  = dynamicInjectPaths.length;
    dynamicInjectPaths.push(null);   // reserva espaço no array

    const extra = document.getElementById("zone-inj-extra");
    if (!extra) return;

    const zone = document.createElement("div");
    zone.className = "media-zone media-zone-inj";
    zone.id = `zone-inj${slotNum}`;
    zone.innerHTML = `
      <span class="zone-label" style="color:rgba(180,242,70,.3)">INJECT ${slotNum}</span>
      <div class="zone-drop" id="drop-inj${slotNum}">
        <input type="file" id="file-inj${slotNum}" accept="image/*" hidden />
        <div class="zone-thumb" id="inj${slotNum}-thumb"></div>
        <div class="zone-empty">
          <span class="zone-icon">⧉</span>
          <span class="zone-txt">Frame ${slotNum}</span>
          <span class="zone-sub">PNG · JPG</span>
        </div>
        <button class="zone-clear" id="inj${slotNum}-clear">✕</button>
      </div>`;
    extra.appendChild(zone);

    _makeDynamicInjectHandler(
      `drop-inj${slotNum}`, `file-inj${slotNum}`,
      `inj${slotNum}-thumb`, `inj${slotNum}-clear`,
      arrIdx
    );
  });
}

/* ══════════════════════════════════════════════════════
   ZONA ÁUDIO
══════════════════════════════════════════════════════ */
function initAudioZone() {
  const zone     = document.getElementById("drop-audio");
  const inputEl  = document.getElementById("file-audio");
  const clearBtn = document.getElementById("audio-clear");
  if (!zone || !inputEl) return;

  zone.addEventListener("click", e => { if (e.target !== clearBtn) inputEl.click(); });
  inputEl.addEventListener("change", e => {
    if (e.target.files[0]) handleAudioFile(e.target.files[0]);
  });
  zone.addEventListener("dragover",  e => { e.preventDefault(); zone.classList.add("drag-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", e => {
    e.preventDefault(); zone.classList.remove("drag-over");
    if (e.dataTransfer.files[0]) handleAudioFile(e.dataTransfer.files[0]);
  });
  if (clearBtn) {
    clearBtn.addEventListener("click", e => {
      e.stopPropagation();
      clearAudioZone();
    });
  }
}

async function handleAudioFile(file) {
  showToast(`Áudio: ${file.name}…`);
  try {
    const form = new FormData();
    form.append("file", file);
    const res  = await fetch("/upload-audio", { method: "POST", body: form });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Upload falhou");
    uploadedPaths.audio = data.path;
    showAudioPreview(file);
    hideToast();
  } catch (err) {
    showToast(`Erro: ${err.message}`, "err");
    setTimeout(hideToast, 3500);
  }
}

function showAudioPreview(file) {
  const preview  = document.getElementById("audio-preview");
  const empty    = document.getElementById("audio-empty");
  const nameEl   = document.getElementById("audio-name");
  const waveEl   = document.getElementById("audio-waveform");
  const clearBtn = document.getElementById("audio-clear");
  const zone     = document.getElementById("drop-audio");
  if (!preview) return;
  preview.style.display = "flex";
  if (empty)    empty.style.display    = "none";
  if (clearBtn) clearBtn.style.display = "";
  if (zone)     zone.classList.add("has-file");

  const short = file.name.length > 22 ? file.name.substring(0, 19) + "…" : file.name;
  if (nameEl) nameEl.textContent = short;

  // Gera barras de waveform decorativas
  if (waveEl) {
    waveEl.innerHTML = "";
    const bars = 28;
    for (let i = 0; i < bars; i++) {
      const h = 20 + Math.random() * 60;
      const bar = document.createElement("span");
      bar.className = "wave-bar";
      bar.style.cssText = `height:${h}%;animation-delay:${(i * 0.05).toFixed(2)}s`;
      waveEl.appendChild(bar);
    }
  }
}

function clearAudioZone() {
  uploadedPaths.audio = null;
  const preview  = document.getElementById("audio-preview");
  const empty    = document.getElementById("audio-empty");
  const clearBtn = document.getElementById("audio-clear");
  const zone     = document.getElementById("drop-audio");
  const input    = document.getElementById("file-audio");
  if (preview)  preview.style.display  = "none";
  if (empty)    empty.style.display    = "";
  if (clearBtn) clearBtn.style.display = "none";
  if (zone)     zone.classList.remove("has-file");
  if (input)    input.value = "";
}

/* ══════════════════════════════════════════════════════
   MODO ÁUDIO — show/hide zona e sliders conforme modo
══════════════════════════════════════════════════════ */

// Labels da zona de upload por modo
const AUDIO_ZONE_LABELS = {
  "A":      "TRILHA GUIA",
  "source": "CUSTOM SOUNDTRACK",
};

// Info bar: explica o que realmente acontece em cada modo
const AUDIO_INFO = {
  "": {
    cls:  "mode-generated",
    icon: "♪",
    text: "O Cinematic Pro gera o áudio automaticamente durante a criação do vídeo",
  },
  "A": {
    cls:  "mode-conditioning",
    icon: "⟳",
    text: "Usa a imagem como base visual e o áudio como referência de ritmo/energia durante a geração",
  },
  "source": {
    cls:  "mode-mux",
    icon: "▶",
    text: "Adiciona o áudio original ao vídeo final sem alterar a geração",
  },
};

function updateAudioUI(mode) {
  const zoneAudio  = document.getElementById("zone-audio");
  const zoneLabel  = document.getElementById("audio-zone-label");
  const scaleRow   = document.getElementById("audio-scale-row");
  const infoBar    = document.getElementById("audio-info-bar");
  const infoIcon   = document.getElementById("audio-info-icon");
  const infoText   = document.getElementById("audio-info-text");

  // Zona de upload: visível apenas quando precisa de arquivo
  const needsUpload = (mode === "A" || mode === "source");
  if (zoneAudio) zoneAudio.style.display = needsUpload ? "" : "none";
  if (zoneLabel) zoneLabel.textContent   = AUDIO_ZONE_LABELS[mode] || "ÁUDIO / SOUNDTRACK";

  // Sliders + lipsync: apenas para Trilha Guia (conditioning real do LTX)
  const needsScale = (mode === "A");
  const lipsyncRow = document.getElementById("audio-lipsync-row");
  if (scaleRow)   scaleRow.style.display   = needsScale ? "" : "none";
  if (lipsyncRow) lipsyncRow.style.display = needsScale ? "" : "none";

  // Info bar: atualiza classe de cor + ícone + texto
  const info = AUDIO_INFO[mode] || AUDIO_INFO[""];
  if (infoBar) {
    infoBar.className = `audio-info-bar ${info.cls}`;
  }
  if (infoIcon) infoIcon.textContent = info.icon;
  if (infoText) infoText.textContent  = info.text;

  // Limpar o upload se o modo mudou para "sem upload"
  if (!needsUpload) clearAudioZone();
}

function initAudioMode() {
  const sel = document.getElementById("audio-mode-select");
  if (!sel) return;

  // Slider audio-scale → live value
  const scaleSlider = document.getElementById("audio-scale");
  const scaleVal    = document.getElementById("audio-scale-val");
  if (scaleSlider && scaleVal) {
    scaleSlider.addEventListener("input", () => {
      scaleVal.textContent = parseFloat(scaleSlider.value).toFixed(2);
    });
  }

  // Slider audio-guidance-scale → live value
  const guidanceSlider = document.getElementById("audio-guidance-scale");
  const guidanceVal    = document.getElementById("audio-guidance-scale-val");
  if (guidanceSlider && guidanceVal) {
    guidanceSlider.addEventListener("input", () => {
      guidanceVal.textContent = parseFloat(guidanceSlider.value).toFixed(1);
    });
  }

  sel.addEventListener("change", () => updateAudioUI(sel.value));
  // Estado inicial (padrão "" = AI Soundtrack, zona oculta)
  updateAudioUI(sel.value);
}

/* ══════════════════════════════════════════════════════
   MODELS
══════════════════════════════════════════════════════ */
let modelsCache = [];

async function loadModels() {
  try {
    const res  = await fetch("/models?type=video");
    const data = await res.json();
    modelsCache = data.models || [];

    const sel = document.getElementById("model-select");
    if (!sel) return;
    sel.innerHTML = "";

    const tested = modelsCache.filter(m => m.tested);
    const others = modelsCache.filter(m => !m.tested);

    if (tested.length) {
      const og = document.createElement("optgroup");
      og.label = "Disponíveis";
      tested.forEach(m => {
        const opt = document.createElement("option");
        opt.value       = m.id;
        opt.textContent = m.id;   // sem "Não instalado" — download transparente para o usuário
        og.appendChild(opt);
      });
      sel.appendChild(og);
    }
    // Default visual: Cinematic Pro 1.1 (instalado, testado).
    // restoreState() sobrescreve se o usuário tiver salvo outra seleção.
    if ([...sel.options].some(o => o.value === "Cinematic Pro 1.1")) {
      sel.value = "Cinematic Pro 1.1";
    }
    if (others.length) {
      const og = document.createElement("optgroup");
      og.label = "Em breve";
      others.forEach(m => {
        const opt = document.createElement("option");
        opt.value = m.id; opt.textContent = m.id;
        opt.disabled = !m.tested;
        og.appendChild(opt);
      });
      sel.appendChild(og);
    }
    _syncDedicatedModePills();   // [12.25] revela "Animar Personagem" se Scail2 disponível
    sel.addEventListener("change", onModelChange);
    await onModelChange();   // aguarda modelo + loras carregados
  } catch (e) {
    console.error("loadModels:", e);
    const sel = document.getElementById("model-select");
    if (sel) sel.innerHTML = '<option>Erro ao carregar modelos</option>';
    showToast("Não foi possível carregar os modelos. Verifique o motor.", "err");
    setTimeout(hideToast, 5000);
  }
  restoreState();  // sempre executa, mesmo se loadModels falhou
  onModelChange();  // [STORY-AV 2026-06-26] re-aplica UI do modelo RESTAURADO (placeholder JoyAI,
                    // guidance phases…) — o onModelChange da L.1400 rodou com o modelo default, antes do restore
  _stateReady = true;  // a partir daqui, saveState() pode gravar normalmente
  gateTrialModels();   // [ERR-12] tranca modelos premium se o plano for trial (fail-open)
}

// [ERR-12] Gating de UI do trial no seletor de modelos de vídeo.
// 100% ADITIVO e FAIL-OPEN: só age se o plano for POSITIVAMENTE "trial".
// Tranca (desabilita + 🔒) os modelos de vídeo fora da lista do plano, espelhando o
// padrão do license-gate.js. O bloqueio REAL é server-side (_require_feature) — isto é UX.
// Cobre também o modo Texto→Imagem (t2i), que usa este mesmo seletor.
async function gateTrialModels() {
  try {
    const lf = await fetch("/license/features", { cache: "no-store" })
      .then(r => r.ok ? r.json() : null);
    if (!lf || lf.plan !== "trial") return;                       // só trial
    const allowed = lf.features && lf.features.video_models;
    if (!Array.isArray(allowed)) return;                          // sem lista → não mexe
    const sel = document.getElementById("model-select");
    if (!sel) return;
    [...sel.options].forEach(o => {
      if (o.value && !allowed.includes(o.value) && !o.disabled) {
        o.disabled = true;
        if (!o.dataset.acsLocked) {
          o.dataset.acsLocked = "1";
          o.textContent = "🔒 " + o.textContent + " — acesso completo";
        }
      }
    });
    // Se a seleção atual ficou travada, move para o 1º modelo permitido.
    const cur = sel.selectedOptions[0];
    if (!cur || cur.disabled || !allowed.includes(sel.value)) {
      const ok = [...sel.options].find(o => o.value && allowed.includes(o.value) && !o.disabled);
      if (ok) { sel.value = ok.value; onModelChange(); }
    }
  } catch (e) { /* fail-open: não trava nada */ }
}

async function onModelChange() {
  const sel     = document.getElementById("model-select");
  const modelId = sel ? sel.value : "";
  const info    = modelsCache.find(m => m.id === modelId);
  if (info) {
    // [G3-STEPS] Auto mode (value=""): não muda o select — buildModePayload usa info.default_steps
    // Manual mode (valor explícito): respeita escolha do usuário — não sobrescreve
    const stepsSel = document.getElementById("steps-select");
    if (stepsSel && stepsSel.value === "") {
      // Auto mode: visual fica em "Auto / Recomendado", payload usará info.default_steps
      // Nada a fazer — buildModePayload lê o default diretamente do cache
    }
    // [G2] Show/hide Guidance Phases control baseado na família do modelo
    const isLtx2Family = info.family === "ltx2";
    const phasesCol = document.getElementById("adv-col-phases");
    const phasesSep = document.getElementById("adv-sep-phases");
    if (phasesCol) phasesCol.style.display = isLtx2Family ? "" : "none";
    if (phasesSep) phasesSep.style.display = isLtx2Family ? "" : "none";
  }
  // [MSR 06-28] Multi-Personagem: usa o addon "Frame Inject" como dropzone de 1-5 referencias.
  // Auto-ativa o addon p/ revelar os slots de imagem + o select KI/I, senao o usuario nao
  // descobre onde soltar as fotos (o backend le ref_inject_paths -> image_refs).
  const _isMsr = modelId === "Multi-Personagem" || info?.base_type === "ltx2_22B_msr";
  // [MSR-FORCE-T2V 2026-07-04] O MSR (Multi-Personagem) SO funciona em t2v: as referencias vao
  // para image_refs (video_prompt_type "I"/"KI"). Se o modo tiver ficado em i2v (herdado de
  // EditAnything/Studio I2V), a 1a referencia era desviada pro slot i2v-start e o modelo quebrava
  // (KFI em vez de KI). Forca t2v ao selecionar Multi-Personagem. PROVADO no teste MSR de hoje.
  if (_isMsr && currentMode !== "t2v") {
    currentMode = "t2v";
    document.querySelectorAll(".mpill[data-mode]").forEach(b => b.classList.toggle("active", b.dataset.mode === "t2v"));
    const _cfgSelMsr = document.getElementById("mode-select-cfg");
    if (_cfgSelMsr) _cfgSelMsr.value = "t2v";
  }
  if (_isMsr && !activeAddons.has("frame-inj")) {
    activeAddons.add("frame-inj");
    document.querySelector('.apill[data-addon="frame-inj"]')?.classList.add("active");
    if (typeof updateMediaZones === "function") updateMediaZones();
    if (typeof updateAddonSubs === "function") updateAddonSubs();
  }
  // [STORY-AV 2026-06-26] Placeholder/helper dinâmico do formato multi-janela JoyAI-Echo.
  // Sem isto o usuário não descobre os comandos [/duration]/[/store_mem]/ID_A e usa o
  // Story AV como t2v comum, perdendo todo o poder multi-cena + memória.
  const _promptEl = document.getElementById("prompt-input");
  if (_promptEl) {
    const _isStoryAV = modelId === "Story AV" || info?.base_type === "joyai_echo";
    _promptEl.placeholder = _isStoryAV
      ? `🎬 Story AV — cada PARÁGRAFO é uma cena. Comandos no início de cada uma:
[/duration=8s] duração · [/store_mem=ana] salva personagem · [/load_mem=ana] reusa · [/new_shot] corte seco
Use IDs estáveis: ID_A, ID_B, ID_PLACE...

Exemplo:
[/duration=6s,/store_mem=ana] ID_A é uma mulher ruiva num café, sorri e diz "bom dia".

[/duration=6s,/new_shot,/load_mem=ana] ID_A a mesma mulher caminha na praia ao pôr do sol.`
      : "Descreva sua cena, plano ou ideia...";
  }
  // [TALKING-HEAD 2026-06-26] Modelos áudio-driven (Talking Head=multitalk, Infinite Talk=
  // infinitetalk) usam a VOZ como condicionamento de lip-sync, não como trilha. Sem isto o
  // audio-mode-select fica no default "" (AI Soundtrack) → audio_prompt_type vazio → o motor
  // gera o lip-sync mas NÃO muxa a voz no mp4 (cliente vê a boca mexer, mas MUDO — provado
  // pela tela: apt="" = sem stream de áudio; apt="A" = aac 16kHz muxado). Força "A" ao trocar
  // p/ esses modelos e revela a zona de upload + sliders (audio_scale/lipsync).
  // NB: /models expõe model_id (não base_type) ao frontend → checa model_id.
  const _audioDriven = info?.model_id === "multitalk" || info?.model_id === "infinitetalk";
  const _audioModeSel = document.getElementById("audio-mode-select");
  if (_audioModeSel) {
    if (_audioDriven && _audioModeSel.value !== "A") {
      _audioModeSel.value = "A";       // lip-sync: voz como condicionamento (senão vídeo mudo)
      updateAudioUI("A");
    } else if (!_audioDriven && window._acsLastAudioDriven && _audioModeSel.value === "A") {
      // saiu de um modelo áudio-driven → limpa o "A" forçado + a voz carregada, p/ não
      // arrastar a voz do Talking Head pra um vídeo normal (Cinematic Pro etc.).
      _audioModeSel.value = "";
      updateAudioUI("");               // "" não precisa upload → clearAudioZone() limpa a voz
    }
  }
  window._acsLastAudioDriven = _audioDriven;
  // [JOYAI-CTRLMEM 2026-06-26] ctrl-select model-aware: o Story AV (JoyAI) usa SÓ a opção de
  // "Memória de Vídeo" (os control modes do LTX2 — Canny/Depth/Pose/etc — não se aplicam a ele).
  // Mostra a opção JoyAI + esconde as LTX2 + revela o campo de posições; nos demais, o inverso.
  // Assim o cliente do Story AV pode semear personagem/voz de um vídeo de ref (multi-frames).
  const _isJoyai = modelId === "Story AV" || info?.model_id === "joyai_echo";
  const _ctrlSel = document.getElementById("ctrl-select");
  const _joyaiPos = document.getElementById("joyai-mem-positions");
  if (_ctrlSel) {
    _ctrlSel.querySelectorAll("option[data-ltx2ctrl]").forEach(o => { o.hidden = _isJoyai; });
    const _joyOpt = _ctrlSel.querySelector("option[data-joyai]");
    if (_joyOpt) _joyOpt.hidden = !_isJoyai;
    if (_isJoyai) {
      _ctrlSel.value = "V";
      if (_joyaiPos) _joyaiPos.style.display = "";
    } else {
      if (_ctrlSel.value === "V") _ctrlSel.value = "EVG";  // volta ao default LTX2 (Canny)
      if (_joyaiPos) _joyaiPos.style.display = "none";
    }
  }
  await loadLoras(modelId);   // aguarda loras antes de continuar
  if (_durationDisplayUpdate) _durationDisplayUpdate();
  updateLtx2ResOptions();
  saveState();  // persiste nova seleção de modelo
}

/* ══════════════════════════════════════════════════════
   RESOLUÇÕES 2K — apenas família ltx2
   Adiciona/remove as opções 2K do res-select dinamicamente.
   Chamado por onModelChange() no boot e a cada troca de modelo.
══════════════════════════════════════════════════════ */
function updateLtx2ResOptions() {
  const resSel  = document.getElementById("res-select");
  if (!resSel) return;

  const modelId = document.getElementById("model-select")?.value || "";
  const info    = modelsCache.find(m => m.id === modelId);
  const isLtx2  = info?.family === "ltx2";

  // Remove todas as opções 2K que já existam (evita duplicatas no re-render)
  resSel.querySelectorAll("option[data-ltx2]").forEach(o => o.remove());

  if (isLtx2) {
    LTX2_RES_OPTIONS.forEach(opt => {
      const el = document.createElement("option");
      el.value        = opt.value;
      el.textContent  = opt.label;
      el.dataset.ltx2 = "1";   // marker para remoção futura
      resSel.appendChild(el);
    });
  } else {
    // [PHASE2] Se modelo mudou para não-ltx2 e opção 2K estava selecionada, volta ao padrão
    const is2k = ["1440x2560", "2560x1440", "1440x1440"].includes(resSel.value);
    if (is2k) {
      resSel.value = "720x1280";   // [PHASE2] era "9:16-balanced"
      currentRatio = "9:16";
      // [PHASE2] Não altera currentQuality — quality é independente
      document.querySelectorAll(".cfg-fmt-btn[data-ratio]").forEach(b => {
        b.classList.toggle("active", b.dataset.ratio === "9:16");
      });
    }
  }
}

/* ══════════════════════════════════════════════════════
   LORAS — carrega opções para o modelo selecionado
══════════════════════════════════════════════════════ */
async function loadLoras(modelId) {
  const loraList = document.getElementById("lora-list");
  if (!loraList) return;
  loraList.innerHTML = '<span class="lora-empty">Carregando...</span>';
  availableLoras = [];
  if (!modelId) {
    loraList.innerHTML = '<span class="lora-empty">Nenhum modelo selecionado.</span>';
    return;
  }
  try {
    const res  = await fetch(`/loras?model_id=${encodeURIComponent(modelId)}`);
    const data = await res.json();
    availableLoras = data.loras || [];
    renderLoraList();
    // [FIX-LORA-INTRUSO] Reconcilia selectedLoras com os LoRAs DESTE modelo. Sem isto, LoRA de
    // outro modelo/família restaurado da sessão anterior (ex: control/i2v no Story AV) ficava em
    // selectedLoras e era ENVIADO no payload mesmo sem aparecer na lista — distorcia/atrasava o gen.
    // Descarta os incompatíveis (não presentes na lista do modelo atual) e re-marca os compatíveis.
    // Só toca em selectedLoras + checkboxes; não mexe em Modo Avançado/resolução/presets.
    const _availFiles = new Set(availableLoras.map(l => l.filename));
    const _kept = selectedLoras.filter(l => _availFiles.has(l.filename));
    if (_kept.length !== selectedLoras.length) {
      console.log(`[ACS] ${selectedLoras.length - _kept.length} LoRA(s) incompativel(eis) removido(s) ao trocar de modelo`);
      selectedLoras = _kept;
      if (_stateReady) saveState();
    }
    if (_kept.length) applyLorasToUI(_kept);
  } catch (e) {
    console.warn("loadLoras:", e);
    loraList.innerHTML = '<span class="lora-empty">Erro ao carregar presets.</span>';
    showToast("Erro ao carregar Estilos. Tente ⟳ Atualizar.", "err");
    setTimeout(hideToast, 4000);
  }
}

function renderLoraList() {
  const loraList = document.getElementById("lora-list");
  if (!loraList) return;
  if (!availableLoras.length) {
    loraList.innerHTML = '<span class="lora-empty">Nenhum preset para este modelo.</span>';
    return;
  }
  loraList.innerHTML = availableLoras.map((l, i) => {
    const isSpecial = l.type === "special";
    const badge = isSpecial
      ? `<span class="lora-badge lora-badge-special" title="${l.warning_message || 'preset especial'}">⚡ especial</span>`
      : "";
    return `
    <div class="lora-item${isSpecial ? " lora-item-special" : ""}" data-idx="${i}">
      <label class="lora-item-top">
        <input type="checkbox" class="lora-cb"
               data-name="${l.name}" data-filename="${l.filename}" data-idx="${i}"
               data-type="${l.type || 'normal'}"
               data-allowed="${(l.allowed_modes || []).join(',')}"
               data-incompatible="${(l.incompatible_modes || []).join(',')}"
               data-warning="${(l.warning_message || '').replace(/"/g, '&quot;')}" />
        <span class="lora-name">${l.label || l.name}</span>${badge}
      </label>
      <div class="lora-slider-row">
        <span class="lora-slider-label">Força</span>
        <input type="range" class="lora-slider" data-idx="${i}"
               min="0" max="2" step="0.05" value="1" />
        <span class="lora-slider-val" id="lora-val-${i}">1.00</span>
      </div>
    </div>`;
  }).join("");

  // Checkboxes — máximo 2 LoRAs simultâneos + validação de capability
  loraList.querySelectorAll(".lora-cb").forEach(cb => {
    cb.addEventListener("change", () => {
      if (cb.checked && loraList.querySelectorAll(".lora-cb:checked").length > 2) {
        cb.checked = false;
        showToast("Máximo 2 Estilos simultâneos.", "warn");
        setTimeout(hideToast, 2500);
        return;
      }
      // Validação de incompatibilidade de modo (client-side warning)
      if (cb.checked && cb.dataset.type === "special") {
        const incompatible = (cb.dataset.incompatible || "").split(",").filter(Boolean);
        if (incompatible.includes(currentMode)) {
          cb.checked = false;
          const allowed = (cb.dataset.allowed || "").split(",").filter(Boolean);
          showToast(`Estilo incompatível com modo '${currentMode}'. Use: ${allowed.join(", ")}`, "warn");
          setTimeout(hideToast, 3500);
          return;
        }
      }
      syncSelectedLoras();
    });
  });

  // Sliders individuais por LoRA
  loraList.querySelectorAll(".lora-slider").forEach(sl => {
    const idx   = sl.dataset.idx;
    const valEl = document.getElementById(`lora-val-${idx}`);
    sl.addEventListener("input", () => {
      if (valEl) valEl.textContent = parseFloat(sl.value).toFixed(2);
      syncSelectedLoras();
    });
  });
}

/**
 * Atualiza o banner de aviso de LoRA especial.
 * Chamado sempre que selectedLoras muda.
 * Mostra o aviso mais relevante (prioridade: HDR > outros especiais).
 */
function updateLoraWarning() {
  const banner  = document.getElementById("lora-warning");
  const textEl  = document.getElementById("lora-warning-text");
  if (!banner || !textEl) return;

  const loraList = document.getElementById("lora-list");
  if (!loraList) { banner.style.display = "none"; return; }

  // Coleta avisos de todos os LoRAs checked que são especiais
  const warnings = [];
  loraList.querySelectorAll(".lora-cb:checked").forEach(cb => {
    if (cb.dataset.type === "special" && cb.dataset.warning) {
      warnings.push(cb.dataset.warning);
    }
  });

  if (warnings.length) {
    textEl.textContent  = warnings.join(" · ");  // mostra todos os avisos
    banner.style.display = "flex";
  } else {
    banner.style.display = "none";
  }
}

function syncSelectedLoras() {
  const loraList = document.getElementById("lora-list");
  selectedLoras = [];
  loraList?.querySelectorAll(".lora-cb:checked").forEach(cb => {
    const idx  = cb.dataset.idx;
    const sl   = loraList.querySelector(`.lora-slider[data-idx="${idx}"]`);
    const lora = availableLoras[parseInt(idx)];
    selectedLoras.push({
      filename:   lora?.filename || cb.dataset.filename || (cb.dataset.name + ".safetensors"),
      multiplier: sl ? parseFloat(sl.value) : 1.0,
    });
  });
  updateLoraWarning();
  saveState();
}

function getLorasPayload() {
  return {
    loras_choices:     selectedLoras.map(l => l.filename),
    loras_multipliers: selectedLoras.map(l => l.multiplier.toFixed(2)).join(","),
  };
}

// Restaura checkboxes + sliders a partir de um array [{filename, multiplier}]
// Usado por restoreState() após loadLoras() popular a lista
function applyLorasToUI(lorasArr) {
  const loraList = document.getElementById("lora-list");
  if (!loraList || !lorasArr.length) return;
  loraList.querySelectorAll(".lora-cb").forEach(cb => {
    const cbFile = cb.dataset.filename || (cb.dataset.name + ".safetensors");
    const match  = lorasArr.find(l => l.filename === cbFile);
    cb.checked = !!match;
    if (match) {
      const sl    = loraList.querySelector(`.lora-slider[data-idx="${cb.dataset.idx}"]`);
      const valEl = document.getElementById(`lora-val-${cb.dataset.idx}`);
      if (sl)    sl.value = match.multiplier;
      if (valEl) valEl.textContent = parseFloat(match.multiplier).toFixed(2);
    }
  });
  // Não chama syncSelectedLoras() aqui para evitar loop — caller é responsável
}

/* ══════════════════════════════════════════════════════
   PRESET COLUMN — ATUALIZAR / LIMPAR
   Seleção direta via checkboxes (sem botão APLICAR).
══════════════════════════════════════════════════════ */
function initPresetCol() {
  const refreshBtn = document.getElementById("preset-refresh-btn");
  const clearBtn   = document.getElementById("preset-clear-btn");

  // ATUALIZAR — re-fetcha lista; preserva seleção atual se filenames ainda existirem
  refreshBtn?.addEventListener("click", async () => {
    const modelId = document.getElementById("model-select")?.value || "";
    refreshBtn.style.transition = "transform 0.4s ease";
    refreshBtn.style.transform  = "rotate(360deg)";
    setTimeout(() => { refreshBtn.style.transform = ""; refreshBtn.style.transition = ""; }, 450);
    const prevSelected = [...selectedLoras];   // guarda seleção antes do re-render
    await loadLoras(modelId);
    if (prevSelected.length) applyLorasToUI(prevSelected);  // tenta reselecionar
    if (prevSelected.length) syncSelectedLoras();            // ressincroniza array
    showToast("Estilos atualizados ✦");
    setTimeout(hideToast, 1800);
  });

  // LIMPAR — desmarca todos os checkboxes e reseta selectedLoras
  clearBtn?.addEventListener("click", () => {
    const loraList = document.getElementById("lora-list");
    loraList?.querySelectorAll(".lora-cb").forEach(cb => { cb.checked = false; });
    selectedLoras = [];
    updateLoraWarning();
    saveState();
    showToast("Seleção limpa.", "warn");
    setTimeout(hideToast, 1800);
  });
}

/* ══════════════════════════════════════════════════════
   BUILD PAYLOAD
══════════════════════════════════════════════════════ */
function buildPayload() {
  const prompt    = document.getElementById("prompt-input")?.value.trim()   || "";
  const negative  = document.getElementById("negative-input")?.value.trim() || "";
  const model     = document.getElementById("model-select")?.value           || "";
  const duration  = parseInt(document.getElementById("dur-slider")?.value)   || 5;
  const seedRaw   = document.getElementById("seed-input")?.value;
  const seed      = seedRaw !== undefined ? parseInt(seedRaw) : -1;

  // Steps
  const steps = parseInt(document.getElementById("steps-select")?.value) || 20;

  // Resolution from res-select "ratio-quality"
  const resVal   = document.getElementById("res-select")?.value || "9:16-balanced";
  const [ratio, quality] = resVal.split("-");
  const resolution = (RES_MATRIX[ratio || currentRatio] || {})[quality || currentQuality] || "720x1280";

  // Motion amplitude — hardcoded 1.0 (campo removido da UI; LTX ignora este valor)
  const motionAmp = 1.0;

  // Audio — resolve mode: "source" UI value = audio_source_path (ffmpeg mux), não audio_prompt_type
  const audioModeRaw = document.getElementById("audio-mode-select")?.value || "";
  const isAudioSource     = (audioModeRaw === "source");
  const audioModeVal      = isAudioSource ? "" : audioModeRaw;       // audio_prompt_type real
  const audio_path        = (!isAudioSource && uploadedPaths.audio) ? uploadedPaths.audio : "";
  const audio_source_path = isAudioSource ? (uploadedPaths.audio || "") : "";
  const audio_scale          = parseFloat(document.getElementById("audio-scale")?.value ?? "1") || 1.0;
  const audio_guidance_scale = parseInt(document.getElementById("audio-guidance-scale")?.value ?? "4", 10) || 4;

  // Addons
  const hasEndFrame = activeAddons.has("end-frame");
  const hasCtrlVid  = activeAddons.has("ctrl-video");
  const hasFrameInj = activeAddons.has("frame-inj");

  const ctrlType   = hasCtrlVid  ? (document.getElementById("ctrl-select")?.value || "THM") : "";
  const injectType = hasFrameInj ? (document.getElementById("inj-select")?.value  || "KI")  : "";

  // Paths por modo
  let ref_image_path  = "";
  let ctrl_video_path = "";
  let end_image_path  = hasEndFrame ? (uploadedPaths.end || "") : "";

  if (currentMode === "i2v") {
    ref_image_path = uploadedPaths.start || "";
  } else if (currentMode === "continue") {
    ctrl_video_path = uploadedPaths.start || "";
  } else if (hasCtrlVid) {
    ctrl_video_path = uploadedPaths.start || "";
  }

  return {
    prompt,
    model,
    resolution,
    duration,
    negative_prompt:           negative,
    steps,
    seed,
    generation_mode:           currentMode,
    ref_image_path,
    end_image_path,
    ctrl_video_path,
    inject_video_prompt_type:  injectType,
    ctrl_video_prompt_type:    ctrlType,
    source_strength:           1.0,
    audio_prompt_type:         audioModeVal,
    audio_path,
    audio_source_path,
    audio_scale,
    audio_guidance_scale,
    ...getLorasPayload(),
    guidance_scale:            5,
    motion_amplitude:          motionAmp,
    film_grain_intensity:      0,
    film_grain_saturation:     0.5,
    sliding_window_size:       81,
    sliding_window_overlap:    5,
    temporal_upsampling:       "",
    spatial_upsampling:        "",
    force_fps:                 "",
    self_refiner_setting:      0,
    prompt_enhancer:           "T",
    multi_prompts_gen_type:    "FG",
    audio_guidance_scale:      4,
    speakers_locations:        "",
  };
}

/* ══════════════════════════════════════════════════════
   BUILD MODE PAYLOAD — payload limpo por modo
   Usa apenas os campos do schema do wrapper específico.
══════════════════════════════════════════════════════ */
function resolveResolution() {
  // [PHASE2] res-select armazena WxH direto — sem parsing de ratio/quality
  const resVal = document.getElementById("res-select")?.value || "720x1280";
  if (/^\d+x\d+$/.test(resVal)) return resVal;
  // Fallback: migra valor legado se ainda existir
  return _migrateResValue(resVal) || "720x1280";
}

function buildModePayload() {
  // Seed: parseInt("") = NaN; garantir fallback -1 sem quebrar seed=0
  const _seedRaw = document.getElementById("seed-input")?.value ?? "";
  const _seed    = _seedRaw !== "" ? parseInt(_seedRaw) : -1;

  // Apenas campos que EXISTEM nos schemas dos wrappers (T2VRequest / I2VRequest / FLFRequest / ContinueRequest)
  // sliding_window_* NÃO estão nos schemas → excluídos do common
  // film_grain_* ADICIONADOS [FIX-BLOCKER-02] — agora nos schemas e enviados ao API

  // LoRA preset — usa o estado interno confirmado com APLICAR
  // (só vai para o payload se o utilizador clicou APLICAR explicitamente)

  // Addons activos
  const hasCtrlVid  = activeAddons.has("ctrl-video");
  const hasFrameInj = activeAddons.has("frame-inj");
  const ctrlType    = hasCtrlVid  ? (document.getElementById("ctrl-select")?.value || "EVG") : ""; // [v49] default: Canny (EVG) — flags 11.77
  const injectType  = hasFrameInj ? (document.getElementById("inj-select")?.value  || "KI")  : "";

  // Audio — resolve mode: "source" = audio_source_path (mux), "A" = audio_prompt_type (conditioning)
  // Lipsync: checkbox "Ignorar música de fundo" adiciona flag "V" → audio_prompt_type="AV"
  // "V" = extrair vocais via roformer antes do conditioning (melhora sincronização labial)
  const _audioModeRaw       = document.getElementById("audio-mode-select")?.value || "";
  const _isAudioSource      = (_audioModeRaw === "source");
  const _lipsync            = _audioModeRaw === "A" && (document.getElementById("audio-lipsync")?.checked || false);
  const _audio_prompt_type  = _isAudioSource ? "" : (_lipsync ? _audioModeRaw + "V" : _audioModeRaw);
  const _audio_path         = (!_isAudioSource && uploadedPaths.audio) ? uploadedPaths.audio : "";
  const _audio_source_path  = _isAudioSource ? (uploadedPaths.audio || "") : "";
  const _audio_scale        = parseFloat(document.getElementById("audio-scale")?.value ?? "1") || 1.0;
  const _audio_guidance_scale = parseInt(document.getElementById("audio-guidance-scale")?.value ?? "4", 10) || 4;

  const common = {
    prompt:               document.getElementById("prompt-input")?.value.trim()         || "",
    model:                document.getElementById("model-select")?.value                 || "Cinematic Pro 1.1",
    negative_prompt:      document.getElementById("negative-input")?.value.trim()       || "",
    duration:             (v => (isFinite(v) && v > 0) ? v : 5)(parseInt(document.getElementById("dur-slider")?.value)),
    steps:                (() => {
      // [G3-STEPS] Auto mode (value=""): usa default do modelo; Manual: usa valor explícito
      const sv = document.getElementById("steps-select")?.value ?? "";
      if (sv !== "") {
        const v = parseInt(sv, 10);
        if (isFinite(v) && v > 0) return v;
      }
      // Auto: busca default_steps do modelo atual no cache
      const mid = document.getElementById("model-select")?.value || "";
      return modelsCache.find(m => m.id === mid)?.default_steps || 30;
    })(),
    seed:                 _seed,
    resolution:           resolveResolution(),
    guidance_scale:       parseFloat(document.getElementById("adv-guidance")?.value)    || 5.0,
    motion_amplitude:     1.0,   // hardcoded — LTX ignora; campo removido da UI
    ...getLorasPayload(),
    // [FIX-INJECT] posição manual de cada frame injetado (vazio = auto-equidistante)
    frames_positions:     document.getElementById("inj-positions")?.value.trim() || "",
    audio_prompt_type:    _audio_prompt_type,
    audio_path:           _audio_path,
    audio_source_path:    _audio_source_path,
    audio_scale:          _audio_scale,
    audio_guidance_scale: _audio_guidance_scale,
    prompt_enhancer:      document.getElementById("adv-enhancer")?.dataset.mode ?? "",
    // [G2] Guidance Phases override: "" → -1 (auto); "1" → 1; "2" → 2
    guidance_phases_override: (() => {
      const ph = document.querySelector(".adv-phase-pill.active")?.dataset.phase ?? "";
      if (ph === "1") return 1;
      if (ph === "2") return 2;
      return -1;  // Auto
    })(),
    // [ADV-1177] Advanced Mode 11.77 — RIFLEx / RIFE / Self Refiner / Spatial / FPS
    riflex_setting:        parseInt(document.getElementById("adv-riflex")?.value        || "0", 10),
    temporal_upsampling:   document.getElementById("adv-temporal")?.value               || "",
    self_refiner_setting:  parseInt(document.getElementById("adv-self-refiner")?.value  || "0", 10),
    spatial_upsampling:    document.getElementById("adv-spatial")?.value                || "",
    force_fps:             document.getElementById("adv-fps")?.value                    || "",
    // [FIX-BLOCKER-02] Film grain agora enviado ao API (era sempre 0 hardcoded)
    // Ambos os sliders têm max=1.0, step=0.05 — usar parseFloat
    film_grain_intensity:  parseFloat(document.getElementById("adv-grain-int")?.value   || "0"),
    film_grain_saturation: parseFloat(document.getElementById("adv-grain-sat")?.value   || "0.5"),
    // [JOYAI-CTRLMEM] posições da memória de vídeo do JoyAI ("2s,8s" ou "ana=2s,leo=8s").
    // Backend só usa quando modelo=Story AV + ctrl-select="V"; inócuo nos demais.
    joyai_control_memory_positions: document.getElementById("joyai-mem-positions")?.value.trim() || "",
    // [TRIM-VÍDEO] corte por frames do vídeo de control / continuação (vazio = usa tudo)
    keep_frames_video_guide:  document.getElementById("keep-frames-guide")?.value.trim()  || "",
    keep_frames_video_source: document.getElementById("keep-frames-source")?.value.trim() || "",
    // [CAP-AUDIO] vídeo termina junto com a voz/control (motor: "|" no video_prompt_type)
    force_control_video_trim: document.getElementById("cap-audio-toggle")?.checked ? 1 : 0,
  };

  switch (currentMode) {
    case "t2v": {
      // Frame Inject: ref_inject_paths (lista: slot1=ref, slot2, slot3, + dinâmicos)
      // Ctrl Video:   ctrl_video_path + ctrl_video_prompt_type (usa zone-ref como ctrl)
      const injectPaths = hasFrameInj
        ? [uploadedPaths.start, uploadedPaths.inj2, uploadedPaths.inj3,
           ...dynamicInjectPaths].filter(Boolean)
        : [];
      return {
        ...common,
        inject_video_prompt_type: injectType,
        ref_inject_paths:         injectPaths,
        ref_image_path:           injectPaths[0] || "",  // backward compat
        ctrl_video_path:          hasCtrlVid ? (uploadedPaths.start || "") : "",
        ctrl_video_prompt_type:   ctrlType,
        // [MSR 06-28] modo de referência (KI=Fundo+Sujeitos / I=so Sujeitos). So usado pelo
        // backend quando model.base_type==ltx2_22B_msr; inocuo nos outros modelos t2v.
        msr_mode:                 (document.getElementById("model-select")?.value === "Multi-Personagem")
                                    ? (document.getElementById("inj-select")?.value || "KI")
                                    : "",
      };
    }

    case "i2v": {
      // ref_image_path = start frame (obrigatório, zona ref)
      // Frame Inject:  slots inj2, inj3 + dinâmicos (start frame NÃO vai aqui)
      // Ctrl Video:    zone-ctrl (separado do start frame)
      const injectPaths = hasFrameInj
        ? [uploadedPaths.inj2, uploadedPaths.inj3,
           ...dynamicInjectPaths].filter(Boolean)
        : [];
      // Leitura segura do slider: || 0.85 seria falso para valor 0
      const _ssRaw = parseFloat(document.getElementById("i2v-source-strength")?.value);
      const _sourceStrength = Number.isFinite(_ssRaw) ? _ssRaw : 0.85;
      return {
        ...common,
        ref_image_path:           uploadedPaths.start || "",
        inject_video_prompt_type: injectType,
        ref_inject_paths:         injectPaths,
        ctrl_video_path:          hasCtrlVid ? (uploadedPaths.ctrl || "") : "",
        ctrl_video_prompt_type:   ctrlType,
        source_strength:          _sourceStrength,
      };
    }

    case "flf":
      return {
        ...common,
        ref_image_path: uploadedPaths.start || "",
        end_image_path: uploadedPaths.end   || "",
      };

    case "continue":
      return {
        ...common,
        ctrl_video_path: uploadedPaths.start || "",
        source_strength: parseFloat(document.getElementById("i2v-source-strength")?.value) || 0.85,
        end_image_path:  uploadedPaths.end   || "",
      };

    case "animate":
      // [12.25] Animar Personagem (Scail2): anima a FOTO de pessoa (zone-ref) usando
      // o movimento de um VÍDEO (zone-ctrl). Tipo "V1" + máscara SAM3 já configurados.
      return {
        ...common,
        model:                  "Character Animate",
        ref_image_path:         uploadedPaths.start || "",   // foto da pessoa (real)
        ctrl_video_path:        uploadedPaths.ctrl  || "",   // vídeo de movimento
        ctrl_video_prompt_type: "V1",
        source_strength:        0.85,
      };

    default:
      // t2i e outros: endpoint genérico com generation_mode explícito
      return { ...common, generation_mode: currentMode };
  }
}

/* ══════════════════════════════════════════════════════
   CENTRAL HUD HELPERS (canvas overlay — #video-loading)
══════════════════════════════════════════════════════ */
function vidShowCanvasHud(pct, statusText, dlStats, showCalm) {
  const el = document.getElementById("video-loading");
  const hero = document.getElementById("hero-section");
  if (el) el.classList.add("visible");
  if (hero) hero.style.display = "none";
  const bar    = document.getElementById("vid-progress-bar");
  const pctEl  = document.getElementById("vid-hud-pct");
  const status = document.getElementById("vid-hud-status");
  const sub    = document.getElementById("vid-dl-sub");
  const calm   = document.getElementById("vid-dl-calm");
  const label  = document.getElementById("vid-progress-label");
  const safePct = Math.min(100, Math.max(0, pct || 0));
  if (bar)    bar.style.width     = safePct + "%";
  if (pctEl)  pctEl.textContent   = Math.round(safePct) + "%";
  if (status) status.textContent  = statusText || "Gerando...";
  if (sub)    sub.textContent     = dlStats || "";
  if (calm)   calm.style.display  = showCalm ? "block" : "none";
  if (label)  label.textContent   = "";
}

function vidHideCanvasHud() {
  const el = document.getElementById("video-loading");
  if (el) el.classList.remove("visible");
}

function vidResetCanvasHud() {
  vidHideCanvasHud();
  const hero = document.getElementById("hero-section");
  // Only restore hero if no video is showing
  const wrap = document.getElementById("video-player-wrap");
  if (hero && (!wrap || !wrap.classList.contains("visible"))) {
    hero.style.display = "";
  }
  const bar   = document.getElementById("vid-progress-bar");
  const pctEl = document.getElementById("vid-hud-pct");
  const status = document.getElementById("vid-hud-status");
  const sub   = document.getElementById("vid-dl-sub");
  const calm  = document.getElementById("vid-dl-calm");
  if (bar)    { bar.style.width = "0%"; }
  if (pctEl)  pctEl.textContent  = "0%";
  if (status) status.textContent = "Inicializando...";
  if (sub)    sub.textContent    = "";
  if (calm)   calm.style.display = "none";
}

function _buildDlStatsVid(dl) {
  try {
    if (!dl || !dl.active) return null;
    const parts = [];
    if (dl.speed_mbps != null && dl.speed_mbps > 0)
      parts.push(`${dl.speed_mbps.toFixed(1)} MB/s`);
    if (dl.downloaded_mb != null && dl.total_mb != null)
      parts.push(`${_fmtSize(dl.downloaded_mb)} / ${_fmtSize(dl.total_mb)}`);
    else if (dl.downloaded_mb != null)
      parts.push(_fmtSize(dl.downloaded_mb));
    const eta = _fmtEta(dl.eta_sec);
    if (eta) parts.push(eta);
    return parts.length ? parts.join(" — ") : null;
  } catch { return null; }
}

/* ══════════════════════════════════════════════════════
   PROGRESS UI INLINE — v1.0
   Reseta APENAS no início de nova geração (progressReset).
   Estado completed/failed persiste indefinidamente (sem timeout).
══════════════════════════════════════════════════════ */

const PUI_STEPS = [
  { pct:  0, label: "Carregando modelo" },
  { pct:  5, label: "Preparando…"       },
  { pct: 15, label: "Gerando vídeo"     },
  { pct: 85, label: "Renderizando vídeo"},
  { pct: 93, label: "Salvando vídeo"    },
  { pct: 98, label: "Finalizando"       },
];

// Whitelist de mensagens legíveis vindas do backend — usadas como override no PUI.
// Mensagens técnicas ("PASSO N: ...", "change_model_family", etc.) NÃO estão aqui
// e caem no puiGetStep(pct) normal.
const READABLE_STEPS = new Set([
  "Aguardando na fila...",
  "Iniciando geração...",
  "Iniciando modelo...",
  "Preparando modelo pela primeira vez...",
  "Baixando modelo do servidor... (pode demorar alguns minutos)",
  "Carregando modelo",
]);

// Retorna true para steps de download (prefixo "Baixando") — exibidos diretamente
// independente de estarem na whitelist exata acima.
function _isDownloadStep(step) {
  return typeof step === "string" && step.toLowerCase().startsWith("baixando");
}

// Formata MB em GB (≥1 GB) ou MB com 1 casa decimal.
function _fmtSize(mb) {
  if (mb == null) return "";
  if (mb >= 1024) return `${(mb / 1024).toFixed(1)} GB`;
  return `${mb.toFixed(0)} MB`;
}

// Formata segundos em "ETA M:SS".
function _fmtEta(sec) {
  if (sec == null || sec <= 0) return null;
  const m = Math.floor(sec / 60);
  const s = String(Math.floor(sec % 60)).padStart(2, "0");
  return `ETA ${m}:${s}`;
}

// Constrói o texto do subtitle de download a partir do campo data.download retornado
// pelo /status/{id}. Retorna:
//   - string com dados reais ("42.3% — 8.7 MB/s — 1.2 GB / 3.0 GB — ETA 3:20")
//   - null se não há dados reais (frontend usa mensagem de fallback)
// FAIL-SAFE: nunca lança — qualquer erro retorna null.
function _buildDlSubtext(dl) {
  try {
    if (!dl || !dl.active) return null;
    const parts = [];
    if (dl.percent  != null)                         parts.push(`${dl.percent.toFixed(1)}%`);
    if (dl.speed_mbps != null && dl.speed_mbps > 0)  parts.push(`${dl.speed_mbps.toFixed(1)} MB/s`);
    if (dl.downloaded_mb != null && dl.total_mb != null) {
      parts.push(`${_fmtSize(dl.downloaded_mb)} / ${_fmtSize(dl.total_mb)}`);
    } else if (dl.downloaded_mb != null) {
      parts.push(_fmtSize(dl.downloaded_mb));
    }
    const eta = _fmtEta(dl.eta_sec);
    if (eta) parts.push(eta);
    if (parts.length === 0) return null; // dados presentes mas vazios — usa fallback
    let line = parts.join(" — ");
    // [FASE C / R-19] NÃO exibir nome técnico do modelo no HUD — só %/velocidade/tamanho/ETA.
    return line;
  } catch (_) {
    return null;
  }
}

function puiGetStep(pct) {
  let label = PUI_STEPS[0].label;
  for (const s of PUI_STEPS) {
    if (pct >= s.pct) label = s.label;
    else break;
  }
  return label;
}

let _puiTimerStart = null;
let _puiTimerRef   = null;

function _puiStartTimer() {
  _puiTimerStart = Date.now();
  _puiTimerRef = setInterval(() => {
    const el = document.getElementById("pui-time");
    if (!el) return;
    const sec = Math.floor((Date.now() - _puiTimerStart) / 1000);
    el.textContent = Math.floor(sec / 60) + ":" + String(sec % 60).padStart(2, "0");
  }, 1000);
}

function _puiStopTimer() {
  clearInterval(_puiTimerRef);
  _puiTimerRef = null;
}

function _puiGetElapsed() {
  if (_puiTimerStart === null) return "";
  const sec = Math.floor((Date.now() - _puiTimerStart) / 1000);
  return Math.floor(sec / 60) + ":" + String(sec % 60).padStart(2, "0");
}

function formatEta(seconds) {
  if (!seconds || seconds <= 0) return null;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return m > 0 ? `${m}m ${s}s` : `${s}s`;
}

function progressReset() {
  _puiStopTimer();
  const ui   = document.getElementById("progress-ui");
  const bar  = document.getElementById("pui-bar");
  const pct  = document.getElementById("pui-pct");
  const step = document.getElementById("pui-step");
  const icon = document.getElementById("pui-icon");
  const time = document.getElementById("pui-time");
  const sub  = document.getElementById("pui-sub");
  if (!ui) return;
  ui.style.transition = "none";
  ui.dataset.state = "idle";
  if (bar)  { bar.style.transition = "none"; bar.style.width = "0%"; }
  if (pct)  pct.textContent  = "0%";
  if (step) step.textContent = "Carregando modelo";
  if (icon) icon.textContent = "●";
  if (time) time.textContent = "";
  if (sub)  sub.textContent  = "";
  requestAnimationFrame(() => requestAnimationFrame(() => {
    ui.style.transition = "";
    if (bar) bar.style.transition = "";
  }));
  vidResetCanvasHud();
}

// dlSubtext: string com dados reais de download ("42.3% — 8.7 MB/s — 1.2 GB / 3.0 GB")
//            ou null para usar mensagem de fallback honesta.
function progressSetGenerating(pct, stepOverride, etaStr, dlSubtext) {
  const ui   = document.getElementById("progress-ui");
  const bar  = document.getElementById("pui-bar");
  const pctEl= document.getElementById("pui-pct");
  const step = document.getElementById("pui-step");
  const icon = document.getElementById("pui-icon");
  const time = document.getElementById("pui-time");
  const sub  = document.getElementById("pui-sub");
  if (!ui) return;
  // [NAMING 2026-06-26] NUNCA exibir nome técnico de arquivo/engine ao cliente. dlSubtext vem como
  // "42.3% — 8.7 MB/s — 1.2 GB / 3.0 GB\nltx-2.3-22b-...safetensors" — a linha do progresso fica,
  // mas qualquer linha com extensão de peso ou nome de motor/lora vira rótulo comercial neutro.
  if (dlSubtext != null) {
    dlSubtext = String(dlSubtext).split("\n").map(line =>
      /\.(safetensors|gguf|ckpt|pth?|bin)\b|\bltx|\bwan|lora|hunyuan|qwen|flux|multitalk|infinitetalk|bernini|scail|magi|longcat|joyai|distilled|quanto/i.test(line)
        ? "Baixando componentes do modelo…"
        : line
    ).join("\n");
  }
  if (ui.dataset.state !== "generating") {
    ui.dataset.state = "generating";
    _puiStartTimer();
  }
  const safePct = Math.min(100, Math.max(0, pct || 0));
  if (icon)  icon.textContent  = "●";
  if (bar)   bar.style.width   = safePct + "%";
  if (pctEl) pctEl.textContent = Math.round(safePct) + "%";
  if (step)  step.textContent  = stepOverride || puiGetStep(safePct);
  if (time && etaStr) time.textContent = "ETA " + etaStr;
  // Subtitle: dados reais de download se disponíveis; fallback honesto caso contrário.
  // dlSubtext tem prioridade sempre que não-nulo (download ativo em qualquer step,
  // incluindo PASSO 10 — o download Wan2GP acontece dentro de process_tasks).
  if (sub) {
    if (dlSubtext != null) {
      sub.textContent = dlSubtext;  // dados reais: "42.3% — 8.7 MB/s — 1.2 GB / 3.0 GB\narquivo.safetensors"
    } else if (_isDownloadStep(stepOverride)) {
      sub.textContent = "Essa etapa pode demorar devido ao tamanho dos arquivos.\nSeu computador não está travado. Aguarde até a conclusão.";
    } else {
      sub.textContent = "";
    }
  }
  // Central HUD (canvas overlay)
  const isDl = dlSubtext != null && dlSubtext !== "";
  const centralStatus = isDl ? "Baixando modelos necessários" : (stepOverride || puiGetStep(safePct));
  vidShowCanvasHud(safePct, centralStatus, isDl ? dlSubtext : null, isDl);
}

function progressSetCompleted() {
  _puiStopTimer();
  const elapsed = _puiGetElapsed();
  const ui   = document.getElementById("progress-ui");
  const bar  = document.getElementById("pui-bar");
  const pctEl= document.getElementById("pui-pct");
  const step = document.getElementById("pui-step");
  const icon = document.getElementById("pui-icon");
  const time = document.getElementById("pui-time");
  const sub  = document.getElementById("pui-sub");
  if (!ui) return;
  ui.dataset.state = "completed";
  if (icon)  icon.textContent  = "✓";
  if (bar)   bar.style.width   = "100%";
  if (pctEl) pctEl.textContent = "100%";
  if (step)  step.textContent  = "Concluído";
  if (time)  time.textContent  = elapsed || "";
  if (sub)   sub.textContent   = "";
  vidHideCanvasHud();
  /* Sem setTimeout — persiste até próxima geração */
}

function progressSetFailed(reason) {
  _puiStopTimer();
  const ui   = document.getElementById("progress-ui");
  const step = document.getElementById("pui-step");
  const icon = document.getElementById("pui-icon");
  const time = document.getElementById("pui-time");
  const sub  = document.getElementById("pui-sub");
  if (!ui) return;
  ui.dataset.state = "failed";
  if (icon) icon.textContent = "✕";
  if (step) step.textContent = reason || "Geração falhou";
  if (time) time.textContent = "—";
  if (sub)  sub.textContent  = "";
  vidHideCanvasHud();
  const hero = document.getElementById("hero-section");
  const wrap = document.getElementById("video-player-wrap");
  if (hero && (!wrap || !wrap.classList.contains("visible"))) hero.style.display = "";
  /* Persiste indefinidamente */
}

/* ══════════════════════════════════════════════════════
   GENERATE
══════════════════════════════════════════════════════ */
function initGenerateBtn() {
  const btn = document.getElementById("btn-generate");
  if (btn) btn.addEventListener("click", onGenerate);
}

function initAbortBtn() {
  const btn = document.getElementById("btn-abort");
  if (btn) btn.addEventListener("click", onAbort);
}

async function onAbort() {
  if (!currentJobId) return;
  try {
    await fetch(`/cancel/${currentJobId}`, { method: "POST" });
    vidClearJobState();
    stopPolling();
    progressSetFailed("Cancelado");  // ← persiste até próxima geração
    showToast("Cancelado", "warn");
    setTimeout(hideToast, 2000);
  } catch (e) {
    console.error("abort:", e);
    showToast("Erro ao cancelar — tente novamente.", "err");
    setTimeout(hideToast, 3000);
  }
}

async function onGenerate() {
  const prompt = document.getElementById("prompt-input")?.value.trim() || "";
  if (!prompt) {
    showToast("Escreva um prompt primeiro!", "warn");
    setTimeout(hideToast, 2200);
    return;
  }

  // ── Verifica se modelo está instalado (genérico) ───────
  const selectedModel = document.getElementById("model-select")?.value || "";
  const modelInfo = modelsCache.find(m => m.id === selectedModel);
  if (modelInfo && modelInfo.installed === false) {
    // Tamanho real não disponível via config — não usar download_gb (estimativa manual).
    // Verificação de espaço em disco: usa download_gb apenas como piso de aviso.
    let diskMsg = "";
    try {
      const dRes = await fetch("/config/disk-space");
      if (dRes.ok) {
        const d = await dRes.json();
        if (d.free_gb != null) {
          diskMsg = `\nEspaço livre em disco: ${d.free_gb} GB`;
          // Aviso de espaço apenas se tiver estimativa configurada E disco insuficiente
          if (modelInfo.download_gb && d.free_gb < modelInfo.download_gb * 1.2) {
            diskMsg += "  ⚠️ PODE SER INSUFICIENTE";
          }
        }
      }
    } catch (_) { /* silencioso — disco não é bloqueante */ }

    const ok = confirm(
      `${selectedModel} ainda não está instalado.\n\n` +
      `Será necessário baixar os arquivos do modelo (vários GB).\n` +
      `O download começa automaticamente ao confirmar e pode demorar.` +
      diskMsg +
      `\n\nDeseja continuar?`
    );
    if (!ok) {
      showToast("Instalação cancelada. Selecione outro modelo.", "warn");
      setTimeout(hideToast, 3000);
      return;
    }
  }

  // ── Validações por modo ────────────────────────────────
  if ((currentMode === "i2v" || currentMode === "flf") && !uploadedPaths.start) {
    showToast("Faça upload da imagem de partida (start frame).", "warn");
    setTimeout(hideToast, 3000);
    document.getElementById("drop-start")?.classList.add("zone-required");
    setTimeout(() => document.getElementById("drop-start")?.classList.remove("zone-required"), 2500);
    return;
  }
  if (currentMode === "flf" && !uploadedPaths.end) {
    showToast("Modo FLF: faça upload do end frame também.", "warn");
    setTimeout(hideToast, 3000);
    document.getElementById("drop-end")?.classList.add("zone-required");
    setTimeout(() => document.getElementById("drop-end")?.classList.remove("zone-required"), 2500);
    return;
  }
  if (currentMode === "continue" && !uploadedPaths.start) {
    showToast("Modo Continue: faça upload do vídeo fonte.", "warn");
    setTimeout(hideToast, 3000);
    document.getElementById("drop-start")?.classList.add("zone-required");
    setTimeout(() => document.getElementById("drop-start")?.classList.remove("zone-required"), 2500);
    return;
  }

  // [12.25] Animar Personagem (Scail2): exige foto da pessoa + vídeo de movimento
  if (currentMode === "animate") {
    if (!uploadedPaths.start) {
      showToast("Animar Personagem: envie a FOTO da pessoa (foto real).", "warn");
      setTimeout(hideToast, 3000);
      document.getElementById("drop-start")?.classList.add("zone-required");
      setTimeout(() => document.getElementById("drop-start")?.classList.remove("zone-required"), 2500);
      return;
    }
    if (!uploadedPaths.ctrl) {
      showToast("Animar Personagem: envie o VÍDEO de movimento.", "warn");
      setTimeout(hideToast, 3000);
      document.getElementById("drop-ctrl")?.classList.add("zone-required");
      setTimeout(() => document.getElementById("drop-ctrl")?.classList.remove("zone-required"), 2500);
      return;
    }
  }

  if (currentJobId) {
    showToast("Geração em andamento…", "warn");
    return;
  }

  // ── Trava imediata — impede race condition de duplo clique ──
  // currentJobId = "pending" bloqueia re-entradas antes do await fetch retornar
  currentJobId = "pending";
  progressReset();   // ← reseta Progress UI antes de cada nova geração
  document.getElementById("btn-generate")?.classList.add("generating");

  // ── Roteia para o endpoint correto por modo ─────────────
  const endpoint = MODE_ENDPOINTS[currentMode] || "/generate";
  const payload  = buildModePayload();

  // ── Validação client-side de LoRA capability ─────────────
  // Bloqueia combos inválidos antes de enviar ao servidor.
  // O servidor também valida (defesa em profundidade) — esta validação
  // fornece feedback imediato sem round-trip.
  {
    const loraList = document.getElementById("lora-list");
    if (loraList) {
      for (const cb of loraList.querySelectorAll(".lora-cb:checked")) {
        if (cb.dataset.type !== "special") continue;
        const incompatible = (cb.dataset.incompatible || "").split(",").filter(Boolean);
        if (incompatible.includes(currentMode)) {
          currentJobId = null;
          document.getElementById("btn-generate")?.classList.remove("generating");
          const allowed = (cb.dataset.allowed || "").split(",").filter(Boolean);
          const loraName = cb.closest(".lora-item")?.querySelector(".lora-name")?.textContent || cb.dataset.name;
          progressSetFailed(`Estilo incompatível com modo ${currentMode}`);
          showToast(`"${loraName}" não suporta modo '${currentMode}'. Use: ${allowed.join(", ")}`, "err");
          setTimeout(hideToast, 5000);
          return;
        }
      }
    }
  }

  // ── Validação client-side de LoRA capability ─────────────
  // Bloqueia combos inválidos antes de enviar ao servidor.
  // O servidor também valida (defesa em profundidade) — esta validação
  // fornece feedback imediato sem round-trip.
  {
    const loraList = document.getElementById("lora-list");
    if (loraList) {
      for (const cb of loraList.querySelectorAll(".lora-cb:checked")) {
        if (cb.dataset.type !== "special") continue;
        const incompatible = (cb.dataset.incompatible || "").split(",").filter(Boolean);
        if (incompatible.includes(currentMode)) {
          currentJobId = null;
          document.getElementById("btn-generate")?.classList.remove("generating");
          const allowed = (cb.dataset.allowed || "").split(",").filter(Boolean);
          const loraName = cb.closest(".lora-item")?.querySelector(".lora-name")?.textContent || cb.dataset.name;
          progressSetFailed(`Estilo incompatível com modo ${currentMode}`);
          showToast(`"${loraName}" não suporta modo '${currentMode}'. Use: ${allowed.join(", ")}`, "err");
          setTimeout(hideToast, 5000);
          return;
        }
      }
    }
  }

  try {
    const res  = await fetch(endpoint, {
      method:  "POST",
      headers: { "Content-Type": "application/json" },
      body:    JSON.stringify(payload),
    });
    const data = await res.json();
    if (!res.ok) {
      const d = data.detail;
      throw new Error(d ? ((typeof d === 'string') ? d : (d.message || d.error || JSON.stringify(d))) : `HTTP ${res.status}`);
    }
    currentJobId = data.job_id;
    vidSaveJobState(currentJobId, "queued", 0);
    progressSetGenerating(0, "Carregando modelo");  // ← inicia Progress UI
    startPolling();
  } catch (err) {
    // Libera o botão se a requisição falhou antes de chegar no servidor
    currentJobId = null;
    document.getElementById("btn-generate")?.classList.remove("generating");
    progressSetFailed("Erro ao iniciar");  // ← estado failed persistente
    showToast(`Erro: ${err.message}`, "err");
    setTimeout(hideToast, 4000);
  }
}

/* ══════════════════════════════════════════════════════
   POLLING
══════════════════════════════════════════════════════ */
function startPolling() {
  showToast("Iniciando…");
  pollInterval = setInterval(async () => {
    if (!currentJobId) return;
    try {
      const res  = await fetch(`/status/${currentJobId}`);
      // 404: job desapareceu do servidor (restart do ACS?) — parar polling imediatamente
      if (res.status === 404) {
        vidClearJobState();
        stopPolling();
        progressSetFailed("Job não encontrado — servidor reiniciado?");
        setTimeout(hideToast, 4500);
        return;
      }
      const data = await res.json();
      const msg  = {
        queued:     "Na fila…",
        running:    `Processando… ${data.progress || 0}%`,
        generating: `Gerando… ${data.progress || 0}%`,
        done:       "✓ Concluído!",
        error:      `Erro: ${data.error || "desconhecido"}`,
        cancelled:  "Cancelado",
      }[data.status] || data.status;
      // ── Progress UI: atualiza barra durante polling ──────
      if (data.status === "queued") {
        progressSetGenerating(0, "Aguardando na fila...", null);
        vidSaveJobState(currentJobId, "queued", 0);
      }
      // [B38-001] downloading_lora incluído — download progress visível via isDl handler
      if (data.status === "running" || data.status === "generating" || data.status === "downloading_lora") {
        const stepOverride = (READABLE_STEPS.has(data.step) || _isDownloadStep(data.step)) ? data.step : null;
        const dlSubtext = _buildDlSubtext(data.download);
        const dl = data.download;
        const isDl = dl && dl.active;
        // [G3-HUD] Step counter + speed — atualiza #vid-step-info com dados reais do backend
        _hudUpdateStepInfo(data);
        // Central HUD: use dedicated stats (speed+size+ETA) for download branch
        if (isDl) {
          const dlPct   = dl.percent != null ? dl.percent : (data.progress || 0);
          const dlStats = _buildDlStatsVid(dl);
          const label   = document.getElementById("vid-progress-label");
          // [R-19] NUNCA exibir o nome técnico do modelo no HUD de download.
          // O HUD já mostra % · velocidade · tamanho · ETA via dlStats.
          if (label) label.textContent = "";
          vidShowCanvasHud(dlPct, "Baixando modelos necessários", dlStats || "Aguardando progresso real do download...", true);
          // Inline pui still uses dlSubtext (full string)
          progressSetGenerating(dlPct, "Baixando modelos necessários", null, dlSubtext);
        } else {
          progressSetGenerating(data.progress || 0, stepOverride, data.eta_seconds ? formatEta(data.eta_seconds) : null, dlSubtext);
        }
        vidSaveJobState(currentJobId, data.status, isDl ? (dl.percent ?? data.progress ?? 0) : (data.progress || 0));
      }
      showToast(msg, data.status === "error" ? "err" : "");
      if (data.status === "done") {
        vidClearJobState({ output: data.output || null });
        stopPolling();
        progressSetCompleted();  // ← 100%, persiste sem timeout
        _hudClearStepInfo();
        if (window.playNotifBeep) playNotifBeep();
        if (data.output) {
          showVideoPlayer(data.output.url, data.output.filename, data.output.size_mb);
          loadRecentOutputs();
        }
        setTimeout(hideToast, 2500);
      }
      if (data.status === "error" || data.status === "cancelled") {
        vidClearJobState({ error: data.error || null });
        stopPolling();
        progressSetFailed(data.status === "cancelled" ? "Cancelado" : ("Erro: " + (data.error || "desconhecido")));  // ← persiste
        _hudClearStepInfo();
        setTimeout(hideToast, 4500);
      }
    } catch (e) { console.error("poll:", e); }
  }, 2000);
}

// ── Download helper — B38-007v2 ──────────────────────────────
// window.location + ?download=1 → Content-Disposition: attachment no servidor
function _downloadFile(url, filename) {
  window.location.href = url + (url.includes("?") ? "&" : "?") + "download=1";
}

function stopPolling() {
  clearInterval(pollInterval);
  pollInterval = null;
  currentJobId = null;
  document.getElementById("btn-generate")?.classList.remove("generating");
}

/* ══════════════════════════════════════════════════════
   [G3-HUD] Step counter + speed helpers
   Exibe "Etapa 6/8 • 6.6s/step" ou "Refinando 2/3 • 23s/step"
   usando campos gen_step/gen_total/gen_stage/gen_speed_sps do backend.
══════════════════════════════════════════════════════ */
function _hudUpdateStepInfo(data) {
  const el = document.getElementById("vid-step-info");
  if (!el) return;
  const step  = data.gen_step;
  const total = data.gen_total;
  const stage = data.gen_stage;   // 1 = Stage1 (denoising), 2 = Stage2 (denoise/refinamento)
  const sps   = data.gen_speed_sps;
  // Só mostra quando temos dados reais de step
  if (typeof step !== "number" || typeof total !== "number" || total <= 0) {
    el.textContent = "";
    return;
  }
  const label = stage === 2 ? "Refinando" : "Etapa";
  const stepStr = `${label} ${step}/${total}`;
  const speedStr = (typeof sps === "number" && sps > 0) ? `  •  ${sps.toFixed(1)}s/step` : "";
  el.textContent = stepStr + speedStr;
}

function _hudClearStepInfo() {
  const el = document.getElementById("vid-step-info");
  if (el) el.textContent = "";
}

// bfcache guard: limpar timer de polling ao sair da página para evitar polling fantasma
// após restauração de sessão do Chrome (bfcache preserva heap JS incluindo setInterval ativos)
window.addEventListener("pagehide", () => {
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
  // currentJobId NOT zeroed — localStorage (VID_JOB_STATE_KEY) is source of truth for recovery
});

/* ══════════════════════════════════════════════════════
   VIDEO PLAYER
══════════════════════════════════════════════════════ */
function showVideoPlayer(url, filename, sizeMb) {
  const wrap = document.getElementById("video-player-wrap");
  const vid  = document.getElementById("video-output");
  const img  = document.getElementById("image-output");
  if (!wrap) return;

  // Detecta se o output é imagem ou vídeo pela extensão
  const isImage = /\.(jpg|jpeg|png|webp|gif)(\?|$)/i.test(url);

  if (isImage && img) {
    // Output de imagem (T2I)
    img.src = url;
    img.classList.add("visible");
    if (vid) { vid.src = ""; vid.style.display = "none"; }
  } else if (vid) {
    // Output de vídeo (todos os outros modos)
    vid.src = url;
    vid.style.removeProperty("display");
    if (img) { img.src = ""; img.classList.remove("visible"); }
  }

  const fnEl = document.getElementById("vp-filename");
  const szEl = document.getElementById("vp-size");
  if (fnEl) fnEl.textContent = filename || "";
  if (szEl) szEl.textContent = sizeMb ? `${sizeMb} MB` : "";

  // Oculta hero, expõe player (flex: 1 — preenche o canvas)
  const hero = document.getElementById("hero-section");
  if (hero) hero.style.display = "none";
  wrap.classList.add("visible");

  // [B38-007] fetch/blob — garante download mesmo em pywebview sem Content-Disposition
  const dlBtn = document.getElementById("btn-download");
  if (dlBtn) dlBtn.onclick = () => _downloadFile(url, filename || "output.mp4");

  // [ESTENDER 2026-06-27] botão "Estender" só para VÍDEO (continua a cena a partir do fim)
  const extBtn = document.getElementById("btn-estender");
  if (extBtn) {
    const canExtend = !isImage && lastVideoOutput && lastVideoOutput.path;
    extBtn.style.display = canExtend ? "" : "none";
    if (canExtend) extBtn.onclick = estenderVideo;
  }
}

// [ESTENDER 2026-06-27] Continua o último vídeo: entra no modo Continue e usa o próprio
// vídeo gerado como fonte (sem re-upload). O usuário ajusta o prompt e clica Gerar → o
// motor estende a cena a partir do último frame (= one_more_window do Gradio, via Continue).
function estenderVideo() {
  if (!lastVideoOutput || !lastVideoOutput.path) return;
  document.querySelector('.mpill[data-mode="continue"]')?.click();   // modo Continue
  uploadedPaths.start = lastVideoOutput.path;                         // vídeo gerado = fonte
  uploadedPaths.end = "";
  // preview do vídeo-fonte na zona de referência
  const zone  = document.getElementById("drop-start");
  const thumb = document.getElementById("ref-thumb");
  if (zone)  zone.classList.add("has-file");
  if (thumb) {
    thumb.style.cssText = "background:#000;overflow:hidden";
    thumb.innerHTML = `<video src="${lastVideoOutput.url}" muted playsinline preload="metadata" style="width:100%;height:100%;object-fit:cover"></video>`;
  }
  if (typeof showToast === "function") showToast("Vídeo carregado para estender — ajuste o prompt e clique em Gerar.");
  document.getElementById("prompt-input")?.focus();
}

/* ══════════════════════════════════════════════════════
   GALLERY AUTO-HIDE
   Hotzone (20px strip at right edge) triggers .peek.
   Debounce of 600ms before hiding — prevents flicker.
══════════════════════════════════════════════════════ */
(function initGalleryAutoHide() {
  const hotzone = document.getElementById("gallery-hotzone");
  const panel   = document.getElementById("gallery-panel");
  if (!hotzone || !panel) return;

  let _hideTimer = null;

  function peekShow() {
    clearTimeout(_hideTimer);
    panel.classList.add("peek");
  }
  function peekHide() {
    clearTimeout(_hideTimer);
    _hideTimer = setTimeout(() => panel.classList.remove("peek"), 600);
  }

  hotzone.addEventListener("mouseenter", peekShow);
  hotzone.addEventListener("mouseleave", peekHide);
  panel.addEventListener("mouseenter", peekShow);
  panel.addEventListener("mouseleave", peekHide);
})();

/* ══════════════════════════════════════════════════════
   RECENT OUTPUTS
══════════════════════════════════════════════════════ */
async function loadRecentOutputs() {
  try {
    const res  = await fetch("/outputs?type=video&limit=200");
    const data = await res.json();
    const grid  = document.getElementById("recent-grid");
    const panel = document.getElementById("gallery-panel");
    if (!grid) return;
    grid.innerHTML = "";
    const videos = (data.outputs || []).filter(o => o.type === "video");
    // Visibilidade controlada exclusivamente pelo auto-hide (CSS transform / .peek)
    // Não injetar display:none aqui — sobrescreveria o sistema de hotzone/peek
    if (!videos.length) return;
    videos.forEach(v => {
      const card = document.createElement("div");
      card.className = "video-card";
      // [FIX-GALERIA] URL encodada (v.url do backend vem com espaços crus = 404) +
      // poster JPG (/thumb): os mp4 têm moov no fim → <video> não renderiza thumb (preto).
      const url    = "/file/"  + encodeURIComponent(v.name);
      const poster = "/thumb/" + encodeURIComponent(v.name);
      card.innerHTML = `
        <video src="${url}" poster="${poster}" muted loop preload="none" playsinline></video>
        <div class="video-card-info">${v.title || v.name}</div>
      `;
      const vidEl = card.querySelector("video");
      vidEl.draggable = false;   // [FIX-DRAG] o drag é do card, não do <video> nativo
      card.addEventListener("mouseenter", () => vidEl.play().catch(() => {}));
      card.addEventListener("mouseleave", () => { vidEl.pause(); vidEl.currentTime = 0; });
      card.addEventListener("click", () => showVideoPlayer(url, v.name, v.size));
      // [FIX-DRAG] torna o card da galeria RECENTES arrastável para as zonas do vídeo
      // (mesmo payload do media-browser → _initGalleryDrop injeta o arquivo na zona).
      card.draggable = true;
      card.addEventListener("dragstart", e => {
        const payload = JSON.stringify({ url: url, type: "video", name: v.name || "" });
        try { e.dataTransfer.setData("application/x-acs-media", payload); } catch (_) {}
        try { e.dataTransfer.setData("text/plain", payload); } catch (_) {}
        try { e.dataTransfer.setData("text/uri-list", url); } catch (_) {}
        try { e.dataTransfer.effectAllowed = "copy"; } catch (_) {}
      });
      grid.appendChild(card);
      // Botão delete (compartilhado via gallery-delete.js)
      if (window.attachGalleryDeleteBtn) window.attachGalleryDeleteBtn(card, v.name);
    });
  } catch (e) { console.error("loadRecentOutputs:", e); }
}

/* ══════════════════════════════════════════════════════
   TOAST
══════════════════════════════════════════════════════ */
function showToast(msg, type = "") {
  const el = document.getElementById("gen-toast");
  if (!el) return;
  el.innerHTML = `<span class="toast-dot"></span>${msg}`;
  el.className = "gen-toast visible" + (type ? ` ${type}` : "");
}
function hideToast() {
  const el = document.getElementById("gen-toast");
  if (el) el.classList.remove("visible");
}
