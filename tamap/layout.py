"""Task-map layout shared by the flow GIF (animate.py) and the live page (live.py).

Layered (Sugiyama-style) drawing, standard library only:
  1. columns = longest dependency path; tasks with no prerequisites are pulled right next to their
     first successor (so e.g. a slide task does not start at column 0 and draw a long line);
  2. edges that skip columns get dummy points, so they take a lane of their own instead of running
     through the boxes in between;
  3. order within a column: barycenter sweeps (down/up) + adjacent swaps, keeping the fewest crossings;
  4. vertical position: each item moves toward its neighbours (critical path weighted most, so it
     ends up as a straight row) while keeping its order and spacing (isotonic regression / PAVA);
  5. edges are horizontal-tangent cubic Béziers through the dummy lanes, sampled to polylines, with
     spread ports and an arrowhead at the target. Both renderers just draw these points.
"""
from __future__ import annotations

from collections import deque

SAMPLES = 14  # points per Bézier segment
ARROW = 9     # arrowhead length (px)


def _graph(tasks):
    ids: list[str] = []
    seen = set()
    for t in tasks:
        if t.get("id") is None or t["id"] in seen:
            continue
        seen.add(t["id"])
        ids.append(t["id"])
    first = {}
    for t in tasks:
        first.setdefault(t.get("id"), t)
    edges = []
    for tid in ids:
        for d in first[tid].get("depends_on") or []:
            if d in seen and d != tid and (d, tid) not in edges:
                edges.append((d, tid))
    return ids, edges


def layers(ids, edges, pull_sources=True) -> dict[str, int]:
    succ = {i: [] for i in ids}
    pred = {i: [] for i in ids}
    indeg = {i: 0 for i in ids}
    for a, b in edges:
        succ[a].append(b)
        pred[b].append(a)
        indeg[b] += 1
    depth: dict[str, int] = {}
    q = deque(i for i in ids if indeg[i] == 0)
    for i in q:
        depth[i] = 0
    while q:
        v = q.popleft()
        for w in succ[v]:
            depth[w] = max(depth.get(w, 0), depth[v] + 1)
            indeg[w] -= 1
            if indeg[w] == 0:
                q.append(w)
    nxt = max(depth.values(), default=-1) + 1
    for i in ids:  # tasks on a cycle: after everything else
        if i not in depth:
            depth[i] = nxt
    if pull_sources:
        for i in ids:
            if not pred[i] and succ[i]:
                fwd = [depth[w] for w in succ[i] if depth[w] > depth[i]]
                if fwd:
                    depth[i] = max(depth[i], min(fwd) - 1)
    return depth


def _crossings_between(upper, lower, links):
    """Crossings between two adjacent columns. links: list of (index_in_upper, index_in_lower)."""
    n = 0
    for i in range(len(links)):
        a1, b1 = links[i]
        for j in range(i + 1, len(links)):
            a2, b2 = links[j]
            if (a1 - a2) * (b1 - b2) < 0:
                n += 1
    return n


def _pava(target, weight):
    """Non-decreasing weighted least squares fit (pool adjacent violators)."""
    blocks = []  # [value, weight, count]
    for t, w in zip(target, weight):
        blocks.append([t, w, 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            v2, w2, c2 = blocks.pop()
            v1, w1, c1 = blocks.pop()
            blocks.append([(v1 * w1 + v2 * w2) / (w1 + w2), w1 + w2, c1 + c2])
    out = []
    for v, _, c in blocks:
        out += [v] * c
    return out


def _bezier(p0, p1, n=SAMPLES):
    (x0, y0), (x1, y1) = p0, p1
    mx = (x1 - x0) / 2
    c0, c1 = (x0 + mx, y0), (x1 - mx, y1)
    pts = []
    for k in range(1, n + 1):
        t = k / n
        u = 1 - t
        pts.append((u ** 3 * x0 + 3 * u * u * t * c0[0] + 3 * u * t * t * c1[0] + t ** 3 * x1,
                    u ** 3 * y0 + 3 * u * u * t * c0[1] + 3 * u * t * t * c1[1] + t ** 3 * y1))
    return pts


def compute(tasks, area=(16, 270, 944, 522), max_box_w=150, max_box_h=56, *, dummies=True,
            pull_sources=True, order=True, align=True, curves=True, ports=True) -> dict:
    """Layout for the task map. Returns pos {id: (x, y)}, box_w, box_h and edges
    [{"from", "to", "points": [[x, y], ...], "arrow": [[x, y] x3] | None, "back": bool}]."""
    left, top, right, bottom = area
    ids, edges = _graph(tasks)
    if not ids:
        return {"pos": {}, "box_w": max_box_w, "box_h": max_box_h, "edges": []}
    depth = layers(ids, edges, pull_sources)
    ncol = max(depth.values()) + 1
    # ---- items per column (real tasks + dummy points of long edges) ----
    cols: list[list[str]] = [[] for _ in range(ncol)]
    for i in ids:
        cols[depth[i]].append(i)
    is_dummy: dict[str, bool] = {i: False for i in ids}
    chains: dict[tuple, list[str]] = {}
    links: list[tuple[str, str, float]] = []  # adjacent-column links (u, v, weight)
    crit = _critical(ids, edges, depth, tasks)
    for a, b in edges:
        if depth[b] <= depth[a]:
            chains[(a, b)] = [a, b]  # back / same-column edge (cycle): drawn but not laid out
            continue
        chain = [a]
        if dummies:
            for c in range(depth[a] + 1, depth[b]):
                dn = f"\0{a}\0{b}\0{c}"
                is_dummy[dn] = False or True
                cols[c].append(dn)
                chain.append(dn)
        chain.append(b)
        chains[(a, b)] = chain
        w = 20.0 if (a, b) in crit else (2.0 if len(chain) > 2 else 1.0)
        for u, v in zip(chain, chain[1:]):
            if depth.get(v, None) is None or True:
                links.append((u, v, w))
    col_of = {}
    for c, items in enumerate(cols):
        for it in items:
            col_of[it] = c
    adj_links = [(u, v, w) for u, v, w in links if col_of[v] == col_of[u] + 1]
    nbr_dn = {it: [] for c in cols for it in c}
    nbr_up = {it: [] for c in cols for it in c}
    for u, v, w in adj_links:
        nbr_dn[u].append((v, w))
        nbr_up[v].append((u, w))

    by_col: dict[int, list] = {}
    for u, v, w in adj_links:
        by_col.setdefault(col_of[u], []).append((u, v))

    def pair_cross(cs, c):
        if c < 0 or c >= len(cs) - 1:
            return 0
        iu = {it: k for k, it in enumerate(cs[c])}
        iv = {it: k for k, it in enumerate(cs[c + 1])}
        return _crossings_between(None, None, [(iu[u], iv[v]) for u, v in by_col.get(c, [])])

    def total_cross(cs):
        idx = {it: k for c in cs for k, it in enumerate(c)}
        n = 0
        for c in range(len(cs) - 1):
            ls = [(idx[u], idx[v]) for u, v, _ in adj_links if col_of[u] == c]
            n += _crossings_between(cs[c], cs[c + 1], ls)
        return n

    if order:
        best = [list(c) for c in cols]
        best_n = total_cross(best)
        cur = [list(c) for c in cols]
        sweeps = 12 if len(col_of) <= 80 else 4
        for it_n in range(sweeps):
            down = it_n % 2 == 0
            rng = range(1, ncol) if down else range(ncol - 2, -1, -1)
            for c in rng:
                ref = cur[c - 1] if down else cur[c + 1]
                ridx = {it: k for k, it in enumerate(ref)}
                nb = nbr_up if down else nbr_dn
                old = {it: k for k, it in enumerate(cur[c])}

                def bc(it):
                    ns = [ridx[n] for n, _ in nb[it] if n in ridx]
                    return sum(ns) / len(ns) if ns else old[it]
                cur[c].sort(key=lambda it: (bc(it), old[it]))
            # adjacent swaps
            improved = True
            while improved:
                improved = False
                for c in range(ncol):
                    for k in range(len(cur[c]) - 1):
                        before = pair_cross(cur, c - 1) + pair_cross(cur, c)
                        cur[c][k], cur[c][k + 1] = cur[c][k + 1], cur[c][k]
                        if pair_cross(cur, c - 1) + pair_cross(cur, c) < before:
                            improved = True
                        else:
                            cur[c][k], cur[c][k + 1] = cur[c][k + 1], cur[c][k]
            n = total_cross(cur)
            if n < best_n:
                best, best_n = [list(c) for c in cur], n
        cols = best
    # ---- vertical positions in abstract units (task-task gap 1.0) ----
    def sep(a, b):
        da, db = is_dummy[a], is_dummy[b]
        return 0.36 if da and db else (0.66 if da or db else 1.0)

    y: dict[str, float] = {}
    for c in cols:
        acc = 0.0
        for k, it in enumerate(c):
            if k:
                acc += sep(c[k - 1], it)
            y[it] = acc
        off = acc / 2
        for it in c:
            y[it] -= off
    if align:
        for _ in range(60):
            for c in (list(range(ncol)) + list(range(ncol - 1, -1, -1))):
                items = cols[c]
                if not items:
                    continue
                tgt, wts = [], []
                for it in items:
                    ns = nbr_up[it] + nbr_dn[it]
                    sw = sum(w for _, w in ns)
                    tgt.append(sum(y[n] * w for n, w in ns) / sw if sw else y[it])
                    wts.append(sw + 0.05)
                offs = [0.0]
                for k in range(1, len(items)):
                    offs.append(offs[-1] + sep(items[k - 1], items[k]))
                z = _pava([t - o for t, o in zip(tgt, offs)], wts)
                for it, zz, o in zip(items, z, offs):
                    y[it] = zz + o
        # snap near-equal rows so straight chains are pixel-straight (critical path first)
        def fits(it, val):
            c = cols[col_of[it]]
            k = c.index(it)
            return ((k == 0 or val - y[c[k - 1]] >= sep(c[k - 1], it) - 1e-6)
                    and (k == len(c) - 1 or y[c[k + 1]] - val >= sep(it, c[k + 1]) - 1e-6))
        crit_nodes = [i for e in crit for i in e]
        if crit_nodes:
            ys = sorted(y[i] for i in crit_nodes)
            cy = ys[len(ys) // 2]
            for i in crit_nodes:
                if abs(y[i] - cy) < 0.3:
                    if fits(i, cy):
                        y[i] = cy
                    else:  # move the whole column with it (keeps its spacing)
                        dlt = cy - y[i]
                        for it in cols[col_of[i]]:
                            y[it] += dlt
        for _ in range(3):
            for u, v, _w in adj_links:
                if abs(y[u] - y[v]) < 0.2 and y[u] != y[v]:
                    a, b = (v, u) if (u, v) in crit or u in crit_nodes else (u, v)
                    if fits(a, y[b]):
                        y[a] = y[b]
    lo = min(y.values())
    hi = max(y.values())
    span = hi - lo
    avail = bottom - top
    unit = min(max_box_h + 16, avail / (span + 1)) if span > 0 else max_box_h + 16
    box_h = int(max(8, min(max_box_h, unit - 10)))
    used = span * unit
    y0 = top + (avail - used) / 2 - lo * unit
    cw = (right - left) / ncol
    box_w = int(max(40, min(max_box_w, cw - 26)))
    px = {it: (left + cw * col_of[it] + cw / 2, y0 + y[it] * unit) for it in y}
    pos = {i: (int(round(px[i][0])), int(round(px[i][1]))) for i in ids}
    bw, bh = box_w / 2, box_h / 2
    # ---- ports: spread the ends of edges sharing a side of a box ----
    out_off, in_off = {}, {}
    if ports:
        for i in ids:
            for key, store_, idx in (("out", out_off, 1), ("in", in_off, 0)):
                es = [e for e in chains if e[1 - idx] == i and len(chains[e]) >= 2]
                nb = lambda e: px[chains[e][1]][1] if idx == 1 else px[chains[e][-2]][1]  # noqa: E731
                es.sort(key=nb)
                step = min(10.0, (box_h - 12) / max(len(es) - 1, 1)) if len(es) > 1 else 0
                for k, e in enumerate(es):
                    store_[e] = (k - (len(es) - 1) / 2) * step
    out_edges = []
    for (a, b), chain in chains.items():
        back = depth[b] <= depth[a]
        (xa, ya), (xb, yb) = pos[a], pos[b]
        start = (xa + bw, ya + out_off.get((a, b), 0))
        end_tip = (xb - bw, yb + in_off.get((a, b), 0))
        end = (end_tip[0] - ARROW, end_tip[1])
        if back:
            pts = [start, ((start[0] + end[0]) / 2, max(start[1], end[1]) + bh + 14), end]
            poly = [start]
            for p, q in zip(pts, pts[1:]):
                poly.append(q)
        else:
            way = [start]
            for dn in chain[1:-1]:
                dx, dy = px[dn]
                way += [(dx - bw, dy), (dx + bw, dy)]
            way.append(end)
            poly = [start]
            for k, (p, q) in enumerate(zip(way, way[1:])):
                if k % 2 == 1:  # straight lane through a dummy column
                    poly.append(q)
                elif curves:
                    poly += _bezier(p, q)
                else:
                    poly.append(q)
        poly.append(end_tip)
        tip = end_tip
        arrow = [[tip[0], tip[1]], [tip[0] - ARROW, tip[1] - 5], [tip[0] - ARROW, tip[1] + 5]]
        out_edges.append({"from": a, "to": b, "back": back,
                          "points": [[round(x, 1), round(yy, 1)] for x, yy in poly], "arrow": arrow})
    return {"pos": pos, "box_w": box_w, "box_h": box_h, "edges": out_edges}


def _critical(ids, edges, depth, tasks=None) -> set:
    """Edges of the critical path (core.critical_path_candidates, the one the mermaid/analysis shows)
    — drawn as a straight row. Falls back to the longest chain for odd data."""
    if tasks is not None:
        try:
            from . import core
            first = {}
            for t in tasks:
                first.setdefault(t["id"], t)
            clean = [dict(first[i], depends_on=[d for d in (first[i].get("depends_on") or []) if d in first])
                     for i in ids]
            cands = core.critical_path_candidates(clean)
            if cands:
                path = cands[0]["path"]
                es = set(zip(path, path[1:]))
                if es and all(depth[b] > depth[a] for a, b in es):
                    return es
        except Exception:  # noqa: BLE001 - layout must never fail on bad data
            pass
    succ = {i: [] for i in ids}
    for a, b in edges:
        if depth[b] > depth[a]:
            succ[a].append(b)
    memo: dict[str, int] = {}

    def longest(v, stack=()):
        if v in memo:
            return memo[v]
        memo[v] = 1 + max((longest(w) for w in succ[v]), default=0)
        return memo[v]
    if not ids:
        return set()
    start = max(ids, key=lambda i: (longest(i), -ids.index(i)))
    out, v = set(), start
    while succ[v]:
        w = max(succ[v], key=lambda x: (longest(x), -ids.index(x)))
        out.add((v, w))
        v = w
    return out


# ---------------- metrics (tests and the comparison script) ----------------

def _seg_cross(p1, p2, p3, p4) -> bool:
    def ccw(a, b, c):
        return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
    d1, d2, d3, d4 = ccw(p3, p4, p1), ccw(p3, p4, p2), ccw(p1, p2, p3), ccw(p1, p2, p4)
    return d1 * d2 < 0 and d3 * d4 < 0


def count_crossings(lay: dict) -> int:
    """Pairs of edges (not sharing a task) whose drawn lines cross."""
    es = lay["edges"]
    n = 0
    for i in range(len(es)):
        for j in range(i + 1, len(es)):
            a, b = es[i], es[j]
            if {a["from"], a["to"]} & {b["from"], b["to"]}:
                continue
            pa, pb = a["points"], b["points"]
            if any(_seg_cross(pa[k], pa[k + 1], pb[m], pb[m + 1])
                   for k in range(len(pa) - 1) for m in range(len(pb) - 1)):
                n += 1
    return n


def _seg_hits_box(p, q, box) -> bool:
    x0, y0, x1, y1 = box
    for k in range(21):
        t = k / 20
        x, y = p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t
        if x0 < x < x1 and y0 < y < y1:
            return True
    return False


def count_node_hits(lay: dict, pad: float = 1.0) -> int:
    """Edges whose line passes through a task box other than its own two ends."""
    bw, bh = lay["box_w"] / 2 - pad, lay["box_h"] / 2 - pad
    n = 0
    for e in lay["edges"]:
        pts = e["points"]
        for tid, (x, y) in lay["pos"].items():
            if tid in (e["from"], e["to"]):
                continue
            box = (x - bw, y - bh, x + bw, y + bh)
            if any(_seg_hits_box(pts[k], pts[k + 1], box) for k in range(len(pts) - 1)):
                n += 1
                break
    return n


def count_overlaps(lay: dict, tol: float = 2.5) -> int:
    """Pairs of edges that run on top of each other (many sampled points within tol px)."""
    es = lay["edges"]
    n = 0
    for i in range(len(es)):
        for j in range(i + 1, len(es)):
            a, b = es[i]["points"], es[j]["points"]
            close = sum(1 for p in a[1:-1] if any(abs(p[0] - q[0]) <= tol and abs(p[1] - q[1]) <= tol for q in b))
            if close >= 4:
                n += 1
    return n
