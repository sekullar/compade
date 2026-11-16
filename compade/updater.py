"""Güncelleme denetimi: GitHub'daki son sürüm (tag) ile çalışan sürümü karşılaştırır.

Kurulum biçimine göre davranır:
  source     kaynak koddan çalışıyor (python -m compade) -> yalnız sürüm sayfasını gösterir
  hub        Sentinel Hub kurmuş (%LOCALAPPDATA%\\SentinelHub\\apps\\compade) -> güncellemeyi Hub yapar
  installer  kendi kurulum dosyasıyla kurulmuş exe -> kurulum dosyasını indirip sessizce kurar, yeniden açar
Sonuç `~/.compade/update.json` içinde 6 saat önbelleklenir; ağ yoksa sessizce "bilinmiyor" döner.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import urllib.request
from pathlib import Path

from . import __version__, config

REPO = "sekullar/compade"
API = f"https://api.github.com/repos/{REPO}/releases/latest"
PAGE = f"https://github.com/{REPO}/releases/latest"
TTL = 6 * 3600
UA = {"User-Agent": "Compade", "Accept": "application/vnd.github+json"}
ASSET_RE = re.compile(r"^Compade[-. ]Setup[-. ][\w.-]+\.exe$", re.I)
_lock = threading.Lock()


def parse(v):
    return [int(n) if n.isdigit() else 0 for n in re.split(r"[.-]", str(v or "").lstrip("vV"))]


def is_newer(latest, current):
    a, b = parse(latest), parse(current)
    n = max(len(a), len(b))
    return (a + [0] * (n - len(a))) > (b + [0] * (n - len(b)))


def install_kind(exe=None, frozen=None):
    frozen = getattr(sys, "frozen", False) if frozen is None else frozen
    if not frozen:
        return "source"
    exe = Path(exe or sys.executable).resolve()
    hub = Path(os.environ.get("LOCALAPPDATA", "")) / "SentinelHub" / "apps"
    try:
        exe.relative_to(hub.resolve())
        return "hub"
    except ValueError:
        return "installer"


def _cache_file():
    return config.HOME / "update.json"


def _fetch():
    with urllib.request.urlopen(urllib.request.Request(API, headers=UA), timeout=10) as r:
        return json.loads(r.read().decode("utf-8"))


def check(force=False, fetch=None, now=None):
    """{"current","latest","has_update","kind","page","notes","asset","checked_at","error"?}"""
    now = now or time.time()
    kind = install_kind()
    with _lock:
        cached = {}
        try:
            cached = json.loads(_cache_file().read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        if not force and cached.get("checked_at", 0) > now - TTL and cached.get("current") == __version__:
            return {**cached, "kind": kind}
        out = {"current": __version__, "latest": None, "has_update": False, "page": PAGE, "notes": "",
               "asset": None, "checked_at": now}
        try:
            rel = (fetch or _fetch)()
            tag = str(rel.get("tag_name") or "")
            exes = [a for a in rel.get("assets") or [] if ASSET_RE.match(a.get("name") or "")]
            out.update(latest=tag.lstrip("vV") or None, has_update=bool(tag) and is_newer(tag, __version__),
                       page=rel.get("html_url") or PAGE, notes=str(rel.get("body") or "")[:1500],
                       asset={"name": exes[0]["name"], "url": exes[0]["browser_download_url"],
                              "size": exes[0].get("size")} if exes else None)
        except Exception as e:  # noqa: ağ yok, 404 (henüz sürüm yok), oran sınırı
            out["error"] = str(e)[:200]
            out["checked_at"] = now - TTL + 600      # hata: 10 dk sonra yeniden dene
        try:
            config.HOME.mkdir(parents=True, exist_ok=True)
            _cache_file().write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
        return {**out, "kind": kind}


def _safe_url(url):
    return bool(re.match(rf"^https://github\.com/{re.escape(REPO)}/releases/download/[^/]+/[^/]+\.exe$", url or "", re.I))


def install(info=None, download=None, launch=None, exit_after=1.2):
    """Kurulum dosyasını indirip sessiz kurar ve Compade'i yeniden açtırır (yalnız 'installer' kurulumunda)."""
    info = info or check(force=True)
    if info.get("kind") != "installer":
        raise ValueError("Bu kurulum kendi kendini güncelleyemez: " + {"hub": "Sentinel Hub'dan güncelle.",
                                                                        "source": "kaynak koddan çalışıyor (git pull)."}.get(info.get("kind"), ""))
    a = info.get("asset") or {}
    if not info.get("has_update") or not _safe_url(a.get("url")):
        raise ValueError("İndirilecek yeni sürüm yok")
    dest = Path(tempfile.gettempdir()) / f"Compade-update-{info['latest']}.exe"
    if download:
        download(a["url"], dest)
    else:
        with urllib.request.urlopen(urllib.request.Request(a["url"], headers={"User-Agent": "Compade"}), timeout=120) as r, \
                open(dest, "wb") as f:
            while chunk := r.read(1 << 16):
                f.write(chunk)
    if a.get("size") and dest.stat().st_size != a["size"]:
        dest.unlink(missing_ok=True)
        raise ValueError("İndirme eksik kaldı")
    inst_dir = Path(sys.executable).resolve().parent
    # NSIS: /D= en sonda ve tırnaksız olmalı; --relaunch kurulum bitince Compade'i açar
    cmd = f'"{dest}" --relaunch /S /D={inst_dir}'
    (launch or (lambda c: subprocess.Popen(c, close_fds=True, creationflags=0x00000008 | 0x00000200)))(cmd)
    if exit_after:
        threading.Timer(exit_after, lambda: os._exit(0)).start()   # kurulum dosyası exe'yi değiştirebilsin
    return {"ok": True, "version": info["latest"]}
