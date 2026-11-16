"""Compade ana penceresi: sol menü + içerik + durum çubuğu. Ajan olayları kuyruktan okunur (arayüz donmaz)."""
import ctypes
import os
import queue
import time
import tkinter as tk

from .. import __version__, config, limits, sysmon
from ..engine import Engine
from ..theme import Theme
from . import widgets as w
from .editor import EditorPage
from .pages import AyarlarPage, CalismalarPage, HesaplarPage, OfisPage

NAV = [("ofis", "Ofis"), ("hesaplar", "Hesaplar"), ("calismalar", "Çalışmalar"), ("editor", "Editör"), ("ayarlar", "Ayarlar")]


def _dpi_aware():
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _dark_titlebar(win, dark):
    try:
        win.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(win.winfo_id())
        val = ctypes.c_int(1 if dark else 0)
        for attr in (20, 19):  # DWMWA_USE_IMMERSIVE_DARK_MODE (yeni / eski kimlik)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(val), 4)
    except Exception:
        pass


class App(tk.Tk):
    def __init__(self):
        _dpi_aware()
        super().__init__()
        self.cfg = config.load()
        self.engine = Engine(self.cfg)
        self.mon = sysmon.Monitor(interval=3.0)
        self.mon.start()
        self.q = queue.Queue()
        self.running = {}   # (run, tag) -> runtime
        self.page_name = os.environ.get("COMPADE_PAGE", "ofis")
        self.title("Compade")
        self.geometry("1180x760")
        self.minsize(960, 620)
        ico = config.ASSETS / "compade.ico"
        try:
            self.iconbitmap(str(ico))
        except Exception:
            try:
                self.iconphoto(True, tk.PhotoImage(file=str(config.ASSETS / "compade.png")))
            except Exception:
                pass
        self.build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.after(150, self.poll)
        self.after(3000, self.tick)

    # ---------- kurulum ----------
    def build(self, page=None):
        for ch in self.winfo_children():
            ch.destroy()
        self.th = Theme(self.cfg["theme"])
        self.th.resolve(self)
        w.style_ttk(self, self.th)
        _dark_titlebar(self, self.th.name == "dark")
        c = self.th.c
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        side = tk.Frame(self, bg=c["surface"], width=210, highlightbackground=c["border"], highlightthickness=0)
        side.grid(row=0, column=0, sticky="ns")
        side.grid_propagate(False)
        side.pack_propagate(False)
        brand = tk.Frame(side, bg=c["surface"])
        brand.pack(fill="x", padx=16, pady=(18, 18))
        w.draw_logo(brand, self.th, 30).pack(side="left")
        tb = tk.Frame(brand, bg=c["surface"])
        tb.pack(side="left", padx=10)
        w.label(tb, self.th, "Compade", "brand").pack(anchor="w")
        w.label(tb, self.th, "alt-ajan ekibi", "small", muted=True).pack(anchor="w")

        self.nav = {}
        for key, txt in NAV:
            if key == "editor" and not self.cfg["editor_enabled"]:
                continue
            row = tk.Frame(side, bg=c["surface"], cursor="hand2")
            row.pack(fill="x")
            bar = tk.Frame(row, width=3, bg=c["surface"])
            bar.pack(side="left", fill="y")
            lab = tk.Label(row, text=txt, bg=c["surface"], fg=c["text_muted"], anchor="w", padx=14, pady=9,
                           font=self.th.font("ui", "section", "bold"), cursor="hand2")
            lab.pack(side="left", fill="x", expand=True)
            for wd in (row, lab, bar):
                wd.bind("<Button-1>", lambda _e, k=key: self.show(k))
                wd.bind("<Enter>", lambda _e, k=key: self._hover(k, True))
                wd.bind("<Leave>", lambda _e, k=key: self._hover(k, False))
            self.nav[key] = (row, bar, lab)
        self.ram_lbl = tk.Label(side, text="", bg=c["surface"], fg=c["text_muted"], font=self.th.font("ui", "small"), anchor="w")
        self.ram_lbl.pack(side="bottom", fill="x", padx=16, pady=(0, 14))
        tk.Label(side, text=f"v{__version__}", bg=c["surface"], fg=c["text_muted"], font=self.th.font("ui", "small"),
                 anchor="w").pack(side="bottom", fill="x", padx=16)

        main = tk.Frame(self, bg=c["bg"])
        main.grid(row=0, column=1, sticky="nsew", padx=14, pady=(14, 8))
        main.rowconfigure(1, weight=1)
        main.columnconfigure(0, weight=1)
        self.heading = tk.Label(main, text="", bg=c["bg"], fg=c["text"], font=self.th.font("brand", "title", "bold"), anchor="w")
        self.heading.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        holder = tk.Frame(main, bg=c["bg"])
        holder.grid(row=1, column=0, sticky="nsew")
        holder.rowconfigure(0, weight=1)
        holder.columnconfigure(0, weight=1)
        self.pages = {"ofis": OfisPage(holder, self), "hesaplar": HesaplarPage(holder, self),
                      "calismalar": CalismalarPage(holder, self), "ayarlar": AyarlarPage(holder, self)}
        if self.cfg["editor_enabled"]:
            self.pages["editor"] = EditorPage(holder, self)
        for p in self.pages.values():
            p.grid(row=0, column=0, sticky="nsew")

        bar = tk.Frame(self, bg=c["surface"], height=26, highlightbackground=c["border"], highlightthickness=0)
        bar.grid(row=1, column=0, columnspan=2, sticky="ew")
        bar.grid_propagate(False)
        self.stat_lbl = tk.Label(bar, text="", bg=c["surface"], fg=c["text_muted"], font=self.th.font("ui", "small"), anchor="w", padx=12)
        self.stat_lbl.pack(side="left", fill="y")
        self.stat_ram = tk.Label(bar, text="", bg=c["surface"], fg=c["text_muted"], font=self.th.font("ui", "small"), padx=12)
        self.stat_ram.pack(side="right", fill="y")
        self.show(page if page in self.pages else self.page_name if self.page_name in self.pages else "ofis")
        self.status("Ofis hazır")
        self.update_ram()

    def rebuild(self, page=None):
        self.build(page or self.page_name)

    # ---------- gezinme ----------
    def _hover(self, key, on):
        row, bar, lab = self.nav[key]
        if key != self.page_name:
            lab.config(fg=self.th.c["text"] if on else self.th.c["text_muted"])

    def show(self, key):
        self.page_name = key
        c = self.th.c
        for k, (row, bar, lab) in self.nav.items():
            sel = k == key
            bar.config(bg=c["accent_fg"] if sel else c["surface"])
            row.config(bg=c["surface_alt"] if sel else c["surface"])
            lab.config(bg=c["surface_alt"] if sel else c["surface"], fg=c["text"] if sel else c["text_muted"])
        self.heading.config(text=dict(NAV)[key])
        self.pages[key].tkraise()
        self.pages[key].refresh()

    # ---------- durum ----------
    def status(self, text):
        self.stat_lbl.config(text="●  " + text)

    def running_count(self, runtime):
        return sum(1 for v in self.running.values() if v == runtime)

    def update_ram(self):
        s = self.mon.stats()
        if s:
            tot = s["now_self"] + s["now_children"]
            self.ram_lbl.config(text=f"RAM  {s['now_self']:.0f} MB")
            self.stat_ram.config(text=f"Compade {s['now_self']:.0f} MB · ajanlarla {tot:.0f} MB · ort. {s['avg_self']:.0f} MB")

    # ---------- iş akışı ----------
    def start_run(self, task, jobs, cwd, write, verify, name=None):
        self.status(f"{len(jobs)} iş başlatıldı")
        self.engine.submit(task, jobs, cwd=cwd, write=write, verify=verify, name=name,
                           on_event=lambda k, d: self.q.put((k, d)))

    def cancel(self):
        self.engine.cancel_all()
        self.pages["ofis"].add_log("Durdurma istendi: çalışan süreçler sonlandırılıyor.", "warn")

    def poll(self):
        ofis = self.pages["ofis"]
        changed = False
        try:
            while True:
                kind, d = self.q.get_nowait()
                changed = True
                tag = d.get("tag")
                if kind == "start":
                    rt = self.engine.roles["models"].get(d["model"], {}).get("runtime")
                    self.running[(d["run"], tag)] = rt
                    ofis.add_log(f"▶ {tag}  ←  {d['model']}" + (f"  (hesap {d['account']})" if d.get("account") else ""), "info")
                elif kind == "limit":
                    ofis.add_log(f"▲ {tag}: {d['account']} limiti doldu ({limits.fmt_wait(d['wait'])} bekleme). Sıradaki hesaba geçiliyor.", "warn")
                    self.status("Limit doldu, yedek hesaba geçildi")
                elif kind == "fallback":
                    ofis.add_log(f"↪ {tag}: {d['from']} hesapları doldu, {d['to']} modeline geçildi.", "warn")
                elif kind == "nohosts":
                    ofis.add_log(f"▲ {tag}: {d['model']} için kullanılabilir hesap yok.", "warn")
                elif kind == "done":
                    self.running.pop((d["run"], tag), None)
                    r = d["result"]
                    ok = r["status"] == "ok" and r.get("verify") in (None, "pass")
                    ofis.add_log(f"{'✔' if ok else '✖'} {tag}: {r['status']} · {r.get('seconds', 0)} sn · {r.get('chars', 0)} karakter"
                                 + (f" · doğrulama {r['verify']}" if r.get("verify") else "") + (f" · {r['note']}" if r.get("note") else ""),
                                 "ok" if ok else "err")
                elif kind == "finished":
                    ofis.add_log(f"Bitti. Rapor: {d['dir']}", "info")
                    self.status("İş tamamlandı")
        except queue.Empty:
            pass
        if changed:
            ofis.refresh()
            if self.page_name == "calismalar":
                self.pages["calismalar"].refresh()
        self.after(150, self.poll)

    def tick(self):
        self.update_ram()
        pg = self.pages.get(self.page_name)
        if self.page_name in ("ofis", "hesaplar", "ayarlar") and pg:
            pg.refresh()
        self.after(3000, self.tick)

    def on_close(self):
        if self.engine.active:
            from tkinter import messagebox
            if not messagebox.askyesno("Compade", "Çalışan işler var. Kapatırsanız durdurulur. Kapatılsın mı?"):
                return
            self.engine.cancel_all()
        self.mon.stop()
        self.destroy()


def run_gui(selftest=False):
    app = App()
    if selftest:
        for key in list(app.pages):
            app.show(key)
            app.update()
        app.update()
        print("GUI selftest OK:", ", ".join(app.pages))
        app.mon.stop()
        app.destroy()
        return 0
    app.mainloop()
    return 0
