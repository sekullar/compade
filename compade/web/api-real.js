// Compade gerçek API katmanı. Tasarım prototipindeki sahte `const api = {...}` bloğunun yerine geçer.
// Sözleşme: design/gorev-tasarim-v2.md. Anahtar, sunucu tarafından HTML'e gömülür (window.__COMPADE__.token).
window.api = (() => {
  const tok = (window.__COMPADE__ || {}).token || '';
  async function req(path, opts = {}) {
    const r = await fetch(path, { ...opts, headers: { 'Content-Type': 'application/json', 'X-Compade-Token': tok, ...(opts.headers || {}) } });
    const j = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(j.error || r.statusText);
    return j;
  }
  const post = (path, body) => req(path, { method: 'POST', body: JSON.stringify(body || {}) });
  return {
    state: () => req('/api/state'),
    run: (b) => post('/api/run', b),
    cancel: () => post('/api/cancel'),
    runs: () => req('/api/runs'),
    runDetail: (id) => req('/api/run?id=' + encodeURIComponent(id)),
    accountAction: (id, action) => post('/api/account', { id, action }),
    addAccount: (provider, label) => post('/api/account/add', { provider, label }),
    roles: () => req('/api/roles'),
    saveRoles: (roles) => post('/api/roles', { roles }),
    catalog: () => req('/api/catalog'),
    teamDesign: (prompt) => post('/api/team/design', { prompt }),
    teamDesignGet: (id) => req('/api/team/design?id=' + encodeURIComponent(id)),
    teamApply: (roles) => post('/api/team/apply', { roles, replace: true }),
    chatSend: (b) => post('/api/chat', b),
    chatMessage: (chat, text, cwd, files, direct) => post('/api/chat', { chat, text, cwd: cwd || '', files: files || [], ...(direct ? { direct: true } : {}) }),
    chatStart: (chat, cwd) => post('/api/chat/start', { chat, cwd: cwd || '' }),
    chatGet: (id) => req('/api/chat?id=' + encodeURIComponent(id)),
    chatDelete: (chat) => post('/api/chat/delete', { chat }),
    chatRename: (chat, title) => post('/api/chat/rename', { chat, title }),
    costs: (days) => req('/api/costs?days=' + encodeURIComponent(days || 7)),
    chatChanges: (id) => req('/api/chat/changes?id=' + encodeURIComponent(id)),
    chatDiff: (id, path) => req('/api/chat/diff?id=' + encodeURIComponent(id) + '&path=' + encodeURIComponent(path)),
    chatApply: (chat, paths) => post('/api/chat/apply', { chat, paths }),
    chatDiscard: (chat) => post('/api/chat/discard', { chat }),
    chatMode: (chat, mode) => post('/api/chat/mode', { chat, mode }),
    chatTool: (chat, tool, model, remember) => post('/api/chat/tool', { session: chat, tool, ...(model ? { model } : {}), remember: !!remember }),
    chatApprove: (chat, drop, cwd) => post('/api/chat/approve', { chat, drop: drop || [], cwd: cwd || '' }),
    chatReject: (chat) => post('/api/chat/reject', { chat }),
    chatCancel: (chat) => post('/api/chat/cancel', { chat }),
    saveConfig: (c) => post('/api/config', c),
    updateCheck: (force) => req('/api/update' + (force ? '?force=1' : '')),
    updateInstall: () => post('/api/update/install'),
    readFile: (p) => req('/api/file?path=' + encodeURIComponent(p)),
    writeFile: (path, text) => post('/api/file', { path, text }),
    ls: (p) => req('/api/ls?path=' + encodeURIComponent(p || '')),
    onEvent(cb, onDisconnect) {
      const es = new EventSource('/api/events?token=' + encodeURIComponent(tok));
      es.onmessage = (e) => { try { cb(JSON.parse(e.data)); } catch (_) {} };
      es.onerror = () => { if (onDisconnect) onDisconnect(); };
      return () => es.close();
    },
  };
})();
