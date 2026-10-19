@echo off
setlocal
title CLANNAD Turkce Font Kurulumu
cd /d "%~dp0"
REM Kullanim:
REM   font_kur.bat                  : kurar, oyun klasorunu kendisi bulur
REM   font_kur.bat "C:\...\CLANNAD"  : kurar, klasoru elle verirsiniz
REM   font_kur.bat /geri            : eski hale dondurur
set "SEEN_BAT=%~f0"
set "SEEN_HERE=%~dp0"
set "SEEN_MODE=kur"
set "SEEN_GAME=%~1"
if /i "%~1"=="/geri" set "SEEN_MODE=geri" & set "SEEN_GAME=%~2"
where powershell >nul 2>&1 || (echo PowerShell bulunamadi. & pause & exit /b 1)
powershell -NoProfile -ExecutionPolicy Bypass -Command "$s=[IO.File]::ReadAllText($env:SEEN_BAT); $i=$s.IndexOf('#PS'+'_BEGIN'); Invoke-Expression $s.Substring($i)"
echo.
pause
exit /b 0
#PS_BEGIN
$ErrorActionPreference = 'Stop'
$env:PYTHONUTF8 = '1'
$here    = $env:SEEN_HERE.TrimEnd('\')
$mode    = $env:SEEN_MODE
$stamp   = (Get-Date).ToString('yyMMddHHmm')
$family  = 'SeenGothicTR' + $stamp
$ttfName = $family + '.ttf'
$regName = $family + ' (TrueType)'
$regKey  = 'HKCU:\Software\Microsoft\Windows NT\CurrentVersion\Fonts'
$fontDir = Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\Fonts'
$fontDest = Join-Path $fontDir $ttfName

function Say($m, $c = 'Gray') { Write-Host $m -ForegroundColor $c }

# Onceki surumlerin kayit ve dosyalarini kaldirir (kullanimdaysa sessizce atlar)
function Remove-OldFonts {
    try {
        $k = Get-Item -Path $regKey -ErrorAction Stop
        foreach ($n in @($k.Property)) {
            if ($n -like 'SeenGothicTR*') {
                $old = $k.GetValue($n)
                try { [void][SeenW.F]::RemoveFontResourceW($old) } catch {}
                try { Remove-ItemProperty -Path $regKey -Name $n -ErrorAction Stop } catch {}
                if ($old) { Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue }
            }
        }
    } catch {}
    Get-ChildItem -LiteralPath $fontDir -Filter 'SeenGothicTR*.ttf' -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
    Get-ChildItem -LiteralPath $here -Filter 'SeenGothicTR*.ttf' -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
}

function Find-Game {
    $cands = @()
    if ($env:SEEN_GAME) { $cands += $env:SEEN_GAME.Trim('"', ' ') }
    $libs = @()
    $sp = $null
    try { $sp = (Get-ItemProperty 'HKCU:\Software\Valve\Steam' -ErrorAction Stop).SteamPath } catch {}
    if ($sp) {
        $sp = $sp -replace '/', '\'
        $libs += $sp
        $vdf = Join-Path $sp 'steamapps\libraryfolders.vdf'
        if (Test-Path $vdf) {
            foreach ($m in [regex]::Matches([IO.File]::ReadAllText($vdf), '"path"\s+"([^"]+)"')) {
                $libs += ($m.Groups[1].Value -replace '\\\\', '\')
            }
        }
    }
    $libs += 'C:\Program Files (x86)\Steam'
    $libs += 'C:\Program Files\Steam'
    foreach ($l in $libs) { $cands += (Join-Path $l 'steamapps\common\CLANNAD') }
    foreach ($p in $cands) {
        if ($p -and (Test-Path -LiteralPath (Join-Path $p 'Gameexe.ini'))) { return $p }
    }
    return $null
}

# Gameexe.ini'ye iki satir ekler. Dosya bayt bayt korunur (Shift-JIS bozulmaz).
function Patch-Ini($ini, $fam) {
    $enc  = [Text.Encoding]::GetEncoding(28591)
    $crlf = [string][char]13 + [string][char]10
    $q    = [string][char]34
    $text = $enc.GetString([IO.File]::ReadAllBytes($ini))
    $lines = [regex]::Split($text, '\r\n')
    $out = New-Object 'System.Collections.Generic.List[string]'
    $added = $false
    foreach ($l in $lines) {
        if ($l -match '^#(ALL_FONT_USE|INIT_FONT_NAME)\s*=') { continue }
        $out.Add($l)
        if (-not $added -and $l -match '^#INIT_FONT_TYPE\s*=') {
            $out.Add('#ALL_FONT_USE=1')
            $out.Add('#INIT_FONT_NAME=' + $q + $fam + $q)
            $added = $true
        }
    }
    if (-not $added) {
        $idx = $out.Count
        if ($idx -gt 0 -and $out[$idx - 1] -eq '') { $idx-- }
        $out.Insert($idx, '#ALL_FONT_USE=1')
        $out.Insert($idx + 1, '#INIT_FONT_NAME=' + $q + $fam + $q)
    }
    [IO.File]::WriteAllBytes($ini, $enc.GetBytes(($out -join $crlf)))
}

try {
    Add-Type -Namespace SeenW -Name F -MemberDefinition @'
[DllImport("gdi32.dll", CharSet = CharSet.Unicode)] public static extern int AddFontResourceW(string f);
[DllImport("gdi32.dll", CharSet = CharSet.Unicode)] public static extern int RemoveFontResourceW(string f);
[DllImport("user32.dll")] public static extern int SendMessageTimeout(IntPtr h, uint m, IntPtr w, IntPtr l, uint f, uint t, out IntPtr r);
'@
} catch {}

try {
    Say '=== CLANNAD Turkce font kurulumu ===' 'Cyan'
    $game = Find-Game
    if (-not $game) {
        Say 'Oyun klasoru otomatik bulunamadi.' 'Yellow'
        $in = (Read-Host 'CLANNAD klasorunun yolunu yapistirin').Trim('"', ' ')
        if (-not (Test-Path -LiteralPath (Join-Path $in 'Gameexe.ini'))) { throw 'Bu klasorde Gameexe.ini yok.' }
        $game = $in
    }
    Say "Oyun klasoru: $game"
    $ini = Join-Path $game 'Gameexe.ini'
    $bak = Join-Path $game 'Gameexe.ini.bak_font'

    if ($mode -eq 'geri') {
        if (Test-Path -LiteralPath $bak) {
            Copy-Item -LiteralPath $bak -Destination $ini -Force
            Say 'Gameexe.ini yedekten geri yuklendi.' 'Green'
        } else {
            Say 'Yedek bulunamadi, Gameexe.ini degistirilmedi.' 'Yellow'
        }
        Remove-OldFonts
        Say 'Font kayitlari silindi.'
        Say 'Geri alma tamam. Seen.txt yedeginizi de geri koymayi unutmayin.' 'Green'
        return
    }

    # 1) Python
    $py = $null
    foreach ($c in @('py', 'python', 'python3')) {
        try {
            $o = & $c --version 2>&1
            if ($LASTEXITCODE -eq 0 -and "$o" -match 'Python 3') { $py = $c; break }
        } catch {}
    }
    if (-not $py) { throw 'Python 3 bulunamadi. python.org adresinden kurun ("Add python.exe to PATH" kutusunu isaretleyin).' }
    Say "Python bulundu: $py"

    # 2) fonttools
    Say 'fonttools kuruluyor...'
    & $py -m pip install --quiet --disable-pip-version-check fonttools
    if ($LASTEXITCODE -ne 0) { throw 'fonttools kurulamadi (internet baglantisini kontrol edin).' }

    # 3) Fontu uret (MS Gothic -> SeenGothicTR)
    $src = Join-Path $env:WINDIR 'Fonts\msgothic.ttc'
    if (-not (Test-Path -LiteralPath $src)) { throw 'MS Gothic (msgothic.ttc) bulunamadi.' }
    $mk = Join-Path $here 'make_font.py'
    if (-not (Test-Path -LiteralPath $mk)) { throw 'make_font.py bu .bat dosyasiyla ayni klasorde olmali.' }
    Remove-OldFonts
    $ttf = Join-Path $here $ttfName
    Say "Font uretiliyor ($family)..."
    & $py $mk $src $ttf $family
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $ttf)) { throw 'Font uretilemedi (yukaridaki mesaja bakin).' }

    # 4) Fontu kullanici icin kur
    $build = [int](Get-CimInstance Win32_OperatingSystem).BuildNumber
    if ($build -lt 17763) {
        Say 'Bu Windows surumu kullanici bazli font kurulumunu desteklemiyor.' 'Yellow'
        Say 'Acilan pencerede "Yukle" tusuna basin, sonra bu betigi tekrar calistirin.' 'Yellow'
        Start-Process -LiteralPath $ttf
        return
    }
    New-Item -ItemType Directory -Force -Path $fontDir | Out-Null
    try { Copy-Item -LiteralPath $ttf -Destination $fontDest -Force }
    catch { throw 'Font dosyasi kullanimda. Oyunu kapatip tekrar deneyin (gerekirse bilgisayari yeniden baslatin).' }
    New-ItemProperty -Path $regKey -Name $regName -Value $fontDest -PropertyType String -Force | Out-Null
    try {
        [void][SeenW.F]::AddFontResourceW($fontDest)
        $r = [IntPtr]::Zero
        [void][SeenW.F]::SendMessageTimeout([IntPtr]0xffff, 0x1D, [IntPtr]::Zero, [IntPtr]::Zero, 2, 1000, [ref]$r)
    } catch {}
    Say 'Font kuruldu.' 'Green'

    # 5) Gameexe.ini (once yedek)
    if (-not (Test-Path -LiteralPath $bak)) { Copy-Item -LiteralPath $ini -Destination $bak }
    Patch-Ini $ini $family
    Say 'Gameexe.ini guncellendi (yedek: Gameexe.ini.bak_font).' 'Green'

    Say ''
    Say 'TAMAM. Siradaki adimlar:' 'Cyan'
    Say '  1) Ceviri aracinda "Turkce karakter" kutusunu isaretleyip Seen.txt olarak disa aktarin.'
    Say '  2) Yeni Seen.txt dosyasini oyun klasorune koyun (orijinalin yedegini alin).'
    Say "  3) Oyunu acin. Font adi her kurulumda degisir: oyunun font ayarinda $family secili olmali."
    Say '  Geri almak icin: font_kur.bat /geri'
} catch {
    Say ('HATA: ' + $_.Exception.Message) 'Red'
}
