(function () {
  'use strict';
  const state = { tabs: [], active: '', cwd: '', tree: new Map(), expanded: new Set(), recent: [], scrollTop: 0, cursor: 0, showExplorer: false, confirmClose: '' };
  let root, ctx, frame = 0, listeners = [];
  const extColor = { py:'#8ebf72', js:'#e3c86d', ts:'#67b9cf', json:'#9cc879', md:'#8aa8cf', html:'#d98d73', css:'#78b9c9', txt:'#87948d' };
  const extType = { py:'Python', js:'JavaScript', ts:'TypeScript', json:'JSON', md:'Markdown', html:'HTML', css:'CSS', txt:'Metin' };
  const esc = s => (ctx && ctx.esc ? ctx.esc(String(s)) : String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])));
  const icon = (kind) => kind === 'dir' ? '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M1.5 4.5h5l1.5 1.7h6.5v6.3h-13z"/><path d="M1.5 4.5V3.5h4l1.3 1"/></svg>' : kind === 'up' ? '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 13V3M4 7l4-4 4 4"/></svg>' : kind === 'refresh' ? '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M13 5.5A5.5 5.5 0 0 0 3 4L2 5.5M2 2.5v3h3M3 10.5A5.5 5.5 0 0 0 13 12l1-1.5M14 13.5v-3h-3"/></svg>' : kind === 'menu' ? '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M2 4h12M2 8h12M2 12h12"/></svg>' : '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3 1.5h6l4 4v9H3z"/><path d="M9 1.5v4h4"/></svg>';
  function pathJoin(a,b){ return a.replace(/[\\/]$/,'') + (a.includes('\\')?'\\':'/') + b; }
  function basename(p){ return p.split(/[\\/]/).filter(Boolean).pop() || p; }
  function ext(p){ return (p.split('.').pop() || '').toLowerCase(); }
  function active(){ return state.tabs.find(t => t.path === state.active); }
  function changed(t){ return t.text !== t.saved; }
  function listen(el, ev, fn, opts){ el.addEventListener(ev,fn,opts); listeners.push(()=>el.removeEventListener(ev,fn,opts)); }
  function dispose(){ listeners.splice(0).forEach(f=>f()); if(frame) cancelAnimationFrame(frame); frame=0; }
  function markRecent(p){ state.recent=[p,...state.recent.filter(x=>x!==p)].slice(0,8); }
  async function openFile(path){
    if(!ctx) return;
    const present=state.tabs.find(t=>t.path===path); if(present){ state.active=path; draw(); return; }
    try {
      const f=await ctx.api.readFile(path); const eol=f.text.includes('\r\n')?'\r\n':'\n'; let t=f.text.replace(/\r\n/g,'\n');
      // Büyük metinler uyarıyla açılır; renklendirme kapatılır.
      if(t.includes('\u0000')) throw new Error('İkili dosya metin editöründe açılamaz.');
      const tab={eol,path:f.path,text:t,saved:t,cursor:0,scrollTop:0,large:t.length>1048576}; state.tabs.push(tab); state.active=tab.path; markRecent(tab.path); draw();
    } catch(e){ ctx.notify(e.message || 'Dosya açılamadı.'); }
  }
  async function loadDir(path){
    try { const r=await ctx.api.ls(path); state.cwd=r.path; state.tree.set(r.path,r.items.filter(i=>!['node_modules','.git','__pycache__'].includes(i.name))); drawTree(); }
    catch(e){ if(root) { const msg=root.querySelector('.ed-tree-error'); if(msg) msg.textContent=e.message||'Klasör okunamadı.'; } }
  }
  function syntax(text, language){
    const safe=esc(text); if(!language) return safe;
    const re=/(\/\/[^\n]*|#[^\n]*|<!--[\s\S]*?-->|"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`|\b\d+(?:\.\d+)?\b|\b(?:const|let|var|function|return|if|else|for|while|class|new|import|from|export|async|await|def|self|None|True|False|and|or|not|in|is|with|as|try|except|pass|raise|print|public|private|static|void|int|bool|string|extends|interface|type)\b|\b[A-Za-z_$][\w$]*(?=\s*\())/g;
    let out='',at=0,m;
    while((m=re.exec(text))){ out+=esc(text.slice(at,m.index)); const x=m[0], type=/^(\/\/|#|<!--)/.test(x)?'comment':/^["'`]/.test(x)?'string':/^\d/.test(x)?'number':/^(const|let|var|function|return|if|else|for|while|class|new|import|from|export|async|await|def|self|None|True|False|and|or|not|in|is|with|as|try|except|pass|raise|print|public|private|static|void|int|bool|string|extends|interface|type)$/.test(x)?'keyword':'function'; out+='<span class="ed-syn-'+type+'">'+esc(x)+'</span>'; at=re.lastIndex; }
    return out+esc(text.slice(at));
  }
  function drawTree(){
    if(!root) return; const tree=root.querySelector('.ed-tree'); if(!tree) return;
    const rows=[]; const walk=(p,depth)=>{ const items=state.tree.get(p)||[]; for(const i of items){ const full=pathJoin(p,i.name), opened=state.expanded.has(full); rows.push(`<button role="treeitem" aria-level="${depth+1}" aria-expanded="${i.dir?opened:'false'}" class="ed-node ${state.active===full?'is-active':''}" style="--depth:${depth}" data-path="${esc(full)}" data-dir="${i.dir}"><span class="ed-arrow">${i.dir?(opened?'⌄':'›'):''}</span><span class="ed-file-icon" style="--file-color:${extColor[ext(i.name)]||'var(--ed-muted)'}">${icon(i.dir?'dir':'file')}</span><span class="ed-node-name">${esc(i.name)}</span></button>`); if(i.dir&&opened&&state.tree.has(full)) walk(full,depth+1); } }; walk(state.cwd,0);
    tree.innerHTML=rows.join('')||'<div class="ed-tree-empty">Bu klasör boş.</div>';
    const nodes=[...tree.querySelectorAll('[data-path]')]; nodes.forEach((b,index)=>{listen(b,'click',()=>{ const p=b.dataset.path; if(b.dataset.dir==='true'){ if(state.expanded.has(p)) state.expanded.delete(p); else {state.expanded.add(p); if(!state.tree.has(p)) loadDir(p); } drawTree(); } else openFile(p); });listen(b,'keydown',e=>{if(e.key==='ArrowDown'||e.key==='ArrowUp'){e.preventDefault();nodes[Math.max(0,Math.min(nodes.length-1,index+(e.key==='ArrowDown'?1:-1)))]?.focus();}else if(e.key==='ArrowRight'&&b.dataset.dir==='true'&&!state.expanded.has(b.dataset.path)){e.preventDefault();b.click();}else if(e.key==='ArrowLeft'&&b.dataset.dir==='true'&&state.expanded.has(b.dataset.path)){e.preventDefault();b.click();}});});
  }
  function lineCount(text){ return text.split('\n').length; }
  function renderHighlight(t){
    const pre=root.querySelector('.ed-highlight'); if(!pre) return;
    const current=t.text.slice(0,t.cursor).split('\n').length-1;
    if(t.large) pre.textContent=t.text;
    else pre.innerHTML=t.text.split('\n').map((line,i)=>`<span class="ed-code-line${i===current?' is-current':''}">${syntax(line,ext(t.path))||' '}</span>`).join('\n');
    const numbers=Array.from({length:lineCount(t.text)},(_,i)=>`<span class="${i===current?'is-current':''}">${i+1}</span>`).join(''); root.querySelector('.ed-line-numbers').innerHTML=numbers;
  }
  function draw(){
    if(!root) return; dispose();
    const t=active();
    root.innerHTML=`<div class="ed-layout ${state.showExplorer?'ed-explorer-open':''}"><aside class="ed-explorer"><div class="ed-explorer-head"><span class="ed-root-name" title="${esc(state.cwd)}">${esc(basename(state.cwd)||state.cwd)}</span><button class="ed-icon-btn" data-action="up" aria-label="Üst klasör" title="Üst klasör">${icon('up')}</button><button class="ed-icon-btn" data-action="refresh" aria-label="Klasörü yenile" title="Yenile">${icon('refresh')}</button></div><div class="ed-tree" role="tree" aria-label="Dosya gezgini"></div><div class="ed-tree-error" role="status"></div></aside><main class="ed-main"><div class="ed-tabs" role="tablist" aria-label="Açık dosyalar"><button class="ed-mobile-toggle" data-action="explorer" aria-label="Gezgini aç">${icon('menu')}</button>${state.tabs.map(x=>`<div class="ed-tab ${x.path===state.active?'is-active':''}" role="tab" aria-selected="${x.path===state.active}" tabindex="0" data-tab="${esc(x.path)}" title="${esc(x.path)}"><span class="ed-tab-name">${esc(basename(x.path))}</span>${changed(x)?'<span class="ed-dirty" aria-label="Kaydedilmedi">●</span>':''}<button data-close="${esc(x.path)}" class="ed-tab-close" aria-label="${esc(basename(x.path))} sekmesini kapat">×</button></div>`).join('')}</div>${t?`<div class="ed-breadcrumb">${esc(t.path.split(/[\\/]/).filter(Boolean).join(' › '))}</div><div class="ed-editor"><div class="ed-code-scroll"><div class="ed-line-numbers" aria-hidden="true"></div><div class="ed-code-layer"><pre class="ed-highlight" aria-hidden="true"></pre><textarea class="ed-input" aria-label="${esc(basename(t.path))} içeriği" spellcheck="false" autocapitalize="off" autocomplete="off" autocorrect="off"></textarea></div></div>${t.large?'<div class="ed-large-note" role="status">Dosya 1 MB üzerinde; sözdizimi renklendirmesi kapalı.</div>':''}<div class="ed-find" hidden><input aria-label="Dosyada bul" placeholder="Bul"><button data-action="prev">Önceki</button><button data-action="next">Sonraki</button><button data-action="find-close" aria-label="Bulmayı kapat">×</button><span class="ed-find-count"></span></div></div><div class="ed-status"><span class="ed-position">Ln 1, Col 1</span><span>${extType[ext(t.path)]||'Metin'}</span><span>UTF-8</span><span>Boşluk: 4</span><span class="ed-unsaved">${changed(t)?'Kaydedilmedi':''}</span></div>`:`<div class="ed-empty"><p>Gezginden bir dosya seç</p>${state.recent.length?`<div class="ed-recent-label">Son açılan dosyalar</div>${state.recent.map(p=>`<button class="ed-recent" data-recent="${esc(p)}">${esc(p)}</button>`).join('')}`:''}</div>`}</main></div>`;
    drawTree();
    root.querySelector('[data-action="up"]').onclick=()=>{const parts=state.cwd.split(/[\\/]/);parts.pop();loadDir(parts.join(state.cwd.includes('\\')?'\\':'/')||state.cwd);};
    root.querySelector('[data-action="refresh"]').onclick=()=>loadDir(state.cwd);
    root.querySelector('[data-action="explorer"]').onclick=()=>{state.showExplorer=!state.showExplorer;root.querySelector('.ed-layout').classList.toggle('ed-explorer-open',state.showExplorer);};
    root.querySelectorAll('[data-tab]').forEach(b=>{listen(b,'click',e=>{if(e.target.closest('[data-close]'))return;state.active=b.dataset.tab;draw();});listen(b,'auxclick',e=>{if(e.button===1)closeTab(b.dataset.tab);});});
    root.querySelectorAll('[data-close]').forEach(b=>listen(b,'click',e=>{e.stopPropagation();closeTab(b.dataset.close);})); root.querySelectorAll('[data-recent]').forEach(b=>listen(b,'click',()=>openFile(b.dataset.recent)));
    if(!t) return;
    const input=root.querySelector('.ed-input'), scroll=root.querySelector('.ed-code-scroll'); input.value=t.text; input.selectionStart=input.selectionEnd=t.cursor; scroll.scrollTop=t.scrollTop;
    const sync=()=>{t.text=input.value;t.cursor=input.selectionStart;t.scrollTop=scroll.scrollTop;const pos=input.value.slice(0,input.selectionStart).split('\n');root.querySelector('.ed-position').textContent=`Ln ${pos.length}, Col ${pos[pos.length-1].length+1}`;root.querySelector('.ed-unsaved').textContent=changed(t)?'Kaydedilmedi':'';const tab=root.querySelector(`[data-tab="${CSS.escape(t.path)}"]`);if(tab&&!tab.querySelector('.ed-dirty')&&changed(t))tab.insertAdjacentHTML('beforeend','<span class="ed-dirty" aria-label="Kaydedilmedi">●</span>');if(tab&&!changed(t))tab.querySelector('.ed-dirty')?.remove();drawTree();if(!t.large&&!frame)frame=requestAnimationFrame(()=>{frame=0;renderHighlight(t);});};
    listen(input,'input',sync); listen(input,'click',sync); listen(input,'keyup',sync); listen(scroll,'scroll',()=>{t.scrollTop=scroll.scrollTop;});
    listen(input,'scroll',()=>{root.querySelector('.ed-highlight').scrollTop=input.scrollTop;root.querySelector('.ed-highlight').scrollLeft=input.scrollLeft;});
    listen(input,'keydown',e=>{ if(e.key==='Tab'){e.preventDefault();const a=input.selectionStart,b=input.selectionEnd;if(e.shiftKey){const line=input.value.slice(0,a).lastIndexOf('\n')+1;if(input.value.slice(line,line+4)==='    '){input.setRangeText('',line,line+4,'end');input.selectionStart=input.selectionEnd=Math.max(line,a-4);}}else{input.setRangeText('    ',a,b,'end');}sync();}
      if(e.key==='Enter'){const before=input.value.slice(0,input.selectionStart), line=before.slice(before.lastIndexOf('\n')+1), indent=(line.match(/^\s*/)||[''])[0]+(/[{[(]\s*$/.test(line)?'    ':'');if(indent){e.preventDefault();input.setRangeText('\n'+indent,input.selectionStart,input.selectionEnd,'end');sync();}}
      if(['"',"'",'(', '[', '{'].includes(e.key)&&!e.ctrlKey&&!e.metaKey){const close={'"':'"',"'":"'",'(':")",'[':']','{':'}'}[e.key];const a=input.selectionStart,b=input.selectionEnd;if(a===b){e.preventDefault();input.setRangeText(e.key+close,a,b,'end');input.selectionStart=input.selectionEnd=a+1;sync();}}
    });
    listen(input,'keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();saveFile();} if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='f'){e.preventDefault();showFind();} if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='w'){e.preventDefault();closeTab(t.path);} });
    renderHighlight(t);
  }
  async function saveFile(){const t=active();if(!t)return;try{await ctx.api.writeFile(t.path,t.eol==='\r\n'?t.text.replace(/\n/g,'\r\n'):t.text);t.saved=t.text;ctx.notify('Dosya kaydedildi');draw();}catch(e){ctx.notify(e.message||'Dosya kaydedilemedi.');}}
  function closeTab(path){const t=state.tabs.find(x=>x.path===path);if(!t)return;if(changed(t)){state.confirmClose=path;let old=root.querySelector('.ed-confirm');if(old)old.remove();root.insertAdjacentHTML('beforeend',`<div class="ed-confirm" role="dialog" aria-label="Kaydedilmemiş değişiklik"><span>${esc(basename(path))} kaydedilmedi.</span><button data-confirm="save">Kaydet</button><button data-confirm="discard">Kapat</button><button data-confirm="cancel">İptal</button></div>`);root.querySelectorAll('[data-confirm]').forEach(b=>listen(b,'click',async()=>{if(b.dataset.confirm==='save'){await saveFile();}else if(b.dataset.confirm==='discard'){removeTab(path);}else draw();}));return;}removeTab(path);}
  function removeTab(path){const i=state.tabs.findIndex(x=>x.path===path);state.tabs.splice(i,1);if(state.active===path)state.active=state.tabs[Math.max(0,i-1)]?.path||'';state.confirmClose='';draw();}
  function showFind(){const bar=root.querySelector('.ed-find');bar.hidden=false;bar.querySelector('input').focus();}
  function findMove(dir){const t=active(),input=root.querySelector('.ed-input'),q=root.querySelector('.ed-find input').value;if(!q)return;const at=dir>0?t.text.indexOf(q,input.selectionEnd):t.text.lastIndexOf(q,Math.max(0,input.selectionStart-1));if(at<0){root.querySelector('.ed-find-count').textContent='Eşleşme yok';return;}input.focus();input.setSelectionRange(at,at+q.length);root.querySelector('.ed-find-count').textContent='Bulundu';}
  function mount(container, context){root=container;ctx=context;state.cwd=state.cwd||ctx.getCwd();draw();if(!state.tree.has(state.cwd))loadDir(state.cwd);const key=e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='w'){e.preventDefault();if(active())closeTab(state.active);}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='s'){e.preventDefault();saveFile();}if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='f'){e.preventDefault();showFind();}if(e.key==='Escape'&&root?.querySelector('.ed-find:not([hidden])'))root.querySelector('.ed-find').hidden=true;};listen(document,'keydown',key);listen(root,'click',e=>{const a=e.target.closest('[data-action]');if(a?.dataset.action==='next')findMove(1);if(a?.dataset.action==='prev')findMove(-1);if(a?.dataset.action==='find-close')root.querySelector('.ed-find').hidden=true;});}
  function unmount(){const t=active();if(t){const input=root?.querySelector('.ed-input'),scroll=root?.querySelector('.ed-code-scroll');if(input){t.cursor=input.selectionStart;t.scrollTop=scroll.scrollTop;t.text=input.value;}}dispose();if(root)root.replaceChildren();root=null;ctx=null;}
  function demo(){state.cwd='/demo';state.tree.set('/demo',[{name:'hello.py',dir:false},{name:'settings.json',dir:false},{name:'notes.md',dir:false}]);state.tabs=[{path:'/demo/hello.py',text:'def greet(name):\n    # Selam ver\n    return "Merhaba, " + name\n',saved:'def greet(name):\n    # Selam ver\n    return "Merhaba, " + name\n',cursor:0,scrollTop:0},{path:'/demo/settings.json',text:'{\n  "theme": "dark",\n  "indent": 4\n}\n',saved:'{\n  "theme": "dark",\n  "indent": 4\n}\n',cursor:0,scrollTop:0},{path:'/demo/notes.md',text:'# Notlar\n\nEditör demosu.\n',saved:'# Notlar\n\nEditör demosu.\n',cursor:0,scrollTop:0}];state.active='/demo/hello.py';draw(); }
  window.EditorUI={mount,unmount,openFile,__demo:demo};
})();
