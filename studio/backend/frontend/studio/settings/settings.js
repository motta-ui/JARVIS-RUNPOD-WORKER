/* ============================================================
   ACS Settings v3.0
   Lê /config, persiste via POST /config/update (Fase 2)
   Lê /config/acs, persiste via POST /config/acs/update
   Valida paths via POST /config/validate-path
   Backup via POST /config/backup
============================================================ */

const API = "";  // mesmo origin

// Estado local — wgp_config.json
let _cfg    = {};   // valores atuais carregados do backend
let _rules  = {};   // validation_rules do backend
let _dirty  = {};   // valores modificados ainda não salvos
let _needsRestart = new Set();
let _restartType  = null;  // "wan2gp" | "acs" | null


// ──────────────────────────────────────────────────────────
// INICIALIZAÇÃO
// ──────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  initTabs();
  initSidebarLinks();
  initRestoreButtons();
  initExperimentalToggle();
  loadConfig();
  loadVersion();
  loadBackups();
  loadTritonStatus();
  loadAppearance();
});

// ──────────────────────────────────────────────────────────
// EXPERIMENTAL SECTION TOGGLE
// ──────────────────────────────────────────────────────────
function initExperimentalToggle() {
  const toggle = document.getElementById("experimental-toggle");
  const body   = document.getElementById("experimental-body");
  if (!toggle || !body) return;
  toggle.addEventListener("click", () => {
    toggle.classList.toggle("open");
    body.classList.toggle("open");
  });
}

// ──────────────────────────────────────────────────────────
// TRITON STATUS
// ──────────────────────────────────────────────────────────
let _tritonStatus = null;   // cached triton status from backend

async function loadTritonStatus() {
  try {
    const res  = await fetch(`${API}/config/triton-status`);
    const data = await res.json();
    _tritonStatus = data;
    applyTritonStatus(data);
  } catch {
    applyTritonStatus({ status: "missing", compile_safe: false,
      message: "Não foi possível verificar o status do Triton." });
  }
}

function applyTritonStatus(s) {
  const status  = s?.status || "missing";
  const safe    = !!s?.compile_safe;
  const msg     = s?.message || "";
  const version = s?.version ? ` ${s.version}` : "";

  // Badge no header da seção
  const headerBadge = document.getElementById("triton-badge-header");
  if (headerBadge) {
    headerBadge.style.display = "inline";
    if (status === "ok") {
      headerBadge.textContent = `Triton${version} OK`;
      headerBadge.className   = "triton-ok";
      headerBadge.style.cssText += ";background:rgba(80,200,100,.15);color:#7de0a0;border:1px solid rgba(80,200,100,.3);border-radius:10px;padding:2px 7px;font-size:9px;font-weight:700";
    } else {
      headerBadge.textContent = status === "missing" ? "Triton ausente" : "Triton incompatível";
      headerBadge.className   = status === "missing" ? "triton-missing" : "triton-incompat";
      headerBadge.style.cssText += ";background:rgba(220,80,80,.15);color:#e08080;border:1px solid rgba(220,80,80,.3);border-radius:10px;padding:2px 7px;font-size:9px;font-weight:700";
    }
  }

  // Card de status Triton
  const icon  = document.getElementById("triton-status-icon");
  const badge = document.getElementById("triton-status-badge");
  const msgEl = document.getElementById("triton-status-msg");
  const card  = document.getElementById("triton-status-card");

  if (icon)  icon.textContent = status === "ok" ? "✅" : status === "missing" ? "❌" : "⚠";
  if (msgEl) msgEl.textContent = msg;

  if (badge) {
    badge.textContent = status === "ok"
      ? `OK — Triton${version}`
      : status === "missing" ? "Não instalado" : `Incompatível${version}`;
    badge.className = "";
    badge.style.cssText = "font-size:9px;font-weight:700;padding:2px 8px;border-radius:10px;";
    if (status === "ok") {
      badge.style.background = "rgba(80,200,100,.2)";
      badge.style.color = "#7de0a0";
    } else if (status === "missing") {
      badge.style.background = "rgba(220,80,80,.2)";
      badge.style.color = "#e08080";
    } else {
      badge.style.background = "rgba(220,160,40,.2)";
      badge.style.color = "#e0c070";
    }
  }

  if (card) {
    card.style.borderColor = status === "ok"
      ? "rgba(80,200,100,.25)"
      : status === "missing" ? "rgba(220,80,80,.25)" : "rgba(220,160,40,.25)";
  }

  // Compile select: desabilitar se Triton não está OK
  const compileSelect = document.getElementById("compile-select");
  const compileWarn   = document.getElementById("compile-triton-warn");

  if (compileSelect) {
    if (!safe) {
      compileSelect.disabled = true;
      compileSelect.title = "Triton não funcional — Compile Transformer bloqueado";
      // Forçar para Off visualmente (não modifica wgp_config — apenas UI)
      compileSelect.value = "";
    } else {
      compileSelect.disabled = false;
      compileSelect.title = "";
    }
  }

  if (compileWarn) {
    compileWarn.style.display = safe ? "none" : "inline";
  }
}

// ──────────────────────────────────────────────────────────
// TABS
// ──────────────────────────────────────────────────────────
function initTabs() {
  document.querySelectorAll(".stab").forEach(tab => {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".stab").forEach(t => t.classList.remove("active"));
      document.querySelectorAll(".settings-panel").forEach(p => p.classList.remove("active"));
      tab.classList.add("active");
      const target = document.getElementById("panel-" + tab.dataset.tab);
      if (target) target.classList.add("active");
    });
  });
  // Colapsáveis (seções Avançado)
  document.querySelectorAll(".sgroup-adv-toggle").forEach(toggle => {
    toggle.addEventListener("click", () => {
      toggle.classList.toggle("open");
      const body = toggle.nextElementSibling;
      if (body?.classList.contains("sgroup-adv-body")) body.classList.toggle("open");
    });
  });
}

// ──────────────────────────────────────────────────────────
// SIDEBAR
// ──────────────────────────────────────────────────────────
function initSidebarLinks() {
  document.querySelectorAll(".sidebar-item[href]").forEach(a => {
    if (!a.getAttribute("href").includes("settings")) return;
    a.classList.add("active");
  });
}

// ──────────────────────────────────────────────────────────
// CARREGAR CONFIG DO BACKEND
// ──────────────────────────────────────────────────────────
async function loadConfig() {
  showLoading(true);
  try {
    const res  = await fetch(`${API}/config`);
    const data = await res.json();
    if (!res.ok) throw new Error(data.error || "Erro ao carregar configurações");

    _cfg   = data.settings || {};
    _rules = data.validation_rules || {};
    _dirty = {};

    renderAllControls();
    showLoading(false);
    updateSaveButton();
  } catch (err) {
    showLoading(false);
    showErrorState(err.message);
  }
}

function showLoading(on) {
  const el = document.getElementById("s-loading");
  if (el) el.style.display = on ? "flex" : "none";
  document.querySelectorAll(".settings-panel").forEach(p => {
    p.style.visibility = on ? "hidden" : "visible";
  });
}

function showErrorState(msg) {
  const el = document.getElementById("s-error-state");
  if (!el) return;
  el.classList.add("visible");
  const desc = el.querySelector(".s-error-desc");
  if (desc) desc.textContent = msg || "Não foi possível conectar ao backend.";
}

// ──────────────────────────────────────────────────────────
// RENDERIZAR CONTROLES
// ──────────────────────────────────────────────────────────
function renderAllControls() {
  // Para cada elemento com data-key, atualiza o valor
  document.querySelectorAll("[data-key]").forEach(el => {
    const key = el.dataset.key;
    const val = _dirty[key] !== undefined ? _dirty[key] : _cfg[key];
    if (val === undefined) return;

    if (el.classList.contains("s-select"))        renderSelect(el, val);
    else if (el.classList.contains("s-path-input")) renderPath(el, val);
    else if (el.classList.contains("s-toggle-input")) renderToggle(el, val);
    else if (el.classList.contains("s-slider"))    renderSlider(el, val);
  });
}

// ──────────────────────────────────────────────────────────
// ARRAY PRESET — encode array → string key, decode string key → array
// Usado por data-type="array-preset" (ex: preload_model_policy)
// ──────────────────────────────────────────────────────────
function arrayToPreset(arr) {
  if (!Array.isArray(arr) || arr.length === 0) return "";
  const sorted = [...arr].sort().join("");
  // Mapeia combinações conhecidas para chaves de select
  const MAP = { "P": "P", "S": "S", "PU": "PU", "U": "PU" };
  return MAP[sorted] ?? "";
}

function presetToArray(preset) {
  const MAP = { "": [], "S": ["S"], "P": ["P"], "PU": ["P", "U"] };
  return MAP[preset] ?? [];
}

function renderSelect(el, val) {
  // Caso especial: array-preset (ex: preload_model_policy)
  if (el.dataset.type === "array-preset") {
    el.value = arrayToPreset(val);
    if (el.selectedIndex < 0 && el.options.length > 0) el.selectedIndex = 0;
    return;
  }
  el.value = String(val);
  // Se value não bater com nenhuma option, usa primeira
  if (el.selectedIndex < 0 && el.options.length > 0) el.selectedIndex = 0;
}
function renderPath(el, val)   { el.value = val ?? ""; }
function renderToggle(el, val) { el.checked = !!(Number(val) || val === true); }
function renderSlider(el, val) {
  el.value = val;
  const disp = el.closest(".s-slider-wrap")?.querySelector(".s-slider-val");
  if (disp) disp.textContent = val;
}

// ──────────────────────────────────────────────────────────
// CAPTURAR MUDANÇAS
// ──────────────────────────────────────────────────────────
document.addEventListener("change", e => {
  const el = e.target;
  const key = el.dataset.key;
  if (!key) return;

  let val;
  if (el.classList.contains("s-toggle-input")) val = el.checked ? 1 : 0;
  else if (el.classList.contains("s-slider"))   val = parseFloat(el.value);
  else                                           val = el.value;

  // Array-preset: converter string key → array antes de guardar
  if (el.dataset.type === "array-preset") {
    val = presetToArray(val);
    _dirty[key] = val;
    updateSaveButton();
    updateRestartBanner();
    return;
  }

  // Coerce enum para número se necessário
  const rule = _rules[key];
  if (rule?.type === "enum" && typeof rule.values[0] === "number") val = Number(val);
  if (rule?.type === "bool") val = Number(val);

  _dirty[key] = val;
  updateSaveButton();
  updateRestartBanner();

  // Validação inline de path
  if (el.classList.contains("s-path-input")) validatePathInline(key, el);
});

document.addEventListener("input", e => {
  const el = e.target;
  const key = el.dataset.key;
  if (!key || !el.classList.contains("s-slider")) return;
  const val = parseFloat(el.value);
  _dirty[key] = val;
  const disp = el.closest(".s-slider-wrap")?.querySelector(".s-slider-val");
  if (disp) disp.textContent = val;
  updateSaveButton();
  updateRestartBanner();
});

// ──────────────────────────────────────────────────────────
// SALVAR
// ──────────────────────────────────────────────────────────
document.getElementById("btn-save")?.addEventListener("click", saveSettings);

async function saveSettings() {
  if (!Object.keys(_dirty).length) return;

  const btn = document.getElementById("btn-save");
  if (btn) { btn.disabled = true; btn.textContent = "Salvando…"; }

  try {
    const res  = await fetch(`${API}/config/update`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ settings: _dirty }),
    });
    const data = await res.json();

    if (!res.ok) {
      const detail = data.detail;
      if (detail?.triton_blocked) {
        // Erro específico de Triton — exibir mensagem clara e resetar compile na UI
        showToast(`⚠ Compile bloqueado: ${detail.message}`, "error");
        // Forçar compile de volta para Off na UI (dirty e controle)
        _dirty["compile"] = "";
        const compileEl = document.getElementById("compile-select");
        if (compileEl) compileEl.value = "";
        updateSaveButton();
        return;
      }
      if (detail?.validation_errors) {
        const msgs = Object.entries(detail.validation_errors)
          .map(([k,v]) => `${k}: ${v}`).join("\n");
        showToast("Erro de validação:\n" + msgs, "error");
      } else {
        showToast(detail?.message || detail || "Erro ao salvar", "error");
      }
      return;
    }

    // Sucesso
    Object.assign(_cfg, _dirty);
    _dirty = {};
    updateSaveButton();

    if (data.requires_restart?.length > 0) {
      _needsRestart = new Set([..._needsRestart, ...data.requires_restart]);
      _restartType  = data.restart_type || "wan2gp";
      updateRestartBanner();
      const svc = _restartType === "acs" ? "ACS Studio" : "Motor de IA";
      showToast(`Salvo. Reinicie o ${svc} para: ${data.requires_restart.join(", ")}`, "warn");
    } else {
      showToast("Configurações salvas com sucesso", "ok");
    }
    loadBackups();
  } catch (err) {
    showToast("Erro de comunicação: " + err.message, "error");
  } finally {
    if (btn) {
      btn.disabled = false;
      btn.textContent = "Salvar";
      updateSaveButton();
    }
  }
}

// ──────────────────────────────────────────────────────────
// RESTAURAR PADRÕES
// ──────────────────────────────────────────────────────────
function initRestoreButtons() {
  document.querySelectorAll("[data-restore-group]").forEach(btn => {
    btn.addEventListener("click", () => {
      const group = btn.dataset.restoreGroup;
      restoreGroup(group);
    });
  });
  document.getElementById("btn-restore-all")?.addEventListener("click", restoreAll);
}

function restoreGroup(group) {
  document.querySelectorAll(`[data-group="${group}"][data-key]`).forEach(el => {
    const key = el.dataset.key;
    const rule = _rules[key];
    // Usa default vindo do backend ou fallback local
    const def = el.dataset.default !== undefined ? el.dataset.default : undefined;
    if (def === undefined) return;

    let parsed;
    if (el.dataset.type === "array-preset") {
      // array-preset: data-default é string preset ("", "S", "P", "PU") → array
      parsed = presetToArray(def);
    } else {
      parsed = rule?.type === "number" || (rule?.type === "enum" && typeof rule.values?.[0] === "number")
        ? Number(def) : def;
    }

    _dirty[key] = parsed;
    if (el.classList.contains("s-select")) renderSelect(el, parsed);
    else if (el.classList.contains("s-path-input")) renderPath(el, parsed);
    else if (el.classList.contains("s-toggle-input")) renderToggle(el, parsed);
    else if (el.classList.contains("s-slider")) renderSlider(el, parsed);
  });
  updateSaveButton();
  showToast("Valores padrão restaurados — clique Salvar para aplicar", "warn");
}

function restoreAll() {
  if (!confirm("Restaurar TODOS os settings para os valores padrão? Isso sobrescreverá suas configurações atuais.")) return;
  document.querySelectorAll("[data-key][data-default]").forEach(el => {
    const key = el.dataset.key;
    const def = el.dataset.default;
    const rule = _rules[key];

    let parsed;
    if (el.dataset.type === "array-preset") {
      parsed = presetToArray(def);
    } else {
      parsed = rule?.type === "number" ? Number(def) : def;
    }

    _dirty[key] = parsed;
    if (el.classList.contains("s-select")) renderSelect(el, parsed);
    else if (el.classList.contains("s-path-input")) renderPath(el, parsed);
    else if (el.classList.contains("s-toggle-input")) renderToggle(el, Number(parsed));
    else if (el.classList.contains("s-slider")) renderSlider(el, parsed);
  });
  updateSaveButton();
  showToast("Todos os padrões restaurados — clique Salvar para aplicar", "warn");
}

// ──────────────────────────────────────────────────────────
// VALIDAÇÃO DE PATH
// ──────────────────────────────────────────────────────────
async function validatePathInline(key, el) {
  el.classList.remove("valid", "invalid");
  const val = el.value.trim();
  if (!val) return;
  try {
    const res  = await fetch(`${API}/config/validate-path`, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ path: val }),
    });
    const data = await res.json();
    el.classList.add(data.valid ? "valid" : "invalid");
    const hint = el.closest(".s-path-wrap")?.querySelector(".s-path-hint");
    if (hint) hint.textContent = data.valid ? `✓ ${data.resolved}` : data.error || "Caminho inválido";
  } catch {}
}

// ──────────────────────────────────────────────────────────
// VERSÃO DO SISTEMA
// ──────────────────────────────────────────────────────────
async function loadVersion() {
  try {
    const res  = await fetch(`${API}/version`);
    const data = await res.json();
    const el = document.getElementById("version-info");
    if (el) el.innerHTML = `
      <span>ACS API <strong>${data.acs_api}</strong></span>
      <span style="color:#444">·</span>
      <span>Motor de IA <strong>${data.wan2gp}</strong></span>
      <span style="color:#444">·</span>
      <span>Motor v2 <strong>${data.mmgp}</strong></span>
    `;
  } catch {}
}

// ──────────────────────────────────────────────────────────
// BACKUPS
// ──────────────────────────────────────────────────────────
async function loadBackups() {
  try {
    const res  = await fetch(`${API}/config/backups`);
    const data = await res.json();
    const list = document.getElementById("backup-list");
    if (!list) return;
    if (!data.backups?.length) {
      list.innerHTML = `<div class="backup-item" style="color:var(--text-dim)">Nenhum backup encontrado</div>`;
      return;
    }
    list.innerHTML = data.backups.map(b => `
      <div class="backup-item">
        <span class="backup-item-name">${b.name}</span>
        <span class="backup-item-meta">${b.size_kb} KB · ${new Date(b.created).toLocaleString("pt-BR")}</span>
      </div>
    `).join("");
  } catch {}
}

document.getElementById("btn-backup")?.addEventListener("click", async () => {
  try {
    const res  = await fetch(`${API}/config/backup`, { method: "POST" });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Erro");
    showToast(`Backup criado: ${data.backup}`, "ok");
    loadBackups();
  } catch (err) {
    showToast("Erro ao criar backup: " + err.message, "error");
  }
});

// ──────────────────────────────────────────────────────────
// UI HELPERS
// ──────────────────────────────────────────────────────────
function updateSaveButton() {
  const btn = document.getElementById("btn-save");
  const count = Object.keys(_dirty).length;
  if (!btn) return;
  btn.disabled = count === 0;
  btn.textContent = count > 0 ? `Salvar (${count})` : "Salvar";
}

// Keys de restart conhecidas pelo frontend (subset de _REQUIRES_RESTART_WAN2GP)
const _WAN2GP_RESTART_KEYS = new Set([
  "attention_mode","transformer_quantization","text_encoder_quantization",
  "enable_int8_kernels","profile","video_profile","image_profile","audio_profile",
  "enable_4k_resolutions","boost","vae_config",
  // Fase 2 — avançado
  "compile","transformer_dtype_policy",
  "vae_precision",
  "lm_decoder_engine",
  "preload_model_policy","preload_in_VRAM",
]);

function updateRestartBanner() {
  const banner  = document.getElementById("restart-banner");
  const descEl  = document.getElementById("restart-banner-desc");
  const keysEl  = document.getElementById("restart-banner-keys");
  if (!banner) return;

  // Chaves sujas que exigem restart
  const dirtyRestartKeys = Object.keys(_dirty).filter(k => _WAN2GP_RESTART_KEYS.has(k));

  // Combina pendentes (já salvos e aguardando restart) com as ainda não salvas
  const allKeys = new Set([..._needsRestart, ...dirtyRestartKeys]);

  if (allKeys.size === 0) {
    banner.classList.remove("visible", "restart-banner--acs");
    return;
  }

  // Determinar tipo de restart: usa _restartType se definido, senão assume wan2gp
  const type = _restartType || "wan2gp";
  banner.classList.toggle("restart-banner--acs", type === "acs");
  banner.classList.add("visible");

  if (descEl) {
    const svc = type === "acs"
      ? "<strong>reinicialização do ACS Studio</strong>"
      : "<strong>reinicialização do Motor de IA</strong>";
    descEl.innerHTML = `As seguintes configurações requerem ${svc} para surtir efeito:`;
  }
  if (keysEl) keysEl.textContent = [...allKeys].join(", ");
}

let _toastTimer;
function showToast(msg, type = "ok") {
  const toast = document.getElementById("s-toast");
  if (!toast) return;
  toast.className = `s-toast ${type} visible`;
  toast.querySelector(".s-toast-text").textContent = msg;
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => toast.classList.remove("visible"), 4500);
}

// ──────────────────────────────────────────────────────────
// APPEARANCE — ui_scale, theme
// ──────────────────────────────────────────────────────────
async function loadAppearance() {
  try {
    const res  = await fetch(`${API}/api/appearance`);
    const data = await res.json();
    applyAppearanceUI(data);
  } catch (e) {
    console.warn("[settings] loadAppearance:", e);
  }
}

function applyAppearanceUI(data) {
  const scale = data?.ui_scale ?? 100;
  // Highlight active scale button
  document.querySelectorAll(".scale-btn").forEach(btn => {
    btn.classList.toggle("active", parseInt(btn.dataset.scale) === scale);
  });
  // Show current value
  const cur = document.getElementById("ui-scale-current");
  if (cur) cur.textContent = scale + "%";
}

async function setUiScale(scale) {
  try {
    const res  = await fetch(`${API}/api/appearance`, {
      method:  "POST",
      headers: {"Content-Type": "application/json"},
      body:    JSON.stringify({ ui_scale: scale }),
    });
    const data = await res.json();
    if (data.ok) {
      applyAppearanceUI({ ui_scale: scale });
      showToast(`Escala ${scale}% salva. Reabra o ACS para aplicar.`, "ok");
    } else {
      showToast(data.error || "Erro ao salvar escala.", "error");
    }
  } catch (e) {
    showToast("Erro de rede ao salvar aparência.", "error");
  }
}

// Wire scale buttons (called after DOM ready — buttons may be dynamic)
function initScaleButtons() {
  document.querySelectorAll(".scale-btn").forEach(btn => {
    btn.addEventListener("click", () => setUiScale(parseInt(btn.dataset.scale)));
  });
}
// Try to wire on DOMContentLoaded (static buttons) and on load (dynamic)
document.addEventListener("DOMContentLoaded", initScaleButtons);
