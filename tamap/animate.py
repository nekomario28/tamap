"""Flow GIF: replay one PM → Map Architect → Risk Analyst → Quality Reviewer → PM cycle from bot_history.

render_flow_gif(map) writes out/<map_id>_flow.gif (TAMAP_OUT_DIR to override). The bots are retro
pixel characters (sprites.py / persona.py): only the working bot is lit and bobs, idle bots are faded
and doze, each status change gets a speech bubble in the bot's own voice (`say` or the persona line).
Requests (blue envelope) and results (yellow envelope) travel between PM and the specialist; the last
frames spread the delay impact from the bottleneck over the task map and show the PM's 3 actions plus
the Quality Reviewer badge (count = analysis.quality.items).
render_team_card() writes out/tamap_team.gif, a team introduction for the PM's greeting.
"""
from __future__ import annotations

import os
import subprocess
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import core, persona, sprites, store
from .render import hms

OUT_DIR = Path(os.environ.get("TAMAP_OUT_DIR", store.ROOT / "out"))
W, H = 960, 540
BG = (248, 250, 252)
INK = (17, 24, 39)
MUTED = (100, 116, 139)
BOT_FILL = {"idle": (156, 163, 175), "working": (59, 130, 246), "done": (34, 197, 94), "error": (239, 68, 68)}
TASK_FILL = {"done": (34, 197, 94), "in_progress": (59, 130, 246), "todo": (156, 163, 175),
             "blocked": (249, 115, 22)}
IMPACT = (250, 204, 21)
ERR = (239, 68, 68)
REQUEST, RESULT = (37, 99, 235), (234, 179, 8)
BOT_STATUS_JA = {"idle": "待機", "working": "作業中", "done": "完了", "error": "エラー"}
NODES = [("user", "ユーザー", 80), ("pm", "TaMap PM", 250), ("map_architect", "Map Architect", 455),
         ("risk_analyst", "Risk Analyst", 640), ("quality_reviewer", "Quality Reviewer", 825)]
NODE_X = {k: x for k, _, x in NODES}
SCALE = 6
BUBBLE_Y = 56
SPRITE_Y = 82
LINK_Y = SPRITE_Y + 7 * SCALE
NAME_Y = 182
CAPTION_Y = 240
TASKS_TOP, TASKS_BOTTOM = 270, 522
GLOW_PAD = 10


def glow_box(key: str, x: int) -> tuple[int, int, int, int]:
    """Highlight box behind a working bot, sized to the sprite's real pixels (Risk Analyst's magnifier
    sticks out to the right) and never narrower than the default 124px card. Shared with the live page."""
    xs = [gx for gx, _, _ in sprites.bot_pixels(key, "working")]
    left = x - 8 * SCALE + min(xs) * SCALE - GLOW_PAD
    right = x - 8 * SCALE + (max(xs) + 1) * SCALE + GLOW_PAD
    return min(left, x - 62), SPRITE_Y - 8 - SCALE, max(right, x + 62), SPRITE_Y + 14 * SCALE + 6


FONT_CANDIDATES = [
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/opentype/ipafont-gothic/ipagp.ttf",
    "/usr/share/fonts/truetype/takao-gothic/TakaoPGothic.ttf",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
]


def find_font() -> str | None:
    env = os.environ.get("TAMAP_FONT")
    if env and Path(env).exists():
        return env
    for p in FONT_CANDIDATES:
        if Path(p).exists():
            return p
    try:
        out = subprocess.run(["fc-list", ":lang=ja", "file"], capture_output=True, text=True, timeout=5).stdout
        for line in out.splitlines():
            p = line.split(":")[0].strip()
            if p and Path(p).exists():
                return p
    except (OSError, subprocess.SubprocessError):
        pass
    return None


class Fonts:
    def __init__(self):
        self.path = find_font()
        self._cache: dict[int, ImageFont.ImageFont] = {}

    def __call__(self, size: int):
        if size not in self._cache:
            self._cache[size] = (ImageFont.truetype(self.path, size) if self.path
                                 else ImageFont.load_default(size))
        return self._cache[size]


GLYPH_FIX = str.maketrans({"〜": "～"})  # WAVE DASH is missing from some CJK fonts (renders as tofu)


def _fit(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> str:
    text = text.translate(GLYPH_FIX)
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…"


def _wrap(draw, text: str, font, width: int, max_lines: int) -> list[str]:
    text = text.translate(GLYPH_FIX)
    lines, cur = [], ""
    for ch in text:
        if draw.textlength(cur + ch, font=font) > width:
            lines.append(cur)
            cur = ch
        else:
            cur += ch
    lines.append(cur)
    if len(lines) > max_lines:
        lines = lines[:max_lines - 1] + [_fit(draw, "".join(lines[max_lines - 1:]), font, width)]
    return lines


def _center(draw, xy, text, font, fill):
    draw.text(xy, text, font=font, fill=fill, anchor="mm")


def cycle_events(history: list[dict]) -> list[dict]:
    """The latest whole cycle, from the user's request to the PM's final answer.

    A cycle ends with `pm done/error`. If the history ends with one, the cycle is the stretch after the
    previous PM done/error; otherwise (still running) it is everything after the last PM done/error.
    Leading entries before the cycle's first `pm working` (the intake) are skipped, so the GIF replays
    PM → Map Architect → PM → Risk Analyst → PM → Quality Reviewer → PM in full.
    """
    if not history:
        return []
    ends = [i for i, h in enumerate(history) if h["bot"] == "pm" and h["status"] in ("done", "error")]
    last = len(history) - 1
    if ends and ends[-1] == last:
        start = ends[-2] + 1 if len(ends) > 1 else 0
    else:
        start = ends[-1] + 1 if ends else 0
    seg = history[start:]
    intake = next((i for i, h in enumerate(seg) if h["bot"] == "pm" and h["status"] == "working"), 0)
    return list(seg[intake:])


def _layers(tasks: list[dict]) -> dict[str, int]:
    by_id = {t["id"]: t for t in tasks}
    depth: dict[str, int] = {}
    succ = {tid: [] for tid in by_id}
    indeg = {tid: 0 for tid in by_id}
    for t in by_id.values():
        for d in t["depends_on"]:
            if d in by_id and d != t["id"]:
                succ[d].append(t["id"])
                indeg[t["id"]] += 1
    q = deque(tid for tid in by_id if indeg[tid] == 0)
    for tid in q:
        depth[tid] = 0
    while q:
        v = q.popleft()
        for w in succ[v]:
            depth[w] = max(depth.get(w, 0), depth[v] + 1)
            indeg[w] -= 1
            if indeg[w] == 0:
                q.append(w)
    nxt = max(depth.values(), default=-1) + 1
    for tid in by_id:  # tasks on a cycle: put them after everything else
        if tid not in depth:
            depth[tid] = nxt
    return depth


def task_layout(tasks: list[dict]) -> tuple[dict[str, tuple[int, int]], int, int]:
    """Task box centres (columns = dependency depth) and box size on the 960x540 canvas (GIF and live page)."""
    ids_seen: dict[str, dict] = {}
    for t in tasks:
        ids_seen.setdefault(t["id"], t)
    depth = _layers(list(ids_seen.values()))
    cols: dict[int, list[str]] = {}
    for tid in ids_seen:
        cols.setdefault(depth[tid], []).append(tid)
    ncol = max(len(cols), 1)
    top, bottom, left, right = TASKS_TOP, TASKS_BOTTOM, 30, W - 30
    cw = (right - left) / ncol
    box_w = int(min(150, cw - 24))
    rows = max((len(v) for v in cols.values()), default=1)
    rh = (bottom - top) / rows
    box_h = int(min(52, rh - 10))
    pos: dict[str, tuple[int, int]] = {}
    for c, ids in sorted(cols.items()):
        x = int(left + cw * c + cw / 2)
        y0 = top + (bottom - top - rh * len(ids)) / 2
        for r, tid in enumerate(ids):
            pos[tid] = (x, int(y0 + rh * r + rh / 2))
    return pos, box_w, box_h


class FlowRenderer:
    def __init__(self, m: dict):
        self.m = m
        self.font = Fonts()
        self.tasks = {t["id"]: t for t in m["tasks"]}
        self.err_ids = set(m["validation"].get("error_task_ids") or [])
        self.bottlenecks = store.top_bottlenecks(m["graph"])
        self.impact_dist: dict[str, int] = {}
        for b in self.bottlenecks:
            for x in core.downstream(m["tasks"], b):
                if x["status"] != "done":
                    self.impact_dist[x["id"]] = min(self.impact_dist.get(x["id"], 99), x["distance"])
        ana = m.get("analysis") or {}
        self.actions = [a.get("text", "") for a in (ana.get("pm") or {}).get("actions", [])][:3]
        self.qr_count = len((ana.get("quality") or {}).get("items") or [])
        self._layout()

    def _layout(self):
        self.pos, self.box_w, self.box_h = task_layout(list(self.tasks.values()))

    # ---------- drawing ----------

    def base(self, caption: str, sub: str = "", rev: int | None = None) -> tuple[Image.Image, ImageDraw.ImageDraw]:
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        head = f"TaMap ・ {self.m['title']}"
        d.text((24, 14), _fit(d, head, self.font(20), 640), font=self.font(20), fill=INK)
        rev = self.m["revision"] if rev is None else rev
        d.text((W - 24, 16), f"map_id {self.m['map_id']} ・ rev {rev}", font=self.font(15),
               fill=MUTED, anchor="ra")
        _pixel_box(d, (24, CAPTION_Y - 18, W - 24, CAPTION_Y + 18), (255, 255, 255), (148, 163, 184))
        d.text((40, CAPTION_Y), _fit(d, caption, self.font(18), W - 300), font=self.font(18), fill=INK, anchor="lm")
        if sub:
            d.text((W - 40, CAPTION_Y), sub, font=self.font(14), fill=MUTED, anchor="rm")
        return img, d

    def bots(self, d, state: dict[str, dict], badge: bool, speaker: tuple[str, str] | None, phase: int,
             blink: bool):
        y = LINK_Y
        for (_, _, xa), (_, _, xb) in zip(NODES, NODES[1:]):
            for x in range(xa + 50, xb - 50, 12):
                d.rectangle((x, y - 2, x + 5, y + 2), fill=(203, 213, 225))
        for key, label, x in NODES:
            if key == "user":
                _pixel_box(d, (x - 46, y - 24, x + 46, y + 24), (255, 255, 255), MUTED)
                _center(d, (x, y), label, self.font(16), INK)
                continue
            st = state.get(key, {}).get("status", "idle")
            p = persona.PERSONAS[key]
            bob = -SCALE if st == "working" and phase else 0
            sx, sy = x - 8 * SCALE, SPRITE_Y + bob
            if st == "working":
                d.rounded_rectangle(glow_box(key, x), radius=14,
                                    fill=(191, 219, 254), outline=(96, 165, 250), width=2)
            sprites.draw_bot(d, key, sx, sy, st, SCALE, blink=blink)
            if st == "working":
                sprites.draw_sparkle(d, x + 46 if phase else x - 60, SPRITE_Y + (4 if phase else 26), 3)
            elif st == "idle":
                d.text((x - 44, SPRITE_Y - 2), "zZ" if phase else "z", font=self.font(15), fill=MUTED)
            _center(d, (x, NAME_Y), label, self.font(16), INK)
            pill = f"{p['role']}・{BOT_STATUS_JA[st]}"
            pw = d.textlength(pill, font=self.font(13)) + 18
            d.rectangle((x - pw / 2, NAME_Y + 12, x + pw / 2, NAME_Y + 32), fill=BOT_FILL[st])
            _center(d, (x, NAME_Y + 22), pill, self.font(13), INK if st == "idle" else (255, 255, 255))
            if speaker and speaker[0] == key:
                self.bubble(d, x, speaker[1], p["color"])
            elif key == "quality_reviewer" and badge and self.qr_count:
                self.bubble(d, x, f"指摘{self.qr_count}件 → PMが修正", (217, 119, 6), fill=(254, 243, 199))

    def bubble(self, d, x: int, text: str, edge, fill=(255, 255, 255)):
        f = self.font(14)
        text = _fit(d, text, f, 250)
        bw = d.textlength(text, font=f) + 22
        x0 = min(max(x - bw / 2, 8), W - 8 - bw)
        _pixel_box(d, (x0, BUBBLE_Y - 14, x0 + bw, BUBBLE_Y + 14), fill, edge)
        for k in range(3):  # stepped pixel tail pointing at the speaker
            d.rectangle((x - 6 + k * 2, BUBBLE_Y + 14 + k * 3, x + 6 - k * 2, BUBBLE_Y + 17 + k * 3), fill=edge)
        d.text((x0 + bw / 2, BUBBLE_Y), text, font=f, fill=INK, anchor="mm")

    def envelope(self, d, a: str, b: str, t: float, color):
        xa, xb = NODE_X[a], NODE_X[b]
        x = xa + (xb - xa) * t
        y = LINK_Y - 6 - 44 * (4 * t * (1 - t))
        sprites.draw_envelope(d, x, y, color)

    def taskmap(self, d, impact_upto: int | None = None):
        for t in self.tasks.values():
            for dep in t["depends_on"]:
                if dep in self.pos and t["id"] in self.pos and dep != t["id"]:
                    (x1, y1), (x2, y2) = self.pos[dep], self.pos[t["id"]]
                    hot = (impact_upto is not None and t["id"] in self.impact_dist
                           and self.impact_dist[t["id"]] <= impact_upto
                           and (dep in self.bottlenecks or dep in self.impact_dist))
                    d.line((x1 + self.box_w / 2, y1, x2 - self.box_w / 2, y2),
                           fill=(202, 138, 4) if hot else (148, 163, 184), width=4 if hot else 2)
        f = self.font(14 if self.box_h >= 40 else 12)
        for tid, (x, y) in self.pos.items():
            t = self.tasks[tid]
            hit = impact_upto is not None and self.impact_dist.get(tid, 99) <= impact_upto
            fill = ERR if tid in self.err_ids else IMPACT if hit else TASK_FILL[t["status"]]
            bw, bh = self.box_w / 2, self.box_h / 2
            is_b = tid in self.bottlenecks
            d.rounded_rectangle((x - bw, y - bh, x + bw, y + bh), radius=8, fill=fill,
                                outline=(124, 45, 18) if is_b else (75, 85, 99), width=4 if is_b else 1)
            txt = INK if fill in (IMPACT, TASK_FILL["todo"]) else (255, 255, 255)
            line1 = _fit(d, f"{tid} {t['title']}", f, self.box_w - 12)
            line2 = core.STATUS_LABELS_JA[t["status"]] + (" ▲" if is_b else "")
            if self.box_h >= 34:
                _center(d, (x, y - 9), line1, f, txt)
                _center(d, (x, y + 10), line2, f, txt)
            else:
                _center(d, (x, y), line1, f, txt)

    def actions_panel(self, d):
        """Final card. It replaces the task map area (drawn instead of the map, never on top of it)."""
        x0, y0, x1, y1 = 24, TASKS_TOP - 6, W - 24, H - 14
        _pixel_box(d, (x0, y0, x1, y1), (255, 255, 255), (37, 99, 235))
        d.text((x0 + 20, y0 + 14), "次の3アクション" if self.actions else "結果", font=self.font(19),
               fill=(30, 64, 175))
        f = self.font(17)
        for i, a in enumerate(self.actions):
            d.text((x0 + 20, y0 + 52 + 34 * i), _fit(d, f"{i + 1}. {a}", f, x1 - x0 - 40), font=f, fill=INK)
        if self.bottlenecks:
            names = "・".join(self.bottlenecks)
            hit = "・".join(t for t in sorted(self.impact_dist, key=store._id_key))
            line = f"ボトルネック {names}" + (f" → 遅れると {hit} に影響" if hit else "")
            if self.qr_count:
                line += f" ／ 品質チェックの指摘{self.qr_count}件を反映済み"
            d.text((x0 + 20, y1 - 30), _fit(d, line, self.font(14), x1 - x0 - 40), font=self.font(14), fill=MUTED)

    # ---------- frames ----------

    def revision_at(self, iso: str | None) -> int:
        """Map revision in effect at a given time (from the revision history); latest if unknown."""
        if not iso:
            return self.m["revision"]
        revs = [h["revision"] for h in self.m.get("history") or [] if h.get("updated_at") and h["updated_at"] <= iso]
        return max(revs) if revs else min((h["revision"] for h in self.m.get("history") or []),
                                          default=self.m["revision"])

    def frames(self, events: list[dict]) -> tuple[list[Image.Image], list[int]]:
        imgs: list[Image.Image] = []
        durs: list[int] = []
        state: dict[str, dict] = {}
        flags = {"badge": False}

        def frame(caption, sub, speaker=None, env=None, impact=None, panel=False, ms=100, phase=0, blink=False,
                  rev=None):
            img, d = self.base(caption, sub, rev)
            self.bots(d, state, flags["badge"], speaker, phase, blink)
            if env:
                self.envelope(d, *env)
            if panel:
                self.actions_panel(d)
            else:
                self.taskmap(d, impact)
            # metadata for tests (not written to the GIF)
            img.info["tamap"] = {"caption": caption, "state": {k: v["status"] for k, v in state.items()},
                                 "rev": self.m["revision"] if rev is None else rev, "panel": panel,
                                 "taskmap": not panel}
            imgs.append(img)
            durs.append(ms)

        def hold(caption, sub, speaker=None, impact=None, panel=False, ms=1100, rev=None):
            frame(caption, sub, speaker, None, impact, panel, int(ms * 0.45), 0, rev=rev)
            frame(caption, sub, speaker, None, impact, panel, int(ms * 0.4), 1, rev=rev)
            frame(caption, sub, speaker, None, impact, panel, ms - int(ms * 0.45) - int(ms * 0.4), 0, True, rev=rev)

        first_rev = self.revision_at(events[0].get("at")) if events else None
        hold("PMに話しかけると、3体の専門Botが順に分析します", "", ("pm", "TaMap チーム、出動します！"), ms=1400,
             rev=first_rev)
        for i, ev in enumerate(events):
            bot, st = ev["bot"], ev["status"]
            rev = self.revision_at(ev.get("at"))
            name = store.BOT_NAMES[bot]
            note = f"：{ev['note']}" if ev.get("note") else ""
            caption = f"{name} {BOT_STATUS_JA[st]}{note}"
            sub = f"{hms(ev.get('at'))} JST ・ {i + 1}/{len(events)}"
            speaker = (bot, persona.line(bot, st, ev.get("say"), self.qr_count))
            # The caption always matches what the cards show: while a request is travelling the receiver
            # is not working yet (caption = the hand-off); a result travels after the sender is done.
            if bot == "pm" and st == "working" and i == 0:
                for k in range(1, 9):
                    frame("ユーザー → TaMap PM に依頼", sub, None, ("user", "pm", k / 9, REQUEST), rev=rev)
            elif bot != "pm" and st == "working":
                state["pm"] = {"status": "idle"}
                for k in range(1, 9):
                    frame(f"TaMap PM → {name} に依頼", sub, None, ("pm", bot, k / 9, REQUEST), rev=rev)
            elif bot != "pm" and st in ("done", "error"):
                state[bot] = {"status": st}
                for k in range(1, 9):
                    frame(caption, sub, None, (bot, "pm", k / 9, RESULT if st == "done" else ERR), rev=rev)
            state[bot] = {"status": st}
            if bot == "quality_reviewer" and st == "done":
                flags["badge"] = True
            hold(caption, sub, speaker, rev=rev)
        if self.bottlenecks:
            names = "・".join(self.bottlenecks)
            ra = ("risk_analyst", f"{names}、あやしいかも…")
            hold(f"ボトルネック {names}", "TaMap Core の計算", ra, impact=0, ms=1200)
            for k in range(1, max(self.impact_dist.values(), default=0) + 1):
                ids = "・".join(t for t, dd in self.impact_dist.items() if dd <= k)
                hold(f"{names} が遅れると {ids} に影響（{k}段先まで）", "TaMap Core の計算", ra, impact=k)
        final = max(self.impact_dist.values(), default=0) if self.bottlenecks else None
        hold("結果：次の3アクション" if self.actions else "結果", "", ("pm", persona.line("pm", "done")),
             impact=final, panel=True, ms=3500)
        return imgs, durs


def _pixel_box(d, box, fill, edge, step: int = 4):
    """Retro box: square corners notched by one pixel step, 2px border."""
    x0, y0, x1, y1 = box
    d.rectangle((x0 + step, y0, x1 - step, y1), fill=edge)
    d.rectangle((x0, y0 + step, x1, y1 - step), fill=edge)
    d.rectangle((x0 + step, y0 + 2, x1 - step, y1 - 2), fill=fill)
    d.rectangle((x0 + 2, y0 + step, x1 - 2, y1 - step), fill=fill)


def _save_gif(imgs: list[Image.Image], durs: list[int], path: Path) -> int:
    """Write the GIF; returns the stored frame count (Pillow merges identical consecutive frames)."""
    tmp = path.with_suffix(f".tmp-{os.getpid()}.gif")
    imgs[0].save(tmp, save_all=True, append_images=imgs[1:], duration=durs, loop=0, optimize=True)
    with Image.open(tmp) as g:
        n = g.n_frames
    os.replace(tmp, path)
    return n


def render_flow_gif(m: dict, out_dir: Path | None = None) -> dict:
    out_dir = Path(out_dir or OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    events = cycle_events(m.get("bot_history") or [])
    r = FlowRenderer(m)
    imgs, durs = r.frames(events)
    path = out_dir / f"{m['map_id']}_flow.gif"
    frames = _save_gif(imgs, durs, path)
    return {"path": str(path), "frames": frames, "duration_ms": sum(durs), "events": len(events),
            "font": r.font.path, "font_fallback": r.font.path is None}


def render_team_card(out_dir: Path | None = None) -> dict:
    """Team introduction GIF (out/tamap_team.gif): the 4 bots bobbing, each with role, motif and catchphrase."""
    out_dir = Path(out_dir or OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    font = Fonts()
    w, h, scale = 960, 400, 7
    keys = ["pm", "map_architect", "risk_analyst", "quality_reviewer"]
    imgs, durs = [], []
    for phase, blink, ms in ((0, False, 420), (1, False, 420), (0, False, 420), (1, False, 300), (0, True, 140)):
        img = Image.new("RGB", (w, h), BG)
        d = ImageDraw.Draw(img)
        d.text((w / 2, 30), "TaMap チーム", font=font(26), fill=INK, anchor="mm")
        d.text((w / 2, 62), "話しかけるのは PM だけ。3体の専門Botが順番に手伝います", font=font(15), fill=MUTED,
               anchor="mm")
        for i, key in enumerate(keys):
            p = persona.PERSONAS[key]
            cx = int(w / 8 + i * w / 4)
            bob = -scale if (phase + i) % 2 else 0
            _pixel_box(d, (cx - 110, 96, cx + 110, 384), (255, 255, 255), p["color"])
            sprites.draw_bot(d, key, cx - 8 * scale, 112 + bob, "working", scale, blink=blink)
            d.text((cx, 228), p["name"], font=font(18), fill=INK, anchor="mm")
            d.text((cx, 252), p["role"], font=font(15), fill=p["color"], anchor="mm")
            d.text((cx, 278), _fit(d, p["motif"], font(12), 200), font=font(12), fill=MUTED, anchor="mm")
            say = f"「{p['lines']['working']}」"
            _pixel_box(d, (cx - 100, 300, cx + 100, 336), (248, 250, 252), (203, 213, 225))
            d.text((cx, 318), _fit(d, say, font(14), 190), font=font(14), fill=INK, anchor="mm")
            for k, ln in enumerate(_wrap(d, p["trait"], font(12), 200, 2)):
                d.text((cx, 354 + 16 * k), ln, font=font(12), fill=MUTED, anchor="mm")
        imgs.append(img)
        durs.append(ms)
    path = out_dir / "tamap_team.gif"
    frames = _save_gif(imgs, durs, path)
    return {"path": str(path), "frames": frames, "duration_ms": sum(durs), "font": font.path,
            "font_fallback": font.path is None}
