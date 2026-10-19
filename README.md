# Seen Tool

RealLive `Seen.txt` arşiv çözücü, çeviri editörü ve yeniden paketleyici (Türkçe karakter desteği).

## EXE'yi GitHub'dan derleme

1. GitHub'da yeni bir depo oluştur ve bu klasörün **tüm içeriğini** (gizli `.github` klasörü dahil) yükle.
2. `main` dalına push et. **Actions** sekmesinde "Build EXE" otomatik başlar (yaklaşık 2-3 dk).
3. Bittiğinde çalıştırmanın sayfasındaki **Artifacts → SeenTool-windows** dosyasını indir.
   - `SeenTool.exe` : arayüz (çift tıkla)
   - `SeenTool-cli.exe` : komut satırı (`SeenTool-cli.exe build Seen.txt proje.json Yeni_Seen.txt`)
4. Kalıcı indirme bağlantısı için sürüm etiketi at:
   ```
   git tag v1.0.0
   git push origin v1.0.0
   ```
   Exe'ler deponun **Releases** bölümüne otomatik eklenir.

Elle başlatmak için: **Actions → Build EXE → Run workflow**.

## Yerelde derleme (Windows)

Python 3.8+ kurulu olmalı. `build_exe.bat` dosyasını çalıştır; çıktılar `dist\` içine gelir.

## Notlar

- Windows Defender / SmartScreen, PyInstaller ile üretilmiş imzasız exe'lere bazen yanlış uyarı verir. Bu normaldir; kendi derlemenizse "Yine de çalıştır" diyebilirsiniz.
- `Seen.txt` gibi oyun dosyalarını depoya yükleme (`.gitignore` bunları dışarıda tutar).

## Arayüz

- Modern görünüm için `pip install sv-ttk` (ya da `pip install -r requirements.txt`). Kurulu değilse araç kendi düz temasını kullanır, işlevler aynıdır.
- Açık/koyu tema: araç çubuğundaki **◐ Tema** düğmesi ya da **Görünüm → Koyu tema**. Seçiminiz `~/.seen_tool.json` dosyasında saklanır.
- **Çevir** menüsü: bu satır, ilk 40 / ilk 400 boş satır, sahnenin tamamı. **▶ Oto çeviri** tüm sahneleri 40'ar satırla gezer.
- Çevirilmiş satırlar yeşilimsi görünür, sol listede sahneler ●/◐/○ ile ilerlemeyi gösterir, sahne kutusuna numara yazarak süzebilirsiniz.
