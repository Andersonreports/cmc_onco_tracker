@echo off
REM Starts the CMC-ONCO Tracker server and opens it in the default browser.
setlocal
if not defined PORT set "PORT=8010"

cd /d "%~dp0backend"

if not exist ".venv" (
    echo Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

echo Installing/checking dependencies...
pip install -q -r requirements.txt

echo Starting server...
start "CMC-ONCO Tracker Server" /min cmd /c "uvicorn backend:app --host 127.0.0.1 --port %PORT%"

echo Waiting for server to start...
timeout /t 3 /nobreak >nul

start "" http://127.0.0.1:%PORT%/

echo Tracker is running. Close the "CMC-ONCO Tracker Server" window to stop it.
pause

endlocal
