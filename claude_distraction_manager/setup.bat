@echo off
title Claude Distraction Manager — Setup
color 0A

echo =====================================================
echo   Claude Distraction Manager — One-Click Setup
echo =====================================================
echo.

:: Check Python
python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python is not installed or not in PATH.
    echo Download from: https://www.python.org/downloads/
    pause
    exit /b 1
)

echo [1/4] Installing Python dependencies...
pip install -r requirements.txt
if errorlevel 1 (
    echo [ERROR] pip install failed. Check your internet connection.
    pause
    exit /b 1
)
echo.

echo [2/4] Installing Playwright browser (Chromium)...
playwright install chromium
if errorlevel 1 (
    echo [ERROR] Playwright browser install failed.
    pause
    exit /b 1
)
echo.

echo [3/4] Verifying installation...
python -c "import playwright, pygetwindow, keyboard, psutil; print('All dependencies OK')"
echo.

echo [4/4] Setup complete!
echo.
echo =====================================================
echo   How to run:
echo     python claude_distraction_manager.py
echo.
echo   First run: Log into Claude in the browser window
echo              that opens automatically.
echo.
echo   Toggle on/off:  Ctrl+Shift+D
echo =====================================================
echo.
pause
