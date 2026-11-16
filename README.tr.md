# Compade

**Compade** = *Company* (şirket) + *ADE* (Agentic Development Environment). Bir şef ajanın (Claude Code) küçük bir
şirket gibi bir kodlama ekibini yönettiği Windows masaüstü uygulaması. Şef işi planlar, her görevi uygun role verir,
sonucu denetler ve sıradaki adıma karar verir. Çalışanlar zaten kullandığın kodlama araçlarıdır: **Codex CLI**,
**OpenCode** (ücretsiz modelleri dahil) ve **Antigravity / Gemini CLI**. Amaç, şefin (Claude'un) token'ını olabildiğince
az harcayarak gerçek iş çıkarmak.

[English README](README.md)

## Özellikler

- **Şef sohbeti (Ofis).** Şefle Claude Code'daki gibi konuşursun. Yanıt verir, soru sorar ya da plan yazar (görevler,
  roller, bağımlılıklar, zorluk). Planı sen onaylarsın ya da otomatik çalışır.
- **Karar döngüsü.** Her görevden sonra şef çalışanın raporunu okur ve karar verir: kabul et, düzeltmeyle yeniden dene,
  başka role ver, sana sor ya da durdur. Yeniden deneme sayısı sınırlıdır.
- **Git worktree ile güvenli yazma.** Git projesinde her yazma görevi `~/.compade/worktrees/` altında kendi dalında
  çalışır. Sen onaylayana kadar klasörüne dokunulmaz. Her görevden sonra projenin testleri kendiliğinden çalışır
  (pytest, unittest, npm test, cargo, go ya da kendi komutun). Testten geçmeyen iş birleştirilmez.
- **Değişiklikler kartı.** Değişen her dosyayı renkli farkıyla görürsün; seçtiklerini ya da hepsini uygular veya
  atarsın.
- **İşe göre model seçimi.** Her görevin bir zorluğu vardır. Politika (tasarruf / dengeli / kalite) bunu rolün kendi
  model listesinden ucuz, orta ya da güçlü bir modele ve Codex ile Claude için bir düşünme seviyesine çevirir. Yeniden
  denemede bir kademe yükselir. Rolde başka seçenek varsa yazma işi ücretsiz modele verilmez.
- **Roller ve ekip.** Kendi model listeleriyle roller tanımlarsın (backend, QA, tasarım...) ya da şefe proje için ekip
  kurdurursun. Rol başına model sabitlenebilir.
- **Çoklu hesap.** Birden çok Codex hesabı (her biri ayrı `CODEX_HOME`) ve birden çok Antigravity girişi. Bir hesap
  sınıra dayanınca iş sıradaki hesaba ya da yedek sağlayıcıya geçer.
- **Maliyet sayfası.** Sağlayıcıların bildirdiği gerçek token sayıları, şefin API eşdeğeri dolar maliyeti, günlük
  grafik, başarı oranlarıyla model ve rol tabloları.
- **Proje hafızası.** Proje kökündeki `COMPADE.md` her çalışanın talimatına eklenir.
- **Kolaylıklar.** Sohbet geçmişi, şef meşgulken mesaj kuyruğu, iş şablonları, pencere arka plandayken masaüstü
  bildirimi, açık/koyu tema.
- **Güncelleme.** Compade GitHub sürümlerini denetler ve durum çubuğunda **Güncelle** düğmesi gösterir
  (bkz. [Güncelleme](#güncelleme)).

## Gerekenler

- Windows 10 ya da 11.
- Microsoft Edge (Compade penceresini Edge uygulama penceresi olarak açar; `compade web --no-window` ile her tarayıcı
  çalışır).
- Şef için giriş yapılmış [Claude Code](https://docs.anthropic.com/en/docs/claude-code).
- En az bir çalışan aracı: [Codex CLI](https://github.com/openai/codex), [OpenCode](https://opencode.ai) ya da
  Antigravity (`agy`).
- Yalıtılmış yazma için Git (git yoksa Compade yine plan yapar ve salt okunur görevleri çalıştırır).

## Kurulum

**Kurulum dosyası:** [son sürümden](../../releases/latest) `Compade-Setup-<sürüm>.exe` dosyasını indirip çalıştır.
Yönetici izni istemeden `%LOCALAPPDATA%\Programs\Compade` klasörüne kurulur. Kurulum dosyası imzalı olmadığı için
Windows SmartScreen onay isteyebilir ("Ek bilgi" → "Yine de çalıştır").

**Sentinel Hub:** Compade, [Sentinel Hub](https://github.com/sekullar/sentinel-hub) kataloğunda da var. Hub kurar,
günceller ve başlatır.

**Kaynaktan** (Python 3.13, yalnız standart kütüphane):

```bash
git clone https://github.com/sekullar/compade.git
cd compade
python -m compade                 # uygulamayı açar
python -m compade web --no-window --port 8778   # yalnız sunucu; http://127.0.0.1:8778 adresini kendin aç
```

## Güncelleme

Compade kendi sürümünü GitHub'daki son sürümle karşılaştırır (açılışta ve 6 saatte bir; hemen denetlemek için durum
çubuğundaki sürüm yazısına tıkla). **Güncelle** düğmesinin yaptığı iş kurulum biçimine bağlıdır:

| Nasıl kuruldu | Güncelleme |
| --- | --- |
| Compade kurulum dosyası | Yeni kurulum dosyasını bu deponun sürümlerinden indirir, sessizce kurar, Compade'i yeniden açar. |
| Sentinel Hub | Hub kendi yeşil **Güncelle** düğmesini gösterir ve güncellemeyi o yapar. |
| Kaynak kod | Sürüm sayfasını açar; `git pull` ile güncellersin. |

`~/.compade` içindeki verilerine (hesaplar, sohbetler, geçmiş) güncelleme de kaldırma da dokunmaz.

## Veri

Her şey `~/.compade/` altında (taşımak için `COMPADE_HOME`): `config.json`, `roles.json`, `ledger.jsonl` (her işin
token ve süresi), `runs/`, `chats/`, `accounts/`, `worktrees/`. Araçların giriş jetonları Compade'in kayıtlarına ya da
arayüzüne hiç alınmaz; yalnız hesap e-postası ve planı gösterilir.

## Komut satırı

```bash
python -m compade run --task gorev.md --model codex [--role backend] [--write] [--verify "npm test"]
python -m compade accounts        # hesaplar ve limit durumu
python -m compade ledger          # model başına geçmiş
python -m compade ram             # bellek kullanımı
python -m unittest discover -s tests
```

## Derleme ve sürüm yayınlama (geliştirici notları)

```bash
pip install pyinstaller
python packaging/build.py   # dist/Compade/Compade.exe ve dist/Compade-Setup-<sürüm>.exe (NSIS gerekir)
```

Sürüm çıkarmak için `compade/__init__.py` içindeki `__version__` değerini artır, commit at, sonra aynı etiketi gönder:

```bash
git tag v0.1.1 && git push origin v0.1.1
```

GitHub Actions kurulum dosyasını derleyip sürümü yayınlar. Kurulu kopyalar ve Sentinel Hub bir sonraki denetimde görür.

## Bilinen sınırlar

- Büyük bir projede gerçek modellerle uçtan uca henüz denenmedi; testler sahte ajanlarla çalışır.
- Codex ve Antigravity'nin limit mesajları, gerçekleri görülene kadar genel desenlerle yakalanır.
- Sağlayıcı sınırlarını aşmak için birden çok hesap kullanmak sağlayıcının kullanım şartlarına aykırı olabilir;
  sorumluluk kullanıcıdadır.

## Lisans

MIT
