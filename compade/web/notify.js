/* Masaüstü bildirimi: pencere arka plandayken önemli olaylar (şef soru sordu, plan onay bekliyor, değişiklikler hazır, iş bitti). */
(function () {
  const supported = 'Notification' in window;
  let asked = false, last = {};
  const enabled = () => supported && (((window.getAppState && window.getAppState()) || {}).cfg || {}).notify !== false;
  const away = () => document.hidden || !document.hasFocus();

  function ask() {
    if (asked || !enabled() || Notification.permission !== 'default') return;
    asked = true;
    try { Notification.requestPermission(); } catch (_) {}
  }
  // izin yalnız kullanıcı etkileşimiyle istenebilir: ilk tıklamada bir kez
  document.addEventListener('click', ask, { capture: true });

  function show(key, title, body) {
    if (!enabled() || Notification.permission !== 'granted' || !away()) return;
    const now = Date.now();
    if (last[key] && now - last[key] < 4000) return;      // aynı olay seli için tek bildirim
    last[key] = now;
    try {
      const n = new Notification(title, { body: String(body || '').slice(0, 180), tag: key, silent: false });
      n.onclick = () => { window.focus(); n.close(); if (window.nav) window.nav('office'); };
    } catch (_) {}
  }

  function handle(e) {
    if (!e || !e.kind) return;
    const c = e.chat || '';
    switch (e.kind) {
      case 'ask_user': show('ask-' + c, 'Şef sana soruyor', e.question); break;
      case 'plan_ready': if (!e.auto) show('plan-' + c, 'Plan onay bekliyor', (e.plan?.tasks || []).length + ' görev · ' + (e.plan?.summary || '')); break;
      case 'cc_plan': show('plan-' + c, 'Plan onay bekliyor', (e.plan?.tasks || []).length + ' görev · ' + (e.plan?.summary || '')); break;
      case 'changes_ready': show('chg-' + c, 'Değişiklikler hazır', (e.files || []).length + ' dosya inceleyip uygulamanı bekliyor'); break;
      case 'chat_done': if (e.state === 'done') show('done-' + c, 'Ekip işi bitirdi', 'Sonuçlar sohbette.'); break;
      case 'cc_result': show('reply-' + c, 'Şef yanıtladı', e.text); break;
      case 'cc_limit': show('limit', 'Kullanım sınırı', e.info || 'Şefin kullanım sınırı doluyor.'); break;
      case 'decision_limit': show('dl-' + c, 'Yeniden deneme hakkı doldu', 'Görev ' + (e.task || '') + ' olduğu gibi bırakıldı.'); break;
    }
  }
  window.Notifier = { handle, supported };
})();
