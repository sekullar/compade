// Geliştirici hata ayıklama: arayüz olaylarını, tıklamaları, hataları ve ekran özetini sunucudaki günlüğe gönderir.
// Okumak için: python -m compade debug -n 100 --src ui   (ya da GET /api/debug)
(function () {
  const tok = (window.__COMPADE__ || {}).token;
  if (!tok) return;                       // yalnız gerçek sunucuyla
  let buf = [], timer = 0, lastSnap = '', snapTimer = 0;
  function flush() {
    timer = 0; if (!buf.length) return;
    const entries = buf; buf = [];
    try { fetch('/api/debug', { method: 'POST', keepalive: true, headers: { 'Content-Type': 'application/json', 'X-Compade-Token': tok }, body: JSON.stringify({ entries }) }).catch(() => {}); } catch (_) {}
  }
  function log(kind, d, chat) { buf.push({ kind, d, chat }); if (buf.length >= 50) flush(); else if (!timer) timer = setTimeout(flush, 400); }
  function short(s, n = 60) { s = String(s == null ? '' : s).replace(/\s+/g, ' ').trim(); return s.length > n ? s.slice(0, n) + '…' : s; }

  // ekranda GÖRÜNEN durum: sohbet kartları ve ekip çubuğu (sunucu/olay durumuyla karşılaştırmak için)
  function snapshot() {
    try {
      const feed = document.querySelector('.chat-feed, #chatFeed, .chat-messages');
      const kids = feed ? [...feed.children].map(n => (n.className || '').split(' ')[0]) : [];
      const plan = kids.indexOf('chat-plan');
      const tasks = [...document.querySelectorAll('.chat-task')].map(n => ({ id: short(n.querySelector('.chat-task-id')?.textContent, 12), st: short(n.querySelector('.chat-task-label')?.textContent, 20) || (n.className.match(/chat-state-(\w+)/) || [])[1] }));
      const bar = [...document.querySelectorAll('.tb-card')].map(c => [c.dataset.key, short(c.querySelector('.tb-status')?.textContent, 30)]).filter(x => x[1] && x[1] !== 'Hazır');
      const mem = (window.ChatUI && ChatUI.debugState && ChatUI.debugState()) || {};
      const snap = { mem, feed: { n: kids.length, plan, tail: kids.slice(-4) }, tasks, bar };
      const key = JSON.stringify(snap);
      if (key !== lastSnap) { lastSnap = key; log('snapshot', snap, mem.chatId); }
    } catch (e) { log('snapshot-error', { error: String(e) }); }
  }
  function soon() { clearTimeout(snapTimer); snapTimer = setTimeout(snapshot, 350); }

  window.Debug = {
    log,
    event(e) {                              // sunucudan gelen her SSE olayı
      const { kind, chat, ...rest } = e || {};
      const d = {}; for (const k of ['task', 'id', 'status', 'role', 'tag', 'state', 'run', 'ok', 'error']) if (rest[k] !== undefined) d[k] = rest[k];
      if (rest.plan) d.tasks = (rest.plan.tasks || []).map(t => t.id + ':' + t.role);
      if (rest.text || rest.summary) d.text = short(rest.text || rest.summary, 120);
      if (!['cc_text', 'cc_thinking'].includes(kind)) log('event ' + kind, d, chat);
      soon();
    },
    snapshot,
  };

  window.addEventListener('error', e => log('js-error', { msg: e.message, at: (e.filename || '').split('/').pop() + ':' + e.lineno + ':' + e.colno }));
  window.addEventListener('unhandledrejection', e => log('js-rejection', { msg: short(e.reason && (e.reason.stack || e.reason.message || e.reason), 400) }));
  for (const lvl of ['error', 'warn']) { const o = console[lvl]; console[lvl] = function (...a) { try { log('console.' + lvl, { msg: short(a.map(x => (x && x.message) || x).join(' '), 300) }); } catch (_) {} return o.apply(this, a); }; }
  document.addEventListener('click', e => {
    const el = e.target.closest && e.target.closest('button,a,[data-action],[data-chat],[data-task],[data-tool],.tb-card,summary');
    if (!el) return;
    log('click', { tag: el.tagName.toLowerCase(), action: el.dataset.action || el.dataset.chat || el.dataset.tool || el.id || undefined, text: short(el.innerText || el.getAttribute('aria-label'), 40) });
    soon();
  }, true);
  document.addEventListener('visibilitychange', () => log('visibility', { hidden: document.hidden }));
  window.addEventListener('online', () => log('net', { online: true })); window.addEventListener('offline', () => log('net', { online: false }));
  window.addEventListener('beforeunload', flush);
  log('ui-start', { ua: short(navigator.userAgent, 80), w: innerWidth, h: innerHeight });
  setInterval(() => { if (!document.hidden) snapshot(); }, 5000);   // olaysız sapmaları da yakala
})();
