#!/bin/bash
# Start FINN. Stop it with Ctrl+C.
set -euo pipefail
cd "$(dirname "$0")/../backend"
source ../.venv/bin/activate
IP=$(ipconfig getifaddr en0 2>/dev/null || true)
echo "FINN is starting at http://localhost:8000"
[ -n "$IP" ] && echo "On your phone (same Wi-Fi): http://$IP:8000"
exec uvicorn finn.api:app --host 0.0.0.0 --port 8000
