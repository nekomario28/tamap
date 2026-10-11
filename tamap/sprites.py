"""Retro pixel-art sprites of the 4 TaMap bots (16x14 grid + accessories), drawn with Pillow.

Same round robot body for everyone; the bot is told apart by its colour and motif (persona.py), and
its state by the face: idle = sleepy, working = sparkly eyes, done = ^ ^, error = > < with a sweat drop.
"""
from __future__ import annotations

from PIL import ImageDraw

from .persona import PERSONAS

BODY = [
    "................",
    "................",
    ".......DD.......",
    "....DDDDDDDD....",
    "...DLBBBBBBBD...",
    "..DLBWWWWWWBBD..",
    "..DBWWWWWWWWBD..",
    "..DBWWWWWWWWBD..",
    "..DBWWWWWWWWBD..",
    "..DBBWWWWWWBBD..",
    "...DBBBBBBBBD...",
    "....DDBBBBDD....",
    ".....DB..BD.....",
    ".....DD..DD.....",
]

INK = (31, 41, 55)
WHITE = (255, 255, 255)
FACE = (241, 245, 249)
BLUSH = (251, 113, 133)
SWEAT = (125, 211, 252)
GREY = (156, 163, 175)

FACES = {
    "working": [(5, 6, "K"), (6, 6, "K"), (5, 7, "K"), (6, 7, "K"), (9, 6, "K"), (10, 6, "K"), (9, 7, "K"),
                (10, 7, "K"), (5, 6, "H"), (9, 6, "H"), (7, 8, "K"), (8, 8, "K"), (4, 8, "P"), (11, 8, "P")],
    "idle": [(5, 7, "K"), (6, 7, "K"), (9, 7, "K"), (10, 7, "K"), (7, 8, "K"), (8, 8, "K")],
    "done": [(4, 7, "K"), (5, 6, "K"), (6, 7, "K"), (9, 7, "K"), (10, 6, "K"), (11, 7, "K"),
             (6, 8, "K"), (7, 9, "K"), (8, 9, "K"), (9, 8, "K"), (4, 8, "P"), (11, 8, "P")],
    "error": [(5, 6, "K"), (6, 7, "K"), (5, 8, "K"), (10, 6, "K"), (9, 7, "K"), (10, 8, "K"),
              (7, 9, "K"), (8, 9, "K"), (13, 3, "S"), (13, 4, "S"), (14, 4, "S")],
}
BLINK = [(5, 7, "K"), (6, 7, "K"), (9, 7, "K"), (10, 7, "K"), (7, 8, "K"), (8, 8, "K"), (4, 8, "P"), (11, 8, "P")]

ACCESSORIES = {
    # flag on the antenna + headset with mic
    "pm": [(7, 0, "D"), (7, 1, "D"), (8, 0, "R"), (9, 0, "R"), (10, 0, "R"), (8, 1, "R"), (9, 1, "R"),
           (1, 6, "K"), (1, 7, "K"), (14, 6, "K"), (14, 7, "K"), (1, 8, "K"), (1, 9, "K"), (2, 10, "K"),
           (3, 10, "G")],
    # yellow hard hat + rolled map
    "map_architect": [(6, 1, "Y"), (7, 1, "Y"), (8, 1, "Y"), (9, 1, "Y"), *[(x, 2, "Y") for x in range(4, 12)],
                      *[(x, 3, "O") for x in range(3, 13)], (14, 8, "M"), (15, 8, "M"), (16, 8, "M"),
                      (14, 9, "M"), (15, 9, "C"), (16, 9, "M"), (14, 10, "M"), (15, 10, "M"), (16, 10, "M")],
    # "!" antenna + magnifying glass
    "risk_analyst": [(7, 0, "R"), (8, 0, "R"), (7, 1, "R"), (8, 1, "R"),
                     (15, 3, "K"), (16, 3, "K"), (17, 3, "K"), (14, 4, "K"), (18, 4, "K"), (14, 5, "K"),
                     (18, 5, "K"), (14, 6, "K"), (18, 6, "K"), (15, 7, "K"), (16, 7, "K"), (17, 7, "K"),
                     (15, 4, "S"), (16, 4, "H"), (17, 4, "S"), (15, 5, "S"), (16, 5, "S"), (17, 5, "S"),
                     (15, 6, "S"), (16, 6, "S"), (17, 6, "S"), (18, 8, "O"), (19, 9, "O"), (19, 10, "O")],
    # red pen + green check badge
    "quality_reviewer": [(7, 1, "P"), (8, 1, "P"), (0, 5, "R"), (0, 6, "R"), (0, 7, "R"), (0, 8, "R"),
                         (0, 9, "K"), (11, 1, "E"), (12, 2, "E"), (13, 1, "E"), (14, 0, "E")],
}
ACC_COLORS = {"K": INK, "D": (75, 85, 99), "R": (239, 68, 68), "Y": (250, 204, 21), "O": (202, 138, 4),
              "M": (254, 243, 199), "C": (37, 99, 235), "S": SWEAT, "P": BLUSH, "G": (209, 213, 219),
              "E": (34, 197, 94), "H": WHITE}


def _mix(c, d, t):
    return tuple(int(a + (b - a) * t) for a, b in zip(c, d))


def draw_bot(d: ImageDraw.ImageDraw, bot: str, x: int, y: int, status: str, scale: int = 5,
             blink: bool = False) -> None:
    """Draw the sprite with its top-left at (x, y). Idle bots are drawn faded (only the worker is lit)."""
    body = PERSONAS[bot]["color"]
    fade = 0.6 if status == "idle" else 0.0

    def col(c):
        return _mix(c, GREY, fade) if fade else c

    pal = {"D": _mix(body, INK, 0.55), "B": body, "L": _mix(body, WHITE, 0.45), "W": FACE}

    def px(gx, gy, c):
        d.rectangle((x + gx * scale, y + gy * scale, x + (gx + 1) * scale - 1, y + (gy + 1) * scale - 1), fill=col(c))

    for gy, row in enumerate(BODY):
        for gx, ch in enumerate(row):
            if ch != ".":
                px(gx, gy, pal[ch])
    for gx, gy, k in ACCESSORIES[bot]:
        px(gx, gy, ACC_COLORS[k])
    face = BLINK if blink and status == "working" else FACES[status]
    for gx, gy, k in face:
        px(gx, gy, ACC_COLORS[k])


def draw_sparkle(d: ImageDraw.ImageDraw, x: int, y: int, scale: int, color=(250, 204, 21)) -> None:
    for gx, gy in ((1, 0), (0, 1), (1, 1), (2, 1), (1, 2)):
        d.rectangle((x + gx * scale, y + gy * scale, x + (gx + 1) * scale - 1, y + (gy + 1) * scale - 1), fill=color)


def draw_envelope(d: ImageDraw.ImageDraw, cx: float, cy: float, color, scale: int = 3) -> None:
    grid = ["DDDDDDDDDDD",
            "DFDFFFFFDFD",
            "DFFDFFFDFFD",
            "DFFFDFDFFFD",
            "DFFFFDFFFFD",
            "DFFFFFFFFFD",
            "DDDDDDDDDDD"]
    x0, y0 = cx - len(grid[0]) * scale / 2, cy - len(grid) * scale / 2
    for gy, row in enumerate(grid):
        for gx, ch in enumerate(row):
            c = INK if ch == "D" else color
            d.rectangle((x0 + gx * scale, y0 + gy * scale, x0 + (gx + 1) * scale - 1, y0 + (gy + 1) * scale - 1),
                        fill=c)
