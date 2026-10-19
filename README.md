# SeenTool

RealLive Seen.txt arşiv çözücü, çeviri editörü ve yeniden paketleyici (Türkçe karakter desteği).

## Windows için indir

- [SeenTool.exe — grafik arayüz](https://github.com/Ritsu-Tainaka/SeenTool/releases/latest/download/SeenTool.exe)
- [SeenTool-cli.exe — komut satırı](https://github.com/Ritsu-Tainaka/SeenTool/releases/latest/download/SeenTool-cli.exe)

Tüm sürümler: [GitHub Releases](https://github.com/Ritsu-Tainaka/SeenTool/releases)

## Kaynaktan çalıştırma

Python 3.8+ kurun. Bağımlılıkları yükleyip arayüzü başlatın:

```powershell
python -m pip install -r requirements.txt
python Seen.py
```

Komut satırı örneği:

```powershell
python Seen.py build Seen.txt proje.json Yeni_Seen.txt
```

## Özellikler

- Modern görünüm için `pip install sv-ttk` (veya `pip install -r requirements.txt`). Kurulu değilse araç kendi düz temasını kullanır.
- Açık/koyu tema: araç çubuğundaki **◐ Tema** düğmesi ya da **Görünüm → Koyu tema**. Seçiminiz `~/.seen_tool.json` dosyasında saklanır.
- **Çevir** menüsü: bu satır, ilk 40 / ilk 400 boş satır, sahnenin tamamı. **▶ Oto çeviri** tüm sahneleri 40'ar satırla gezer.
- Çevrilmiş satırlar yeşilimsi görünür; sahne ilerlemesi ●/◐/○ ile gösterilir ve sahne numarasıyla süzülebilir.

Oyun arşivi dosyalarını (ör. `Seen.txt`) depoya eklemeyin; `.gitignore` bunları dışarıda tutar.
