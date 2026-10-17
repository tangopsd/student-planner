#!/usr/bin/env bash
# Start the Desk API and the Next.js app together.
set -euo pipefail
root="$(cd "$(dirname "$0")/.." && pwd)"
cd "$root"

if [[ ! -x backend/.venv/bin/uvicorn ]]; then
  echo "Create the backend virtualenv first. See the README." >&2
  exit 1
fi

backend/.venv/bin/uvicorn main:app --app-dir backend --host 0.0.0.0 --port 8741 &
backend_pid=$!
trap 'kill "$backend_pid"' EXIT

npm run dev --prefix frontend
