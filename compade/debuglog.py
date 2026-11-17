"""Geliştirici hata ayıklama günlüğü: sunucu olayları, API istekleri, arayüz olayları ve ekran özetleri.

Yerelde, ~/.compade/debug/debug.jsonl dosyasına satır satır JSON olarak yazılır (boyuta göre döner).
Uzun metinler kısaltılır, gizli görünen alanlar (token, parola, anahtar...) maskelenir.
Kapatmak için: COMPADE_DEBUG=0 ortam değişkeni.
"""
import json
import os
import re
import threading
import time

from . import config

MAX_BYTES = 5 * 1024 * 1024
KEEP = 3                 # debug.jsonl + debug.1.jsonl + debug.2.jsonl
STR_LIMIT = 300
SECRET = re.compile(r"token|secret|pass(word)?|authorization|api[_-]?key|cookie|bearer", re.I)

_lock = threading.Lock()
_seq = 0


def enabled():
    return os.environ.get("COMPADE_DEBUG", "1").strip().lower() not in ("0", "false", "off", "hayır")


def _dir():
    return config.HOME / "debug"


def _path():
    return _dir() / "debug.jsonl"


def scrub(value, depth=0):
    """Günlüğe yazılacak değeri küçült: uzun metin kısalır, gizli alan maskelenir, derinlik/boyut sınırlanır."""
    if depth > 4:
        return "…"
    if isinstance(value, str):
        return value if len(value) <= STR_LIMIT else value[:STR_LIMIT] + f"…(+{len(value) - STR_LIMIT})"
    if isinstance(value, dict):
        out = {}
        for i, (k, v) in enumerate(value.items()):
            if i >= 40:
                out["…"] = f"+{len(value) - 40} alan"
                break
            out[str(k)] = "***" if SECRET.search(str(k)) else scrub(v, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        items = [scrub(v, depth + 1) for v in list(value)[:20]]
        if len(value) > 20:
            items.append(f"…(+{len(value) - 20})")
        return items
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return scrub(str(value), depth + 1)


def _rotate(path):
    try:
        if path.exists() and path.stat().st_size >= MAX_BYTES:
            for i in range(KEEP - 1, 0, -1):
                src = path.with_name("debug.jsonl" if i == 1 else f"debug.{i - 1}.jsonl")
                dst = path.with_name(f"debug.{i}.jsonl")
                if src.exists():
                    if dst.exists():
                        dst.unlink()
                    src.rename(dst)
    except OSError:
        pass


def log(source, kind, data=None, chat=None):
    """Bir satır yaz. Hiçbir koşulda çağıranı bozmaz."""
    global _seq
    if not enabled():
        return
    try:
        with _lock:
            _seq += 1
            row = {"n": _seq, "t": round(time.time(), 3), "src": source, "kind": kind}
            if chat:
                row["chat"] = chat
            if data:
                row["d"] = scrub(data)
            p = _path()
            p.parent.mkdir(parents=True, exist_ok=True)
            _rotate(p)
            with p.open("a", encoding="utf-8") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
    except Exception:  # noqa
        pass


def _files():
    base = _path()
    return [base.with_name(f"debug.{i}.jsonl") for i in range(KEEP - 1, 0, -1)] + [base]


def read(n=200, src=None, kind=None, chat=None, since=None, contains=None):
    """Son n satırı (eskiden yeniye) döner; süzgeçler isteğe bağlı."""
    rows = []
    for f in _files():
        try:
            with f.open(encoding="utf-8") as fh:
                for line in fh:
                    try:
                        r = json.loads(line)
                    except ValueError:
                        continue
                    if src and r.get("src") != src:
                        continue
                    if kind and not re.search(kind, str(r.get("kind", ""))):
                        continue
                    if chat and r.get("chat") != chat:
                        continue
                    if since and r.get("t", 0) < since:
                        continue
                    if contains and contains.lower() not in line.lower():
                        continue
                    rows.append(r)
        except OSError:
            continue
    return rows[-max(1, int(n)):]


def fmt(r):
    t = time.strftime("%H:%M:%S", time.localtime(r.get("t", 0))) + f".{int((r.get('t', 0) % 1) * 1000):03d}"
    chat = f" [{r['chat'][-4:]}]" if r.get("chat") else ""
    d = json.dumps(r.get("d"), ensure_ascii=False) if r.get("d") else ""
    return f"{t} {r.get('src', '?'):6} {r.get('kind', '')}{chat} {d}".rstrip()


def clear():
    for f in _files():
        try:
            f.unlink()
        except OSError:
            pass
