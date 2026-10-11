"""Shared store: one JSON file per map_id (the source of truth for TaMap state).

Writes are atomic (tmp file + os.replace) and serialized with an fcntl lock so that
expected_revision checks are race-free between concurrent MCP processes.
"""
from __future__ import annotations

import contextlib
import copy
import fcntl
import json
import os
import re
import secrets
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import core

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("TAMAP_DATA_DIR", ROOT / "data" / "maps"))
MAP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,64}$")
MAX_ACTIONS = 3
HISTORY_LIMIT = 50


class StoreError(Exception):
    pass


class RevisionConflict(StoreError):
    def __init__(self, map_id: str, expected: int, actual: int):
        super().__init__(
            f"revision conflict: map {map_id} は revision {actual} です（expected_revision={expected}）。"
            " get_map で最新状態を読み直してから再度 update_map してください。")
        self.expected = expected
        self.actual = actual


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _path(map_id: str) -> Path:
    if not MAP_ID_RE.match(map_id or ""):
        raise StoreError(f"不正な map_id です: {map_id!r}")
    return DATA_DIR / f"{map_id}.json"


@contextlib.contextmanager
def _lock():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(DATA_DIR / ".lock", "a+") as fh:
        fcntl.flock(fh, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(fh, fcntl.LOCK_UN)


def _write(map_: dict) -> None:
    p = _path(map_["map_id"])
    tmp = p.with_suffix(f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(map_, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


def read_map(map_id: str) -> dict:
    p = _path(map_id)
    if not p.exists():
        raise StoreError(f"map {map_id} は存在しません。")
    return json.loads(p.read_text(encoding="utf-8"))


def _as_list(x: Any) -> list:
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return [x]


def _normalize_item(x: Any) -> dict:
    """Free-form finding/action: accept a string or {text/after/title, before, reason/detail, task_ids}.

    For quality items, `before` is the original wording and `text` the corrected one (UX_DESIGN 4.3).
    """
    if isinstance(x, str):
        return {"text": x}
    if isinstance(x, dict):
        out = {"text": str(x.get("text") or x.get("after") or x.get("title") or x.get("summary") or "").strip()}
        for k in ("before", "reason", "detail", "severity", "owner"):
            if x.get(k):
                out[k] = str(x[k])
        tids = x.get("task_ids") or x.get("tasks")
        if tids:
            out["task_ids"] = [str(t) for t in _as_list(tids)]
        return out
    return {"text": str(x)}


def normalize_analysis(raw: Any) -> dict:
    """analysis = {pm:{summary, actions<=3}, risk:{summary, items}, quality:{summary, items},
                   map_architect:{summary}, assumptions:[str], question:str}"""
    if raw is None:
        raw = {}
    if not isinstance(raw, dict):
        raise StoreError("analysis はオブジェクトである必要があります。")
    out: dict[str, Any] = {}
    for role in ("pm", "map_architect", "risk", "quality"):
        r = raw.get(role)
        if r is None:
            continue
        if isinstance(r, str):
            r = {"summary": r}
        if not isinstance(r, dict):
            raise StoreError(f"analysis.{role} はオブジェクトか文字列である必要があります。")
        sec: dict[str, Any] = {"summary": str(r.get("summary") or "").strip()}
        if role == "pm":
            actions = [_normalize_item(a) for a in _as_list(r.get("actions"))]
            if len(actions) > MAX_ACTIONS:
                raise StoreError(f"analysis.pm.actions は最大 {MAX_ACTIONS} 件です（{len(actions)} 件指定）。")
            sec["actions"] = actions
        else:
            sec["items"] = [_normalize_item(a) for a in _as_list(r.get("items") or r.get("findings"))]
        out[role] = sec
    # Allow top-level "actions" as a shortcut for pm.actions.
    if raw.get("actions") is not None:
        actions = [_normalize_item(a) for a in _as_list(raw["actions"])]
        if len(actions) > MAX_ACTIONS:
            raise StoreError(f"actions は最大 {MAX_ACTIONS} 件です（{len(actions)} 件指定）。")
        out.setdefault("pm", {"summary": ""})["actions"] = actions
    out["assumptions"] = [str(a) for a in _as_list(raw.get("assumptions"))]
    if raw.get("question"):
        out["question"] = str(raw["question"])
    return out


def _apply_tasks(map_: dict, raw_tasks: Any) -> None:
    result = core.process(raw_tasks)
    map_["tasks"] = result["tasks"]
    map_["validation"] = result["validation"]
    map_["graph"] = result["graph"]


def top_bottlenecks(graph: dict) -> list[str]:
    """Ids sharing the highest bottleneck score (the ones labelled ▲ボトルネック in the map)."""
    bs = graph.get("bottlenecks") or []
    return [b["id"] for b in bs if b["score"] == bs[0]["score"]] if bs else []


def impacted_by(tasks: list[dict], ids: list[str]) -> list[str]:
    """Unfinished tasks downstream of any of the given ids (what the bottlenecks hold up).

    A bottleneck that sits downstream of another bottleneck is held up too, so it is included.
    """
    known = {t["id"] for t in tasks}
    out: list[str] = []
    for tid in ids:
        if tid not in known:
            continue
        for x in core.downstream(tasks, tid):
            if x["status"] != "done" and x["id"] not in out:
                out.append(x["id"])
    return sorted(out, key=_id_key)


def _id_key(tid: str):
    m = re.match(r"^(.*?)(\d+)$", tid)
    return (m.group(1), int(m.group(2)), tid) if m else (tid, -1, tid)


def _ids(xs: list[str]) -> str:
    return "・".join(xs) if xs else "なし"


def compute_diff(old: dict, new: dict) -> dict:
    """One-line revision diff: task changes / bottleneck / impacted tasks (UX_DESIGN 4.5, P3)."""
    before = {t["id"]: t for t in old["tasks"]}
    after = {t["id"]: t for t in new["tasks"]}
    label = core.STATUS_LABELS_JA
    changes: list[dict] = []
    for tid in sorted(set(before) | set(after), key=_id_key):
        a, b = before.get(tid), after.get(tid)
        if a is None:
            changes.append({"id": tid, "kind": "added", "text": f"{tid} 追加"})
        elif b is None:
            changes.append({"id": tid, "kind": "removed", "text": f"{tid} 削除"})
        else:
            if a["status"] != b["status"]:
                changes.append({"id": tid, "kind": "status", "from": a["status"], "to": b["status"],
                                "text": f"{tid} {label[a['status']]}→{label[b['status']]}"})
            if a["depends_on"] != b["depends_on"]:
                changes.append({"id": tid, "kind": "depends_on", "from": a["depends_on"], "to": b["depends_on"],
                                "text": f"{tid} 依存 {_ids(a['depends_on'])}→{_ids(b['depends_on'])}"})
            if a["title"] != b["title"]:
                changes.append({"id": tid, "kind": "title", "from": a["title"], "to": b["title"],
                                "text": f"{tid} タイトル変更"})
    if changes:
        change_text = "、".join(c["text"] for c in changes)
    elif old.get("analysis") != new.get("analysis"):
        change_text = "分析のみ更新（タスク変化なし）"
    elif old.get("title") != new.get("title"):
        change_text = "タイトルのみ更新"
    else:
        change_text = "変化なし"

    bn_old, bn_new = top_bottlenecks(old["graph"]), top_bottlenecks(new["graph"])

    def why_dropped(tid: str, fallback: str | None) -> str | None:
        if tid not in after:
            return "削除"
        if after[tid]["status"] == "done":
            return "完了"
        if tid in bn_new:
            return "ボトルネックに"
        return fallback

    def part(name: str, x: list[str], y: list[str], fallback: str | None) -> tuple[dict, str]:
        """`X→Y`, plus why ids left the list so a shorter list is not misread as less impact."""
        if x == y:
            return {"before": x, "after": y, "changed": False}, f"{name}：変化なし（{_ids(y)}）"
        reasons: dict[str, list[str]] = {}
        for tid in x:
            r = why_dropped(tid, fallback) if tid not in y else None
            if r:
                reasons.setdefault(r, []).append(tid)
        note = "、".join(f"{_ids(ids)}は{r}" for r, ids in reasons.items())
        return ({"before": x, "after": y, "changed": True, "dropped": reasons},
                f"{name}：{_ids(x)}→{_ids(y)}" + (f"（{note}）" if note else ""))

    bott, bott_text = part("ボトルネック", bn_old, bn_new, None)
    imp, imp_text = part("影響先", impacted_by(old["tasks"], bn_old), impacted_by(new["tasks"], bn_new),
                         "ボトルネックの下流から外れた")
    segs = [f"変更点：{change_text}", bott_text, imp_text]
    ov, nv = old["validation"], new["validation"]
    if ov["ok"] != nv["ok"] or len(ov["errors"]) != len(nv["errors"]):
        def vs(v):
            return "OK" if v["ok"] else f"エラー{len(v['errors'])}件"
        segs.append(f"検証：{vs(ov)}→{vs(nv)}")
    return {"from_revision": old["revision"], "to_revision": new["revision"], "task_changes": changes,
            "bottleneck": bott, "impacted": imp, "text": " ／ ".join(segs)}


def create_map(title: str, tasks: Any, analysis: Any = None, source: str = "unknown") -> dict:
    title = (title or "").strip() or "無題のプロジェクト"
    ana = normalize_analysis(analysis)
    with _lock():
        map_id = secrets.token_urlsafe(6).replace("_", "x").replace("-", "y")
        ts = now_iso()
        map_ = {"map_id": map_id, "title": title, "revision": 1, "created_at": ts, "updated_at": ts,
                "source": source, "analysis": ana, "history": [],
                "bots": {}, "bot_history": []}
        _apply_tasks(map_, tasks)
        map_["history"].append({"revision": 1, "updated_at": ts, "source": source, "change": "create"})
        _write(map_)
    return map_


def update_map(map_id: str, expected_revision: int, tasks: Any = None, analysis: Any = None,
               source: str = "unknown", title: str | None = None) -> dict:
    ana = normalize_analysis(analysis) if analysis is not None else None
    with _lock():
        map_ = read_map(map_id)
        if int(expected_revision) != int(map_["revision"]):
            raise RevisionConflict(map_id, int(expected_revision), int(map_["revision"]))
        old = {k: copy.deepcopy(map_[k]) for k in ("revision", "title", "tasks", "validation", "graph")}
        old["analysis"] = copy.deepcopy(map_.get("analysis"))
        changed = []
        if tasks is not None:
            _apply_tasks(map_, tasks)
            changed.append("tasks")
        if ana is not None:
            map_["analysis"] = ana
            changed.append("analysis")
        if title and title.strip():
            map_["title"] = title.strip()
            changed.append("title")
        if not changed:
            raise StoreError("更新内容がありません（tasks / analysis / title のいずれかを指定してください）。")
        map_["revision"] = int(map_["revision"]) + 1
        map_["updated_at"] = now_iso()
        map_["source"] = source
        map_["last_diff"] = compute_diff(old, map_)
        map_["history"].append({"revision": map_["revision"], "updated_at": map_["updated_at"],
                                "source": source, "change": ",".join(changed),
                                "diff": map_["last_diff"]["text"]})
        map_["history"] = map_["history"][-HISTORY_LIMIT:]
        _write(map_)
    return map_


def list_maps() -> list[dict]:
    if not DATA_DIR.exists():
        return []
    out = []
    for p in DATA_DIR.glob("*.json"):
        try:
            m = json.loads(p.read_text(encoding="utf-8"))
            out.append({k: m[k] for k in ("map_id", "title", "revision", "updated_at")})
        except (OSError, ValueError, KeyError):
            continue
    return sorted(out, key=lambda m: m["updated_at"], reverse=True)


BOT_KEYS = ("pm", "map_architect", "risk_analyst", "quality_reviewer")
BOT_STATUSES = ("idle", "working", "done", "error")
BOT_ALIASES = {"tamap_pm": "pm", "main": "pm", "architect": "map_architect", "risk": "risk_analyst",
               "quality": "quality_reviewer", "reviewer": "quality_reviewer"}
BOT_HISTORY_LIMIT = 30
SAY_LIMIT = 30


BOT_NAMES = {"pm": "TaMap PM", "map_architect": "Map Architect", "risk_analyst": "Risk Analyst",
             "quality_reviewer": "Quality Reviewer"}


def set_bot_status(map_id: str, bot: str, status: str, note: str | None = None, say: str | None = None) -> dict:
    """Record a bot's activity state on a map. Does not bump the map revision (operational data).

    Only one bot lights up at a time: when a specialist becomes `working`, a working PM is put back
    to `idle` (note「<Bot>の結果待ち」) and that is recorded in bot_history too.
    `say` is an optional in-character one-liner shown in the flow GIF speech bubble (note stays factual).
    """
    key = (bot or "").strip().lower().replace(" ", "_").replace("-", "_")
    key = BOT_ALIASES.get(key, key)
    if key not in BOT_KEYS:
        raise StoreError(f"bot は {' / '.join(BOT_KEYS)} のいずれかです（{bot!r}）。")
    st = (status or "").strip().lower()
    if st not in BOT_STATUSES:
        raise StoreError(f"status は {' / '.join(BOT_STATUSES)} のいずれかです（{status!r}）。")
    note = (note or "").strip()[:200] or None
    say = (say or "").strip()[:SAY_LIMIT] or None
    with _lock():
        map_ = read_map(map_id)
        ts = now_iso()
        bots = map_.setdefault("bots", {})
        hist = map_.setdefault("bot_history", [])
        if key != "pm" and st == "working" and (bots.get("pm") or {}).get("status", "idle") != "idle":
            wait = f"{BOT_NAMES[key]}の結果待ち"
            bots["pm"] = {"status": "idle", "note": wait, "updated_at": ts}
            hist.append({"at": ts, "bot": "pm", "status": "idle", "note": wait, "auto": True})
        bots[key] = {"status": st, "note": note, "updated_at": ts, **({"say": say} if say else {})}
        hist.append({"at": ts, "bot": key, "status": st, "note": note, **({"say": say} if say else {})})
        map_["bot_history"] = hist[-BOT_HISTORY_LIMIT:]
        _write(map_)
    return map_
