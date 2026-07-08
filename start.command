#!/bin/bash
# Starts the CMC-ONCO Tracker server and opens it in the default browser (macOS/Linux).
set -e

cd "$(dirname "$0")/backend"

if [ ! -d ".venv" ]; then
    echo "Creating virtual environment..."
    python3 -m venv .venv
fi

source .venv/bin/activate

echo "Installing/checking dependencies..."
pip install -q -r requirements.txt

echo "Starting server..."
uvicorn backend:app --host 127.0.0.1 --port 8000 &
SERVER_PID=$!

sleep 3

if command -v open >/dev/null 2>&1; then
    open http://127.0.0.1:8000/
elif command -v xdg-open >/dev/null 2>&1; then
    xdg-open http://127.0.0.1:8000/
fi

echo "Tracker is running (PID $SERVER_PID). Press Ctrl+C to stop it."
wait $SERVER_PID
