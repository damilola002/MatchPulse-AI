
#!/bin/zsh
set -e

cd "$(dirname "$0")"

echo "Starting MatchPulse AI..."

# Start PostgreSQL
docker compose up -d

# Load local environment
set -a
source .env
set +a

export MATCHPULSE_DEMO_MODE=true
export MATCHPULSE_NARRATIVE_PROVIDER=fake
export PYTHONPATH=src

# Choose an existing environment with the backend dependencies installed.
PYTHON=""
for candidate in /private/tmp/matchpulse-demo-venv/bin/python .venv-phase2/bin/python .venv/bin/python; do
  environment_root="${candidate%/bin/python}"
  site_packages="$environment_root/lib/python3.12/site-packages"
  if [[ -x "$candidate" && -d "$site_packages/fastapi" && -d "$site_packages/sqlalchemy" && -d "$site_packages/uvicorn" ]]; then
    PYTHON="$candidate"
    break
  fi
done
if [[ -z "$PYTHON" ]]; then
  echo "No usable project Python environment found. Create .venv and install the project dependencies from pyproject.toml."
  exit 1
fi

# Vite 8 and the frontend dependencies require the project's Node 22 range.
if [[ "$(node -p 'process.versions.node.split(`.`)[0]' 2>/dev/null)" != "22" ]]; then
  for candidate in /opt/homebrew/opt/node@22/bin /usr/local/opt/node@22/bin /usr/local/bin; do
    if [[ -x "$candidate/node" ]]; then
      export PATH="$candidate:$PATH"
      break
    fi
  done
fi
if [[ "$(node -p 'process.versions.node.split(`.`)[0]' 2>/dev/null)" != "22" ]]; then
  echo "Node.js 22 is required. Install Node 22 or add it to PATH, then retry."
  exit 1
fi
if [[ ! -d frontend/node_modules ]]; then
  echo "Frontend dependencies are missing. Run npm ci in the frontend folder, then retry."
  exit 1
fi

BACKEND_PID=""
FRONTEND_PID=""
STARTED_PIDS=()

cleanup() {
  for pid in "${STARTED_PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
}
trap cleanup EXIT INT TERM

if curl --max-time 2 -fsS http://127.0.0.1:8001/openapi.json >/dev/null; then
  echo "Using the API already running at http://127.0.0.1:8001"
else
  # Start backend and allow the initial Python imports time to finish.
  "$PYTHON" -m matchpulse_sim serve --host 127.0.0.1 --port 8001 &
  BACKEND_PID=$!
  STARTED_PIDS+=("$BACKEND_PID")
  backend_ready=false
  for attempt in {1..180}; do
    if curl --max-time 2 -fsS http://127.0.0.1:8001/openapi.json >/dev/null; then
      backend_ready=true
      break
    fi
    if ! kill -0 "$BACKEND_PID" 2>/dev/null; then
      echo "The API server exited before it became ready. Check the local database configuration and server output."
      exit 1
    fi
    sleep 1
  done
  if [[ "$backend_ready" != true ]]; then
    echo "The API server did not become ready within 180 seconds."
    exit 1
  fi
fi

if curl --max-time 2 -fsS http://127.0.0.1:5174/ >/dev/null; then
  echo "Using the dashboard already running at http://127.0.0.1:5174"
else
  cd frontend
  npm run dev -- --host 127.0.0.1 --port 5174 &
  FRONTEND_PID=$!
  STARTED_PIDS+=("$FRONTEND_PID")
  frontend_ready=false
  for attempt in {1..30}; do
    if curl --max-time 2 -fsS http://127.0.0.1:5174/ >/dev/null; then
      frontend_ready=true
      break
    fi
    if ! kill -0 "$FRONTEND_PID" 2>/dev/null; then
      echo "The dashboard server exited before it became ready. Check the frontend output above."
      exit 1
    fi
    sleep 1
  done
  if [[ "$frontend_ready" != true ]]; then
    echo "The dashboard did not become ready within 30 seconds."
    exit 1
  fi
  cd ..
fi

echo ""
echo "MatchPulse AI dashboard:"
echo "http://127.0.0.1:5174"
echo ""
echo "Press Ctrl+C to stop servers started by this script."

if (( ${#STARTED_PIDS[@]} > 0 )); then
  wait "${STARTED_PIDS[@]}"
else
  echo "Both local servers were already running."
fi
