Bu klasör Compade adlı bir Python masaüstü uygulaması (alt-ajan yönetimi). Şu dosyaları oku ve **gerçek hataları** bul:
- compade/accounts.py (hesap yönetimi; agy kimlik değişimi Windows Kimlik Yöneticisi üzerinden)
- compade/engine.py (ajan çalıştırma, limit dolunca hesap/ajan yedeklemesi)
- compade/limits.py (limit tespiti, bekleme süresi okuma, Codex oturum günlüğünden kullanım okuma)
- compade/wincred.py (ctypes ile CredRead/CredWrite)

Özellikle şunlara bak:
1. agy kimlik değişiminde (agy_activate, agy_prepare_login, agy_sync_back) kullanıcının kimliğini kaybetme/bozma riski, yarış durumu, yarım kalan yazma.
2. engine.execute içinde limit yedeklemesi: yanlış hesaba geçiş, sonsuz döngü, kilit (AGY_LOCK) bırakılmaması, iptal (cancel) sırasında takılma.
3. limits.is_limit_error yanlış pozitifleri (başarılı bir işi limit sanıp hesabı bekletmek) ve yanlış negatifleri.
4. wincred.py'da ctypes imza/bellek hataları (CredFree, işaretçi ömrü, 64-bit).
5. Çoklu iş parçacığı: Accounts.state'in eşzamanlı güncellenmesi.

Kurallar: Dosya değiştirme. Her bulgu için `dosya:satır`, sorunun tek cümlelik özeti, hangi girdi/durumda ne yanlış olur, ve önerilen düzeltmeyi yaz.
Emin olmadığını "olası" diye işaretle. Küçük üslup/stil önerisi yazma, yalnız doğruluk ve güvenlik sorunları.
En fazla 10 bulgu, en ciddiden başla.
