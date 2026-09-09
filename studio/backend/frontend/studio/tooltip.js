/* ============================================================
   ACS Studio — Commercial Tooltips  v1
   Standalone engine. No dependencies. No modifications to
   IDs, values, data-keys, payloads, routes or generation logic.

   How it works:
     1. Elements with data-acs-tip-title / data-acs-tip-body
        get a small ⓘ icon appended (inside buttons, or after labels).
     2. Hovering the ⓘ shows a global floating bubble (#acs-tip-bubble).
     3. MutationObserver adds ⓘ to LoRA items when dynamically rendered.

   Triggering: hover the ⓘ icon (not the element itself — no interference
   with clicks, drags, or keyboard navigation).
============================================================ */
(function () {
  'use strict';

  /* ── LoRA tooltip map (matches LORA_DISPLAY_NAMES in acs_api.py) ───────
     Key: filename stem (data-name attribute on .lora-cb checkboxes)
  ─────────────────────────────────────────────────────────────────────── */
  const LORA_TIPS = {
    'Ltx2.3-Licon-VBVR-I2V-96000-R32': {
      title: 'Motion Intelligence I2V',
      body:  'Melhora a coerência de movimento entre frames, criando animações mais fluidas e naturais. Câmera e personagens se movem de forma independente e coerente — ideal para cenas com múltiplos objetos em animação simultânea.',
      tag:   'Cinematic Pro ·I2V'
    },
    'id-lora-celebvhq-ltx2.3': {
      title: 'ID Portrait',
      body:  'Preserva a identidade facial durante todo o vídeo. Perfeito para talking-heads, narrações e retratos em movimento onde o rosto precisa ser consistente e reconhecível de ponta a ponta.',
      tag:   'Cinematic Pro ·Retrato'
    },
    'ltx-2.3-22b-distilled-lora-384-1.1': {
      title: 'Turbo Render',
      body:  'Acelera drasticamente a geração reduzindo para 8 steps de inferência, sem perda perceptível de qualidade visual. Ideal para prototipagem rápida, testes de composição e quando VRAM é limitada.',
      tag:   'Cinematic Pro ·Rápido'
    },
    'ltx-2.3-22b-ic-lora-hdr-0.9': {
      title: 'HDR Cinematic',
      body:  'Realça contraste, brilho e profundidade cinematográfica, criando cenas mais impactantes e dramáticas. Ideal para neons, sunsets, luz forte e estética premium de filme de estúdio.',
      tag:   'Cinematic Pro ·HDR'
    },
    'ltx-2.3-22b-ic-lora-outpaint': {
      title: 'Scene Expander',
      body:  'Expande o enquadramento além das bordas originais, preenchendo as regiões novas com conteúdo visualmente coerente. Use para ampliar paisagens, revelar o ambiente ao redor ou criar composições mais largas.',
      tag:   'Cinematic Pro ·Expansão'
    },
    'ltx-2.3-22b-ic-lora-union-control-ref0.5': {
      title: 'Director Control',
      body:  'Ajuda a criar movimentos de câmera mais cinematográficos e controlados, com sensação de direção profissional. Suporta controle simultâneo por bordas Canny, mapa de profundidade e OpenPose.',
      tag:   'Cinematic Pro ·Direção'
    },
  };

  /* ── Singleton bubble ──────────────────────────────────────── */
  const bubble = document.createElement('div');
  bubble.id = 'acs-tip-bubble';
  document.body.appendChild(bubble);

  let hideTimer    = null;
  let showTimer    = null;
  const SHOW_DELAY = 220;   // ms before showing (avoids flicker on fast sweeps)
  const HIDE_DELAY = 130;   // ms before hiding

  /* ── Build HTML content ──────────────────────────────────── */
  function buildHTML(tip) {
    if (typeof tip === 'string') {
      return '<span class="acs-tip-body">' + tip + '</span>';
    }
    let html = '';
    if (tip.title) html += '<span class="acs-tip-title">' + tip.title + '</span>';
    if (tip.body)  html += '<span class="acs-tip-body">'  + tip.body  + '</span>';
    if (tip.tag)   html += '<span class="acs-tip-tag">'   + tip.tag   + '</span>';
    return html;
  }

  /* ── Show bubble above/below anchor element ──────────────── */
  function showBubble(anchor, tip) {
    clearTimeout(hideTimer);
    clearTimeout(showTimer);

    showTimer = setTimeout(function () {
      bubble.innerHTML = buildHTML(tip);
      bubble.classList.remove('below');
      bubble.classList.add('visible');

      // Position: above anchor by default
      var rect   = anchor.getBoundingClientRect();
      var bw     = bubble.offsetWidth  || 224;
      var bh     = bubble.offsetHeight || 80;
      var vw     = window.innerWidth;
      var vh     = window.innerHeight;
      var margin = 8;

      // Horizontal center over anchor, clamped to viewport
      var left = rect.left + rect.width / 2 - bw / 2;
      left = Math.max(margin, Math.min(left, vw - bw - margin));

      // Vertical: prefer above anchor
      var topAbove = rect.top - bh - 10;
      var topBelow = rect.bottom + 10;

      var top, below;
      if (topAbove >= margin) {
        top   = topAbove;
        below = false;
      } else {
        top   = topBelow;
        below = true;
      }
      top = Math.max(margin, Math.min(top, vh - bh - margin));

      // Caret alignment relative to bubble left edge
      var caretCenterPx = rect.left + rect.width / 2 - left;
      caretCenterPx = Math.max(16, Math.min(caretCenterPx, bw - 16));
      bubble.style.setProperty('--caret-left', caretCenterPx + 'px');

      bubble.style.left = left + 'px';
      bubble.style.top  = top  + 'px';

      if (below) bubble.classList.add('below');
    }, SHOW_DELAY);
  }

  function hideBubble() {
    clearTimeout(showTimer);
    hideTimer = setTimeout(function () {
      bubble.classList.remove('visible');
      bubble.classList.remove('below');
    }, HIDE_DELAY);
  }

  /* Keep bubble visible when mouse is over it */
  bubble.addEventListener('mouseenter', function () { clearTimeout(hideTimer); });
  bubble.addEventListener('mouseleave', hideBubble);

  /* ── Wire a single element (idempotent) ──────────────────── */
  function wire(el, tip) {
    if (el._acsTipWired) return;
    el._acsTipWired = true;
    el.addEventListener('mouseenter', function () { showBubble(el, tip); });
    el.addEventListener('mouseleave', hideBubble);
    el.addEventListener('focus',      function () { showBubble(el, tip); });
    el.addEventListener('blur',       hideBubble);
  }

  /* ── Append ⓘ icon inside a button/pill ─────────────────── */
  function appendIconInsideButton(btn, tip) {
    if (btn.querySelector('.acs-tip-icon')) return; // already done
    var icon = document.createElement('span');
    icon.className = 'acs-tip-icon';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = 'ⓘ';
    btn.appendChild(icon);
    wire(icon, tip);
  }

  /* ── Append ⓘ icon after a label/span ───────────────────── */
  function appendIconAfterLabel(label, tip) {
    if (label.querySelector('.acs-tip-icon')) return;
    var icon = document.createElement('span');
    icon.className = 'acs-tip-icon acs-tip-icon--label';
    icon.setAttribute('aria-hidden', 'true');
    icon.textContent = 'ⓘ';
    label.appendChild(icon);
    wire(icon, tip);
  }

  /* ── Init: static elements with data-acs-tip-* ──────────── */
  function initStatic() {
    document.querySelectorAll('[data-acs-tip-title],[data-acs-tip-body]').forEach(function (el) {
      var tip = {
        title: el.dataset.acsTipTitle || '',
        body:  el.dataset.acsTipBody  || '',
        tag:   el.dataset.acsTipTag   || '',
      };

      // Determine icon placement by element type
      var tag = el.tagName.toLowerCase();
      if (tag === 'button') {
        appendIconInsideButton(el, tip);
      } else if (tag === 'label' || tag === 'span' || tag === 'div') {
        appendIconAfterLabel(el, tip);
      } else if (tag === 'select') {
        // For selects: find or create a wrapper, put icon after select
        var icon = document.createElement('span');
        icon.className = 'acs-tip-icon acs-tip-icon--label';
        icon.setAttribute('aria-hidden', 'true');
        icon.textContent = 'ⓘ';
        el.insertAdjacentElement('afterend', icon);
        wire(icon, tip);
      } else {
        // Fallback: wire hover on the element itself
        wire(el, tip);
      }
    });
  }

  /* ── LoRA observer: watches #lora-list for rendered items ── */
  function initLoraObserver() {
    var list = document.getElementById('lora-list');
    if (!list) return;

    function processItems() {
      // Each lora-item has a .lora-cb checkbox with data-name="${l.name}"
      list.querySelectorAll('.lora-item').forEach(function (item) {
        if (item._acsTipLoraWired) return;

        var cb       = item.querySelector('.lora-cb[data-name]');
        var nameSpan = item.querySelector('.lora-name');
        if (!cb && !nameSpan) return;

        var stemKey  = (cb && cb.dataset.name) || '';
        var labelTxt = (nameSpan && nameSpan.textContent.trim()) || '';

        // Match by stem first, then by label text
        var tip = LORA_TIPS[stemKey];
        if (!tip) {
          // Try partial match on label text vs LORA_TIPS values
          var keys = Object.keys(LORA_TIPS);
          for (var k = 0; k < keys.length; k++) {
            if (labelTxt && LORA_TIPS[keys[k]].title === labelTxt) {
              tip = LORA_TIPS[keys[k]];
              break;
            }
          }
        }

        if (tip && nameSpan) {
          appendIconAfterLabel(nameSpan, tip);
          item._acsTipLoraWired = true;
        }
      });
    }

    var obs = new MutationObserver(processItems);
    obs.observe(list, { childList: true, subtree: true });
    processItems(); // run immediately if already rendered
  }

  /* ── Boot ────────────────────────────────────────────────── */
  function boot() {
    initStatic();
    initLoraObserver();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }

})();
