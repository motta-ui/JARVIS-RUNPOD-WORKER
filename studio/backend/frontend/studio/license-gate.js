/* license-gate.js — [TRIAL-GATE Peça 4] Gating de UI do trial.
 * 100% ADITIVO e FAIL-SAFE: só trava se o plano for POSITIVAMENTE "trial".
 * Qualquer outra coisa (dev, pro, ultimate, erro de rede, resposta estranha) => NÃO mexe em nada.
 * Não toca payload/geração — apenas esconde abas 100% premium + mostra o banner de garantia.
 * O bloqueio REAL é server-side (acs_api /generate). Isto é só UX/upsell.
 */
(function () {
  "use strict";

  function lockNav(href) {
    try {
      var sel = 'a.nav-item[href="' + href + '"]';
      document.querySelectorAll(sel).forEach(function (a) {
        if (a.dataset.acsLocked) return;
        a.dataset.acsLocked = "1";
        a.setAttribute("title", "Disponível no acesso completo — liberado após a garantia (7 dias)");
        a.style.opacity = "0.5";
        var badge = a.querySelector(".nav-badge");
        if (badge) { badge.textContent = "🔒"; }
        a.addEventListener("click", function (e) {
          e.preventDefault();
          e.stopPropagation();
          showUpsell();
        }, true);
      });
    } catch (e) { /* fail-open */ }
  }

  function showUpsell() {
    try {
      alert("Este recurso faz parte do acesso completo.\n\n" +
            "Ele é liberado automaticamente após o período de garantia (7 dias).");
    } catch (e) {}
  }

  function showBanner(msg) {
    try {
      if (document.getElementById("acs-trial-banner")) return;
      var b = document.createElement("div");
      b.id = "acs-trial-banner";
      b.textContent = msg;
      b.style.cssText =
        "position:fixed;left:0;right:0;bottom:0;z-index:99999;" +
        "background:#17112b;color:#d9ccff;border-top:1px solid #6a4fd0;" +
        "padding:7px 14px;font:13px Inter,system-ui,sans-serif;text-align:center;" +
        "letter-spacing:.2px;box-shadow:0 -2px 12px rgba(0,0,0,.35)";
      document.body.appendChild(b);
    } catch (e) {}
  }

  function applyTrial() {
    lockNav("/studio/audio");
    lockNav("/studio/motion");
    showBanner("🛡️ Período de garantia (7 dias) — acesso completo é liberado automaticamente no 8º dia.");
    try { document.body.setAttribute("data-acs-plan", "trial"); } catch (e) {}
  }

  function init() {
    try {
      fetch("/license/features", { cache: "no-store" })
        .then(function (r) { return r.ok ? r.json() : null; })
        .then(function (d) {
          // SÓ trava se for explicitamente "trial". Senão, UI completa.
          if (d && d.plan === "trial") { applyTrial(); }
        })
        .catch(function () { /* fail-open: não trava nada */ });
    } catch (e) { /* fail-open */ }
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", init);
  } else {
    init();
  }
})();
