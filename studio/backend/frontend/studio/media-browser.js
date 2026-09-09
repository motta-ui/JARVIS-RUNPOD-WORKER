/* ══════════════════════════════════════════════════════
   SIDEBAR MEDIA BROWSER — Fase 1 (safe) — 2026-05-13

   Expande um mini painel DENTRO da própria sidebar,
   abaixo do item "Gallery". Sem overlay, sem backdrop,
   sem posicionamento fixo, sem z-index global.

   API pública:
     window.SidebarMediaBrowser.open()
     window.SidebarMediaBrowser.close()
     window.SidebarMediaBrowser.toggle()
     window.SidebarMediaBrowser.reload()
══════════════════════════════════════════════════════ */
(function () {
  "use strict";

  var LIMIT = 50;          // outputs a carregar (painel pequeno)

  var _items           = [];
  var _filter          = "all";
  var _loaded          = false;
  var _audioEl         = null;
  var _activeAudioCard = null;

  /* ════════════════════════════════════════════════
     Injetar painel no DOM (após o link Gallery)
  ════════════════════════════════════════════════ */
  function buildPanel(galleryLink) {
    var panel = document.createElement("div");
    panel.className = "sidebar-media-panel";
    panel.id        = "sidebar-media-panel";
    panel.innerHTML =
      '<div class="sidebar-media-filters">' +
        '<button class="smb-filter smb-active" data-type="all">All</button>' +
        '<button class="smb-filter" data-type="image">Img</button>' +
        '<button class="smb-filter" data-type="video">Vid</button>' +
        '<button class="smb-filter" data-type="audio">Aud</button>' +
      '</div>' +
      '<div class="sidebar-media-count" id="smb-count"></div>' +
      '<div class="sidebar-media-grid"  id="smb-grid"></div>' +
      // [B39-003] Removido target="_blank" — abria navegador externo no pywebview.
      // href com barra final + target="_self" → navega DENTRO da janela ACS.
      '<a href="/studio/gallery/" class="sidebar-media-full" target="_self">' +
        'Galeria completa &rarr;' +
      '</a>';

    /* Inserir imediatamente após o link Gallery */
    galleryLink.parentNode.insertBefore(panel, galleryLink.nextSibling);

    /* Filtros */
    panel.querySelectorAll(".smb-filter").forEach(function (btn) {
      btn.addEventListener("click", function () {
        _filter = btn.dataset.type;
        panel.querySelectorAll(".smb-filter").forEach(function (b) {
          b.classList.remove("smb-active");
        });
        btn.classList.add("smb-active");
        renderGrid();
      });
    });
  }

  /* ════════════════════════════════════════════════
     Open / Close / Toggle
  ════════════════════════════════════════════════ */
  function open() {
    var panel   = document.getElementById("sidebar-media-panel");
    var sidebar = document.querySelector(".sidebar");
    if (!panel) return;

    panel.classList.add("smb-open");
    if (sidebar) sidebar.classList.add("sidebar-media-open");

    var link = document.querySelector(".nav-item[data-smb-gallery]");
    if (link) link.classList.add("smb-gallery-active");

    if (!_loaded) loadItems();
  }

  function close() {
    var panel   = document.getElementById("sidebar-media-panel");
    var sidebar = document.querySelector(".sidebar");
    if (!panel) return;

    panel.classList.remove("smb-open");
    if (sidebar) sidebar.classList.remove("sidebar-media-open");

    var link = document.querySelector(".nav-item[data-smb-gallery]");
    if (link) link.classList.remove("smb-gallery-active");

    stopAudio();
  }

  function toggle() {
    var panel = document.getElementById("sidebar-media-panel");
    if (panel && panel.classList.contains("smb-open")) {
      close();
    } else {
      open();
    }
  }

  function reload() {
    _loaded = false;
    _items  = [];
    loadItems();
  }

  /* ════════════════════════════════════════════════
     Fetch /outputs
  ════════════════════════════════════════════════ */
  function loadItems() {
    var grid = document.getElementById("smb-grid");
    if (grid) grid.innerHTML = '<div class="smb-loading">Carregando&hellip;</div>';

    fetch("/outputs?limit=" + LIMIT)
      .then(function (r) { return r.json(); })
      .then(function (data) {
        _items  = data.outputs || [];
        _loaded = true;
        renderGrid();
      })
      .catch(function (e) {
        console.error("SidebarMediaBrowser: erro ao carregar.", e);
        if (grid) {
          grid.innerHTML = '<div class="smb-empty">Erro ao carregar.<br>ACS ativo?</div>';
        }
      });
  }

  /* ════════════════════════════════════════════════
     Render
  ════════════════════════════════════════════════ */
  function renderGrid() {
    var grid  = document.getElementById("smb-grid");
    var count = document.getElementById("smb-count");
    if (!grid) return;

    var items = _filter === "all"
      ? _items
      : _items.filter(function (i) { return i.type === _filter; });

    if (count) {
      count.textContent = items.length + " item" + (items.length !== 1 ? "s" : "");
    }

    if (!items.length) {
      grid.innerHTML = '<div class="smb-empty">Nenhum item.</div>';
      return;
    }

    grid.innerHTML = "";
    items.forEach(function (item) {
      var card = buildCard(item);
      if (card) grid.appendChild(card);
    });
  }

  // [B39-003/004] Viewer interno self-contained — substitui window.open(_blank),
  // que abria navegador externo no pywebview. Controles fixos (irmãos da transform),
  // zoom +/- por botão, reset, fechar (X/Esc/clique-fora). Sem navegador externo.
  function _smbOpenViewer(url, kind) {
    var prev = document.getElementById("acs-internal-viewer");
    if (prev) prev.remove();

    var ov = document.createElement("div");
    ov.id = "acs-internal-viewer";
    ov.style.cssText = "position:fixed;inset:0;z-index:99999;background:rgba(0,0,0,.93);overflow:hidden;";

    var stage = document.createElement("div");
    stage.style.cssText = "position:absolute;inset:0;display:flex;align-items:center;justify-content:center;overflow:hidden;";

    var media, isImage = (kind !== "video" && kind !== "audio");
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
      media.style.cssText = "max-width:92vw;max-height:88vh;border-radius:8px;object-fit:contain;transform-origin:center center;will-change:transform;user-select:none;";
    }
    media.draggable = false;
    media.addEventListener("click", function (e) { e.stopPropagation(); });
    stage.appendChild(media);

    var bar = document.createElement("div");
    bar.style.cssText = "position:absolute;top:14px;right:18px;z-index:5;display:flex;gap:8px;background:rgba(0,0,0,.55);border:1px solid #333;border-radius:10px;padding:6px 8px;";

    var scale = 1, MIN = 1, MAX = 6, STEP = 0.25;
    function apply() { if (isImage) media.style.transform = "scale(" + scale + ")"; }
    function setScale(n) { if (!isImage) return; scale = Math.min(MAX, Math.max(MIN, n)); apply(); }
    function reset() { scale = 1; apply(); }
    function mkBtn(label, title, fn) {
      var b = document.createElement("button");
      b.textContent = label; b.title = title;
      b.style.cssText = "min-width:34px;height:34px;font-size:16px;color:#fff;background:rgba(255,255,255,.08);border:1px solid #444;border-radius:7px;cursor:pointer;line-height:1;";
      b.addEventListener("click", function (e) { e.stopPropagation(); fn(); });
      return b;
    }
    function close() {
      try { if (media.pause) media.pause(); } catch (e) {}
      ov.remove(); document.removeEventListener("keydown", onKey);
    }
    function onKey(e) { if (e.key === "Escape") close(); }

    if (isImage) {
      bar.appendChild(mkBtn("−", "Zoom out", function () { setScale(scale - STEP); }));
      bar.appendChild(mkBtn("+", "Zoom in", function () { setScale(scale + STEP); }));
      bar.appendChild(mkBtn("↺", "Reset", reset));
      media.addEventListener("dblclick", function (e) { e.stopPropagation(); reset(); });
    }
    bar.appendChild(mkBtn("✕", "Fechar (Esc)", close));

    stage.addEventListener("click", close);
    document.addEventListener("keydown", onKey);
    ov.appendChild(stage); ov.appendChild(bar);
    document.body.appendChild(ov);
  }

  function buildCard(item) {
    var type = item.type || "image";
    var url  = item.url  || "";
    var name = item.name || (url.split("/").pop() || "—");
    var size = item.size_mb != null ? (item.size_mb + " MB") : "";

    if (type === "image") return buildImageCard(url, name);
    if (type === "video") return buildVideoCard(url, name);
    if (type === "audio") return buildAudioCard(url, name, size);
    return null;
  }

  /* ── Image ─────────────────────────────────────── */
  function buildImageCard(url, name) {
    var div = document.createElement("div");
    div.className = "smb-card smb-card-img";
    div.title     = name;

    var img = document.createElement("img");
    img.src     = url;
    img.alt     = name;
    img.loading = "lazy";

    var lbl = document.createElement("div");
    lbl.className   = "smb-card-label";
    lbl.textContent = name;

    div.appendChild(img);
    div.appendChild(lbl);
    // [B39-003] viewer interno em vez de window.open(_blank)
    div.addEventListener("click", function () {
      _smbOpenViewer(url, "image");
    });
    _setCardDrag(div, url, "image", name);
    return div;
  }

  /* ── Video ─────────────────────────────────────── */
  function buildVideoCard(url, name) {
    var div = document.createElement("div");
    div.className = "smb-card smb-card-vid";
    div.title     = name;

    /* <video> exibe o primeiro frame via preload="metadata" + seek 0.01s */
    var vid = document.createElement("video");
    vid.src     = url;
    vid.muted   = true;
    vid.preload = "metadata";
    vid.setAttribute("playsinline", "");
    /* Seek para o primeiro frame visível após carregar metadata */
    vid.addEventListener("loadedmetadata", function () {
      vid.currentTime = 0.01;
    });

    /* Ícone ▶ sobreposto */
    var icon = document.createElement("div");
    icon.className   = "smb-play-icon";
    icon.textContent = "▶";

    /* Tooltip com nome do arquivo */
    var lbl = document.createElement("div");
    lbl.className   = "smb-card-label";
    lbl.textContent = name;

    div.appendChild(vid);
    div.appendChild(icon);
    div.appendChild(lbl);
    // [B39-003] viewer interno em vez de window.open(_blank)
    div.addEventListener("click", function () {
      _smbOpenViewer(url, "video");
    });
    _setCardDrag(div, url, "video", name);
    return div;
  }

  /* ── Audio ─────────────────────────────────────── */
  function buildAudioCard(url, name, size) {
    var div = document.createElement("div");
    div.className   = "smb-card smb-card-aud";
    div.dataset.url = url;

    var ic = document.createElement("span");
    ic.className   = "smb-aud-ic";
    ic.textContent = "♪";

    var info = document.createElement("div");
    info.className = "smb-aud-info";

    var nm = document.createElement("div");
    nm.className   = "smb-aud-name";
    nm.title       = name;
    nm.textContent = name;
    info.appendChild(nm);

    if (size) {
      var mt = document.createElement("div");
      mt.className   = "smb-aud-meta";
      mt.textContent = size;
      info.appendChild(mt);
    }

    var btn = document.createElement("button");
    btn.className   = "smb-aud-btn";
    btn.title       = "Reproduzir";
    btn.textContent = "▶";
    btn.addEventListener("click", function (e) {
      e.stopPropagation();
      toggleAudio(url, div);
    });

    div.appendChild(ic);
    div.appendChild(info);
    div.appendChild(btn);
    div.addEventListener("click", function () {
      toggleAudio(url, div);
    });
    _setCardDrag(div, url, "audio", name);
    return div;
  }

  /* ════════════════════════════════════════════════
     Audio playback
  ════════════════════════════════════════════════ */
  function toggleAudio(url, card) {
    if (_audioEl && _activeAudioCard === card) {
      if (_audioEl.paused) {
        _audioEl.play();
        setAudioUI(card, true);
      } else {
        _audioEl.pause();
        setAudioUI(card, false);
      }
      return;
    }
    stopAudio();
    _audioEl         = new Audio(url);
    _activeAudioCard = card;
    _audioEl.addEventListener("ended", function () {
      setAudioUI(card, false);
      _audioEl         = null;
      _activeAudioCard = null;
    });
    _audioEl.play().catch(function (e) {
      console.warn("SidebarMediaBrowser: falha ao reproduzir.", e);
    });
    setAudioUI(card, true);
  }

  function stopAudio() {
    if (_audioEl) { _audioEl.pause(); _audioEl = null; }
    if (_activeAudioCard) {
      setAudioUI(_activeAudioCard, false);
      _activeAudioCard = null;
    }
  }

  function setAudioUI(card, playing) {
    var btn = card.querySelector(".smb-aud-btn");
    if (playing) {
      card.classList.add("smb-playing");
      if (btn) btn.textContent = "⏸";
    } else {
      card.classList.remove("smb-playing");
      if (btn) btn.textContent = "▶";
    }
  }

  /* ════════════════════════════════════════════════
     [FIX-DRAG] Arrastar item da galeria → zonas do dock
     Restaura o recurso de arrastar imagem/vídeo/áudio da
     sidebar para as zonas de upload (Video/Image/Motion/
     Audio). Origem: cards viram draggable e publicam
     {url,type,name}. Destino: interceptador global captura
     o drop, acha o <input type=file> da zona, valida o tipo
     pelo accept, baixa a URL → File, injeta no input e
     dispara 'change' (reusa os handlers já existentes).
  ════════════════════════════════════════════════ */
  var DRAG_MIME = "application/x-acs-media";

  function _setCardDrag(el, url, kind, name) {
    if (!el || !url) return;
    el.draggable = true;
    // [FIX-DRAG-IMG] <img>/<video> internos são nativamente arrastáveis e
    // "roubam" o drag do card (carregando só a própria URL, sem nosso payload).
    // Desligar draggable em TODOS os descendentes garante que SÓ o card seja a
    // origem do drag e publique {url,type,name}. (vídeo já era false; imagem não.)
    try {
      el.querySelectorAll("img, video, a").forEach(function (ch) { ch.draggable = false; });
    } catch (_) {}
    el.addEventListener("dragstart", function (e) {
      var payload = JSON.stringify({ url: url, type: kind, name: name || "" });
      try { e.dataTransfer.setData(DRAG_MIME, payload); } catch (_) {}
      try { e.dataTransfer.setData("text/plain", payload); } catch (_) {}
      try { e.dataTransfer.setData("text/uri-list", url); } catch (_) {}
      try { e.dataTransfer.effectAllowed = "copy"; } catch (_) {}
    });
  }

  // toast auto-contido (independe do showToast de cada aba)
  function _dragToast(msg) {
    var t = document.getElementById("acs-drag-toast");
    if (!t) {
      t = document.createElement("div");
      t.id = "acs-drag-toast";
      t.style.cssText = "position:fixed;bottom:24px;left:50%;transform:translateX(-50%);" +
        "z-index:100000;background:rgba(20,20,20,.95);color:#fff;border:1px solid #b4f246;" +
        "border-radius:8px;padding:10px 16px;font-size:13px;font-family:inherit;" +
        "box-shadow:0 4px 18px rgba(0,0,0,.5);pointer-events:none;transition:opacity .2s;";
      document.body.appendChild(t);
    }
    t.textContent = msg;
    t.style.opacity = "1";
    clearTimeout(t._h);
    t._h = setTimeout(function () { t.style.opacity = "0"; }, 2600);
  }

  function _zoneKindsFromAccept(input) {
    var a = (input.getAttribute("accept") || "").toLowerCase();
    var kinds = [];
    if (a.indexOf("image") !== -1) kinds.push("image");
    if (a.indexOf("video") !== -1) kinds.push("video");
    if (a.indexOf("audio") !== -1 || /\.(wav|mp3|ogg|flac|m4a|aac)/.test(a)) kinds.push("audio");
    return kinds;   // [] = aceita qualquer (não restringe)
  }

  function _findZoneInput(target) {
    var node = target;
    while (node && node.nodeType === 1) {
      if (node.querySelector) {
        var inp = node.querySelector('input[type="file"]');
        if (inp) return inp;
      }
      node = node.parentElement;
    }
    return null;
  }

  function _initGalleryDrop() {
    // CAPTURE: roda antes do handler de drop da própria zona
    document.addEventListener("drop", function (e) {
      var raw = "";
      try { raw = e.dataTransfer.getData(DRAG_MIME); } catch (_) {}
      if (!raw) { try { raw = e.dataTransfer.getData("text/plain"); } catch (_) {} }
      if (!raw || raw.charAt(0) !== "{") return;   // drop de arquivo do SO / externo → deixa nativo
      var meta; try { meta = JSON.parse(raw); } catch (_) { return; }
      if (!meta || !meta.url) return;

      var input = _findZoneInput(e.target);
      if (!input) return;                          // não caiu numa zona de upload

      e.preventDefault();
      e.stopPropagation();                         // assume o controle (evita handler duplicado)

      var kinds = _zoneKindsFromAccept(input);
      var kind  = meta.type || "image";
      if (kinds.length && kinds.indexOf(kind) === -1) {
        _dragToast('Tipo "' + kind + '" não vai nesta zona.');
        return;
      }

      _dragToast("Carregando da galeria…");
      fetch(meta.url).then(function (r) { return r.blob(); }).then(function (blob) {
        var name = meta.name || (meta.url.split("/").pop()) || "gallery";
        var file = new File([blob], name, { type: blob.type || "" });
        var dt = new DataTransfer();
        dt.items.add(file);
        input.files = dt.files;
        input.dispatchEvent(new Event("change", { bubbles: true }));
      }).catch(function () {
        _dragToast("Falha ao carregar da galeria.");
      });
    }, true);

    // habilita o drop (preventDefault no dragover) quando for nosso item sobre uma zona
    document.addEventListener("dragover", function (e) {
      var types = null;
      try { types = e.dataTransfer && e.dataTransfer.types; } catch (_) {}
      var isOurs = types && Array.prototype.indexOf.call(types, DRAG_MIME) !== -1;
      if (isOurs && _findZoneInput(e.target)) e.preventDefault();
    }, true);
  }

  /* ════════════════════════════════════════════════
     Init
  ════════════════════════════════════════════════ */
  function init() {
    var galleryLink = document.querySelector('a.nav-item[href="/studio/gallery"]');
    if (!galleryLink) return;

    galleryLink.setAttribute("data-smb-gallery", "1");

    galleryLink.addEventListener("click", function (e) {
      e.preventDefault();
      toggle();
    });

    buildPanel(galleryLink);
    _initGalleryDrop();
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }

  window.SidebarMediaBrowser = {
    open:   open,
    close:  close,
    toggle: toggle,
    reload: reload,
  };

}());
