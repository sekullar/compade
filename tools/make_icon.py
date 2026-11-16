"""Compade simgesini (C biçimli ofis bloğu + amber ajan masası) PNG ve ICO olarak üretir.

Kaynak çizim (256x256): design/logo.svg ile aynı geometri. Bağımlılık yok (zlib + struct).
Kullanım: python tools/make_icon.py
"""
import struct
import sys
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "compade" / "assets"
TEAL = (0x0F, 0x76, 0x6E)
AMBER = (0xF5, 0x9E, 0x0B)
# C gövdesi = üç dikdörtgenin birleşimi (SVG path'iyle aynı alan)
C_RECTS = [(48, 32, 208, 80), (48, 32, 96, 224), (48, 176, 208, 224)]
AMBER_RECT = (128, 104, 208, 152, 4)  # x0,y0,x1,y1,yarıçap


def in_rect(x, y, r):
    return r[0] <= x < r[2] and r[1] <= y < r[3]


def in_round(x, y, r):
    x0, y0, x1, y1, rad = r
    if not (x0 <= x < x1 and y0 <= y < y1):
        return False
    cx = min(max(x, x0 + rad), x1 - rad)
    cy = min(max(y, y0 + rad), y1 - rad)
    return (x - cx) ** 2 + (y - cy) ** 2 <= rad * rad


def render(size, ss=4):
    """RGBA bayt dizisi. Süper örnekleme ile kenar yumuşatma."""
    scale = 256 / size
    pix = bytearray()
    for py in range(size):
        for px in range(size):
            cov_c = cov_a = 0
            for sy in range(ss):
                for sx in range(ss):
                    x = (px + (sx + 0.5) / ss) * scale
                    y = (py + (sy + 0.5) / ss) * scale
                    if in_round(x, y, AMBER_RECT):
                        cov_a += 1
                    elif any(in_rect(x, y, r) for r in C_RECTS):
                        cov_c += 1
            n = ss * ss
            tot = cov_a + cov_c
            if tot == 0:
                pix += b"\x00\x00\x00\x00"
                continue
            col = tuple((TEAL[i] * cov_c + AMBER[i] * cov_a) // tot for i in range(3))
            pix += bytes(col) + bytes([min(255, 255 * tot // n)])
    return bytes(pix)


def png(size, rgba):
    def chunk(t, d):
        c = struct.pack(">I", len(d)) + t + d
        return c + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    raw = b"".join(b"\x00" + rgba[y * size * 4:(y + 1) * size * 4] for y in range(size))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    sizes = [16, 32, 48, 64, 128, 256]
    pngs = {s: png(s, render(s, ss=4 if s >= 128 else 6)) for s in sizes}
    (OUT / "compade.png").write_bytes(pngs[256])
    (OUT / "compade-64.png").write_bytes(pngs[64])
    head = struct.pack("<HHH", 0, 1, len(sizes))
    off = 6 + 16 * len(sizes)
    entries, blobs = b"", b""
    for s in sizes:
        d = pngs[s]
        entries += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(d), off + len(blobs))
        blobs += d
    (OUT / "compade.ico").write_bytes(head + entries + blobs)
    print("yazıldı:", ", ".join(p.name for p in sorted(OUT.glob("compade*"))))


if __name__ == "__main__":
    sys.exit(main())
