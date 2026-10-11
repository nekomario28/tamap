#!/usr/bin/env bash
# Shell fallback for bots that cannot use the MCP server: calls the same tool functions.
#   scripts/tamap_cli.sh <tool> '<json args>'     (or pipe the JSON on stdin)
#   e.g. scripts/tamap_cli.sh simulate_delay '{"map_id":"JbeSRnxW","task_id":"T4"}'
# stdout = the chat text (paste as-is); stderr = structuredContent JSON; exit 1 on tool error.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" && exec "$ROOT/.venv/bin/python" -c '
import json, sys
from tamap import mcp_server as s
name = sys.argv[1]
raw = sys.argv[2] if len(sys.argv) > 2 else sys.stdin.read()
tools = {"create_map", "update_map", "get_map", "simulate_delay", "list_maps", "set_bot_status", "get_status",
         "render_flow_gif"}
if name not in tools:
    sys.exit(f"unknown tool: {name} (one of {sorted(tools)})")
r = getattr(s, name)(**json.loads(raw or "{}"))
print(r.content[0].text)
print(json.dumps(r.structuredContent, ensure_ascii=False), file=sys.stderr)
sys.exit(1 if r.isError else 0)
' "$@"
