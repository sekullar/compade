# Compade hata notları (gözetimli çalıştırma, 2026-11-18)

Atlanabilen (işi durdurmayan) hatalar buraya yazılır, sonra toplu düzeltilir. Tıkayanlar anında düzeltilip yeniden başlatılır.

## Atlanabilir
- [ ] `GET /api/runs` iş sırasında ~0,4 istek/sn: her işçi olayı ağır yenileme tetikliyor (index.html soonRefresh + updateStatus içindeki api.runs).
- [ ] Görev etiketi yanıltıcı: t4 etiketi "agy-claude-opus-4-6-thinking", gerçek model codex:gpt-5.6-terra.
- [ ] İşçiler engellenen eylemi (Playwright file:, ana checkout okuma, worktree izin hatası) düz yazı raporla bildiriyor; izin kartı yok (kullanıcı istedi, sonra).
- [ ] Codex tek yamada aynı dosyayı birden çok kez düzenlemeye çalışıp "apply_patch ... multiple operations target" ile döngüye giriyor; çıktı 650 KB'a şişiyor (bekçi gerekli).

## Tıkayan (düzeltildi / düzeltilecek)
(aşağıya eklenir)
