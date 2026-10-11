"""Shared store: one JSON file per map_id (the source of truth for TaMap state).

Writes are atomic (tmp file + os.replace) and serialized with an fcntl lock so that
expected_revision checks are race-free between concurrent MCP processes.
"""
from __future__ import annotations

import contextlib
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
    """Free-form finding/action: accept a string or {title/text, reason/detail, task_ids}."""
    if isinstance(x, str):
        return {"text": x}
    if isinstance(x, dict):
        out = {"text": str(x.get("text") or x.get("title") or x.get("summary") or "").strip()}
        for k in ("reason", "detail", "severity", "owner"):
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
        map_["history"].append({"revision": map_["revision"], "updated_at": map_["updated_at"],
                                "source": source, "change": ",".join(changed)})
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


def set_bot_status(map_id: str, bot: str, status: str, note: str | None = None) -> dict:
    """Record a bot's activity state on a map. Does not bump the map revision (operational data)."""
    key = (bot or "").strip().lower().replace(" ", "_").replace("-", "_")
    key = BOT_ALIASES.get(key, key)
    if key not in BOT_KEYS:
        raise StoreError(f"bot は {' / '.join(BOT_KEYS)} のいずれかです（{bot!r}）。")
    st = (status or "").strip().lower()
    if st not in BOT_STATUSES:
        raise StoreError(f"status は {' / '.join(BOT_STATUSES)} のいずれかです（{status!r}）。")
    note = (note or "").strip()[:200] or None
    with _lock():
        map_ = read_map(map_id)
        ts = now_iso()
        map_.setdefault("bots", {})[key] = {"status": st, "note": note, "updated_at": ts}
        hist = map_.setdefault("bot_history", [])
        hist.append({"at": ts, "bot": key, "status": st, "note": note})
        map_["bot_history"] = hist[-BOT_HISTORY_LIMIT:]
        _write(map_)
    return map_
