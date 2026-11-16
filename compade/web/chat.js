/* Compade chief conversation module. */
(function () {
  'use strict';
  const memory = { chatId: null, messages: [], plan: null, tasks: {}, state: 'idle', phase: '', ready: false, usage: null, estTokens: null, direct: false, busy: false, auto: false, seen: new Set(), cwd: '', approval: '', disconnected: false, demo: false, toolQuestion: null, selectedTool: null, cc: false, ccTools: [], ccThinking: '', ccLive: '', ccMode: 'default', ccUsage: null, ccLimit: '', ccTasks: [], ccQuestion: '' };
  let host = null, ctx = null, els = null;
  const esc = (s) => ctx && ctx.esc ? ctx.esc(String(s == null ? '' : s)) : String(s == null ? '' : s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  function toText(v) {
    if (typeof v === 'string') return v;
    if (v == null) return '';
    if (Array.isArray(v)) return v.map(x => typeof x === 'string' ? x : (x && (x.text ?? x.content) != null ? toText(x.text ?? x.content) : '')).filter(Boolean).join('\n');
    if (typeof v === 'object') { for (const k of ['text', 'content', 'message']) if (v[k] != null) return toText(v[k]); try { return JSON.stringify(v).slice(0, 4000); } catch (_) { return ''; } }
    return String(v);
  }
  const notify = (e) => { if (ctx && ctx.notify) ctx.notify(e && e.message ? e.message : String(e)); };
  function toolCard(t) {
    const card = document.createElement('details'); card.className = 'cc-tool';
    const input = (() => { let v = t.input || {}; if (typeof v === 'string') { try { const o = JSON.parse(v); if (o && typeof o === 'object') v = o; } catch (_) {} } return v; })(), name = String(t.name || 'Araç'), root = (ctx.getCwd && ctx.getCwd() || '').replace(/\\/g, '/').replace(/\/$/, '');
    const path = value => { let p = String(value || '').replace(/\\\\/g, '\\').replace(/\\/g, '/'); if (root && p.toLowerCase().startsWith(root.toLowerCase() + '/')) p = p.slice(root.length + 1); return p; };
    let summary = typeof input === 'string' ? input : '';
    if (input && typeof input === 'object') {
      if (/^(Bash|PowerShell|powershell)$/i.test(name)) summary = input.command || input.cmd || '';
      else if (/^(Read|Write|Edit)$/i.test(name)) summary = path(input.file_path || input.path);
      else if (/^(Grep|Glob)$/i.test(name)) summary = [input.pattern, path(input.path || input.directory)].filter(Boolean).join(' · ');
      else summary = input.command || input.file_path || input.path || JSON.stringify(input);
    }
    const state = t.status === 'running' ? '<span class="cc-spinner" aria-label="Çalışıyor"></span> Çalışıyor' : t.ok === false ? 'Hata' : 'Tamamlandı';
    const oldText = input.old_string ?? input.old ?? input.before, newText = input.new_string ?? input.new ?? input.after;
    const diff = oldText != null || newText != null ? '<pre class="cc-diff">' + String(oldText || '').split('\n').map(x => '<span class="cc-diff-old">− ' + esc(x) + '</span>').join('\n') + (oldText && newText ? '\n' : '') + String(newText || '').split('\n').map(x => '<span class="cc-diff-new">+ ' + esc(x) + '</span>').join('\n') + '</pre>' : '';
    card.innerHTML = '<summary><strong>' + esc(name) + '</strong><code title="' + esc(summary) + '">' + esc(String(summary).slice(0, 180)) + '</code><span>' + state + '</span></summary>' + diff + '<pre>' + esc(JSON.stringify(input, null, 2)) + (t.content ? '\n\n' + esc(String(t.content).slice(0, 4000)) : '') + '</pre>';
    return card;
  }
  function format(text) {
    const blocks = String(text || '').split(/```([^\n]*)\n([\s\S]*?)```/g);
    let out = '';
    for (let i = 0; i < blocks.length; i += 3) {
      if (i) out += '<pre class="chat-code"><code>' + esc(blocks[i + 2]) + '</code></pre>';
      const raw = blocks[i] || '';
      const lines = raw.split('\n'); let list = false;
      for (const line of lines) {
        const m = line.match(/^\s*[-*]\s+(.+)$/);
        if (m) { if (!list) { out += '<ul>'; list = true; } out += '<li>' + inline(m[1]) + '</li>'; }
        else { if (list) { out += '</ul>'; list = false; } out += inline(line) + '<br>'; }
      }
      if (list) out += '</ul>';
    }
    return out.replace(/(?:<br>)+$/, '');
  }
  function inline(s) {
    let x = esc(s);
    x = x.replace(/`([^`]+)`/g, '<code>$1</code>');
    x = x.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    return x;
  }
  function button(label, cls, action, disabled) { return '<button type="button" class="btn ' + (cls || '') + '" data-action="' + action + '"' + (disabled ? ' disabled' : '') + '>' + label + '</button>'; }
  function render() {
    if (!host || !els) return;
    if (!memory.cc && (memory.messages.length || memory.plan) && els.feed.querySelector('.chat-empty')) {
      if (!els.feed.classList.contains('chat-hero-leaving')) {
        els.feed.classList.add('chat-hero-leaving');
        setTimeout(() => { if (!els) return; els.feed.querySelectorAll('.chat-empty,.chat-hero-scene').forEach(n => n.remove()); els.feed.classList.remove('chat-hero-leaving'); render(); }, 220);
      }
      return;
    }
    const priorScrollTop = els.feed.scrollTop;
    const nearBottom = els.feed.scrollHeight - els.feed.scrollTop - els.feed.clientHeight <= 80;
    els.feed.innerHTML = '';
    if (memory.cc) {
      const html = memory.messages.map(m => m.who === 'user' ? '<div class="cc-user"><span aria-hidden="true">&gt;</span> ' + format(toText(m.text)) + '</div>' : m.note ? noteHtml(m) : '<div class="cc-assistant">' + format(toText(m.text)) + '</div>').join('');
      els.feed.innerHTML = html;
      if (memory.ccThinking) { const d = document.createElement('details'); d.className = 'cc-thinking'; d.open = false; d.innerHTML = '<summary>Düşünüyor…</summary><div>' + format(memory.ccThinking) + (memory.busy ? '<span class="cc-cursor" aria-hidden="true"></span>' : '') + '</div>'; els.feed.appendChild(d); }
      if (memory.ccLive) { const live = document.createElement('div'); live.className = 'cc-assistant'; live.innerHTML = format(memory.ccLive) + (memory.busy ? '<span class="cc-cursor" aria-hidden="true"></span>' : ''); live.setAttribute('aria-live', 'polite'); els.feed.appendChild(live); }
      for (let i = 0; i < memory.ccTools.length;) {
        let end = i + 1;
        while (end < memory.ccTools.length && memory.ccTools[end].name === memory.ccTools[i].name) end++;
        const batch = memory.ccTools.slice(i, end);
        if (batch.length >= 4) { const group = document.createElement('details'); group.className = 'cc-tool-group'; group.innerHTML = '<summary>' + batch.length + ' araç çağrısı · ' + esc(batch[0].name) + '</summary>'; batch.forEach(t => group.appendChild(toolCard(t))); els.feed.appendChild(group); }
        else batch.forEach(t => els.feed.appendChild(toolCard(t)));
        i = end;
      }
      memory.ccTasks.forEach(t => { const row = document.createElement('div'); row.className = 'cc-task cc-task-' + esc(t.status); row.innerHTML = '<strong>' + esc(t.role || t.task || 'Görev') + '</strong> <span>' + esc(({ done: 'Tamam', blocked: 'Takıldı', failed: 'Başarısız', needs_input: 'Bilgi istiyor', continued: 'Atlandı' })[t.status] || t.status || '') + '</span> ' + format(t.summary || '') + (t.needs ? '<small> · Gerekli: ' + esc(t.needs) + '</small>' : ''); els.feed.appendChild(row); });
      if (memory.ccQuestion) { const q = document.createElement('section'); q.className = 'cc-question'; q.innerHTML = '<strong>Şef soruyor</strong><p>' + format(memory.ccQuestion) + '</p><textarea aria-label="Yanıtınız" rows="2"></textarea><button type="button" data-action="answer">Yanıtla</button>'; els.feed.appendChild(q); }
      if (memory.ccLimit) { const n = document.createElement('div'); n.className = 'cc-limit'; n.setAttribute('role', 'alert'); n.textContent = memory.ccLimit; els.feed.appendChild(n); }
      if (memory.plan) els.feed.appendChild(planCard());
      if (memory.ccPlanInvalid) { const n = document.createElement('div'); n.className = 'cc-limit'; n.setAttribute('role', 'alert'); n.textContent = 'Plan geçersiz: ' + memory.ccPlanInvalid; els.feed.appendChild(n); }
      if (memory.ccUsage) { const u = memory.ccUsage; const n = document.createElement('div'); n.className = 'cc-usage'; n.textContent = `${u.duration_ms == null ? '' : (u.duration_ms / 1000).toFixed(1) + ' sn · '}${u.usage?.in ?? u.in ?? 0} in / ${u.usage?.out ?? u.out ?? 0} out · önbellek ${u.usage?.cache_read ?? u.cache_read ?? 0} · $${Number(u.cost_usd || 0).toFixed(4)}`; els.feed.appendChild(n); }
      document.documentElement.classList.remove('chat-hero-visible');
    } else if (!memory.messages.length && !memory.plan) {
      document.documentElement.classList.add('chat-hero-visible');
      const state = ctx && ctx.getState ? ctx.getState() || {} : {};
      const roles = Array.isArray(state.roles) ? state.roles : [];
      const chief = roles.find(r => r.key === 'chief' || r.chief) || {};
      const hasRoles = roles.length > 0;
      let mascot = '';
      try { if (window.TeamBar && typeof window.TeamBar.mascot === 'function') mascot = window.TeamBar.mascot(chief.color || 'var(--accent, var(--teal, #35c8ad))', 'idle', !!chief.key, 'round'); } catch (_) {}
      const discussFirst = !!state.cfg?.discuss_first;
      els.feed.innerHTML = '<div class="chat-hero-scene" aria-hidden="true"><i class="chat-aurora chat-aurora-one"></i><i class="chat-aurora chat-aurora-two"></i><i class="chat-aurora chat-aurora-three"></i><i class="chat-hero-grid"></i><i class="chat-hero-spotlight"></i></div><section class="chat-empty" aria-labelledby="chat-hero-title"><div class="chat-hero-mascot-wrap">' + (mascot ? '<div class="chat-hero-mascot">' + mascot + '</div>' : '') + '<span class="chat-hero-shadow"></span></div><h1 id="chat-hero-title">' + (chief.key ? '<span>Şefe</span> <span>bir</span>' : '<span>Bir</span>') + ' <span>iş</span> <span>anlat</span></h1><p>' + (discussFirst ? 'Önce konuşup anlaşırsınız, sonra şef planı çıkarır.' : hasRoles ? 'İsteğini yaz; şef uygun rollere görev dağıtıp sonucu toparlasın.' : 'İsteğini yaz; kullanılacak aracı seçebilirsin.') + '</p><div class="chat-examples"><button type="button" class="chat-chip">Projeyi inceleyip iyileştirme önerileri çıkar</button><button type="button" class="chat-chip">Bu hatanın nedenini bul ve düzelt</button><button type="button" class="chat-chip">Arayüzü mobil ekranlara uyarla</button></div></section>';
      const scene = els.feed.querySelector('.chat-hero-scene');
      const hero = els.feed.querySelector('.chat-empty');
      const reduced = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
      if (!reduced) {
        let frame = 0;
        hero.addEventListener('pointermove', e => {
          const rect = hero.getBoundingClientRect();
          const x = e.clientX - rect.left, y = e.clientY - rect.top;
          hero.style.setProperty('--mx', x + 'px'); hero.style.setProperty('--my', y + 'px');
          if (scene) { scene.style.setProperty('--mx', x + 'px'); scene.style.setProperty('--my', y + 'px'); }
          const dx = Math.max(-3, Math.min(3, (x / rect.width - .5) * 6));
          const dy = Math.max(-3, Math.min(3, (y / rect.height - .5) * 6));
          if (!frame) frame = requestAnimationFrame(() => { if (mascot) hero.style.setProperty('--lx', dx + 'px'); if (mascot) hero.style.setProperty('--ly', dy + 'px'); frame = 0; });
        });
        hero.querySelectorAll('.chat-chip').forEach(card => card.addEventListener('pointermove', e => { const r = card.getBoundingClientRect(); card.style.setProperty('--card-x', (e.clientX-r.left)+'px'); card.style.setProperty('--card-y', (e.clientY-r.top)+'px'); }));
      }
      if (scene) scene.addEventListener('pointermove', e => { if (!reduced) { const r = scene.getBoundingClientRect(); scene.style.setProperty('--mx', (e.clientX-r.left)+'px'); scene.style.setProperty('--my', (e.clientY-r.top)+'px'); } });
      els.feed.querySelectorAll('.chat-chip').forEach(b => b.onclick = () => { els.input.value = b.textContent; resizeInput(); els.input.focus(); });
    }
    if (memory.messages.length || memory.plan) document.documentElement.classList.remove('chat-hero-visible');
    if (!memory.cc) for (const m of memory.messages) {
      if (m.note) { const n = document.createElement('div'); n.innerHTML = noteHtml(m); els.feed.appendChild(n.firstChild); continue; }
      const row = document.createElement('article'); row.className = 'chat-message chat-message-' + (m.who === 'user' ? 'user' : 'chief');
      row.innerHTML = (m.who === 'chief' ? '<span class="chat-avatar" aria-hidden="true">Ş</span>' : '') + '<div class="chat-bubble' + (m.error ? ' chat-error' : '') + '">' + format(toText(m.text)) + '</div>';
      els.feed.appendChild(row);
    }
    if (!memory.cc && (memory.state === 'planning' || memory.state === 'discussing')) addStatus('Şef düşünüyor…');
    if (!memory.cc && memory.state === 'running') addStatus('Görevler çalışıyor…');
    if (!memory.cc && memory.plan) els.feed.appendChild(planCard());
    if (!memory.cc && memory.phase === 'discuss') {
      const bar = document.createElement('section'); bar.className = 'chat-discuss-banner';
      bar.innerHTML = '<span>' + (memory.ready ? '✓ Şef emir vermeye hazır' : 'Şef henüz netleşmeyen noktalar soruyor') + '</span><button type="button" class="btn ' + (memory.ready ? 'primary' : '') + '" data-action="chatStart">' + (memory.ready ? 'Planı çıkar' : 'Yine de planla') + '</button>' + (!memory.ready ? '<small>Planı şimdi çıkarabilirsiniz; belirsiz noktalar eksik kalabilir.</small>' : '');
      els.feed.appendChild(bar);
    }
    if (!memory.cc && memory.state === 'awaiting_tool' && memory.toolQuestion) els.feed.appendChild(toolQuestionCard());
    if (memory.disconnected) { const n = document.createElement('div'); n.className = 'chat-status'; n.innerHTML = 'Bağlantı kesildi. <button type="button" data-action="sync">Yenile</button>'; els.feed.appendChild(n); }
    els.headerBadge.textContent = memory.approval === 'auto' ? 'Onay: otomatik' : memory.approval === 'ask' ? 'Onay: her seferinde' : 'Onay modu';
    const state = ctx.getState() || {}, roles = Array.isArray(state.roles) ? state.roles : Object.entries(state.roles?.roles || state.roles || {}).map(([key,r])=>({...r,key})), chief=roles.find(r=>r.chief), primary=roles.find(r=>r.primary), recipient=chief||primary;
    const recipientText = recipient ? (chief?'Şef: ':'Birincil: ')+recipient.name+(recipient.models?.[0]?' · '+(window.Logos&&Logos.agent(recipient.models[0],16)||'')+' '+esc(recipient.models[0]):'') : state.cfg?.default_tool ? 'Varsayılan: '+(window.Logos&&Logos.agent(state.cfg.default_tool,16)||'')+' '+esc(state.cfg.default_tool)+' <button type="button" class="chat-default-clear" aria-label="Varsayılan aracı temizle">×</button>' : 'Her seferinde sorulur';
    host.querySelectorAll('.chat-recipient').forEach(el=>{el.innerHTML=recipientText;el.querySelector('.chat-default-clear')?.addEventListener('click',async()=>{try{await ctx.api.saveConfig({default_tool:''});state.cfg.default_tool='';render()}catch(e){notify(e)}})});
    els.cwdLabel.textContent = shortPath(memory.cwd || (ctx && ctx.getCwd ? ctx.getCwd() : ''));
    els.busy = memory.busy || memory.state === 'planning' || memory.state === 'discussing' || memory.state === 'running' || memory.state === 'awaiting';
    els.input.disabled = false; els.send.disabled = !els.input.value.trim(); els.send.textContent = memory.busy ? 'Sıraya al' : 'Gönder'; els.send.title = memory.state === 'discussing' ? 'Şef yanıtlıyor' : ''; els.cancel.hidden = !(memory.chatId && (memory.state === 'planning' || memory.state === 'discussing' || memory.state === 'running' || memory.cc && memory.busy));
    els.cancel.setAttribute('aria-label', 'Durdur'); els.cancel.innerHTML = '<svg viewBox="0 0 16 16" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="10" height="10" rx="1"/></svg> Durdur';
    if (memory.changes?.files?.length) els.feed.appendChild(changesCard());
    if (memory.stopped) { const mark = document.createElement('div'); mark.className = 'chat-stopped'; mark.setAttribute('role', 'status'); mark.textContent = 'Durduruldu'; els.feed.appendChild(mark); }
    els.direct.checked = memory.direct;
    const usage = memory.usage;
    if (usage?.manager_real || memory.ccUsage?.usage) { const u = usage.manager_real || memory.ccUsage.usage; const n = v => (Number(v || 0) / 1000).toFixed(1) + 'k'; const input = u.in ?? u.input_tokens, output = u.out ?? u.output_tokens, cache = u.cache_read ?? u.cache_read_input_tokens; const cost = u.cost_usd ?? memory.ccUsage?.cost_usd; els.tokens.hidden = !(input || output || cache || cost); els.tokens.textContent = `Şef: ${n(input)} giriş · ${n(output)} çıkış · önbellek ${n(cache)}${cost ? ' · $' + Number(cost).toFixed(2) : ''}`; }
    else if (usage) { const manager = (usage.manager_in || 0) + (usage.manager_out || 0), worker = (usage.worker_in || 0) + (usage.worker_out || 0), total = memory.estTokens == null ? (manager + worker) / 3.6 : memory.estTokens; els.tokens.hidden = !(total || manager || worker); els.tokens.textContent = `Tahmini token: ~${(total / 1000).toFixed(1)}k · Yönetici ~${(manager / 3.6 / 1000).toFixed(1)}k / İşçi ~${(worker / 3.6 / 1000).toFixed(1)}k`; } else els.tokens.hidden = true;
    const jump = host.querySelector('.chat-jump-bottom');
    if (jump) jump.hidden = nearBottom;
    if (nearBottom) els.feed.scrollTop = els.feed.scrollHeight; else els.feed.scrollTop = priorScrollTop;
    renderHistory();
    wireActions();
  }
  function renderHistory() {
    const list = document.querySelector('.chat-history-list'); if (!list) return;
    const chats = [...((ctx.getState() || {}).chats || [])].sort((a,b) => Number(b.updated||0)-Number(a.updated||0));
    list.innerHTML = chats.map(c => {
      const when = c.updated ? new Date(Number(c.updated)*1000).toLocaleString() : '';
      const active = c.id === memory.chatId;
      const busy = ['planning','discussing','running'].includes(c.state);
      return '<div class="chat-history-row"><button type="button" class="chat-history-item" data-chat="'+esc(c.id)+'" aria-current="'+(active?'page':'false')+'"><i class="chat-state-dot '+(busy?'is-running':'')+'" aria-label="'+(busy?'Çalışıyor':'Bitti')+'"></i><span><strong>'+esc(c.title||'Sohbet')+'</strong><small>'+esc(when)+' · '+(busy?'Çalışıyor':'Bitti')+'</small></span></button><button type="button" class="chat-history-delete" data-delete-chat="'+esc(c.id)+'" aria-label="Sohbeti sil"><svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 4h10M6 4V2.5h4V4m2 0-.6 9H4.6L4 4m2.5 2v5m3-5v5"/></svg></button></div>';
    }).join('');
    list.querySelectorAll('[data-chat]').forEach((b,i,all)=>{
      b.onclick=()=>selectChat(b.dataset.chat);
      b.ondblclick=async()=>{const current=chats.find(c=>c.id===b.dataset.chat);const title=prompt('Sohbet başlığı',current?.title||'');if(title?.trim()){await ctx.api.chatRename(b.dataset.chat,title.trim());await ctx.refresh();renderHistory();}};
      b.onkeydown=e=>{if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();all[(i+(e.key==='ArrowDown'?1:-1)+all.length)%all.length]?.focus();}};
    });
    list.querySelectorAll('[data-delete-chat]').forEach(b=>b.onclick=async()=>{if(!confirm('Bu sohbet silinsin mi?'))return;await ctx.api.chatDelete(b.dataset.deleteChat);if(memory.chatId===b.dataset.deleteChat)newChat();await ctx.refresh();renderHistory();});
  }
  async function selectChat(id) { memory.chatId=id; memory.queue=[]; memory.messages=[];memory.changes=null;memory.diffOpen={};memory.chgSel=null; memory.plan=null;memory.tasks={};memory.ccTools=[];memory.ccTasks=[];memory.ccLive='';memory.ccThinking='';memory.toolQuestion=null;memory.selectedTool=null;memory.state='idle';await sync(); }
  function newChat() { memory.chatId=null;memory.queue=[];memory.messages=[];memory.changes=null;memory.diffOpen={};memory.chgSel=null;memory.plan=null;memory.tasks={};memory.phase='';memory.ready=false;memory.state='idle';memory.busy=false;memory.cc=false;memory.toolQuestion=null;memory.selectedTool=null;memory.ccTools=[];memory.ccTasks=[];memory.ccLive='';memory.ccThinking='';memory.ccQuestion='';memory.ccLimit='';render();els.input.focus(); }
  function addStatus(text) { const n = document.createElement('div'); n.className = 'chat-status'; n.setAttribute('role', 'status'); n.textContent = text; els.feed.appendChild(n); }
  function shortPath(p) { p = String(p || 'Klasör seçilmedi'); return p.length > 58 ? '…' + p.slice(-55) : p; }
  function planCard() {
    const p = memory.plan, card = document.createElement('section'); card.className = 'chat-plan card';
    const tasks = p.tasks || [], completed = tasks.filter(t => ['ok', 'error', 'skipped', 'cancelled', 'limit', 'timeout', 'suspicious'].includes((memory.tasks[t.id] || {}).status)).length;
    const roles = (ctx.getState() || {}).roles || [];
    const roleMap = Array.isArray(roles) ? roles.reduce((a, r) => (a[r.key] = r, a), {}) : (roles.roles || roles);
    let html = '<div class="chat-plan-head"><div><span class="chat-eyebrow">ŞEF PLANI</span><h2>' + format(p.summary || 'Plan hazır.') + '</h2></div><button type="button" class="chat-link" data-action="sync">Yenile</button></div>';
    if (tasks.some(t => t.write)) html += '<div class="chat-write-warning">▲ Bu plan dosya değiştirebilir.</div>';
    if (memory.state === 'running' || memory.state === 'done') html += '<div class="chat-progress" aria-label="İlerleme"><span style="width:' + (tasks.length ? Math.round(completed / tasks.length * 100) : 0) + '%"></span></div><div class="chat-progress-label">' + completed + '/' + tasks.length + ' görev tamamlandı</div>';
    html += '<div class="chat-task-list">';
    for (const t of tasks) {
      const st = memory.tasks[t.id] || {}, status = st.status || 'waiting', icon = ({ waiting: '○', running: '◐', ok: '✔', error: '✖', timeout: '✖', suspicious: '✖', limit: '▲', cancelled: '■', skipped: '⤼' })[status] || '○';
      const role = roleMap[t.role] || {}, checked = !memory.drops || !memory.drops.has(t.id);
      const roleColor = /^#[\da-f]{3,8}$/i.test(role.color || '') ? role.color : '';
      html += '<article class="chat-task chat-state-' + esc(status) + '"><div class="chat-task-top"><span class="chat-task-status" aria-label="' + esc(status) + '">' + icon + '</span><strong' + (roleColor ? ' style="color:' + roleColor + '"' : '') + '>' + esc(role.name || t.role) + '</strong>' + (t.write ? '<span class="chat-write-badge">Yazma</span>' : '') + '<span class="chat-task-id">' + esc(t.id) + '</span></div>';
      if (memory.state === 'awaiting' && !memory.auto) html += '<label class="chat-task-include"><input type="checkbox" data-task="' + esc(t.id) + '" ' + (checked ? 'checked' : '') + '> Dahil et</label>';
      html += '<div class="chat-instruction" data-short="' + esc(t.id) + '">' + format(t.instruction) + '</div><button type="button" class="chat-link" data-action="expand" data-id="' + esc(t.id) + '">devamı</button>';
      if (t.depends_on && t.depends_on.length) html += '<div class="chat-deps">Bağımlılık: ' + t.depends_on.map(d => '← ' + esc(d)).join(' ') + '</div>';
      if (st.fallback) html += '<div class="chat-fallback" role="status">' + (window.Logos && Logos.agent(st.fallback.from,16) || '') + '<span>' + esc(st.fallback.from) + ' yerine</span>' + (window.Logos && Logos.agent(st.fallback.to,16) || '') + '<span>' + esc(st.fallback.to) + ' çalıştı</span></div>';
      if (st.run) html += '<button type="button" class="chat-link" data-action="run" data-run="' + esc(st.run) + '">Çıktıyı aç</button>';
      html += '</article>';
    }
    html += '</div>';
    if (memory.state === 'awaiting') html += memory.auto ? '<p class="chat-auto-note">Otomatik onaylandı.</p>' : '<div class="chat-plan-actions">' + button('Onayla ve çalıştır', 'primary', 'approve', false) + button('Reddet', 'danger', 'reject', false) + '</div>';
    card.innerHTML = html;
    card.querySelectorAll('.chat-instruction').forEach(el => { const full = (tasks.find(t => t.id === el.dataset.short) || {}).instruction || ''; el.classList.add('chat-clamped'); el.dataset.full = full; });
    return card;
  }
  function toolQuestionCard() {
    const q = memory.toolQuestion || { options: memory.selectedTool?.options || [] }, card = document.createElement('section'); card.className = 'chat-tool-card';
    const tools = q.options || [], selected = memory.selectedTool;
    card.innerHTML = '<h2>Bu işi hangi araçla yapayım?</h2>' + (selected ? '<p>Seçim: ' + esc(selected.label) + '</p>' : '<div class="chat-tool-options">' + tools.map(t => '<button type="button" class="chat-tool-option" data-tool="' + esc(t.key) + '" aria-pressed="false">' + (window.Logos && Logos.agent(t.key,22) || '') + '<span>' + esc(t.label) + '</span></button>').join('') + '</div><label class="chat-tool-remember"><input type="checkbox" data-remember> Bundan sonra hep bunu kullan</label>') + (selected ? '' : '<div class="chat-model-picker" hidden><label for="chat-model-search">OpenCode modeli ara</label><input id="chat-model-search" type="search" placeholder="Model ara"><div class="chat-model-list" role="listbox"></div></div>');
    if (selected) { const p=card.querySelector('p'); if(p){p.innerHTML='Seçim: '+(window.Logos&&Logos.agent(selected.key,22)||'')+' <strong>'+esc(selected.label)+(selected.model?' · '+esc(selected.model):'')+'</strong>';p.classList.add('chat-tool-selection');} const status=document.createElement('p');status.setAttribute('role','status');status.textContent='İş başlıyor…';card.appendChild(status); }
    const list = card.querySelector('.chat-model-list'), search = card.querySelector('#chat-model-search');
    function fillModels(term='') { if (!list) return; const items = (tools.find(t=>t.key==='opencode')||{}).models||[]; list.innerHTML=items.filter(m=>String(typeof m==='string'?m:m.key||m.model_id||m.name).toLowerCase().includes(term.toLowerCase())).map(m=>{const key=typeof m==='string'?m:(m.key||m.model_id||m.name);return '<button type="button" role="option" data-model="'+esc(key)+'">'+esc(key)+'</button>'}).join('');list.querySelectorAll('[data-model]').forEach(b=>b.onclick=()=>choose('opencode',b.dataset.model)); }
    fillModels(); search?.addEventListener('input',()=>fillModels(search.value));
    card.querySelectorAll('[data-tool]').forEach(b=>b.onclick=()=>{const key=b.dataset.tool;if(key==='opencode'){card.querySelector('.chat-model-picker').hidden=false;search.focus()}else choose(key)});
    function choose(key,model){card.querySelectorAll('button').forEach(b=>b.disabled=true);card.setAttribute('aria-busy','true');card._choose?.(key,model)}
    card._choose = async (key,model) => { try { const remember=!!card.querySelector('[data-remember]')?.checked; await ctx.api.chatTool(memory.chatId,key,model,remember); memory.selectedTool={key,label:(tools.find(t=>t.key===key)||{}).label||key,model,options:tools}; memory.toolQuestion=null; memory.state='planning'; render(); } catch(e) { card.removeAttribute('aria-busy'); card.querySelectorAll('button').forEach(b=>b.disabled=false); notify(e); } };
    return card;
  }
  function wireActions() {
    host.querySelectorAll('[data-action]').forEach(b => { b.onclick = async () => {
      try {
        const a = b.dataset.action;
        if (a === 'send') { if (!memory.approval) showApproval(); else send(); }
        if (a === 'approve') { const drop = Array.from(host.querySelectorAll('[data-task]:not(:checked)')).map(x => x.dataset.task); memory.drops = new Set(drop); await ctx.api.chatApprove(memory.chatId, drop, memory.cwd); memory.state = 'running'; render(); }
        if (a === 'reject') { await ctx.api.chatReject(memory.chatId); memory.state = 'idle'; memory.plan = null; render(); }
        if (a === 'cancel') { await ctx.api.chatCancel(memory.chatId); if (memory.ccLive) memory.messages.push({ who: 'chief', text: memory.ccLive }); memory.state = 'idle'; memory.busy = false; memory.stopped = true; memory.ccLive = ''; memory.ccThinking = ''; render(); }
        if (a === 'sync') await sync();
        if (a === 'expand') { const el = host.querySelector('[data-short="' + CSS.escape(b.dataset.id) + '"]'); if (el) { el.classList.toggle('chat-clamped'); b.textContent = el.classList.contains('chat-clamped') ? 'devamı' : 'daralt'; } }
        if (a === 'run' && ctx.openRun) ctx.openRun(b.dataset.run);
        if (a === 'approval') showApproval();
        if (a === 'chatStart') { await ctx.api.chatStart(memory.chatId, memory.cwd); memory.phase = 'plan'; memory.state = 'planning'; memory.busy = true; render(); }
        if (a === 'cwd') editCwd();
        if (a === 'answer') { const answer = host.querySelector('.cc-question textarea')?.value.trim(); if (answer) { memory.messages.push({ who: 'user', text: answer }); memory.ccQuestion = ''; memory.busy = true; await ctx.api.chatMessage(memory.chatId, answer, memory.cwd, [], false); render(); } }
      } catch (e) { notify(e); }
    }; });
  }
  function resizeInput() { if (!els) return; els.input.style.height = 'auto'; els.input.style.height = Math.min(els.input.scrollHeight, 200) + 'px'; els.send.disabled = !els.input.value.trim(); }
  function showApproval() {
    const modal = document.createElement('div'); modal.className = 'chat-modal-backdrop'; modal.innerHTML = '<section class="chat-modal" role="dialog" aria-modal="true" aria-labelledby="chat-approval-title"><h2 id="chat-approval-title">Plan onayı</h2><p>Planları otomatik onaylayayım mı, yoksa her seferinde sana mı sorayım? Planlar yazma izinli görevler içerebilir.</p><div class="chat-modal-options"><button class="btn primary" data-mode="auto">Otomatik onayla</button><button class="btn" data-mode="ask">Her seferinde sor</button></div></section>';
    host.appendChild(modal); modal.querySelectorAll('[data-mode]').forEach(b => b.onclick = async () => { try { memory.approval = b.dataset.mode; await ctx.api.saveConfig({ plan_approval: memory.approval }); modal.remove(); render(); await send(); } catch (e) { notify(e); } }); modal.querySelector('[data-mode="auto"]').focus();
  }
  function editCwd() { const value = prompt('Çalışma klasörü', memory.cwd); if (value != null) { memory.cwd = value.trim(); render(); } }
  async function send() {
    if (!memory.approval) { showApproval(); return; }
    const message = els.input.value.trim(); if (!message) return;
    if (memory.ccQuestion && memory.chatId) { memory.ccQuestion = ''; memory.messages.push({ who: 'user', text: message }); els.input.value = ''; resizeInput(); render(); try { await ctx.api.chatMessage(memory.chatId, message, memory.cwd, [], false); } catch (e) { notify(e); } return; }
    if (memory.busy || ['planning', 'discussing', 'running'].includes(memory.state)) { (memory.queue = memory.queue || []).push(message); els.input.value = ''; resizeInput(); renderQueue(); notify('Sıraya alındı; şef boşalınca gönderilecek'); return; }
    memory.cwd = els.cwdEdit.value.trim() || memory.cwd || (ctx.getCwd ? ctx.getCwd() : '');
    const priorChat = memory.chatId; memory.messages.push({ who: 'user', text: message }); memory.state = memory.direct ? 'planning' : 'discussing'; memory.busy = true; els.input.value = ''; resizeInput(); render();
    try { if (memory.ccMode !== 'default' && ctx.api.chatMode) await ctx.api.chatMode(priorChat, memory.ccMode); const res = ctx.api.chatMessage ? await ctx.api.chatMessage(priorChat, message, memory.cwd, [], memory.direct) : await ctx.api.chatSend({ chat: priorChat, text: message, message, cwd: memory.cwd, files: [], direct: memory.direct }); if (res && res.chat) memory.chatId = res.chat; }
    catch (e) { memory.messages.pop(); memory.state = 'idle'; memory.busy = false; notify(e); render(); }
  }
  async function sync() {
    if (!memory.chatId || !ctx.api.chatGet) return;
    try { const d = await ctx.api.chatGet(memory.chatId); const c = d.chat || d; memory.state = c.state || 'idle'; memory.phase = c.phase || memory.phase; memory.cc = !!(c.cc_session_id || c.phase === 'cc' || c.phase === 'claude' || c.runtime === 'claude'); if (memory.cc) memory.toolQuestion = null; memory.ccMode = c.cc_mode || c.mode || memory.ccMode; memory.ccUsage = c.cc_result || memory.ccUsage; memory.ready = !!c.ready; memory.usage = c.usage || memory.usage; memory.estTokens = c.est_tokens ?? memory.estTokens; memory.plan = c.plan || memory.plan; memory.tasks = c.tasks || memory.tasks; memory.ccTools = c.tools || c.tool_summaries || (c.messages || []).filter(m=>m.who==='araç').map(m=>({name:m.name,input:m.input,ok:m.ok,status:'done'})); memory.messages = (c.messages || []).filter(m=>m.who!=='araç').map(m => ({ who: /kullanıcı|user/i.test(m.who) ? 'user' : 'chief', text: m.text, tools: m.tools })); memory.busy = ['planning', 'discussing', 'running', 'awaiting', 'awaiting_user'].includes(memory.state); memory.disconnected = false; memory.changes = (c.changes || []).length ? { files: c.changes, applied: c.applied || [], branch: c.workspace?.branch || '' } : null; render(); }
    catch (e) { notify(e); }
  }
  function mount(container, context) {
    host = container; ctx = context; if (!memory.cwd && ctx.getCwd) memory.cwd = ctx.getCwd() || '';
    memory.approval = ((ctx.getState() || {}).cfg || {}).plan_approval || memory.approval;
    host.innerHTML = '<section class="chat-shell"><header class="chat-header"><div><span class="chat-eyebrow">COMPADE · OFİS SOHBETİ</span><h1>Bir iş anlat</h1><div class="chat-recipient"></div></div><button type="button" class="chat-badge" data-action="approval"></button></header><nav class="chat-history" aria-label="Sohbet geçmişi"><button type="button" class="btn chat-new" data-new-chat>Yeni sohbet</button><div class="chat-history-list" role="list"></div></nav><div class="chat-feed" aria-live="polite" aria-relevant="additions text" role="log"></div><button type="button" class="chat-jump-bottom" aria-label="En alta git" hidden><svg viewBox="0 0 16 16" aria-hidden="true"><path d="m3 6 5 5 5-5"/></svg> En alta</button><section class="chat-composer"><div class="chat-cwd-row"><span>Çalışma klasörü</span><button type="button" class="chat-link" data-action="cwd"><span class="chat-cwd-label"></span> · değiştir</button><span class="chat-recipient"></span><input class="chat-cwd-edit" aria-label="Çalışma klasörü" hidden></div><div class="chat-queue" hidden></div><textarea class="chat-input" aria-label="Mesaj" rows="3" placeholder="Şefe yaz… (Enter gönderir, Shift+Enter yeni satır)"></textarea><div class="chat-compose-actions"><span class="chat-hint">Enter gönderir · Shift+Enter yeni satır</span><div class="tpl-wrap"><button type="button" class="btn tpl-btn" aria-haspopup="true" aria-expanded="false" title="Hazır iş şablonları">Şablon</button><div class="tpl-menu" role="menu" hidden></div></div><span class="chat-spacer"></span><label class="chat-direct" title="Şefle konuşmayı atlayıp doğrudan plan çıkar"><input type="checkbox" class="chat-direct-toggle"> Direkt yap</label><label class="cc-mode-label">İzin modu <select class="cc-mode" aria-label="İzin modu"><option value="plan">Plan (salt okunur)</option><option value="acceptEdits">Düzenleme onaylı</option><option value="default" selected>Varsayılan</option></select></label><button type="button" class="btn danger" data-action="cancel" hidden>Durdur</button><button type="button" class="btn primary" data-action="send">Gönder</button></div><div class="cc-readonly-hint" hidden>Plan modu salt okunurdur; dosya değişikliği için başka izin modu seçin.</div><div class="chat-token-count" hidden title="Tahmindir; gerçek sağlayıcı token sayısı değil."></div></section></section>';
    const historyToggle=document.createElement('button');historyToggle.type='button';historyToggle.className='chat-history-toggle';historyToggle.textContent='Sohbetler';historyToggle.setAttribute('aria-expanded','true');host.querySelector('.chat-history').prepend(historyToggle);historyToggle.onclick=()=>{const nav=historyToggle.closest('.chat-history');nav.classList.toggle('is-collapsed');historyToggle.setAttribute('aria-expanded',String(!nav.classList.contains('is-collapsed')));};
    const sidebar=document.querySelector('#sidebar'); if(sidebar) sidebar.insertBefore(host.querySelector('.chat-history'),sidebar.querySelector('#activityPanel'));
    els = { feed: host.querySelector('.chat-feed'), input: host.querySelector('.chat-input'), send: host.querySelector('[data-action="send"]'), cancel: host.querySelector('[data-action="cancel"]'), headerBadge: host.querySelector('.chat-badge'), cwdLabel: host.querySelector('.chat-cwd-label'), cwdEdit: host.querySelector('.chat-cwd-edit'), direct: host.querySelector('.chat-direct-toggle'), tokens: host.querySelector('.chat-token-count') };
    (document.querySelector('[data-new-chat]')||host.querySelector('[data-new-chat]')).onclick=newChat;
    host.querySelector('.chat-jump-bottom').onclick=()=>{els.feed.scrollTop=els.feed.scrollHeight;render();};
    els.feed.addEventListener('scroll',()=>{const b=host.querySelector('.chat-jump-bottom');if(b)b.hidden=els.feed.scrollHeight-els.feed.scrollTop-els.feed.clientHeight<=80;},{passive:true});
    els.direct.onchange = () => { memory.direct = els.direct.checked; };
    wireTemplates(); renderQueue();
    const modeSelect = host.querySelector('.cc-mode'); modeSelect.value = memory.ccMode; host.querySelector('.cc-readonly-hint').hidden = memory.ccMode !== 'plan'; modeSelect.addEventListener('change', () => { memory.ccMode = modeSelect.value; host.querySelector('.cc-readonly-hint').hidden = memory.ccMode !== 'plan'; });
    els.input.addEventListener('input', resizeInput); els.input.addEventListener('keydown', e => { if (e.key === 'Escape' && !els.cancel.hidden) { e.preventDefault(); els.cancel.click(); } if (e.key === 'Enter' && !e.shiftKey && !e.isComposing && !e.nativeEvent?.isComposing) { e.preventDefault(); send(); } });
    document.documentElement.classList.toggle('chat-hero-paused', document.hidden);
    document.addEventListener('visibilitychange', onVisibilityChange);
    els.send.onclick = () => { if (!memory.approval) showApproval(); else send(); };
    els.cwdEdit.addEventListener('change', () => { memory.cwd = els.cwdEdit.value; els.cwdEdit.hidden = true; render(); });
    host.querySelector('[data-action="cwd"]').onclick = () => { els.cwdEdit.hidden = false; els.cwdEdit.value = memory.cwd; els.cwdEdit.focus(); };
    render();
    const state = ctx.getState() || {}; const chat = state.cc_session_id || state.chat?.cc_session_id || state.chat?.id;
    if (chat && !memory.chatId) { memory.chatId = chat; memory.cc = true; sync(); }
  }
  function onVisibilityChange() { document.documentElement.classList.toggle('chat-hero-paused', document.hidden); }

  const NOTE_KINDS = ['decision_start', 'chief_decision', 'decision_limit', 'decision_error', 'workspace_ready', 'workspace_off', 'workspace_error', 'verify_start', 'verify_result', 'task_merged', 'merge_conflict', 'changes_ready', 'changes_applied', 'changes_discarded', 'route'];
  function note(text, warn) { memory.messages.push({ who: 'chief', note: true, error: !!warn, text }); }
  function noteEvent(e) {
    const k = e.kind, tk = e.task || '';
    if (k === 'decision_start') note('Şef, ' + (tk || 'görev') + ' raporunu değerlendiriyor (' + ({ blocked: 'takıldı', failed: 'başarısız', needs_input: 'bilgi istiyor' }[e.status] || e.status || '') + ')…');
    else if (k === 'chief_decision') { const label = { retry: 'Yeniden dene', reassign: 'Başka role ver' + (e.role ? ' → ' + e.role : ''), ask_user: 'Sana soruyor', abort: 'Planı durdur', continue: 'Atla, devam et' }[e.action] || e.action; note('Şef kararı (' + tk + '): ' + label + (e.message && e.action !== 'ask_user' ? ' — ' + toText(e.message) : '')); }
    else if (k === 'decision_limit') note('Yeniden deneme hakkı doldu (' + tk + '). Görev olduğu gibi bırakıldı.', true);
    else if (k === 'decision_error') note('Şef kararı uygulanamadı: ' + toText(e.error), true);
    else if (k === 'workspace_ready') note('Yalıtılmış çalışma dalı açıldı: ' + (e.branch || '') + '. Roller senin klasörüne doğrudan yazmayacak.');
    else if (k === 'workspace_off') note(toText(e.reason) || 'Yalıtım kapalı; roller doğrudan klasöre yazar.', true);
    else if (k === 'workspace_error') note('Çalışma dalı hatası: ' + toText(e.error), true);
    else if (k === 'verify_start') note('Doğrulama çalışıyor (' + tk + '): ' + (e.cmd || ''));
    else if (k === 'verify_result') note(e.ok ? 'Doğrulama geçti (' + tk + ').' : 'Doğrulama başarısız (' + tk + '): ' + toText(e.tail).slice(-300), !e.ok);
    else if (k === 'task_merged') note('Birleştirildi (' + tk + '): ' + (e.files || []).length + ' dosya.');
    else if (k === 'merge_conflict') note('Birleştirme çakışması (' + tk + '): ' + (e.files || []).join(', '), true);
    else if (k === 'changes_ready') { memory.changes = { files: e.files || [], applied: [], branch: e.branch || '' }; memory.chgSel = new Set((e.files || []).map(f => f.path)); }
    else if (k === 'changes_applied') { if (memory.changes) memory.changes.applied = [...new Set([...(memory.changes.applied || []), ...(e.files || [])])]; note((e.files || []).length + ' dosya klasörüne uygulandı' + (e.mode === '3yollu' ? ' (senin değişikliklerinle birleştirildi)' : '') + '.'); }
    else if (k === 'route') note('Model seçimi (' + tk + '): ' + (e.model || '') + (e.effort ? ' · düşünme ' + ({ low: 'düşük', medium: 'orta', high: 'yüksek' }[e.effort] || e.effort) : '') + ' — ' + toText(e.reason));
    else if (k === 'changes_discarded') { memory.changes = null; note('Değişiklikler atıldı, çalışma dalı silindi.'); }
  }
  function noteHtml(m) { return '<div class="cc-note' + (m.error ? ' cc-note-warn' : '') + '"><svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><path d="M8 2v4l3 2"/><circle cx="8" cy="8" r="6"/></svg><span>' + esc(toText(m.text)) + '</span></div>'; }
  function diffHtml(text) {
    return toText(text).split('\n').filter(l => !/^(diff --git|index |--- |\+\+\+ )/.test(l)).map(l => {
      const c = l.startsWith('@@') ? 'dh' : l.startsWith('+') ? 'da' : l.startsWith('-') ? 'dd' : '';
      return '<div class="' + c + '">' + (esc(l) || '&nbsp;') + '</div>';
    }).join('');
  }
  function changesCard() {
    const ch = memory.changes, files = ch.files || [], applied = new Set(ch.applied || []);
    memory.chgSel = memory.chgSel || new Set(files.map(f => f.path));
    memory.diffOpen = memory.diffOpen || {};
    const pending = files.filter(f => !applied.has(f.path));
    const add = files.reduce((a, f) => a + (f.add || 0), 0), del = files.reduce((a, f) => a + (f.del || 0), 0);
    const card = document.createElement('section'); card.className = 'chg-card'; card.setAttribute('aria-label', 'Değişiklikler');
    const badge = { added: ['A', 'Yeni'], deleted: ['D', 'Silindi'], renamed: ['R', 'Taşındı'], modified: ['M', 'Değişti'] };
    card.innerHTML = '<header><div><strong>Değişiklikler</strong><span class="chg-meta">' + files.length + ' dosya · <b class="chg-add">+' + add + '</b> <b class="chg-del">−' + del + '</b>' + (ch.branch ? ' · <code>' + esc(ch.branch) + '</code>' : '') + '</span></div>'
      + '<p>Roller bu değişiklikleri ayrı bir dalda yaptı; senin klasörüne henüz dokunulmadı. İncele, seç, uygula.</p></header>'
      + '<ul>' + files.map(f => { const b = badge[f.status] || badge.modified, done = applied.has(f.path), open = memory.diffOpen[f.path];
        return '<li class="' + (done ? 'chg-done' : '') + '"><div class="chg-row">'
          + '<input type="checkbox" aria-label="' + esc(f.path) + ' seç" data-chg-sel="' + esc(f.path) + '"' + (done ? ' disabled checked' : memory.chgSel.has(f.path) ? ' checked' : '') + '>'
          + '<span class="chg-badge chg-' + esc(f.status || 'modified') + '" title="' + b[1] + '">' + b[0] + '</span>'
          + '<button type="button" class="chg-path" data-chg-diff="' + esc(f.path) + '" aria-expanded="' + (open ? 'true' : 'false') + '">' + esc(f.path) + '</button>'
          + (f.binary ? '<span class="chg-meta">ikili</span>' : '<span class="chg-num"><b class="chg-add">+' + (f.add || 0) + '</b> <b class="chg-del">−' + (f.del || 0) + '</b></span>')
          + (done ? '<span class="chg-ok">Uygulandı</span>' : '') + '</div>'
          + (open ? '<pre class="chg-diff">' + (open === '…' ? '<div class="dh">Yükleniyor…</div>' : diffHtml(open)) + '</pre>' : '') + '</li>'; }).join('') + '</ul>'
      + (pending.length ? '<footer><button type="button" class="chg-primary" data-chg="apply">Seçilenleri uygula (' + pending.filter(f => memory.chgSel.has(f.path)).length + ')</button><button type="button" data-chg="all">Hepsini uygula</button><button type="button" class="chg-danger" data-chg="discard">Hepsini at</button></footer>' : '');
    card.querySelectorAll('[data-chg-sel]').forEach(x => x.onchange = () => { x.checked ? memory.chgSel.add(x.dataset.chgSel) : memory.chgSel.delete(x.dataset.chgSel); render(); });
    card.querySelectorAll('[data-chg-diff]').forEach(x => x.onclick = async () => {
      const path = x.dataset.chgDiff;
      if (memory.diffOpen[path]) { delete memory.diffOpen[path]; render(); return; }
      memory.diffOpen[path] = '…'; render();
      try { const r = await ctx.api.chatDiff(memory.chatId, path); memory.diffOpen[path] = r.diff || '(fark yok)'; } catch (e) { delete memory.diffOpen[path]; notify(e); }
      render();
    });
    card.querySelectorAll('[data-chg]').forEach(x => x.onclick = async () => {
      const a = x.dataset.chg;
      try {
        if (a === 'discard') { if (!confirm('Bu sohbetin tüm değişiklikleri ve çalışma dalı silinsin mi? Geri alınamaz.')) return; await ctx.api.chatDiscard(memory.chatId); return; }
        const paths = a === 'all' ? pending.map(f => f.path) : pending.map(f => f.path).filter(p => memory.chgSel.has(p));
        if (!paths.length) { notify('Dosya seçilmedi'); return; }
        card.querySelectorAll('button').forEach(b => b.disabled = true);
        const r = await ctx.api.chatApply(memory.chatId, paths);
        if (!r.ok) { note('Uygulanamadı: ' + toText(r.error) + (r.conflicts?.length ? ' (çakışan: ' + r.conflicts.join(', ') + ')' : ''), true); render(); }
      } catch (e) { notify(e); render(); }
    });
    return card;
  }

  const TEMPLATES = [
    { name: 'Hata düzelt', text: 'Hata: <ne oluyor>\nBeklenen: <ne olmalı>\nNasıl tekrarlanır: <adımlar>\nİlgili dosya / hata çıktısı: <yol veya log>\n\nKök nedeni bul, düzelt ve testle doğrula. Yalnız gereken dosyalara dokun.' },
    { name: 'Özellik ekle', text: 'Özellik: <ne eklenecek>\nNerede: <sayfa / modül>\nKabul ölçütleri:\n- <ölçüt 1>\n- <ölçüt 2>\n\nMevcut yapıya uy, test ekle.' },
    { name: 'Kod incelemesi', text: 'Şunu incele: <klasör / dosyalar / son değişiklikler>\nHata, güvenlik açığı, gereksiz karmaşıklık ve eksik testleri önem sırasıyla listele; her biri için dosya:satır ve kısa öneri. Dosya değiştirme.' },
    { name: 'Test yaz', text: 'Şunun için test yaz: <modül / fonksiyon>\nKapsam: normal akış, sınır durumları, hata durumları. Projenin mevcut test aracını kullan; testleri çalıştırıp geçtiğini göster.' },
    { name: 'Yeniden düzenle', text: 'Yeniden düzenle: <dosya / modül>\nAmaç: <okunabilirlik / tekrarı azaltma / bölme>\nDavranış DEĞİŞMESİN; önce ve sonra testler geçmeli.' },
    { name: 'Doküman yaz', text: 'Doküman: <README / API / kurulum>\nKimin için: <geliştirici / kullanıcı>\nKısa, örnekli, Türkçe yaz; koddan doğrula, uydurma.' },
    { name: 'Proje hafızası (COMPADE.md)', text: 'Projeyi incele ve köke COMPADE.md yaz (en çok 60 satır): ne iş yaptığı, kurulum ve çalıştırma, test komutu, klasör yapısı, kod kuralları, dikkat edilecek tuzaklar. Ekip her işte bu dosyayı okuyacak.' },
  ];
  function userTemplates() { try { return JSON.parse(localStorage.getItem('compade-templates') || '[]'); } catch (_) { return []; } }
  function saveUserTemplates(list) { try { localStorage.setItem('compade-templates', JSON.stringify(list.slice(0, 30))); } catch (_) {} }
  function insertTemplate(text) {
    els.input.value = text; resizeInput(); els.input.focus();
    const i = text.indexOf('<'), j = text.indexOf('>', i);
    if (i >= 0 && j > i) els.input.setSelectionRange(i, j + 1);
  }
  function wireTemplates() {
    const btn = host.querySelector('.tpl-btn'), menu = host.querySelector('.tpl-menu');
    const close = () => { menu.hidden = true; btn.setAttribute('aria-expanded', 'false'); };
    const fill = () => {
      const mine = userTemplates();
      menu.innerHTML = TEMPLATES.map((t, i) => '<button type="button" role="menuitem" data-tpl="' + i + '">' + esc(t.name) + '</button>').join('')
        + (mine.length ? '<div class="tpl-sep">Benim şablonlarım</div>' + mine.map((t, i) => '<div class="tpl-mine"><button type="button" role="menuitem" data-mine="' + i + '">' + esc(t.name) + '</button><button type="button" class="tpl-del" data-del="' + i + '" aria-label="' + esc(t.name) + ' şablonunu sil" title="Sil">×</button></div>').join('') : '')
        + '<div class="tpl-sep"></div><button type="button" role="menuitem" data-save' + (els.input.value.trim() ? '' : ' disabled') + '>Yazdığımı şablon olarak kaydet</button>';
      menu.querySelectorAll('[data-tpl]').forEach(b => b.onclick = () => { close(); insertTemplate(TEMPLATES[+b.dataset.tpl].text); });
      menu.querySelectorAll('[data-mine]').forEach(b => b.onclick = () => { close(); insertTemplate(userTemplates()[+b.dataset.mine].text); });
      menu.querySelectorAll('[data-del]').forEach(b => b.onclick = e => { e.stopPropagation(); const l = userTemplates(); l.splice(+b.dataset.del, 1); saveUserTemplates(l); fill(); });
      const save = menu.querySelector('[data-save]');
      if (save) save.onclick = () => { const text = els.input.value.trim(); if (!text) return; const name = prompt('Şablon adı', text.split('\n')[0].slice(0, 40)); if (!name) return; saveUserTemplates([{ name: name.trim().slice(0, 50), text }, ...userTemplates()]); close(); notify('Şablon kaydedildi'); };
    };
    btn.onclick = e => { e.stopPropagation(); if (!menu.hidden) return close(); fill(); menu.hidden = false; const r = btn.getBoundingClientRect(); menu.style.left = Math.max(8, Math.min(innerWidth - menu.offsetWidth - 8, r.left)) + 'px'; menu.style.bottom = (innerHeight - r.top + 6) + 'px'; btn.setAttribute('aria-expanded', 'true'); menu.querySelector('button')?.focus(); };
    menu.addEventListener('keydown', e => { if (e.key === 'Escape') { close(); btn.focus(); } });
    document.addEventListener('click', e => { if (!menu.hidden && !e.target.closest('.tpl-wrap')) close(); });
  }
  function renderQueue() {
    const q = host && host.querySelector('.chat-queue'); if (!q) return;
    const list = memory.queue || [];
    q.hidden = !list.length;
    q.innerHTML = list.length ? '<span class="chat-queue-label">Sırada ' + list.length + '</span>' + list.map((m, i) => '<span class="chat-queue-item" title="' + esc(m) + '">' + esc(m.length > 60 ? m.slice(0, 60) + '…' : m) + '<button type="button" data-unqueue="' + i + '" aria-label="Sıradan çıkar">×</button></span>').join('') : '';
    q.querySelectorAll('[data-unqueue]').forEach(b => b.onclick = () => { memory.queue.splice(+b.dataset.unqueue, 1); renderQueue(); });
  }
  function drainQueue() {
    if (!els || !memory.queue?.length || memory.busy || ['planning', 'discussing', 'running', 'awaiting', 'awaiting_user'].includes(memory.state) || memory.ccQuestion) return;
    const next = memory.queue.shift(); renderQueue();
    els.input.value = next; resizeInput(); send();
  }
  function handleEvent(e) {
    if (!e || !e.kind || (memory.chatId && e.chat && e.chat !== memory.chatId)) return;
    if (e.chat && !memory.chatId) memory.chatId = e.chat;
    const d = e;
    const key = [e.chat, e.kind, e.id, e.msg, e.delta, e.status, e.text, e.question, e.error, e.session_id, e.task, e.action, e.message, e.summary, e.ok, e.cmd, e.model, e.effort, e.files && JSON.stringify(e.files), e.plan && JSON.stringify(e.plan)].join(':');
    if (memory.seen.has(key)) return; memory.seen.add(key);
    if (['cc_result', 'cc_error', 'discuss_reply', 'discuss_error', 'chat_done', 'plan_error', 'plan_question'].includes(e.kind)) setTimeout(drainQueue, 400);
    if (NOTE_KINDS.includes(e.kind)) { noteEvent(e); render(); return; }
    if (e.kind.startsWith('cc_') || ['task_report', 'ask_user'].includes(e.kind)) {
      memory.cc = true;
      if (e.kind === 'cc_start') { memory.ccSessionId = e.session_id; memory.busy = true; memory.ccLive = ''; memory.ccThinking = ''; }
      else if (e.kind === 'cc_text') { const delta=toText(e.delta);memory.ccLive += delta;memory.busy = true;let live=els.feed.querySelector('.cc-live-delta');if(!live){live=document.createElement('div');live.className='cc-assistant cc-live-delta';els.feed.appendChild(live);}live.appendChild(document.createTextNode(delta));if(els.feed.scrollHeight-els.feed.scrollTop-els.feed.clientHeight<=80)els.feed.scrollTop=els.feed.scrollHeight;return; }
      else if (e.kind === 'cc_thinking') { const delta=toText(e.delta);memory.ccThinking += delta;memory.busy=true;let thinking=els.feed.querySelector('.cc-thinking>div');if(!thinking){const d=document.createElement('details');d.className='cc-thinking';d.innerHTML='<summary>Düşünüyor…</summary><div></div>';els.feed.appendChild(d);thinking=d.querySelector('div');}thinking.appendChild(document.createTextNode(delta));return; }
      else if (e.kind === 'cc_tool') { const i = memory.ccTools.findIndex(t => t.id === e.id); const t = { ...e }; if (i < 0) memory.ccTools.push(t); else memory.ccTools[i] = { ...memory.ccTools[i], ...t }; }
      else if (e.kind === 'cc_tool_result') { const t = memory.ccTools.find(x => x.id === e.id); if (t) Object.assign(t, { ok: e.ok, content: toText(e.content), status: 'done' }); else memory.ccTools.push({ ...e, content: toText(e.content), status: 'done' }); }
      else if (e.kind === 'cc_assistant_done') { const text = toText(e.text || e.msg || memory.ccLive); if (text) memory.messages.push({ who: 'chief', text }); memory.ccLive = ''; memory.ccThinking = ''; }
      else if (e.kind === 'cc_result') { memory.busy = false; if (['planning', 'discussing'].includes(memory.state)) memory.state = 'idle'; memory.ccUsage = e; const text = toText(e.text ?? e.content); if (text && !memory.messages.some(m => m.who === 'chief' && m.text === text)) memory.messages.push({ who: 'chief', text }); memory.ccLive = ''; memory.ccThinking = ''; }
      else if (e.kind === 'cc_error') { memory.busy = false; if (['planning', 'discussing'].includes(memory.state)) memory.state = 'idle'; memory.messages.push({ who: 'chief', text: e.error || 'Şef hatası', error: true }); }
      else if (e.kind === 'cc_limit') memory.ccLimit = toText(e.info) || 'Kullanım sınırına ulaşıldı.';
      else if (e.kind === 'cc_plan') { memory.plan = e.plan; memory.ccPlanInvalid = false; }
      else if (e.kind === 'cc_plan_invalid') { memory.ccPlanInvalid = toText(e.error); }
      else if (e.kind === 'task_report') { const i = memory.ccTasks.findIndex(t => t.task === e.task); const t = { ...e, summary: toText(e.summary) }; if (i < 0) memory.ccTasks.push(t); else memory.ccTasks[i] = t; }
      else if (e.kind === 'ask_user') memory.ccQuestion = toText(e.question);
      render(); return;
    }
    if (e.kind === 'ask_tool') { const state = ctx.getState() || {}, roles = Array.isArray(state.roles) ? state.roles : Object.values(state.roles?.roles || state.roles || {}), chief = roles.find(r => r.chief); const models = state.roles?.models || {}; const chiefRuntime = chief && (chief.runtime || models[(chief.models || [])[0]]?.runtime); if (memory.cc || chiefRuntime === 'claude') { memory.toolQuestion = null; return; } if (!memory.toolQuestion && memory.state !== 'awaiting_tool') memory.toolQuestion=e; memory.state='awaiting_tool'; memory.busy=false; }
    else if (e.kind === 'fallback') { const t=memory.plan?.tasks?.find(x=>x.id===d.tag||x.role===d.tag)||memory.plan?.tasks?.find(x=>(memory.tasks[x.id]||{}).status==='running'); if(t) memory.tasks[t.id]={...(memory.tasks[t.id]||{}),fallback:d}; }
    else if (e.kind === 'chat_user') { if (!memory.messages.some(m => m.who === 'user' && m.text === d.text)) memory.messages.push({ who: 'user', text: d.text || '' }); }
    else if (e.kind === 'discuss_start') { memory.phase = 'discuss'; memory.state = 'discussing'; memory.busy = true; }
    else if (e.kind === 'discuss_reply') { memory.phase = 'discuss'; memory.ready = !!d.ready; memory.state = 'idle'; memory.busy = false; if (!memory.messages.some(m => m.who === 'chief' && m.text === d.text)) memory.messages.push({ who: 'chief', text: d.text || '' }); }
    else if (e.kind === 'discuss_error') { memory.phase = 'discuss'; memory.state = 'idle'; memory.busy = false; if (!memory.messages.some(m => m.who === 'chief' && m.text === (d.error || 'Şef yanıt veremedi.'))) memory.messages.push({ who: 'chief', text: d.error || 'Şef yanıt veremedi.', error: true }); }
    else if (e.kind === 'usage') { memory.usage = d.usage || null; memory.estTokens = d.est_tokens ?? null; }
    else if (e.kind === 'plan_start') { memory.phase = 'plan'; memory.state = 'planning'; memory.busy = true; }
    else if (e.kind === 'plan_ready') { memory.plan = d.plan; memory.auto = !!d.auto; memory.state = d.auto ? 'running' : 'awaiting'; if (!memory.messages.some(m => m.who === 'chief' && m.text === (d.plan.summary || 'Plan hazır.'))) memory.messages.push({ who: 'chief', text: d.plan.summary || 'Plan hazır.' }); }
    else if (e.kind === 'plan_question') { memory.state = 'idle'; memory.messages.push({ who: 'chief', text: d.question || '' }); }
    else if (e.kind === 'plan_error') { memory.state = 'idle'; memory.messages.push({ who: 'chief', text: 'Hata: ' + (d.error || 'Plan hazırlanamadı.'), error: true }); }
    else if (e.kind === 'plan_run') memory.state = 'running';
    else if (e.kind === 'task_state') memory.tasks[d.id] = { ...(memory.tasks[d.id] || {}), status: d.status, run: d.run || (memory.tasks[d.id] || {}).run };
    else if (e.kind === 'chat_summary') { if (!memory.messages.some(m => m.who === 'chief' && m.text === d.text)) memory.messages.push({ who: 'chief', text: d.text || '' }); }
    else if (e.kind === 'chat_done') { memory.state = d.state === 'rejected' ? 'idle' : 'done'; memory.busy = false; if (d.state === 'rejected') memory.plan = null; }
    else return;
    render();
  }
  function unmount() { document.removeEventListener('visibilitychange', onVisibilityChange); document.documentElement.classList.remove('chat-hero-paused', 'chat-hero-visible'); document.querySelector('#sidebar .chat-history')?.remove(); if (host) host.innerHTML = ''; host = null; ctx = null; els = null; }
  function handleDisconnect() { memory.disconnected = true; render(); }
  function demo() {
    memory.demo = true; memory.chatId = 'demo-chat'; memory.messages = [{ who: 'user', text: 'Arayüzü gözden geçir ve küçük ekranlar için iyileştir.' }]; memory.plan = null; memory.tasks = {}; memory.state = 'planning'; memory.auto = false; memory.approval = 'ask'; memory.seen.clear(); render();
    const plan = { summary: 'Arayüzü inceleyip mobil deneyimi iyileştireceğim.', tasks: [{ id: 't1', role: 'frontend', instruction: 'Dar ekranlarda taşan bileşenleri belirle ve düzenle.\n- 600px altı görünümü kontrol et.', write: true, depends_on: [] }, { id: 't2', role: 'reviewer', instruction: 'Değişiklikleri erişilebilirlik açısından gözden geçir.', write: false, depends_on: ['t1'] }] };
    setTimeout(() => handleEvent({ kind: 'plan_ready', chat: 'demo-chat', plan, auto: false }), 700);
    setTimeout(() => { memory.state = 'running'; handleEvent({ kind: 'plan_run', chat: 'demo-chat', tasks: ['t1', 't2'] }); handleEvent({ kind: 'task_state', chat: 'demo-chat', id: 't1', status: 'running' }); }, 1400);
    setTimeout(() => { handleEvent({ kind: 'task_state', chat: 'demo-chat', id: 't1', status: 'ok', run: 'demo-run-1' }); handleEvent({ kind: 'task_state', chat: 'demo-chat', id: 't2', status: 'running' }); }, 2100);
    setTimeout(() => { handleEvent({ kind: 'task_state', chat: 'demo-chat', id: 't2', status: 'ok', run: 'demo-run-2' }); handleEvent({ kind: 'chat_summary', chat: 'demo-chat', text: 'Demo tamamlandı: mobil düzen önerileri hazır.' }); handleEvent({ kind: 'chat_done', chat: 'demo-chat', state: 'done' }); }, 2900);
  }
  window.ChatUI = { mount, handleEvent, handleDisconnect, unmount, refreshHistory: renderHistory, __demo: demo };
})();
