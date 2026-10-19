PROJEYİ ORİJİNAL SEEN'E TAŞIMA: Proje (JSON) çevrilmiş bir Seen dosyasından çıkarılmışsa:
   python Seen.py rebase eski.json orijinal_Seen.txt yeni.json
Çeviriler korunur, eski kodlar harfe çevrilir. Sonra hep orijinal Seen.txt + yeni.json ile derleyin.

ESKİ KODLU DOSYAYI ONARMA: Önceki araç sürümleriyle dışa aktarılmış bir Seen dosyanız varsa
(bazı satırlarda harfler kutu çıkıyorsa) dosyayı onar.bat'ın üstüne sürükleyip bırakın.
Yanına *_duzeltilmis.txt oluşur. ÖNEMLİ: Dışa aktarırken kaynak olarak her zaman ORİJİNAL Seen.txt'yi seçin.

GÜNCELLEME (v2): Harften sonra boşluk sorunu düzeltildi. Eski fontu kullanıyorsanız
font_kur.bat'ı OYUN KAPALIYKEN yeniden çalıştırın ve Seen.txt'yi yeniden dışa aktarın.
NOT: Font adı her kurulumda değişir (SeenGothicTR + tarih/saat). Gameexe.ini otomatik güncellenir;
kayıtlı bir font seçiminiz varsa oyundaki font ayarından yeni adı yeniden seçin.

OTOMATİK KURULUM: make_font.py ile aynı klasörde font_kur.bat dosyasına çift tıklayın.
Geri almak için: font_kur.bat /geri
(Aşağıdaki adımlar aynı işi elle yapmak içindir.)

TÜRKÇE HARFLİ FONT KURULUMU (CLANNAD Steam, Windows)
=====================================================
Fikir: Seen.txt'ye Türkçe harfler 12 tek baytlık Shift-JIS koduna (A1-AC) yazılır.
(Tek bayt olduğu için oyun yarım genişlik ayırır, harften sonra boşluk kalmaz.)
make_font.py, Windows'taki MS Gothic'in kendi ğ ş ı İ ç ö ü glifleriyle bu
kodları dolduran "SeenGothicTR" adlı bir kopya üretir. Oyun bu fontu adıyla kullanır.
(Sadece kendi bilgisayarınız için. MS Gothic Microsoft'undur, üretilen fontu paylaşmayın.)

1) Font üret
   pip install fonttools
   python make_font.py
   -> SeenGothicTR.ttf oluşur. "Bu fontta şu harfler yok" derse bana yazın.

2) Fontu kur
   SeenGothicTR.ttf dosyasına sağ tık -> Tüm kullanıcılar için yükle (ya da Yükle).

3) Oyunun Gameexe.ini dosyasını yedekle, sonra not defteriyle aç.
   "#INIT_FONT_TYPE=0" satırının altına şu iki satırı ekle:
       #ALL_FONT_USE=1
       #INIT_FONT_NAME="SeenGothicTR"
   (Oyunun exe'sinde bu iki ayar var; etkisini denemeden doğrulayamadım.)

4) Çeviri aracında "Türkçe karakter" kutusunu işaretle, dışa aktar,
   yeni Seen.txt'yi oyun klasörüne koy (orijinalin yedeğini al).

5) Oyunu aç. Hâlâ MS Gothic görünüyorsa oyundaki "Font ayarı" menüsünden
   (Gameexe'de SYSCOM.009) SeenGothicTR'yi seç.

Geri alma: Seen.txt ve Gameexe.ini yedeklerini geri koy, fontu Ayarlar > Yazı Tipleri'nden kaldır.
