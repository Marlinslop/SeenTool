@echo off
setlocal
title Seen Tool - Eski Turkce Kodlari Onar
cd /d "%~dp0"
REM Kullanim: onarmak istediginiz Seen dosyasini bu .bat dosyasinin ustune surukleyip birakin.
if "%~1"=="" (
  echo Seen dosyasini bu dosyanin ustune surukleyip birakin.
  pause
  exit /b 1
)
set "OUT=%~dpn1_duzeltilmis.txt"
python "%~dp0Seen.py" repair "%~1" "%OUT%"
if errorlevel 1 (
  echo.
  echo Hata olustu. Python kurulu mu ve Seen.py bu dosyayla ayni klasorde mi?
) else (
  echo.
  echo Tamam: "%OUT%"
  echo Oyun klasorunde Seen.txt yedegini alip bu dosyanin adini Seen.txt yapin.
)
pause
exit /b 0
