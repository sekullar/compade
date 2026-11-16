/* Maliyet sayfası: /api/costs toplamı (gerçek token + Claude eşdeğer maliyet). */
(function () {
  let host = null, days = 7, data = null, showTable = false, seq = 0;
  const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const fmt = n => { n = Number(n || 0); return n >= 1e6 ? (n / 1e6).toFixed(n >= 1e7 ? 0 : 1) + 'M' : n >= 1e3 ? (n / 1e3).toFixed(n >= 1e4 ? 0 : 1) + 'k' : String(Math.round(n)); };
  const usd = n => '$' + Number(n || 0).toFixed(n >= 10 ? 0 : 2);
  const dur = s => { s = Number(s || 0); return s >= 60 ? Math.round(s / 60) + ' dk' : Math.round(s) + ' sn'; };
  const TIER = { cheap: 'Ucuz', mid: 'Orta', strong: 'Güçlü' };
  const dayLabel = d => { const [, m, g] = d.split('-'); return +g + '.' + +m; };

  async function load() {
    const my = ++seq;
    host.querySelector('.cost-body').setAttribute('aria-busy', 'true');
    try {
      const d = await window.api.costs(days);
      if (my !== seq) return;
      data = d; draw();
    } catch (e) { host.querySelector('.cost-body').innerHTML = '<div class="empty">Veri alınamadı: ' + esc(e.message || e) + '</div>'; }
  }

  function tiles(t) {
    const tile = (label, value, sub) => '<div class="cost-tile"><span>' + label + '</span><strong>' + value + '</strong>' + (sub ? '<small>' + sub + '</small>' : '') + '</div>';
    return '<div class="cost-tiles">'
      + tile('Toplam token', fmt(t.tokens), t.est_tokens ? '+ ~' + fmt(t.est_tokens) + ' tahmini' : 'sağlayıcının bildirdiği')
      + tile('Ekibin payı', t.team_share == null ? '—' : '%' + t.team_share, 'şef ' + fmt(t.chief_tokens) + ' · ekip ' + fmt(t.team_tokens))
      + tile('Şef (Claude) eşdeğeri', usd(t.cost_usd), t.cache_read ? 'önbellekten ' + fmt(t.cache_read) + ' token' : 'API fiyatıyla; abonelikte çekilmez')
      + tile('Başarı', t.pass == null ? '—' : '%' + t.pass, t.ok + ' / ' + t.runs + ' iş · ' + dur(t.seconds))
      + tile('Ucuz modelde', t.runs ? '%' + Math.round(100 * t.cheap_runs / t.runs) : '—', t.cheap_runs + ' iş' + (t.fell_back ? ' · ' + t.fell_back + ' yedeğe düştü' : ''))
      + '</div>';
  }

  function chart(rows) {
    const W = 720, H = 220, L = 44, B = 26, T = 10, R = 8;
    const max = Math.max(1, ...rows.map(r => r.team + r.chief));
    const step = Math.pow(10, Math.floor(Math.log10(max))); const top = Math.ceil(max / step) * step;
    const n = rows.length, slot = (W - L - R) / n, bw = Math.max(4, Math.min(34, slot * 0.62));
    const y = v => T + (H - T - B) * (1 - v / top);
    let g = '';
    for (let i = 0; i <= 4; i++) { const v = top * i / 4, yy = y(v); g += '<line x1="' + L + '" x2="' + (W - R) + '" y1="' + yy + '" y2="' + yy + '" class="cost-grid"/><text x="' + (L - 6) + '" y="' + (yy + 3) + '" class="cost-axis" text-anchor="end">' + fmt(v) + '</text>'; }
    const every = Math.ceil(n / 10);
    const bar = (x, y0, y1, cls, roundTop) => {
      const h = Math.max(0, y0 - y1); if (h < 0.5) return '';
      const r = roundTop ? Math.min(4, h, bw / 2) : 0;
      return '<path class="' + cls + '" d="M' + x + ',' + y0 + 'V' + (y1 + r) + (r ? 'Q' + x + ',' + y1 + ' ' + (x + r) + ',' + y1 + 'H' + (x + bw - r) + 'Q' + (x + bw) + ',' + y1 + ' ' + (x + bw) + ',' + (y1 + r) : 'H' + (x + bw)) + 'V' + y0 + 'Z"/>';
    };
    rows.forEach((r, i) => {
      const x = L + i * slot + (slot - bw) / 2, yb = y(0), yt = y(r.team), yc = y(r.team + r.chief);
      g += bar(x, yb, yt, 'cost-team', !r.chief);
      if (r.chief) g += bar(x, r.team ? yt - 2 : yb, yc, 'cost-chief', true);   // 2px yüzey boşluğu
      g += '<rect class="cost-hit" x="' + (L + i * slot) + '" y="' + T + '" width="' + slot + '" height="' + (H - T - B) + '" data-i="' + i + '"/>';
      if (i % every === 0 || i === n - 1) g += '<text x="' + (x + bw / 2) + '" y="' + (H - 8) + '" class="cost-axis" text-anchor="middle">' + dayLabel(r.day) + '</text>';
    });
    return '<svg viewBox="0 0 ' + W + ' ' + H + '" class="cost-svg" role="img" aria-label="Günlük token: ekip ve şef">' + g + '</svg>';
  }

  function dayTable(rows) {
    return '<table class="cost-table"><thead><tr><th>Gün</th><th>Ekip</th><th>Şef</th><th>Tahmini</th><th>İş</th><th>Şef $</th></tr></thead><tbody>'
      + rows.slice().reverse().map(r => '<tr><td>' + esc(r.day) + '</td><td>' + fmt(r.team) + '</td><td>' + fmt(r.chief) + '</td><td>' + (r.est ? '~' + fmt(r.est) : '—') + '</td><td>' + r.runs + '</td><td>' + (r.cost_usd ? usd(r.cost_usd) : '—') + '</td></tr>').join('') + '</tbody></table>';
  }

  function table(title, rows, isModel) {
    if (!rows.length) return '';
    return '<section class="cost-card"><h2>' + title + '</h2><div class="cost-scroll"><table class="cost-table"><thead><tr><th>' + (isModel ? 'Model' : 'Rol') + '</th>' + (isModel ? '<th>Kademe</th>' : '') + '<th>İş</th><th>Başarı</th><th>Token</th><th>Ort. süre</th><th>$</th></tr></thead><tbody>'
      + rows.map(r => '<tr><td class="cost-key">' + esc(r.key) + (r.chief ? ' <span class="cost-tag">şef</span>' : '') + '</td>' + (isModel ? '<td>' + (r.tier ? '<span class="cost-tier cost-tier-' + r.tier + '">' + TIER[r.tier] + '</span>' : '—') + '</td>' : '')
        + '<td>' + r.runs + '</td><td>%' + r.pass + '</td><td>' + (r.tokens ? fmt(r.tokens) + (r.est_tokens ? ' <small>+~' + fmt(r.est_tokens) + '</small>' : '') : r.est_tokens ? '<small title="Model token bildirmiyor; karakterden tahmin">~' + fmt(r.est_tokens) + '</small>' : '—') + '</td><td>' + dur(r.avg_sec) + '</td><td>' + (r.cost_usd ? usd(r.cost_usd) : '—') + '</td></tr>').join('')
      + '</tbody></table></div></section>';
  }

  function draw() {
    const body = host.querySelector('.cost-body'); body.removeAttribute('aria-busy');
    const d = data, t = d.totals;
    if (!t.runs) { body.innerHTML = '<div class="cost-empty"><strong>Bu aralıkta kayıt yok.</strong><p>Ekip ya da şef çalıştıkça token ve süreler burada toplanır.</p></div>'; return; }
    body.innerHTML = tiles(t)
      + '<section class="cost-card"><div class="cost-card-head"><h2>Günlük token</h2><div class="cost-legend"><span><i class="cost-sw cost-team"></i>Ekip</span><span><i class="cost-sw cost-chief"></i>Şef (Claude)</span></div><button type="button" class="cost-link" data-cost="table" aria-pressed="' + showTable + '">' + (showTable ? 'Grafik' : 'Tablo') + '</button></div>'
      + (showTable ? '<div class="cost-scroll">' + dayTable(d.by_day) + '</div>' : '<div class="cost-plot">' + chart(d.by_day) + '<div class="cost-tip" hidden></div></div>')
      + '<p class="cost-note">Token: sağlayıcının bildirdiği gerçek sayı. Bildirmeyen modellerde karakterden tahmin edilir ve ayrı gösterilir. $: Claude Code\'un bildirdiği eşdeğer API maliyeti.</p></section>'
      + '<div class="cost-grid2">' + table('Model başına', d.by_model, true) + table('Rol başına', d.by_role, false) + '</div>';
    body.querySelector('[data-cost="table"]').onclick = () => { showTable = !showTable; draw(); };
    const plot = body.querySelector('.cost-plot'); if (!plot) return;
    const tip = plot.querySelector('.cost-tip');
    plot.querySelectorAll('.cost-hit').forEach(h => {
      const show = () => { const r = d.by_day[+h.dataset.i]; tip.innerHTML = '<strong>' + esc(r.day) + '</strong><div><i class="cost-sw cost-team"></i>Ekip <b>' + fmt(r.team) + '</b></div><div><i class="cost-sw cost-chief"></i>Şef <b>' + fmt(r.chief) + '</b></div>' + (r.est ? '<div>Tahmini <b>~' + fmt(r.est) + '</b></div>' : '') + '<div>' + r.runs + ' iş' + (r.cost_usd ? ' · ' + usd(r.cost_usd) : '') + '</div>';
        tip.hidden = false; const pb = plot.getBoundingClientRect(), hb = h.getBoundingClientRect(); let x = hb.left - pb.left + hb.width / 2 - tip.offsetWidth / 2; x = Math.max(0, Math.min(pb.width - tip.offsetWidth, x)); tip.style.left = x + 'px'; plot.querySelectorAll('.cost-hit').forEach(o => o.classList.toggle('on', o === h)); };
      h.addEventListener('mouseenter', show); h.addEventListener('focus', show);
    });
    plot.addEventListener('mouseleave', () => { tip.hidden = true; plot.querySelectorAll('.cost-hit').forEach(o => o.classList.remove('on')); });
  }

  function mount(el) {
    host = el;
    host.innerHTML = '<section class="page cost-page"><div class="cost-head"><h1>Maliyet</h1><div class="cost-range" role="group" aria-label="Zaman aralığı">'
      + [7, 30, 90].map(n => '<button type="button" data-days="' + n + '" aria-pressed="' + (n === days) + '">' + n + ' gün</button>').join('') + '</div><button type="button" class="cost-link" data-cost="reload">Yenile</button></div><div class="cost-body" aria-live="polite"><div class="cost-empty">Yükleniyor…</div></div></section>';
    host.querySelectorAll('[data-days]').forEach(b => b.onclick = () => { days = +b.dataset.days; host.querySelectorAll('[data-days]').forEach(x => x.setAttribute('aria-pressed', x === b)); load(); });
    host.querySelector('[data-cost="reload"]').onclick = load;
    load();
  }
  function unmount() { host = null; seq++; }
  window.CostsUI = { mount, unmount };
})();
