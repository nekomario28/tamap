"""Read-only live page: the 4 pixel bots move with bot_history as it is recorded (exception to "chat only").

    scripts/live_view.sh [--host 127.0.0.1] [--port 8765]     →  http://127.0.0.1:8765/live/{map_id}

Standard library only (http.server + Server-Sent Events). The server never writes: it only reads
data/maps/{map_id}.json (store.read_map) and polls the file's stat to push a new snapshot when
set_bot_status / update_map replace it. Only GET and HEAD are accepted; every other method is 405.
Sprites, colours, layout and bot lines come from sprites.py / persona.py / animate.py, so the page
draws exactly the same pixels as the flow GIF. Set TAMAP_LIVE_TOKEN to require ?token=… on every page.
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import re
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, quote, urlsplit

from . import animate, core, persona, sprites, store
from .render import hms

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8765
POLL_SEC = 0.2
HEARTBEAT_SEC = 15
ROUTE = re.compile(r"^/(live|api/maps|events)/([^/]+)$")


def token() -> str | None:
    return os.environ.get("TAMAP_LIVE_TOKEN") or None


def base_url() -> str:
    env = os.environ.get("TAMAP_LIVE_BASE_URL")
    if env:
        return env.rstrip("/")
    host = os.environ.get("TAMAP_LIVE_HOST", DEFAULT_HOST)
    return f"http://{host}:{int(os.environ.get('TAMAP_LIVE_PORT', DEFAULT_PORT))}"


def live_url(map_id: str) -> str:
    t = token()
    return f"{base_url()}/live/{map_id}" + (f"?token={quote(t)}" if t else "")


LIVE_EVENTS = 40  # the page shows the last 8; extra ones only seed envelopes


def _hex(c) -> str:
    return "#%02x%02x%02x" % tuple(c)


def scene_spec() -> dict:
    """Everything the page needs to draw like the GIF: canvas layout, colours, resolved sprite pixels, lines."""
    spr = {}
    for key in persona.PERSONAS:
        spr[key] = {st: [[gx, gy, _hex(c)] for gx, gy, c in sprites.bot_pixels(key, st)] for st in store.BOT_STATUSES}
        spr[key]["working_blink"] = [[gx, gy, _hex(c)] for gx, gy, c in sprites.bot_pixels(key, "working", True)]
    a = animate
    return {
        "w": a.W, "h": a.H, "scale": a.SCALE, "bubble_y": a.BUBBLE_Y, "sprite_y": a.SPRITE_Y, "link_y": a.LINK_Y,
        "name_y": a.NAME_Y, "caption_y": a.CAPTION_Y, "nodes": [list(n) for n in a.NODES],
        "colors": {"bg": _hex(a.BG), "ink": _hex(a.INK), "muted": _hex(a.MUTED), "request": _hex(a.REQUEST),
                   "result": _hex(a.RESULT), "err": _hex(a.ERR), "impact": _hex(a.IMPACT),
                   "sprite_ink": _hex(sprites.INK), "sparkle": "#facc15"},
        "bot_fill": {k: _hex(v) for k, v in a.BOT_FILL.items()},
        "task_fill": {k: _hex(v) for k, v in a.TASK_FILL.items()},
        "status_ja": a.BOT_STATUS_JA, "task_status_ja": core.STATUS_LABELS_JA,
        "sprites": spr, "glow": {k: list(a.glow_box(k, 0)) for k in persona.PERSONAS}, "sparkle": [list(p) for p in sprites.SPARKLE], "envelope": sprites.ENVELOPE,
        "personas": {k: {"name": p["name"], "emoji": p["emoji"], "role": p["role"], "color": _hex(p["color"]),
                         "lines": p["lines"]} for k, p in persona.PERSONAS.items()},
    }


def snapshot(map_id: str) -> dict:
    m = store.read_map(map_id)
    ana = m.get("analysis") or {}
    qr = len((ana.get("quality") or {}).get("items") or [])
    bots = {k: {"status": "idle", **((m.get("bots") or {}).get(k) or {})} for k in store.BOT_KEYS}
    events = []
    for h in (m.get("bot_history") or [])[-LIVE_EVENTS:]:
        events.append({"at": h["at"], "time": hms(h["at"]), "bot": h["bot"], "status": h["status"],
                       "note": h.get("note"), "say": h.get("say"), "auto": bool(h.get("auto")),
                       "name": store.BOT_NAMES[h["bot"]], "status_ja": animate.BOT_STATUS_JA[h["status"]],
                       "line": persona.line(h["bot"], h["status"], h.get("say"), qr)})
    pos, bw, bh = animate.task_layout(m["tasks"])
    err_ids = set(m["validation"].get("error_task_ids") or [])
    bott = set(store.top_bottlenecks(m["graph"]))
    seen, tasks = set(), []
    for t in m["tasks"]:
        if t["id"] in seen:
            continue
        seen.add(t["id"])
        x, y = pos[t["id"]]
        tasks.append({"id": t["id"], "title": t["title"], "status": t["status"], "x": x, "y": y,
                      "error": t["id"] in err_ids, "bottleneck": t["id"] in bott})
    edges = sorted({(d, t["id"]) for t in m["tasks"] for d in t["depends_on"] if d in pos and d != t["id"]})
    return {"map_id": m["map_id"], "title": m["title"], "revision": m["revision"], "updated_at": m["updated_at"],
            "updated_time": hms(m["updated_at"]), "ok": m["validation"]["ok"],
            "error_count": len(m["validation"]["errors"]), "bots": bots, "events": events,
            "tasks": tasks, "edges": [list(e) for e in edges], "box_w": bw, "box_h": bh,
            "actions": [x.get("text", "") for x in (ana.get("pm") or {}).get("actions", [])][:3],
            "quality_count": qr}


class Handler(BaseHTTPRequestHandler):
    server_version = "TaMapLive/1"
    protocol_version = "HTTP/1.1"

    # ---------- read-only: everything except GET/HEAD is rejected ----------
    def _reject(self):
        self._send(HTTPStatus.METHOD_NOT_ALLOWED, b'{"error":"read-only"}', "application/json",
                   extra={"Allow": "GET, HEAD"})

    do_POST = do_PUT = do_DELETE = do_PATCH = do_OPTIONS = _reject

    def do_HEAD(self):
        self._route(head=True)

    def do_GET(self):
        self._route(head=False)

    def log_message(self, fmt, *args):  # one short line per request on stderr
        if getattr(self.server, "quiet", False):
            return
        sys.stderr.write("live: %s %s\n" % (self.address_string(), fmt % args))

    def _send(self, status, body: bytes, ctype: str, head: bool = False, extra: dict | None = None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy",
                         "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; "
                         "connect-src 'self'; img-src 'self' data:")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if not head:
            self.wfile.write(body)

    def _json(self, data, status=HTTPStatus.OK, head=False):
        self._send(status, json.dumps(data, ensure_ascii=False).encode(), "application/json; charset=utf-8", head)

    def _route(self, head: bool):
        url = urlsplit(self.path)
        qs = parse_qs(url.query)
        if url.path == "/healthz":
            return self._json({"ok": True, "read_only": True}, head=head)
        if url.path == "/favicon.ico":
            return self._send(HTTPStatus.NO_CONTENT, b"", "image/x-icon", head)
        t = token()
        if t and not hmac.compare_digest((qs.get("token") or [""])[0], t):
            return self._json({"error": "token required"}, HTTPStatus.FORBIDDEN, head)
        tq = f"?token={quote(t)}" if t else ""
        if url.path in ("/", "/live", "/live/"):
            items = "".join(f'<li><a href="/live/{x["map_id"]}{tq}">{_esc(x["title"])}</a> '
                            f'<code>{x["map_id"]}</code> rev {x["revision"]}</li>' for x in store.list_maps())
            body = INDEX.replace("__ITEMS__", items or "<li>保存されたマップはありません</li>")
            return self._send(HTTPStatus.OK, body.encode(), "text/html; charset=utf-8", head)
        if url.path == "/api/scene":
            return self._json(scene_spec(), head=head)
        m = ROUTE.match(url.path)
        if not m:
            return self._json({"error": "not found"}, HTTPStatus.NOT_FOUND, head)
        kind, map_id = m.groups()
        try:
            snap = snapshot(map_id)
        except store.StoreError as e:
            return self._json({"error": str(e)}, HTTPStatus.NOT_FOUND, head)
        if kind == "live":
            body = PAGE.replace("__MAP_ID__", json.dumps(map_id)).replace("__TOKEN_QS__", json.dumps(tq)) \
                       .replace("__TITLE__", _esc(snap["title"]))
            return self._send(HTTPStatus.OK, body.encode(), "text/html; charset=utf-8", head)
        if kind == "api/maps":
            return self._json(snap, head=head)
        if head:
            return self._send(HTTPStatus.OK, b"", "text/event-stream", True)
        self._events(map_id)

    def _events(self, map_id: str):
        path = store._path(map_id)
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Accel-Buffering", "no")
        self.send_header("Connection", "close")
        self.end_headers()
        self.close_connection = True
        last_sig, last_write = None, 0.0
        stop: threading.Event = getattr(self.server, "stopping", threading.Event())
        try:
            self.wfile.write(b"retry: 2000\n\n")
            while not stop.is_set():
                try:
                    st = path.stat()
                    sig = (st.st_mtime_ns, st.st_size, st.st_ino)
                except FileNotFoundError:
                    sig = None
                if sig != last_sig and sig is not None:
                    try:
                        data = json.dumps(snapshot(map_id), ensure_ascii=False)
                    except (store.StoreError, ValueError):
                        time.sleep(POLL_SEC)
                        continue
                    last_sig = sig
                    self.wfile.write(f"event: snapshot\ndata: {data}\n\n".encode())
                    self.wfile.flush()
                    last_write = time.monotonic()
                elif time.monotonic() - last_write > HEARTBEAT_SEC:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    last_write = time.monotonic()
                time.sleep(POLL_SEC)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return


def _esc(s: str) -> str:
    return (str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;"))


def make_server(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT, quiet: bool = False) -> ThreadingHTTPServer:
    srv = ThreadingHTTPServer((host, port), Handler)
    srv.daemon_threads = True
    srv.quiet = quiet
    srv.stopping = threading.Event()
    return srv


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="TaMap read-only live page")
    ap.add_argument("--host", default=os.environ.get("TAMAP_LIVE_HOST", DEFAULT_HOST))
    ap.add_argument("--port", type=int, default=int(os.environ.get("TAMAP_LIVE_PORT", DEFAULT_PORT)))
    args = ap.parse_args(argv)
    srv = make_server(args.host, args.port)
    host, port = srv.server_address[:2]
    print(f"TaMap live (read-only): http://{host}:{port}/live/<map_id>  data={store.DATA_DIR}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.stopping.set()
        srv.server_close()


INDEX = """<!doctype html><html lang="ja"><meta charset="utf-8"><title>TaMap live</title>
<style>body{font-family:sans-serif;background:#f8fafc;color:#111827;margin:2rem}code{color:#64748b}</style>
<h1>TaMap live（閲覧専用）</h1><ul>__ITEMS__</ul></html>"""

PAGE = r"""<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TaMap live ・ __TITLE__</title>
<style>
 body{margin:0;background:#e2e8f0;font-family:"Noto Sans CJK JP","Hiragino Sans","WenQuanYi Micro Hei",sans-serif;color:#111827}
 main{max-width:960px;margin:16px auto;padding:0 8px}
 canvas{display:block;width:100%;max-width:960px;aspect-ratio:16/9;image-rendering:pixelated;background:#f8fafc;
        border:4px solid #334155;box-shadow:6px 6px 0 #94a3b8}
 .bar{display:flex;gap:12px;align-items:center;font-size:14px;margin:8px 0;color:#334155}
 .dot{display:inline-block;width:10px;height:10px;background:#9ca3af;margin-right:4px}
 .live .dot{background:#22c55e} .lost .dot{background:#ef4444}
 .ro{margin-left:auto;padding:2px 8px;border:2px solid #334155;background:#fff}
 ul{font-size:13px;color:#334155;background:#fff;border:2px solid #cbd5e1;padding:8px 8px 8px 24px;margin:8px 0}
</style></head>
<body><main>
<div class="bar"><span id="conn"><span class="dot"></span><span id="connText">接続中…</span></span>
<span id="rev"></span><span class="ro">閲覧専用</span></div>
<canvas id="c" width="960" height="540" aria-label="TaMap のBotの動き"></canvas>
<ul id="hist"></ul>
<noscript>このページは JavaScript で描画します。</noscript>
</main>
<script>
"use strict";
const MAP_ID = __MAP_ID__, TQ = __TOKEN_QS__;
const FONT = '"Noto Sans CJK JP","Hiragino Sans","WenQuanYi Micro Hei",sans-serif';
const cv = document.getElementById("c"), ctx = cv.getContext("2d");
let S = null, snap = null, lastKey = null, envs = [];
const K = Math.max(1, Math.round(window.devicePixelRatio || 1));  // integer zoom keeps every sprite cell on whole pixels

function key(e) { return e ? [e.at, e.bot, e.status, e.note, e.say].join("|") : null; }
function font(px) { ctx.font = px + "px " + FONT; }
function fit(t, w) {
  t = String(t); if (ctx.measureText(t).width <= w) return t;
  while (t && ctx.measureText(t + "…").width > w) t = t.slice(0, -1);
  return t + "…";
}
function text(t, x, y, px, color, align) {
  font(px); ctx.fillStyle = color; ctx.textAlign = align || "center"; ctx.textBaseline = "middle"; ctx.fillText(t, x, y);
}
function rect(x0, y0, x1, y1, c) { ctx.fillStyle = c; ctx.fillRect(x0, y0, x1 - x0 + 1, y1 - y0 + 1); }
function pixelBox(x0, y0, x1, y1, fill, edge, step) {  // same notched box as animate._pixel_box
  step = step || 4; x0 = Math.round(x0); x1 = Math.round(x1);
  rect(x0 + step, y0, x1 - step, y1, edge); rect(x0, y0 + step, x1, y1 - step, edge);
  rect(x0 + step, y0 + 2, x1 - step, y1 - 2, fill); rect(x0 + 2, y0 + step, x1 - 2, y1 - step, fill);
}
function cells(list, x, y, s) { for (const [gx, gy, c] of list) { ctx.fillStyle = c; ctx.fillRect(x + gx * s, y + gy * s, s, s); } }
function roundRect(x0, y0, x1, y1, r, fill, stroke, lw) {
  ctx.beginPath(); ctx.roundRect(x0, y0, x1 - x0, y1 - y0, r);
  if (fill) { ctx.fillStyle = fill; ctx.fill(); }
  if (stroke) { ctx.strokeStyle = stroke; ctx.lineWidth = lw || 1; ctx.stroke(); }
}

function bubble(x, t, edge, fill) {
  font(14); t = fit(t, 250);
  const bw = ctx.measureText(t).width + 22, y = S.bubble_y;
  const x0 = Math.min(Math.max(x - bw / 2, 8), S.w - 8 - bw);
  pixelBox(x0, y - 14, x0 + bw, y + 14, fill || "#ffffff", edge);
  for (let k = 0; k < 3; k++) rect(x - 6 + k * 2, y + 14 + k * 3, x + 6 - k * 2, y + 17 + k * 3, edge);
  text(t, x0 + bw / 2, y, 14, S.colors.ink);
}

function envelope(a, b, t, color) {
  const xa = nodeX(a), xb = nodeX(b), s = 3, g = S.envelope;
  const cx = xa + (xb - xa) * t, cy = S.link_y - 6 - 44 * (4 * t * (1 - t));
  const x0 = Math.round(cx - g[0].length * s / 2), y0 = Math.round(cy - g.length * s / 2);
  for (let gy = 0; gy < g.length; gy++) for (let gx = 0; gx < g[gy].length; gx++) {
    ctx.fillStyle = g[gy][gx] === "D" ? S.colors.sprite_ink : color; ctx.fillRect(x0 + gx * s, y0 + gy * s, s, s);
  }
}
function nodeX(k) { for (const n of S.nodes) if (n[0] === k) return n[2]; return 0; }

function draw(now) {
  const C = S.colors, sc = S.scale;
  ctx.setTransform(K, 0, 0, K, 0, 0);
  rect(0, 0, S.w, S.h, C.bg);
  if (!snap) { text("読み込み中…", S.w / 2, S.h / 2, 18, C.muted); return; }
  const phase = Math.floor(now / 450) % 2, blink = now % 3200 < 160;
  font(20); ctx.textAlign = "left"; ctx.textBaseline = "top"; ctx.fillStyle = C.ink;
  ctx.fillText(fit("TaMap ・ " + snap.title, 640), 24, 14);
  text("map_id " + snap.map_id + " ・ rev " + snap.revision, S.w - 24, 24, 15, C.muted, "right");
  // links + bots
  const y = S.link_y;
  for (let i = 0; i + 1 < S.nodes.length; i++)
    for (let x = S.nodes[i][2] + 50; x < S.nodes[i + 1][2] - 50; x += 12) rect(x, y - 2, x + 5, y + 2, "#cbd5e1");
  const last = snap.events[snap.events.length - 1];
  for (const [k, label, x] of S.nodes) {
    if (k === "user") { pixelBox(x - 46, y - 24, x + 46, y + 24, "#ffffff", C.muted); text(label, x, y, 16, C.ink); continue; }
    const st = snap.bots[k].status, p = S.personas[k];
    const bob = st === "working" && phase ? -sc : 0;
    if (st === "working") { const g = S.glow[k]; roundRect(x + g[0], g[1], x + g[2], g[3], 14, "#bfdbfe", "#60a5fa", 2); }
    cells(st === "working" && blink ? S.sprites[k].working_blink : S.sprites[k][st], x - 8 * sc, S.sprite_y + bob, sc);
    if (st === "working") cells(S.sparkle.map(([gx, gy]) => [gx, gy, C.sparkle]), phase ? x + 46 : x - 60, S.sprite_y + (phase ? 4 : 26), 3);
    else if (st === "idle") text(phase ? "zZ" : "z", x - 40, S.sprite_y + 6, 15, C.muted, "left");
    text(label, x, S.name_y, 16, C.ink);
    font(13); const pill = p.role + "・" + S.status_ja[st], pw = ctx.measureText(pill).width + 18;
    rect(Math.round(x - pw / 2), S.name_y + 12, Math.round(x + pw / 2), S.name_y + 32, S.bot_fill[st]);
    text(pill, x, S.name_y + 22, 13, st === "idle" ? C.ink : "#ffffff");
    if (last && last.bot === k) bubble(x, last.line, p.color);
    else if (k === "quality_reviewer" && snap.quality_count && st === "done")
      bubble(x, "指摘" + snap.quality_count + "件 → PMが修正", "#d97706", "#fef3c7");
  }
  for (const e of envs) {
    const t = (now - e.start) / 900;
    if (t >= 0 && t <= 1) envelope(e.a, e.b, t, e.color);
  }
  envs = envs.filter(e => now - e.start <= 900);
  // caption
  const cy = S.caption_y;
  pixelBox(24, cy - 18, S.w - 24, cy + 18, "#ffffff", "#94a3b8");
  const cap = last ? last.name + " " + last.status_ja + (last.note ? "：" + last.note : "") : "まだBotの記録はありません";
  font(18); ctx.textAlign = "left"; ctx.textBaseline = "middle"; ctx.fillStyle = C.ink; ctx.fillText(fit(cap, S.w - 300), 40, cy);
  text((last ? last.time + " JST ・ " : "") + "ライブ", S.w - 40, cy, 14, C.muted, "right");
  // task map
  const bw = snap.box_w / 2, bh = snap.box_h / 2, pos = {};
  for (const t of snap.tasks) pos[t.id] = t;
  ctx.lineWidth = 2; ctx.strokeStyle = "#94a3b8";
  for (const [a, b] of snap.edges) {
    ctx.beginPath(); ctx.moveTo(pos[a].x + bw, pos[a].y); ctx.lineTo(pos[b].x - bw, pos[b].y); ctx.stroke();
  }
  const fs = snap.box_h >= 40 ? 14 : 12;
  for (const t of snap.tasks) {
    const fill = t.error ? C.err : S.task_fill[t.status];
    roundRect(t.x - bw, t.y - bh, t.x + bw, t.y + bh, 8, fill, t.bottleneck ? "#7c2d12" : "#4b5563", t.bottleneck ? 4 : 1);
    const tc = t.status === "todo" && !t.error ? C.ink : "#ffffff";
    font(fs); const l1 = fit(t.id + " " + t.title, snap.box_w - 12);
    const l2 = S.task_status_ja[t.status] + (t.bottleneck ? " ▲" : "");
    if (snap.box_h >= 34) { text(l1, t.x, t.y - 9, fs, tc); text(l2, t.x, t.y + 10, fs, tc); }
    else text(l1, t.x, t.y, fs, tc);
  }
}

function envelopesFor(e, bots) {
  if (e.bot !== "pm" && e.status === "working") return ["pm", e.bot, S.colors.request];
  if (e.bot !== "pm" && e.status === "done") return [e.bot, "pm", S.colors.result];
  if (e.bot !== "pm" && e.status === "error") return [e.bot, "pm", S.colors.err];
  const busy = ["map_architect", "risk_analyst", "quality_reviewer"].some(k => bots[k].status !== "idle");
  if (e.bot === "pm" && e.status === "working" && !busy) return ["user", "pm", S.colors.request];
  return null;
}

function apply(s) {
  const prev = snap; snap = s;
  document.getElementById("rev").textContent = "revision " + s.revision + " ・ 更新 " + s.updated_time + " JST";
  const evs = s.events, lastNew = key(evs[evs.length - 1]);
  if (prev && lastKey !== null && lastNew !== lastKey) {
    let i = evs.findIndex(e => key(e) === lastKey);
    const fresh = evs.slice(i + 1), t0 = performance.now();
    fresh.forEach((e, j) => { const env = envelopesFor(e, s.bots); if (env) envs.push({a: env[0], b: env[1], color: env[2], start: t0 + j * 300}); });
  }
  lastKey = lastNew;
  const ol = document.getElementById("hist"); ol.replaceChildren();
  for (const e of evs.slice(-8).reverse()) {
    const li = document.createElement("li");
    li.textContent = e.time + " " + S.personas[e.bot].emoji + " " + e.name + "：" + e.status_ja + (e.note ? "（" + e.note + "）" : "") + "「" + e.line + "」";
    ol.appendChild(li);
  }
  document.body.dataset.revision = s.revision;
  document.body.dataset.lastEvent = lastNew || "";
}

function conn(state, label) { const el = document.getElementById("conn"); el.className = state; document.getElementById("connText").textContent = label; }

async function start() {
  S = await (await fetch("/api/scene" + TQ)).json();
  cv.width = S.w * K; cv.height = S.h * K; ctx.imageSmoothingEnabled = false;
  const loop = now => { draw(now); requestAnimationFrame(loop); };
  requestAnimationFrame(loop);
  const es = new EventSource("/events/" + encodeURIComponent(MAP_ID) + TQ);
  es.addEventListener("snapshot", ev => { apply(JSON.parse(ev.data)); conn("live", "ライブ"); });
  es.onerror = () => conn("lost", "再接続中…");
}
start();
</script></body></html>
"""

if __name__ == "__main__":
    main()
