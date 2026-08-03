#!/usr/bin/env bash
# Starts the Vectis backend (FastAPI/uvicorn) and frontend (Vite) dev servers.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cleanup() {
  echo "Stopping servers..."
  kill "${BACKEND_PID:-}" "${FRONTEND_PID:-}" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Starting backend (FastAPI) on http://127.0.0.1:8000 ..."
(cd "$ROOT_DIR/backend" && .venv/bin/uvicorn main:app --reload --port 8000) &
BACKEND_PID=$!

echo "Starting frontend (Vite) on http://127.0.0.1:5173 ..."
(cd "$ROOT_DIR/frontend" && npm run dev) &
FRONTEND_PID=$!

wait "$BACKEND_PID" "$FRONTEND_PID"
