/* ═══════════════════════════════════════════════════════════════
   gallery-delete.js — botão 🗑 reutilizável para cards de galeria
   ─────────────────────────────────────────────────────────────────
   Uso (em qualquer tab JS após criar um card):

     attachGalleryDeleteBtn(card, filename);
     attachGalleryDeleteBtn(card, filename, { onDeleted: () => refresh() });

   - Adiciona um botão pequeno no canto sup-direito do card.
   - Confirmação antes de deletar.
   - Chama DELETE /outputs/{filename}.
   - Em sucesso: fade out e remove o card do DOM.
   - Em falha: alerta com mensagem do backend.

   Compatível com .gallery-thumb (image), .video-card (video/motion),
   .audio-card (audio). O CSS de visibilidade hover está em studio.css.
═══════════════════════════════════════════════════════════════ */
(function (global) {
  function _request(filename) {
    return fetch('/outputs/' + encodeURIComponent(filename), { method: 'DELETE' })
      .then(async function (res) {
        if (!res.ok) {
          let detail = 'HTTP ' + res.status;
          try {
            const err = await res.json();
            if (err && err.detail) detail = err.detail;
          } catch (_) { /* ignore json parse error */ }
          throw new Error(detail);
        }
        return res.json();
      });
  }

  global.attachGalleryDeleteBtn = function (cardEl, filename, opts) {
    if (!cardEl || !filename) return null;
    if (cardEl.querySelector(':scope > .gallery-delete-btn')) return null; /* idempotente */

    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'gallery-delete-btn';
    btn.title = 'Deletar este arquivo';
    btn.setAttribute('aria-label', 'Deletar arquivo');
    btn.textContent = '🗑';

    btn.addEventListener('click', async function (e) {
      e.preventDefault();
      e.stopPropagation();
      if (!confirm('Tem certeza que deseja deletar "' + filename + '"?')) return;
      btn.disabled = true;
      try {
        await _request(filename);
        cardEl.style.transition = 'opacity 180ms ease, transform 180ms ease';
        cardEl.style.opacity = '0';
        cardEl.style.transform = 'scale(.92)';
        setTimeout(function () { cardEl.remove(); }, 200);
        if (opts && typeof opts.onDeleted === 'function') {
          try { opts.onDeleted(filename); } catch (_) { /* swallow */ }
        }
      } catch (err) {
        alert('Erro ao deletar: ' + (err && err.message ? err.message : 'desconhecido'));
        btn.disabled = false;
      }
    });

    cardEl.appendChild(btn);
    return btn;
  };
})(window);
