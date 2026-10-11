"""Flow GIF: replay one PM → Map Architect → Risk Analyst → Quality Reviewer → PM cycle from bot_history.

render_flow_gif(map) writes out/<map_id>_flow.gif (TAMAP_OUT_DIR to override). The bots are retro
pixel characters (sprites.py / persona.py): only the working bot is lit and bobs, idle bots are faded
and doze, each status change gets a speech bubble in the bot's own voice (`say` or the persona line).
Requests (blue envelope) and results (yellow envelope) travel between PM and the specialist; the last
frames spread the delay impact from the bottleneck over the task map (no action list: bots show the AI analysis,
the task map shows the project progress) plus the Quality Reviewer badge (count = analysis.quality.items).
render_team_card() writes out/tamap_team.gif, a team introduction for the PM's greeting.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import core, layout, persona, sprites, store
from .render import hms

OUT_DIR = Path(os.environ.get("TAMAP_OUT_DIR", store.ROOT / "out"))
W, H = 960, 540
BG = (248, 250, 252)
INK = (17, 24, 39)
MUTED = (100, 116, 139)
BOT_FILL = persona.BOT_COLORS
TASK_FILL = persona.TASK_COLORS
IMPACT = persona.TASK_IMPACT
ERR = persona.TASK_ERR
BOT_ERR = persona.BOT_COLORS["error"]
REQUEST, RESULT = (37, 99, 235), (234, 179, 8)
BOT_STATUS_JA = persona.BOT_STATUS_JA  # 待機 / 分析中 / 分析完了 / エラー (the bots' analysis, not the tasks)
NODES = [("user", "ユーザー", 80), ("pm", "TaMap PM", 250), ("map_architect", "Map Architect", 455),
         ("risk_analyst", "Risk Analyst", 640), ("quality_reviewer", "Quality Reviewer", 825)]
NODE_X = {k: x for k, _, x in NODES}
SCALE = 6
BUBBLE_Y = 56
SPRITE_Y = 82
LINK_Y = SPRITE_Y + 7 * SCALE
NAME_Y = 182
CAPTION_Y = 240
TASKS_TOP, TASKS_BOTTOM = 272, 524
ALL_DONE_CAPTION = persona.ALL_DONE_CAPTION
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


def task_layout(tasks: list[dict]) -> tuple[dict[str, tuple[int, int]], int, int]:
    """Task box centres and box size on the 960x540 canvas (GIF and live page). See layout.py."""
    lay = map_layout(tasks)
    return lay["pos"], lay["box_w"], lay["box_h"]


def map_layout(tasks: list[dict], **opts) -> dict:
    """Shared task-map layout (positions + routed edges with arrowheads) for the GIF and the live page."""
    return layout.compute(tasks, area=(16, TASKS_TOP, W - 16, TASKS_BOTTOM), **opts)


EDGE = (148, 163, 184)
EDGE_DONE = (196, 205, 216)   # edges out of finished tasks fade back
EDGE_HOT = persona.TASK_EDGE_HOT


def task_label(task: dict, bottleneck: bool, box_h: int) -> tuple[str, str, int]:
    """Box text shared with the live page: (head line, title to wrap, max title lines).
    Tall boxes: "T10 未着手▲" then the title on up to 2 lines."""
    tid, title = task["id"], task["title"]
    st = core.STATUS_LABELS_JA.get(task["status"], task["status"]) + ("▲" if bottleneck else "")
    if box_h >= 46:
        return f"{tid} {st}", title, 2
    if box_h >= 34:
        return st, f"{tid} {title}", 1
    return "", f"{tid} {title}", 1


def impact_distances(m: dict) -> tuple[list[str], dict[str, int]]:
    """Top bottlenecks and, for each unfinished downstream task, its distance from them (1 = direct).
    The GIF and the live page paint these orange (IMPACT) and the edges between them dark orange."""
    bottlenecks = store.top_bottlenecks(m["graph"])
    dist: dict[str, int] = {}
    for b in bottlenecks:
        for x in core.downstream(m["tasks"], b):
            if x["status"] != "done":
                dist[x["id"]] = min(dist.get(x["id"], 99), x["distance"])
    return bottlenecks, dist


def impact_visible(bots: dict) -> bool:
    """Live page: show the delay impact once Risk Analyst has delivered (or the PM has answered)."""
    return any((bots.get(k) or {}).get("status") == "done" for k in ("risk_analyst", "pm"))


class FlowRenderer:
    def __init__(self, m: dict):
        self.m = m
        self.font = Fonts()
        self.tasks = {t["id"]: t for t in m["tasks"]}
        self.err_ids = set(m["validation"].get("error_task_ids") or [])
        self.bottlenecks, self.impact_dist = impact_distances(m)
        ana = m.get("analysis") or {}
        self.qr_count = len((ana.get("quality") or {}).get("items") or [])
        self._layout()

    def _layout(self):
        self.lay = map_layout(list(self.tasks.values()))
        self.pos, self.box_w, self.box_h = self.lay["pos"], self.lay["box_w"], self.lay["box_h"]

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
                                    fill=persona.BOT_GLOW[0], outline=persona.BOT_GLOW[1], width=2)
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
        for e in self.lay["edges"]:
            dep, tid = e["from"], e["to"]
            hot = (impact_upto is not None and tid in self.impact_dist
                   and self.impact_dist[tid] <= impact_upto
                   and (dep in self.bottlenecks or dep in self.impact_dist))
            col = EDGE_HOT if hot else EDGE_DONE if self.tasks[dep]["status"] == "done" else EDGE
            pts = [tuple(p) for p in e["points"]]
            d.line(pts[:-1], fill=col, width=4 if hot else 2, joint="curve")  # last point = arrow tip
            d.polygon([tuple(p) for p in e["arrow"]], fill=col)
        f = self.font(13 if self.box_h >= 52 else 12)
        lh = (13 if self.box_h >= 52 else 12) + 3
        for tid, (x, y) in self.pos.items():
            t = self.tasks[tid]
            hit = impact_upto is not None and self.impact_dist.get(tid, 99) <= impact_upto
            bw, bh = self.box_w / 2, self.box_h / 2
            is_b = tid in self.bottlenecks
            fill = ERR if tid in self.err_ids else IMPACT if hit else TASK_FILL.get(t["status"], TASK_FILL["todo"])
            d.rounded_rectangle((x - bw, y - bh, x + bw, y + bh), radius=8, fill=fill,
                                outline=(124, 45, 18) if is_b else (75, 85, 99), width=4 if is_b else 1)
            txt = INK if fill in (IMPACT, TASK_FILL["todo"]) else (255, 255, 255)
            head, body, nmax = task_label(t, is_b, self.box_h)
            lines = _wrap(d, body, f, self.box_w - 10, nmax)
            head = _fit(d, head, f, self.box_w - 8) if head else head
            if head and nmax == 2:
                lines = [head] + lines
            elif head:
                lines = lines + [head]
            y0 = y - lh * (len(lines) - 1) / 2
            for k, ln in enumerate(lines):
                _center(d, (x, y0 + lh * k), ln, f, txt)

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
            self.taskmap(d, impact)  # no action list at the end (the GIF shows the AI's analysis, not a TODO list)
            # metadata for tests (not written to the GIF)
            img.info["tamap"] = {"caption": caption, "state": {k: v["status"] for k, v in state.items()},
                                 "rev": self.m["revision"] if rev is None else rev, "panel": False,
                                 "taskmap": True}
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
                    frame(caption, sub, None, (bot, "pm", k / 9, RESULT if st == "done" else BOT_ERR), rev=rev)
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
        hold(ALL_DONE_CAPTION, "", ("pm", persona.line("pm", "done")), impact=final, ms=3500)
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
