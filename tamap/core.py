"""TaMap Core: deterministic task-graph validation and analysis.

No LLM is involved here. Everything is plain graph computation so that
"決定的な検証はコード側" (README) holds: LLM explanations never override these results.

Task shape: {"id": str, "title": str, "status": "done|in_progress|todo|blocked",
             "depends_on": [str, ...], (optional) "note": str, "owner": str}
Edge semantics: if B.depends_on contains A, then A -> B (A must finish before B).
"""
from __future__ import annotations

from collections import deque
from typing import Any

STATUSES = ("done", "in_progress", "todo", "blocked")
STATUS_LABELS_JA = {"done": "完了", "in_progress": "進行中", "todo": "未着手", "blocked": "ブロック中"}
# A few lenient aliases so that Bots can pass Japanese/variant labels.
_STATUS_ALIASES = {
    "完了": "done", "done": "done", "complete": "done", "completed": "done",
    "進行中": "in_progress", "in_progress": "in_progress", "in-progress": "in_progress",
    "inprogress": "in_progress", "doing": "in_progress", "wip": "in_progress",
    "未着手": "todo", "todo": "todo", "to_do": "todo", "not_started": "todo", "pending": "todo",
    "ブロック中": "blocked", "blocked": "blocked", "停滞": "blocked",
}


def normalize_tasks(raw_tasks: Any) -> tuple[list[dict], list[dict]]:
    """Coerce input into the canonical task list. Returns (tasks, errors).

    Invalid entries are kept as far as possible (so the UI can show them in red)
    and reported as errors rather than silently dropped.
    """
    errors: list[dict] = []
    if not isinstance(raw_tasks, list):
        return [], [_err("invalid_tasks", "tasks は配列である必要があります。", [])]
    tasks: list[dict] = []
    for i, raw in enumerate(raw_tasks):
        if not isinstance(raw, dict):
            errors.append(_err("invalid_task", f"{i} 番目のタスクがオブジェクトではありません。", []))
            continue
        tid = raw.get("id")
        tid = str(tid).strip() if tid is not None else ""
        if not tid:
            errors.append(_err("missing_id", f"{i} 番目のタスクに id がありません。", []))
            continue
        title = str(raw.get("title") or "").strip()
        if not title:
            errors.append(_err("missing_title", f"{tid} に title がありません。", [tid]))
        status_raw = str(raw.get("status") or "").strip()
        status = _STATUS_ALIASES.get(status_raw.lower(), _STATUS_ALIASES.get(status_raw))
        if status is None:
            errors.append(_err(
                "invalid_status",
                f"{tid} の status '{status_raw}' は不正です（done / in_progress / todo / blocked のいずれか）。",
                [tid]))
            status = "todo"
        deps_raw = raw.get("depends_on") or []
        if isinstance(deps_raw, str):
            deps_raw = [d for d in deps_raw.replace("、", ",").split(",")]
        if not isinstance(deps_raw, list):
            errors.append(_err("invalid_depends_on", f"{tid} の depends_on が配列ではありません。", [tid]))
            deps_raw = []
        deps: list[str] = []
        for d in deps_raw:
            d = str(d).strip()
            if d and d not in deps:
                deps.append(d)
        task = {"id": tid, "title": title or tid, "status": status, "depends_on": deps}
        for k in ("note", "owner"):
            if raw.get(k):
                task[k] = str(raw[k])
        tasks.append(task)
    return tasks, errors


def _err(code: str, message: str, task_ids: list[str], severity: str = "error") -> dict:
    return {"code": code, "severity": severity, "message": message, "task_ids": task_ids}


def validate(tasks: list[dict]) -> dict:
    """Detect duplicate IDs, unknown references, self dependencies and cycles.

    Returns {"ok": bool, "errors": [...], "warnings": [...], "cycles": [[ids...]]}.
    """
    errors: list[dict] = []
    warnings: list[dict] = []
    seen: dict[str, int] = {}
    for t in tasks:
        seen[t["id"]] = seen.get(t["id"], 0) + 1
    for tid, n in seen.items():
        if n > 1:
            errors.append(_err("duplicate_id", f"タスクID {tid} が {n} 回定義されています。", [tid]))
    ids = set(seen)
    by_id = {t["id"]: t for t in tasks}  # last one wins for analysis purposes
    for t in tasks:
        for d in t["depends_on"]:
            if d == t["id"]:
                errors.append(_err("self_dependency", f"{t['id']} が自分自身に依存しています。", [t["id"]]))
            elif d not in ids:
                errors.append(_err("unknown_reference",
                                   f"{t['id']} が存在しないタスク {d} に依存しています。", [t["id"], d]))
    cycles = find_cycles(by_id)
    for cyc in cycles:
        path = " → ".join(cyc + [cyc[0]])
        errors.append(_err("cycle", f"依存関係が循環しています: {path}", list(cyc)))
    # Consistency warnings (not fatal): progress state contradicts dependencies.
    for t in tasks:
        unfinished = [d for d in t["depends_on"] if d in by_id and by_id[d]["status"] != "done"]
        if t["status"] == "done" and unfinished:
            warnings.append(_err("done_before_dependency",
                                 f"{t['id']} は完了ですが、依存先 {', '.join(unfinished)} が未完了です。",
                                 [t["id"], *unfinished], "warning"))
        elif t["status"] == "in_progress" and unfinished:
            warnings.append(_err("started_before_dependency",
                                 f"{t['id']} は進行中ですが、依存先 {', '.join(unfinished)} が未完了です（並行作業なら問題なし）。",
                                 [t["id"], *unfinished], "warning"))
    return {"ok": not errors, "errors": errors, "warnings": warnings, "cycles": cycles}


def find_cycles(by_id: dict[str, dict]) -> list[list[str]]:
    """Return one representative cycle per strongly connected component (size>1)."""
    # Edges dep -> task, only for known ids, ignoring self loops (reported separately).
    succ: dict[str, list[str]] = {tid: [] for tid in by_id}
    for t in by_id.values():
        for d in t["depends_on"]:
            if d in by_id and d != t["id"]:
                succ[d].append(t["id"])
    # Tarjan SCC (iterative).
    index: dict[str, int] = {}
    low: dict[str, int] = {}
    on_stack: set[str] = set()
    stack: list[str] = []
    sccs: list[list[str]] = []
    counter = 0
    for root in sorted(by_id):
        if root in index:
            continue
        work = [(root, 0)]
        while work:
            v, i = work.pop()
            if i == 0:
                index[v] = low[v] = counter
                counter += 1
                stack.append(v)
                on_stack.add(v)
            recurse = False
            nbrs = succ[v]
            while i < len(nbrs):
                w = nbrs[i]
                i += 1
                if w not in index:
                    work.append((v, i))
                    work.append((w, 0))
                    recurse = True
                    break
                if w in on_stack:
                    low[v] = min(low[v], index[w])
            if recurse:
                continue
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop()
                    on_stack.discard(w)
                    comp.append(w)
                    if w == v:
                        break
                if len(comp) > 1:
                    sccs.append(comp)
            if work:
                parent = work[-1][0]
                low[parent] = min(low[parent], low[v])
    cycles = []
    for comp in sccs:
        cycles.append(_cycle_in_component(set(comp), succ))
    return cycles


def _cycle_in_component(comp: set[str], succ: dict[str, list[str]]) -> list[str]:
    start = min(comp)
    # BFS from start back to start within the component.
    prev: dict[str, str] = {}
    q = deque([start])
    visited = {start}
    while q:
        v = q.popleft()
        for w in succ[v]:
            if w not in comp:
                continue
            if w == start:
                path = [v]
                while path[-1] != start:
                    path.append(prev[path[-1]])
                return list(reversed(path))
            if w not in visited:
                visited.add(w)
                prev[w] = v
                q.append(w)
    return sorted(comp)


def _successors(tasks: list[dict]) -> dict[str, list[str]]:
    by_id = {t["id"]: t for t in tasks}
    succ: dict[str, list[str]] = {tid: [] for tid in by_id}
    for t in tasks:
        for d in t["depends_on"]:
            if d in by_id and d != t["id"] and t["id"] not in succ[d]:
                succ[d].append(t["id"])
    return succ


def downstream(tasks: list[dict], task_id: str) -> list[dict]:
    """All tasks reachable from task_id via dependency edges (what a delay would hit).

    Safe with cycles. Returns [{"id", "title", "status", "distance", "via"}] sorted by distance.
    """
    by_id = {t["id"]: t for t in tasks}
    if task_id not in by_id:
        raise KeyError(task_id)
    succ = _successors(tasks)
    dist = {task_id: 0}
    via: dict[str, str] = {}
    q = deque([task_id])
    while q:
        v = q.popleft()
        for w in succ[v]:
            if w not in dist:
                dist[w] = dist[v] + 1
                via[w] = v
                q.append(w)
    out = []
    for tid, dd in sorted(dist.items(), key=lambda kv: (kv[1], kv[0])):
        if tid == task_id:
            continue
        t = by_id[tid]
        out.append({"id": tid, "title": t["title"], "status": t["status"], "distance": dd, "via": via[tid]})
    return out


def simulate_delay(tasks: list[dict], task_id: str) -> dict:
    impacted = downstream(tasks, task_id)
    by_id = {t["id"]: t for t in tasks}
    unfinished = [x for x in impacted if x["status"] != "done"]
    already_done = [x for x in impacted if x["status"] == "done"]
    ids = [x["id"] for x in unfinished]
    if ids:
        summary = f"{task_id}（{by_id[task_id]['title']}）の遅延は {'・'.join(ids)} に波及する可能性があります。"
    else:
        summary = f"{task_id}（{by_id[task_id]['title']}）に依存する未完了タスクはありません。"
    if already_done:
        summary += f"（完了済みの {'・'.join(x['id'] for x in already_done)} は依存関係の矛盾として要確認）"
    return {"task_id": task_id, "impacted": unfinished, "impacted_done": already_done,
            "impacted_ids": ids, "summary": summary,
            "note": "所要時間の入力がないため、遅延日数ではなく到達可能な後続タスクのみを計算しています。"}


def analyze(tasks: list[dict], validation: dict | None = None) -> dict:
    """Bottleneck metrics, merge points and critical-path candidates."""
    validation = validation or validate(tasks)
    by_id = {t["id"]: t for t in tasks}
    succ = _successors(tasks)
    metrics = {}
    for tid, t in by_id.items():
        ds = downstream(tasks, tid)
        known_deps = [d for d in t["depends_on"] if d in by_id and d != tid]
        metrics[tid] = {
            "downstream_count": len(ds),
            "downstream_unfinished": sum(1 for x in ds if x["status"] != "done"),
            "downstream_ids": [x["id"] for x in ds],
            "in_degree": len(known_deps),
            "out_degree": len(succ[tid]),
            "is_merge_point": len(known_deps) >= 2,
        }
    merge_points = [
        {"id": tid, "title": by_id[tid]["title"], "depends_on": [d for d in by_id[tid]["depends_on"] if d in by_id]}
        for tid in sorted(by_id) if metrics[tid]["is_merge_point"]
    ]
    unfinished_ids = [tid for tid in by_id if by_id[tid]["status"] != "done"]
    bottlenecks = sorted(
        ({"id": tid, "title": by_id[tid]["title"], "status": by_id[tid]["status"],
          "downstream_unfinished": metrics[tid]["downstream_unfinished"],
          "is_merge_point": metrics[tid]["is_merge_point"],
          "score": metrics[tid]["downstream_unfinished"] + (1 if metrics[tid]["is_merge_point"] else 0)
                   + (2 if by_id[tid]["status"] == "blocked" else 0)}
         for tid in unfinished_ids),
        key=lambda x: (-x["score"], -x["downstream_unfinished"], x["id"]))
    bottlenecks = [b for b in bottlenecks if b["score"] > 0][:5]
    critical = critical_path_candidates(tasks) if not validation["cycles"] else []
    return {
        "metrics": metrics,
        "merge_points": merge_points,
        "bottlenecks": bottlenecks,
        "critical_path_candidates": critical,
        "critical_path_note": (
            "所要時間が未入力のため、各未完了タスクを同じ重み(1)と仮定した最長の未完了チェーンを候補として示しています。"
            if not validation["cycles"] else "循環があるためクリティカルパスは計算していません。"),
        "counts": {s: sum(1 for t in tasks if t["status"] == s) for s in STATUSES},
    }


def critical_path_candidates(tasks: list[dict], limit: int = 3) -> list[dict]:
    """Longest chains counted by unfinished tasks (unit weight). Assumes a DAG."""
    by_id = {t["id"]: t for t in tasks}
    succ = _successors(tasks)
    preds: dict[str, list[str]] = {tid: [] for tid in by_id}
    for v, ws in succ.items():
        for w in ws:
            preds[w].append(v)
    # Topological order (Kahn).
    indeg = {tid: len(preds[tid]) for tid in by_id}
    q = deque(sorted(t for t, d in indeg.items() if d == 0))
    order = []
    while q:
        v = q.popleft()
        order.append(v)
        for w in sorted(succ[v]):
            indeg[w] -= 1
            if indeg[w] == 0:
                q.append(w)
    if len(order) != len(by_id):
        return []
    w = {tid: (0 if by_id[tid]["status"] == "done" else 1) for tid in by_id}
    best: dict[str, int] = {}
    best_prev: dict[str, str | None] = {}
    for v in order:
        cands = [(best[p], p) for p in preds[v]]
        if cands:
            # Prefer the heavier chain; tie-break by id for determinism.
            score, p = max(cands, key=lambda c: (c[0], c[1]))
            best[v] = score + w[v]
            best_prev[v] = p
        else:
            best[v] = w[v]
            best_prev[v] = None
    sinks = [tid for tid in by_id if not succ[tid] and best[tid] > 0]
    sinks.sort(key=lambda t: (-best[t], t))
    out = []
    for s in sinks[:limit]:
        path = [s]
        while best_prev[path[-1]] is not None:
            path.append(best_prev[path[-1]])
        path.reverse()
        remaining = [p for p in path if by_id[p]["status"] != "done"]
        out.append({"path": path, "remaining": remaining, "remaining_count": len(remaining)})
    return out


def process(raw_tasks: Any) -> dict:
    """Normalize + validate + analyze. Used on every create/update."""
    tasks, norm_errors = normalize_tasks(raw_tasks)
    v = validate(tasks)
    v["errors"] = norm_errors + v["errors"]
    v["ok"] = not v["errors"]
    v["error_task_ids"] = sorted({tid for e in v["errors"] for tid in e["task_ids"]})
    return {"tasks": tasks, "validation": v, "graph": analyze(tasks, v)}
