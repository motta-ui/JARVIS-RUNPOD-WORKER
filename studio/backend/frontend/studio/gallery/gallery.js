// gallery.js — ACS Studio Gallery page — B38-008: suporte a image/video/audio
const API = ""; // URL relativa — funciona com localhost, 127.0.0.1 ou qualquer host

function fileUrl(url) { return `${API}${url}`; }

async function loadOutputs() {
  const r = await fetch(`${API}/outputs`);
  if (!r.ok) return [];
  const d = await r.json();
  // [B38-008] Remove filtro image-only — retorna todos os tipos
  return d.outputs || [];
}

// ── State ─────────────────────────────────────────────────────
let allOutputs  = [];
let filteredOutputs = [];
let currentIdx  = 0;
let activeFilter = "all"; // "all" | "image" | "video" | "audio"

const galleryPage  = document.getElementById("gallery-page");
const galleryCount = document.getElementById("gallery-count");

// ── Download helper — B38-007v2 ──────────────────────────────
// window.location + ?download=1 → Content-Disposition: attachment no servidor
function _downloadFile(url, filename) {
  window.location.href = url + (url.includes("?") ? "&" : "?") + "download=1";
}

// ── Lightbox ──────────────────────────────────────────────────
const lightbox   = document.getElementById("gallery-lightbox");
const lbImg      = document.getElementById("gallery-lb-img");
const lbMedia    = document.getElementById("gallery-lb-media");
const lbInfo     = document.getElementById("gallery-lb-info");
const lbClose    = document.getElementById("gallery-lb-close");
const lbBackdrop = document.getElementById("gallery-lb-backdrop");
const lbPrev     = document.getElementById("gallery-lb-prev");
const lbNext     = document.getElementById("gallery-lb-next");
const lbDownload = document.getElementById("gallery-lb-download");
const lbOpen     = document.getElementById("gallery-lb-open");

function openLightbox(idx) {
  currentIdx = idx;
  const o = filteredOutputs[idx];
  if (!o) return;
  const url = fileUrl(o.url);
  lbInfo.textContent = `${o.title || o.name}  ·  ${o.date || ""}  ·  ${o.size_mb}MB`;
  lbDownload.onclick = () => _downloadFile(url, o.name);
  // [B39-003] "Abrir" = fullscreen do conteúdo do lightbox (viewer interno),
  // em vez de window.open(_blank) que abriria navegador externo no pywebview.
  lbOpen.onclick = () => {
    try {
      const target = (o.type === "image" && lbImg && lbImg.style.display !== "none")
        ? lbImg
        : (lbMedia && lbMedia.firstElementChild) || lbMedia || lbImg;
      if (target && target.requestFullscreen) target.requestFullscreen();
    } catch { /* fullscreen indisponível — lightbox já exibe a mídia, sem ação externa */ }
  };
  lbPrev.style.display = idx > 0 ? "" : "none";
  lbNext.style.display = idx < filteredOutputs.length - 1 ? "" : "none";

  // [B38-008] Lightbox por tipo
  if (lbImg)   { lbImg.style.display   = "none"; lbImg.src   = ""; }
  if (lbMedia) { lbMedia.style.display = "none"; lbMedia.innerHTML = ""; }

  if (o.type === "image") {
    if (lbImg) { lbImg.src = url; lbImg.style.display = "block"; }
  } else if (o.type === "video") {
    if (lbMedia) {
      lbMedia.innerHTML = `<video src="${url}" controls autoplay style="max-width:100%;max-height:70vh;border-radius:8px;"></video>`;
      lbMedia.style.display = "flex";
    }
  } else if (o.type === "audio") {
    if (lbMedia) {
      lbMedia.innerHTML = `
        <div style="display:flex;flex-direction:column;align-items:center;gap:16px;padding:32px 0;">
          <span style="font-size:48px;">♪</span>
          <span style="color:rgba(255,255,255,.7);font-size:13px;">${o.title || o.name}</span>
          <audio src="${url}" controls style="width:340px;"></audio>
        </div>`;
      lbMedia.style.display = "flex";
    }
  }

  lightbox.style.display = "flex";
}

function closeLightbox() {
  lightbox.style.display = "none";
  // Parar vídeo/áudio ao fechar
  if (lbMedia) {
    const vid = lbMedia.querySelector("video,audio");
    if (vid) { vid.pause(); vid.src = ""; }
    lbMedia.innerHTML = "";
  }
}

lbClose?.addEventListener("click", closeLightbox);
lbBackdrop?.addEventListener("click", closeLightbox);
lbPrev?.addEventListener("click", () => openLightbox(currentIdx - 1));
lbNext?.addEventListener("click", () => openLightbox(currentIdx + 1));
document.addEventListener("keydown", e => {
  if (lightbox.style.display === "none") return;
  if (e.key === "Escape")      closeLightbox();
  if (e.key === "ArrowLeft")   openLightbox(currentIdx - 1);
  if (e.key === "ArrowRight")  openLightbox(currentIdx + 1);
});

// ── Filtros ───────────────────────────────────────────────────
function applyFilter(type) {
  activeFilter = type;
  filteredOutputs = type === "all" ? allOutputs : allOutputs.filter(o => o.type === type);
  document.querySelectorAll(".gallery-filter-btn").forEach(b => {
    b.classList.toggle("active", b.dataset.filter === type);
  });
  render();
}

// ── Render ────────────────────────────────────────────────────
function formatDate(dateStr) {
  if (!dateStr) return "Sem data";
  try {
    const d = new Date(dateStr);
    return d.toLocaleDateString("pt-BR", { day: "numeric", month: "long", year: "numeric" });
  } catch { return dateStr; }
}

function buildCard(o, idx) {
  const url  = fileUrl(o.url);
  const card = document.createElement("div");
  card.className = "gallery-full-item";

  if (o.type === "image") {
    const img = document.createElement("img");
    img.src = url; img.alt = o.title || ""; img.loading = "lazy";
    card.appendChild(img);
  } else if (o.type === "video") {
    const thumb = document.createElement("div");
    thumb.className = "gallery-video-thumb";
    thumb.innerHTML = `<span class="gallery-thumb-icon">▶</span>`;
    thumb.style.cssText = "display:flex;align-items:center;justify-content:center;width:100%;height:100%;background:#0a0a14;min-height:120px;";
    // Tentar thumbnail via video (muted, no controls)
    const vid = document.createElement("video");
    vid.src = url; vid.muted = true; vid.preload = "metadata";
    vid.style.cssText = "width:100%;height:100%;object-fit:cover;position:absolute;top:0;left:0;";
    vid.addEventListener("loadeddata", () => { thumb.innerHTML = ""; thumb.appendChild(vid); });
    card.style.position = "relative";
    card.appendChild(thumb);
    const overlay = document.createElement("div");
    overlay.style.cssText = "position:absolute;top:8px;right:8px;background:rgba(0,0,0,.6);border-radius:4px;padding:2px 6px;font-size:10px;color:#fff;";
    overlay.textContent = "▶ VIDEO";
    card.appendChild(overlay);
  } else if (o.type === "audio") {
    const aud = document.createElement("div");
    aud.style.cssText = "display:flex;flex-direction:column;align-items:center;justify-content:center;width:100%;height:100%;background:#0a0a14;min-height:100px;gap:8px;padding:12px;";
    aud.innerHTML = `<span style="font-size:28px;">♪</span><span style="font-size:10px;color:rgba(255,255,255,.4);text-align:center;word-break:break-all;">${o.name}</span>`;
    card.appendChild(aud);
  }

  const overlay = document.createElement("div");
  overlay.className = "gallery-full-overlay";
  overlay.innerHTML = `
    <span class="gallery-full-item-title">${o.title || o.name}</span>
    <span class="gallery-full-item-meta">${o.size_mb}MB</span>`;
  card.appendChild(overlay);
  card.addEventListener("click", () => openLightbox(idx));
  return card;
}

function render() {
  if (!galleryPage) return;
  const total = allOutputs.length;
  const shown = filteredOutputs.length;

  if (!total) {
    galleryPage.innerHTML = `<div class="gallery-page-empty"><p>Nenhuma mídia gerada ainda.</p><a class="gallery-go-image" href="/studio/image">→ Ir para Image Studio</a></div>`;
    if (galleryCount) galleryCount.textContent = "0 arquivos";
    return;
  }

  if (galleryCount) {
    const imgs  = allOutputs.filter(o => o.type === "image").length;
    const vids  = allOutputs.filter(o => o.type === "video").length;
    const auds  = allOutputs.filter(o => o.type === "audio").length;
    const parts = [
      imgs ? `${imgs} img` : "",
      vids ? `${vids} vid` : "",
      auds ? `${auds} áud` : "",
    ].filter(Boolean).join(" · ");
    galleryCount.textContent = `${total} arquivo${total !== 1 ? "s" : ""}  (${parts})`;
  }

  // Agrupa por data
  const byDate = {};
  filteredOutputs.forEach((o, idx) => {
    const key = o.date ? o.date.split(" ")[0] : "Sem data";
    if (!byDate[key]) byDate[key] = [];
    byDate[key].push({ ...o, _idx: idx });
  });

  galleryPage.innerHTML = "";

  for (const [date, items] of Object.entries(byDate)) {
    const section = document.createElement("div");
    section.className = "gallery-section";

    const header = document.createElement("div");
    header.className = "gallery-date-header";
    header.textContent = formatDate(date);
    section.appendChild(header);

    const grid = document.createElement("div");
    grid.className = "gallery-date-group";
    section.appendChild(grid);

    items.forEach(o => {
      grid.appendChild(buildCard(o, o._idx));
    });

    galleryPage.appendChild(section);
  }
}

// ── Filter bar (inserir após o header) ───────────────────────
function insertFilterBar() {
  const topbar = document.querySelector(".topbar");
  if (!topbar) return;
  const bar = document.createElement("div");
  bar.className = "gallery-filter-bar";
  bar.style.cssText = "display:flex;gap:6px;padding:8px 24px;border-bottom:1px solid #1a1a2e;background:#0d0d1a;flex-shrink:0;";
  [["all","Todos"],["image","◻ Image"],["video","▶ Video"],["audio","♪ Audio"]].forEach(([type, label]) => {
    const btn = document.createElement("button");
    btn.className = "gallery-filter-btn" + (type === "all" ? " active" : "");
    btn.dataset.filter = type;
    btn.textContent = label;
    btn.style.cssText = "padding:4px 12px;border-radius:14px;border:1px solid #2a2a40;background:transparent;color:rgba(255,255,255,.5);font-size:12px;cursor:pointer;";
    btn.addEventListener("mouseenter", () => { if (!btn.classList.contains("active")) btn.style.borderColor="#4a4a60"; });
    btn.addEventListener("mouseleave", () => { if (!btn.classList.contains("active")) btn.style.borderColor="#2a2a40"; });
    btn.addEventListener("click", () => applyFilter(type));
    bar.appendChild(btn);
  });
  topbar.insertAdjacentElement("afterend", bar);

  // Estilo active
  const style = document.createElement("style");
  style.textContent = `.gallery-filter-btn.active{background:#1e1e35!important;border-color:#5050a0!important;color:#fff!important;}`;
  document.head.appendChild(style);
}

// ── Init ─────────────────────────────────────────────────────
(async () => {
  insertFilterBar();
  allOutputs = await loadOutputs();
  filteredOutputs = allOutputs;
  render();
})();
