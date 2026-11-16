"""İşe göre model seçimi (akıllı yönlendirme).

Her görev için zorluk (easy|medium|hard) belirlenir: şef planda verdiyse o, yoksa sezgisel.
Politika (cfg.routing: off|saver|balanced|quality) zorluğu bir model kademesine (cheap|mid|strong) ve
düşünme seviyesine (low|medium|high) çevirir. Model YALNIZ rolün kendi model listesinden seçilir; rolde tek
model varsa ya da rol `pin_model` ise dokunulmaz. Yeniden denemede zorluk bir kademe artar (ucuzdan güçlüye).
"""
import re

LEVELS = ("easy", "medium", "hard")
TIERS = ("cheap", "mid", "strong")
POLICY = {   # zorluk -> (kademe, düşünme)
    "saver":    {"easy": ("cheap", "low"), "medium": ("cheap", "medium"), "hard": ("mid", "high")},
    "balanced": {"easy": ("cheap", "low"), "medium": ("mid", "medium"), "hard": ("strong", "high")},
    "quality":  {"easy": ("mid", "medium"), "medium": ("strong", "high"), "hard": ("strong", "high")},
}
EFFORT_RUNTIMES = {"codex", "claude"}

HARD = re.compile(r"mimari|architect|refactor|yeniden yapılandır|güvenlik|security|migration|göç|concurren|eşzaman|"
                  r"performans|performance|optimiz|hata ayıkla|debug|race|kilitlen|deadlock|şifrele|encrypt|"
                  r"birden (çok|fazla) dosya|tüm proje|bütün proje|baştan yaz|sıfırdan", re.I)
EASY = re.compile(r"yazım|typo|imla|çevir|translate|readme|doküman|dokuman|belge|yorum satırı|comment|yeniden adlandır|"
                  r"rename|özetle|özet çıkar|summar|listele|renk|color|metin değiştir|başlığı değiştir|format", re.I)


def tier_of(model_key, model):
    """Modelin kademesi: açık `tier` alanı > ad sezgisi."""
    t = (model or {}).get("tier")
    if t in TIERS:
        return t
    name = f"{model_key} {(model or {}).get('id', '')}".lower()
    if re.search(r"free|ollama|flash|small|mini|-mini|nano|haiku|oss|-oss|lite", name):
        return "cheap"
    if re.search(r"opus|thinking|gpt-6|\bpro\b|-pro|ultra|max", name):
        return "strong"
    if (model or {}).get("runtime") == "codex" and (model or {}).get("id") in (None, "", "default"):
        return "strong"
    return "mid"


def difficulty(task, write=None):
    d = str(task.get("difficulty") or "").lower()
    if d in LEVELS:
        return d
    text = task.get("instruction") or ""
    w = task.get("write") if write is None else write
    if HARD.search(text) or len(text) > 1500:
        return "hard"
    if EASY.search(text) and len(text) < 600:
        return "easy"
    if not w and len(text) < 300:
        return "easy"
    return "medium"


def bump(level, steps=1):
    return LEVELS[min(len(LEVELS) - 1, LEVELS.index(level) + steps)]


def choose(roles, role_key, task, policy="balanced", attempt=0, write=False, usable=lambda mk: True):
    """Dönüş: {"model","effort","difficulty","tier","reason"} ya da None (yönlendirme yok → rolün ilk modeli)."""
    if policy not in POLICY:
        return None
    role = roles["roles"].get(role_key) or {}
    models = [mk for mk in role.get("models") or [] if mk in roles["models"]
              and roles["models"][mk].get("runtime") not in ("manual", None) and usable(mk)]
    level = bump(difficulty(task, write), attempt) if attempt else difficulty(task, write)
    want, effort = POLICY[policy][level]
    if write and want == "cheap":
        want = "mid"            # yazma işi ücretsiz/küçük modele verilmez (rolde başka seçenek varsa)
    if not models:
        return None
    if role.get("pin_model") or len(models) == 1:
        mk = models[0]
        reason = "rol modeli sabit" if role.get("pin_model") else "rolün tek modeli"
    else:
        order = {t: i for i, t in enumerate(TIERS)}
        target = order[want]
        # tam eşleşme > bir üst kademe > bir alt kademe; eşitlikte rol sırası (kullanıcının tercihi)
        def score(mk):
            diff = order[tier_of(mk, roles["models"][mk])] - target
            return (abs(diff), 0 if diff > 0 else 1, models.index(mk))
        mk = min(models, key=score)
        reason = f"{ {'easy': 'kolay', 'medium': 'orta', 'hard': 'zor'}[level] } iş → {want} kademe"
        if attempt:
            reason += f" (yeniden deneme {attempt}: kademe yükseltildi)"
    runtime = roles["models"][mk].get("runtime")
    return {"model": mk, "effort": effort if runtime in EFFORT_RUNTIMES else None, "difficulty": level,
            "tier": tier_of(mk, roles["models"][mk]), "reason": reason}


def chief_effort(kind, policy="balanced"):
    """Şef (Claude Code) turu için düşünme seviyesi: sohbet hafif, plan/karar derin."""
    if policy not in POLICY:
        return None
    if kind in ("plan", "decision"):
        return "high" if policy != "saver" else "medium"
    return "low" if policy == "saver" else "medium"
