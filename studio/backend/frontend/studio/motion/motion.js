if(!window.playNotifBeep){var _ns=document.createElement("script");_ns.src="/studio/notif.js?v=1";document.head.appendChild(_ns)}
/* ============================================================
   ACS Studio - Motion  v2
   Modes: Image Motion · Talking Image · Infinite Talk
   Dock: gen-dock (bottom fixed) + gallery panel (right overlay)
   NO references to third-party engine names in user-visible text.
============================================================ */

const API = "";   // same origin

/* ?? State ??????????????????????????????????????????????????? */
const MOTION_STATE_KEY = "acs:motion:state";
let _stateReady = false;

function saveState() {
  if (!_stateReady) return;
  try {
    localStorage.setItem(MOTION_STATE_KEY, JSON.stringify({
      mode:      currentMode,
      prompt:    document.getElementById("dock-prompt")?.value    ?? "",
      model:     document.getElementById("cfg-model")?.value      ?? "",
      seed:      parseInt(document.getElementById("cfg-seed")?.value ?? "-1") || -1,
      duration:  parseInt(document.getElementById("dur-slider")?.value ?? "5") || 5,
      resolution:document.getElementById("cfg-res")?.value        ?? "",
      steps:     parseInt(document.getElementById("cfg-steps")?.value ?? "20") || 20,
      amplitude: parseFloat(document.getElementById("amp-slider")?.value ?? "1") || 1,
      endFrame:  endFrameActive,
      dualSpk:   dualSpkActive,
    }));
  } catch { /* quota exceeded — ignorar silenciosamente */ }
}

function restoreState() {
  let s;
  try { s = JSON.parse(localStorage.getItem(MOTION_STATE_KEY)); } catch { s = null; }
  if (!s || typeof s !== "object") return;

  // Mode — via switchMode para sincronizar toda a UI
  if (typeof s.mode === "string" && s.mode && s.mode !== currentMode) {
    switchMode(s.mode);
  }

  // Prompt
  if (typeof s.prompt === "string") {
    const el = document.getElementById("dock-prompt");
    if (el) el.value = s.prompt;
  }

  // Model select — apenas options visíveis para o mode atual (switchMode filtra por display)
  if (typeof s.model === "string" && s.model) {
    const el = document.getElementById("cfg-model");
    if (el && [...el.options].some(o => o.value === s.model && o.style.display !== "none")) {
      el.value = s.model;
    }
  }

  // Seed
  if (typeof s.seed === "number") {
    const el = document.getElementById("cfg-seed");
    if (el) el.value = s.seed >= 0 ? String(s.seed) : "-1";
  }

  // Duration slider
  if (typeof s.duration === "number" && s.duration > 0) {
    const el = document.getElementById("dur-slider");
    if (el) {
      el.value = s.duration;
      // dispara evento para atualizar display se existir
      el.dispatchEvent(new Event("input"));
    }
  }

  // Resolution
  if (typeof s.resolution === "string" && s.resolution) {
    const el = document.getElementById("cfg-res");
    if (el && [...el.options].some(o => o.value === s.resolution)) el.value = s.resolution;
  }

  // Steps
  if (typeof s.steps === "number" && s.steps > 0) {
    const el = document.getElementById("cfg-steps");
    if (el) el.value = String(s.steps);
  }

  // Amplitude slider
  if (typeof s.amplitude === "number") {
    const el = document.getElementById("amp-slider");
    if (el) {
      el.value = s.amplitude;
      el.dispatchEvent(new Event("input"));
    }
  }

  // End-frame addon
  if (s.endFrame === true && !endFrameActive) {
    document.getElementById("apill-end-frame")?.click();
  }

  // Dual speaker addon
  if (s.dualSpk === true && !dualSpkActive) {
    document.getElementById("apill-dual-spk")?.click();
  }
}

let currentMode  = "image-motion";   // image-motion | talking-image | infinite-talk
let currentJobId = null;
let pollInterval = null;
let endFrameActive  = false;   // Image Motion: End Frame addon
let dualSpkActive   = false;   // Talking Image: Speaker 2 addon
let genStartTime    = null;
let toastTimer      = null;

/* ── Phase 3: Job State Persistence ────────────────────────── */
const MOT_JOB_STATE_KEY  = "acs:state:motion";
const MOT_JOB_MAX_AGE_MS = 6 * 60 * 60 * 1000;  // 6h

function motSaveJobState(jId, lastStatus, lastProgress) {
  try {
    const ex   = motLoadJobState();
    const same = ex?.job_id === jId;
    localStorage.setItem(MOT_JOB_STATE_KEY, JSON.stringify({
      job_id:        jId,
      tab:           "motion",
      started_at:    same ? (ex.started_at || Date.now()) : Date.now(),
      last_status:   lastStatus  ?? "queued",
      last_progress: lastProgress ?? 0,
      last_output:   same ? (ex.last_output || null) : null,
      last_error:    null,
    }));
  } catch { }
}

function motLoadJobState() {
  try { return JSON.parse(localStorage.getItem(MOT_JOB_STATE_KEY)); }
  catch { return null; }
}

function motClearJobState({ output = null, error = null } = {}) {
  try {
    localStorage.setItem(MOT_JOB_STATE_KEY, JSON.stringify({
      job_id: null, tab: "motion", started_at: null,
      last_status: null, last_progress: null,
      last_output: output, last_error: error,
    }));
  } catch { }
}

async function motCheckJobRecovery() {
  let s;
  try { s = motLoadJobState(); } catch { return; }
  if (!s) return;
  if (!s.job_id && s.last_output) {
    try { showOutput(s.last_output); } catch { }
    return;
  }
  if (!s.job_id) return;
  if (s.started_at && (Date.now() - s.started_at) > MOT_JOB_MAX_AGE_MS) { motClearJobState(); return; }
  let data;
  try {
    const resp = await fetch(`${API}/status/${s.job_id}`);
    if (resp.status === 404) { motClearJobState(); return; }
    data = await resp.json();
    const job = Array.isArray(data.jobs) ? data.jobs.find(j => j.id === s.job_id) : data;
    if (!job) { motClearJobState(); return; }
    data = job;
  } catch { motClearJobState(); return; }
  if (data.status === "done") {
    motClearJobState({ output: data.output ?? null });
    if (data.output) { try { showOutput(data.output); } catch { } loadRecentOutputs(); }
    return;
  }
  if (data.status === "error") {
    motClearJobState({ error: data.error || "Erro" });
    setProgress("failed", 0, "Erro na geração anterior");
    setGenerating(false);
    return;
  }
  if (data.status === "cancelled") { motClearJobState(); return; }
  if (["queued", "running", "generating"].includes(data.status)) {
    currentJobId = s.job_id;
    genStartTime = s.started_at || Date.now();
    setGenerating(true);
    const pct = s.last_progress ?? 0;
    setProgress("generating", pct, s.last_status || "Retomando...", "", null);
    motShowCanvasHud(pct, s.last_status || "Retomando...", null, false);
    startPolling(currentJobId);
  }
}

/* ── Phase 3: Central HUD helpers ──────────────────────────── */
function motShowCanvasHud(pct, statusText, dlStats, showCalm) {
  const el   = document.getElementById("motion-loading");
  const hero = document.getElementById("motion-hero");
  if (el) el.classList.add("visible");
  if (hero) hero.style.display = "none";
  const bar    = document.getElementById("mot-progress-bar");
  const pctEl  = document.getElementById("mot-hud-pct");
  const status = document.getElementById("mot-hud-status");
  const sub    = document.getElementById("mot-dl-sub");
  const calm   = document.getElementById("mot-dl-calm");
  const safePct = Math.min(100, Math.max(0, pct || 0));
  if (bar)    bar.style.width    = safePct + "%";
  if (pctEl)  pctEl.textContent  = Math.round(safePct) + "%";
  if (status) status.textContent = statusText || "Gerando...";
  if (sub)    sub.textContent    = dlStats || "";
  if (calm)   calm.style.display = showCalm ? "block" : "none";
}

function motHideCanvasHud() {
  const el = document.getElementById("motion-loading");
  if (el) el.classList.remove("visible");
}

function motResetCanvasHud() {
  motHideCanvasHud();
  const hero = document.getElementById("motion-hero");
  const wrap = document.getElementById("motion-player-wrap");
  if (hero && (!wrap || !wrap.classList.contains("visible"))) hero.style.display = "";
  const bar   = document.getElementById("mot-progress-bar");
  const pctEl = document.getElementById("mot-hud-pct");
  const status = document.getElementById("mot-hud-status");
  const sub   = document.getElementById("mot-dl-sub");
  const calm  = document.getElementById("mot-dl-calm");
  if (bar)    { bar.style.width = "0%"; }
  if (pctEl)  pctEl.textContent  = "0%";
  if (status) status.textContent = "Inicializando...";
  if (sub)    sub.textContent    = "";
  if (calm)   calm.style.display = "none";
}

function _buildDlStatsMot(dl) {
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

// Upload slot paths (null = not yet uploaded)
const uploads = {
  "ref-img":   null,   // reference image / face / scene-1
  "end-frame": null,   // end frame (FLF)
  "scene-2":   null,
  "scene-3":   null,
  "scene-4":   null,
  "audio-1":   null,
  "audio-2":   null,
};

// [TEST-HOOK 2026-06-27] Permite a preview injetar uploads/modo p/ testar modelos que precisam
// de arquivo (a preview não consegue setar <input type=file>). Inofensivo em produção.
window.__acsMotionTest = {
  setUpload: (slot, path) => { uploads[slot] = path; },
  setMode:   (m) => { currentMode = m; },
  getUploads:() => ({ ...uploads }),
};

/* ?? Per-mode metadata ??????????????????????????????????????? */
const MODE_META = {
  // [12.25] Animar Personagem (Scail2) — transferência de movimento: foto + vídeo guia
  "character-animate": {
    icon: "🕺",
    name: "Animar Personagem",
    desc: "Copie o movimento de um vídeo para a foto de uma pessoa.",
    badges: [{ cls: "dsbadge-exp", text: "Personagem" }],
    promptPlaceholder: "Descreva a cena/ação – ex: a pessoa dança naturalmente, movimento expressivo...",
    models: ["Character Animate"],
    defaultModel: "Character Animate",
    refImgLabel: "Foto da Pessoa",
    refImgTxt: "Solte uma FOTO de pessoa (não desenho)",
    audio1Label: "Áudio",
    infoRows: [
      ["Função",      "Animar a foto de uma pessoa copiando o movimento de um vídeo"],
      ["Obrigatório", "Foto de pessoa REAL + vídeo de movimento"],
      ["Saída",       "Vídeo da pessoa se movendo como no vídeo guia"],
      ["Tecnologia",  "Pose 3D + máscara automática"],
      ["Dica",        "Foto nítida, pessoa inteira, fundo simples = melhor resultado"],
      ["Tempo",       "É o mais pesado (~5-6 min)"],
    ],
  },
  "image-motion": {
    icon: "⟳",
    name: "Image Motion",
    desc: "Anime uma imagem estática com Prompt e controles de movimento.",
    badges: [{ cls: "dsbadge-stable", text: "Estável" }],
    promptPlaceholder: "Descreva o movimento desejado – ex: panorâmica suave para direita, folhas se movendo ao vento...",
    models: ["Studio AI I2V", "Cinematic Pro 1.1", "Cinematic Pro Full"],
    defaultModel: "Studio AI I2V",
    refImgLabel: "Imagem de Referência",
    refImgTxt: "Solte a imagem aqui",
    audio1Label: "Áudio",
    infoRows: [
      ["Função",       "Animar qualquer imagem estática com movimento cinemático"],
      ["Obrigatório",  "Imagem de referência"],
      ["Opcional",     "End frame (modo FLF), Prompt de texto"],
      ["Saída",        "Clipe de vídeo animado curto"],
      ["Áudio",        "Não obrigatório"],
      ["Prompt",     "Suportado – guia a direção do movimento"],
      ["End Frame",    "Ativar via pill + End Frame"],
      ["Duração",    "2 – 30 segundos"],
      ["Dica",       "Amplitude baixa (0,3–0,7) para movimento sutil"],
    ],
  },
  "talking-image": {
    icon: "🗣",
    name: "Talking Image",
    desc: "Transforme um retrato em um personagem falante sincronizado com áudio.",
    badges: [
      { cls: "dsbadge-exp",   text: "Experimental" },
      { cls: "dsbadge-audio", text: "Áudio Obrigatório" },
    ],
    promptPlaceholder: "Descreva o contexto da cena – ex: pessoa fazendo apresentação em sala de conferências...",
    models: ["Talking Head"],
    defaultModel: "Talking Head",
    refImgLabel: "Imagem de Rosto",
    refImgTxt: "Solte o retrato aqui",
    audio1Label: "Áudio – Falante",
    infoRows: [
      ["Função",       "Animar retrato com sincronismo labial de alta precisão"],
      ["Obrigatório",  "Imagem de rosto (frontal) + arquivo de áudio"],
      ["Opcional",     "Áudio do 2° falante (pill + Falante 2)"],
      ["Saída",        "Vídeo falante sincronizado com o áudio"],
      ["Áudio",      "Obrigatório – WAV / MP3 / OGG"],
      ["Prompt",     "Opcional – descreva o contexto da cena"],
      ["Dois Falantes","Ativar via pill + Falante 2"],
      ["Módulo",       "Requer módulo compatível de talking-head"],
      ["Dica",         "Use um retrato frontal nítido para melhores resultados"],
    ],
  },
  "infinite-talk": {
    icon: "∞",
    name: "Infinite Talk",
    desc: "Diálogo longo com transições de cena e sincronização de áudio.",
    badges: [
      { cls: "dsbadge-exp",   text: "Experimental" },
      { cls: "dsbadge-audio", text: "Áudio Obrigatório" },
    ],
    promptPlaceholder: "Descreva a cena – ex: âncora de notícias em estúdio profissional de TV...",
    models: ["Infinite Talk"],
    defaultModel: "Infinite Talk",
    refImgLabel: "Cena 1",
    refImgTxt: "Solte a imagem da cena aqui",
    audio1Label: "Áudio – Narração",
    infoRows: [
      ["Função",       "Gerar vídeo falante longo com transições de cena"],
      ["Obrigatório",  "Imagem da Cena 1 + arquivo de áudio completo"],
      ["Opcional",     "Imagem da Cena 2 para transição automática"],
      ["Saída",        "Vídeo falante multicena (duração pelo áudio)"],
      ["Áudio",      "Obrigatório – trilha completa em WAV / MP3"],
      ["Prompt",     "Opcional – descreva o cenário"],
      ["Cenas",        "Até 2 cenas visíveis no dock"],
      ["Módulo",       "Requer módulo compatível de vídeo longo"],
      ["Dica",         "O comprimento do áudio define a duração mínima do vídeo"],
    ],
  },
};

/* ??????????????????????????????????????????????????????????????
   MODE SWITCHING
?????????????????????????????????????????????????????????????? */
function switchMode(mode) {
  if (!MODE_META[mode]) return;
  currentMode = mode;
  const meta = MODE_META[mode];
  const dock = document.getElementById("gen-dock");

  // ?? CSS class on dock ??????????????????????????????????????
  dock.classList.remove("mode-image-motion", "mode-talking-image", "mode-infinite-talk", "mode-character-animate");
  dock.classList.add("mode-" + mode);

  // ?? Mode strip pills ???????????????????????????????????????
  document.querySelectorAll(".mpill[data-mode]").forEach(p =>
    p.classList.toggle("active", p.dataset.mode === mode));

  // ?? Addon pills visibility ?????????????????????????????????
  const apillEnd  = document.getElementById("apill-end-frame");
  const apillDual = document.getElementById("apill-dual-spk");
  apillEnd.style.display  = (mode === "image-motion")  ? "" : "none";
  apillDual.style.display = (mode === "talking-image") ? "" : "none";

  // Reset addons on mode switch
  if (mode !== "image-motion" && endFrameActive) {
    endFrameActive = false;
    apillEnd.classList.remove("active");
    const endWrap = document.getElementById("zone-end-frame-wrap");
    if (endWrap) endWrap.classList.remove("addon-active");
    clearSlot("end-frame");
  }
  if (mode !== "talking-image" && dualSpkActive) {
    dualSpkActive = false;
    apillDual.classList.remove("active");
    document.getElementById("zone-audio-2-wrap").style.display = "none";
    clearSlot("audio-2");
  }

  // ?? Dock-side info ?????????????????????????????????????????
  document.getElementById("ds-icon").textContent = meta.icon;
  document.getElementById("ds-name").textContent = meta.name;
  document.getElementById("ds-desc").textContent = meta.desc;
  const badgesEl = document.getElementById("ds-badges");
  badgesEl.innerHTML = meta.badges.map(b =>
    `<span class="dock-side-badge ${b.cls}">${b.text}</span>`).join("");

  // ?? Prompt placeholder ?????????????????????????????????????
  document.getElementById("dock-prompt").placeholder = meta.promptPlaceholder;

  // ?? Zone labels (ref-img varies by mode) ??????????????????
  document.getElementById("zone-ref-img-label").textContent = meta.refImgLabel;
  document.getElementById("zone-ref-img-txt").textContent   = meta.refImgTxt;
  document.getElementById("zone-audio-1-label").textContent = meta.audio1Label;

  // ?? Model options ??????????????????????????????????????????
  const sel = document.getElementById("cfg-model");
  sel.querySelectorAll("option").forEach(o => o.style.display = "none");
  meta.models.forEach(v => {
    const o = sel.querySelector(`option[value="${v}"]`);
    if (o) o.style.display = "";
  });
  sel.value = meta.defaultModel;

  // ?? Info panel ?????????????????????????????????????????????
  const infoWrap = document.getElementById("ptab-info-wrap");
  infoWrap.innerHTML = meta.infoRows.map(([k, v]) =>
    `<div style="display:flex;gap:6px;align-items:flex-start">
       <span style="flex:0 0 72px;font-size:9.5px;font-weight:700;color:#303030;text-transform:uppercase;letter-spacing:.3px;padding-top:1px">${k}</span>
       <span style="flex:1;color:#555;font-size:10.5px">${v}</span>
     </div>`
  ).join("");

  // ?? Hero mode cards ????????????????????????????????????????
  document.querySelectorAll(".hero-mode-card").forEach(c =>
    c.style.borderColor = c.dataset.mode === mode ? "rgba(77,216,216,.4)" : "");
}

/* ??????????????????????????????????????????????????????????????
   ADDON PILLS
?????????????????????????????????????????????????????????????? */
function initAddonPills() {
  // End Frame pill (Image Motion)
  document.getElementById("apill-end-frame")?.addEventListener("click", () => {
    endFrameActive = !endFrameActive;
    document.getElementById("apill-end-frame").classList.toggle("active", endFrameActive);
    const wrap = document.getElementById("zone-end-frame-wrap");
    wrap.classList.toggle("addon-active", endFrameActive);
    if (!endFrameActive) clearSlot("end-frame");
    saveState();
  });

  // Speaker 2 pill (Talking Image)
  document.getElementById("apill-dual-spk")?.addEventListener("click", () => {
    dualSpkActive = !dualSpkActive;
    document.getElementById("apill-dual-spk").classList.toggle("active", dualSpkActive);
    document.getElementById("zone-audio-2-wrap").style.display = dualSpkActive ? "flex" : "none";
    if (!dualSpkActive) clearSlot("audio-2");
    saveState();
  });

  // Refresh gallery
  document.getElementById("apill-refresh")?.addEventListener("click", () => loadRecentOutputs());
}

/* ??????????????????????????????????????????????????????????????
   PROMPT TABS
?????????????????????????????????????????????????????????????? */
function initPromptTabs() {
  document.querySelectorAll(".ptab[data-ptab]").forEach(btn => {
    btn.addEventListener("click", () => {
      document.querySelectorAll(".ptab[data-ptab]").forEach(b => b.classList.remove("active"));
      btn.classList.add("active");
      const tab = btn.dataset.ptab;
      document.getElementById("ptab-prompt-wrap").style.display = tab === "prompt" ? "flex" : "none";
      document.getElementById("ptab-info-wrap").style.display   = tab === "info"   ? "flex" : "none";
    });
  });
  // Char counter
  document.getElementById("dock-prompt")?.addEventListener("input", e => {
    const n = e.target.value.length;
    const el = document.getElementById("char-count");
    if (el) el.textContent = n + " / 500";
  });
}

/* ??????????????????????????????????????????????????????????????
   UPLOAD ZONES - IMAGE
?????????????????????????????????????????????????????????????? */
function initImageZone(dropId, inputId, thumbId, clearId, slot) {
  const drop  = document.getElementById(dropId);
  const input = document.getElementById(inputId);
  const thumb = document.getElementById(thumbId);
  const clrBtn = document.getElementById(clearId);
  if (!drop || !input) return;

  drop.addEventListener("click", e => {
    if (e.target === clrBtn) return;
    input.click();
  });
  drop.addEventListener("dragover",  e => { e.preventDefault(); drop.classList.add("drag-over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("drag-over"));
  drop.addEventListener("drop", e => {
    e.preventDefault(); drop.classList.remove("drag-over");
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith("image/")) handleImageFile(slot, file, drop, thumb);
  });
  input.addEventListener("change", () => {
    const file = input.files[0];
    if (file) handleImageFile(slot, file, drop, thumb);
    input.value = "";
  });
  clrBtn?.addEventListener("click", e => {
    e.stopPropagation();
    clearSlot(slot, drop, thumb, input);
  });
}

function handleImageFile(slot, file, drop, thumb) {
  const reader = new FileReader();
  reader.onload = ev => {
    if (thumb) {
      thumb.style.backgroundImage = `url(${ev.target.result})`;
      thumb.style.display = "block";
    }
    drop.classList.add("has-file");
  };
  reader.readAsDataURL(file);

  const fd = new FormData();
  fd.append("file", file);
  fetch(`${API}/upload-ref`, { method: "POST", body: fd })
    .then(r => r.json())
    .then(d => { uploads[slot] = d.path; })
    .catch(err => showToast("err", "Falha no upload: " + err.message));
}

/* [FIX-MOTION] Zona de VÍDEO (zone-ctrl-video) — antes NÃO era inicializada, então o
   placeholder "Vídeo de Movimento" era morto (clique/drop não faziam nada). Espelha o
   initImageZone mas aceita video/* e mostra um frame-poster. /upload-ref já aceita .mp4. */
function initVideoZone(dropId, inputId, thumbId, clearId, slot) {
  const drop  = document.getElementById(dropId);
  const input = document.getElementById(inputId);
  const thumb = document.getElementById(thumbId);
  const clrBtn = document.getElementById(clearId);
  if (!drop || !input) return;

  drop.addEventListener("click", e => {
    if (e.target === clrBtn) return;
    input.click();
  });
  drop.addEventListener("dragover",  e => { e.preventDefault(); drop.classList.add("drag-over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("drag-over"));
  drop.addEventListener("drop", e => {
    e.preventDefault(); drop.classList.remove("drag-over");
    const file = e.dataTransfer.files[0];
    if (file && file.type.startsWith("video/")) handleVideoFile(slot, file, drop, thumb);
  });
  input.addEventListener("change", () => {
    const file = input.files[0];
    if (file) handleVideoFile(slot, file, drop, thumb);
    input.value = "";
  });
  clrBtn?.addEventListener("click", e => {
    e.stopPropagation();
    clearSlot(slot, drop, thumb, input);
  });
}

function handleVideoFile(slot, file, drop, thumb) {
  // poster: 1º frame do vídeo como miniatura (fallback = nome do arquivo)
  if (thumb) {
    try {
      const url = URL.createObjectURL(file);
      const v = document.createElement("video");
      v.src = url; v.muted = true; v.preload = "metadata";
      v.addEventListener("loadeddata", () => {
        try {
          const c = document.createElement("canvas");
          c.width = 200; c.height = 120;
          c.getContext("2d").drawImage(v, 0, 0, c.width, c.height);
          thumb.style.backgroundImage = `url(${c.toDataURL("image/jpeg", 0.7)})`;
          thumb.style.display = "block";
        } catch (_) { thumb.textContent = "🎬 " + file.name; thumb.style.display = "block"; }
        URL.revokeObjectURL(url);
      });
      v.addEventListener("error", () => { thumb.textContent = "🎬 " + file.name; thumb.style.display = "block"; });
    } catch (_) { thumb.textContent = "🎬 " + file.name; thumb.style.display = "block"; }
  }
  drop.classList.add("has-file");

  const fd = new FormData();
  fd.append("file", file);
  fetch(`${API}/upload-ref`, { method: "POST", body: fd })
    .then(r => r.json())
    .then(d => { uploads[slot] = d.path; })
    .catch(err => showToast("err", "Falha no upload do vídeo: " + err.message));
}

/* ??????????????????????????????????????????????????????????????
   UPLOAD ZONES - AUDIO
?????????????????????????????????????????????????????????????? */
function initAudioZone(dropId, inputId, emptyId, previewId, fnameId, clearId, slot) {
  const drop    = document.getElementById(dropId);
  const input   = document.getElementById(inputId);
  const emptyEl = document.getElementById(emptyId);
  const prevEl  = document.getElementById(previewId);
  const fnameEl = document.getElementById(fnameId);
  const clrBtn  = document.getElementById(clearId);
  if (!drop || !input) return;

  drop.addEventListener("click", e => {
    if (e.target === clrBtn) return;
    input.click();
  });
  drop.addEventListener("dragover",  e => { e.preventDefault(); drop.classList.add("drag-over"); });
  drop.addEventListener("dragleave", () => drop.classList.remove("drag-over"));
  drop.addEventListener("drop", e => {
    e.preventDefault(); drop.classList.remove("drag-over");
    const file = e.dataTransfer.files[0];
    if (file) handleAudioFile(slot, file, drop, emptyEl, prevEl, fnameEl);
  });
  input.addEventListener("change", () => {
    const file = input.files[0];
    if (file) handleAudioFile(slot, file, drop, emptyEl, prevEl, fnameEl);
    input.value = "";
  });
  clrBtn?.addEventListener("click", e => {
    e.stopPropagation();
    clearAudioSlot(slot, drop, emptyEl, prevEl, input);
  });
}

function handleAudioFile(slot, file, drop, emptyEl, prevEl, fnameEl) {
  if (fnameEl) fnameEl.textContent = file.name;
  if (emptyEl) emptyEl.style.display = "none";
  if (prevEl)  prevEl.style.display  = "flex";
  drop.classList.add("has-file");
  uploads[slot] = null; // pessimistic

  const fd = new FormData();
  fd.append("file", file);
  fetch(`${API}/upload/audio`, { method: "POST", body: fd })
    .then(r => r.json())
    .then(d => { uploads[slot] = d.path; })
    .catch(err => {
      clearAudioSlot(slot, drop, emptyEl, prevEl, null);
      showToast("err", "Falha no upload de áudio: " + err.message);
    });
}

/* ?? Generic clear helpers ??????????????????????????????????? */
function clearSlot(slot, drop, thumb, input) {
  uploads[slot] = null;
  if (drop)  drop.classList.remove("has-file");
  if (thumb) { thumb.style.backgroundImage = ""; thumb.style.display = "none"; }
  if (input) input.value = "";
}

function clearAudioSlot(slot, drop, emptyEl, prevEl, input) {
  uploads[slot] = null;
  if (drop)    drop.classList.remove("has-file");
  if (emptyEl) emptyEl.style.display = "flex";
  if (prevEl)  prevEl.style.display  = "none";
  if (input)   input.value = "";
}

/* ??????????????????????????????????????????????????????????????
   SLIDERS
?????????????????????????????????????????????????????????????? */
function initSliders() {
  // Duration
  const durSlider = document.getElementById("dur-slider");
  const durNum    = document.getElementById("dur-num");
  durSlider?.addEventListener("input", () => {
    if (durNum) durNum.textContent = durSlider.value;
  });
  // Amplitude
  const ampSlider = document.getElementById("amp-slider");
  const ampNum    = document.getElementById("amp-num");
  ampSlider?.addEventListener("input", () => {
    if (ampNum) ampNum.textContent = parseFloat(ampSlider.value).toFixed(1);
  });
  // Seed dice
  document.getElementById("cfg-seed-dice")?.addEventListener("click", () => {
    const seed = Math.floor(Math.random() * 2147483647);
    const inp = document.getElementById("cfg-seed");
    if (inp) inp.value = seed;
  });
}

/* ??????????????????????????????????????????????????????????????
   MODO AVANÇADO — [FIX-MOTION] portado da aba Vídeo
?????????????????????????????????????????????????????????????? */
function initAdvancedDrawer() {
  const drawer = document.getElementById("advanced-drawer");
  document.getElementById("adv-toggle")?.addEventListener("click", () => drawer?.classList.toggle("open"));
  document.getElementById("adv-close") ?.addEventListener("click", () => drawer?.classList.remove("open"));

  // sliders → atualiza valor exibido
  const bindVal = (id, valId, fmt) => {
    const el = document.getElementById(id), out = document.getElementById(valId);
    el?.addEventListener("input", () => { if (out) out.textContent = fmt(el.value); });
  };
  bindVal("adv-guidance",  "adv-guidance-val",  v => parseFloat(v).toFixed(1));
  bindVal("adv-grain-int", "adv-grain-int-val", v => parseFloat(v).toFixed(2));
  bindVal("adv-grain-sat", "adv-grain-sat-val", v => parseFloat(v).toFixed(2));

  // guidance phases pills
  document.querySelectorAll("#advanced-drawer .adv-phase-pill").forEach(pill => {
    pill.addEventListener("click", () => {
      document.querySelectorAll("#advanced-drawer .adv-phase-pill").forEach(p => p.classList.remove("active"));
      pill.classList.add("active");
    });
  });

  // prompt enhancer: OFF → ENHANCE(T) → RELAY(T1) → OFF
  const enh = document.getElementById("adv-enhancer");
  enh?.addEventListener("click", () => {
    const cur  = enh.dataset.mode || "";
    const next = cur === "" ? "T" : cur === "T" ? "T1" : "";
    enh.dataset.mode  = next;
    enh.textContent   = next === "" ? "OFF" : next === "T" ? "ENHANCE" : "RELAY";
    enh.classList.toggle("active", next !== "");
  });
}

// Lê os parâmetros do drawer p/ mesclar no payload (mesmos campos da aba Vídeo).
function getAdvancedParams() {
  const p = {
    negative_prompt:          document.getElementById("negative-input")?.value.trim() || "",
    guidance_scale:           parseFloat(document.getElementById("adv-guidance")?.value) || 5.0,
    riflex_setting:           parseInt(document.getElementById("adv-riflex")?.value || "0", 10),
    temporal_upsampling:      document.getElementById("adv-temporal")?.value || "",
    self_refiner_setting:     parseInt(document.getElementById("adv-self-refiner")?.value || "0", 10),
    spatial_upsampling:       document.getElementById("adv-spatial")?.value || "",
    force_fps:                document.getElementById("adv-fps")?.value || "",
    film_grain_intensity:     parseFloat(document.getElementById("adv-grain-int")?.value || "0"),
    film_grain_saturation:    parseFloat(document.getElementById("adv-grain-sat")?.value || "0.5"),
    guidance_phases_override: (() => {
      const ph = document.querySelector("#advanced-drawer .adv-phase-pill.active")?.dataset.phase ?? "";
      if (ph === "1") return 1;
      if (ph === "2") return 2;
      return -1;
    })(),
  };
  // enhancer só sobrescreve o default do modo se o usuário escolheu algo
  const enh = document.getElementById("adv-enhancer")?.dataset.mode ?? "";
  if (enh) p.prompt_enhancer = enh;
  return p;
}

/* ??????????????????????????????????????????????????????????????
   GENERATE
?????????????????????????????????????????????????????????????? */
function initGenerateButton() {
  document.getElementById("btn-gen")?.addEventListener("click", startGenerate);
  document.getElementById("btn-abort")?.addEventListener("click", cancelJob);
}

async function startGenerate() {
  stopPolling();
  hideOutput();

  const model    = document.getElementById("cfg-model")?.value  ?? "";
  const duration = parseInt(document.getElementById("dur-slider")?.value ?? "5");
  const res      = document.getElementById("cfg-res")?.value    ?? "832x480";
  const steps    = parseInt(document.getElementById("cfg-steps")?.value ?? "20");
  const seed     = parseInt(document.getElementById("cfg-seed")?.value  ?? "-1");
  const amp      = parseFloat(document.getElementById("amp-slider")?.value ?? "1.0");
  const prompt   = document.getElementById("dock-prompt")?.value?.trim() ?? "";

  let endpoint = "/generate/i2v";
  let payload  = {};

  // [12.25] Animar Personagem (Scail2): foto da pessoa + vídeo de movimento → V1
  if (currentMode === "character-animate") {
    if (!uploads["ref-img"]) {
      markRequired("zone-ref-img-drop");
      showToast("warn", "Adicione a FOTO da pessoa (foto real).");
      return;
    }
    if (!uploads["ctrl-video"]) {
      markRequired("zone-ctrl-video-drop");
      showToast("warn", "Adicione o vídeo de movimento.");
      return;
    }
    endpoint = "/generate/i2v";
    payload  = {
      prompt,
      model:               "Character Animate",
      resolution:          res,
      duration,
      steps,
      seed,
      guidance_scale:      5.0,
      motion_amplitude:    1.0,
      ref_image_path:      uploads["ref-img"],
      ctrl_video_path:     uploads["ctrl-video"],
      ctrl_video_prompt_type: "V1",
      prompt_enhancer:     "",
    };

  // ?? Image Motion ???????????????????????????????????????????
  } else if (currentMode === "image-motion") {
    if (!uploads["ref-img"]) {
      markRequired("zone-ref-img-drop");
      showToast("warn", "Adicione uma imagem de referência para continuar.");
      return;
    }
    if (endFrameActive && uploads["end-frame"]) {
      endpoint = "/generate/flf";
      payload = {
        prompt,
        model,
        resolution:       res,
        duration,
        steps,
        seed,
        guidance_scale:   5.0,
        motion_amplitude: amp,
        ref_image_path:   uploads["ref-img"],
        end_image_path:   uploads["end-frame"],
        prompt_enhancer:  prompt ? "T" : "",
      };
    } else {
      endpoint = "/generate/i2v";
      payload = {
        prompt,
        model,
        resolution:       res,
        duration,
        steps,
        seed,
        guidance_scale:   5.0,
        motion_amplitude: amp,
        ref_image_path:   uploads["ref-img"],
        prompt_enhancer:  prompt ? "T" : "",
      };
    }

  // ?? Talking Image (MultiTalk) ??????????????????????????????
  } else if (currentMode === "talking-image") {
    if (!uploads["ref-img"]) {
      markRequired("zone-ref-img-drop");
      showToast("warn", "Adicione uma foto de rosto para continuar.");
      return;
    }
    if (!uploads["audio-1"]) {
      markRequired("zone-audio-1-drop");
      showToast("warn", "Adicione um arquivo de áudio para continuar.");
      return;
    }
    const hasAudio2 = dualSpkActive && !!uploads["audio-2"];
    endpoint = "/generate/i2v";
    payload  = {
      prompt,
      model:               "Talking Head",
      resolution:          res,
      duration,
      steps,
      seed,
      guidance_scale:      5.0,
      motion_amplitude:    1.0,
      ref_image_path:      uploads["ref-img"],
      audio_prompt_type:   hasAudio2 ? "B" : "A",
      audio_path:          uploads["audio-1"],
      audio_path2:         hasAudio2 ? uploads["audio-2"] : "",
      speakers_locations:  hasAudio2 ? "0:45 55:100" : "",
      audio_guidance_scale: 4,
      audio_scale:          1.0,
      prompt_enhancer:      "",
    };

  // ?? Infinite Talk ??????????????????????????????????????????
  } else if (currentMode === "infinite-talk") {
    if (!uploads["ref-img"]) {
      markRequired("zone-ref-img-drop");
      showToast("warn", "Adicione a imagem da Cena 1 para continuar.");
      return;
    }
    if (!uploads["audio-1"]) {
      markRequired("zone-audio-1-drop");
      showToast("warn", "Adicione um arquivo de áudio para continuar.");
      return;
    }
    const extraScenes = ["scene-2", "scene-3", "scene-4"]
      .map(k => uploads[k]).filter(Boolean);
    endpoint = "/generate/i2v";
    payload  = {
      prompt,
      model:               "Infinite Talk",
      resolution:          res,
      duration,
      steps,
      seed,
      guidance_scale:      5.0,
      motion_amplitude:    1.0,
      ref_image_path:      uploads["ref-img"],
      // InfiniteTalk: "KI" é flag de pipeline OBRIGATÓRIA (Sharp Transitions + I2V)
      // Wan2GP requer video_prompt_type="0KI" — o backend adiciona o prefixo "0"
      inject_video_prompt_type: "KI",
      ref_inject_paths:    extraScenes,
      audio_prompt_type:   "A",
      audio_path:          uploads["audio-1"],
      audio_guidance_scale: 4,
      audio_scale:          1.0,
      prompt_enhancer:      "",
    };
  }

  // [FIX-MOTION] mescla os parâmetros do Modo Avançado (mesmos campos da aba Vídeo).
  // Spread DEPOIS do payload → guidance/enhancer/grain/riflex/etc. do drawer prevalecem.
  payload = { ...payload, ...getAdvancedParams() };

  // ?? Fire request ???????????????????????????????????????????
  setGenerating(true);
  setProgress("generating", 0, "Enviando para a fila...");
  genStartTime = Date.now();

  try {
    const resp = await fetch(`${API}${endpoint}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!resp.ok) {
      const err = await resp.json().catch(() => ({}));
      throw new Error(err.detail ?? `HTTP ${resp.status}`);
    }
    const data = await resp.json();
    currentJobId = data.job_id;
    motSaveJobState(currentJobId, "queued", 0);
    motResetCanvasHud();
    motShowCanvasHud(0, "Na fila...", null, false);
    setProgress("generating", 5, `Na fila - job ${currentJobId}`);
    startPolling(currentJobId);
  } catch (err) {
    setProgress("failed", 0, err.message);
    showToast("err", "Erro: " + err.message);
    setGenerating(false);
  }
}

/* ?? required zone animation ????????????????????????????????? */
function markRequired(id) {
  const el = document.getElementById(id);
  if (!el) return;
  el.classList.add("zone-required");
  setTimeout(() => el.classList.remove("zone-required"), 1400);
}

/* ??????????????????????????????????????????????????????????????
   DOWNLOAD PROGRESS HELPERS
?????????????????????????????????????????????????????????????? */
function _fmtSizeMot(mb) {
  if (mb == null) return "";
  return mb >= 1024 ? `${(mb / 1024).toFixed(1)} GB` : `${mb.toFixed(0)} MB`;
}
function _buildDlSubtextMot(dl) {
  try {
    if (!dl || !dl.active) return null;
    const parts = [];
    if (dl.percent   != null)                        parts.push(`${dl.percent.toFixed(1)}%`);
    if (dl.speed_mbps != null && dl.speed_mbps > 0)  parts.push(`${dl.speed_mbps.toFixed(1)} MB/s`);
    if (dl.downloaded_mb != null && dl.total_mb != null) {
      parts.push(`${_fmtSizeMot(dl.downloaded_mb)} / ${_fmtSizeMot(dl.total_mb)}`);
    } else if (dl.downloaded_mb != null) {
      parts.push(_fmtSizeMot(dl.downloaded_mb));
    }
    if (dl.eta_sec != null && dl.eta_sec > 0) {
      const m = Math.floor(dl.eta_sec / 60);
      const s = String(Math.floor(dl.eta_sec % 60)).padStart(2, "0");
      parts.push(`ETA ${m}:${s}`);
    }
    if (parts.length === 0) return null;
    let line = parts.join(" — ");
    // [FASE C / R-19] NÃO exibir nome técnico do modelo no HUD — só %/velocidade/tamanho/ETA.
    return line;
  } catch (_) { return null; }
}

/* ??????????????????????????????????????????????????????????????
   POLLING
?????????????????????????????????????????????????????????????? */
function startPolling(jobId) {
  stopPolling();
  pollInterval = setInterval(() => pollJob(jobId), 2500);
}

function stopPolling() {
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
}

async function pollJob(jobId) {
  try {
    const resp = await fetch(`${API}/status/${jobId}`);
    if (!resp.ok) return;
    const data = await resp.json();
    const job  = Array.isArray(data.jobs) ? data.jobs.find(j => j.id === jobId) : data;
    if (!job) return;

    const status   = job.status   ?? "";
    const progress = job.progress ?? 0;
    const step     = job.step     ?? "";
    const download = job.download ?? null;
    const elapsed  = genStartTime ? Math.round((Date.now() - genStartTime) / 1000) : 0;
    const timeStr  = elapsed > 0 ? `${elapsed}s decorridos` : "";
    const dlSub    = _buildDlSubtextMot(download);
    const isDl     = download && download.active;

    if (status === "queued") {
      setProgress("generating", progress || 2, `In queue. ${step}`, timeStr, isDl ? (dlSub || "Aguardando progresso real do download...") : null);
      motSaveJobState(jobId, "queued", progress || 0);
    } else if (status === "loading" || status === "preparing") {
      const activePct = isDl ? (download.percent ?? (progress || 8)) : (progress || 8);
      setProgress("generating", activePct, isDl ? "Baixando modelos necessários" : `Loading model. ${step}`, timeStr, isDl ? (dlSub || "Aguardando progresso real do download...") : null);
      if (isDl) {
        const stats = _buildDlStatsMot(download);
        const label = document.getElementById("mot-progress-label");
        if (label) label.textContent = download.filename ? `↓ ${download.filename}` : "";
        motShowCanvasHud(download.percent ?? activePct, "Baixando modelos necessários", stats || "Aguardando progresso real do download...", true);
      }
      motSaveJobState(jobId, status, activePct);
    } else if (status === "generating") {
      const activePct = isDl ? (download.percent ?? progress) : progress;
      setProgress("generating", activePct, isDl ? "Baixando modelos necessários" : `Generating. ${step}`, timeStr, isDl ? (dlSub || "Aguardando progresso real do download...") : null);
      if (isDl) {
        const stats = _buildDlStatsMot(download);
        const label = document.getElementById("mot-progress-label");
        if (label) label.textContent = download.filename ? `↓ ${download.filename}` : "";
        motShowCanvasHud(download.percent ?? activePct, "Baixando modelos necessários", stats || "Aguardando progresso real do download...", true);
      }
      motSaveJobState(jobId, status, activePct);
    } else if (status === "downloading_lora") {
      // [B38-001] LoRA DOD — reutiliza o handler isDl completo
      const activePct = isDl ? (download.percent ?? progress) : (progress || 0);
      const dlLabel   = isDl && download.filename ? `↓ ${download.filename}` : "Baixando Estilo...";
      setProgress("generating", activePct, "Baixando modelos necessários", timeStr, isDl ? (dlSub || "Aguardando progresso real do download...") : null);
      if (isDl) {
        const stats = _buildDlStatsMot(download);
        const label = document.getElementById("mot-progress-label");
        if (label) label.textContent = dlLabel;
        motShowCanvasHud(activePct, "Baixando modelos necessários", stats || "Aguardando progresso real do download...", true);
      }
      motSaveJobState(jobId, status, activePct);
    } else if (status === "done") {
      motClearJobState({ output: job.output ?? null });
      stopPolling();
      setProgress("completed", 100, "Geração concluída", timeStr);
      if (window.playNotifBeep) playNotifBeep();
      const path = job.output ?? null;
      if (path) showOutput(path);
      else showToast("warn", "Completed - output not detected");
      setGenerating(false);
      loadRecentOutputs();
    } else if (status === "cancelled") {
      motClearJobState();
      stopPolling();
      setProgress("failed", 0, "Cancelado");
      setGenerating(false);
    } else if (status === "error" || status === "failed") {
      motClearJobState({ error: job.error || null });
      stopPolling();
      const msg = job.error ?? "Erro desconhecido";
      setProgress("failed", 0, msg);
      showToast("err", "Falha: " + msg);
      setGenerating(false);
    }
  } catch (e) {
    console.warn("[Motion] Poll error:", e);
  }
}

/* ??????????????????????????????????????????????????????????????
   CANCEL
?????????????????????????????????????????????????????????????? */
async function cancelJob() {
  if (!currentJobId) return;
  motClearJobState();
  stopPolling();
  try {
    await fetch(`${API}/cancel/${currentJobId}`, { method: "POST" });
  } catch (_) { /* ignore */ }
  setProgress("failed", 0, "Cancelamento solicitado");
  setGenerating(false);
  currentJobId = null;
}

/* ??????????????????????????????????????????????????????????????
   UI HELPERS - Progress + Toast
?????????????????????????????????????????????????????????????? */
function setProgress(state, pct, step, timeStr, dlSubtext) {
  const ui    = document.getElementById("progress-ui");
  const bar   = document.getElementById("pui-bar");
  const stepEl = document.getElementById("pui-step");
  const pctEl  = document.getElementById("pui-pct");
  const timeEl = document.getElementById("pui-time");
  const subEl  = document.getElementById("pui-sub");
  if (!ui) return;
  ui.dataset.state = state;
  if (bar)    bar.style.width = Math.min(100, Math.max(0, pct)) + "%";
  if (stepEl) stepEl.textContent = step ?? "";
  if (pctEl)  pctEl.textContent  = pct > 0 ? pct + "%" : "";
  if (timeEl) timeEl.textContent = timeStr ?? "";
  if (subEl)  subEl.textContent  = dlSubtext ?? "";
  // Central HUD (canvas overlay)
  if (state === "generating") {
    const isDl = dlSubtext != null && dlSubtext !== "";
    motShowCanvasHud(pct, isDl ? "Baixando modelos necessários" : (step || "Gerando..."), isDl ? dlSubtext : null, isDl);
  } else if (state === "completed" || state === "failed") {
    motHideCanvasHud();
    if (state === "failed") {
      const hero = document.getElementById("motion-hero");
      const wrap = document.getElementById("motion-player-wrap");
      if (hero && (!wrap || !wrap.classList.contains("visible"))) hero.style.display = "";
    }
  }
}

function setGenerating(active) {
  const btn   = document.getElementById("btn-gen");
  const abort = document.getElementById("btn-abort");
  if (btn) {
    btn.disabled = active;
    btn.classList.toggle("generating", active);
    btn.innerHTML = active
      ? `<span class="gen-lbl">GERANDO.</span>`
      : `<span class="gen-plus">+</span><span class="gen-lbl">GERAR</span>`;
  }
  if (abort) abort.style.opacity = active ? "1" : "";
}

function showToast(type, msg) {
  const toast  = document.getElementById("gen-toast");
  const msgEl  = document.getElementById("toast-msg");
  if (!toast || !msgEl) return;
  msgEl.textContent = msg;
  toast.className = "gen-toast visible" + (type ? " " + type : "");
  if (toastTimer) clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 5000);
}

/* ??????????????????????????????????????????????????????????????
   OUTPUT PLAYER
?????????????????????????????????????????????????????????????? */
function showOutput(path) {
  const wrap   = document.getElementById("motion-player-wrap");
  const video  = document.getElementById("vp-video");
  const fname  = document.getElementById("vp-filename");
  const dlBtn  = document.getElementById("vp-dl");
  const cpyBtn = document.getElementById("vp-copy");
  const hero   = document.getElementById("motion-hero");
  if (!wrap || !video) return;

  const filename = path.split("\\").pop().split("/").pop();
  const url = `/outputs/${encodeURIComponent(filename)}`;

  video.src = url;
  if (fname)  fname.textContent = filename;
  if (dlBtn)  { dlBtn.href = url; dlBtn.download = filename; }
  if (cpyBtn) {
    cpyBtn.onclick = () => {
      navigator.clipboard?.writeText(path).catch(() => {});
      cpyBtn.textContent = "✓ Copiado";
      setTimeout(() => cpyBtn.textContent = "⎘ Copiar caminho", 2000);
    };
  }

  // Show player, hide hero
  if (hero) hero.style.display = "none";
  wrap.classList.add("visible");
}

function hideOutput() {
  const wrap  = document.getElementById("motion-player-wrap");
  const video = document.getElementById("vp-video");
  const hero  = document.getElementById("motion-hero");
  if (wrap) {
    wrap.classList.remove("visible");
    if (video) { video.pause(); video.src = ""; }
  }
  if (hero) hero.style.display = "";
}

/* ??????????????????????????????????????????????????????????????
   GALLERY PANEL
?????????????????????????????????????????????????????????????? */
function initGalleryHotzone() {
  const panel   = document.getElementById("gallery-panel");
  const hotzone = document.getElementById("gallery-hotzone");
  if (!panel || !hotzone) return;

  let leaveTimer = null;

  const showPanel = () => {
    if (leaveTimer) { clearTimeout(leaveTimer); leaveTimer = null; }
    panel.classList.add("peek");
  };
  const hidePanel = () => {
    leaveTimer = setTimeout(() => panel.classList.remove("peek"), 220);
  };

  hotzone.addEventListener("mouseenter", showPanel);
  panel.addEventListener("mouseenter",   showPanel);
  panel.addEventListener("mouseleave",   hidePanel);
  hotzone.addEventListener("mouseleave", hidePanel);
}

async function loadRecentOutputs() {
  const grid = document.getElementById("gallery-grid");
  if (!grid) return;

  try {
    const resp = await fetch(`${API}/outputs?type=video&limit=200`);
    if (!resp.ok) return;
    const data = await resp.json();
    const items = Array.isArray(data) ? data : (data.files ?? data.outputs ?? []);
    if (!items.length) {
      grid.innerHTML = `<div style="padding:20px 12px;font-size:10px;color:#333;text-align:center">Nenhuma geração ainda</div>`;
      return;
    }
    grid.innerHTML = items.map(item => {
      // [FIX-GALERIA] o /outputs entrega {name, url:"/file/..."}; antes o código procurava
      // item.path/filename (inexistentes → vazio) e montava /outputs/<file> (rota 404) → vídeo
      // nunca carregava = miniatura PRETA. Agora usa a url real do backend (/file/...).
      const filename = typeof item === "string"
        ? item.split("\\").pop().split("/").pop()
        : (item.name ?? (item.path ?? item.filename ?? "").split("\\").pop().split("/").pop());
      // SEMPRE encodar: a item.url do backend vem com espaços CRUS → 404 no <video src>.
      // /file/<nome-encodado> serve 200 (rota /file/{filename}, não /outputs/).
      const url = `/file/${encodeURIComponent(filename)}`;
      // poster JPG do backend: os mp4 têm moov no fim → <video> não renderiza frame
      // como thumb (preto). O poster (imagem) sempre aparece; preload=none = leve.
      const poster = `/thumb/${encodeURIComponent(filename)}`;
      const ts = (typeof item === "object" && item.date) ? String(item.date).split(" ").pop() : "";
      return `
        <div class="video-card" data-filename="${filename}" onclick="loadGalleryItem('${url}','${filename}','${url}')">
          <video src="${url}" poster="${poster}" muted preload="none" loop playsinline
            onmouseenter="this.play()" onmouseleave="this.pause();this.currentTime=0"></video>
          <div class="video-card-info">${filename}${ts ? " · " + ts : ""}</div>
        </div>`;
    }).join("");
    // [FIX-DRAG] cards arrastáveis para as zonas (mesmo payload do media-browser)
    grid.querySelectorAll('.video-card[data-filename]').forEach(card => {
      const fn = card.dataset.filename;
      const u  = `/file/${encodeURIComponent(fn)}`;   // [FIX-GALERIA] /file/, não /outputs/ (404)
      const vEl = card.querySelector("video"); if (vEl) vEl.draggable = false;
      card.draggable = true;
      card.addEventListener("dragstart", e => {
        const payload = JSON.stringify({ url: u, type: "video", name: fn });
        try { e.dataTransfer.setData("application/x-acs-media", payload); } catch (_) {}
        try { e.dataTransfer.setData("text/plain", payload); } catch (_) {}
        try { e.dataTransfer.setData("text/uri-list", u); } catch (_) {}
        try { e.dataTransfer.effectAllowed = "copy"; } catch (_) {}
      });
    });
    // Botão delete (compartilhado via gallery-delete.js) — anexar após renderizar
    if (window.attachGalleryDeleteBtn) {
      grid.querySelectorAll('.video-card[data-filename]').forEach(card => {
        window.attachGalleryDeleteBtn(card, card.dataset.filename);
      });
    }
  } catch (e) {
    console.warn("[Motion] Gallery load error:", e);
  }
}

function loadGalleryItem(url, filename, path) {
  const wrap   = document.getElementById("motion-player-wrap");
  const video  = document.getElementById("vp-video");
  const fname  = document.getElementById("vp-filename");
  const dlBtn  = document.getElementById("vp-dl");
  const hero   = document.getElementById("motion-hero");
  if (!video) return;
  video.src = url;
  if (fname)  fname.textContent = filename;
  if (dlBtn)  { dlBtn.href = url; dlBtn.download = filename; }
  if (hero)   hero.style.display = "none";
  if (wrap)   wrap.classList.add("visible");
  // Close gallery panel
  document.getElementById("gallery-panel")?.classList.remove("peek");
}

/* ??????????????????????????????????????????????????????????????
   HERO MODE CARDS - click to switch mode
?????????????????????????????????????????????????????????????? */
function initHeroCards() {
  document.querySelectorAll(".hero-mode-card[data-mode]").forEach(card => {
    card.addEventListener("click", () => switchMode(card.dataset.mode));
  });
}

// bfcache guard: limpar timer de polling ao sair da página
window.addEventListener("pagehide", () => {
  if (pollInterval) { clearInterval(pollInterval); pollInterval = null; }
  // currentJobId NOT zeroed — localStorage (MOT_JOB_STATE_KEY) is source of truth for recovery
});

/* ??????????????????????????????????????????????????????????????
   INIT
?????????????????????????????????????????????????????????????? */
document.addEventListener("DOMContentLoaded", async () => {

  // Mode pills
  document.querySelectorAll(".mpill[data-mode]").forEach(btn =>
    btn.addEventListener("click", () => { switchMode(btn.dataset.mode); saveState(); }));

  // Addon pills
  initAddonPills();

  // Prompt tabs
  initPromptTabs();

  // Hero mode cards
  initHeroCards();

  // Image zones
  initImageZone("zone-ref-img-drop",    "zone-ref-img-input",    "zone-ref-img-thumb",    "zone-ref-img-clear",    "ref-img");
  initImageZone("zone-end-frame-drop",  "zone-end-frame-input",  "zone-end-frame-thumb",  "zone-end-frame-clear",  "end-frame");
  initImageZone("zone-scene-2-drop",    "zone-scene-2-input",    "zone-scene-2-thumb",    "zone-scene-2-clear",    "scene-2");
  initImageZone("zone-scene-3-drop",    "zone-scene-3-input",    "zone-scene-3-thumb",    "zone-scene-3-clear",    "scene-3");
  initImageZone("zone-scene-4-drop",    "zone-scene-4-input",    "zone-scene-4-thumb",    "zone-scene-4-clear",    "scene-4");
  // [FIX-MOTION] zona de VÍDEO de movimento (estava sem init → placeholder morto)
  initVideoZone("zone-ctrl-video-drop", "zone-ctrl-video-input", "zone-ctrl-video-thumb", "zone-ctrl-video-clear", "ctrl-video");

  // Audio zones
  initAudioZone("zone-audio-1-drop", "zone-audio-1-input", "zone-audio-1-empty", "audio-1-preview", "audio-1-fname", "zone-audio-1-clear", "audio-1");
  initAudioZone("zone-audio-2-drop", "zone-audio-2-input", "zone-audio-2-empty", "audio-2-preview", "audio-2-fname", "zone-audio-2-clear", "audio-2");

  // Sliders + seed dice
  initSliders();
  initAdvancedDrawer();   // [FIX-MOTION] Modo Avançado

  // Generate + abort buttons
  initGenerateButton();

  // Gallery hotzone
  initGalleryHotzone();

  // Initial mode (Image Motion) — sobrescrito por restoreState abaixo se houver estado salvo
  switchMode("image-motion");

  // Load recent outputs
  loadRecentOutputs();

  // State persistence — restaura e wira triggers
  restoreState();
  _stateReady = true;
  await motCheckJobRecovery();  // Phase 3: restaura job ativo ou último output
  document.getElementById("dock-prompt")  ?.addEventListener("input",  saveState);
  document.getElementById("cfg-model")    ?.addEventListener("change", saveState);
  document.getElementById("cfg-seed")     ?.addEventListener("input",  saveState);
  document.getElementById("dur-slider")   ?.addEventListener("input",  saveState);
  document.getElementById("cfg-res")      ?.addEventListener("change", saveState);
  document.getElementById("cfg-steps")    ?.addEventListener("input",  saveState);
  document.getElementById("amp-slider")   ?.addEventListener("input",  saveState);
});
