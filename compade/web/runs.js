"use strict";
(() => {
  const statuses = {
    running: ["Çalışıyor", "running"], ok: ["Tamam", "ok"], suspicious: ["Şüpheli", "warn"],
    limit: ["Limit", "warn"], error: ["Hata", "error"], timeout: ["Zaman aşımı", "error"],
    cancelled: ["Durduruldu", "muted"]
  };
  let host = null, ctx = null, opts = {}, runs = [], selected = null, filter = "all", query = "", expanded = new Set(), showAll = new Set(), busy = false;
  const esc = s => ctx.esc(String(s ?? ""));
  const status = s => statuses[s] || ["Bilinmiyor", "muted"];
  const titleFor = (name, tag) => {
    const n = String(name || "").trim(), value=n || String(tag || "");
    if (/(^|-)sef-plan($|-)/i.test(value)) return "Şef planı";
    if (/(^|-)sef-ozet($|-)/i.test(value)) return "Şef özeti";
    const m = value.match(/(?:^|-)\d{4}-(.+)$/);
    return m ? m[1].replace(/[-_]+/g, " ") : (n || tag || "Çalışma");
  };
  const roleFor = tag => {
    const t = String(tag || "");
    if (/^sef-plan/.test(t)) return "Şef planı";
    if (/^sef-ozet/.test(t)) return "Şef özeti";
    const m = t.match(/^[^-]+-(.+?)(?:-[^-]+)?$/);
    return m ? m[1].replace(/[-_]+/g, " ") : t || "Çalışan";
  };
  function relative(ms) {
    const d = new Date(Number(ms) || 0), now = new Date(), mins = Math.max(0, Math.floor((Date.now() - d.getTime()) / 60000));
    if (mins < 1) return "az önce";
    if (mins < 60) return `${mins} dk önce`;
    if (d.toDateString() === now.toDateString()) return `bugün ${d.toLocaleTimeString("tr-TR", {hour:"2-digit", minute:"2-digit"})}`;
    const y = new Date(now); y.setDate(y.getDate() - 1);
    if (d.toDateString() === y.toDateString()) return `dün ${d.toLocaleTimeString("tr-TR", {hour:"2-digit", minute:"2-digit"})}`;
    return d.toLocaleDateString("tr-TR", {day:"numeric", month:"short"});
  }
  function group(r) { const d = new Date(Number(r.when) || 0), n = new Date(); if (d.toDateString() === n.toDateString()) return "Bugün"; const y = new Date(n); y.setDate(y.getDate()-1); return d.toDateString() === y.toDateString() ? "Dün" : "Daha eski"; }
  function runStatus(r) {
    if (r.running) return "running";
    const s = String(r.status_summary || "").toLowerCase();
    if (/hata|error|zaman aşımı/.test(s)) return "error";
    if (/limit|şüpheli/.test(s)) return "warn";
    return "ok";
  }
  function stateView(s) { const x = s === "warn" ? ["Sorunlu", "warn"] : status(s); return `<span class="rn-status rn-${x[1]}"><i aria-hidden="true"></i>${esc(x[0])}</span>`; }
  function markdown(src) {
    const code = [];
    let text = esc(src).replace(/```([^\n]*)\n([\s\S]*?)```/g, (_, lang, body) => { code.push(`<pre><code>${body}</code></pre>`); return `\u0000${code.length-1}\u0000`; });
    text = text.replace(/^###?\s+(.+)$/gm, (_, s) => `<strong class="rn-md-heading">${s}</strong>`)
      .replace(/^\s*[-*]\s+(.+)$/gm, "<span class=\"rn-md-bullet\">•</span> $1")
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>").replace(/`([^`]+)`/g, "<code>$1</code>");
    text = text.split(/\n{2,}/).map(p => /^\u0000\d+\u0000$/.test(p.trim()) ? p : `<p>${p.replace(/\n/g,"<br>")}</p>`).join("");
    return text.replace(/\u0000(\d+)\u0000/g, (_, i) => code[+i]);
  }
  function requestText(d) {
    const m = String(d.digest || "").match(/^##\s+(?:İstek|Görev|Task)\s*\n+([\s\S]*?)(?=\n##\s|$)/mi);
    return m ? m[1].trim() : "";
  }
  function drawList() {
    const filtered = runs.filter(r => {
      const st = runStatus(r), matchFilter = filter === "all" || (filter === "running" ? st === "running" : st === "warn" || st === "error");
      return matchFilter && `${titleFor(r.name,r.id)} ${r.id}`.toLocaleLowerCase("tr").includes(query.toLocaleLowerCase("tr"));
    }).sort((a,b) => Number(!!b.running)-Number(!!a.running) || b.when-a.when);
    const groups = ["Bugün", "Dün", "Daha eski"].map(g => {
      const items = filtered.filter(r => group(r) === g); if (!items.length) return "";
    return `<div class="rn-group-title">${g}</div>${items.map(r => `<button class="rn-row ${r.id===selected?"is-active":""}" data-rn-select="${esc(r.id)}" aria-pressed="${r.id===selected}"><span class="rn-row-main"><strong>${esc(titleFor(r.name,r.id))}</strong><small>${esc(relative(r.when))}</small></span>${stateView(runStatus(r))}</button>`).join("")}`;
    }).join("");
    return `<aside class="rn-list" aria-label="Çalışmalar"><div class="rn-list-tools"><div class="rn-segments" role="group" aria-label="Çalışmaları filtrele">${[["all","Hepsi"],["running","Çalışan"],["issues","Sorunlu"]].map(([k,v])=>`<button type="button" data-rn-filter="${k}" aria-pressed="${filter===k}">${v}</button>`).join("")}</div><input class="rn-search" type="search" aria-label="Çalışmalarda ara" placeholder="Ara" value="${esc(query)}"></div><div class="rn-list-items">${groups || `<p class="rn-muted rn-list-empty">${runs.length ? "Eşleşen çalışma yok." : "Henüz çalışma yok. Ofis'ten şefe bir iş ver."}</p>`}</div></aside>`;
  }
  function workerCard(w, i) {
    const key = `${selected}:${i}`, [label, cls] = status(w.status), logo = window.Logos && window.Logos.agent(w.model || w.tag) || "";
    const out = String(w.output || ""), long = out.length > 1600, expandedNow = showAll.has(key), body = long && !expandedNow ? out.slice(0,1600) : out;
    const notes = [];
    if (w.status === "limit") notes.push("Limit doldu, sonraki hesaba geçildi.");
    if (w.status === "suspicious") notes.push("Yanıt şüpheli; istenen iş tamamlanmamış olabilir.");
    if (w.note) notes.push(w.note);
    const verify = w.verify ? `<span>Doğrulama: ${esc(({pass:"geçti",fail:"başarısız"})[w.verify] || w.verify)}</span>` : "";
    return `<article class="rn-worker"><button class="rn-worker-toggle" type="button" data-rn-worker="${i}" aria-expanded="${expanded.has(key)}"><span class="rn-agent-logo" aria-hidden="true">${logo}</span><span class="rn-worker-title"><strong>${esc(roleFor(w.tag))}</strong><small>${esc(w.model || "Model bilinmiyor")}${w.account ? ` · ${esc(w.account)}` : ""}</small></span><span class="rn-status rn-${cls}"><i aria-hidden="true"></i>${esc(label)}</span><span class="rn-chevron" aria-hidden="true">${expanded.has(key)?"−":"+"}</span></button><div class="rn-worker-meta">${w.seconds == null ? "Süre bilinmiyor" : `${esc(w.seconds)} sn`} · ${w.chars == null ? "Karakter sayısı yok" : `${esc(w.chars)} karakter`}${verify}</div>${notes.length ? `<p class="rn-note">${notes.map(esc).join(" ")}</p>` : ""}${expanded.has(key) ? `<div class="rn-output-wrap"><div class="rn-markdown">${markdown(body)}</div>${long ? `<div class="rn-output-actions"><button type="button" data-rn-more="${i}">${expandedNow?"Daha az göster":"Tümünü göster"}</button><button type="button" data-rn-copy="${i}">Kopyala</button></div>` : ""}</div>` : ""}</article>`;
  }
  async function detail() {
    const r = runs.find(x => x.id === selected); if (!r) return `<div class="rn-detail-placeholder">${runs.length ? "Bir çalışma seçin." : ""}</div>`;
    let d = {digest:"",workers:[]};
    try { d = await ctx.api.runDetail(selected) || d; } catch (e) { ctx.notify(e.message || "Çalışma ayrıntısı alınamadı."); }
    if (!host || !host.isConnected || !runs.some(x=>x.id===selected)) return "";
    lastDetail = d;
    const workers = d.workers || [], issue = workers.some(w=>["error","timeout","limit","suspicious"].includes(w.status));
    const overall = r.running ? "running" : issue ? "warn" : workers.length ? "ok" : "muted";
    const secs = workers.reduce((n,w)=>n+(Number(w.seconds)||0),0);
    const req = requestText(d);
    return `<section class="rn-detail" aria-live="polite"><header class="rn-detail-head"><button type="button" class="rn-back" data-rn-back>Çalışmalar</button><div><h2>${esc(titleFor(r.name||r.id, workers[0]?.tag))}</h2><p>${esc(relative(r.when))}${secs ? ` · toplam ${esc(secs)} sn` : ""}</p></div>${stateView(overall)}</header>${req ? `<section class="rn-request"><h3>İstek</h3><div class="rn-markdown">${markdown(req)}</div></section>` : ""}${workers.length ? `<section class="rn-workers"><h3>Çalışanlar <span>${workers.length}</span></h3>${workers.map(workerCard).join("")}</section>` : r.running ? `<div class="rn-progress"><span class="rn-spinner" aria-hidden="true"></span><strong>Çalışıyor…</strong><p>Sonuçlar geldikçe burada görünecek.</p></div>` : `<div class="rn-detail-placeholder">Bu çalışma için sonuç bulunamadı.</div>`}</section>`;
  }
  function bind() {
    host.querySelectorAll("[data-rn-filter]").forEach(b=>b.onclick=()=>{filter=b.dataset.rnFilter; render();});
    const search=host.querySelector(".rn-search"); if(search) search.oninput=()=>{query=search.value; const pos=search.selectionStart; render(); const next=host.querySelector(".rn-search"); next.focus(); next.setSelectionRange(pos,pos);};
    host.querySelectorAll("[data-rn-select]").forEach(b=>b.onclick=()=>{selected=b.dataset.rnSelect; expanded.clear(); showAll.clear(); render(); host.querySelector(".rn-layout")?.classList.add("rn-show-detail");});
    host.querySelector("[data-rn-back]")?.addEventListener("click",()=>host.querySelector(".rn-layout")?.classList.remove("rn-show-detail"));
    host.querySelectorAll("[data-rn-worker]").forEach(b=>b.onclick=()=>{const k=`${selected}:${b.dataset.rnWorker}`; expanded.has(k)?expanded.delete(k):expanded.add(k); render();});
    host.querySelectorAll("[data-rn-more]").forEach(b=>b.onclick=()=>{const k=`${selected}:${b.dataset.rnMore}`; showAll.has(k)?showAll.delete(k):showAll.add(k); render();});
    host.querySelectorAll("[data-rn-copy]").forEach(b=>b.onclick=async()=>{const w=(lastDetail?.workers||[])[+b.dataset.rnCopy]; try { await navigator.clipboard.writeText(w?.output||""); ctx.notify("Çıktı kopyalandı."); } catch (_) { ctx.notify("Çıktı kopyalanamadı."); }});
  }
  let lastDetail = null;
  async function render() { if(!host) return; const mobileDetail=host.querySelector(".rn-layout")?.classList.contains("rn-show-detail"); host.innerHTML=`<div class="rn-layout ${mobileDetail?"rn-show-detail":""}">${drawList()}<main class="rn-detail-pane">${await detail()}</main></div>`; bind(); }
  async function refresh() { if(!host || busy) return; busy=true; const scroll=host.querySelector(".rn-list-items")?.scrollTop; try { const next=await ctx.api.runs(); runs=Array.isArray(next)?next:[]; if(!selected || !runs.some(r=>r.id===selected)) selected=(opts.select && runs.some(r=>r.id===opts.select)?opts.select:runs[0]?.id)||null; await render(); const list=host.querySelector(".rn-list-items"); if(list) list.scrollTop=scroll||0; } catch(e) { ctx.notify(e.message || "Çalışmalar alınamadı."); } finally {busy=false;} }
  function mount(container, context, options={}) { host=container; ctx=context; opts=options; selected=options.select || selected; return refresh(); }
  function unmount() { host=null; ctx=null; runs=[]; lastDetail=null; expanded.clear(); showAll.clear(); }
  async function demo() { runs=[{id:"demo-ok",when:Date.now()-60000,name:"Görev: Arayüzü düzenle",status_summary:"1/1 başarılı",running:false},{id:"demo-error",when:Date.now()-7200000,name:"Görev: Hata incelemesi",status_summary:"1 hata",running:false},{id:"demo-limit",when:Date.now()-86400000,name:"Görev: Testleri çalıştır",status_summary:"1 limit",running:false},{id:"demo-running",when:Date.now(),name:"Görev: Yeni modül",status_summary:"Çalışıyor",running:true}]; selected="demo-ok"; const original=ctx.api.runDetail; ctx.api.runDetail=async id=>({digest:"",workers:[{tag:"gelistirici-codex",model:"codex",account:"kişisel",status:id==="demo-error"?"error":id==="demo-limit"?"limit":id==="demo-running"?"running":"ok",seconds:18,chars:248,tokens:63,verify:"pass",note:"",output:"## Sonuç\n\n- Bileşen eklendi\n- **Arayüz düzenlendi**\n\n```js\nconst ready = true;\n```"}]}); await render(); ctx.api.runDetail=original; }
  window.RunsUI={mount,unmount,refresh,__demo:demo};
})();
