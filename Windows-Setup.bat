@echo off
title QuickTasks Windows Setup
echo Checking for Python...
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Python 3 is not installed or not added to PATH. 
    echo Please install Python (check "Add Python to PATH") and run this setup again.
    pause
    exit /b 1
)
pip --version >nul 2>&1
if %errorlevel% neq 0 (
    echo Pip is not installed. Please install pip.
    pause
    exit /b 1
)
echo Python found. Running installer...
python install.py
pause
