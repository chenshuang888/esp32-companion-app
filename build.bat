@echo off
setlocal

echo ===== ESP32 Companion build =====

if not exist .venv (
    echo [1/4] create venv ...
    python -m venv .venv
    if errorlevel 1 (
        echo create venv failed. is python in PATH?
        exit /b 1
    )
) else (
    echo [1/4] .venv exists, skip
)

echo [2/4] install deps ...
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip -q
python -m pip install -r requirements.txt pyinstaller -q
if errorlevel 1 (
    echo install deps failed.
    exit /b 1
)

echo [3/4] clean old build ...
if exist build rmdir /s /q build
if exist dist  rmdir /s /q dist

echo [4/4] pyinstaller ...
pyinstaller ESP32Companion.spec --noconfirm
if errorlevel 1 (
    echo pyinstaller failed.
    exit /b 1
)

echo.
echo ===== done =====
echo output: dist\ESP32Companion.exe
endlocal
