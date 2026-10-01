@echo off
echo ================================================
echo  Chess Analyzer - Starting up...
echo ================================================
echo.

:: Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python not found. Install Python 3.8+ from python.org
    pause
    exit /b
)

:: Install dependencies if needed
echo Installing Python dependencies...
pip install flask flask-cors chess -q

echo.
echo ================================================
echo  Make sure Stockfish is at:
echo  stockfish\stockfish-windows-x86-64-avx2.exe  (next to app.py)
echo.
echo  OR set environment variable:
echo  set STOCKFISH_PATH=C:\path\to\stockfish.exe
echo ================================================
echo.

:: Open browser after 2 seconds
start "" timeout /t 2 /nobreak >nul && start "" "http://localhost:5000"

:: Start the server
python app.py

pause
