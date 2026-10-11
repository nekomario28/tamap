"""End-to-end test: spawn the stdio MCP server with the official mcp client and call every tool.

Writes the chat text (mermaid) each tool returned to docs/sample_output.md.
Usage: uv run python tests/e2e_mcp.py   (exits non-zero on failure)
"""
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from mcp import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

ROOT = Path(__file__).resolve().parent.parent
# Use a throwaway data dir unless TAMAP_E2E_KEEP=1 (then the real data/maps is used).
DATA_DIR = None if os.environ.get("TAMAP_E2E_KEEP") else tempfile.mkdtemp(prefix="tamap-e2e-")
ENV = {**os.environ, **({"TAMAP_DATA_DIR": DATA_DIR, "TAMAP_OUT_DIR": os.path.join(DATA_DIR, "out")}
                         if DATA_DIR else {})}
SERVER = StdioServerParameters(command=str(ROOT / "scripts" / "mcp_server.sh"), args=[], env=ENV)

failed = False
log: list[tuple[str, str]] = []


def check(cond, msg):
    global failed
    print(("PASS " if cond else "FAIL ") + msg)
    failed |= not cond


async def call(s, name, args, label=None):
    res = await s.call_tool(name, args)
    md = res.content[0].text
    data = res.structuredContent or {}
    if label:
        log.append((label, md))
    return res, md, data


async def main():
    sample = json.loads((ROOT / "samples" / "readme_example.json").read_text())
    broken = json.loads((ROOT / "samples" / "broken_example.json").read_text())
    async with stdio_client(SERVER) as (r, w):
        async with ClientSession(r, w) as s:
            await s.initialize()
            tools = sorted(t.name for t in (await s.list_tools()).tools)
            check(tools == ["create_map", "get_map", "get_status", "list_maps", "render_flow_gif", "set_bot_status",
                            "simulate_delay", "update_map"], f"tools: {tools}")

            analysis = {
                "pm": {"summary": "T6がT4系列とT5系列の合流点。T3→T4→T6→T7が最長の未完了チェーン。",
                       "actions": [{"text": "T3（DB設計）を完了させる", "reason": "T4・T6・T7がT3に依存"},
                                   {"text": "T4（API実装）の着手条件を確認する"},
                                   {"text": "T6（統合テスト）の準備を先行する", "reason": "T4とT5の合流点"}]},
                "assumptions": ["所要時間は未入力のため遅延日数は算出しない"],
            }
            res, md, d = await call(s, "create_map", {"title": sample["title"], "tasks": sample["tasks"],
                                                      "analysis": analysis, "source": "e2e test"},
                                    "create_map（README例）")
            mid = d["map_id"]
            check(not res.isError and d["revision"] == 1 and d["ok"], "create_map: rev1, 検証OK")
            check(md.startswith("```mermaid\ngraph LR") and md.count("```") == 2, "chat text is a single mermaid block")
            tail = md.rsplit("```", 1)[1].strip()
            check(tail.startswith("revision 1 ・ map_id") and "\n" not in tail, f"one revision line below: {tail}")
            check("|" not in md, "no markdown table")
            check('T6 統合テスト<br>未着手<br>◆合流点"]' in md, "T6 labelled 合流点")
            check('T3 DB設計<br>進行中<br>▲ボトルネック"]' in md, "T3 labelled ボトルネック")
            check("==>" in md, "critical path edges drawn thick")
            check(d["merge_points"] == ["T6"], "structured: merge_points T6")

            tasks2 = [dict(t, status="blocked") if t["id"] == "T4" else dict(t) for t in sample["tasks"]]
            res, md, d = await call(s, "update_map", {"map_id": mid, "expected_revision": 1, "tasks": tasks2,
                                                      "source": "e2e test: T4 blocked"}, "update_map（T4をブロック中に）")
            check(not res.isError and d["revision"] == 2, "update_map: rev2")
            check('T4 API実装<br>ブロック中<br>▲ボトルネック"]' in md and "blocked" in md, "T4 blocked -> ボトルネック, orange")
            diff_line = "変更点：T4 未着手→ブロック中 ／ ボトルネック：T3→T4 ／ 影響先：T4・T6・T7→T6・T7"
            check(md.startswith(diff_line + "\n\n```mermaid\ngraph LR"), f"diff line above the map: {md.splitlines()[0]}")
            check(md.rsplit("```", 1)[1].strip().startswith("revision 2 ・"), "revision line still last")
            check((d.get("diff") or {}).get("text") == diff_line and d["diff"]["bottleneck"]["changed"]
                  and d["diff"]["from_revision"] == 1 and d["diff"]["to_revision"] == 2, "structured: diff")

            res, md, d = await call(s, "update_map", {"map_id": mid, "expected_revision": 1, "tasks": sample["tasks"],
                                                      "source": "stale writer"}, "update_map（古いrevisionで更新 → 拒否）")
            check(res.isError and d.get("code") == "revision_conflict" and d.get("current_revision") == 2, "stale update rejected")

            res, md, d = await call(s, "get_map", {"map_id": mid}, "get_map")
            check(not res.isError and d["revision"] == 2 and "revision 2 ・" in md, "get_map: rev2")
            check(md.startswith("```mermaid") and "diff" not in d, "get_map has no diff line")

            res, md, d = await call(s, "simulate_delay", {"map_id": mid, "task_id": "T4"}, "simulate_delay（T4）")
            check(d.get("impacted_ids") == ["T6", "T7"], f"T4 delay impacts T6,T7 ({d.get('impacted_ids')})")
            check("遅延影響 1段先" in md and "遅延影響 2段先" in md and "⏱遅延元" in md, "impact labels in nodes")
            check("class n5,n6 impact" in md, "T6,T7 nodes yellow")
            check("what-if: T4" in md, "footer mentions what-if")
            res2, md2, d2 = await call(s, "get_map", {"map_id": mid})
            check(d2["revision"] == 2, "simulate_delay did not change revision")

            # Bot status flow
            res, md, d = await call(s, "set_bot_status", {"map_id": mid, "bot": "pm", "status": "working",
                                                          "note": "依頼を受付"})
            res, md, d = await call(s, "set_bot_status", {"map_id": mid, "bot": "map_architect", "status": "working",
                                                          "note": "T1〜T7を構造化中"}, "set_bot_status（MA作業中 → PMは自動で待機）")
            check(d["bots"]["pm"]["status"] == "idle" and d["bots"]["pm"]["note"] == "Map Architectの結果待ち",
                  "specialist working -> pm idle (結果待ち) automatically")
            check("class PM,RA,QR idle" in md and "class MA working" in md, "only MA lit in flowchart")
            check([(h["bot"], h["status"]) for h in d["bot_history"][-3:]]
                  == [("pm", "working"), ("pm", "idle"), ("map_architect", "working")], "auto pm idle in history")
            steps = [("map_architect", "done", "7タスク・7依存"),
                     ("risk_analyst", "working", "T4遅延の波及を分析中")]
            for i, (bot, st, note) in enumerate(steps):
                label = "set_bot_status（Risk Analyst 作業中）" if i == len(steps) - 1 else None
                res, md, d = await call(s, "set_bot_status", {"map_id": mid, "bot": bot, "status": st,
                                                              **({"note": note} if note else {})}, label)
                check(not res.isError, f"set_bot_status {bot}={st}")
            check(md.startswith("```mermaid\nflowchart LR") and "class RA working" in md, "RA shown working (blue)")
            check("class MA done" in md, "MA shown done (green)")
            check("linkStyle 2 stroke:#2563eb,stroke-width:5px" in md, "edge into RA emphasised")
            check("- " in md.rsplit("```", 1)[1] and "Risk Analyst: 作業中" in md, "history lines below")
            res, md, d = await call(s, "set_bot_status", {"map_id": mid, "bot": "quality_reviewer", "status": "error",
                                                          "note": "T9参照を確認できず"})
            res, md, d = await call(s, "set_bot_status", {"map_id": mid, "bot": "risk_analyst", "status": "done"})
            res, md, d = await call(s, "set_bot_status", {"map_id": mid, "bot": "pm", "status": "working",
                                                          "note": "結果を統合中"}, "set_bot_status（PM統合中・QRエラー）")
            check("class QR error" in md and "linkStyle 4 " in md, "QR error red, edge QR->PM emphasised")
            res, md, d = await call(s, "get_status", {"map_id": mid}, "get_status")
            check(not res.isError and d["bots"]["pm"]["status"] == "working", "get_status")
            res, md, d = await call(s, "set_bot_status", {"map_id": mid, "bot": "designer", "status": "working"})
            check(res.isError, "unknown bot rejected")
            res, md, d = await call(s, "set_bot_status", {"map_id": mid, "bot": "pm", "status": "busy"})
            check(res.isError, "unknown status rejected")
            res, md, d = await call(s, "get_map", {"map_id": mid})
            check(d["revision"] == 2, "bot status does not change map revision")
            res, md, d = await call(s, "set_bot_status", {"map_id": mid, "bot": "pm", "status": "done"})

            # T3 done + QR before/after (UX_DESIGN 4.5 / 4.3)
            tasks3 = [dict(t, status="done") if t["id"] == "T3" else t for t in tasks2]
            qa = {"pm": {"summary": "ボトルネックはT4", "actions": ["T4のブロック理由を確認する"]},
                  "quality": {"summary": "2件修正", "items": [
                      {"before": "T4の遅れの原因はDB設計", "text": "原因はDB設計の可能性あり（推定・未確認）",
                       "reason": "断定しすぎ"},
                      {"before": "モックで並行開発する", "text": "T5→T4の依存がある場合のみモックで進める"}]}}
            res, md, d = await call(s, "update_map", {"map_id": mid, "expected_revision": 2, "tasks": tasks3,
                                                      "analysis": qa, "source": "e2e test: T3 done"},
                                    "update_map（T3を完了に・差分の1行）")
            check(not res.isError and d["revision"] == 3, "update_map: rev3")
            check(md.splitlines()[0] == "変更点：T3 進行中→完了 ／ ボトルネック：変化なし（T4） ／ 影響先：変化なし（T6・T7）",
                  f"T3 done diff line: {md.splitlines()[0]}")
            check(d["diff"]["task_changes"] == [{"id": "T3", "kind": "status", "from": "in_progress", "to": "done",
                                                 "text": "T3 進行中→完了"}], "structured diff task_changes")
            res, md, d = await call(s, "get_map", {"map_id": mid})
            items = d["analysis"]["quality"]["items"]
            check(items[0] == {"text": "原因はDB設計の可能性あり（推定・未確認）", "before": "T4の遅れの原因はDB設計",
                               "reason": "断定しすぎ"} and items[1]["before"] == "モックで並行開発する",
                  "quality items keep before/reason")

            res, md, d = await call(s, "render_flow_gif", {"map_id": mid}, "render_flow_gif")
            gif = Path(d.get("gif_path") or "/nonexistent")
            check(not res.isError and gif.name == f"{mid}_flow.gif" and gif.exists()
                  and gif.read_bytes()[:6] in (b"GIF89a", b"GIF87a"), f"flow GIF written ({gif})")
            check(d.get("frames", 0) > 20 and d.get("events") == 9 and md.startswith("▶ 流れのGIF: "),
                  f"flow GIF frames={d.get('frames')} events={d.get('events')}")
            check(d["revision"] == 3, "render_flow_gif does not change revision")
            res, md, d = await call(s, "render_flow_gif", {"map_id": "nosuchmap"})
            check(res.isError, "render_flow_gif unknown map -> error")

            res, md, d = await call(s, "create_map", {"title": broken["title"], "tasks": broken["tasks"],
                                                      "source": "e2e test (broken sample)"}, "create_map（不整合サンプル）")
            check(not d["ok"] and d["error_count"] == 3, f"broken: 3 errors ({d.get('error_count')})")
            for needle in ("✖重複ID ×2", "✖存在しない参照: T9", "✖循環", '["T9<br>✖存在しないタスク"]',
                           "-. 未定義 .->", "-. 循環 .->", "stroke:#ef4444,stroke-width:3px,stroke-dasharray:5 4",
                           " err\n", "検証エラー3件"):
                check(needle in md, f"broken output contains {needle!r}")

            res, md, d = await call(s, "create_map", {"title": 'Q"uote <b> & |x| [y] `z` end', "tasks": [
                {"id": "A", "title": '"引用" <tag> & |pipe| [角] {波} #h; `bt` -->', "status": "todo", "depends_on": []},
                {"id": "B", "title": "end", "status": "blocked", "depends_on": ["A"]}]}, "create_map（記号入りタイトルのエスケープ確認）")
            check(not res.isError and "#quot;" in md and "#lt;tag#gt;" in md, "special characters escaped")

            res, md, d = await call(s, "create_map", {"title": "x", "tasks": sample["tasks"],
                                                      "analysis": {"pm": {"actions": ["a", "b", "c", "d"]}}})
            check(res.isError and "最大 3 件" in md, "4 actions rejected")
            res, md, d = await call(s, "simulate_delay", {"map_id": mid, "task_id": "T99"})
            check(res.isError, "unknown task in simulate_delay -> error")
            res, md, d = await call(s, "list_maps", {}, "list_maps")
            check(len(d["maps"]) == 3, "list_maps: 3 maps")

    out = ["# TaMap MCP 出力サンプル", "",
           "`tests/e2e_mcp.py` が stdio MCP サーバーを公式 mcp クライアントで実際に呼び、各ツールが返したチャット用テキスト（mermaid）をそのまま貼ったものです（自動生成）。時刻は実行時のもの。",
           ""]
    for label, md in log:
        out += [f"## {label}", "", md, "", "---", ""]
    (ROOT / "docs" / "sample_output.md").write_text("\n".join(out), encoding="utf-8")
    print("wrote docs/sample_output.md")
    sys.exit(1 if failed else 0)


asyncio.run(main())
