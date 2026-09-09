/* notif.js — Som de notificação ao terminar geração (Web Audio API)
   Lê notification_sound_enabled + notification_sound_volume de /config (wgp_config.json).
   Expõe window.playNotifBeep() — chamado pelos handlers "done" de cada aba. */
(function () {
  var _enabled = false, _volume = 50;

  fetch("/config").then(function (r) { return r.json(); }).then(function (d) {
    var s = d && d.settings;
    if (!s) return;
    _enabled = !!(Number(s.notification_sound_enabled) || s.notification_sound_enabled === true);
    _volume  = parseInt(s.notification_sound_volume ?? 50, 10);
  }).catch(function () {});

  window.playNotifBeep = function () {
    if (!_enabled || _volume <= 0) return;
    try {
      var ctx  = new (window.AudioContext || window.webkitAudioContext)();
      var vol  = Math.max(0, Math.min(100, _volume)) / 100 * 0.35;
      var now  = ctx.currentTime;

      function tone(freq, start, dur) {
        var osc  = ctx.createOscillator();
        var gain = ctx.createGain();
        osc.type = "sine";
        osc.frequency.value = freq;
        gain.gain.setValueAtTime(vol, now + start);
        gain.gain.exponentialRampToValueAtTime(0.001, now + start + dur);
        osc.connect(gain);
        gain.connect(ctx.destination);
        osc.start(now + start);
        osc.stop(now + start + dur + 0.05);
      }

      tone(523.25, 0,    0.25);
      tone(659.25, 0,    0.25);
      tone(783.99, 0,    0.25);
      tone(1046.5, 0.30, 0.35);
    } catch (e) {}
  };
})();
