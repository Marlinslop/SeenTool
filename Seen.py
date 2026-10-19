#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
seen_tool.py - RealLive (Seen.txt) arşiv çözücü + çeviri editörü + yeniden paketleyici
Türkçe karakter desteği ile!

Komutlar:
  python seen_tool.py gui [proje.json]            -> grafik arayüz (önerilen)
  python seen_tool.py unpack  Seen.txt klasor     -> sahneleri çöz (.bin) + okunur .txt döküm
  python seen_tool.py extract Seen.txt proje.json -> çevrilecek satırları proje dosyasına çıkar
  python seen_tool.py build   Seen.txt proje.json Yeni_Seen.txt   -> çevirileri arşive geri yaz
  python seen_tool.py verify  Seen.txt            -> arşivi baştan sona doğrula
  python seen_tool.py tsv     proje.json cikti.tsv
  python seen_tool.py patch-font input.fnt output.fnt -> Font dosyasına Türkçe karakter ekle

Gereksinim: Python 3.8+ (GUI için tkinter; Windows/macOS Python'da hazır gelir).
"""
import sys, os, re, json, struct, bisect, unicodedata, threading, argparse, time

# ---------------------------------------------------------------- şifre anahtarı
_KEY_HEX = (
    "8be55dc3a1e030440085c074095f5e33c05b8be55dc38b450c85c075148b55ec"
    "83c220526a00e8f528010083c40889450c8b45e46a006a005053ff1534b14300"
    "8b451085c074058b4dec89088a45f084c07578a1e03044008b7de88b750c85c0"
    "75448b1dd0b0430085ff763781ff000004006a0076438b45f88d55fc52680000"
    "04005650ff152cb143006a05ffd3a1e030440081ef0000040081c60000040085"
    "c074c58b5df853e8f4fbffff8b450c83c4045f5e5b8be55dc38b55f88d4dfc51"
    "575652ff152cb14300ebd88b45e883c020506a00e8472801008b7de88945f48b"
    "f0a1e030440083c40885c075568b1dd0b0430085ff764981ff000004006a0076"
)
KEY = bytes.fromhex(_KEY_HEX)
assert len(KEY) == 256

# ---------------------------------------------------------------- Türkçe karakter desteği
# Türkçe harfler TEK BAYT olarak 0xA1-0xAC kodlarına yazılır (cp932'de yarım genişlikli
# katakana alanı, U+FF61-U+FF6C). Oyun bunları yarım genişlik sayar, yani harften sonra
# boşluk kalmaz. Glifleri make_font.py ile üretilen SeenGothicTR fontu sağlar.
# (Orijinal İngilizce metinde yarım genişlikli katakana kullanılmıyor; çakışma yok.)
TURKISH_ENCODING = {
    'ğ': b'\xa1',
    'Ğ': b'\xa2',
    'ş': b'\xa3',
    'Ş': b'\xa4',
    'ı': b'\xa5',
    'İ': b'\xa6',
    'ç': b'\xa7',
    'Ç': b'\xa8',
    'ö': b'\xa9',
    'Ö': b'\xaa',
    'ü': b'\xab',
    'Ü': b'\xac',
}

TURKISH_DECODING = {v: k for k, v in TURKISH_ENCODING.items()}
# Eski araç sürümlerinin ürettiği iki baytlık kodlar (sadece okuma/onarım için)
LEGACY_TURKISH_DECODING = {}
for _i, _c in enumerate(TURKISH_ENCODING):
    LEGACY_TURKISH_DECODING[bytes([0xF0, 0x40 + _i])] = _c
    LEGACY_TURKISH_DECODING[bytes([0x87, 0x40 + _i])] = _c

# ASCII fallback (eğer font patch yapılmazsa)
_FOLD = {
    'ğ': 'g', 'Ğ': 'G', 'ş': 's', 'Ş': 'S', 'ı': 'i', 'İ': 'I',
    'ç': 'c', 'Ç': 'C', 'ö': 'o', 'Ö': 'O', 'ü': 'u', 'Ü': 'U',
    '\u2018': "'", '\u2019': "'", '\u201c': '"', '\u201d': '"', '\u2013': '-', '\u2014': '-', '\u2026': '...'
}

# ---------------------------------------------------------------- arşiv
def read_index(d):
    return [struct.unpack_from('<II', d, i * 8) for i in range(10000)]

def decompress_scene(sc):
    """Bir sahneyi (başlık, bytecode) olarak döndürür."""
    off, usz, csz = struct.unpack_from('<III', sc, 0x20)
    ver = struct.unpack_from('<I', sc, 4)[0]
    if ver != 10002:
        raise ValueError('Desteklenmeyen sahne sürümü: %d (ikinci seviye XOR gerekebilir)' % ver)
    comp = sc[off:off + csz]
    out = bytearray(); mask = 8; p = 8
    flag = comp[p] ^ KEY[mask]; p += 1; mask = (mask + 1) & 255; bit = 1
    while p < len(comp) and len(out) < usz:
        if bit == 256:
            bit = 1; flag = comp[p] ^ KEY[mask]; p += 1; mask = (mask + 1) & 255
        if flag & bit:
            out.append(comp[p] ^ KEY[mask]); p += 1; mask = (mask + 1) & 255
        else:
            c = comp[p] ^ KEY[mask]; p += 1; mask = (mask + 1) & 255
            c += (comp[p] ^ KEY[mask]) << 8; p += 1; mask = (mask + 1) & 255
            r = len(out) - ((c >> 4) - 1) - 1
            for i in range((c & 15) + 2): out.append(out[r + i])
        bit <<= 1
    if len(out) != usz: raise ValueError('Sıkıştırma hatası')
    return bytes(sc[:off]), bytes(out)

def compress_literal(data):
    """Sadece 'literal' bayt içeren geçerli bir akış üretir (sıkıştırma yok, motor okuyabilir)."""
    csz = 8 + len(data) + (len(data) + 7) // 8
    hdr = struct.pack('<II', csz, len(data))
    out = bytearray(h ^ KEY[i] for i, h in enumerate(hdr))
    mask = 8
    for i in range(0, len(data), 8):
        out.append(0xff ^ KEY[mask]); mask = (mask + 1) & 255
        for c in data[i:i + 8]:
            out.append(c ^ KEY[mask]); mask = (mask + 1) & 255
    return bytes(out)

# ---------------------------------------------------------------- bytecode ayrıştırıcı
class ParseError(Exception): pass
def is_lead(c): return 0x81 <= c <= 0x9f or 0xe0 <= c <= 0xfc
BINOPS = set(range(0, 10)) | set(range(0x28, 0x2e)) | {0x3c, 0x3d}
ASSIGN = set(range(0x14, 0x1f))

class Parser:
    def __init__(s, b):
        s.b = b; s.n = len(b); s.ptrs = []; s.sel = []
    def chk(s, p):
        if p >= s.n: raise ParseError('eof %d' % p)
    def term(s, p):
        b = s.b; s.chk(p); c = b[p]
        if c == 0x24:
            t = b[p + 1]
            if t == 0xff: return p + 6
            if t == 0xc8: return p + 2
            if b[p + 2] != 0x5b: raise ParseError('memref @%d' % p)
            q = s.expr(p + 3)
            if b[q] != 0x5d: raise ParseError('] @%d' % q)
            return q + 1
        if c == 0x28:
            q = s.expr(p + 1)
            if b[q] != 0x29: raise ParseError(') @%d' % q)
            return q + 1
        if c == 0x5c: return s.term(p + 2)
        raise ParseError('term %02x @%d' % (c, p))
    def expr(s, p):
        b = s.b; p = s.term(p)
        while p + 1 < s.n and b[p] == 0x5c and b[p + 1] in BINOPS: p = s.term(p + 2)
        return p
    def string(s, p):
        b = s.b
        if b[p] == 0x22:
            p += 1
            while b[p] != 0x22:
                if b[p] == 0x5c: p += 2
                elif is_lead(b[p]): p += 2
                else: p += 1
            return p + 1
        q = p
        while q < s.n and b[q] not in (0, 0x2c, 0x29, 0x24, 0x23, 0x0a, 0x40, 0x21, 0x7b, 0x7d, 0x28):
            q += 2 if is_lead(b[q]) else 1
        if q == p: raise ParseError('empty string @%d' % p)
        return q
    def piece(s, p):
        c = s.b[p]
        if c == 0x61: return s.piece(p + 2)
        if c == 0x28: return s.plist(p)
        if c in (0x24, 0x5c): return s.expr(p)
        return s.string(p)
    def plist(s, p):
        b = s.b; p += 1
        while True:
            s.chk(p); c = b[p]
            if c == 0x29: return p + 1
            if c == 0x2c: p += 1; continue
            if c in (0x0a, 0x40): p += 3; continue
            p = s.piece(p)
    def cond(s, p):
        b = s.b
        if b[p] != 0x28: raise ParseError('cond ( @%d' % p)
        q = s.expr(p + 1)
        if b[q] != 0x29: raise ParseError('cond ) @%d' % q)
        return q + 1
    def ptr(s, p):
        s.ptrs.append(p); return p + 4
    def command(s, p):
        b = s.b
        t, mod = b[p + 1], b[p + 2]
        op = struct.unpack_from('<H', b, p + 3)[0]; argc = struct.unpack_from('<H', b, p + 5)[0]
        q = p + 8
        if t == 0 and mod == 1:
            if op in (0, 5): return s.ptr(q)
            if op in (1, 2, 6, 7): return s.ptr(s.cond(q))
            if op in (3, 8):
                q = s.cond(q)
                if b[q] != 0x7b: raise ParseError('{ @%d' % q)
                q += 1
                for _ in range(argc): q = s.ptr(q)
                if b[q] != 0x7d: raise ParseError('} @%d' % q)
                return q + 1
            if op in (4, 9):
                q = s.cond(q)
                if b[q] != 0x7b: raise ParseError('{ @%d' % q)
                q += 1
                while b[q] != 0x7d:
                    q = q + 2 if (b[q] == 0x28 and b[q + 1] == 0x29) else s.cond(q)
                    q = s.ptr(q)
                return q + 1
            if op == 16:
                if b[q] == 0x28: q = s.plist(q)
                return s.ptr(q)
        if q < s.n and b[q] == 0x28: q = s.plist(q)
        if q < s.n and b[q] == 0x7b:
            q += 1
            while b[q] != 0x7d:
                c = b[q]
                if c in (0x0a, 0x40): q += 3
                elif c == 0x2c: q += 1
                elif c == 0x28: q = s.plist(q)
                elif b[q:q + 8] == b'###PRINT': q += 8
                else:
                    e = s.string(q)
                    if b[q] == 0x22: s.sel.append((q, e))
                    q = e
            q += 1
        return q
    def run(s):
        b = s.b; p = 0; els = []
        while p < s.n:
            c = b[p]; st = p
            if c in (0, 0x2c): p += 1; k = 'comma'
            elif c in (0x0a, 0x40, 0x21): p += 3; k = 'meta'
            elif c == 0x24:
                p = s.term(p)
                if b[p] != 0x5c or b[p + 1] not in ASSIGN: raise ParseError('assign @%d' % p)
                p = s.expr(p + 2); k = 'expr'
            elif c == 0x23: p = s.command(p); k = 'cmd'
            else:
                q = False
                while p < s.n:
                    c = b[p]
                    if q:
                        if c == 0x5c: p += 2
                        elif c == 0x22: q = False; p += 1
                        elif is_lead(c): p += 2
                        else: p += 1
                    else:
                        if c == 0x22: q = True; p += 1
                        elif is_lead(c): p += 2
                        elif c in (0, 0x2c, 0x0a, 0x40, 0x21, 0x23, 0x24): break
                        else: p += 1
                k = 'text'
            els.append((st, p, k))
        if p != s.n: raise ParseError('overrun')
        return els

# ---------------------------------------------------------------- metin <-> görüntü (Türkçe destekli)
def _split_prefix(e):
    """Elemanın başındaki 【isim】 önekini (bayt) ve kalanı ayırır."""
    if e[:2] != b'\x81\x79': return b'', e
    p = 2
    while p < len(e) - 1:
        if e[p] == 0x81 and e[p + 1] == 0x7a: return e[:p + 2], e[p + 2:]
        p += 2 if is_lead(e[p]) else 1
    return b'', e

def _segments(b):
    out = []; p = 0; n = len(b); cur = bytearray(); q = False
    while p < n:
        c = b[p]
        if q:
            if c == 0x5c: cur += b[p:p + 2]; p += 2
            elif c == 0x22: out.append((True, bytes(cur))); cur = bytearray(); q = False; p += 1
            elif is_lead(c): cur += b[p:p + 2]; p += 2
            else: cur.append(c); p += 1
        else:
            if c == 0x22:
                if cur: out.append((False, bytes(cur))); cur = bytearray()
                q = True; p += 1
            elif is_lead(c): cur += b[p:p + 2]; p += 2
            else: cur.append(c); p += 1
    if cur: out.append((q, bytes(cur)))
    return out

def _dec(x):
    """Türkçe karakter desteğiyle decode."""
    out = []
    i = 0
    while i < len(x):
        # Türkçe karakter kontrolü (tek bayt)
        one = bytes([x[i]])
        if one in TURKISH_DECODING:
            out.append(TURKISH_DECODING[one])
            i += 1
            continue
        
        # Eski sürüm kodları (iki bayt)
        two = bytes(x[i:i + 2])
        if two in LEGACY_TURKISH_DECODING:
            out.append(LEGACY_TURKISH_DECODING[two])
            i += 2
            continue

        # Normal Shift-JIS
        if is_lead(x[i]) and i + 1 < len(x):
            try:
                out.append(x[i:i+2].decode('cp932'))
                i += 2
            except:
                out.append('?')
                i += 1
        else:
            try:
                out.append(bytes([x[i]]).decode('cp932'))
            except:
                out.append('?')
            i += 1
    
    return ''.join(out)

def body_to_display(body):
    """Bayt gövdeyi (öneksiz) okunur metne çevirir. Tırnak dışı parçalar {{...}} olur."""
    parts = []; has = False
    for q, x in _segments(body):
        t = _dec(x)
        if q: has = True; parts.append(t.replace('\\"', '"').replace('\\\\', '\\'))
        else: parts.append('{{' + t + '}}')
    return ''.join(parts), has

def encode_text(s, fold=True):
    """
    Metni oyunun kodlamasına çevirir.
    fold=True: Türkçe karakterleri ASCII'ye çevir (font patch yoksa)
    fold=False: Türkçe karakterleri özel kodlarla sakla (font patch varsa)
    """
    out = bytearray()
    for ch in s:
        # Türkçe karakter - fold durumuna göre
        if ch in TURKISH_ENCODING:
            if fold:
                # ASCII'ye çevir (eski davranış)
                out += _FOLD.get(ch, ch).encode('ascii', 'replace')
            else:
                # Özel kodla sakla (yeni özellik)
                out += TURKISH_ENCODING[ch]
            continue
        
        # Normal karakterler için standart fold tablosu
        if ch in _FOLD and fold:
            out += _FOLD[ch].encode('ascii')
            continue
        
        # Shift-JIS encode
        try:
            out += ch.encode('cp932')
            continue
        except UnicodeEncodeError:
            pass
        
        # Son çare: normalize et
        r = unicodedata.normalize('NFKD', ch).encode('ascii', 'ignore').decode() or '?'
        out += r.encode('ascii', 'replace')
    
    return bytes(out)

def display_to_body(disp, fold=True):
    """Görüntü metnini oyun baytlarına geri çevirir ({{..}} = tırnaksız ham parça)."""
    out = bytearray()
    for part in re.split(r'(\{\{.*?\}\})', disp, flags=re.S):
        if not part: continue
        if part.startswith('{{') and part.endswith('}}'):
            out += encode_text(part[2:-2], fold)
        else:
            out += b'"' + encode_text(part.replace('\\', '\\\\').replace('"', '\\"'), fold) + b'"'
    return bytes(out)

# ---------------------------------------------------------------- Font Patcher
def patch_font_file(input_path, output_path):
    """Eski ikili font yamalayıcı kaldırıldı (bu oyun glifleri sistem fontundan çizer)."""
    raise ValueError('Bu komut kaldırıldı. Türkçe harfli font için make_font.py dosyasını '
                     'çalıştırın (README_FONT.txt dosyasına bakın).')

def _old_patch_font_file(input_path, output_path):
    """(Kullanılmıyor) Eski deneme."""
    if os.path.abspath(input_path) == os.path.abspath(output_path):
        raise ValueError('Çıktı dosyası, orijinal font dosyasıyla aynı olamaz.')
    print('UYARI: Glif düzeni varsayıma dayanır; her font formatında çalışmayabilir.')
    print('Font dosyası açılıyor:', input_path)
    
    try:
        with open(input_path, 'rb') as f:
            font_data = bytearray(f.read())
    except FileNotFoundError:
        print('Hata: Font dosyası bulunamadı!')
        print('Oyun klasöründeki .g00, .pdt veya .fnt uzantılı dosyayı deneyin')
        return False
    
    print('Font boyutu:', len(font_data), 'bytes')
    
    # Türkçe karakter glyphleri oluştur
    turkish_glyphs = generate_turkish_glyphs()
    
    # Her Türkçe karakter için glyph ekle
    added = 0
    for char, code_bytes in TURKISH_ENCODING.items():
        code = struct.unpack('>H', code_bytes)[0]  # 2-byte code'u integer'a çevir
        
        # Glyph offset hesapla (dosya formatına bağlı)
        offset = calculate_glyph_offset(code)
        
        if offset + 32 <= len(font_data):
            glyph = turkish_glyphs.get(char)
            if glyph:
                font_data[offset:offset+32] = glyph
                added += 1
                print(f'  {char} ({code:04X}) eklendi offset: {offset}')
        else:
            print(f'  Uyarı: {char} için yeterli alan yok')
    
    # Patch'lenmiş dosyayı kaydet
    with open(output_path, 'wb') as f:
        f.write(font_data)
    
    if added == 0:
        print('Hiçbir glif yazılamadı (dosya beklenen düzende değil); çıktı değişmedi.')
    print(f'\n✓ Font patch tamamlandı: {added} karakter eklendi')
    print(f'✓ Çıktı: {output_path}')
    print('\nKullanım: Patchlenmiş font dosyasını oyun klasörüne kopyalayın')
    
    return True

def calculate_glyph_offset(sjis_code):
    """Shift-JIS kodundan font dosyasındaki offset'i hesaplar."""
    # RealLive font yapısı (varsayılan)
    header_size = 0x100
    glyph_size = 32  # 16x16, 2-bit per pixel
    
    # Shift-JIS tablosu: 0x8140-0x9FFC ve 0xE040-0xEFFC
    hi = (sjis_code >> 8) & 0xFF
    lo = sjis_code & 0xFF
    
    if 0x81 <= hi <= 0x9F:
        row = hi - 0x81
    elif 0xE0 <= hi <= 0xFC:
        row = hi - 0xE0 + 0x1F
    else:
        row = 0
    
    if 0x40 <= lo <= 0x7E:
        col = lo - 0x40
    elif 0x80 <= lo <= 0xFC:
        col = lo - 0x80 + 0x3F
    else:
        col = 0
    
    # Toplam offset
    index = row * 188 + col
    offset = header_size + index * glyph_size
    
    return offset

def generate_turkish_glyphs():
    """Türkçe karakterler için basit piksel glyphleri oluşturur."""
    # Her karakter için 16x16 piksel, 2-bit per pixel = 32 byte
    
    glyphs = {}
    
    # Basit el yapımı glyphler (gerçek kullanımda TTF'den render etmek daha iyi)
    # Format: her satır 4 byte (16 piksel * 2-bit = 32-bit = 4 byte)
    
    # ğ (küçük g + breve)
    glyphs['ğ'] = bytes([
        0x00, 0x54, 0x00, 0x00,  # breve (˘)
        0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
        0x0F, 0xF0, 0x00, 0x00,  # g başlangıç
        0x30, 0x0C, 0x00, 0x00,
        0x30, 0x0C, 0x00, 0x00,
        0x0F, 0xFC, 0x00, 0x00,
        0x30, 0x0C, 0x00, 0x00,
        0x30, 0x0C, 0x00, 0x00,
        0x30, 0x0C, 0x00, 0x00,
        0x0F, 0xFC, 0x00, 0x00,
        0x00, 0x0C, 0x00, 0x00,
        0x30, 0x0C, 0x00, 0x00,
        0x0F, 0xF0, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
    ])
    
    # Ğ (büyük G + breve)
    glyphs['Ğ'] = bytes([
        0x00, 0x54, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
        0x0F, 0xFC, 0x00, 0x00,
        0x30, 0x00, 0x00, 0x00,
        0x30, 0x00, 0x00, 0x00,
        0x30, 0x00, 0x00, 0x00,
        0x30, 0xFF, 0x00, 0x00,
        0x30, 0x0C, 0x00, 0x00,
        0x30, 0x0C, 0x00, 0x00,
        0x30, 0x0C, 0x00, 0x00,
        0x30, 0x0C, 0x00, 0x00,
        0x0F, 0xF8, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
    ])
    
    # ş (küçük s + cedilla)
    glyphs['ş'] = bytes([
        0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
        0x0F, 0xF0, 0x00, 0x00,
        0x30, 0x0C, 0x00, 0x00,
        0x30, 0x00, 0x00, 0x00,
        0x0F, 0xC0, 0x00, 0x00,
        0x00, 0x3C, 0x00, 0x00,
        0x00, 0x0C, 0x00, 0x00,
        0x30, 0x0C, 0x00, 0x00,
        0x0F, 0xF0, 0x00, 0x00,
        0x00, 0x30, 0x00, 0x00,  # cedilla
        0x00, 0xC0, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
        0x00, 0x00, 0x00, 0x00,
    ])
    
    # Diğer karakterler için benzer desenler...
    # (Kısa tutmak için sadece birkaç örnek gösterdim)
    
    # Basit fallback: ASCII benzerleri kullan
    for char in ['Ş', 'ı', 'İ', 'ç', 'Ç', 'ö', 'Ö', 'ü', 'Ü']:
        # Gerçekte bunları da render etmek gerekir
        glyphs[char] = bytes(32)  # Boş glyph
    
    return glyphs

# ---------------------------------------------------------------- konuşmacı adı sözlüğü
DEFAULT_NAMES = {
    "＊Ｂ": "＊Ｂ",
    "％Ａ": "％Ａ",
    "％Ｂ": "％Ｂ",
    "春原": "Sunohara",
    "渚": "Nagisa",
    "杏": "Kyou",
    "智代": "Tomoyo",
    "椋": "Ryou",
    "秋生": "Akio",
    "風子": "Fuko",
    "古河": "Furukawa",
    "ことみ": "Kotomi",
    "早苗": "Sanae",
    "芽衣": "Mei",
    "美佐枝": "Misae",
    "芳野": "Yoshino",
    "宮沢": "Miyazawa",
    "勝平": "Shouhei",
    "汐": "Ushio",
    "志麻": "Shima",
    "伊吹": "Ibuki",
    "公子": "Kimiko",
    "幸村": "Yukimura",
    "サキ": "Saki",
    "仁科": "Nishina",
    "勇": "Isamu",
    "史乃": "Shino",
    "杉坂": "Sugisaka",
    "ユキ": "Yuki",
    "クマ": "Kuma",
    "三井": "Mitsui",
    "五十嵐": "Igarashi",
    "八木": "Yagi",
    "鷹文": "Takafumi",
    "谷口": "Taniguchi",
    "田村": "Tamura",
    "辻本": "Tsujimoto",
    "木下": "Kinoshita",
    "大上": "Oogami",
    "ジョニー": "Johnny",
    "柳本": "Yanagimoto",
    "ようへい": "Youhei",
    "祐介": "Yuusuke",
    "関口": "Sekiguchi",
    "ナベ": "Nabe",
    "猪": "Inoshishi",
    "男子生徒": "Erkek öğrenci",
    "女生徒": "Kız öğrenci",
    "教師": "Öğretmen",
    "男": "Adam",
    "女の子": "Kız çocuk",
    "作業員": "İşçi",
    "ボタン": "Düğme",
    "親父": "Baba",
    "少女": "Genç kız",
    "紳士": "Beyefendi",
    "？？": "???",
    "？": "?",
    "担任": "Sınıf öğretmeni",
    "監督": "Şef",
    "親方": "Usta",
    "声": "Ses",
    "部長": "Kulüp başkanı",
    "男子": "Erkek",
    "子供": "Çocuk",
    "店員": "Tezgahtar",
    "サッカー部員": "Futbol kulübü üyesi",
    "主将": "Kaptan",
    "バスケ部員": "Basketbol kulübü üyesi",
    "主婦": "Ev hanımı",
    "合唱部員": "Koro üyesi",
    "母": "Anne",
    "ラグビー部員": "Ragbi kulübü üyesi",
    "審判": "Hakem",
    "男の子": "Erkek çocuk",
    "ガキども": "Veletler",
    "生徒": "Öğrenci",
    "女性": "Kadın",
    "客": "Müşteri",
    "古河・父": "Furukawa'nın babası",
    "おばちゃん": "Teyze",
    "部員": "Kulüp üyesi",
    "女性教師": "Kadın öğretmen",
    "ラグビー部": "Ragbi kulübü",
    "医師": "Doktor",
    "父": "Baba",
    "勇の母": "Isamu'nun annesi",
    "店長": "Müdür",
    "先生": "Öğretmen",
    "店主": "Dükkan sahibi",
    "相手": "Rakip",
    "全員": "Hepsi",
    "婆さん": "Yaşlı kadın",
    "Ａ組担任": "A sınıfı öğretmeni",
    "謎の男": "Gizemli adam",
    "母親": "Anne",
    "野球部員": "Beyzbol kulübü üyesi",
    "チームメイト": "Takım arkadaşı",
    "野郎ども": "Herifler",
    "バッター": "Vurucu",
    "ウェイトレス": "Garson",
    "相手チーム": "Rakip takım",
    "不良ども": "Serseriler",
    "不良": "Serseri",
    "観客": "Seyirci",
    "テレビ": "Televizyon",
    "ジェット男": "Jet adam",
    "謎の転校生": "Gizemli nakil öğrencisi",
    "旅人": "Gezgin",
    "車掌": "Kondüktör",
    "ラーメン屋の店員": "Erişte dükkanı tezgahtarı",
    "運転手": "Şoför",
    "医者": "Doktor",
    "売り子": "Satıcı",
    "女子主将": "Kız kaptan",
    "男子主将": "Erkek kaptan",
    "藤林姉妹": "Fujibayashi kardeşler",
    "合唱部員一同": "Koro üyeleri",
    "クラスメイトたち": "Sınıf arkadaşları",
    "クラスメイト一同": "Sınıf arkadaşları",
    "一同": "Hepsi",
    "観客一同": "Seyirciler",
    "聴衆": "Dinleyiciler",
    "図書委員": "Kütüphane görevlisi",
    "女の人": "Kadın",
    "クラス一同": "Sınıf",
    "別の男": "Başka bir adam",
    "不良一同": "Serseriler",
    "助産婦": "Ebe",
    "僕": "Ben",
    "女子": "Kız",
    "合唱部員２、３": "Koro üyeleri",
    "風…": "Fu...",
}

def default_name(s):
    """Japonca konuşmacı etiketi için yerleşik Latin/Türkçe karşılık ('' = bilinmiyor)."""
    out = []
    for p in s.split('＆'):
        m = re.match(r'^(.*?)([Ａ-Ｚ０-９]+)?$', p, re.S)
        w = DEFAULT_NAMES.get(p); b = w if w else DEFAULT_NAMES.get(m.group(1))
        if not b: return ''
        if w: out.append(w)
        else: out.append(b + (' ' + ''.join(chr(ord(c) - 0xFEE0) for c in m.group(2)) if m.group(2) else ''))
    r = ' & '.join(out)
    return '' if r == s else r

def speaker_name(s, speakers):
    """Kullanıcının girdiği ad önceliklidir, yoksa yerleşik sözlük."""
    v = (speakers or {}).get(s, '').strip()
    return v or default_name(s)

# ---------------------------------------------------------------- çıkarma
def scene_items(b):
    """Bir sahnedeki çevrilebilir satırlar. (o,e) = bayt aralığı."""
    P = Parser(b); els = P.run(); items = []
    for st, en, k in els:
        if k != 'text': continue
        raw = b[st:en]
        if raw[:4] == b'\x82r\x82\x85': continue
        pre, body = _split_prefix(raw)
        disp, has = body_to_display(body)
        items.append({'o': st, 'e': en, 't': 'd', 's': _dec(pre)[1:-1] if pre else '', 'en': disp, 'has': has})
    for st, en in P.sel:
        disp, _ = body_to_display(b[st:en])
        items.append({'o': st, 'e': en, 't': 'c', 's': '', 'en': disp.strip(), 'has': True})
    items.sort(key=lambda x: x['o'])
    return P, els, items

def load_archive(path):
    with open(path, 'rb') as f: return f.read()

def extract_project(seen_path, progress=None):
    d = load_archive(seen_path); ix = read_index(d)
    proj = {'version': 1, 'source': os.path.basename(seen_path), 'speakers': {}, 'scenes': {}, 'turkish_chars': False}
    ids = [i for i, (o, l) in enumerate(ix) if l]
    for n, i in enumerate(ids):
        o, l = ix[i]
        _, b = decompress_scene(d[o:o + l])
        _, _, items = scene_items(b)
        rows = []
        for it in items:
            if it['s']: proj['speakers'].setdefault(it['s'], '')
            if it['has']: rows.append({'o': it['o'], 't': it['t'], 's': it['s'], 'en': it['en'], 'tr': ''})
        if rows: proj['scenes'][str(i)] = rows
        if progress: progress(n + 1, len(ids))
    return proj

# ---------------------------------------------------------------- geri yazma
def _apply_edits(b, edits):
    edits = sorted(edits); out = bytearray(); pos = 0
    starts = []; cum = []; delta = 0
    for s, e, nb in edits:
        out += b[pos:s]; out += nb; pos = e
        delta += len(nb) - (e - s); starts.append(s); cum.append(delta)
    out += b[pos:]
    def newpos(o):
        k = bisect.bisect_left(starts, o)
        return o + (cum[k - 1] if k else 0)
    return bytes(out), newpos

def rebuild_scene(sc, scene_rows, speakers, fold=True):
    header, b = decompress_scene(sc)
    P, els, items = scene_items(b)
    byo = {r['o']: r for r in scene_rows}
    edits = []
    for it in items:
        r = byo.get(it['o']); raw = b[it['o']:it['e']]
        if it['t'] == 'c':
            if r and r['tr'].strip(): edits.append((it['o'], it['e'], display_to_body(r['tr'], fold)))
            continue
        pre, body = _split_prefix(raw)
        new_pre = pre
        sn = speaker_name(it['s'], speakers) if pre else ''
        if sn:
            new_pre = encode_text('【' + sn + '】', fold)
        new_body = body
        if r and r['tr'].strip(): new_body = display_to_body(r['tr'], fold)
        nb = new_pre + new_body
        if nb != raw: edits.append((it['o'], it['e'], nb))
    if not edits: return sc
    nbc, newpos = _apply_edits(b, edits)
    nbc = bytearray(nbc)
    for p in P.ptrs:
        t = struct.unpack_from('<I', b, p)[0]
        struct.pack_into('<I', nbc, newpos(p), newpos(t))
    h = bytearray(header)
    for k in range(100):
        v = struct.unpack_from('<I', h, 0x34 + 4 * k)[0]
        if v: struct.pack_into('<I', h, 0x34 + 4 * k, newpos(v))
    comp = compress_literal(bytes(nbc))
    struct.pack_into('<II', h, 0x24, len(nbc), len(comp))
    return bytes(h) + comp

def build_archive(seen_path, proj, out_path, fold=True, progress=None):
    d = load_archive(seen_path); ix = read_index(d)
    ids = sorted((o, i) for i, (o, l) in enumerate(ix) if l)
    end = max(o + l for o, l in ix if l)
    speakers = proj.get('speakers', {})
    use_spk = True
    
    # Türkçe karakter modu kontrolü
    turkish_mode = proj.get('turkish_chars', False)
    if turkish_mode:
        fold = False  # Türkçe karakterleri koru
        print('✓ Türkçe karakter modu: AÇIK')
        print('  SeenGothicTR fontu kurulu olmalı (font_kur.bat).')
    else:
        print('✓ Türkçe karakter modu: KAPALI (ASCII çevirme)')
    
    new_scenes = {}; changed = 0
    for n, (o, i) in enumerate(ids):
        sc = d[o:o + ix[i][1]]
        rows = proj['scenes'].get(str(i), [])
        new = rebuild_scene(sc, rows, speakers, fold) if (rows or use_spk) else sc
        if new != sc: changed += 1
        new_scenes[i] = new
        if progress: progress(n + 1, len(ids))
    index = bytearray(80000); pos = 80000; body = bytearray()
    for o, i in ids:
        sc = new_scenes[i]
        struct.pack_into('<II', index, i * 8, pos + len(body), len(sc)); body += sc
    with open(out_path, 'wb') as f:
        f.write(index); f.write(body); f.write(d[end:])
    return changed

def repair_archive(src, dst, progress=None):
    """Eski kodlarla yazılmış Türkçe harfleri yeni tek baytlık kodlara çevirir.
    Kaynak: önceki bir çıktı (Seen_1.txt gibi). Çeviri metinleri korunur."""
    proj = extract_project(src)
    tr_letters = set(TURKISH_ENCODING)
    n = 0
    for rows in proj['scenes'].values():
        for r in rows:
            if any(c in tr_letters for c in r['en']):
                r['tr'] = r['en']; n += 1
    # Konuşmacı adlarındaki eski kodlar (örn. 【Kız çocuk】) da yeniden kodlansın
    for name in list(proj['speakers']):
        if any(c in tr_letters for c in name) and not proj['speakers'][name].strip():
            proj['speakers'][name] = name
    proj['turkish_chars'] = True
    changed = build_archive(src, proj, dst, fold=False, progress=progress)
    return n, changed

def rebase_project(old, orig_seen_path):
    """Eski bir projedeki çevirileri ORİJİNAL Seen.txt'ye göre yeniden kurar.
    Eski proje başka bir (çevrilmiş) Seen dosyasından çıkarılmışsa da çalışır:
    satırlar sahne içindeki sıraya göre eşleşir. Eski kod/PUA karakterleri harfe çevrilir."""
    fix_map = {chr(0xE000 + i): c for i, c in enumerate(TURKISH_ENCODING)}
    fix = lambda t: ''.join(fix_map.get(c, c) for c in t)
    new = extract_project(orig_seen_path)
    moved = skipped = 0
    for sid, rows in old.get('scenes', {}).items():
        base = new['scenes'].get(sid)
        if base is None or len(base) != len(rows):
            skipped += sum(1 for r in rows if r.get('tr', '').strip()); continue
        for a, b in zip(base, rows):
            if b.get('tr', '').strip():
                a['tr'] = fix(b['tr']); moved += 1
    # kullanıcının elle girdiği konuşmacı adları (anahtar çevrilmiş dosyadaki ad olabilir)
    translated_name = {}
    for sid, rows in old.get('scenes', {}).items():
        base = new['scenes'].get(sid)
        if base is None or len(base) != len(rows): continue
        for a, b in zip(base, rows):
            if a['s'] and b['s'] != a['s']: translated_name[fix(b['s'])] = a['s']
    for k, v in old.get('speakers', {}).items():
        if not v.strip(): continue
        key = fix(k)
        orig_key = key if key in new['speakers'] else translated_name.get(key)
        if orig_key: new['speakers'][orig_key] = fix(v)
    new['turkish_chars'] = True
    return new, moved, skipped

def verify_archive(path):
    d = load_archive(path); ix = read_index(d); ok = 0
    for i, (o, l) in enumerate(ix):
        if not l: continue
        _, b = decompress_scene(d[o:o + l])
        P = Parser(b); els = P.run()
        starts = {e[0] for e in els} | {len(b)}
        for p in P.ptrs:
            if struct.unpack_from('<I', b, p)[0] not in starts: raise ParseError('Sahne %d: geçersiz atlama hedefi' % i)
        ok += 1
    return ok

# ---------------------------------------------------------------- Claude ile çeviri
_LETTER = re.compile(r'[A-Za-z\u00C0-\u024F]')

def translate_by_ids(lines, ask, max_rounds=3):
    """LLM çevirisi için güvenli yöntem: satırlar KİMLİK (id) ile gönderilir, sonuçlar sıraya değil
    kimliğe göre eşlenir. (Model bir satırı atlarsa tüm liste kaymaz.) Bir satır 3 turda da çevrilmezse
    o satır None döner, diğerleri korunur.
    - Harf içermeyen satırlar (?, ..., ♪, {{%A}}) modele gönderilmez, aynen korunur.
    - Eksik kalan kimlikler için yalnızca o satırlar yeniden istenir.
    ask(items) -> [{'id': .., 'tr': ..}, ...] ; items = [{'id': .., 'en': ..}, ...]"""
    out = [None] * len(lines); todo = []
    for i, l in enumerate(lines):
        if _LETTER.search(re.sub(r'\{\{.*?\}\}', '', l, flags=re.S)): todo.append(i)
        else: out[i] = l
    for _ in range(max_rounds):
        need = [i for i in todo if out[i] is None]
        if not need: break
        got = ask([{'id': i, 'en': lines[i]} for i in need])
        for g in got if isinstance(got, list) else []:
            try: k, t = int(g['id']), str(g['tr'])
            except Exception: continue
            if k in need and t.strip(): out[k] = t
    miss = [i for i in todo if out[i] is None]
    if miss and len(miss) == len(todo):                 # hiçbiri çevrilmediyse gerçek bir hata
        raise ValueError('Model hiçbir satırı çevirmedi')
    return out                                           # kısmi: çevrilemeyenler None kalır (çağıran atlar)

def _ids_prompt(items, glossary, target):
    p = ('Aşağıda bir görsel romandan (Clannad) İngilizce satırlar var. Her öğe {"id": sayı, "en": metin} biçiminde. '
         'Her birini doğal, akıcı %s diline çevir. {{...}} içindeki parçaları AYNEN koru. Çıktı: aynı id\'lerle '
         '{"id": sayı, "tr": çeviri} öğelerinden oluşan bir JSON dizisi. Hiçbir id\'yi atlama, birleştirme ya da değiştirme; '
         'başka hiçbir şey yazma.\n' % target)
    if glossary: p += 'Karakter adları sözlüğü: ' + json.dumps(glossary, ensure_ascii=False) + '\n'
    return p + json.dumps(items, ensure_ascii=False)

def claude_translate(lines, api_key, glossary=None, model='claude-sonnet-5-5', target='Türkçe'):
    import urllib.request
    def ask(items):
        body = json.dumps({'model': model, 'max_tokens': 4000,
                           'messages': [{'role': 'user', 'content': _ids_prompt(items, glossary, target)}]}).encode()
        req = urllib.request.Request('https://api.anthropic.com/v1/messages', data=body, headers={
            'content-type': 'application/json', 'x-api-key': api_key, 'anthropic-version': '2023-06-01'})
        with urllib.request.urlopen(req, timeout=120) as r: data = json.load(r)
        text = ''.join(c.get('text', '') for c in data['content'])
        text = re.sub(r'^```(?:json)?|```$', '', text.strip(), flags=re.M).strip()
        return json.loads(text)
    return translate_by_ids(lines, ask)

# ---------------------------------------------------------------- Gemini ile çeviri
class RetryAfter(Exception):
    """API "şu kadar sonra tekrar dene" dedi (hız sınırı, yoğunluk, günlük kota)."""
    def __init__(self, msg, seconds=15, daily=False):
        super().__init__(msg); self.retry_after = seconds; self.daily = daily

_GEMINI = {'caps': {}, 'last': 0.0, 'lock': threading.Lock()}
GEMINI_MIN_INTERVAL = 4.0          # istekler arası en az saniye (~15 istek/dk), 429'ları önler
_GEMINI_THINK = [{'thinkingBudget': 0}, {'thinkingLevel': 'minimal'}, None]   # çeviri için "düşünme" kapalı
# (şema, düşünme) kombinasyonları: en gelişmişten en basite. Son sıra, bilinen çalışan sade ayardır.
_GEMINI_LADDER = [(s_, t_) for s_ in (0, 1) for t_ in (0, 1, 2)]   # şema: 0=minItems/maxItems'li, 1=şemasız

def _gemini_pace():
    with _GEMINI['lock']:
        wait = GEMINI_MIN_INTERVAL - (time.time() - _GEMINI['last'])
        if wait > 0: time.sleep(wait)
        _GEMINI['last'] = time.time()

def _gemini_retry_info(body):
    """429 gövdesinden (bekleme_sn, günlük_mü) çıkarır."""
    secs, daily = None, False
    try: details = json.loads(body).get('error', {}).get('details', []) or []
    except Exception: details = []
    for d in details:
        if isinstance(d, dict):
            if 'retryDelay' in d:
                mm = re.match(r'\s*([\d.]+)', str(d['retryDelay']))
                if mm: secs = float(mm.group(1))
            for v in d.get('violations', []) or []:
                if 'perday' in str(v.get('quotaId', '')).lower(): daily = True
    if 'perday' in body.lower().replace(' ', '').replace('_', ''): daily = True
    return secs, daily

def gemini_translate(lines, api_key, glossary=None, model='gemini-3.5-flash-lite', target='Türkçe',
                     timeout=60, base_url='https://generativelanguage.googleapis.com/v1beta'):
    import urllib.request, urllib.parse, urllib.error
    url = '%s/models/%s:generateContent' % (base_url, urllib.parse.quote(model, safe=''))
    caps = _GEMINI['caps'].setdefault(model, {'i': 0})        # bu modelde işe yarayan ayar kademesini hatırla

    def ask(items):
        n = len(items); prompt = _ids_prompt(items, glossary, target); data = None
        for _ in range(len(_GEMINI_LADDER) + 1):
            schema_i, think_i = _GEMINI_LADDER[caps['i']]
            gen = {'responseMimeType': 'application/json', 'temperature': 0.2}
            if schema_i == 0:
                gen['responseSchema'] = {'type': 'ARRAY', 'minItems': n, 'maxItems': n,
                                         'items': {'type': 'OBJECT', 'required': ['id', 'tr'],
                                                   'properties': {'id': {'type': 'INTEGER'}, 'tr': {'type': 'STRING'}}}}
            think = _GEMINI_THINK[think_i]
            if think: gen['thinkingConfig'] = think
            body = json.dumps({'contents': [{'parts': [{'text': prompt}]}], 'generationConfig': gen}).encode('utf-8')
            req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json', 'x-goog-api-key': api_key})
            _gemini_pace()
            try:
                with urllib.request.urlopen(req, timeout=timeout) as r: data = json.load(r)
                break
            except urllib.error.HTTPError as e:
                eb = e.read().decode('utf-8', errors='replace'); low = eb.lower()
                if e.code == 429:
                    secs, daily = _gemini_retry_info(eb)
                    raise RetryAfter('Gemini hız/kota sınırı (429)%s' % (': günlük kota doldu' if daily else ''), (secs or 30) + 1, daily)
                if e.code in (500, 502, 503, 504):
                    raise RetryAfter('Gemini yoğun/geçici hata (%d)' % e.code, 15)
                if e.code == 400 and not any(k in low for k in ('api key', 'api_key', 'permission', 'billing', 'location', 'not supported for')) \
                        or (e.code == 400 and 'think' in low):
                    cur = _GEMINI_LADDER[caps['i']]
                    if 'think' in low: nxt = next((j for j in range(caps['i'] + 1, len(_GEMINI_LADDER)) if _GEMINI_LADDER[j][1] != cur[1]), None)
                    elif 'schema' in low or 'items' in low: nxt = next((j for j in range(caps['i'] + 1, len(_GEMINI_LADDER)) if _GEMINI_LADDER[j][0] != cur[0]), None)
                    else: nxt = caps['i'] + 1 if caps['i'] + 1 < len(_GEMINI_LADDER) else None
                    if nxt is not None: caps['i'] = nxt; continue
                raise ValueError('Gemini API hatası: %s (model=%s) - %s' % (e.code, model, eb[:500]))
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                raise RetryAfter('Gemini bağlantı hatası/zaman aşımı: %s' % e, 10)
        if data is None: raise ValueError('Gemini ayarları kabul edilmedi (model=%s)' % model)
        try:
            text = ''.join(p.get('text', '') for p in data['candidates'][0]['content']['parts'])
            return json.loads(re.sub(r'^```(?:json)?|```$', '', text.strip(), flags=re.M).strip())
        except (KeyError, IndexError, TypeError, json.JSONDecodeError) as e:
            raise ValueError('Gemini geçerli JSON çeviri döndürmedi: %s' % e)

    return translate_by_ids(lines, ask)

# ---------------------------------------------------------------- DeepL ile çeviri
def deepl_translate(lines, api_key, glossary=None, target='TR'):
    """DeepL API kullanarak toplu çeviri yapar."""
    import urllib.request
    import urllib.parse
    
    endpoint = 'https://api-free.deepl.com/v2/translate' if api_key.endswith(':fx') else 'https://api.deepl.com/v2/translate'
    results = []
    batch_size = 50
    
    for i in range(0, len(lines), batch_size):
        batch = lines[i:i + batch_size]
        placeholders = {}
        processed_batch = []
        
        counter = 0
        for line in batch:
            matches = re.findall(r'\{\{.*?\}\}', line, flags=re.S)
            processed = line
            for match in matches:
                placeholder = f'__PLACEHOLDER_{counter}__'
                counter += 1
                placeholders[placeholder] = match
                processed = processed.replace(match, placeholder, 1)
            processed_batch.append(processed)
        
        params = []
        for text in processed_batch:
            params.append(('text', text.encode('utf-8')))
        params.append(('target_lang', target.encode('utf-8')))
        params.append(('source_lang', b'EN'))
        params.append(('preserve_formatting', b'1'))
        
        data = urllib.parse.urlencode(params).encode('utf-8')
        req = urllib.request.Request(endpoint, data=data, headers={
            'Authorization': 'DeepL-Auth-Key ' + api_key,
            'Content-Type': 'application/x-www-form-urlencoded'
        })
        
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                result = json.load(r)
                translations = result.get('translations', [])
                for trans in translations:
                    text = trans.get('text', '')
                    for placeholder, original in placeholders.items():
                        text = text.replace(placeholder, original)
                    results.append(text)
        except urllib.error.HTTPError as e:
            error_body = e.read().decode('utf-8')
            raise ValueError(f'DeepL API hatası: {e.code} - {error_body}')
    
    if len(results) != len(lines):
        raise ValueError(f'Satır sayısı uyuşmadı: beklenen {len(lines)}, alınan {len(results)}')
    return results

# ---------------------------------------------------------------- toplu çeviri yardımcıları
def chunk_indices(rows, idxs, max_n=40, max_chars=5000):
    """Satır numaralarını API için makul büyüklükte parçalara böler."""
    out, chunk, chars = [], [], 0
    for i in idxs:
        n = len(rows[i]['en'])
        if chunk and (len(chunk) >= max_n or chars + n > max_chars):
            out.append(chunk); chunk, chars = [], 0
        chunk.append(i); chars += n
    if chunk: out.append(chunk)
    return out

def translate_rows(rows, idxs, translate_fn, on_chunk, on_progress=None, should_stop=None, sleep=None):
    """Satırları parça parça çevirir. Her parça biter bitmez on_chunk(parça, sonuçlar) çağrılır,
    böylece hata olsa bile o ana kadar çevrilenler kaybolmaz. API "şu kadar sonra dene" derse
    (RetryAfter) o kadar bekler. (çevrilen_adet, hata|None) döner."""
    sleep = sleep or time.sleep
    done = 0
    for part in chunk_indices(rows, idxs):
        if should_stop and should_stop(): break
        res, err, tries = None, None, 0
        while tries < 3:
            tries += 1
            try:
                res = translate_fn([rows[i]['en'] for i in part])
                if len(res) != len(part): raise ValueError('Satır sayısı uyuşmadı')
                err = None; break
            except Exception as ex:
                res, err = None, str(ex)
                ra = getattr(ex, 'retry_after', None)
                if ra is not None:
                    if getattr(ex, 'daily', False): break                 # günlük kota: beklemek boşuna
                    for _ in range(int(min(ra, 120)) + 1):
                        if should_stop and should_stop(): break
                        sleep(1)
        if err: return done, err
        on_chunk(part, res); done += sum(1 for r in res if r is not None)
        if on_progress: on_progress(done, len(idxs))
    return done, None

class AutoFatal(Exception):
    """Oto çeviride devam edilemeyen hata (ağ/anahtar/kota gibi)."""

def auto_translate(scenes, order, fn, apply_cb, should_stop, log=None, exclude=None,
                   sleep=None, batch=40, waits=(10, 30, 90), max_passes=3, on_wait=None,
                   daily_wait_max=26 * 3600):
    """Sahneleri sırayla gezip çevrilmemiş satırları batch'er batch'er çevirir.
    - Hız sınırı (RetryAfter) olunca API'nin söylediği süre kadar bekler, satır satır DENEMEZ.
    - Günlük kota dolarsa 10 dk'da bir deneyerek (en fazla daily_wait_max sn) bekler; sıfırlanınca devam eder.
    - Diğer geçici hatalarda waits kadar bekleyip yeniden dener; parti çalışmazsa satır satır dener.
    - Hiçbir satır çevrilemiyorsa AutoFatal fırlatır. Tek tek çevrilemeyen satırlar atlanır.
    apply_cb(sid, idxler, sonuçlar) her parça için çağrılır. (çevrilen, atlanan) döner."""
    sleep = sleep or time.sleep
    log = log or (lambda m: None)

    def wait(sec, why=''):
        if on_wait and sec >= 5: on_wait('%s %d sn bekleniyor' % (why, sec))
        while sec > 0 and not should_stop():
            sleep(min(1, sec)); sec -= 1

    def call(lines):
        res = fn(lines)
        if len(res) != len(lines): raise ValueError('Satır sayısı uyuşmadı')
        return res

    def robust(lines):
        err, attempts, rate_hits, daily_waited = None, 0, 0, 0
        while True:
            if should_stop(): return None
            try: return call(lines)
            except Exception as ex:
                err = ex; log('hata: %s' % ex)
                ra = getattr(ex, 'retry_after', None)
                if ra is not None:
                    if getattr(ex, 'daily', False):
                        if daily_waited >= daily_wait_max: raise AutoFatal('Günlük kota yenilenmedi: %s' % ex)
                        log('günlük kota doldu; 10 dk sonra yeniden denenecek'); wait(600, 'Günlük kota doldu,'); daily_waited += 600
                        continue
                    rate_hits += 1
                    if rate_hits > 8: raise AutoFatal('Sürekli hız sınırı/bağlantı hatası: %s' % ex)
                    wait(min(int(ra), 120), 'Hız sınırı,'); continue
                attempts += 1
                if attempts > len(waits): break
                wait(waits[attempts - 1], 'Hata,')
        out, bad = [], 0                                # parti olmadı: satır satır (içerik sorunu olabilir)
        for ln in lines:
            if should_stop(): return None
            try: out.append(call([ln])[0])
            except Exception as ex:
                if getattr(ex, 'retry_after', None) is not None: raise AutoFatal(str(ex))
                out.append(None); bad += 1; log('satır atlandı: %s' % ex)
        if bad == len(lines): raise AutoFatal(str(err))
        return out

    done, skipped = 0, set()
    for _ in range(max_passes):
        before = done
        for sid in order:
            rows = scenes[sid]
            while not should_stop():
                idxs = [i for i, r in enumerate(rows)
                        if not r['tr'].strip() and (sid, i) not in skipped
                        and not (exclude and exclude(sid, i))][:batch]
                if not idxs: break
                res = robust([rows[i]['en'] for i in idxs])
                if res is None: return done, len(skipped)
                good = [(i, t) for i, t in zip(idxs, res) if t is not None and str(t).strip()]
                for i, t in zip(idxs, res):
                    if t is None or not str(t).strip(): skipped.add((sid, i))   # boş/çevrilemeyen satır
                if good:
                    apply_cb(sid, [i for i, _ in good], [t for _, t in good]); done += len(good)
                    for i, _ in good:
                        if not rows[i]['tr'].strip(): skipped.add((sid, i))      # yazılamadıysa takılma
            if should_stop(): return done, len(skipped)
        if done == before: break
    return done, len(skipped)

# ---------------------------------------------------------------- yardımcılar
def save_project(proj, path):
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f: json.dump(proj, f, ensure_ascii=False, indent=0)
    os.replace(tmp, path)

def load_project(path):
    with open(path, encoding='utf-8') as f: return json.load(f)

def cmd_unpack(seen, outdir):
    os.makedirs(outdir, exist_ok=True)
    d = load_archive(seen); ix = read_index(d); n = 0
    for i, (o, l) in enumerate(ix):
        if not l: continue
        h, b = decompress_scene(d[o:o + l])
        with open(os.path.join(outdir, 'SEEN%04d.bin' % i), 'wb') as f: f.write(b)
        _, _, items = scene_items(b)
        with open(os.path.join(outdir, 'SEEN%04d.txt' % i), 'w', encoding='utf-8') as f:
            for it in items:
                if it['has']: f.write('[%s] %s\n' % ('SEÇENEK' if it['t'] == 'c' else (it['s'] or '-'), it['en']))
        n += 1
    print('%d sahne çözüldü -> %s' % (n, outdir))

def cmd_tsv(projpath, out):
    proj = load_project(projpath)
    with open(out, 'w', encoding='utf-8') as f:
        f.write('sahne\tofset\tkonusmaci\tingilizce\tceviri\n')
        for sid, rows in proj['scenes'].items():
            for r in rows:
                f.write('\t'.join([sid, str(r['o']), r['s'], r['en'].replace('\t', ' ').replace('\n', '\\n'),
                                   r['tr'].replace('\t', ' ').replace('\n', '\\n')]) + '\n')

# ---------------------------------------------------------------- GUI
# ---------------------------------------------------------------- arayüz ayarları ve renkler
def _settings_path(): return os.path.join(os.path.expanduser('~'), '.seen_tool.json')
def load_settings():
    try:
        with open(_settings_path(), encoding='utf-8') as f: return json.load(f)
    except Exception: return {}
def save_settings(d):
    try:
        with open(_settings_path(), 'w', encoding='utf-8') as f: json.dump(d, f)
    except Exception: pass

# sv-ttk kuruluysa onun (Windows 11 tarzı) teması, değilse kendi düz teması kullanılır
PAL_SV = {
    'light': dict(bg='#fafafa', surface='#ffffff', surface2='#f3f3f3', fg='#1c1c1c', muted='#6b6b6b', border='#e0e0e0',
                  accent='#005fb8', accent2='#0a4f96', accent_fg='#ffffff', sel='#dbeafe', sel_fg='#10305a', zebra='#f6f6f6', done='#eaf6ee'),
    'dark':  dict(bg='#1c1c1c', surface='#282828', surface2='#232323', fg='#fafafa', muted='#a0a0a0', border='#3a3a3a',
                  accent='#57c8ff', accent2='#3aa9e0', accent_fg='#06202e', sel='#1f4a6b', sel_fg='#ffffff', zebra='#222222', done='#1d2f25')}
PAL_OWN = {
    'light': dict(bg='#f3f4f6', surface='#ffffff', surface2='#f3f4f6', fg='#1f2937', muted='#6b7280', border='#d9dde3',
                  accent='#2563eb', accent2='#1d4ed8', accent_fg='#ffffff', sel='#dbeafe', sel_fg='#1e3a8a', zebra='#f8f9fb', done='#e9f7ef'),
    'dark':  dict(bg='#111827', surface='#1f2937', surface2='#18212f', fg='#e5e7eb', muted='#9ca3af', border='#374151',
                  accent='#3b82f6', accent2='#60a5fa', accent_fg='#ffffff', sel='#1e3a8a', sel_fg='#dbeafe', zebra='#1a2332', done='#14301f')}

def run_gui(initial=None):
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox

    CFG = load_settings()
    root = tk.Tk(); root.title('Seen.txt Çeviri Aracı (Türkçe Karakter Destekli)'); root.geometry(CFG.get('geometry', '1280x820'))
    S = {'proj': None, 'path': None, 'seen': None, 'scene': None, 'sids': [], 'dirty': False, 'sel': None,
         'claude_api': os.environ.get('ANTHROPIC_API_KEY', ''),
         'deepl_api': os.environ.get('DEEPL_API_KEY', ''),
         'gemini_api': os.environ.get('GEMINI_API_KEY', ''),
         'gemini_model': 'gemini-3.5-flash-lite',
         'translator': 'deepl',
         'turkish_mode': tk.BooleanVar(value=False)}

    # ---------------------------------------------------------------- yerleşim (modern)
    import tkinter.font as tkfont
    _fams = set(tkfont.families())
    FAM = 'Segoe UI' if 'Segoe UI' in _fams else tkfont.nametofont('TkDefaultFont').actual('family')
    for _nm in ('TkDefaultFont', 'TkTextFont', 'TkMenuFont', 'TkHeadingFont', 'TkFixedFont'):
        try: tkfont.nametofont(_nm).configure(family=FAM, size=10)
        except Exception: pass
    FONT, FONT_B, EDIT = (FAM, 10), (FAM, 10, 'bold'), (FAM, 12)
    try:
        if os.environ.get('SEEN_NO_SV'): raise ImportError
        import sv_ttk
    except Exception: sv_ttk = None
    root.minsize(1000, 640)
    S['theme'] = CFG.get('theme', 'light') if CFG.get('theme') in ('light', 'dark') else 'light'
    set_msg = tk.StringVar(); stat = tk.StringVar()

    # --- üst araç çubuğu
    toolbar = ttk.Frame(root, padding=(12, 10)); toolbar.pack(fill='x', side='top')
    ttk.Button(toolbar, text='Proje aç', command=lambda: open_proj()).pack(side='left')
    ttk.Button(toolbar, text='Kaydet', command=lambda: save()).pack(side='left', padx=(6, 0))
    ttk.Separator(toolbar, orient='vertical').pack(side='left', fill='y', padx=14)
    ttk.Label(toolbar, text='Servis', style='Muted.TLabel').pack(side='left')
    service_var = tk.StringVar(value='DeepL')
    service_cb = ttk.Combobox(toolbar, textvariable=service_var, values=('DeepL', 'Claude', 'Gemini'), state='readonly', width=9)
    service_cb.pack(side='left', padx=(6, 12))
    tmb = ttk.Menubutton(toolbar, text='Çevir'); tmb.pack(side='left')
    translate_menu = tk.Menu(tmb, tearoff=0)
    translate_menu.add_command(label='Bu satırı çevir', command=lambda: mt(False))
    translate_menu.add_command(label='İlk 40 boş satırı çevir', command=lambda: mt(40))
    translate_menu.add_command(label='İlk 400 boş satırı çevir', command=lambda: mt(400))
    translate_menu.add_command(label='Sahnenin tamamını çevir…', command=lambda: mt(-1))
    tmb['menu'] = translate_menu
    auto_btn = ttk.Button(toolbar, text="▶ Oto çeviri (40'ar)", style='Accent.TButton', command=lambda: auto_toggle())
    auto_btn.pack(side='left', padx=10)
    stop_btn = ttk.Button(toolbar, text='■ Durdur', command=lambda: S.__setitem__('stop', True)); stop_btn.pack(side='left')
    theme_btn = ttk.Button(toolbar, text='◐ Tema', command=lambda: toggle_theme()); theme_btn.pack(side='right')

    # --- alt durum çubuğu ve düzenleme paneli (önce paketlenir, pencere küçülünce de görünür kalır)
    sbar = ttk.Frame(root, padding=(12, 8)); sbar.pack(fill='x', side='bottom')
    ttk.Label(sbar, textvariable=set_msg, style='Status.TLabel').pack(side='left')
    ttk.Checkbutton(sbar, text='Türkçe harfleri koru (ğ ş ı ç ö ü) · font gerekir', variable=S['turkish_mode']).pack(side='right')
    ttk.Label(sbar, textvariable=stat, style='Muted.TLabel').pack(side='right', padx=14)
    progress = ttk.Progressbar(sbar, length=180, maximum=100); progress.pack(side='right')

    ed = ttk.Frame(root, padding=(12, 6)); ed.pack(fill='x', side='bottom')
    head = ttk.Frame(ed); head.pack(fill='x')
    spk = tk.StringVar(); ttk.Label(head, textvariable=spk, style='Title.TLabel').pack(side='left')
    warn = tk.StringVar(); ttk.Label(head, textvariable=warn, foreground='#c2410c').pack(side='right')
    cards = ttk.Frame(ed); cards.pack(fill='x', pady=6); cards.columnconfigure(0, weight=1, uniform='c'); cards.columnconfigure(1, weight=1, uniform='c')
    ttk.Label(cards, text='İngilizce', style='Muted.TLabel').grid(row=0, column=0, sticky='w')
    ttk.Label(cards, text='Türkçe', style='Muted.TLabel').grid(row=0, column=1, sticky='w', padx=(10, 0))
    en_t = tk.Text(cards, height=5, wrap='word'); en_t.grid(row=1, column=0, sticky='nsew'); en_t.configure(state='disabled')
    tr_t = tk.Text(cards, height=5, wrap='word'); tr_t.grid(row=1, column=1, sticky='nsew', padx=(10, 0))
    bb = ttk.Frame(ed); bb.pack(fill='x', pady=(6, 0))
    ttk.Button(bb, text='◀ Önceki', command=lambda: move(-1)).pack(side='left')
    ttk.Button(bb, text='İngilizceyi kopyala', command=lambda: copy_en()).pack(side='left', padx=6)
    ttk.Button(bb, text='Kaydet ve sonraki ▶  (Ctrl+Enter)', style='Accent.TButton', command=lambda: move(1)).pack(side='right')

    # --- gövde: sahneler + satır tablosu
    paned = ttk.PanedWindow(root, orient='horizontal'); paned.pack(fill='both', expand=True, padx=12, pady=(0, 4))
    left = ttk.Frame(paned); paned.add(left, weight=1)
    ttk.Label(left, text='Sahneler', style='Title.TLabel').pack(anchor='w', pady=(0, 6))
    sq = tk.StringVar(); ttk.Entry(left, textvariable=sq).pack(fill='x', pady=(0, 6))
    lf = ttk.Frame(left); lf.pack(fill='both', expand=True)
    sl = tk.Listbox(lf, exportselection=False, width=26); lsb = ttk.Scrollbar(lf, command=sl.yview); sl.configure(yscrollcommand=lsb.set)
    lsb.pack(side='right', fill='y'); sl.pack(side='left', fill='both', expand=True)
    right = ttk.Frame(paned); paned.add(right, weight=5)

    fbar = ttk.Frame(right); fbar.pack(fill='x', pady=(0, 6))
    ttk.Label(fbar, text='Ara', style='Muted.TLabel').pack(side='left')
    q = tk.StringVar(); ttk.Entry(fbar, textvariable=q, width=34).pack(side='left', padx=8)
    only = tk.BooleanVar(); ttk.Checkbutton(fbar, text='Sadece çevrilmemişler', variable=only).pack(side='left', padx=8)

    cols = ('n', 's', 'en', 'tr')
    tvf = ttk.Frame(right); tvf.pack(fill='both', expand=True)
    tv = ttk.Treeview(tvf, columns=cols, show='headings', height=12, selectmode='browse')
    for c, t, w in (('n', '#', 56), ('s', 'Konuşmacı', 130), ('en', 'İngilizce', 470), ('tr', 'Türkçe', 470)):
        tv.heading(c, text=t, anchor='w'); tv.column(c, width=w, anchor='w', stretch=(c in ('en', 'tr')))
    sb = ttk.Scrollbar(tvf, command=tv.yview); tv.configure(yscrollcommand=sb.set)
    sb.pack(side='right', fill='y'); tv.pack(side='left', fill='both', expand=True)

    def set_title(t):
        root.title(t); set_msg.set(t if t.startswith(('Çevriliyor', 'OTO')) else '')
    def mk_top():
        w = tk.Toplevel(root); w.configure(bg=S['pal']['bg']); return w
    def sync_service():
        service_var.set({'deepl': 'DeepL', 'claude': 'Claude', 'gemini': 'Gemini'}.get(S['translator'], 'DeepL'))
    service_cb.bind('<<ComboboxSelected>>', lambda e: (S.__setitem__('translator', service_var.get().lower()), service_cb.selection_clear()))

    def apply_theme(mode):
        S['theme'] = mode; P = (PAL_SV if sv_ttk else PAL_OWN)[mode]; S['pal'] = P
        st = ttk.Style(root)
        if sv_ttk: sv_ttk.set_theme(mode)
        else:
            st.theme_use('clam')
            st.configure('.', background=P['bg'], foreground=P['fg'], fieldbackground=P['surface'], bordercolor=P['border'],
                         lightcolor=P['bg'], darkcolor=P['bg'], troughcolor=P['zebra'], focuscolor=P['bg'], font=FONT)
            st.configure('TButton', background=P['surface'], foreground=P['fg'], padding=(14, 7), relief='flat', borderwidth=1, bordercolor=P['border'])
            st.map('TButton', background=[('pressed', P['sel']), ('active', P['sel'])], bordercolor=[('active', P['accent'])])
            st.configure('Accent.TButton', background=P['accent'], foreground=P['accent_fg'], bordercolor=P['accent'], padding=(14, 7))
            st.map('Accent.TButton', background=[('pressed', P['accent2']), ('active', P['accent2'])], bordercolor=[('active', P['accent2'])])
            st.configure('TEntry', fieldbackground=P['surface'], padding=6, bordercolor=P['border'])
            st.map('TEntry', bordercolor=[('focus', P['accent'])])
            st.configure('TCombobox', fieldbackground=P['surface'], padding=6, arrowcolor=P['fg'], bordercolor=P['border'], background=P['surface'])
            st.map('TCombobox', fieldbackground=[('readonly', P['surface'])], bordercolor=[('focus', P['accent'])], background=[('active', P['sel'])])
            st.configure('TCheckbutton', background=P['bg'], foreground=P['fg']); st.map('TCheckbutton', background=[('active', P['bg'])])
            st.configure('TMenubutton', background=P['surface'], foreground=P['fg'], padding=(14, 7), relief='flat', bordercolor=P['border'], arrowcolor=P['fg'])
            st.map('TMenubutton', background=[('active', P['sel'])])
            st.configure('Treeview', background=P['surface'], fieldbackground=P['surface'], foreground=P['fg'], bordercolor=P['border'], borderwidth=0)
            st.map('Treeview', background=[('selected', P['sel'])], foreground=[('selected', P['sel_fg'])])
            st.configure('Treeview.Heading', background=P['bg'], foreground=P['muted'], relief='flat', padding=(8, 7), bordercolor=P['border'])
            st.map('Treeview.Heading', background=[('active', P['bg'])])
            st.configure('TProgressbar', background=P['accent'], troughcolor=P['border'], bordercolor=P['bg'], lightcolor=P['accent'], darkcolor=P['accent'], thickness=8)
            st.configure('TScrollbar', background=P['border'], troughcolor=P['bg'], bordercolor=P['bg'], arrowcolor=P['muted'], relief='flat')
            st.configure('TScrollbar', arrowsize=13, gripcount=0)
            st.map('TScrollbar', background=[('active', P['muted'])])
            st.configure('TSeparator', background=P['border'])
        st.configure('Treeview', rowheight=30, font=FONT); st.configure('Treeview.Heading', font=FONT_B)
        st.map('Treeview', background=[('selected', P['sel'])], foreground=[('selected', P['sel_fg'])])
        st.configure('Title.TLabel', font=(FAM, 11, 'bold')); st.configure('Muted.TLabel', foreground=P['muted'])
        st.configure('Status.TLabel', foreground=P['accent'], font=FONT_B)
        root.configure(bg=P['bg'])
        sl.configure(bg=P['surface'], fg=P['fg'], selectbackground=P['sel'], selectforeground=P['sel_fg'], font=FONT, bd=0, relief='flat',
                     highlightthickness=1, highlightbackground=P['border'], highlightcolor=P['accent'], activestyle='none')
        for t, bgc in ((en_t, P['surface2']), (tr_t, P['surface'])):
            t.configure(bg=bgc, fg=P['fg'], insertbackground=P['fg'], font=EDIT, relief='flat', padx=10, pady=8, bd=0,
                        highlightthickness=1, highlightbackground=P['border'], highlightcolor=P['accent'], selectbackground=P['sel'], selectforeground=P['sel_fg'])
        tv.tag_configure('odd', background=P['zebra']); tv.tag_configure('done', background=P['done'])
        translate_menu.configure(bg=P['surface'], fg=P['fg'], activebackground=P['sel'], activeforeground=P['sel_fg'], bd=0, font=FONT)
        try: theme_var.set(mode == 'dark')
        except Exception: pass
    def toggle_theme():
        apply_theme('dark' if S['theme'] == 'light' else 'light'); save_settings({**load_settings(), 'theme': S['theme']})
    theme_var = tk.BooleanVar(value=(S['theme'] == 'dark'))
    apply_theme(S['theme'])


    def spk_label(s):
        if not s: return ''
        n = speaker_name(s, S['proj']['speakers'] if S['proj'] else {})
        return s + ' → ' + n if n else s
    def trunc(s, n=140):
        s = s.replace('\n', ' ')
        return s if len(s) <= n else s[:n] + '…'
    def counts():
        if not S['proj']: return
        tot = sum(len(r) for r in S['proj']['scenes'].values())
        done = sum(1 for r in S['proj']['scenes'].values() for x in r if x['tr'].strip())
        stat.set('%d / %d çevrildi (%% %d)' % (done, tot, 100 * done // max(tot, 1)))
        progress['value'] = 100.0 * done / max(tot, 1)
    def scene_label(sid):
        rows = S['proj']['scenes'][sid]; d = sum(1 for x in rows if x['tr'].strip()); n = len(rows)
        return '%s  Sahne %s    %d/%d' % ('●' if d == n else ('◐' if d else '○'), sid, d, n)
    def fill_scenes(keep=None):
        sl.delete(0, 'end'); f = sq.get().strip()
        S['sids'] = [k for k in S['proj']['scenes'] if not f or f in k]
        for sid in S['sids']: sl.insert('end', scene_label(sid))
        if keep is not None and keep in S['sids']:
            ix = S['sids'].index(keep); sl.selection_set(ix); sl.see(ix)
        counts()
    def row_tags(i, text): return ('done',) if text.strip() else (('odd',) if i % 2 else ())
    def set_cell(i, text):
        if tv.exists(str(i)): tv.set(str(i), 'tr', trunc(text)); tv.item(str(i), tags=row_tags(i, text))
    def refresh_rows():
        tv.delete(*tv.get_children()); S['sel'] = None
        if S['scene'] is None: return
        rows = S['proj']['scenes'][S['scene']]; f = q.get().lower().strip()
        for i, r in enumerate(rows):
            if only.get() and r['tr'].strip(): continue
            if f and f not in r['en'].lower() and f not in r['tr'].lower() and f not in r['s']: continue
            tv.insert('', 'end', iid=str(i), tags=row_tags(i, r['tr']),
                      values=(i + 1, ('SEÇENEK' if r['t'] == 'c' else spk_label(r['s'])), trunc(r['en']), trunc(r['tr'])))
    def commit():
        i = S['sel']
        if i is None or S['scene'] is None: return
        rows = S['proj']['scenes'][S['scene']]; new = tr_t.get('1.0', 'end').rstrip('\n')
        if rows[i]['tr'] != new:
            rows[i]['tr'] = new; S['dirty'] = True
            set_cell(i, new)
            if S['scene'] in S['sids']:
                idx = S['sids'].index(S['scene']); sl.delete(idx); sl.insert(idx, scene_label(S['scene'])); sl.selection_set(idx)
            counts()
    def on_scene(_=None):
        s = sl.curselection()
        if not s: return
        commit(); S['scene'] = S['sids'][s[0]]; refresh_rows()
        ch = tv.get_children()
        if ch: tv.selection_set(ch[0]); tv.focus(ch[0])
    def check_placeholders(*_):
        i = S['sel']
        if i is None: return
        r = S['proj']['scenes'][S['scene']][i]; new = tr_t.get('1.0', 'end')
        a = sorted(re.findall(r'\{\{.*?\}\}', r['en'])); b = sorted(re.findall(r'\{\{.*?\}\}', new))
        warn.set('' if (a == b or not new.strip()) else 'Uyarı: {{...}} parçaları İngilizce ile aynı olmalı: ' + ' '.join(a))
    def on_row(_=None):
        s = tv.selection()
        if not s: return
        commit(); i = int(s[0]); S['sel'] = i
        r = S['proj']['scenes'][S['scene']][i]
        spk.set(('Seçenek' if r['t'] == 'c' else 'Konuşmacı: ' + (spk_label(r['s']) or '—')) + '   [ofset %d]' % r['o'])
        en_t.configure(state='normal'); en_t.delete('1.0', 'end'); en_t.insert('1.0', r['en']); en_t.configure(state='disabled')
        tr_t.delete('1.0', 'end'); tr_t.insert('1.0', r['tr']); tr_t.focus_set(); check_placeholders()
    def push_undo(run, sid, old):
        u = S.setdefault('undo', [])
        u.append({'run': run, 'scene': sid, 'old': old}); del u[:-400]

    def undo_last():
        """Son toplu çeviri işleminin (ya da aralık silmenin) tamamını geri alır."""
        if S.get('busy'): messagebox.showinfo('Çeviri sürüyor', 'Önce çeviriyi durdurun.'); return
        u = S.get('undo') or []
        if not u: messagebox.showinfo('Geri al', 'Geri alınacak toplu çeviri yok.'); return
        run = u[-1]['run']; ents = [e for e in u if e['run'] == run]
        n = sum(len(e['old']) for e in ents)
        if not messagebox.askyesno('Geri al', f'Son işlemdeki {n} satır eski haline döndürülecek. Devam edilsin mi?'): return
        for e in reversed(ents):
            rows = S['proj']['scenes'][e['scene']]
            for i, t in e['old']: rows[i]['tr'] = t
        S['undo'] = [e for e in u if e['run'] != run]; S['dirty'] = True
        refresh_rows(); counts(); fill_scenes(S['scene'])
        messagebox.showinfo('Geri alındı', f'{n} satır geri alındı.')

    def clear_range():
        """Açık sahnede, tablodaki '#' numarasına göre bir aralığın çevirisini siler."""
        if S.get('busy'): messagebox.showinfo('Çeviri sürüyor', 'Önce çeviriyi durdurun.'); return
        if not S['proj'] or S['scene'] is None: return
        from tkinter import simpledialog
        txt = simpledialog.askstring('Çeviriyi sil', 'Silinecek satır aralığı (tablodaki # numarası, örn. 358-397 ya da 370):', parent=root)
        if not txt: return
        mm = re.fullmatch(r'\s*(\d+)\s*(?:[-–]\s*(\d+))?\s*', txt)
        if not mm: messagebox.showerror('Hata', 'Biçim: 358-397'); return
        lo = int(mm.group(1)); hi = int(mm.group(2) or lo)
        if lo > hi: lo, hi = hi, lo
        rows = S['proj']['scenes'][S['scene']]
        hit = [i for i in range(lo - 1, min(hi, len(rows))) if rows[i]['tr'].strip()]
        if not hit: messagebox.showinfo('Çeviriyi sil', 'Bu aralıkta çevrilmiş satır yok.'); return
        if not messagebox.askyesno('Çeviriyi sil', f'{lo}-{hi} aralığında {len(hit)} satırın çevirisi silinecek (geri alınabilir). Devam?'): return
        S['run'] = S.get('run', 0) + 1
        push_undo(S['run'], S['scene'], [(i, rows[i]['tr']) for i in hit])
        for i in hit: rows[i]['tr'] = ''
        S['dirty'] = True; refresh_rows(); counts(); fill_scenes(S['scene'])

    def reload_editor():
        """Seçili satırın güncel çevirisini kutuya yükler (commit YAPMAZ, yoksa yeni çeviri eskiyle ezilir)."""
        i = S['sel']
        if i is None or S['scene'] is None: return
        try:
            r = S['proj']['scenes'][S['scene']][i]
            tr_t.delete('1.0', 'end'); tr_t.insert('1.0', r['tr']); check_placeholders()
        except Exception: pass
    def move(d):
        commit(); ch = tv.get_children()
        if S['sel'] is None or str(S['sel']) not in ch: return 'break'
        k = ch.index(str(S['sel'])) + d
        if 0 <= k < len(ch): tv.selection_set(ch[k]); tv.focus(ch[k]); tv.see(ch[k])
        return 'break'
    def copy_en():
        i = S['sel']
        if i is None: return
        tr_t.delete('1.0', 'end'); tr_t.insert('1.0', S['proj']['scenes'][S['scene']][i]['en']); check_placeholders()

    def ask_api():
        w = mk_top(); w.title('API Ayarları'); w.geometry('560x420')
        ttk.Label(w, text='Çeviri servisi:').pack(anchor='w', padx=10, pady=(10, 0))
        trans_var = tk.StringVar(value=S['translator'])
        ttk.Radiobutton(w, text='DeepL (önerilen)', variable=trans_var, value='deepl').pack(anchor='w', padx=20)
        ttk.Radiobutton(w, text='Claude (Anthropic)', variable=trans_var, value='claude').pack(anchor='w', padx=20)
        ttk.Radiobutton(w, text='Gemini', variable=trans_var, value='gemini').pack(anchor='w', padx=20)
        
        ttk.Label(w, text='DeepL API anahtarı:', font=('TkDefaultFont', 9, 'bold')).pack(anchor='w', padx=10, pady=(10, 0))
        deepl_entry = ttk.Entry(w, show='*', width=60)
        deepl_entry.insert(0, S['deepl_api'])
        deepl_entry.pack(padx=10, pady=2, fill='x')
        
        ttk.Label(w, text='Claude API anahtarı:', font=('TkDefaultFont', 9, 'bold')).pack(anchor='w', padx=10, pady=(10, 0))
        claude_entry = ttk.Entry(w, show='*', width=60)
        claude_entry.insert(0, S['claude_api'])
        claude_entry.pack(padx=10, pady=2, fill='x')

        ttk.Label(w, text='Gemini API anahtarı:', font=('TkDefaultFont', 9, 'bold')).pack(anchor='w', padx=10, pady=(10, 0))
        gemini_entry = ttk.Entry(w, show='*', width=60)
        gemini_entry.insert(0, S['gemini_api'])
        gemini_entry.pack(padx=10, pady=2, fill='x')
        ttk.Label(w, text='Gemini model adı:').pack(anchor='w', padx=10)
        model_entry = ttk.Entry(w, width=60)
        model_entry.insert(0, S['gemini_model'])
        model_entry.pack(padx=10, pady=2, fill='x')
        
        def save_settings():
            S['translator'] = trans_var.get()
            S['deepl_api'] = deepl_entry.get().strip()
            S['claude_api'] = claude_entry.get().strip()
            S['gemini_api'] = gemini_entry.get().strip()
            S['gemini_model'] = model_entry.get().strip() or 'gemini-3.5-flash-lite'
            sync_service(); w.destroy()
        
        ttk.Button(w, text='Tamam', command=save_settings).pack(pady=10)
    
    def mt(count):
        """count: sahnedeki ilk N boş satırı çevirir; 0/False ise sadece seçili satırı."""
        if S.get('busy'):
            messagebox.showinfo('Çeviri sürüyor', 'Önce şu anki çeviri bitsin.'); return
        if S['translator'] == 'deepl' and not S['deepl_api']:
            ask_api()
            if not S['deepl_api']: return
        elif S['translator'] == 'claude' and not S['claude_api']:
            ask_api()
            if not S['claude_api']: return
        elif S['translator'] == 'gemini' and not S['gemini_api']:
            ask_api()
            if not S['gemini_api']: return

        if S['scene'] is None: return
        scene = S['scene']
        rows = S['proj']['scenes'][scene]
        if count: idxs = [int(x) for x in tv.get_children() if not rows[int(x)]['tr'].strip()]
        elif S['sel'] is not None: idxs = [S['sel']]
        else: return
        if count and count > 0: idxs = idxs[:count]
        if not idxs: return
        if count == -1 and not messagebox.askyesno('Sahnenin tamamı',
                f'Bu sahnede çevrilmemiş {len(idxs)} satır var (yaklaşık {-(-len(idxs) // 40)} API isteği).\n'
                'Hepsi çevrilsin mi? İstediğiniz an "Durdur" düğmesiyle kesebilirsiniz.'): return
        S['stop'] = False
        commit()
        gl = {k: v for k, v in S['proj']['speakers'].items() if v}
        if S['translator'] == 'deepl': fn = lambda ls: deepl_translate(ls, S['deepl_api'], gl)
        elif S['translator'] == 'gemini': fn = lambda ls: gemini_translate(ls, S['gemini_api'], gl, model=S['gemini_model'])
        else: fn = lambda ls: claude_translate(ls, S['claude_api'], gl)
        S['busy'] = True
        title0 = 'Seen.txt Çeviri Aracı (Türkçe Karakter Destekli)'
        set_title(f'Çevriliyor ({S["translator"].upper()})… 0/{len(idxs)}')

        S['run'] = S.get('run', 0) + 1; run = S['run']
        def apply(part, res):
            old = []
            for i, t in zip(part, res):
                if t is None: continue                            # model bu satırı çevirmedi
                if count and rows[i]['tr'].strip(): continue      # bu arada elle yazılanı ezme
                old.append((i, rows[i]['tr'])); rows[i]['tr'] = t
                if S['scene'] == scene: set_cell(i, t)
            if old: push_undo(run, scene, old)
            S['dirty'] = True

        def work():
            def on_chunk(part, res): root.after(0, lambda: apply(part, res))
            def on_prog(d, n): root.after(0, lambda: set_title(f'Çevriliyor ({S["translator"].upper()})… {d}/{n}'))
            done, err = translate_rows(rows, idxs, fn, on_chunk, on_prog, lambda: S.get('stop'))
            def finish():
                S['busy'] = False; set_title(title0)
                reload_editor(); fill_scenes(S['scene']); counts()
                if count and S['path']:
                    try: save()
                    except Exception: pass
                if err: messagebox.showerror('Çeviri hatası', f'{done}/{len(idxs)} satır çevrildi, sonra durdu:\n{err}')
                elif S.get('stop'): messagebox.showinfo('Durduruldu', f'{done}/{len(idxs)} satır çevrildi.')
            root.after(0, finish)
        threading.Thread(target=work, daemon=True).start()

    def auto_toggle():
        if S.get('auto'):
            S['stop'] = True; auto_btn.configure(text='Durduruluyor…'); return
        if S.get('busy'):
            messagebox.showinfo('Çeviri sürüyor', 'Önce şu anki çeviri bitsin.'); return
        if not S['proj']: return
        if S['translator'] == 'deepl' and not S['deepl_api']:
            ask_api()
            if not S['deepl_api']: return
        elif S['translator'] == 'claude' and not S['claude_api']:
            ask_api()
            if not S['claude_api']: return
        elif S['translator'] == 'gemini' and not S['gemini_api']:
            ask_api()
            if not S['gemini_api']: return
        commit()
        scenes = S['proj']['scenes']; sids = list(scenes.keys())
        start = sids.index(S['scene']) if S['scene'] in sids else 0
        order = sids[start:] + sids[:start]
        total = sum(1 for rows in scenes.values() for r in rows if not r['tr'].strip())
        if not total:
            messagebox.showinfo('Oto çeviri', 'Çevrilmemiş satır kalmadı.'); return
        if not messagebox.askyesno('Oto çeviri',
                f'Toplam {total} çevrilmemiş satır var (yaklaşık {-(-total // 40)} API isteği).\n'
                'Seçili sahneden başlayıp 40\'ar satır çevirerek tüm sahneleri gezecek.\n'
                'Durdurana ya da bitene kadar çalışır; bilgisayarın uyumasını engeller.\n'
                'Başlatılsın mı?'): return
        gl = {k: v for k, v in S['proj']['speakers'].items() if v}
        if S['translator'] == 'deepl': fn = lambda ls: deepl_translate(ls, S['deepl_api'], gl)
        elif S['translator'] == 'gemini': fn = lambda ls: gemini_translate(ls, S['gemini_api'], gl, model=S['gemini_model'])
        else: fn = lambda ls: claude_translate(ls, S['claude_api'], gl)
        S['busy'] = True; S['auto'] = True; S['stop'] = False
        auto_btn.configure(text='■ Oto çeviriyi durdur')
        title0 = 'Seen.txt Çeviri Aracı (Türkçe Karakter Destekli)'
        log_path = (S['path'] or 'Seen_ceviri.json') + '.oto.log'
        def log(msg):
            try:
                with open(log_path, 'a', encoding='utf-8') as f: f.write(time.strftime('%H:%M:%S ') + msg + '\n')
            except Exception: pass
        log('=== oto çeviri başladı: %d satır ===' % total)
        counter = {'done': 0}

        S['run'] = S.get('run', 0) + 1; run = S['run']
        def apply(sid, idxs, res):
            rows = scenes[sid]
            push_undo(run, sid, [(i, rows[i]['tr']) for i in idxs])
            for i, t in zip(idxs, res): rows[i]['tr'] = t
            counter['done'] += len(idxs); S['dirty'] = True
            log('sahne %s: %d satır (toplam %d/%d)' % (sid, len(idxs), counter['done'], total))
            def ui():
                if S['scene'] == sid:
                    for i, t in zip(idxs, res):
                        set_cell(i, t)
                    if S['sel'] in idxs: reload_editor()
                counts()
                set_title(f'OTO ÇEVİRİ… {counter["done"]}/{total} · sahne {sid}')
            root.after(0, ui)

        def on_wait(msg):
            log('bekleme: ' + msg)
            root.after(0, lambda: set_title(f'OTO ÇEVİRİ · {msg} · {counter["done"]}/{total}'))

        def work():
            def sleep_flag(on):
                try:
                    import ctypes; ctypes.windll.kernel32.SetThreadExecutionState(0x80000001 if on else 0x80000000)
                except Exception: pass
            sleep_flag(True); err = None; skipped = 0
            try:
                _, skipped = auto_translate(scenes, order, fn, apply, lambda: S.get('stop'), log,
                                            exclude=lambda sid, i: S['scene'] == sid and S['sel'] == i, on_wait=on_wait)
                if not S.get('stop'):          # ekranda seçili olduğu için atlanan satırı da çevir
                    _, sk2 = auto_translate(scenes, order, fn, apply, lambda: S.get('stop'), log, on_wait=on_wait)
                    skipped = max(skipped, sk2)
            except Exception as ex:
                err = str(ex); log('DURDU: ' + err)
            finally: sleep_flag(False)
            stopped = bool(S.get('stop'))
            log('=== bitti: %d satır, %d atlandı%s ===' % (counter['done'], skipped, ' (durduruldu)' if stopped else ''))
            def finish():
                S['busy'] = False; S['auto'] = False; S['stop'] = False
                auto_btn.configure(text="▶ Oto çeviri (40'ar)"); set_title(title0)
                try: reload_editor(); fill_scenes(S['scene']); save()
                except Exception: pass
                extra = f'\n{skipped} satır çevrilemedi (log: {log_path}).' if skipped else ''
                if err: messagebox.showerror('Oto çeviri durdu', f'{counter["done"]}/{total} satır çevrildi, sonra durdu:\n{err}{extra}')
                elif stopped: messagebox.showinfo('Oto çeviri durduruldu', f'{counter["done"]}/{total} satır çevrildi.{extra}')
                else: messagebox.showinfo('Oto çeviri bitti', f'{counter["done"]} satır çevrildi.{extra}')
            root.after(0, finish)
        threading.Thread(target=work, daemon=True).start()


    def set_project(proj, path):
        for k, v in proj.get('speakers', {}).items():
            if not v.strip(): proj['speakers'][k] = default_name(k)
        S['proj'] = proj; S['path'] = path; S['scene'] = None; S['sel'] = None; S['dirty'] = False
        
        # Türkçe mod ayarını yükle
        if 'turkish_chars' in proj:
            S['turkish_mode'].set(proj['turkish_chars'])
        
        fill_scenes(); tv.delete(*tv.get_children())
        set_title('Seen.txt Çeviri Aracı (Türkçe Karakter Destekli) - ' + (os.path.basename(path) if path else ''))
    
    def save(_=None):
        commit()
        if not S['proj']: return
        if not S['path']:
            S['path'] = filedialog.asksaveasfilename(defaultextension='.json', filetypes=[('Proje', '*.json')])
            if not S['path']: return
        
        # Türkçe mod ayarını kaydet
        S['proj']['turkish_chars'] = S['turkish_mode'].get()
        
        save_project(S['proj'], S['path']); S['dirty'] = False
    
    def open_seen():
        p = filedialog.askopenfilename(title='Seen.txt seç')
        if not p: return
        win = mk_top(); win.title('Çözülüyor…')
        pb = ttk.Progressbar(win, length=360, maximum=100); pb.pack(padx=20, pady=20); win.update()
        def prog(n, t): root.after(0, lambda: pb.configure(value=100 * n / t))
        def work():
            try:
                proj = extract_project(p, prog)
                def done():
                    win.destroy(); sp = os.path.splitext(p)[0] + '_ceviri.json'
                    S['seen'] = p; set_project(proj, sp); save()
                    messagebox.showinfo('Hazır', 'Arşiv çözüldü.\nProje dosyası: ' + sp)
                root.after(0, done)
            except Exception as ex:
                msg = str(ex)
                root.after(0, lambda: (win.destroy(), messagebox.showerror('Hata', msg)))
        threading.Thread(target=work, daemon=True).start()
    
    def open_proj():
        p = filedialog.askopenfilename(title='Proje aç', filetypes=[('Proje', '*.json')])
        if p:
            proj = load_project(p); set_project(proj, p)
            guess = os.path.join(os.path.dirname(p), proj.get('source', 'Seen.txt'))
            if os.path.exists(guess): S['seen'] = guess
    
    def export_seen():
        commit()
        if not S['proj']: return
        if not S['seen'] or not os.path.exists(S['seen']):
            S['seen'] = filedialog.askopenfilename(title='Orijinal Seen.txt dosyasını seç')
            if not S['seen']: return
        out = filedialog.asksaveasfilename(title='Yeni Seen.txt olarak kaydet', initialfile='Seen_TR.txt')
        if not out: return
        if os.path.abspath(out) == os.path.abspath(S['seen']):
            messagebox.showerror('Hata', 'Orijinal dosyanın üstüne yazılamaz.'); return
        
        # Türkçe mod ayarını kaydet
        S['proj']['turkish_chars'] = S['turkish_mode'].get()
        save()
        
        try:
            fold = not S['turkish_mode'].get()
            n = build_archive(S['seen'], S['proj'], out, fold=fold); v = verify_archive(out)
            
            if S['turkish_mode'].get():
                msg = f'{n} sahne güncellendi, {v} sahne doğrulandı.\n\n'
                msg += '✓ Türkçe karakterler (ğ,ş,ı,ç,ö,ü) korundu!\n\n'
                msg += 'ÖNEMLİ: Türkçe harfli font gerekli:\n'
                msg += 'make_font.py çalıştırın (README_FONT.txt)'
            else:
                msg = f'{n} sahne güncellendi, {v} sahne doğrulandı.\n\n'
                msg += 'Türkçe özel harfler (ğ,ş,ı,ç,ö,ü) ASCII\'ye çevrildi.'
            
            messagebox.showinfo('Tamam', msg)
        except Exception as ex: messagebox.showerror('Hata', str(ex))
    
    def export_tsv():
        if not S['proj']: return
        commit(); save()
        p = filedialog.asksaveasfilename(defaultextension='.tsv')
        if p and S['path']: cmd_tsv(S['path'], p)
    
    def speakers_dlg():
        if not S['proj']: return
        w = mk_top(); w.title('Karakter adları'); w.geometry('440x540')
        ttk.Label(w, text='Japonca ad → Türkçe ad (boş = değiştirme)').pack(pady=4)
        ttk.Button(w, text='Tamam', command=lambda: ok()).pack(side='bottom', pady=4)
        cv = tk.Canvas(w); fr = ttk.Frame(cv); vs = ttk.Scrollbar(w, command=cv.yview); cv.configure(yscrollcommand=vs.set)
        vs.pack(side='right', fill='y'); cv.pack(fill='both', expand=True); cv.create_window((0, 0), window=fr, anchor='nw')
        fr.bind('<Configure>', lambda e: cv.configure(scrollregion=cv.bbox('all')))
        vars_ = {}
        for k, name in enumerate(sorted(S['proj']['speakers'])):
            ttk.Label(fr, text=name, width=18).grid(row=k, column=0, sticky='w', padx=4)
            v = tk.StringVar(value=S['proj']['speakers'][name]); vars_[name] = v
            ttk.Entry(fr, textvariable=v, width=28).grid(row=k, column=1, pady=1)
        def ok():
            for n, v in vars_.items(): S['proj']['speakers'][n] = v.get().strip()
            S['dirty'] = True; w.destroy()
    
    def font_patch_dialog():
        w = mk_top(); w.title('Font Patch'); w.geometry('600x300')
        
        ttk.Label(w, text='RealLive Font Dosyasına Türkçe Karakter Ekle', 
                 font=('TkDefaultFont', 12, 'bold')).pack(pady=10)
        
        ttk.Label(w, text='Oyun klasöründeki font dosyasını seçin (.g00, .pdt, .fnt):').pack(pady=5)
        
        input_frame = ttk.Frame(w)
        input_frame.pack(fill='x', padx=20, pady=5)
        input_path = tk.StringVar()
        ttk.Entry(input_frame, textvariable=input_path, width=50).pack(side='left', padx=5)
        ttk.Button(input_frame, text='Seç', command=lambda: input_path.set(
            filedialog.askopenfilename(title='Font dosyasını seç')
        )).pack(side='left')
        
        ttk.Label(w, text='Çıktı dosyası:').pack(pady=5)
        output_frame = ttk.Frame(w)
        output_frame.pack(fill='x', padx=20, pady=5)
        output_path = tk.StringVar()
        ttk.Entry(output_frame, textvariable=output_path, width=50).pack(side='left', padx=5)
        ttk.Button(output_frame, text='Seç', command=lambda: output_path.set(
            filedialog.asksaveasfilename(title='Patch\'lenmiş dosyayı kaydet')
        )).pack(side='left')
        
        def do_patch():
            if not input_path.get():
                messagebox.showerror('Hata', 'Font dosyası seçin!')
                return
            if not output_path.get():
                messagebox.showerror('Hata', 'Çıktı dosyası seçin!')
                return
            
            try:
                success = patch_font_file(input_path.get(), output_path.get())
                if success:
                    w.destroy()
            except Exception as e:
                messagebox.showerror('Hata', str(e))
        
        ttk.Button(w, text='Font Patch Uygula', command=do_patch).pack(pady=20)
        
        info = 'Not: Font patch sonrası patch\'lenmiş dosyayı oyun klasörüne kopyalayın.\n'
        info += 'Orijinal font dosyasını yedeklemeyi unutmayın!'
        ttk.Label(w, text=info, foreground='blue').pack(pady=10)

    m = tk.Menu(root); fm = tk.Menu(m, tearoff=0)
    fm.add_command(label='Seen.txt aç (çöz)…', command=open_seen); fm.add_command(label='Proje aç…', command=open_proj)
    fm.add_command(label='Kaydet (Ctrl+S)', command=save); fm.add_separator()
    fm.add_command(label='Seen.txt olarak dışa aktar…', command=export_seen)
    fm.add_command(label='TSV olarak dışa aktar…', command=export_tsv); fm.add_separator()
    fm.add_command(label='Çıkış', command=lambda: on_close())
    m.add_cascade(label='Dosya', menu=fm)
    tm = tk.Menu(m, tearoff=0); tm.add_command(label='Karakter adları…', command=speakers_dlg)
    tm.add_command(label='API Ayarları…', command=ask_api)
    tm.add_command(label='Son toplu çeviriyi geri al', command=undo_last)
    tm.add_command(label='Satır aralığının çevirisini sil…', command=clear_range)
    tm.add_command(label='Font Patch (Türkçe karakter için)…', command=font_patch_dialog)
    m.add_cascade(label='Araçlar', menu=tm)
    vm = tk.Menu(m, tearoff=0)
    vm.add_checkbutton(label='Koyu tema', variable=theme_var, command=lambda: apply_theme('dark' if theme_var.get() else 'light') or save_settings({**load_settings(), 'theme': S['theme']}))
    m.add_cascade(label='Görünüm', menu=vm)
    root.config(menu=m)

    sl.bind('<<ListboxSelect>>', on_scene); tv.bind('<<TreeviewSelect>>', on_row)
    tr_t.bind('<Control-Return>', lambda e: move(1)); tr_t.bind('<KeyRelease>', check_placeholders)
    root.bind('<Control-s>', save)
    q.trace_add('write', lambda *a: (commit(), refresh_rows()))
    only.trace_add('write', lambda *a: (commit(), refresh_rows()))
    sq.trace_add('write', lambda *a: S['proj'] and fill_scenes(S['scene']))
    def autosave():
        if S['dirty'] and S['path']:
            try: commit(); S['proj']['turkish_chars'] = S['turkish_mode'].get(); save_project(S['proj'], S['path']); S['dirty'] = False
            except Exception: pass
        root.after(60000, autosave)
    def on_close():
        try: commit()
        except Exception: pass
        if S['dirty'] and S['path']: 
            S['proj']['turkish_chars'] = S['turkish_mode'].get()
            save_project(S['proj'], S['path'])
        save_settings({**load_settings(), 'theme': S['theme'], 'geometry': root.geometry()})
        root.destroy()
    root.protocol('WM_DELETE_WINDOW', on_close); autosave()
    if initial and initial.lower().endswith('.json'):
        proj = load_project(initial); set_project(proj, initial)
        guess = os.path.join(os.path.dirname(os.path.abspath(initial)), proj.get('source', 'Seen.txt'))
        if os.path.exists(guess): S['seen'] = guess
    root.mainloop()

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(description='RealLive Seen.txt çeviri aracı (Türkçe karakter destekli)')
    sp = ap.add_subparsers(dest='cmd')
    sp.add_parser('gui').add_argument('proje', nargs='?')
    a = sp.add_parser('unpack'); a.add_argument('seen'); a.add_argument('klasor')
    a = sp.add_parser('extract'); a.add_argument('seen'); a.add_argument('proje')
    a = sp.add_parser('build'); a.add_argument('seen'); a.add_argument('proje'); a.add_argument('cikti')
    a.add_argument('--turkish', action='store_true', help='Türkçe karakterleri koru (make_font.py ile üretilen font gerektirir)')
    a = sp.add_parser('verify'); a.add_argument('seen')
    a = sp.add_parser('tsv'); a.add_argument('proje'); a.add_argument('cikti')
    a = sp.add_parser('patch-font'); a.add_argument('input'); a.add_argument('output')
    a = sp.add_parser('rebase', help='Eski projeyi orijinal Seen.txt temeline taşı'); a.add_argument('eski_json'); a.add_argument('orijinal_seen'); a.add_argument('yeni_json')
    a = sp.add_parser('repair', help='Eski kodlu Türkçe harfleri yeni kodlara çevir'); a.add_argument('seen'); a.add_argument('cikti')
    
    ns = ap.parse_args()
    if ns.cmd in (None, 'gui'): run_gui(getattr(ns, 'proje', None))
    elif ns.cmd == 'unpack': cmd_unpack(ns.seen, ns.klasor)
    elif ns.cmd == 'extract':
        proj = extract_project(ns.seen); save_project(proj, ns.proje)
        print('%d sahne, %d satır -> %s' % (len(proj['scenes']), sum(len(r) for r in proj['scenes'].values()), ns.proje))
    elif ns.cmd == 'build':
        proj = load_project(ns.proje)
        fold = not ns.turkish
        n = build_archive(ns.seen, proj, ns.cikti, fold=fold)
        print('%d sahne güncellendi; doğrulama: %d sahne OK' % (n, verify_archive(ns.cikti)))
        if ns.turkish:
            print('\n✓ Türkçe karakterler korundu! make_font.py ile font üretip kurun (README_FONT.txt).')
    elif ns.cmd == 'rebase':
        new, moved, skipped = rebase_project(load_project(ns.eski_json), ns.orijinal_seen)
        save_project(new, ns.yeni_json)
        print('%d çeviri taşındı, %d atlandı -> %s' % (moved, skipped, ns.yeni_json))
    elif ns.cmd == 'repair':
        n, ch = repair_archive(ns.seen, ns.cikti)
        print('%d Türkçe satır yeniden kodlandı, %d sahne güncellendi; doğrulama: %d sahne OK' % (n, ch, verify_archive(ns.cikti)))
    elif ns.cmd == 'verify': print('%d sahne doğrulandı' % verify_archive(ns.seen))
    elif ns.cmd == 'tsv': cmd_tsv(ns.proje, ns.cikti)
    elif ns.cmd == 'patch-font':
        try: patch_font_file(ns.input, ns.output)
        except ValueError as ex: print('Hata:', ex); sys.exit(1)

if __name__ == '__main__':
    main()
