"""Flow GIF: replay one PM → Map Architect → Risk Analyst → Quality Reviewer → PM cycle from bot_history.

render_flow_gif(map) writes out/<map_id>_flow.gif (TAMAP_OUT_DIR to override). Only the bot that is
working is lit; requests (blue envelope) and results (yellow envelope) travel between PM and the
specialist; the last frames spread the delay impact from the bottleneck over the task map and show
the PM's 3 actions plus the Quality Reviewer badge (count = analysis.quality.items).
"""
from __future__ import annotations

import os
import subprocess
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from . import core, store
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
BOT_Y = 130
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


def _fit(draw: ImageDraw.ImageDraw, text: str, font, width: int) -> str:
    if draw.textlength(text, font=font) <= width:
        return text
    while text and draw.textlength(text + "…", font=font) > width:
        text = text[:-1]
    return text + "…"


def _center(draw, xy, text, font, fill):
    draw.text(xy, text, font=font, fill=fill, anchor="mm")


def cycle_events(history: list[dict]) -> list[dict]:
    """The last PM-intake → ... cycle: from the last `pm working` before the last specialist `working`."""
    last_spec = max((i for i, h in enumerate(history) if h["bot"] != "pm" and h["status"] == "working"), default=None)
    if last_spec is None:
        return list(history)
    first_spec = last_spec
    while first_spec > 0 and not (history[first_spec - 1]["bot"] == "pm" and history[first_spec - 1]["status"] == "working"):
        first_spec -= 1
    start = max(first_spec - 1, 0)
    return list(history[start:])


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
        depth = _layers(list(self.tasks.values()))
        cols: dict[int, list[str]] = {}
        for tid in self.tasks:
            cols.setdefault(depth[tid], []).append(tid)
        ncol = max(len(cols), 1)
        top, bottom, left, right = 250, 500, 30, W - 30
        cw = (right - left) / ncol
        self.box_w = int(min(150, cw - 24))
        rows = max((len(v) for v in cols.values()), default=1)
        rh = (bottom - top) / rows
        self.box_h = int(min(52, rh - 10))
        self.pos: dict[str, tuple[int, int]] = {}
        for c, ids in sorted(cols.items()):
            x = int(left + cw * c + cw / 2)
            y0 = top + (bottom - top - rh * len(ids)) / 2
            for r, tid in enumerate(ids):
                self.pos[tid] = (x, int(y0 + rh * r + rh / 2))

    # ---------- drawing ----------

    def base(self, caption: str, sub: str = "") -> tuple[Image.Image, ImageDraw.ImageDraw]:
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        head = f"TaMap ・ {self.m['title']}"
        d.text((24, 16), _fit(d, head, self.font(20), 640), font=self.font(20), fill=INK)
        d.text((W - 24, 18), f"map_id {self.m['map_id']} ・ rev {self.m['revision']}", font=self.font(15),
               fill=MUTED, anchor="ra")
        d.rounded_rectangle((24, 196, W - 24, 236), radius=8, fill=(255, 255, 255), outline=(203, 213, 225))
        d.text((40, 216), _fit(d, caption, self.font(18), W - 300), font=self.font(18), fill=INK, anchor="lm")
        if sub:
            d.text((W - 40, 216), sub, font=self.font(14), fill=MUTED, anchor="rm")
        return img, d

    def bots(self, d, state: dict[str, dict], badge: bool):
        y = BOT_Y
        for (a, _, xa), (b, _, xb) in zip(NODES, NODES[1:]):
            d.line((xa + 70, y, xb - 70, y), fill=(203, 213, 225), width=3)
        for key, label, x in NODES:
            if key == "user":
                d.ellipse((x - 48, y - 30, x + 48, y + 30), fill=(255, 255, 255), outline=MUTED, width=2)
                _center(d, (x, y), label, self.font(16), INK)
                continue
            st = state.get(key, {}).get("status", "idle")
            fill = BOT_FILL[st]
            if st == "working":
                d.rounded_rectangle((x - 82, y - 46, x + 82, y + 46), radius=18, fill=(191, 219, 254))
            d.rounded_rectangle((x - 72, y - 36, x + 72, y + 36), radius=12, fill=fill,
                                outline=(30, 64, 175) if st == "working" else (75, 85, 99),
                                width=4 if st == "working" else 1)
            txt = (255, 255, 255) if st != "idle" else INK
            _center(d, (x, y - 12), label, self.font(16), txt)
            _center(d, (x, y + 12), BOT_STATUS_JA[st], self.font(15), txt)
            if key == "quality_reviewer" and badge and self.qr_count:
                bt = f"指摘{self.qr_count}件 → PMが修正"
                bw = d.textlength(bt, font=self.font(13)) + 16
                d.rounded_rectangle((x - bw / 2, y - 74, x + bw / 2, y - 50), radius=10, fill=(254, 243, 199),
                                    outline=(217, 119, 6))
                _center(d, (x, y - 62), bt, self.font(13), (120, 53, 15))

    def envelope(self, d, a: str, b: str, t: float, color):
        xa, xb = NODE_X[a], NODE_X[b]
        x = xa + (xb - xa) * t
        y = BOT_Y - 58 - 30 * (4 * t * (1 - t))
        d.rectangle((x - 16, y - 11, x + 16, y + 11), fill=color, outline=INK, width=1)
        d.line((x - 16, y - 11, x, y + 2, x + 16, y - 11), fill=INK, width=1)

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
        if not self.actions:
            return
        f = self.font(16)
        h = 44 + 28 * len(self.actions)
        x0, y0 = 300, H - 24 - h
        d.rounded_rectangle((x0, y0, W - 24, H - 24), radius=10, fill=(255, 255, 255), outline=(37, 99, 235), width=2)
        d.text((x0 + 16, y0 + 12), "次の3アクション", font=self.font(17), fill=(30, 64, 175))
        for i, a in enumerate(self.actions):
            d.text((x0 + 16, y0 + 40 + 28 * i), _fit(d, f"{i + 1}. {a}", f, W - x0 - 64), font=f, fill=INK)

    # ---------- frames ----------

    def frames(self, events: list[dict]) -> tuple[list[Image.Image], list[int]]:
        imgs: list[Image.Image] = []
        durs: list[int] = []

        def frame(caption, sub, state, env=None, badge=False, impact=None, panel=False, ms=100):
            img, d = self.base(caption, sub)
            self.bots(d, state, badge)
            if env:
                self.envelope(d, *env)
            self.taskmap(d, impact)
            if panel:
                self.actions_panel(d)
            imgs.append(img)
            durs.append(ms)

        state: dict[str, dict] = {}
        badge = False
        frame("PMに話しかけると、3体の専門Botが順に分析します", "", state, ms=1200)
        for i, ev in enumerate(events):
            bot, st = ev["bot"], ev["status"]
            if bot != "pm" and st == "working":
                state["pm"] = {"status": "idle"}
            name = store.BOT_NAMES[bot]
            note = f"：{ev['note']}" if ev.get("note") else ""
            caption = f"{name} {BOT_STATUS_JA[st]}{note}"
            sub = f"{hms(ev.get('at'))} JST ・ {i + 1}/{len(events)}"
            env = None
            if bot == "pm" and st == "working" and i == 0:
                env = ("user", "pm", REQUEST)
            elif bot != "pm" and st == "working":
                env = ("pm", bot, REQUEST)
            elif bot != "pm" and st in ("done", "error"):
                env = (bot, "pm", RESULT if st == "done" else ERR)
            if env:
                for k in range(1, 9):
                    frame(caption, sub, state, (env[0], env[1], k / 9, env[2]), badge)
            state[bot] = {"status": st}
            if bot == "quality_reviewer" and st == "done":
                badge = True
            frame(caption, sub, state, None, badge, ms=1100)
        if self.bottlenecks:
            names = "・".join(self.bottlenecks)
            frame(f"ボトルネック {names}", "TaMap Core の計算", state, None, badge, impact=0, ms=1200)
            for k in range(1, max(self.impact_dist.values(), default=0) + 1):
                ids = "・".join(t for t, dd in self.impact_dist.items() if dd <= k)
                frame(f"{names} が遅れると {ids} に影響（{k}段先まで）", "TaMap Core の計算", state, None, badge,
                      impact=k, ms=1100)
        final = max(self.impact_dist.values(), default=0) if self.bottlenecks else None
        frame("結果：次の3アクション" if self.actions else "結果", "", state, None, badge, impact=final,
              panel=True, ms=3500)
        return imgs, durs


def render_flow_gif(m: dict, out_dir: Path | None = None) -> dict:
    out_dir = Path(out_dir or OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    events = cycle_events(m.get("bot_history") or [])
    r = FlowRenderer(m)
    imgs, durs = r.frames(events)
    path = out_dir / f"{m['map_id']}_flow.gif"
    tmp = path.with_suffix(f".tmp-{os.getpid()}.gif")
    imgs[0].save(tmp, save_all=True, append_images=imgs[1:], duration=durs, loop=0, optimize=True)
    os.replace(tmp, path)
    return {"path": str(path), "frames": len(imgs), "duration_ms": sum(durs), "events": len(events),
            "font": r.font.path, "font_fallback": r.font.path is None}
