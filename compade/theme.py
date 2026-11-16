"""Tema: assets/theme.json içindeki jetonları (renk, yazı tipi, durum dili) yükler."""
import json
import tkinter.font as tkfont

from . import config


class Theme:
    def __init__(self, name="dark"):
        data = json.loads((config.ASSETS / "theme.json").read_text(encoding="utf-8"))
        self.name = name if name in ("dark", "light") else "dark"
        self.c = data[self.name]
        self.status = data["status"]
        self._fonts = data["fonts"]
        self.sizes = data["fonts"]["size"]
        self.family = {k: v[-1] for k, v in self._fonts.items() if k != "size"}

    def resolve(self, root):
        """Sistemde kurulu ilk yazı tipini seç (Plus Jakarta Sans yoksa Segoe UI Semibold...)."""
        avail = set(tkfont.families(root))
        for k, cands in self._fonts.items():
            if k == "size":
                continue
            self.family[k] = next((f for f in cands if f in avail), cands[-1])

    def font(self, kind="ui", size="body", weight="normal"):
        return (self.family[kind], self.sizes[size] if isinstance(size, str) else size, weight)

    def status_color(self, key):
        return self.c[self.status[key]["token"]]

    def status_text(self, key):
        s = self.status[key]
        return f"{s['symbol']} {s['label']}"
