#!/usr/bin/env bash
# Read-only live page for TaMap maps (keep it running on the box, e.g. in tmux).
#   scripts/live_view.sh [--host 127.0.0.1] [--port 8765]   ->  http://127.0.0.1:8765/live/<map_id>
# Env: TAMAP_DATA_DIR (maps to watch), TAMAP_LIVE_HOST / TAMAP_LIVE_PORT, TAMAP_LIVE_TOKEN (require ?token=).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" && exec "$ROOT/.venv/bin/python" -m tamap.live "$@"
