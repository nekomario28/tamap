"""TaMap UI Bridge MCP server (stdio) - mermaid-first output for use inside the Grok Bot chat.

Every map/status tool returns, as its text content, a ```mermaid block (+ one short line or a few
history lines below) that the PM Bot pastes into the chat as-is. Machine-readable fields
(map_id, revision, validation, metrics, ...) are returned alongside as structuredContent.

Run:  /workspace/tamap/scripts/mcp_server.sh
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

from . import core, render, store

mcp = FastMCP(
    "tamap",
    instructions=(
        "TaMap: task dependency map. create_map registers tasks and returns a mermaid graph to paste into the chat "
        "as-is. update_map needs expected_revision (stale updates are rejected). get_map shows the current state, "
        "simulate_delay shows which tasks a delay would reach (read-only), list_maps lists maps. "
        "set_bot_status records pm/map_architect/risk_analyst/quality_reviewer as idle/working/done/error; "
        "get_status returns a mermaid flowchart of bot activity - post it at each hand-off. "
        "Task status: done/in_progress/todo/blocked. Validation (duplicate ids, unknown references, cycles) is "
        "computed by deterministic code; do not override it in prose. Optional analysis = {pm:{summary, actions"
        "(max 3)}, map_architect:{summary}, risk:{summary, items}, quality:{summary, items}, assumptions:[...]}."
    ),
)


def _ok(text: str, **data) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)],
                          structuredContent={**data, "chat_text": text}, isError=False)


def _fail(e: Exception | str) -> CallToolResult:
    data = {"error": str(e)}
    if isinstance(e, store.RevisionConflict):
        data.update(code="revision_conflict", current_revision=e.actual)
    return CallToolResult(content=[TextContent(type="text", text=f"エラー: {e}")],
                          structuredContent=data, isError=True)


def _meta(m: dict) -> dict:
    g = m["graph"]
    return {"map_id": m["map_id"], "title": m["title"], "revision": m["revision"], "updated_at": m["updated_at"],
            "ok": m["validation"]["ok"], "error_count": len(m["validation"]["errors"]),
            "errors": m["validation"]["errors"], "warnings": m["validation"]["warnings"],
            "merge_points": [x["id"] for x in g["merge_points"]], "bottlenecks": g["bottlenecks"],
            "critical_path_candidates": g["critical_path_candidates"]}


@mcp.tool()
def create_map(title: str, tasks: list[dict], analysis: dict | None = None,
               source: str = "TaMap PM (GrokBot Main)") -> CallToolResult:
    """Create a task map. Text result = mermaid graph (paste as-is) + one revision line; structured data has map_id/revision.

    tasks: [{"id": "T1", "title": "要件整理", "status": "done|in_progress|todo|blocked", "depends_on": ["..."]}]
    Validation errors do not block saving; they are shown in the output so they can be fixed with update_map.
    """
    try:
        m = store.create_map(title, tasks, analysis, source)
        return _ok(render.render_map(m), **_meta(m))
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@mcp.tool()
def update_map(map_id: str, expected_revision: int, tasks: list[dict] | None = None,
               analysis: dict | None = None, source: str = "TaMap PM (GrokBot Main)",
               title: str | None = None) -> CallToolResult:
    """Update a map (tasks replaces the whole list; analysis replaces the whole analysis).

    Rejected with revision_conflict if expected_revision != current revision: call get_map and retry.
    """
    try:
        m = store.update_map(map_id, expected_revision, tasks, analysis, source, title)
        return _ok(render.render_map(m), **_meta(m))
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@mcp.tool()
def get_map(map_id: str) -> CallToolResult:
    """Show the current map as a mermaid graph (+ revision line). Structured data includes tasks and analysis."""
    try:
        m = store.read_map(map_id)
        return _ok(render.render_map(m), **_meta(m), tasks=m["tasks"], analysis=m.get("analysis"))
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@mcp.tool()
def simulate_delay(map_id: str, task_id: str) -> CallToolResult:
    """What-if (read-only): which tasks are reachable downstream if task_id is delayed.

    Returns the mermaid graph with the delayed task outlined and impacted tasks/edges in yellow.
    """
    try:
        m = store.read_map(map_id)
        w = core.simulate_delay(m["tasks"], task_id)
        return _ok(render.render_map(m, whatif=w), **_meta(m), task_id=task_id, impacted_ids=w["impacted_ids"],
                   impacted=w["impacted"], summary=w["summary"])
    except KeyError:
        return _fail(f"タスク {task_id} は map {map_id} に存在しません。")
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@mcp.tool()
def list_maps() -> CallToolResult:
    """List saved maps (map_id, title, revision, updated_at), newest first."""
    try:
        maps = store.list_maps()
        text = "\n".join(f"- `{x['map_id']}` {x['title']}（revision {x['revision']}、更新 {render.hms(x['updated_at'])} JST）"
                         for x in maps) or "保存されたマップはありません。"
        return _ok(text, maps=maps)
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@mcp.tool()
def set_bot_status(map_id: str, bot: str, status: str, note: str | None = None) -> CallToolResult:
    """Record a bot's state on a map and return the bot-activity flowchart (mermaid) to post in the chat.

    bot: pm | map_architect | risk_analyst | quality_reviewer
    status: idle | working | done | error     note: short free text (optional)
    Does not change the map revision.
    """
    try:
        m = store.set_bot_status(map_id, bot, status, note)
        return _ok(render.render_status(m), map_id=map_id, bots=m["bots"], bot_history=m["bot_history"][-5:])
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@mcp.tool()
def get_status(map_id: str) -> CallToolResult:
    """Return the bot-activity flowchart (User → PM → Map Architect → Risk Analyst → Quality Reviewer → PM)."""
    try:
        m = store.read_map(map_id)
        return _ok(render.render_status(m), map_id=map_id, bots=m.get("bots") or {},
                   bot_history=(m.get("bot_history") or [])[-5:])
    except Exception as e:  # noqa: BLE001
        return _fail(e)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
