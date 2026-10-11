"""Lenient reader for a specialist bot's plain-text reply.

Grok Bot teammate messages are plain text. The PM asks with a short note plus one
```json fence, and the specialist answers the same way. Models still wrap that JSON in
prose, smart quotes, and trailing commas, so the PM should pass the raw reply here
instead of parsing it itself.
"""
from __future__ import annotations

import json
import re
from typing import Any

# Speech-bubble cap used by set_bot_status. Duplicated here so this module does not import store.
SAY_LIMIT = 30

_FENCE = re.compile(r"```([^\n`]*)\n(.*?)```", re.DOTALL)
_INLINE_FENCE = re.compile(r"```[ \t]*(json|jsonc)[ \t]+(\{.*?\})[ \t]*```", re.DOTALL | re.IGNORECASE)

_DOUBLE_QUOTES = str.maketrans({
    "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u00ab": '"', "\u00bb": '"', "\uff02": '"',
})
_SINGLE_QUOTES = str.maketrans({"\u2018": '"', "\u2019": '"', "\u201a": '"'})

ROLE_ALIASES = {
    "map_architect": "map_architect", "ma": "map_architect", "architect": "map_architect",
    "maparchitect": "map_architect",
    "risk_analyst": "risk_analyst", "ra": "risk_analyst", "risk": "risk_analyst",
    "quality_reviewer": "quality_reviewer", "qr": "quality_reviewer", "quality": "quality_reviewer",
    "reviewer": "quality_reviewer",
}
ROLE_NAMES = {
    "map_architect": "Map Architect",
    "risk_analyst": "Risk Analyst",
    "quality_reviewer": "Quality Reviewer",
}


class HandoffError(Exception):
    def __init__(self, message: str, *, hint: str | None = None):
        super().__init__(message)
        self.hint = hint


def canon_role(role: str | None) -> str | None:
    if role is None or not str(role).strip():
        return None
    key = str(role).strip().lower().replace(" ", "_").replace("-", "_")
    if key not in ROLE_ALIASES:
        raise HandoffError(
            f"role は map_architect / risk_analyst / quality_reviewer のいずれかです（{role!r}）。",
            hint="parse_handoff の role を空にするか、3つの名前のいずれかにしてください。")
    return ROLE_ALIASES[key]


def normalize_text(text: str) -> str:
    text = text.replace("\ufeff", "").replace("\u200b", "").replace("\u200c", "").replace("\u200d", "")
    text = text.replace("\u00a0", " ")
    return text.translate(_DOUBLE_QUOTES)


def strip_trailing_commas(s: str) -> str:
    """Remove commas that sit immediately before } or ], without touching commas inside strings."""
    out: list[str] = []
    in_str = False
    esc = False
    i = 0
    n = len(s)
    while i < n:
        c = s[i]
        if in_str:
            out.append(c)
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            i += 1
            continue
        if c == '"':
            in_str = True
            out.append(c)
            i += 1
            continue
        if c == ",":
            j = i + 1
            while j < n and s[j] in " \t\r\n":
                j += 1
            if j < n and s[j] in "}]":
                i += 1
                continue
        out.append(c)
        i += 1
    return "".join(out)


def loads_lenient(s: str) -> Any:
    """json.loads after smart-quote and trailing-comma repair. Raises json.JSONDecodeError."""
    primary = strip_trailing_commas(normalize_text(s))
    try:
        return json.loads(primary)
    except json.JSONDecodeError as first:
        secondary = strip_trailing_commas(primary.translate(_SINGLE_QUOTES))
        if secondary == primary:
            raise first
        try:
            return json.loads(secondary)
        except json.JSONDecodeError:
            raise first


def _fence_lang(info: str) -> str:
    info = (info or "").strip().lower()
    return info.split()[0] if info else ""


def _fences(text: str) -> list[tuple[str, str]]:
    blocks = [(_fence_lang(m.group(1)), m.group(2).strip()) for m in _FENCE.finditer(text)]
    if blocks:
        return blocks
    return [("json", m.group(2).strip()) for m in _INLINE_FENCE.finditer(text)]


def _match_brace(s: str, start: int) -> int | None:
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(s)):
        c = s[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return i
    return None


def top_level_objects(s: str) -> list[str]:
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        if s[i] == "{":
            end = _match_brace(s, i)
            if end is None:
                i += 1
                continue
            out.append(s[i:end + 1])
            i = end + 1
            continue
        i += 1
    return out


def _candidates(text: str) -> list[str]:
    """Preferred blobs first.

    A ```json fence is the reply. Only the last such fence is read, so an example earlier in the
    message is not used when the actual fence fails. Without a fence, outermost objects are tried
    from the end of the text.
    """
    seen: set[str] = set()
    out: list[str] = []

    def add(blob: str) -> None:
        blob = blob.strip()
        if blob and blob not in seen:
            seen.add(blob)
            out.append(blob)

    tagged = [(lang, body) for lang, body in _fences(text) if lang in ("json", "jsonc") or lang.startswith("json")]
    plain = [(lang, body) for lang, body in _fences(text) if lang == ""]
    fences = tagged or plain
    if fences:
        body = fences[-1][1]
        add(body)
        for obj in reversed(top_level_objects(body)):
            add(obj)
        return out
    for obj in reversed(top_level_objects(text)):
        add(obj)
    return out


def _validate(data: dict, role: str | None) -> tuple[list[str], list[str]]:
    problems: list[str] = []
    warnings: list[str] = []
    say = data.get("say")
    if isinstance(say, str) and len(say.strip()) > SAY_LIMIT:
        warnings.append(f"say は{len(say.strip())}文字あります。set_bot_status では{SAY_LIMIT}文字までです。")
    if role == "map_architect":
        tasks = data.get("tasks")
        if not isinstance(tasks, list) or not tasks:
            problems.append("Map Architect の返信には tasks（空でない配列）が必要です。")
        else:
            for i, t in enumerate(tasks):
                if not isinstance(t, dict) or not str(t.get("id") or "").strip():
                    problems.append(f"tasks[{i}] に id がありません。")
                elif not str(t.get("title") or "").strip():
                    warnings.append(f"tasks[{i}]（{t.get('id')}）に title がありません。")
    elif role == "risk_analyst":
        if not any(k in data for k in ("summary", "items", "origin_ids")):
            problems.append("Risk Analyst の返信には summary / items / origin_ids のいずれかが必要です。")
        for key in ("items", "origin_ids", "impacted_ids", "merge_points"):
            if key in data and not isinstance(data[key], list):
                problems.append(f"{key} は配列である必要があります。")
    elif role == "quality_reviewer":
        items = data.get("items")
        if not isinstance(items, list):
            problems.append("Quality Reviewer の返信には items（指摘の配列。無ければ []）が必要です。")
        else:
            for i, it in enumerate(items):
                if isinstance(it, str):
                    if not it.strip():
                        problems.append(f"items[{i}] が空です。")
                    else:
                        warnings.append(f"items[{i}] は文字列です。before / text / reason のオブジェクトにしてください。")
                elif isinstance(it, dict):
                    if not str(it.get("text") or it.get("after") or "").strip():
                        problems.append(f"items[{i}] に text（直した文）がありません。")
                    elif not str(it.get("before") or "").strip():
                        warnings.append(f"items[{i}] に before（直す前）がありません。")
                else:
                    problems.append(f"items[{i}] はオブジェクトか文字列である必要があります。")
    return problems, warnings


def _hint_for(role: str | None) -> str:
    if role == "map_architect":
        return "```json の中に {\"tasks\": [{\"id\", \"title\", \"status\", \"depends_on\"}], \"say\"} を1つ入れて送り直してください。"
    if role == "risk_analyst":
        return "```json の中に summary と items（対処案）を1つのオブジェクトで返してください。"
    if role == "quality_reviewer":
        return "```json の中に {\"items\": [{\"before\", \"text\", \"reason\"}]} を返してください。指摘が無ければ items は [] です。"
    return "返信に ```json と ``` で囲んだオブジェクトを1つだけ入れてください。"


def parse_reply(text: str | None, role: str | None = None) -> dict:
    """Extract one JSON object from a specialist reply.

    Returns {"role", "data", "warnings"}. Raises HandoffError with a Japanese message and hint.
    """
    role_key = canon_role(role)
    if text is None or not str(text).strip():
        raise HandoffError(
            "返信が空です。",
            hint="専門Botには、短い説明のあとに ```json で囲んだオブジェクトを1つ返させてください。")
    raw = normalize_text(str(text))
    candidates = _candidates(raw)
    if not candidates:
        raise HandoffError("JSON が見つかりません。", hint=_hint_for(role_key))
    syntax: list[str] = []
    saw_non_object = False
    for index, blob in enumerate(candidates):
        try:
            value = loads_lenient(blob)
        except json.JSONDecodeError as e:
            syntax.append(str(e))
            continue
        if not isinstance(value, dict):
            # The fence (or the only blob) itself parsed as a non-object. Don't dig into it.
            if index == 0:
                raise HandoffError(
                    "JSON はオブジェクト（{...}）である必要があります。配列や文字列は受け取れません。",
                    hint=_hint_for(role_key))
            saw_non_object = True
            continue
        problems, warnings = _validate(value, role_key)
        if problems:
            raise HandoffError(" / ".join(problems), hint=_hint_for(role_key))
        return {"role": role_key, "data": value, "warnings": warnings}
    if saw_non_object and not syntax:
        raise HandoffError(
            "JSON はオブジェクト（{...}）である必要があります。配列や文字列は受け取れません。",
            hint=_hint_for(role_key))
    detail = syntax[-1] if syntax else "形式が分かりません。"
    raise HandoffError(f"JSON を読めませんでした: {detail}", hint=_hint_for(role_key))


def summary_line(parsed: dict) -> str:
    """One chat line. The PM should not paste the specialist JSON itself."""
    role = parsed.get("role")
    data = parsed["data"]
    name = ROLE_NAMES.get(role or "", "専門Bot")
    if role == "map_architect" and isinstance(data.get("tasks"), list):
        head = f"{name} の返信を読み取りました（tasks {len(data['tasks'])}件）。"
    elif role == "quality_reviewer" and isinstance(data.get("items"), list):
        head = f"{name} の返信を読み取りました（指摘 {len(data['items'])}件）。"
    elif role == "risk_analyst":
        origins = data.get("origin_ids") if isinstance(data.get("origin_ids"), list) else []
        head = f"{name} の返信を読み取りました（起点 {'・'.join(map(str, origins)) or '記載なし'}）。"
    else:
        keys = "、".join(list(data)[:8]) or "（空）"
        head = f"返信の JSON を読み取りました（キー: {keys}）。"
    if parsed.get("warnings"):
        head += "注意: " + " / ".join(parsed["warnings"])
    return head
