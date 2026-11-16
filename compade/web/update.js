/* Güncelleme: durum çubuğunda sürüm yanında "Güncelle vX" düğmesi. Sürüm yazısına tıklamak yeniden denetler. */
(function () {
  let info = null, busy = false;
  const $ = s => document.querySelector(s);

  function chip() {
    let b = $('#updateChip');
    if (!b) {
      const v = $('#version'); if (!v) return null;
      b = document.createElement('button');
      b.id = 'updateChip'; b.type = 'button'; b.className = 'update-chip'; b.hidden = true;
      v.parentNode.insertBefore(b, v);
      v.style.cursor = 'pointer'; v.title = 'Güncellemeleri denetle';
      v.addEventListener('click', () => check(true));
      b.addEventListener('click', act);
    }
    return b;
  }

  function render() {
    const b = chip(); if (!b) return;
    if (!info || !info.has_update) { b.hidden = true; return; }
    b.hidden = false;
    b.textContent = busy ? 'Kuruluyor…' : 'Güncelle v' + info.latest;
    b.disabled = busy;
    b.title = info.kind === 'hub' ? 'Sentinel Hub ile kuruldu: Hub\'daki Güncelle düğmesini kullan'
      : info.kind === 'source' ? 'Kaynaktan çalışıyor: sürüm sayfasını aç (git pull)'
      : 'İndir, kur ve yeniden aç';
  }

  async function check(force) {
    try { info = await window.api.updateCheck(force); } catch (_) { info = null; }
    render();
    if (force) {
      const v = $('#version');
      if (v && info) { const old = v.textContent; v.textContent = info.has_update ? 'yeni sürüm var' : info.error ? 'denetlenemedi' : 'güncel'; setTimeout(() => { v.textContent = old; }, 2500); }
    }
  }

  async function act() {
    if (!info || busy) return;
    if (info.kind !== 'installer') { window.open(info.page, '_blank', 'noopener'); return; }
    if (!confirm('Compade v' + info.latest + ' indirilip kurulacak. Uygulama kapanıp kendiliğinden yeniden açılacak; çalışan işler durur. Devam edilsin mi?')) return;
    busy = true; render();
    try { await window.api.updateInstall(); }
    catch (e) { busy = false; render(); alert('Güncelleme başlatılamadı: ' + (e.message || e)); }
  }

  window.addEventListener('load', () => { setTimeout(() => check(false), 3000); setInterval(() => check(false), 6 * 3600 * 1000); });
  window.CompadeUpdate = { check };
})();
