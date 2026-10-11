#!/usr/bin/env bash
# stdio entrypoint for the TaMap MCP server (stdout is the MCP channel: print nothing else).
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT" && exec "$ROOT/.venv/bin/python" -m tamap.mcp_server
