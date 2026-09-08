@echo off
setlocal EnableExtensions
cd /d "%~dp0"

where py >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python launcher ^(py.exe^) was not found. Install Python 3.11+ for Windows.
  exit /b 2
)

if not exist ".launcher-build-venv\Scripts\python.exe" (
  py -3 -m venv .launcher-build-venv
  if errorlevel 1 exit /b 3
)

call .launcher-build-venv\Scripts\activate.bat
python -m pip install --upgrade pip
if errorlevel 1 exit /b 4
python -m pip install -r tools\windows-launcher\requirements-build.txt
if errorlevel 1 exit /b 5

if exist build\CryptoPlatform rmdir /s /q build\CryptoPlatform
if exist dist\CryptoPlatform.exe del /q dist\CryptoPlatform.exe

pyinstaller --noconfirm --clean --distpath dist --workpath build\CryptoPlatform tools\windows-launcher\CryptoPlatform.spec
if errorlevel 1 exit /b 6

if not exist "dist\CryptoPlatform.exe" (
  echo [ERROR] PyInstaller completed without producing dist\CryptoPlatform.exe
  exit /b 7
)

echo [OK] Built dist\CryptoPlatform.exe
exit /b 0
