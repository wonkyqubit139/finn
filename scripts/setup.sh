#!/bin/bash
# One-time setup after installing Python (python.org) and Node.js (nodejs.org).
# Safe to re-run: it only installs what's missing.
set -euo pipefail
cd "$(dirname "$0")/.."

PY=$(command -v python3.13 || command -v python3.12 || true)
if [ -z "$PY" ]; then
  echo "Python 3.13 not found. Install it from https://www.python.org/downloads/macos/ first."; exit 1
fi
if ! command -v npm >/dev/null; then
  echo "Node.js not found. Install the LTS .pkg from https://nodejs.org first."; exit 1
fi
echo "Using $($PY --version) and Node $(node --version)"

echo "[1/5] Creating Python virtual environment in .venv"
[ -d .venv ] || "$PY" -m venv .venv
source .venv/bin/activate

echo "[2/5] Installing Python packages"
pip install --quiet --upgrade pip
pip install --quiet -r backend/requirements.txt

echo "[3/5] Installing and building the frontend"
(cd frontend && npm ci --no-audit --no-fund && npm run build)

echo "[4/5] Creating .env (settings file) if missing"
[ -f .env ] || cp .env.example .env

echo "[5/5] Running the test suite"
(cd backend && python -m pytest -q)

echo
echo "Setup complete. Fetch data with:  bash scripts/refresh.sh"
echo "Then start FINN with:             bash scripts/start.sh"
