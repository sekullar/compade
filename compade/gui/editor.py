"""İsteğe bağlı metin editörü: satır numaraları, aç/kaydet, Ctrl+S."""
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import widgets as w


class EditorPage(tk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, bg=app.th.c["bg"])
        self.app, th = app, app.th
        self.path = None
        c = th.c
        bar = tk.Frame(self, bg=c["bg"])
        bar.pack(fill="x", pady=(0, 8))
        for txt, cmd, prim in (("Aç", self.open, False), ("Yeni", self.new, False), ("Kaydet", self.save, True),
                               ("Farklı kaydet", self.save_as, False), ("Kopyala", self.copy, False)):
            w.button(bar, th, txt, cmd, primary=prim).pack(side="left", padx=(0, 6))
        self.title = tk.Label(bar, text="Adsız", bg=c["bg"], fg=c["text_muted"], font=th.font("ui", "body"))
        self.title.pack(side="left", padx=10)

        body = tk.Frame(self, bg=c["editor_bg"], highlightbackground=c["border"], highlightthickness=1)
        body.pack(fill="both", expand=True)
        self.sb = ttk.Scrollbar(body, orient="vertical", command=self._yview)
        self.sb.pack(side="right", fill="y")
        self.nums = tk.Text(body, width=5, bg=c["editor_bg"], fg=c["editor_linenum"], relief="flat", bd=0,
                            font=th.font("mono", "mono"), padx=6, pady=6, state="disabled", cursor="arrow",
                            takefocus=0, highlightthickness=0)
        self.nums.pack(side="left", fill="y")
        self.text = tk.Text(body, bg=c["editor_bg"], fg=c["editor_fg"], insertbackground=c["editor_fg"],
                            selectbackground=c["editor_selection"], relief="flat", bd=0, undo=True, wrap="none",
                            font=th.font("mono", "mono"), padx=8, pady=6, yscrollcommand=self._on_scroll,
                            highlightthickness=0, spacing1=2, spacing3=2)
        self.nums.configure(spacing1=2, spacing3=2)
        self.text.pack(side="left", fill="both", expand=True)
        self.text.bind("<<Modified>>", self._modified)
        self.text.bind("<Control-s>", lambda e: (self.save(), "break")[1])
        self.text.bind("<Control-o>", lambda e: (self.open(), "break")[1])
        self._renumber()

    def _yview(self, *a):
        self.text.yview(*a)
        self.nums.yview(*a)

    def _on_scroll(self, lo, hi):
        self.sb.set(lo, hi)
        self.nums.yview_moveto(lo)

    def _modified(self, _e=None):
        if self.text.edit_modified():
            self._renumber()
            name = self.path.name if self.path else "Adsız"
            self.title.config(text=f"{name} •")
        self.text.edit_modified(False)

    def _renumber(self):
        n = int(self.text.index("end-1c").split(".")[0])
        self.nums.config(state="normal")
        self.nums.delete("1.0", "end")
        self.nums.insert("1.0", "\n".join(str(i) for i in range(1, n + 1)))
        self.nums.tag_configure("r", justify="right")
        self.nums.tag_add("r", "1.0", "end")
        self.nums.config(state="disabled")
        self.nums.yview_moveto(self.text.yview()[0])

    def load_path(self, p):
        p = Path(p)
        try:
            data = p.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            data = p.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            messagebox.showerror("Compade", f"Dosya açılamadı:\n{e}")
            return
        self.text.delete("1.0", "end")
        self.text.insert("1.0", data)
        self.text.edit_reset()
        self.path = p
        self.title.config(text=p.name)
        self._renumber()

    def open(self):
        f = filedialog.askopenfilename(title="Dosya aç")
        if f:
            self.load_path(f)

    def new(self):
        self.text.delete("1.0", "end")
        self.path = None
        self.title.config(text="Adsız")
        self._renumber()

    def save(self):
        if not self.path:
            return self.save_as()
        try:
            self.path.write_text(self.text.get("1.0", "end-1c"), encoding="utf-8")
            self.title.config(text=self.path.name)
            self.app.status("Kaydedildi: " + self.path.name)
        except OSError as e:
            messagebox.showerror("Compade", f"Kaydedilemedi:\n{e}")

    def save_as(self):
        f = filedialog.asksaveasfilename(title="Farklı kaydet")
        if f:
            self.path = Path(f)
            self.save()

    def copy(self):
        self.clipboard_clear()
        self.clipboard_append(self.text.get("1.0", "end-1c"))
        self.app.status("Panoya kopyalandı")

    def refresh(self):
        pass
