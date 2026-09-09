// ACS Studio — app.js
// Integração mínima: botão GERAR → ACS API → polling /status → preview

const ACS_API = "";

// ────────────────────────────────────────────────────────────
// ESTADO GLOBAL
// ────────────────────────────────────────────────────────────
let currentJobId = null;
let pollTimer    = null;

// ────────────────────────────────────────────────────────────
// PROMPT — contador de caracteres
// ────────────────────────────────────────────────────────────
const promptTA  = document.getElementById("prompt-input");
const charCount = document.getElementById("char-count");
if (promptTA && charCount) {
  promptTA.addEventListener("input", () => {
    charCount.textContent = `${promptTA.value.length} / 2000`;
  });
}

// ────────────────────────────────────────────────────────────
// UPLOAD drop zone
// ────────────────────────────────────────────────────────────
const dropZone  = document.getElementById("drop-zone");
const fileInput = document.getElementById("file-input");
if (dropZone && fileInput) {
  dropZone.addEventListener("click", () => fileInput.click());
  dropZone.addEventListener("dragover", e => { e.preventDefault(); dropZone.classList.add("dz-over"); });
  ["dragleave", "dragend"].forEach(ev => dropZone.addEventListener(ev, () => dropZone.classList.remove("dz-over")));
  dropZone.addEventListener("drop", e => {
    e.preventDefault(); dropZone.classList.remove("dz-over");
    if (e.dataTransfer.files[0]) onFileSelected(e.dataTransfer.files[0]);
  });
  fileInput.addEventListener("change", () => { if (fileInput.files[0]) onFileSelected(fileInput.files[0]); });
}
function onFileSelected(file) {
  const p = dropZone.querySelector("p"), icon = dropZone.querySelector(".dz-icon");
  if (p)    p.textContent    = file.name;
  if (icon) icon.textContent = "✓";
  dropZone.style.borderColor = "rgba(214,255,0,0.45)";
  dropZone.style.background  = "rgba(214,255,0,0.045)";
}

// ────────────────────────────────────────────────────────────
// SLIDER de duração
// ────────────────────────────────────────────────────────────
const durSlider = document.getElementById("dur-slider");
const durVal    = document.getElementById("dur-val");
if (durSlider && durVal) {
  const upd = () => durVal.textContent = durSlider.value + "s";
  durSlider.addEventListener("input", upd); upd();
}

// ────────────────────────────────────────────────────────────
// BOTÕES de formato
// ────────────────────────────────────────────────────────────
let currentRatio = "16:9";
document.querySelectorAll(".fmt-btn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".fmt-btn").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
    currentRatio = btn.dataset.ratio;
  });
});

// ────────────────────────────────────────────────────────────
// MODE toggle
// ────────────────────────────────────────────────────────────
const btnSimple   = document.getElementById("btn-simple");
const btnAdvanced = document.getElementById("btn-advanced");
[btnSimple, btnAdvanced].forEach(btn => {
  btn?.addEventListener("click", () => {
    btnSimple?.classList.remove("active");
    btnAdvanced?.classList.remove("active");
    btn.classList.add("active");
  });
});

// ────────────────────────────────────────────────────────────
// SIDEBAR nav
// ────────────────────────────────────────────────────────────
document.querySelectorAll(".nav-item").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach(b => b.classList.remove("active"));
    btn.classList.add("active");
  });
});

// ────────────────────────────────────────────────────────────
// TOPBAR links
// ────────────────────────────────────────────────────────────
document.querySelectorAll(".tb-link").forEach(a => {
  a.addEventListener("click", e => {
    e.preventDefault();
    document.querySelectorAll(".tb-link").forEach(x => x.classList.remove("active"));
    a.classList.add("active");
  });
});

// ────────────────────────────────────────────────────────────
// BOTÃO GERAR — fluxo principal
// ────────────────────────────────────────────────────────────
const btnGenerate = document.getElementById("btn-generate");
const btnStar     = btnGenerate?.querySelector(".gerar-star");
const btnLabel    = btnGenerate?.querySelector("span:last-child");

if (btnGenerate) {
  btnGenerate.addEventListener("click", async () => {
    // Valida prompt
    const prompt = promptTA?.value?.trim();
    if (!prompt) {
      promptTA.style.borderColor = "rgba(255,70,70,0.55)";
      promptTA.focus();
      setTimeout(() => { promptTA.style.borderColor = ""; }, 1500);
      return;
    }

    // Evita duplo clique durante geração
    if (btnGenerate.disabled) return;

    setGeneratingState(true);
    showStatus("Enviando para o backend...", "loading");

    // Payload fixo para flux2_klein_9b (único modelo testado e confirmado)
    const payload = {
      prompt:     prompt,
      model:      "Gerador de Imagens Realista",
      resolution: "1024x1024",
      steps:      4,
      seed:       -1,
    };

    try {
      // 1. POST /generate → recebe job_id
      const resp = await fetch(`${ACS_API}/generate`, {
        method:  "POST",
        headers: { "Content-Type": "application/json" },
        body:    JSON.stringify(payload),
      });

      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

      const data = await resp.json();
      currentJobId = data.job_id;
      console.log("[ACS] Job criado:", currentJobId);

      showStatus("Aguardando geração...", "loading");

      // 2. Inicia polling de status a cada 3s
      startJobPolling(currentJobId);

    } catch (err) {
      console.error("[ACS] Erro ao iniciar geração:", err);
      showStatus("Erro ao conectar com o backend. Verifique se acs_api.py está rodando.", "error");
      setGeneratingState(false);
    }
  });
}

// ────────────────────────────────────────────────────────────
// POLLING — /status/{job_id} a cada 3s
// ────────────────────────────────────────────────────────────
function startJobPolling(jobId) {
  if (pollTimer) clearInterval(pollTimer);

  pollTimer = setInterval(async () => {
    try {
      const r = await fetch(`${ACS_API}/status/${jobId}`);
      if (!r.ok) return;

      const s = await r.json();
      const { status, step, progress, output, error } = s;

      // Atualiza barra com o passo atual
      if (step) {
        showStatus(`${step}  (${progress || 0}%)`, "loading");
      }

      if (status === "done") {
        clearInterval(pollTimer);
        setGeneratingState(false);

        if (output?.url) {
          showStatus("Imagem gerada! ✦", "done");
          showGeneratedFile(output);
          // Recarrega galeria completa
          loadInitialOutputs();
        } else {
          showStatus("Concluído, mas sem arquivo retornado.", "error");
        }
      }

      if (status === "error") {
        clearInterval(pollTimer);
        setGeneratingState(false);
        showStatus(`Erro: ${error || "falha desconhecida"}`, "error");
        console.error("[ACS] Erro no job:", error);
      }

      if (status === "cancelled") {
        clearInterval(pollTimer);
        setGeneratingState(false);
        showStatus("Geração cancelada.", "info");
      }

    } catch (e) {
      console.warn("[ACS] Polling error:", e);
    }
  }, 3000);
}

// ────────────────────────────────────────────────────────────
// MOSTRA ARQUIVO GERADO — destaque no topo da galeria
// ────────────────────────────────────────────────────────────
function showGeneratedFile(output) {
  // output = { filename, url, size_mb }
  const url      = `${ACS_API}${output.url}`;
  const filename = output.filename || "";
  const isImage  = /\.(jpg|jpeg|png|webp)$/i.test(filename);

  // Cria ou reutiliza painel de preview
  let preview = document.getElementById("acs-preview");
  if (!preview) {
    preview = document.createElement("div");
    preview.id = "acs-preview";
    preview.style.cssText = `
      margin: 24px auto 0;
      max-width: 640px;
      border-radius: 12px;
      overflow: hidden;
      border: 1px solid rgba(214,255,0,0.25);
      background: #0d0d0d;
      position: relative;
    `;
    // Insere após o director-panel
    const dp = document.querySelector(".director-panel");
    if (dp) dp.insertAdjacentElement("afterend", preview);
    else document.querySelector(".canvas")?.prepend(preview);
  }

  if (isImage) {
    preview.innerHTML = `
      <img src="${url}" alt="${filename}"
           style="width:100%;display:block;border-radius:12px;cursor:pointer;"
           onclick="window.open('${url}','_blank')" />
      <div style="padding:10px 14px;font-size:12px;color:#888;font-family:'Inter',sans-serif;">
        ${filename} · ${output.size_mb} MB
        <a href="${url}" target="_blank"
           style="color:#d6ff00;text-decoration:none;margin-left:12px;">↗ Abrir</a>
      </div>`;
  } else {
    preview.innerHTML = `
      <video src="${url}" controls autoplay muted loop
             style="width:100%;display:block;border-radius:12px;"></video>
      <div style="padding:10px 14px;font-size:12px;color:#888;font-family:'Inter',sans-serif;">
        ${filename} · ${output.size_mb} MB
        <a href="${url}" target="_blank"
           style="color:#d6ff00;text-decoration:none;margin-left:12px;">↗ Abrir</a>
      </div>`;
  }

  // Scroll suave até o preview
  preview.scrollIntoView({ behavior: "smooth", block: "center" });
}

// ────────────────────────────────────────────────────────────
// GALERIA — carrega /outputs e preenche .cards-grid
// ────────────────────────────────────────────────────────────
const recentSection = document.querySelector(".recent");

async function loadInitialOutputs() {
  try {
    const r = await fetch(`${ACS_API}/outputs`);
    const d = await r.json();
    if (d.outputs && d.outputs.length > 0) {
      showGallery(d.outputs);
    }
  } catch (e) {}
}

function showGallery(outputs) {
  if (!recentSection) return;
  const grid = recentSection.querySelector(".cards-grid");
  if (!grid || outputs.length === 0) return;

  grid.innerHTML = outputs.slice(0, 6).map((o, i) => {
    const url      = `${ACS_API}${o.url}`;
    const title    = o.title  || o.name.slice(0, 48);
    const date     = o.date   || "";
    const sizeMb   = o.size_mb ? `${o.size_mb} MB` : "";
    const isImage  = o.type === "image" || /\.(jpg|jpeg|png|webp)$/i.test(o.name);

    const thumb = isImage
      ? `<img src="${url}" alt="${title}"
              style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0.75;pointer-events:none;" />`
      : `<video src="${url}" muted preload="metadata"
                style="position:absolute;inset:0;width:100%;height:100%;object-fit:cover;opacity:0.75;pointer-events:none;"></video>`;

    return `
      <div class="card card-${(i % 5) + 1} acs-card"
           data-url="${url}" data-image="${isImage}"
           style="cursor:pointer;overflow:hidden;position:relative;">
        ${thumb}
        <span class="card-duration" style="position:relative;z-index:2">${sizeMb}</span>
        <div class="card-foot" style="position:relative;z-index:2">
          <div class="card-name">${title}</div>
          <div class="card-meta">${date} · ${isImage ? "IMG" : "MP4"}</div>
        </div>
      </div>`;
  }).join("");

  // Hover play para vídeos; click abre em nova aba
  grid.querySelectorAll(".acs-card").forEach(card => {
    const vid = card.querySelector("video");
    if (vid) {
      card.addEventListener("mouseenter", () => vid.play().catch(() => {}));
      card.addEventListener("mouseleave", () => { vid.pause(); vid.currentTime = 0; });
    }
    card.addEventListener("click", () => window.open(card.dataset.url, "_blank"));
  });
}

// ────────────────────────────────────────────────────────────
// UI HELPERS
// ────────────────────────────────────────────────────────────
function setGeneratingState(generating) {
  if (!btnGenerate) return;
  btnGenerate.disabled       = generating;
  btnGenerate.style.opacity  = generating ? "0.65" : "";
  btnGenerate.style.cursor   = generating ? "wait"  : "";
  if (btnLabel) btnLabel.textContent = generating ? "GERANDO..." : "GERAR";
  if (btnStar)  btnStar.style.animation = generating ? "spin 1s linear infinite" : "";
}

function showStatus(msg, type = "info") {
  let bar = document.getElementById("acs-status-bar");
  if (!bar) {
    bar = document.createElement("div");
    bar.id = "acs-status-bar";
    bar.style.cssText = `
      position:fixed; bottom:24px; left:50%; transform:translateX(-50%);
      background:#111; border:1px solid rgba(214,255,0,0.3); color:#eee;
      padding:10px 22px; border-radius:8px; font-size:13px; z-index:9999;
      font-family:'Inter',sans-serif; transition:opacity .4s;
      box-shadow:0 0 20px rgba(214,255,0,0.1);
    `;
    document.body.appendChild(bar);
  }
  const colors = { loading: "#d6ff00", done: "#7fff00", error: "#ff4444", info: "#aaa" };
  bar.style.color   = colors[type] || "#eee";
  bar.style.opacity = "1";
  bar.textContent   = msg;
  if (type === "done") setTimeout(() => { bar.style.opacity = "0"; }, 5000);
}

// ────────────────────────────────────────────────────────────
// INIT
// ────────────────────────────────────────────────────────────
(async () => {
  try {
    const r = await fetch(`${ACS_API}/health`);
    const d = await r.json();
    if (d.status === "ok") {
      console.log("[ACS] API online:", d);
      showStatus("ACS Studio conectado ✦", "done");
    }
  } catch (e) {
    console.warn("[ACS] API offline.");
    showStatus("API offline. Inicie o acs_api.py.", "error");
  }
  await loadInitialOutputs();
})();

// Keyframe spin
if (!document.getElementById("acs-keyframes")) {
  const s = document.createElement("style");
  s.id = "acs-keyframes";
  s.textContent = `@keyframes spin { to { transform: rotate(360deg); } }`;
  document.head.appendChild(s);
}

console.log("[AGI Studio] v3.1 — API:", ACS_API);
