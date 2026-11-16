"""compade/web/logos/*.svg dosyalarını compade/web/logos.js içine gömer (ağ isteği/titreme olmasın).

Kullanım: python tools/make_logos.py
Kaynak: @lobehub/icons-static-svg@1.84.0 (MIT). Marka işaretleri ilgili sahiplerine aittir.
"""
import json
import re
from pathlib import Path

WEB = Path(__file__).resolve().parent.parent / "compade" / "web"
SRC = WEB / "logos"

# anahtar -> (renkli dosya, tek renk dosya)
MAP = {
    "codex": ("codex-color", "codex"),
    "openai": ("openai", "openai"),
    "claude": ("claude-color", "claude"),
    "gemini": ("gemini-color", "gemini"),
    "agy": ("antigravity-color", "antigravity"),
    "antigravity": ("antigravity-color", "antigravity"),
    "opencode": ("opencode", "opencode"),
    "glm": ("glmv", "glmv"),
    "zhipu": ("zhipu", "zhipu"),
    "deepseek": ("deepseek-color", "deepseek"),
    "minimax": ("minimax-color", "minimax"),
    "nvidia": ("nvidia-color", "nvidia"),
    "nemotron": ("nvidia-color", "nvidia"),
    "longcat": ("longcat-color", "longcat"),
}
LABELS = {"codex": "Codex", "openai": "OpenAI", "claude": "Claude", "gemini": "Gemini", "agy": "Antigravity",
          "antigravity": "Antigravity", "opencode": "OpenCode", "glm": "GLM", "zhipu": "Zhipu", "deepseek": "DeepSeek",
          "minimax": "MiniMax", "nvidia": "NVIDIA", "nemotron": "Nemotron", "longcat": "LongCat"}


def inner(name):
    """SVG'nin iç içeriğini ve viewBox'ını döner (başlık/stil/boyut temizlenmiş)."""
    raw = (SRC / f"{name}.svg").read_text(encoding="utf-8")
    vb = re.search(r'viewBox="([^"]+)"', raw)
    body = re.sub(r"^.*?<svg[^>]*>", "", raw, flags=re.S)
    body = re.sub(r"</svg>\s*$", "", body.strip())
    body = re.sub(r"<title>.*?</title>", "", body, flags=re.S)
    return {"vb": vb.group(1) if vb else "0 0 24 24", "body": body.strip()}


def main():
    files = sorted({n for pair in MAP.values() for n in pair})
    data = {n: inner(n) for n in files if (SRC / f"{n}.svg").exists()}
    out = f"""/* Otomatik üretildi: python tools/make_logos.py. Elle düzenleme. */
(function () {{
  'use strict';
  const ICONS = {json.dumps(data, ensure_ascii=False)};
  const MAP = {json.dumps({k: list(v) for k, v in MAP.items()}, ensure_ascii=False)};
  const LABELS = {json.dumps(LABELS, ensure_ascii=False)};
  let uid = 0;
  function norm(key) {{
    const k = String(key || '').toLowerCase();
    if (MAP[k]) return k;
    for (const m of Object.keys(MAP)) if (k.startsWith(m)) return m;
    return '';
  }}
  function mono(letter, size) {{
    return `<svg class="lg lg-mono" width="${{size}}" height="${{size}}" viewBox="0 0 24 24" aria-hidden="true"><rect x="2" y="2" width="20" height="20" rx="5" fill="none" stroke="currentColor" stroke-width="1.5"/><text x="12" y="16.2" text-anchor="middle" font-size="11" font-weight="600" fill="currentColor" font-family="Segoe UI,system-ui,sans-serif">${{letter}}</text></svg>`;
  }}
  /** Ajan logosu (SVG dizgesi). opts.color=false -> tek renkli (currentColor). */
  function agent(key, size, opts) {{
    size = size || 16;
    const k = norm(key);
    if (!k) return mono(String(key || '?').charAt(0).toUpperCase(), size);
    const useColor = !opts || opts.color !== false;
    const name = MAP[k][useColor ? 0 : 1];
    const ic = ICONS[name] || ICONS[MAP[k][1]];
    if (!ic) return mono(LABELS[k].charAt(0), size);
    const id = 'lg' + (++uid);
    const body = ic.body.replace(/id="([^"]+)"/g, (m, a) => `id="${{id}}-${{a}}"`).replace(/url\\(#([^)]+)\\)/g, (m, a) => `url(#${{id}}-${{a}})`);
    return `<svg class="lg lg-${{k}}" width="${{size}}" height="${{size}}" viewBox="${{ic.vb}}" fill="currentColor" aria-hidden="true">${{body}}</svg>`;
  }}
  function label(key) {{
    const k = norm(key);
    return k ? LABELS[k] : String(key || '');
  }}
  function mark(size) {{
    size = size || 18;
    return `<svg class="lg lg-mark" width="${{size}}" height="${{size}}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" aria-hidden="true"><path d="M17.5 7.2A7 7 0 1 0 17.5 16.8"/><path d="M12 12h5"/></svg>`;
  }}
  window.Logos = {{ agent, label, mark }};
}}());
"""
    (WEB / "logos.js").write_text(out, encoding="utf-8", newline="\n")
    print("yazıldı:", WEB / "logos.js", len(out), "bayt;", len(data), "ikon")


if __name__ == "__main__":
    main()
