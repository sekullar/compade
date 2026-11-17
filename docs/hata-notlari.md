# Compade hata notları (gözetimli çalıştırma, 2026-11-18)

Atlanabilen (işi durdurmayan) hatalar buraya yazılır, sonra toplu düzeltilir. Tıkayanlar anında düzeltilip yeniden başlatılır.

## Atlanabilir
- [x] `GET /api/runs` iş sırasında ~0,4 istek/sn: her işçi olayı ağır yenileme tetikliyor (index.html soonRefresh + updateStatus içindeki api.runs).
- [x] Görev etiketi yanıltıcı: t4 etiketi "agy-claude-opus-4-6-thinking", gerçek model codex:gpt-5.6-terra.
- [ ] İşçiler engellenen eylemi (Playwright file:, ana checkout okuma, worktree izin hatası) düz yazı raporla bildiriyor; izin kartı yok (kullanıcı istedi, sonra).
- [x] Codex tek yamada aynı dosyayı birden çok kez düzenlemeye çalışıp "apply_patch ... multiple operations target" ile döngüye giriyor; çıktı 650 KB'a şişiyor (bekçi gerekli).

## Tıkayan (düzeltildi / düzeltilecek)
(aşağıya eklenir)

## Tasarım bulguları (ahmetefekorkmazdev Faz 2, Playwright ile ölçüldü)
- Mobil (390px) index.html yatay taşma: `.demo-showcase`/`.browser-frame` 1280px genişlikte kalıyor (ölçekli iframe). Masaüstü index'te bir kaynak 404 veriyor (hangisi henüz bulunmadı).
- Ekran görüntüleri: ahmetefekorkmazdev-onizleme/faz2-ekran/*.png

## Compade notları
- Şef turu bağlam maliyeti yüksek: tek tur ~$2 (cache_read ~480k token).
- [x] Windows PowerShell komut satırında Türkçe karakterli arama metni bozuluyor (Codex `-match 'nasıl'` yanlış negatif verdi); şef "ön koşul yok" diye işi abort etti. Çözüm: şef/rol istemlerine "komutlarda ASCII ile ara, Türkçe karakter kullanma" kuralı ekle; şefin abort'tan önce kanıtı kontrol etmesi (tek başarısız ön koşul abort sebebi olmasın).

## Düzeltildi (2026-11-18 gece)
- Yenileme aralığı 4 sn; etiket yönlendirilen modeli yansıtıyor; Codex apply_patch döngü bekçisi (4 tekrar -> durdur); işçi ve şef istemine ASCII/Windows ipucu.
- Açık: izin/engellenen eylem kartı (kullanıcı istedi, sıradaki iş).
