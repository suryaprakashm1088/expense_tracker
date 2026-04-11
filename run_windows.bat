@echo off
REM ─────────────────────────────────────────────────────────────────────────────
REM  Expense Tracker – Quick Start (Windows)
REM  Double-click this file or run from Command Prompt
REM ─────────────────────────────────────────────────────────────────────────────

echo.
echo  ============================================
echo    💰  Expense Tracker  💰
echo  ============================================
echo.

cd /d "%~dp0"

REM Check Python
where python >nul 2>&1
if %errorlevel% neq 0 (
  echo ERROR: Python not found. Install Python 3.8+ from https://python.org
  pause
  exit /b 1
)

REM Create venv
if not exist "venv\" (
  echo Creating virtual environment...
  python -m venv venv
)

REM Activate and install
call venv\Scripts\activate
echo Installing dependencies...
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo.
echo Setup complete!
echo Starting server at http://127.0.0.1:5000
echo Press Ctrl+C to stop.
echo.

python app.py
pause
