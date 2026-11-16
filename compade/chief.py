"""Şef: kullanıcıyla konuşan tek rol. Plan istemi (sabit) + plan JSON ayrıştırma/doğrulama."""
import json
import re

MAX_TASKS = 12

CHIEF_SYSTEM = """# Compade — Şef görevi
Sen Compade ekibinin **şefisin** ({chief_name}). Kullanıcıyla sen konuşursun; alt roller kullanıcıyla konuşmaz.
İşin: kullanıcının isteğini analiz etmek, aşağıdaki rollerden uygun olanlara iş dağıtan bir PLAN üretmek.
Kendin kod yazma, dosya değiştirme; yalnız planla.

## Kullanılabilir roller (yalnız bunları kullan, uydurma rol yazma)
{roles}

## Plan kuralları
- Yanıtı Türkçe yaz. Önce 1-3 cümlelik kısa bir açıklama, sonra TEK bir ```json bloğu.
- Her görev tek bir role gider ve kendi başına anlaşılır olmalı: alt rol senin konuşmanı görmez, yalnız `instruction` alanını görür.
- `instruction` içinde: hedef, ilgili dosya/klasör yolları, beklenen çıktı biçimi, sınırlar (neye dokunma) yaz.
- Bağımsız işleri paralel bırak; yalnız gerçekten başka görevin çıktısına muhtaç olanlara `depends_on` ver.
- `write`: görev dosya değiştirecekse true, yalnız okuyup rapor yazacaksa false. Gereksiz yere true yapma.
- `difficulty`: easy (yazım, doküman, küçük tek dosya düzeltmesi, okuma/özet) | medium (tek özellik, sıradan hata) | hard (çok dosya, mimari, güvenlik, zor hata). Model seçimi buna göre yapılır; dürüst ver.
- En çok {max_tasks} görev. Basit iş için tek görev yeterlidir; rol sayısını şişirme.
- Kullanıcının isteği belirsizse ve plan çıkaramıyorsan `tasks` boş bırak, `question` alanında tek soru sor.

## JSON şeması
```json
{{
  "summary": "planın tek cümlelik özeti",
  "question": "",
  "tasks": [
    {{"id": "t1", "role": "rol-anahtarı", "instruction": "...", "write": false, "depends_on": [], "difficulty": "easy|medium|hard"}}
  ]
}}
```
"""


def roles_text(roles, chief):
    lines = []
    for k, r in roles.items():
        if k == chief:
            continue
        desc = (r.get("brief") or "").strip().replace("\n", " ")
        lines.append(f"- `{k}` — {r['name']}: {desc}" + (" [yazma izni var]" if r.get("write") else ""))
    return "\n".join(lines) or "(tanımlı rol yok)"


def system_prompt(roles, chief):
    c = roles.get(chief, {})
    return CHIEF_SYSTEM.format(chief_name=c.get("name", "Şef"), roles=roles_text(roles, chief), max_tasks=MAX_TASKS)


def plan_prompt(user_msg, roles, chief, history=(), cwd="", files=(), brief=None):
    parts = [system_prompt(roles, chief)]
    if cwd:
        parts.append(f"## Çalışma klasörü\n{cwd}")
    if files:
        parts.append("## Kullanıcının eklediği dosyalar\n" + "\n".join(f"- {f}" for f in files))
    if brief is not None:
        parts.append("## Önceki konuşma özeti\n" + brief[:1200])
    elif history:
        parts.append("## Önceki konuşma\n" + "\n".join(f"**{h['who']}:** {h['text']}" for h in history))
    parts.append("## Kullanıcının yeni isteği\n" + user_msg.strip())
    return "\n\n".join(parts) + "\n"


def discuss_prompt(user_msg, roles, chief, brief="", history=(), cwd="", files=()):
    """Kompakt konuşma istemi; sabit rol bağlamı başta tutulur."""
    c = roles.get(chief, {})
    role_lines = []
    for key, role in roles.items():
        if key == chief:
            continue
        desc = (role.get("brief") or "").strip().replace("\n", " ")
        role_lines.append(f"{key} — {role.get('name', key)}" + (f": {desc[:80]}" if len(roles) <= 13 else ""))
    system = ["Compade şefisin. Kullanıcıyla Türkçe konuş; kısa tut.",
              "İsteği anladığını söyle, en çok 3 net soru sor ve yaklaşım öner.",
              "Plan/rol dağılımı veya plan JSON'u üretme.",
              'Yanıtın sonuna tek JSON bloğu ekle: {"ready": bool, "brief": "..."}.',
              "ready yalnız kapsam, dosyalar ve kısıtlar netleşince true olsun.",
              "brief en çok 1200 karakterlik yuvarlanan karar/bağlam özetidir.",
              "Kullanılabilir roller:"] + role_lines
    parts = ["\n".join(system)]
    if cwd:
        parts.append("Çalışma klasörü: " + cwd)
    if files:
        parts.append("Ek dosyalar: " + ", ".join(files))
    if brief:
        parts.append("Önceki özet:\n" + brief[:1200])
    turns = list(history)[-6:]
    if turns:
        parts.append("Son 3 tur:\n" + "\n".join(f"{h['who']}: {h['text'][:800]}" for h in turns))
    parts.append("Yeni kullanıcı mesajı:\n" + user_msg.strip())
    return "\n\n".join(parts) + "\n"


def extract_discuss(text):
    data = extract_json(text)
    if not isinstance(data, dict) or not isinstance(data.get("ready"), bool):
        raise ValueError("Şef yanıtında ready/brief JSON'u bulunamadı")
    return {"ready": data["ready"], "brief": str(data.get("brief") or "")[:1200]}


def extract_summary(text):
    m = re.search(r"^##\s*Özet\s*\n(.*?)(?=^##\s|\Z)", text or "", re.S | re.M | re.I)
    return m.group(1).strip() if m else ""


def summary_prompt(user_msg, plan, results):
    out = ["# Compade — Şef: sonuç özeti",
           "Kullanıcının isteği ve alt rollerin sonuçları aşağıda. Türkçe, kısa ve dürüst bir özet yaz: "
           "ne yapıldı, ne başarısız oldu, kullanıcının karar vermesi gereken ne var. Sonuçlarda olmayan bir şeyi uydurma.",
           "## İstek\n" + user_msg.strip(), "## Plan\n" + (plan.get("summary") or "")]
    for r in results:
        raw = r.get("output") or ""
        short = extract_summary(raw) or raw
        out.append(f"### {r['id']} ({r['role']}) — {r['status']}\n{short[:1500]}")
    return "\n\n".join(out) + "\n"


_FENCE = re.compile(r"```(?:[\w-]+)?\s*(\{.*?\})\s*```", re.S)


def extract_json(text):
    """Yanıttaki son JSON bloğunu (ya da çıplak en dıştaki nesneyi) bulur."""
    cands = _FENCE.findall(text or "")[::-1]
    if not cands and text and "{" in text and "}" in text:
        cands = [text[text.index("{"): text.rindex("}") + 1]]
    for c in cands:
        try:
            return json.loads(c)
        except ValueError:
            continue
    raise ValueError("Yanıtta geçerli bir JSON planı bulunamadı")


def validate_plan(plan, roles, chief):
    """Planı doğrular, temizlenmiş halini döner. Hata: ValueError (Türkçe, şefe geri verilebilir)."""
    if not isinstance(plan, dict):
        raise ValueError("Plan bir JSON nesnesi olmalı")
    tasks = plan.get("tasks") or []
    question = str(plan.get("question") or "").strip()
    if not isinstance(tasks, list):
        raise ValueError("`tasks` bir liste olmalı")
    if not tasks:
        if not question:
            raise ValueError("Plan boş: görev yok ve soru da yok")
        return {"summary": str(plan.get("summary") or ""), "question": question, "tasks": [], "levels": []}
    if len(tasks) > MAX_TASKS:
        raise ValueError(f"En çok {MAX_TASKS} görev olabilir, {len(tasks)} verildi")
    ids, clean = set(), []
    for i, t in enumerate(tasks, 1):
        if not isinstance(t, dict):
            raise ValueError(f"Görev {i} bir nesne olmalı")
        tid = str(t.get("id") or f"t{i}")
        if tid in ids:
            raise ValueError(f"Yinelenen görev kimliği: {tid}")
        role = t.get("role")
        if role not in roles:
            raise ValueError(f"{tid}: bilinmeyen rol {role!r}")
        if role == chief:
            raise ValueError(f"{tid}: şef kendine görev veremez")
        ins = str(t.get("instruction") or "").strip()
        if not ins:
            raise ValueError(f"{tid}: `instruction` boş")
        dep = t.get("depends_on") or []
        if not isinstance(dep, list):
            raise ValueError(f"{tid}: `depends_on` liste olmalı")
        ids.add(tid)
        item = {"id": tid, "role": role, "instruction": ins, "write": bool(t.get("write", False)),
                "depends_on": [str(d) for d in dep]}
        if str(t.get("difficulty") or "").lower() in ("easy", "medium", "hard"):
            item["difficulty"] = str(t["difficulty"]).lower()
        clean.append(item)
    for t in clean:
        for d in t["depends_on"]:
            if d not in ids:
                raise ValueError(f"{t['id']}: bilinmeyen bağımlılık {d!r}")
            if d == t["id"]:
                raise ValueError(f"{t['id']}: kendine bağlı")
    return {"summary": str(plan.get("summary") or ""), "question": "", "tasks": clean, "levels": topo_levels(clean)}


def topo_levels(tasks):
    """Bağımlılık katmanları: her katman paralel çalışabilir. Döngüde ValueError."""
    left = {t["id"]: set(t["depends_on"]) for t in tasks}
    levels = []
    while left:
        ready = sorted(k for k, d in left.items() if not d)
        if not ready:
            raise ValueError("Görev bağımlılıklarında döngü var: " + ", ".join(sorted(left)))
        levels.append(ready)
        for k in ready:
            del left[k]
        for d in left.values():
            d.difference_update(ready)
    return levels


_OUT = re.compile(r"^##\s*\d*\.?\s*[ÇCç]\w*kt\w*[^\n]*\n(.*?)(?=^##\s*\d*\.?\s|\Z)", re.S | re.M)


def extract_output(text):
    """Rol başlığının teslim biçimindeki ('## 2. Çıktı') bölümünü döner; bulunamazsa metnin kendisini."""
    m = _OUT.search(text or "")
    return (m.group(1).strip() if m and m.group(1).strip() else (text or "").strip())


def parse_report(text):
    """Alt rolün compade-report bloğunu doğrular; bozuk/yoksa None."""
    matches = re.findall(r"```compade-report\s*(\{.*?\})\s*```", text or "", re.S)
    if not matches:
        return None
    try:
        data = json.loads(matches[-1])
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("status") not in ("done", "blocked", "failed", "needs_input"):
        return None
    files = data.get("files", [])
    if not isinstance(files, list):
        return None
    return {"status": data["status"], "summary": str(data.get("summary") or "")[:300],
            "files": [str(x) for x in files], "needs": str(data.get("needs") or "")}


def parse_decision(text):
    matches = re.findall(r"```compade-decision\s*(\{.*?\})\s*```", text or "", re.S)
    if not matches:
        return None
    try:
        data = json.loads(matches[-1])
    except (ValueError, TypeError):
        return None
    if not isinstance(data, dict) or data.get("action") not in ("retry", "reassign", "ask_user", "abort", "continue"):
        return None
    return {"action": data["action"], "task": str(data.get("task") or ""), "role": str(data.get("role") or ""), "message": str(data.get("message") or "")}


def _norm_questions(items):
    """[{question, options[]}] — en çok 4 soru, soru başına en çok 6 kısa seçenek."""
    out = []
    for q in items if isinstance(items, list) else []:
        if isinstance(q, str):
            q = {"question": q}
        if not isinstance(q, dict):
            continue
        text = str(q.get("question") or q.get("q") or "").strip()
        if not text:
            continue
        opts = []
        for o in q.get("options") or []:
            label = o.get("label") if isinstance(o, dict) else o
            label = str(label or "").strip()
            if label and label not in opts:
                opts.append(label[:120])
        out.append({"question": text[:600], "options": opts[:6], "multi": bool(q.get("multi") or q.get("multiSelect"))})
        if len(out) == 4:
            break
    return out


def parse_questions(text):
    """Şef yanıtındaki ```compade-questions [...]``` bloğu (dizi ya da {"questions":[...]})."""
    matches = re.findall(r"```compade-questions\s*(\[.*?\]|\{.*?\})\s*```", text or "", re.S)
    if not matches:
        return None
    try:
        data = json.loads(matches[-1])
    except (ValueError, TypeError):
        return None
    if isinstance(data, dict):
        data = data.get("questions")
    return _norm_questions(data) or None


def questions_from_tool(tool_input):
    """Claude'un AskUserQuestion aracı girdisi -> aynı biçim (araç -p kipinde yanıt alamaz; soruyu kullanıcıya biz sorarız)."""
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except ValueError:
            return None
    return _norm_questions((tool_input or {}).get("questions") if isinstance(tool_input, dict) else None) or None
