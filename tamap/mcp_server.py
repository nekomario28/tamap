"""TaMap MCP server (stdio) - mermaid-first output for use inside the Grok Bot chat.

Every map/status tool returns, as its text content, a ```mermaid block (+ one short line or a few
history lines below) that the PM Bot pastes into the chat as-is. Machine-readable fields
(map_id, revision, validation, metrics, ...) are returned alongside as structuredContent.

Run:  /workspace/tamap/scripts/mcp_server.sh
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent

import urllib.request

from . import animate, core, handoff, live, persona, render, store

mcp = FastMCP(
    "tamap",
    instructions=(
        "TaMap: task dependency map. create_map registers tasks and returns a mermaid graph to paste into the chat "
        "as-is. update_map needs expected_revision (stale updates are rejected, even for an identical payload). "
        "If tasks, analysis and title are the same after normalization, revision stays put "
        "(unchanged: true, chat line 変更なし（revision N のまま）). get_map shows the current state, "
        "simulate_delay shows which tasks a delay would reach (read-only), list_maps lists maps. "
        "set_bot_status records pm/map_architect/risk_analyst/quality_reviewer as idle/working/done/error "
        "(a specialist going working puts the PM back to idle automatically); record it at each hand-off but do "
        "not post the flowchart except on errors or when the user asks (get_status). say is the speech bubble; "
        "if the tool schema has no say argument, embed it in note as '事実 ｜ say:一言' or {\"note\",\"say\"}. "
        "render_flow_gif replays the last cycle as out/<map_id>_flow.gif to attach to the result message; the bots "
        "appear as pixel characters. render_team_card makes out/tamap_team.gif for the greeting. "
        "parse_handoff(text, bot) reads each specialist reply (prose, ```json fences, trailing commas, smart quotes) "
        "and returns the object as structuredContent.data; pass the raw message, do not parse it yourself. "
        "get_live_url gives an optional read-only live page (scripts/live_view.sh) where the bots move in real time. "
        "Task status: done/in_progress/todo/blocked. Validation (duplicate ids, unknown references, cycles) is "
        "computed by deterministic code; do not override it in prose. Optional analysis = {pm:{summary, actions"
        "(max 3)}, map_architect:{summary}, risk:{summary, items}, quality:{summary, items:[{before, text, "
        "reason}]}, assumptions:[...]}."
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
        return _ok(render.render_map(m), **_meta(m), live_url=live.live_url(m["map_id"]))
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@mcp.tool()
def update_map(map_id: str, expected_revision: int, tasks: list[dict] | None = None,
               analysis: dict | None = None, source: str = "TaMap PM (GrokBot Main)",
               title: str | None = None) -> CallToolResult:
    """Update a map (tasks replaces the whole list; analysis replaces the whole analysis).

    Text result = one diff line (変更点 ／ ボトルネック ／ 影響先) + mermaid graph + revision line; the same
    diff is in structuredContent.diff. If tasks, analysis and title are identical after normalization, revision
    is left unchanged: the text starts with 「変更なし（revision N のまま）」 and structuredContent.unchanged is true.
    Rejected with revision_conflict if expected_revision != current revision, even when the payload is a no-op:
    call get_map and retry. Do not tell the user the revision increased unless unchanged is false.
    """
    try:
        m = store.update_map(map_id, expected_revision, tasks, analysis, source, title)
        if m.get("unchanged"):
            note = store.unchanged_message(m["revision"])
            return _ok(f"{note}\n\n" + render.render_map(m), **_meta(m), unchanged=True, note=note, diff=None)
        diff = m.get("last_diff")
        return _ok(render.render_map(m, diff=diff), **_meta(m), diff=diff, unchanged=False)
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
def set_bot_status(map_id: str, bot: str, status: str, note: str | None = None,
                   say: str | None = None) -> CallToolResult:
    """Record a bot's state on a map and return the bot-activity flowchart (mermaid).

    bot: pm | map_architect | risk_analyst | quality_reviewer
    status: idle | working | done | error     note: short factual text (optional)
    say: optional in-character one-liner (<=30 chars) for the flow GIF speech bubble.
    If this schema has no say parameter (a host cached the tool list from before say existed), put it in note:
    "受付 ｜ say:まかせてください！" or {"note":"受付","say":"まかせてください！"}. An explicit say wins.
    When a non-pm bot becomes working, pm is set to idle (note「<Bot>の結果待ち」) automatically.
    Does not change the map revision. Post the flowchart only on errors (the result uses the flow GIF).
    """
    try:
        m = store.set_bot_status(map_id, bot, status, note, say)
        return _ok(render.render_status(m), map_id=map_id, bots=m["bots"], bot_history=m["bot_history"][-5:])
    except Exception as e:  # noqa: BLE001
        return _fail(e)


def _handoff_bot(bot: str | None, role: str | None) -> str | None:
    """`bot` and `role` are the same argument. Either name may be used; both must agree if set."""
    b = str(bot).strip() if bot is not None and str(bot).strip() else ""
    r = str(role).strip() if role is not None and str(role).strip() else ""
    if b and r and handoff.canon_role(b) != handoff.canon_role(r):
        raise handoff.HandoffError(
            f"bot と role が違います（{b} / {r}）。どちらか一方を指定してください。",
            hint="bot（role でも同じ）は map_architect / risk_analyst / quality_reviewer です。")
    return handoff.canon_role(b or r or None)


@mcp.tool()
def parse_handoff(text: str, bot: str | None = None, role: str | None = None) -> CallToolResult:
    """Extract one JSON object from a specialist bot's plain-text reply. Call this on every reply; do not parse it yourself.

    Tolerates surrounding prose, a ```json fence, trailing commas, and smart quotes (“ ”).
    bot: map_architect | risk_analyst | quality_reviewer (optional; `role` is the same argument).
    When set, checks the fields that bot should return and explains what is missing.
    Text result is one short line (or エラー + ヒント). The object is structuredContent.data.
    Do not paste this line into the user-facing result — use data.
    """
    try:
        parsed = handoff.parse_reply(text, _handoff_bot(bot, role))
    except handoff.HandoffError as e:
        hint = f"\nヒント: {e.hint}" if e.hint else ""
        return CallToolResult(
            content=[TextContent(type="text", text=f"エラー: {e}{hint}")],
            structuredContent={"ok": False, "error": str(e), "hint": e.hint},
            isError=True)
    except Exception as e:  # noqa: BLE001
        return _fail(e)
    return _ok(handoff.summary_line(parsed), ok=True, role=parsed["role"], data=parsed["data"],
               say=parsed["data"].get("say"), warnings=parsed["warnings"])


@mcp.tool()
def get_status(map_id: str) -> CallToolResult:
    """Return the bot-activity flowchart (User → PM → Map Architect → Risk Analyst → Quality Reviewer → PM)."""
    try:
        m = store.read_map(map_id)
        return _ok(render.render_status(m), map_id=map_id, bots=m.get("bots") or {},
                   bot_history=(m.get("bot_history") or [])[-5:])
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@mcp.tool()
def render_flow_gif(map_id: str) -> CallToolResult:
    """Render the last bot cycle (bot_history) as an animated GIF at out/<map_id>_flow.gif; attach it in the chat.

    Text result = one line with the file path. Does not change the map revision.
    """
    try:
        m = store.read_map(map_id)
        r = animate.render_flow_gif(m)
        text = (f"▶ 流れのGIF: `{r['path']}`（約{round(r['duration_ms'] / 1000)}秒・Bot履歴{r['events']}件）")
        if r["font_fallback"]:
            text += " ※日本語フォントが見つからず、文字が化けている可能性があります（TAMAP_FONT で指定可）"
        return _ok(text, map_id=map_id, revision=m["revision"], gif_path=r["path"], frames=r["frames"],
                   duration_ms=r["duration_ms"], events=r["events"], font=r["font"])
    except Exception as e:  # noqa: BLE001
        return _fail(e)


def _live_running() -> bool:
    try:
        with urllib.request.urlopen(live.base_url() + "/healthz", timeout=0.5) as r:
            return r.status == 200
    except OSError:
        return False


@mcp.tool()
def get_live_url(map_id: str) -> CallToolResult:
    """URL of the read-only live page where the 4 pixel bots move with this map's bot_history in real time.

    Served by scripts/live_view.sh on the box (default http://127.0.0.1:8765, only reachable from the box
    unless it is exposed separately). Text result = one line; structured data has live_url and running.
    """
    try:
        m = store.read_map(map_id)
        url = live.live_url(map_id)
        running = _live_running()
        text = f"▶ ライブページ（閲覧専用）: {url}" + ("" if running else "（ライブページのサーバーが起動していません: scripts/live_view.sh）")
        return _ok(text, map_id=map_id, revision=m["revision"], live_url=url, running=running)
    except Exception as e:  # noqa: BLE001
        return _fail(e)


@mcp.tool()
def render_team_card() -> CallToolResult:
    """Render the team introduction GIF (out/tamap_team.gif): the 4 bots as pixel characters with role and
    catchphrase. Attach it to the PM's first greeting. Text result = one line with the file path."""
    try:
        r = animate.render_team_card()
        text = f"▶ チーム紹介のGIF: `{r['path']}`"
        if r["font_fallback"]:
            text += " ※日本語フォントが見つからず、文字が化けている可能性があります（TAMAP_FONT で指定可）"
        personas = {k: {f: p[f] for f in ("name", "emoji", "role", "motif", "trait", "lines")}
                    for k, p in persona.PERSONAS.items()}
        return _ok(text, gif_path=r["path"], frames=r["frames"], font=r["font"], personas=personas)
    except Exception as e:  # noqa: BLE001
        return _fail(e)


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
