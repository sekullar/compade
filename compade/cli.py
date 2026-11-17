"""Komut satırı: argümansız çalıştırılırsa arayüz açılır.

  python -m compade                       # arayüz
  python -m compade run --task gorev.md --model codex [--model gemini] [--role backend] [--write] [--verify "npm test"]
  python -m compade accounts              # hesaplar ve limit durumu
  python -m compade accounts --add codex --label "Yedek"
  python -m compade ram                   # kendi RAM kullanımı
  python -m compade ledger                # model başına geçmiş özeti
"""
import argparse
import sys
import time

from . import config, ledger, limits, sysmon


def _out_utf8():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass


def cmd_accounts(args, eng):
    if args.add:
        a = eng.acc.add(args.add, args.label)
        print(f"Eklendi: {a['id']} ({a['label']})")
        if args.login:
            eng.acc.start_login(a)
            print("Giriş penceresi açıldı.")
        return
    for a in eng.acc.list():
        s = eng.acc.status(a)
        extra = ""
        if s.get("used") is not None:
            extra += f" · kullanım %{s['used']:.0f}"
        if s.get("resets_at"):
            extra += f" · sıfırlanma {limits.fmt_wait(s['resets_at'] - time.time())} sonra"
        act = " [aktif]" if a["provider"] == "agy" and a["id"] == eng.acc.agy_active() else ""
        print(f"{a['id']:14} {a['provider']:9} {a['label']:24} {s['state']:10}{extra}{act}")
    if getattr(args, "restore_agy", False):
        eng.acc.agy_restore_backup()
        print("Özgün agy girişi geri yüklendi.")
    if args.save_agy:
        eng.acc.agy_save_current(args.save_agy)
        print(f"agy'nin şu anki girişi '{args.save_agy}' hesabına kaydedildi.")


def cmd_run(args, eng):
    from pathlib import Path
    task = Path(args.task).read_text(encoding="utf-8")
    jobs, skipped = eng.plan(args.role or [], args.model or [], args.second, args.as_role)
    if not jobs:
        sys.exit("Dış çalışan yok (yalnız claude rolleri).")
    print("Başlatılan: " + ", ".join(j["tag"] for j in jobs))
    if skipped:
        print("Yöneticiye kalan: " + ", ".join(f"{s['role']}({s['model']})" for s in skipped))

    def ev(kind, d):
        if kind == "start":
            print(f"  ▶ {d['tag']} ← {d['model']} / hesap {d['account'] or '-'}", flush=True)
        elif kind == "limit":
            print(f"  ▲ {d['tag']}: {d['account']} limit doldu, sıradaki hesap/ajan denenecek", flush=True)
        elif kind == "fallback":
            print(f"  ↪ {d['tag']}: {d['from']} → {d['to']}", flush=True)
        elif kind == "done":
            r = d["result"]
            print(f"  [{r['status']}] {d['tag']} {r.get('seconds', 0)} sn {r.get('chars', 0)} karakter"
                  + (f" · doğrulama {r['verify']}" if r.get("verify") else ""), flush=True)

    run_dir, _ = eng.run(task, jobs, cwd=args.cwd, write=args.write, files=args.file or [], verify=args.verify,
                         name=args.name or Path(args.task).stem, timeout=args.timeout, on_event=ev)
    print(f"BİTTİ. Özet: {run_dir / 'digest.md'}  ·  Tam rapor: {run_dir / 'report.md'}")


def cmd_ram(_a, _e):
    mon = sysmon.Monitor(interval=0.5)
    mon.start()
    time.sleep(1.6)
    s = mon.stats()
    mon.stop()
    print(f"Compade süreci: {s['now_self']:.1f} MB · alt süreçler: {s['now_children']:.1f} MB ({s['child_count']} süreç)")
    print(f"Sistem: {s['system_used']:.0f} / {s['system_total']:.0f} MB")


def cmd_ledger(_a, _e):
    for k, v in sorted(ledger.summary(ledger.tail(1000)).items()):
        print(f"{k:22} iş {v['n']:3} · geçen %{v['pass']:3} · ort. {v['avg_sec']} sn")


def main(argv=None):
    _out_utf8()
    ap = argparse.ArgumentParser(prog="compade")
    sub = ap.add_subparsers(dest="cmd")
    r = sub.add_parser("run")
    r.add_argument("--task", required=True)
    r.add_argument("--role", action="append")
    r.add_argument("--model", action="append")
    r.add_argument("--as-role", dest="as_role")
    r.add_argument("--second", action="store_true")
    r.add_argument("--cwd")
    r.add_argument("--file", action="append")
    r.add_argument("--write", action="store_true")
    r.add_argument("--verify")
    r.add_argument("--name")
    r.add_argument("--timeout", type=int)
    a = sub.add_parser("accounts")
    a.add_argument("--add", choices=["codex", "agy"])
    a.add_argument("--label", default="")
    a.add_argument("--login", action="store_true")
    a.add_argument("--save-agy", dest="save_agy", metavar="HESAP_ID")
    a.add_argument("--restore-agy-backup", dest="restore_agy", action="store_true",
                   help="acil durum: ilk değişimden önceki özgün agy girişini geri yükle")
    sub.add_parser("ram")
    sub.add_parser("ledger")
    d = sub.add_parser("debug", help="geliştirici hata ayıklama günlüğünü oku")
    d.add_argument("-n", type=int, default=80, help="son kaç satır")
    d.add_argument("--src", choices=["server", "api", "ui"])
    d.add_argument("--kind", help="olay türü (regex)")
    d.add_argument("--chat", help="sohbet kimliği")
    d.add_argument("-q", dest="contains", help="satırda geçen metin")
    d.add_argument("-f", "--follow", action="store_true", help="yeni satırları izle")
    d.add_argument("--json", action="store_true")
    d.add_argument("--clear", action="store_true", help="günlüğü sil")
    g = sub.add_parser("gui", help="eski Tkinter arayüzü")
    g.add_argument("--selftest", action="store_true", help="pencereyi kurup kapat (kendini sına)")
    wb = sub.add_parser("web", help="web arayüzü (varsayılan)")
    wb.add_argument("--no-window", action="store_true", help="pencere açma, yalnız sunucuyu başlat")
    wb.add_argument("--port", type=int, default=0)
    args = ap.parse_args(argv)
    if args.cmd == "debug":
        import json
        import time as _t
        from . import debuglog
        if args.clear:
            debuglog.clear()
            print("günlük silindi")
            return 0
        flt = dict(src=args.src, kind=args.kind, chat=args.chat, contains=args.contains)
        show = (lambda r: print(json.dumps(r, ensure_ascii=False))) if args.json else (lambda r: print(debuglog.fmt(r)))
        rows = debuglog.read(args.n, **flt)
        for r in rows:
            show(r)
        last = rows[-1]["t"] if rows else _t.time()
        while args.follow:
            _t.sleep(1)
            fresh = [r for r in debuglog.read(500, **flt) if r["t"] > last]
            for r in fresh:
                show(r)
                last = r["t"]
        return 0
    if args.cmd == "gui":
        from .gui.app import run_gui
        return run_gui(selftest=getattr(args, "selftest", False))
    if args.cmd in (None, "web"):
        from .server import run_web
        return run_web(open_window=not getattr(args, "no_window", False), port=getattr(args, "port", 0))
    from .engine import Engine
    eng = Engine()
    {"run": cmd_run, "accounts": cmd_accounts, "ram": cmd_ram, "ledger": cmd_ledger}[args.cmd](args, eng)
    return 0
