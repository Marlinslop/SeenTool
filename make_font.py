#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
make_font.py - Seen Tool için Türkçe harfli oyun fontu üretir.

Windows'taki MS Gothic'in KENDİ ğ ş ı İ ç ö ü glifleri, Shift-JIS'in tek baytlık
A1-AC kodlarına (yarım genişlikli katakana, U+FF61-FF6C) bağlanır ve font "SeenGothicTR"
adıyla kaydedilir. Böylece oyun bu harfleri yarım genişlikte yerleştirir (harf sonrası boşluk olmaz).
Üretilen font sadece sizin bilgisayarınız içindir, paylaşmayın (MS Gothic Microsoft'a aittir).

Kullanım:
    pip install fonttools
    python make_font.py                       # MS Gothic'i C:\\Windows\\Fonts'tan bulur
    python make_font.py girdi.ttc cikti.ttf   # elle belirtmek için
"""
import sys, os
from fontTools.ttLib import TTFont, TTCollection

FAMILY = 'SeenGothicTR'
# Seen.py'deki TURKISH_ENCODING ile birebir aynı sıra: bayt A1 + i  ->  U+FF61 + i
CHARS = 'ğĞşŞıİçÇöÖüÜ'

def halfwidth_unicode(byte):
    """cp932 tek bayt A1-DF -> Unicode U+FF61-FF9F (yarım genişlikli katakana)."""
    return 0xFF61 + (byte - 0xA1)

def load(path):
    if path.lower().endswith('.ttc'):
        coll = TTCollection(path)
        for f in coll.fonts:                       # "MS Gothic" yüzünü seç
            names = [n.toUnicode() for n in f['name'].names if n.nameID in (1, 4)]
            if any(n.strip() in ('MS Gothic', 'ＭＳ ゴシック') for n in names):
                return f
        return coll.fonts[0]
    return TTFont(path)

def main():
    src = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.environ.get('WINDIR', r'C:\Windows'), 'Fonts', 'msgothic.ttc')
    dst = sys.argv[2] if len(sys.argv) > 2 else FAMILY + '.ttf'
    family = sys.argv[3] if len(sys.argv) > 3 else FAMILY
    if not os.path.exists(src):
        sys.exit('Font bulunamadı: %s' % src)
    font = load(src)

    uni = font.getBestCmap()
    missing = [c for c in CHARS if ord(c) not in uni]
    if missing:
        sys.exit('Bu fontta şu harfler yok: %s\nFarklı bir font deneyin.' % ' '.join(missing))

    pairs = [(halfwidth_unicode(0xA1 + i), ch) for i, ch in enumerate(CHARS)]
    for table in font['cmap'].tables:
        if table.isUnicode():
            for pua, ch in pairs:
                table.cmap[pua] = uni[ord(ch)]

    # Windows bu fontu Shift-JIS (cp932) için uygun saysın (GDI yazı tipi eşlemesi)
    os2 = font['OS/2']
    os2.ulCodePageRange1 |= (1 << 17)

    # Yeni ad: sistem fontuyla karışmasın
    for rec in font['name'].names:
        if rec.nameID in (1, 16):  rec.string = family
        elif rec.nameID in (2, 17): rec.string = 'Regular'
        elif rec.nameID == 4:       rec.string = family
        elif rec.nameID == 6:       rec.string = family
        elif rec.nameID in (3,):    rec.string = family + ';custom'
    font['name'].names = [r for r in font['name'].names if r.nameID not in (0, 7, 8, 9, 13, 14)]

    font.save(dst)
    print('Tamam: %s' % dst)
    for pua, ch in pairs:
        print('  %s -> U+%04X (Shift-JIS bayt %02X)' % (ch, pua, 0xA1 + CHARS.index(ch)))
    print('\nSıradaki adımlar için README_FONT.txt dosyasına bakın.')

if __name__ == '__main__':
    main()
