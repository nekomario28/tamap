"""Render TaMap state as mermaid diagrams to paste into the Grok Bot chat as-is.

- render_map(): task map (graph LR). Notes (merge point / bottleneck / delay impact / validation
  errors) are expressed with node labels, colours and edge styles; one revision line below
  (after update_map, a one-line diff above the block).
- render_status(): bot activity flowchart (User → PM → Map Architect → Risk Analyst → Quality Reviewer → PM)
  plus a few recent status changes below.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from . import core

JST = timezone(timedelta(hours=9))
ERROR_LABELS = {
    "duplicate_id": "重複ID", "unknown_reference": "存在しない参照", "self_dependency": "自己依存",
    "cycle": "循環", "invalid_status": "不正な状態", "missing_title": "タイトルなし",
    "invalid_depends_on": "不正な依存先",
}
STATUS_CLASS = {"done": "done", "in_progress": "prog", "todo": "todo", "blocked": "blocked"}
CLASSDEFS = [
    "  classDef done fill:#22c55e,stroke:#15803d,color:#ffffff",
    "  classDef prog fill:#3b82f6,stroke:#1d4ed8,color:#ffffff",
    "  classDef todo fill:#9ca3af,stroke:#4b5563,color:#111827",
    "  classDef blocked fill:#f97316,stroke:#c2410c,color:#ffffff",
    "  classDef impact fill:#facc15,stroke:#a16207,color:#111827",
    "  classDef err fill:#ef4444,stroke:#991b1b,color:#ffffff",
]


def hms(iso: str | None) -> str:
    if not iso:
        return "-"
    try:
        return datetime.fromisoformat(iso).astimezone(JST).strftime("%H:%M:%S")
    except ValueError:
        return iso


def mm_text(x) -> str:
    """Escape text for a quoted mermaid label (entity codes keep the syntax intact)."""
    s = str(x if x is not None else "")
    for a, b in (("&", "#amp;"), ('"', "#quot;"), ("<", "#lt;"), (">", "#gt;"), ("`", "#96;"),
                 ("\r", " "), ("\n", " ")):
        s = s.replace(a, b)
    return s


def _short(s: str, n: int = 40) -> str:
    s = str(s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def mermaid_map(m: dict, whatif: dict | None = None) -> str:
    v, g = m["validation"], m["graph"]
    tasks_by_id: dict[str, dict] = {}
    dup_count: dict[str, int] = {}
    for t in m["tasks"]:
        tasks_by_id.setdefault(t["id"], t)  # one node per id; duplicates flagged in the label
        dup_count[t["id"]] = dup_count.get(t["id"], 0) + 1
    metrics = g.get("metrics", {})
    top = g["bottlenecks"][0]["score"] if g.get("bottlenecks") else None
    bottlenecks = {b["id"] for b in g.get("bottlenecks", []) if b["score"] == top}
    impacted = {x["id"]: x for x in (whatif or {}).get("impacted", []) + (whatif or {}).get("impacted_done", [])}
    origin = (whatif or {}).get("task_id")
    errs: dict[str, list[str]] = {}
    for e in v["errors"]:
        label = ERROR_LABELS.get(e["code"], e["code"])
        if e["code"] == "unknown_reference":
            label = f"存在しない参照: {e['task_ids'][1]}"
            targets = e["task_ids"][:1]
        elif e["code"] == "duplicate_id":
            label = f"重複ID ×{dup_count.get(e['task_ids'][0], 2)}"
            targets = e["task_ids"]
        else:
            targets = e["task_ids"]
        for tid in targets:
            if label not in errs.setdefault(tid, []):
                errs[tid].append(label)
    warns: dict[str, list[str]] = {}
    for w in v["warnings"]:
        tid, deps = w["task_ids"][0], w["task_ids"][1:]
        warns.setdefault(tid, []).append(("完了だが依存先未完了: " if w["code"] == "done_before_dependency"
                                          else "依存先未完了: ") + "・".join(deps))

    node: dict[str, str] = {}

    def nid(tid: str) -> str:
        if tid not in node:
            node[tid] = f"n{len(node)}"
        return node[tid]

    lines = ["```mermaid", "graph LR"]
    for tid, t in tasks_by_id.items():
        parts = [f"{mm_text(tid)} {mm_text(_short(t['title']))}", core.STATUS_LABELS_JA[t["status"]]]
        tags = []
        if metrics.get(tid, {}).get("is_merge_point"):
            tags.append("◆合流点")
        if tid in bottlenecks:
            tags.append("▲ボトルネック")
        if tid == origin:
            tags.append("⏱遅延元")
        if tid in impacted:
            tags.append(f"遅延影響 {impacted[tid]['distance']}段先")
        if tags:
            parts.append(" ".join(tags))
        for e in errs.get(tid, []):
            parts.append(f"✖{mm_text(e)}")
        for w in warns.get(tid, []):
            parts.append(f"△{mm_text(w)}")
        lines.append(f'  {nid(tid)}["{"<br>".join(parts)}"]')
    unknown = []
    for t in m["tasks"]:
        for d in t["depends_on"]:
            if d not in tasks_by_id and d not in unknown:
                unknown.append(d)
    for d in unknown:
        lines.append(f'  {nid(d)}["{mm_text(d)}<br>✖存在しないタスク"]')

    cycle_edges = set()
    for c in v.get("cycles") or []:
        for i, a in enumerate(c):
            cycle_edges.add((a, c[(i + 1) % len(c)]))
    crit = g.get("critical_path_candidates") or []
    crit_path = crit[0]["path"] if crit else []
    crit_edges = {(crit_path[i], crit_path[i + 1]) for i in range(len(crit_path) - 1)}
    edges, red, yellow = [], [], []
    seen = set()
    for t in m["tasks"]:
        for d in t["depends_on"]:
            key = (d, t["id"])
            if d == t["id"] or key in seen:
                continue
            seen.add(key)
            a, b = nid(d), nid(t["id"])
            if d not in tasks_by_id:
                edges.append(f"  {a} -. 未定義 .-> {b}")
                red.append(len(edges) - 1)
            elif key in cycle_edges:
                edges.append(f"  {a} -. 循環 .-> {b}")
                red.append(len(edges) - 1)
            elif key in crit_edges:
                edges.append(f"  {a} ==> {b}")
            else:
                edges.append(f"  {a} --> {b}")
            if whatif and (d == origin or d in impacted) and t["id"] in impacted and len(edges) - 1 not in red:
                yellow.append(len(edges) - 1)
    lines += edges
    lines += CLASSDEFS
    err_ids = set(v.get("error_task_ids") or [])
    groups: dict[str, list[str]] = {}
    for tid in node:
        if tid in unknown or tid in err_ids:
            cls = "err"
        elif tid in impacted:
            cls = "impact"
        else:
            cls = STATUS_CLASS[tasks_by_id[tid]["status"]]
        groups.setdefault(cls, []).append(node[tid])
    for cls, ns in groups.items():
        lines.append(f"  class {','.join(ns)} {cls}")
    for tid in bottlenecks:
        if tid in node and tid not in err_ids:
            lines.append(f"  style {node[tid]} stroke:#7c2d12,stroke-width:4px,stroke-dasharray:6 3")
    if origin in node:
        lines.append(f"  style {node[origin]} stroke:#ca8a04,stroke-width:5px")
    if red:
        lines.append(f"  linkStyle {','.join(map(str, red))} stroke:#ef4444,stroke-width:3px,stroke-dasharray:5 4")
    if yellow:
        lines.append(f"  linkStyle {','.join(map(str, yellow))} stroke:#ca8a04,stroke-width:4px")
    lines.append("```")
    return "\n".join(lines)


def footer(m: dict, whatif: dict | None = None) -> str:
    v = m["validation"]
    check = "検証OK" if v["ok"] else f"検証エラー{len(v['errors'])}件"
    extra = f" ・ what-if: {whatif['task_id']}（保存なし）" if whatif else ""
    return (f"revision {m['revision']} ・ map_id `{m['map_id']}` ・ 更新 {hms(m['updated_at'])} JST ・ "
            f"{check}{extra}")


def render_map(m: dict, whatif: dict | None = None, diff: dict | None = None) -> str:
    """Mermaid block + revision line. With diff (update_map), the one-line diff goes on top (UX_DESIGN 4.5)."""
    head = f"{diff['text']}\n\n" if diff else ""
    return head + mermaid_map(m, whatif) + "\n" + footer(m, whatif)


# ---------- bot status ----------

BOTS = [("pm", "TaMap PM"), ("map_architect", "Map Architect"),
        ("risk_analyst", "Risk Analyst"), ("quality_reviewer", "Quality Reviewer")]
BOT_LABEL = dict(BOTS)
BOT_STATUS_JA = {"idle": "待機", "working": "作業中", "done": "完了", "error": "エラー"}
BOT_NODE = {"pm": "PM", "map_architect": "MA", "risk_analyst": "RA", "quality_reviewer": "QR"}


def render_status(m: dict, history_limit: int = 5) -> str:
    bots = m.get("bots") or {}
    lines = ["```mermaid", "flowchart LR", '  U(["ユーザー"])']
    for key, label in BOTS:
        b = bots.get(key) or {"status": "idle"}
        parts = [label, BOT_STATUS_JA[b["status"]]]
        if b.get("note"):
            parts.append(mm_text(_short(b["note"], 36)))
        if b.get("updated_at"):
            parts.append(f"{hms(b['updated_at'])} JST")
        lines.append(f'  {BOT_NODE[key]}["{"<br>".join(parts)}"]')
    edges = [("U", "PM", "依頼"), ("PM", "MA", "分解"), ("MA", "RA", "構造"), ("RA", "QR", "リスク"), ("QR", "PM", "検証結果")]
    for a, b, lab in edges:
        lines.append(f"  {a} -- {lab} --> {b}")
    lines += [
        "  classDef idle fill:#9ca3af,stroke:#4b5563,color:#111827",
        "  classDef working fill:#3b82f6,stroke:#1d4ed8,color:#ffffff",
        "  classDef done fill:#22c55e,stroke:#15803d,color:#ffffff",
        "  classDef error fill:#ef4444,stroke:#991b1b,color:#ffffff",
        "  classDef user fill:#ffffff,stroke:#4b5563,color:#111827",
        "  class U user",
    ]
    groups: dict[str, list[str]] = {}
    for key, _ in BOTS:
        groups.setdefault((bots.get(key) or {}).get("status", "idle"), []).append(BOT_NODE[key])
    for st, ns in groups.items():
        lines.append(f"  class {','.join(ns)} {st}")
    # Emphasise the edge(s) leading into whichever bot is working now.
    others_active = any((bots.get(k) or {}).get("status", "idle") != "idle" for k in BOT_NODE if k != "pm")
    thick = []
    for key, node in BOT_NODE.items():
        if (bots.get(key) or {}).get("status") != "working":
            continue
        if key == "pm":
            thick.append(4 if others_active else 0)
        else:
            thick.append({"MA": 1, "RA": 2, "QR": 3}[node])
    if thick:
        lines.append(f"  linkStyle {','.join(map(str, sorted(set(thick))))} stroke:#2563eb,stroke-width:5px")
    lines.append("```")
    hist = (m.get("bot_history") or [])[-history_limit:]
    tail = [f"map `{m['map_id']}` のBot稼働状況 ・ 直近の変更（新しい順）:" if hist else f"map `{m['map_id']}` のBot稼働状況 ・ 変更履歴なし"]
    for h in reversed(hist):
        note = f"（{_short(h['note'], 40)}）" if h.get("note") else ""
        tail.append(f"- {hms(h['at'])} {BOT_LABEL[h['bot']]}: {BOT_STATUS_JA[h['status']]}{note}")
    return "\n".join(lines) + "\n" + "\n".join(tail)
