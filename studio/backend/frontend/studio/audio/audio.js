if(!window.playNotifBeep){var _ns=document.createElement("script");_ns.src="/studio/notif.js?v=1";document.head.appendChild(_ns)}
/* ============================================================
   ACS Studio — Audio Module  v1
   Wan2GP Voice Studio — 8 modelos TTS reais
   POST /generate/audio  |  GET /status/:job_id
   Console: [ACS AUDIO PAYLOAD] antes de enviar
============================================================ */

/* ── Definição completa dos modelos (engenharia reversa dos handlers) ─────

  Legenda de flags:
    music      — gera música (Lyrics → Áudio)
    tts        — gera fala (texto → voz)
    audio_guide— aceita referência de voz (audio_guide)
    audio_guide2—aceita segunda referência (audio_guide2)
    alt_prompt — aceita campo secundário (Tags, Caption, Emoção, Voice Instruction)
    bpm/keyscale/timesig/language_iso — parâmetros de custom_settings
    exaggeration/pace — custom_settings do Chatterbox
    auto_split — custom_settings de KugelAudio, IndexTTS2, Qwen3 Base
    model_mode — seletor de idioma ou speaker (model_mode no payload)
    temperature / guidance / topk / topp / alt_guidance / audio_scale
────────────────────────────────────────────────────────── */
const MODEL_DEFS = {
  // [12.25] Stable Audio 3 — música/SFX por texto (nome comercial: Music Studio)
  "Music Studio": {
    label:        "Music Studio (Stable Audio 3)",
    type:         "music",
    duration:     { min: 1, max: 47, default: 8 },
    temperature:  false,
    guidance:     { default: 7.0 },
    audio_guide:  false,
    audio_guide2: false,
    alt_prompt:   { label: "Estilo / Gênero", placeholder: "synthwave, 110 bpm, driving bass", required: false },
    audio_task:   { label: "Modo", options: [ { value: "", label: "Texto → Áudio" } ], default: "" },
    custom:       [],
    topk:         false,
    topp:         false,
    alt_guidance: false,
    audio_scale:  false,
    model_mode:   false,
  },
  "ace_step_v1": {
    label:        "TTS ACE-Step v1.0 3.5B",
    type:         "music",
    duration:     { min: 5, max: 240, default: 20 },
    temperature:  false,
    guidance:     { default: 7.0 },
    audio_guide:  true,
    audio_guide2: false,
    alt_prompt:   { label: "Genres / Tags", placeholder: "disco, synth-pop, dreamy", required: false },
    audio_task: {
      label: "Source Audio Mode",
      options: [
        { value: "", label: "No Source Audio" },
        { value: "A", label: "Remix Audio (provide original lyrics + audio)" },
      ],
      default: "",
    },
    custom: [],
    topk:         false,
    topp:         false,
    alt_guidance: false,
    audio_scale:  true,   // "Prompt Audio Strength"
    model_mode:   false,
  },
  "ace_step_v1_5": {
    label:        "TTS ACE-Step v1.5 Turbo 2B",
    type:         "music",
    duration:     { min: 5, max: 360, default: 20 },
    temperature:  { default: 0.85 },
    guidance:     { default: 1.0 },
    audio_guide:  true,
    audio_guide2: true,
    alt_prompt:   { label: "Music Caption (style, genre, instruments, mood)", placeholder: "disco, shimmering pads", required: false },
    audio_task: {
      label: "Audio Task",
      options: [
        { value: "",   label: "Text (Lyrics) to Audio" },
        { value: "A",  label: "Cover Mode of Source Audio" },
        { value: "B",  label: "Transfer Reference Audio Timbre" },
        { value: "AB", label: "Cover Mode + Transfer Timbre" },
      ],
      default: "",
    },
    custom: ["bpm", "keyscale", "timesig", "language_iso"],
    topk:         { default: 0 },
    topp:         { default: 0.9 },
    alt_guidance: { default: 2.5 },
    audio_scale:  true,   // "Source Audio Strength"
    model_mode:   false,
  },
  "ace_step_v1_5_xl": {
    label:        "TTS ACE-Step v1.5 XL Turbo 4B",
    type:         "music",
    duration:     { min: 5, max: 360, default: 20 },
    temperature:  { default: 0.85 },
    guidance:     { default: 1.0 },
    audio_guide:  true,
    audio_guide2: true,
    alt_prompt:   { label: "Music Caption (style, genre, instruments, mood)", placeholder: "cinematic orchestral, epic", required: false },
    audio_task: {
      label: "Audio Task",
      options: [
        { value: "",   label: "Text (Lyrics) to Audio" },
        { value: "A",  label: "Cover Mode of Source Audio" },
        { value: "B",  label: "Transfer Reference Audio Timbre" },
        { value: "AB", label: "Cover Mode + Transfer Timbre" },
      ],
      default: "",
    },
    custom: ["bpm", "keyscale", "timesig", "language_iso"],
    topk:         { default: 0 },
    topp:         { default: 0.9 },
    alt_guidance: { default: 2.5 },
    audio_scale:  true,
    model_mode:   false,
  },
  "chatterbox": {
    label:        "TTS Chatterbox Multilingual",
    type:         "tts",
    duration:     false,  // sem slider de duração
    temperature:  { default: 0.8 },
    guidance:     { default: 1.0 },
    audio_guide:  true,   // "Voice to Replicate" — obrigatório por padrão
    audio_guide2: false,
    alt_prompt:   false,
    audio_task:   false,
    audio_prompt_fixed: "A",  // [FIX-CLONE] chatterbox EXIGE "A" p/ clonar a voz de referência
    custom:       ["exaggeration", "pace"],
    topk:         false,
    topp:         false,
    alt_guidance: false,
    audio_scale:  false,
    model_mode: {
      label: "Idioma",
      options: [
        { value: "ar", label: "Arabic" },
        { value: "da", label: "Danish" },
        { value: "de", label: "German" },
        { value: "el", label: "Greek" },
        { value: "en", label: "English" },
        { value: "es", label: "Spanish" },
        { value: "fi", label: "Finnish" },
        { value: "fr", label: "French" },
        { value: "he", label: "Hebrew" },
        { value: "hi", label: "Hindi" },
        { value: "it", label: "Italian" },
        { value: "ja", label: "Japanese" },
        { value: "ko", label: "Korean" },
        { value: "ms", label: "Malay" },
        { value: "nl", label: "Dutch" },
        { value: "no", label: "Norwegian" },
        { value: "pl", label: "Polish" },
        { value: "pt", label: "Portuguese" },
        { value: "ru", label: "Russian" },
        { value: "sv", label: "Swedish" },
        { value: "sw", label: "Swahili" },
        { value: "tr", label: "Turkish" },
        { value: "zh", label: "Chinese" },
      ],
      default: "pt",
    },
  },
  "heartmula_oss_3b": {
    label:        "TTS HeartMuLa 3B",
    type:         "music",
    duration:     { min: 30, max: 240, default: 120 },
    temperature:  { default: 1.0 },
    guidance:     { default: 1.5 },
    audio_guide:  false,  // não suporta referência de voz
    audio_guide2: false,
    alt_prompt:   { label: "Keywords / Tags", placeholder: "piano,happy,wedding", required: true },
    audio_task:   false,
    custom:       [],
    topk:         { default: 50 },
    topp:         false,
    alt_guidance: false,
    audio_scale:  false,
    model_mode:   false,
  },
  "index_tts2": {
    label:        "TTS Index TTS 2",
    type:         "tts",
    duration:     { min: 1, max: 600, default: 25 },
    temperature:  { default: 0.8 },
    guidance:     { default: 1.0 },
    audio_guide:  true,   // "Speaker reference voice" — obrigatório
    audio_guide2: true,   // "Speaker 2 voice / emotion reference (optional)"
    alt_prompt:   { label: "Default Emotion Instruction (optional)", placeholder: "happy,angry,sad,afraid,calm", required: false },
    audio_task: {
      label: "Voice Mode",
      options: [
        { value: "A",   label: "Voice cloning (1 reference audio)" },
        { value: "AB",  label: "Voice + emotion (2 reference audios)" },
        { value: "AB2", label: "Dialogue (2 speaker reference audios)" },
      ],
      default: "A",
    },
    custom: ["auto_split"],
    topk:         { default: 30 },
    topp:         { default: 0.8 },
    alt_guidance: false,
    audio_scale:  false,
    model_mode:   false,
  },
  "kugelaudio_0_open": {
    label:        "TTS KugelAudio 0 Open 7B",
    type:         "tts",
    duration:     { min: 1, max: 600, default: 20 },
    temperature:  { default: 1.0 },
    guidance:     { default: 3.0 },
    audio_guide:  true,   // opcional ("Reference voice")
    audio_guide2: true,   // opcional (segundo speaker)
    alt_prompt:   false,
    audio_task: {
      label: "Voice Mode",
      options: [
        { value: "",   label: "Text only (no reference)" },
        { value: "A",  label: "Voice cloning (1 reference audio)" },
        { value: "AB", label: "Voice cloning (2 reference audios)" },
      ],
      default: "",
    },
    custom: ["auto_split"],
    topk:         false,
    topp:         false,
    alt_guidance: false,
    audio_scale:  false,
    model_mode:   false,
  },
  "qwen3_tts_base": {
    label:        "TTS Qwen3 1.7B",
    type:         "tts",
    duration:     { min: 1, max: 600, default: 20 },
    temperature:  { default: 0.9 },
    guidance:     { default: 1.0 },
    audio_guide:  true,   // "Speaker 1 reference voice"
    audio_guide2: true,   // "Speaker 2 reference voice"
    alt_prompt:   { label: "Reference transcript(s) (optional)", placeholder: "Speaker 1 reference transcript\nSpeaker 2 reference transcript", required: false },
    audio_task: {
      label: "Voice Mode",
      options: [
        { value: "A",  label: "Voice cloning of 1 speaker" },
        { value: "AB", label: "Voice cloning of 2 speakers" },
      ],
      default: "A",
    },
    custom: ["auto_split"],
    topk:         { default: 50 },
    topp:         false,
    alt_guidance: false,
    audio_scale:  false,
    // [ENG-REVERSA] qwen3_handler.py declara model_modes (Language, default "auto").
    // Valores = nomes completos (auto/portuguese/english...), igual ao handler.
    model_mode: {
      label: "Idioma",
      options: [
        { value: "auto",       label: "Automático (detecta)" },
        { value: "portuguese", label: "Português" },
        { value: "english",    label: "English" },
        { value: "spanish",    label: "Español" },
        { value: "french",     label: "Français" },
        { value: "german",     label: "Deutsch" },
        { value: "italian",    label: "Italiano" },
        { value: "japanese",   label: "日本語" },
        { value: "korean",     label: "한국어" },
        { value: "chinese",    label: "中文" },
        { value: "russian",    label: "Русский" },
      ],
      default: "auto",
    },
  },
};

/* ── Estado global ─────────────────────────────────────── */
let currentModel  = "ace_step_v1";
let currentJobId  = null;
let pollInterval  = null;
const uploadedPaths = {
  guide1: null,
  guide2: null,
};

/* ── Persistência de estado (UI State Persistence v1) ──────── */
const AUDIO_STATE_KEY = "acs_audio_state_v1";
const AUD_JOB_STATE_KEY  = "acs:state:audio";
const AUD_JOB_MAX_AGE_MS = 6 * 60 * 60 * 1000;  // 6h
let _stateReady = false;

/* ── Phase 3: Job State Persistence ────────────────────────── */
function audSaveJobState(jId, lastStatus, lastProgress) {
  try {
    const ex   = audLoadJobState();
    const same = ex?.job_id === jId;
    localStorage.setItem(AUD_JOB_STATE_KEY, JSON.stringify({
      job_id:        jId,
      tab:           "audio",
      started_at:    same ? (ex.started_at || Date.now()) : Date.now(),
      last_status:   lastStatus  ?? "queued",
      last_progress: lastProgress ?? 0,
      last_output:   same ? (ex.last_output || null) : null,
      last_error:    null,
    }));
  } catch { }
}

function audLoadJobState() {
  try { return JSON.parse(localStorage.getItem(AUD_JOB_STATE_KEY)); }
  catch { return null; }
}

function audClearJobState({ output = null, error = null } = {}) {
  try {
    localStorage.setItem(AUD_JOB_STATE_KEY, JSON.stringify({
      job_id: null, tab: "audio", started_at: null,
      last_status: null, last_progress: null,
      last_output: output, last_error: error,
    }));
  } catch { }
}

async function audCheckJobRecovery() {
  let s;
  try { s = audLoadJobState(); } catch { return; }
  if (!s) return;
  if (!s.job_id && s.last_output?.url) {
    try { showAudioPlayer(s.last_output.url, s.last_output.filename, s.last_output.size_mb); } catch { }
    return;
  }
  if (!s.job_id) return;
  if (s.started_at && (Date.now() - s.started_at) > AUD_JOB_MAX_AGE_MS) { audClearJobState(); return; }
  let data;
  try {
    const resp = await fetch(`/status/${s.job_id}`);
    if (resp.status === 404) { audClearJobState(); return; }
    data = await resp.json();
  } catch { audClearJobState(); return; }
  if (data.status === "done") {
    audClearJobState({ output: data.output || null });
    if (data.output?.url) {
      try { showAudioPlayer(data.output.url, data.output.filename, data.output.size_mb); } catch { }
      loadRecentOutputs();
    }
    return;
  }
  if (data.status === "error") {
    audClearJobState({ error: data.error || "Erro" });
    showToast("Erro na geração anterior: " + (data.error || "falha desconhecida"), "err");
    setTimeout(hideToast, 5000);
    return;
  }
  if (data.status === "cancelled") { audClearJobState(); return; }
  if (["queued", "running", "generating"].includes(data.status)) {
    currentJobId = s.job_id;
    document.getElementById("btn-generate")?.classList.add("generating");
    const pct = s.last_progress ?? 0;
    audShowCanvasHud(pct, s.last_status || "Retomando...", null, false);
    showToast(`Retomando… ${Math.round(pct)}%`);
    startPolling();
  }
}

/* ── Phase 3: Central HUD helpers ──────────────────────────── */
function audShowCanvasHud(pct, statusText, dlStats, showCalm) {
  const el   = document.getElementById("audio-loading");
  const hero = document.getElementById("hero-section");
  if (el) el.classList.add("visible");
  if (hero) hero.style.display = "none";
  const bar    = document.getElementById("aud-progress-bar");
  const pctEl  = document.getElementById("aud-hud-pct");
  const status = document.getElementById("aud-hud-status");
  const sub    = document.getElementById("aud-dl-sub");
  const calm   = document.getElementById("aud-dl-calm");
  const safePct = Math.min(100, Math.max(0, pct || 0));
  if (bar)    bar.style.width    = safePct + "%";
  if (pctEl)  pctEl.textContent  = Math.round(safePct) + "%";
  if (status) status.textContent = statusText || "Gerando...";
  if (sub)    sub.textContent    = dlStats || "";
  if (calm)   calm.style.display = showCalm ? "block" : "none";
}

function audHideCanvasHud() {
  const el = document.getElementById("audio-loading");
  if (el) el.classList.remove("visible");
}

function _buildDlStatsAud(dl) {
  try {
    if (!dl || !dl.active) return null;
    const parts = [];
    if (dl.speed_mbps != null && dl.speed_mbps > 0) parts.push(`${dl.speed_mbps.toFixed(1)} MB/s`);
    if (dl.downloaded_mb != null && dl.total_mb != null) {
      const fmt = mb => mb >= 1024 ? `${(mb/1024).toFixed(1)} GB` : `${mb.toFixed(0)} MB`;
      parts.push(`${fmt(dl.downloaded_mb)} / ${fmt(dl.total_mb)}`);
    }
    if (dl.eta_sec != null && dl.eta_sec > 0) {
      const m = Math.floor(dl.eta_sec / 60), ss = String(Math.floor(dl.eta_sec % 60)).padStart(2,"0");
      parts.push(`ETA ${m}:${ss}`);
    }
    return parts.length ? parts.join(" — ") : null;
  } catch { return null; }
}

function saveState() {
  if (!_stateReady) return;
  try {
    const seedInput = document.getElementById("seed-input");
    const seedFix   = document.getElementById("seed-mode-fix");
    // Audio saveState FIX: inclui topk, topp, altGuidance, audioScale,
    // exaggeration, pace que estavam faltando e se perdiam ao recarregar.
    // Sliders chamavam saveState() no input mas os valores não eram capturados.
    const _sv = id => document.getElementById(id)?.value ?? null;
    localStorage.setItem(AUDIO_STATE_KEY, JSON.stringify({
      prompt:          document.getElementById("prompt-input")?.value          ?? "",
      altPrompt:       document.getElementById("alt-prompt-input")?.value      ?? "",
      model:           currentModel,
      duration:        parseInt(_sv("dur-slider")         ?? "20")  || 20,
      numGenerations:  parseInt(_sv("num-generations")    ?? "1")   || 1,
      seed:            parseInt(seedInput?.value           ?? "-1")  || -1,
      seedMode:        seedFix?.classList.contains("active") ? "fix" : "rand",
      guidance:        parseFloat(_sv("guidance-slider")    ?? "7")   || 7,
      temperature:     parseFloat(_sv("temperature-slider") ?? "0.8") || 0.8,
      audioPromptType: document.getElementById("audio-prompt-type")?.value ?? "",
      // ── Sliders avançados (por modelo) ─────────────────────────────────
      topk:            _sv("topk-slider")         !== null ? (parseInt(_sv("topk-slider"))         || 0)   : null,
      topp:            _sv("topp-slider")          !== null ? (parseFloat(_sv("topp-slider"))        || 0)   : null,
      altGuidance:     _sv("alt-guidance-slider")  !== null ? (parseFloat(_sv("alt-guidance-slider")) || 0)  : null,
      audioScale:      _sv("audio-scale-slider")   !== null ? (parseFloat(_sv("audio-scale-slider")) || 0.5) : null,
      exaggeration:    _sv("exaggeration-slider")  !== null ? (parseFloat(_sv("exaggeration-slider")) || 0.5): null,
      pace:            _sv("pace-slider")          !== null ? (parseFloat(_sv("pace-slider"))        || 1.0) : null,
    }));
  } catch { /* quota exceeded — ignorar silenciosamente */ }
}

function restoreState() {
  let s;
  try { s = JSON.parse(localStorage.getItem(AUDIO_STATE_KEY)); } catch { s = null; }
  if (!s || typeof s !== "object") return;

  // Model pills — restaurar e reconstruir UI
  if (typeof s.model === "string" && s.model && MODEL_DEFS[s.model]) {
    currentModel = s.model;
    document.querySelectorAll(".mpill[data-model]").forEach(b => {
      b.classList.toggle("active", b.dataset.model === currentModel);
    });
    const sel = document.getElementById("model-display");
    if (sel) sel.value = currentModel;
    updateModelUI(currentModel);  // reconfigura sliders/controles para o modelo restaurado
    // Restaurar audioPromptType APÓS updateModelUI (que reseta para o default do modelo)
    if (typeof s.audioPromptType === "string") {
      const taskSel = document.getElementById("audio-prompt-type");
      if (taskSel && taskSel.value !== s.audioPromptType) {
        taskSel.value = s.audioPromptType;
        onAudioTaskChange(currentModel, s.audioPromptType);
      }
    }
  }

  // Prompt
  const promptEl = document.getElementById("prompt-input");
  if (promptEl && typeof s.prompt === "string") {
    promptEl.value = s.prompt;
    const cc = document.getElementById("char-count");
    if (cc) cc.textContent = `${s.prompt.length} / 12000`;
  }

  // Duration (após updateModelUI que define min/max/default)
  if (typeof s.duration === "number" && s.duration > 0) {
    const durEl = document.getElementById("dur-slider");
    if (durEl) { durEl.value = s.duration; updateDurDisplay(); }
  }

  // Seed + modo rand/fix
  if (typeof s.seed === "number") {
    const seedInput = document.getElementById("seed-input");
    const seedFix   = document.getElementById("seed-mode-fix");
    const seedRand  = document.getElementById("seed-mode-rand");
    if (s.seedMode === "fix" && s.seed >= 0 && seedInput) {
      seedInput.value    = String(s.seed);
      seedInput.disabled = false;
      seedFix?.classList.add("active");
      seedRand?.classList.remove("active");
    }
    // modo "rand" é o default de initSeedRand — não precisa restaurar
  }

  // Guidance slider
  if (typeof s.guidance === "number") {
    const el = document.getElementById("guidance-slider");
    if (el) {
      el.value = s.guidance;
      const v = document.getElementById("guidance-val");
      if (v) v.textContent = s.guidance.toFixed(1);
    }
  }

  // Temperature slider
  if (typeof s.temperature === "number") {
    const el = document.getElementById("temperature-slider");
    if (el) {
      el.value = s.temperature;
      const v = document.getElementById("temperature-val");
      if (v) v.textContent = s.temperature.toFixed(2);
    }
  }

  // ── Sliders avançados por modelo — restaurar APÓS updateModelUI ─────────
  // updateModelUI() reseta para os defaults do modelo; só sobrescreve se o
  // slider estiver visível (row visível = modelo suporta o parâmetro).
  // Audio saveState FIX: estes valores estavam salvos mas nunca restaurados.
  const _restoreSlider = (id, valId, savedVal, toFixed) => {
    if (savedVal === null || savedVal === undefined) return;
    const el = document.getElementById(id);
    if (!el) return;
    // Só restaura se o slider estiver visível (modelo suporta o parâmetro)
    const row = el.closest(".param-row, .ctrl-row, [id$='-row']");
    if (row && row.style.display === "none") return;
    el.value = savedVal;
    const v = document.getElementById(valId);
    if (v) v.textContent = typeof toFixed === "number"
      ? parseFloat(savedVal).toFixed(toFixed)
      : String(savedVal);
  };
  _restoreSlider("topk-slider",         "topk-val",         s.topk,         0);
  _restoreSlider("topp-slider",         "topp-val",         s.topp,         2);
  _restoreSlider("alt-guidance-slider", "alt-guidance-val", s.altGuidance,  1);
  _restoreSlider("audio-scale-slider",  "audio-scale-val",  s.audioScale,   2);
  _restoreSlider("exaggeration-slider", "exaggeration-val", s.exaggeration, 2);
  _restoreSlider("pace-slider",         "pace-val",         s.pace,         2);

  // Alt prompt (Tags/Caption)
  if (typeof s.altPrompt === "string") {
    const el = document.getElementById("alt-prompt-input");
    if (el) el.value = s.altPrompt;
  }

  // Número de gerações
  if (typeof s.numGenerations === "number" && s.numGenerations >= 1) {
    const el = document.getElementById("num-generations");
    if (el && [...el.options].some(o => parseInt(o.value) === s.numGenerations)) {
      el.value = String(s.numGenerations);
    }
  }
}

/* ── Audio task select — saveState hook ─────────────── */
function initAudioTaskSelect() {
  document.getElementById("audio-prompt-type")
    ?.addEventListener("change", saveState);
}

// bfcache guard: limpar timer de polling ao sair da página
window.addEventListener("pagehide", () => {
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
  // currentJobId NOT zeroed — localStorage (AUD_JOB_STATE_KEY) is source of truth for recovery
});

/* ── Boot ──────────────────────────────────────────────── */
document.addEventListener("DOMContentLoaded", async () => {
  initModelPills();
  initPrompt();
  initDuration();
  initSliders();
  initSeedRand();
  initGuide1Zone();
  initGuide2Zone();
  initGenerateBtn();
  initAbortBtn();
  initAudioPlayer();
  initAudioTaskSelect();
  loadRecentOutputs();
  updateModelUI(currentModel);
  restoreState();
  _stateReady = true;
  await audCheckJobRecovery();  // Phase 3: restaura job ativo ou último output
  // Hooks para campos adicionados à persistência
  document.getElementById("alt-prompt-input")?.addEventListener("input", saveState);
  document.getElementById("num-generations")?.addEventListener("change", saveState);
});

/* ══════════════════════════════════════════════════════
   MODEL PILLS — seleção na faixa topo
══════════════════════════════════════════════════════ */
function initModelSelect() {
  const sel = document.getElementById("model-display");
  if (!sel) return;
  sel.addEventListener("change", () => {
    currentModel = sel.value;
    // Sincroniza pills
    document.querySelectorAll(".mpill[data-model]").forEach(b => {
      b.classList.toggle("active", b.dataset.model === currentModel);
    });
    updateModelUI(currentModel);
  });
}

function initModelPills() {
  document.querySelectorAll(".mpill[data-model]").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".mpill[data-model]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      currentModel = btn.dataset.model;
      // Sincroniza select
      const sel = document.getElementById("model-display");
      if (sel) sel.value = currentModel;
      updateModelUI(currentModel);
      saveState();
    });
  });
  initModelSelect();
}

/* ══════════════════════════════════════════════════════
   UPDATE MODEL UI — mostra/oculta controles por modelo
══════════════════════════════════════════════════════ */
function updateModelUI(modelId) {
  const def = MODEL_DEFS[modelId];
  if (!def) return;

  /* --- Duração ---------------------------------------- */
  const durCol = document.querySelector(".cfg-col-dur-audio");
  const durSlider = document.getElementById("dur-slider");
  // [DICA-DUR] dica para modelos sem slider de duração (ex.: Chatterbox TTS):
  // a duração não é controlável — vem do tamanho do texto digitado.
  let durHint = document.getElementById("dur-tts-hint");
  if (def.duration) {
    if (durCol) durCol.style.display = "";
    if (durHint) durHint.style.display = "none";
    if (durSlider) {
      durSlider.min = def.duration.min;
      durSlider.max = def.duration.max;
      durSlider.value = def.duration.default;
      updateDurDisplay();
    }
  } else {
    if (durCol) durCol.style.display = "none";
    if (!durHint && durCol && durCol.parentNode) {
      durHint = document.createElement("div");
      durHint.id = "dur-tts-hint";
      durHint.style.cssText = "font-size:11px;color:#9fb0b0;opacity:.85;margin-top:6px;line-height:1.4;";
      durHint.innerHTML = "&#9201; A dura&ccedil;&atilde;o deste modelo vem do <b>tamanho do texto</b> &mdash; escreva mais para um &aacute;udio mais longo.";
      durCol.parentNode.insertBefore(durHint, durCol.nextSibling);
    }
    if (durHint) durHint.style.display = "";
  }

  /* --- Alt Prompt (Tags / Caption) -------------------- */
  const altSection = document.getElementById("alt-prompt-section");
  const altLabel   = document.getElementById("alt-prompt-label");
  const altInput   = document.getElementById("alt-prompt-input");
  const ptabAlt    = document.getElementById("ptab-alt");
  if (def.alt_prompt) {
    if (altSection) altSection.style.display = "";
    if (ptabAlt)   ptabAlt.style.display = "";
    if (altLabel)  altLabel.textContent = def.alt_prompt.label;
    if (altInput)  altInput.placeholder = def.alt_prompt.placeholder;
  } else {
    if (altSection) altSection.style.display = "none";
    if (ptabAlt)   ptabAlt.style.display = "none";
  }

  /* --- Audio Guide Zones ------------------------------ */
  const zoneGuide1 = document.getElementById("zone-guide1");
  const zoneGuide2 = document.getElementById("zone-guide2");
  const guide1Lbl  = document.getElementById("guide1-label");
  const guide2Lbl  = document.getElementById("guide2-label");
  const mediaCol   = document.getElementById("dock-media-col");

  if (def.audio_guide) {
    if (mediaCol)   mediaCol.style.display = "";
    if (zoneGuide1) zoneGuide1.style.display = "";
    // Labels personalizadas por modelo
    const g1labels = {
      "chatterbox":        "VOZ A REPLICAR",
      "index_tts2":        "SPEAKER 1 — VOZ DE REF.",
      "kugelaudio_0_open": "REFERÊNCIA DE VOZ (OPC.)",
      "qwen3_tts_base":    "SPEAKER 1 — VOZ DE REF.",
    };
    if (guide1Lbl) guide1Lbl.textContent = g1labels[modelId] || "VOZ DE REFERÊNCIA";
  } else {
    if (mediaCol)   mediaCol.style.display = "none";
    if (zoneGuide1) zoneGuide1.style.display = "none";
    uploadedPaths.guide1 = null;
    clearGuideZone(1);
  }

  if (def.audio_guide2) {
    if (zoneGuide2) zoneGuide2.style.display = "";
    const g2labels = {
      "ace_step_v1_5":     "REFERÊNCIA DE TIMBRE",
      "ace_step_v1_5_xl":  "REFERÊNCIA DE TIMBRE",
      "index_tts2":        "SPEAKER 2 / EMOÇÃO (OPC.)",
      "kugelaudio_0_open": "REFERÊNCIA VOZ 2 (OPC.)",
      "qwen3_tts_base":    "SPEAKER 2 — VOZ DE REF.",
    };
    if (guide2Lbl) guide2Lbl.textContent = g2labels[modelId] || "REFERÊNCIA 2";
  } else {
    if (zoneGuide2) zoneGuide2.style.display = "none";
    uploadedPaths.guide2 = null;
    clearGuideZone(2);
  }

  /* --- Audio Task (audio_prompt_type) ----------------- */
  const taskRow  = document.getElementById("audio-task-row");
  const taskSel  = document.getElementById("audio-prompt-type");
  const taskLbl  = document.getElementById("audio-task-label");
  if (def.audio_task) {
    if (taskRow) taskRow.style.display = "";
    if (taskLbl) taskLbl.textContent = def.audio_task.label;
    if (taskSel) {
      taskSel.innerHTML = "";
      def.audio_task.options.forEach(opt => {
        const o = document.createElement("option");
        o.value = opt.value;
        o.textContent = opt.label;
        taskSel.appendChild(o);
      });
      taskSel.value = def.audio_task.default;
    }
    // Quando a tarefa muda, pode precisar mostrar/ocultar guide2 e audio_scale
    taskSel?.addEventListener("change", () => onAudioTaskChange(modelId, taskSel.value));
    onAudioTaskChange(modelId, def.audio_task.default);
  } else {
    if (taskRow) taskRow.style.display = "none";
  }

  /* --- Model Mode (idioma / speaker) ------------------ */
  const modeRow  = document.getElementById("model-mode-row");
  const modeSel  = document.getElementById("model-mode-select");
  const modeLbl  = document.getElementById("model-mode-label");
  if (def.model_mode) {
    if (modeRow) modeRow.style.display = "";
    if (modeLbl) modeLbl.textContent = def.model_mode.label;
    if (modeSel) {
      modeSel.innerHTML = "";
      def.model_mode.options.forEach(opt => {
        const o = document.createElement("option");
        o.value = opt.value;
        o.textContent = opt.label;
        modeSel.appendChild(o);
      });
      modeSel.value = def.model_mode.default;
    }
  } else {
    if (modeRow) modeRow.style.display = "none";
  }

  /* --- Temperature ------------------------------------ */
  const tempRow = document.getElementById("temperature-row");
  const tempSlider = document.getElementById("temperature-slider");
  if (def.temperature) {
    if (tempRow) tempRow.style.display = "";
    if (tempSlider) {
      tempSlider.value = def.temperature.default;
      document.getElementById("temperature-val").textContent = def.temperature.default.toFixed(2);
    }
  } else {
    if (tempRow) tempRow.style.display = "none";
  }

  /* --- Exaggeration (Chatterbox) ---------------------- */
  show("exaggeration-row", def.custom.includes("exaggeration"));
  show("pace-row",         def.custom.includes("pace"));

  /* --- BPM / KeyScale / TimeSignature / Language ISO (ACE-Step 1.5) */
  show("bpm-row",          def.custom.includes("bpm"));
  show("keyscale-row",     def.custom.includes("keyscale"));
  show("timesig-row",      def.custom.includes("timesig"));
  show("language-iso-row", def.custom.includes("language_iso"));

  /* --- Auto Split (KugelAudio, IndexTTS2, Qwen3 Base) */
  show("auto-split-row",   def.custom.includes("auto_split"));

  /* --- Guidance scale --------------------------------- */
  const guidanceRow    = document.getElementById("guidance-row");
  const guidanceSlider = document.getElementById("guidance-slider");
  const guidanceVal    = document.getElementById("guidance-val");
  if (def.guidance) {
    if (guidanceRow) guidanceRow.style.display = "";
    if (guidanceSlider) {
      guidanceSlider.value = def.guidance.default;
      if (guidanceVal) guidanceVal.textContent = def.guidance.default.toFixed(1);
    }
  } else {
    if (guidanceRow) guidanceRow.style.display = "none";
  }

  /* --- Top-K ------------------------------------------ */
  const topkRow    = document.getElementById("topk-row");
  const topkSlider = document.getElementById("topk-slider");
  const topkVal    = document.getElementById("topk-val");
  if (def.topk) {
    if (topkRow) topkRow.style.display = "";
    if (topkSlider) topkSlider.value = def.topk.default;
    if (topkVal) topkVal.textContent = String(def.topk.default);
  } else {
    if (topkRow) topkRow.style.display = "none";
  }

  /* --- Top-P ------------------------------------------ */
  const toppRow    = document.getElementById("topp-row");
  const toppSlider = document.getElementById("topp-slider");
  const toppVal    = document.getElementById("topp-val");
  if (def.topp) {
    if (toppRow) toppRow.style.display = "";
    if (toppSlider) toppSlider.value = def.topp.default;
    if (toppVal) toppVal.textContent = def.topp.default.toFixed(2);
  } else {
    if (toppRow) toppRow.style.display = "none";
  }

  /* --- LM Guidance / Alt Guidance (ACE-Step 1.5) ------- */
  const altGRow    = document.getElementById("alt-guidance-row");
  const altGSlider = document.getElementById("alt-guidance-slider");
  const altGVal    = document.getElementById("alt-guidance-val");
  if (def.alt_guidance) {
    if (altGRow) altGRow.style.display = "";
    if (altGSlider) altGSlider.value = def.alt_guidance.default;
    if (altGVal) altGVal.textContent = def.alt_guidance.default.toFixed(1);
  } else {
    if (altGRow) altGRow.style.display = "none";
  }

  /* --- Audio Scale (ACE-Step Cover Mode) --------------- */
  // Inicialmente oculto — aparece quando audio task incluir "A"
  show("audio-scale-row", false);
}

/* ── Muda visibilidade de audio_guide2 e audio_scale conforme audio task ── */
function onAudioTaskChange(modelId, taskValue) {
  const def = MODEL_DEFS[modelId];
  if (!def) return;
  const zoneGuide2 = document.getElementById("zone-guide2");

  // guide2 aparece quando task inclui "B" ou "AB" ou "AB2" ou "2"
  const needGuide2 = def.audio_guide2 && (
    taskValue.includes("B") || taskValue.includes("2")
  );
  if (zoneGuide2) zoneGuide2.style.display = needGuide2 ? "" : "none";
  if (!needGuide2) { uploadedPaths.guide2 = null; clearGuideZone(2); }

  // audio_scale aparece quando task incluir "A" (Cover Mode)
  const needScale = def.audio_scale && taskValue.includes("A");
  show("audio-scale-row", needScale);
}

/* ── Utilitário show/hide por id ──────────────────────── */
function show(id, visible) {
  const el = document.getElementById(id);
  if (el) el.style.display = visible ? "" : "none";
}

/* ══════════════════════════════════════════════════════
   PROMPT — contador de caracteres
══════════════════════════════════════════════════════ */
function initPrompt() {
  const ta = document.getElementById("prompt-input");
  const cc = document.getElementById("char-count");
  if (ta && cc) {
    ta.addEventListener("input", () => { cc.textContent = `${ta.value.length} / 12000`; saveState(); });
  }
}

/* ══════════════════════════════════════════════════════
   DURAÇÃO — slider com display ao vivo
══════════════════════════════════════════════════════ */
function updateDurDisplay() {
  const slider = document.getElementById("dur-slider");
  const label  = document.getElementById("dur-val");
  if (slider && label) label.textContent = `${slider.value}s`;
}

function initDuration() {
  const slider = document.getElementById("dur-slider");
  if (slider) {
    slider.addEventListener("input", updateDurDisplay);
    slider.addEventListener("input", saveState);
  }
  updateDurDisplay();
}

/* ══════════════════════════════════════════════════════
   SLIDERS COM DISPLAY AO VIVO
══════════════════════════════════════════════════════ */
function initSliders() {
  const pairs = [
    { id: "temperature-slider",  valId: "temperature-val",  dec: 2 },
    { id: "exaggeration-slider", valId: "exaggeration-val", dec: 2 },
    { id: "pace-slider",         valId: "pace-val",         dec: 2 },
    { id: "guidance-slider",     valId: "guidance-val",     dec: 1 },
    { id: "topk-slider",         valId: "topk-val",         dec: 0 },
    { id: "topp-slider",         valId: "topp-val",         dec: 2 },
    { id: "alt-guidance-slider", valId: "alt-guidance-val", dec: 1 },
    { id: "audio-scale-slider",  valId: "audio-scale-val",  dec: 2 },
  ];
  pairs.forEach(({ id, valId, dec }) => {
    const slider = document.getElementById(id);
    const valEl  = document.getElementById(valId);
    if (slider && valEl) {
      slider.addEventListener("input", () => {
        valEl.textContent = parseFloat(slider.value).toFixed(dec);
        saveState();
      });
    }
  });
}

/* ══════════════════════════════════════════════════════
   SEED MODE TOGGLE (Aleatório / Fixar)
══════════════════════════════════════════════════════ */
function initSeedRand() {
  const btnRand = document.getElementById("seed-mode-rand");
  const btnFix  = document.getElementById("seed-mode-fix");
  const input   = document.getElementById("seed-input");

  if (!btnRand || !btnFix) return;

  function setMode(mode) {
    if (mode === "rand") {
      btnRand.classList.add("active");
      btnFix.classList.remove("active");
      if (input) { input.disabled = true; }
    } else {
      btnFix.classList.add("active");
      btnRand.classList.remove("active");
      if (input) {
        input.disabled = false;
        input.focus();
        input.select();
      }
    }
  }

  btnRand.addEventListener("click", () => { setMode("rand"); saveState(); });
  btnFix.addEventListener("click",  () => { setMode("fix");  saveState(); });

  // Ao digitar no input, ativa automaticamente modo Fixar
  if (input) {
    input.addEventListener("input", () => {
      if (!btnFix.classList.contains("active")) setMode("fix");
      saveState();
    });
  }

  // Estado inicial: Aleatório ativo
  setMode("rand");
}

/* ══════════════════════════════════════════════════════
   UPLOAD — ZONA DE REFERÊNCIA DE VOZ
══════════════════════════════════════════════════════ */
function initGuide1Zone() {
  setupAudioZone("drop-guide1", "file-guide1", "guide1-preview", "guide1-empty",
                 "guide1-name", "guide1-waveform", "guide1-clear", 1);
}

function initGuide2Zone() {
  setupAudioZone("drop-guide2", "file-guide2", "guide2-preview", "guide2-empty",
                 "guide2-name", "guide2-waveform", "guide2-clear", 2);
}

function setupAudioZone(dropId, fileId, previewId, emptyId, nameId, waveId, clearId, slot) {
  const zone     = document.getElementById(dropId);
  const inputEl  = document.getElementById(fileId);
  const clearBtn = document.getElementById(clearId);
  if (!zone || !inputEl) return;

  async function handleFile(file) {
    showToast(`Carregando ${file.name}…`);
    try {
      const form = new FormData();
      form.append("file", file);
      const res  = await fetch("/upload/audio", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Upload falhou");
      uploadedPaths[`guide${slot}`] = data.path;
      showAudioPreview(previewId, emptyId, nameId, waveId, clearId, zone, file);
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
      uploadedPaths[`guide${slot}`] = null;
      clearGuideZone(slot);
    });
  }
}

function showAudioPreview(previewId, emptyId, nameId, waveId, clearId, zone, file) {
  const preview  = document.getElementById(previewId);
  const empty    = document.getElementById(emptyId);
  const nameEl   = document.getElementById(nameId);
  const waveEl   = document.getElementById(waveId);
  const clearBtn = document.getElementById(clearId);
  if (preview) preview.style.display = "flex";
  if (empty)   empty.style.display   = "none";
  if (clearBtn) clearBtn.style.display = "";
  if (zone)    zone.classList.add("has-file");
  const short = file.name.length > 22 ? file.name.substring(0, 19) + "…" : file.name;
  if (nameEl) nameEl.textContent = short;
  if (waveEl) {
    waveEl.innerHTML = "";
    for (let i = 0; i < 28; i++) {
      const h = 20 + Math.random() * 60;
      const bar = document.createElement("span");
      bar.className = "wave-bar";
      bar.style.cssText = `height:${h}%;animation-delay:${(i * 0.05).toFixed(2)}s`;
      waveEl.appendChild(bar);
    }
  }
}

function clearGuideZone(slot) {
  const ids = {
    1: { zone: "drop-guide1", preview: "guide1-preview", empty: "guide1-empty", clear: "guide1-clear", file: "file-guide1" },
    2: { zone: "drop-guide2", preview: "guide2-preview", empty: "guide2-empty", clear: "guide2-clear", file: "file-guide2" },
  };
  const d = ids[slot];
  if (!d) return;
  const zone    = document.getElementById(d.zone);
  const preview = document.getElementById(d.preview);
  const empty   = document.getElementById(d.empty);
  const clear   = document.getElementById(d.clear);
  const inp     = document.getElementById(d.file);
  if (zone)    zone.classList.remove("has-file");
  if (preview) preview.style.display = "none";
  if (empty)   empty.style.display   = "";
  if (clear)   clear.style.display   = "none";
  if (inp)     inp.value = "";
}

/* ══════════════════════════════════════════════════════
   BUILD AUDIO PAYLOAD
══════════════════════════════════════════════════════ */
function buildAudioPayload() {
  const def = MODEL_DEFS[currentModel];

  const prompt     = document.getElementById("prompt-input")?.value.trim()    || "";
  const alt_prompt = def.alt_prompt
    ? (document.getElementById("alt-prompt-input")?.value.trim() || "")
    : "";

  const seedModeRand = document.getElementById("seed-mode-rand")?.classList.contains("active") ?? true;
  const seedFixed    = parseInt(document.getElementById("seed-input")?.value ?? "") || 42;
  const seed         = seedModeRand ? -1 : seedFixed;

  const numGenerations = parseInt(document.getElementById("num-generations")?.value) || 1;

  const duration = def.duration
    ? (parseInt(document.getElementById("dur-slider")?.value) || def.duration.default)
    : null;

  const temperature = def.temperature
    ? (parseFloat(document.getElementById("temperature-slider")?.value) || def.temperature.default)
    : null;

  const guidance_scale = def.guidance
    ? (parseFloat(document.getElementById("guidance-slider")?.value) || def.guidance.default)
    : null;

  // [FIX-CLONE] Modelos sem seletor de Audio Task (ex.: Chatterbox) podem EXIGIR um
  // audio_prompt_type fixo p/ usar a voz de referência. O chatterbox_handler exige "A"
  // (clonar da referência) — sem isso, sai a voz default (masculina), ignorando o sample.
  const audio_prompt_type = def.audio_task
    ? (document.getElementById("audio-prompt-type")?.value || def.audio_task.default)
    : (def.audio_prompt_fixed || "");

  const model_mode = def.model_mode
    ? (document.getElementById("model-mode-select")?.value || def.model_mode.default)
    : null;

  // audio_guide paths
  const audio_guide  = uploadedPaths.guide1 || null;
  const audio_guide2 = uploadedPaths.guide2 || null;

  // audio_scale (ACE-Step Cover Mode)
  const audio_scale = def.audio_scale
    ? (parseFloat(document.getElementById("audio-scale-slider")?.value) || 0.5)
    : null;

  // Top-K / Top-P / Alt Guidance
  const top_k = def.topk
    ? (parseInt(document.getElementById("topk-slider")?.value) || def.topk.default)
    : null;
  const top_p = def.topp
    ? (parseFloat(document.getElementById("topp-slider")?.value) || def.topp.default)
    : null;
  const alt_guidance_scale = def.alt_guidance
    ? (parseFloat(document.getElementById("alt-guidance-slider")?.value) || def.alt_guidance.default)
    : null;

  // custom_settings por modelo
  const custom_settings = buildCustomSettings(def.custom);

  // Monta payload final — inclui apenas campos relevantes
  const payload = {
    model:            currentModel,
    prompt,
    seed,
    num_generations:  numGenerations,
    audio_prompt_type,
  };

  if (alt_prompt) payload.alt_prompt = alt_prompt;
  if (duration !== null) payload.duration_seconds = duration;
  if (temperature !== null) payload.temperature = temperature;
  if (guidance_scale !== null) payload.guidance_scale = guidance_scale;
  if (audio_guide) payload.audio_guide = audio_guide;
  if (audio_guide2) payload.audio_guide2 = audio_guide2;
  if (audio_scale !== null) payload.audio_scale = audio_scale;
  if (top_k !== null) payload.top_k = top_k;
  if (top_p !== null) payload.top_p = top_p;
  if (alt_guidance_scale !== null) payload.alt_guidance_scale = alt_guidance_scale;
  if (model_mode !== null) payload.model_mode = model_mode;
  if (custom_settings && Object.keys(custom_settings).length > 0) {
    payload.custom_settings = custom_settings;
  }

  return payload;
}

function buildCustomSettings(customKeys) {
  const settings = {};
  if (!customKeys || !customKeys.length) return settings;

  if (customKeys.includes("exaggeration")) {
    const v = parseFloat(document.getElementById("exaggeration-slider")?.value);
    if (!isNaN(v)) settings.exaggeration = v;
  }
  if (customKeys.includes("pace")) {
    const v = parseFloat(document.getElementById("pace-slider")?.value);
    if (!isNaN(v)) settings.pace = v;
  }
  if (customKeys.includes("bpm")) {
    const v = document.getElementById("bpm-input")?.value?.trim();
    if (v && v !== "") {
      const bpm = parseInt(v);
      if (!isNaN(bpm)) settings.bpm = bpm;
    }
  }
  if (customKeys.includes("keyscale")) {
    const v = document.getElementById("keyscale-input")?.value?.trim();
    if (v) settings.keyscale = v;
  }
  if (customKeys.includes("timesig")) {
    const v = document.getElementById("timesig-select")?.value;
    if (v && v !== "") settings.timesignature = parseInt(v);
  }
  if (customKeys.includes("language_iso")) {
    const v = document.getElementById("language-iso-input")?.value?.trim().toLowerCase();
    if (v) settings.language = v;
  }
  if (customKeys.includes("auto_split")) {
    const v = document.getElementById("auto-split-input")?.value?.trim();
    if (v && v !== "") {
      const s = parseFloat(v);
      if (!isNaN(s)) settings.auto_split_every_s = s;
    }
  }

  return settings;
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
    audClearJobState();
    stopPolling();
    audHideCanvasHud();
    const hero = document.getElementById("hero-section");
    const wrap = document.getElementById("audio-player-wrap");
    if (hero && (!wrap || !wrap.classList.contains("visible"))) hero.style.display = "";
    showToast("Cancelado", "warn");
    setTimeout(hideToast, 2000);
  } catch (e) { console.error("abort:", e); }
}

async function onGenerate() {
  const def    = MODEL_DEFS[currentModel];
  const prompt = document.getElementById("prompt-input")?.value.trim() || "";

  // Validação: prompt
  if (!prompt) {
    showToast("Escreva um prompt / letra primeiro!", "warn");
    setTimeout(hideToast, 2500);
    return;
  }

  // Validação: alt_prompt obrigatório (HeartMuLa — keywords, Yue — tags)
  if (def.alt_prompt && def.alt_prompt.required) {
    const alt = document.getElementById("alt-prompt-input")?.value.trim() || "";
    if (!alt) {
      showToast(`Campo "${def.alt_prompt.label}" é obrigatório.`, "warn");
      setTimeout(hideToast, 3000);
      return;
    }
  }

  // Validação: audio_guide obrigatório (Chatterbox, IndexTTS2)
  const audioTaskVal = document.getElementById("audio-prompt-type")?.value || "";
  const requiresGuide1 = (
    currentModel === "chatterbox" ||
    currentModel === "index_tts2" ||
    (currentModel === "qwen3_tts_base" && audioTaskVal !== "")
  );
  if (requiresGuide1 && !uploadedPaths.guide1) {
    showToast("Faça upload da voz de referência.", "warn");
    setTimeout(hideToast, 3000);
    document.getElementById("drop-guide1")?.classList.add("zone-required");
    setTimeout(() => document.getElementById("drop-guide1")?.classList.remove("zone-required"), 2500);
    return;
  }

  if (currentJobId) {
    showToast("Geração em andamento…", "warn");
    return;
  }

  // Trava imediata
  currentJobId = "pending";
  document.getElementById("btn-generate")?.classList.add("generating");

  const payload = buildAudioPayload();

  // Log obrigatório
  console.log("[ACS AUDIO PAYLOAD]", payload);
  console.table({
    model:             payload.model,
    prompt_length:     payload.prompt?.length,
    duration:          payload.duration_seconds,
    seed:              payload.seed,
    audio_prompt_type: payload.audio_prompt_type,
    has_guide1:        !!payload.audio_guide,
    has_guide2:        !!payload.audio_guide2,
    temperature:       payload.temperature,
    guidance:          payload.guidance_scale,
  });

  try {
    const res  = await fetch("/generate/audio", {
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
    audSaveJobState(currentJobId, "queued", 0);
    audShowCanvasHud(0, "Na fila...", null, false);
    startPolling();
  } catch (err) {
    currentJobId = null;
    document.getElementById("btn-generate")?.classList.remove("generating");
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
      const data = await res.json();
      const dl   = data.download;
      const isDl = dl && dl.active;
      const pct  = data.progress || 0;
      let msg;
      if (isDl) {
        const dlPct = dl.percent != null ? dl.percent : pct;
        const dlStats = _buildDlStatsAud(dl);
        const spd = dl.speed_mbps > 0 ? ` — ${dl.speed_mbps.toFixed(1)} MB/s` : "";
        msg = `Baixando modelos necessários${dl.percent != null ? ` ${dl.percent.toFixed(1)}%` : ""}${spd}`;
        audShowCanvasHud(dlPct, "Baixando modelos necessários", dlStats || "Aguardando progresso real do download...", true);
        const label = document.getElementById("aud-progress-label");
        // [R-19] NUNCA exibir o nome técnico do modelo no HUD de download.
        // O HUD já mostra % · velocidade · tamanho · ETA via dlStats.
        if (label) label.textContent = "";
        audSaveJobState(currentJobId, data.status, dlPct);
      } else {
        msg = {
          queued:     "Na fila…",
          running:    `Processando… ${pct}%`,
          generating: `Gerando… ${pct}%`,
          done:       "✓ Concluído!",
          error:      `Erro: ${data.error || "desconhecido"}`,
          cancelled:  "Cancelado",
        }[data.status] || data.status;
        // [B38-001] downloading_lora incluído — progresso visível durante LoRA DOD
        if (["queued", "running", "generating", "downloading_lora"].includes(data.status)) {
          audShowCanvasHud(pct, msg, null, false);
          audSaveJobState(currentJobId, data.status, pct);
        }
      }
      showToast(msg, data.status === "error" ? "err" : "");
      if (data.status === "done") {
        audClearJobState({ output: data.output || null });
        stopPolling();
        audHideCanvasHud();
        if (window.playNotifBeep) playNotifBeep();
        if (data.output) {
          showAudioPlayer(data.output.url, data.output.filename, data.output.size_mb);
          loadRecentOutputs();
        }
        setTimeout(hideToast, 2500);
      }
      if (data.status === "error" || data.status === "cancelled") {
        audClearJobState({ error: data.error || null });
        stopPolling();
        audHideCanvasHud();
        const hero = document.getElementById("hero-section");
        const wrap = document.getElementById("audio-player-wrap");
        if (hero && (!wrap || !wrap.classList.contains("visible"))) hero.style.display = "";
        setTimeout(hideToast, 4500);
      }
    } catch (e) { console.error("poll:", e); }
  }, 2000);
}

function stopPolling() {
  clearInterval(pollInterval);
  pollInterval = null;
  currentJobId = null;
  document.getElementById("btn-generate")?.classList.remove("generating");
}

/* ══════════════════════════════════════════════════════
   AUDIO PLAYER
══════════════════════════════════════════════════════ */
function initAudioPlayer() {
  const audio    = document.getElementById("audio-output");
  const playBtn  = document.getElementById("ap-play-btn");
  const fill     = document.getElementById("ap-progress-fill");
  const timeCur  = document.getElementById("ap-time-cur");
  const timeDur  = document.getElementById("ap-time-dur");
  const bar      = document.getElementById("ap-progress-bar");

  if (!audio) return;

  // Play / pause
  if (playBtn) {
    playBtn.addEventListener("click", () => {
      if (audio.paused) { audio.play(); playBtn.textContent = "⏸"; }
      else              { audio.pause(); playBtn.textContent = "▶"; }
    });
  }

  // Atualiza barra de progresso e tempo
  audio.addEventListener("timeupdate", () => {
    if (!audio.duration || isNaN(audio.duration)) return;
    const pct = (audio.currentTime / audio.duration) * 100;
    if (fill) fill.style.width = `${pct}%`;
    if (timeCur) timeCur.textContent = formatTime(audio.currentTime);
  });

  audio.addEventListener("loadedmetadata", () => {
    if (timeDur) timeDur.textContent = formatTime(audio.duration);
  });

  audio.addEventListener("ended", () => {
    if (playBtn) playBtn.textContent = "▶";
  });

  // Seek por clique na barra
  if (bar) {
    bar.addEventListener("click", e => {
      if (!audio.duration) return;
      const rect = bar.getBoundingClientRect();
      const pct  = (e.clientX - rect.left) / rect.width;
      audio.currentTime = pct * audio.duration;
    });
  }
}

function formatTime(secs) {
  if (!isFinite(secs)) return "0:00";
  const m = Math.floor(secs / 60);
  const s = Math.floor(secs % 60);
  return `${m}:${String(s).padStart(2, "0")}`;
}

function showAudioPlayer(url, filename, sizeMb) {
  const wrap    = document.getElementById("audio-player-wrap");
  const audio   = document.getElementById("audio-output");
  const hero    = document.getElementById("hero-section");
  const fnEl    = document.getElementById("ap-filename");
  const szEl    = document.getElementById("ap-size");
  const playBtn = document.getElementById("ap-play-btn");
  const fillEl  = document.getElementById("ap-progress-fill");
  const waveEl  = document.getElementById("ap-waveform");

  if (!wrap || !audio) return;

  audio.src = url;
  audio.load();
  audio.play().catch(() => {});
  if (playBtn) playBtn.textContent = "⏸";
  if (fillEl)  fillEl.style.width = "0%";

  if (fnEl) fnEl.textContent = filename || "";
  if (szEl) szEl.textContent = sizeMb ? `${sizeMb} MB` : "";

  // Waveform decorativa
  if (waveEl) {
    waveEl.innerHTML = "";
    for (let i = 0; i < 64; i++) {
      const h = 15 + Math.random() * 70;
      const bar = document.createElement("span");
      bar.className = "ap-wave-bar";
      bar.style.cssText = `height:${h}%;animation-delay:${(i * 0.03).toFixed(2)}s`;
      waveEl.appendChild(bar);
    }
  }

  if (hero) hero.style.display = "none";
  wrap.classList.add("visible");

  // [B38-007] fetch/blob — garante download mesmo em pywebview sem Content-Disposition
  const dlBtn = document.getElementById("btn-download");
  if (dlBtn) dlBtn.onclick = () => _downloadFile(url, filename || "audio.wav");
}

// ── Download helper — B38-007v2 ──────────────────────────────
// window.location + ?download=1 → Content-Disposition: attachment no servidor
function _downloadFile(url, filename) {
  window.location.href = url + (url.includes("?") ? "&" : "?") + "download=1";
}

/* ══════════════════════════════════════════════════════
   RECENT OUTPUTS (galeria lateral)
══════════════════════════════════════════════════════ */
async function loadRecentOutputs() {
  try {
    const res  = await fetch("/outputs?type=audio&limit=200");
    const data = await res.json();
    const grid  = document.getElementById("recent-grid");
    const panel = document.getElementById("gallery-panel");
    if (!grid) return;
    grid.innerHTML = "";
    const audios = (data.outputs || []).filter(o => o.type === "audio").slice(0, 20);
    if (panel) panel.style.display = audios.length ? "" : "none";
    if (!audios.length) return;
    audios.forEach(a => {
      const card = document.createElement("div");
      card.className = "audio-card";
      card.innerHTML = `
        <div class="audio-card-icon">&#9836;</div>
        <div class="audio-card-info">${a.title || a.name || "áudio"}</div>
      `;
      card.addEventListener("click", () => showAudioPlayer(a.url, a.name, a.size));
      // [FIX-DRAG] card da galeria arrastável para as zonas (payload do media-browser)
      card.draggable = true;
      card.addEventListener("dragstart", e => {
        const payload = JSON.stringify({ url: a.url, type: "audio", name: a.name || "" });
        try { e.dataTransfer.setData("application/x-acs-media", payload); } catch (_) {}
        try { e.dataTransfer.setData("text/plain", payload); } catch (_) {}
        try { e.dataTransfer.setData("text/uri-list", a.url); } catch (_) {}
        try { e.dataTransfer.effectAllowed = "copy"; } catch (_) {}
      });
      grid.appendChild(card);
      // Botão delete (compartilhado via gallery-delete.js)
      if (window.attachGalleryDeleteBtn) window.attachGalleryDeleteBtn(card, a.name);
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

/* ══════════════════════════════════════════════════════
   GALERIA DIREITA — auto-hide no hover (igual video/motion)
   [FIX] A aba Áudio não tinha o handler do gallery-hotzone — a galeria
   lateral direita não abria ao passar o mouse. Espelha o initGalleryAutoHide
   do video.js. Debounce de 600ms p/ evitar flicker.
══════════════════════════════════════════════════════ */
(function initGalleryAutoHide() {
  const hotzone = document.getElementById("gallery-hotzone");
  const panel   = document.getElementById("gallery-panel");
  if (!hotzone || !panel) return;
  let _hideTimer = null;
  function peekShow() { clearTimeout(_hideTimer); panel.classList.add("peek"); }
  function peekHide() { clearTimeout(_hideTimer); _hideTimer = setTimeout(() => panel.classList.remove("peek"), 600); }
  hotzone.addEventListener("mouseenter", peekShow);
  hotzone.addEventListener("mouseleave", peekHide);
  panel.addEventListener("mouseenter", peekShow);
  panel.addEventListener("mouseleave", peekHide);
})();
