@echo off
REM Yerelde (Windows) exe derlemek icin: cift tikla veya cmd'den calistir
python -m pip install -r requirements.txt || goto :err
pyinstaller --noconfirm --clean --onefile --windowed --collect-data sv_ttk --name SeenTool Seen.py || goto :err
pyinstaller --noconfirm --onefile --console --name SeenTool-cli Seen.py || goto :err
echo.
echo Tamam: dist\SeenTool.exe (arayuz) ve dist\SeenTool-cli.exe (komut satiri)
pause
exit /b 0
:err
echo Derleme basarisiz oldu.
pause
exit /b 1
