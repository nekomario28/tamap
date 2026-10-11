"""The 4 TaMap bots as characters: role, colour, motif, face per status and a line in their own voice.

Shared by the flow GIF (pixel sprites), the bot-status mermaid and the bot instructions, so that each
bot looks and talks the same everywhere. The status palettes below are the single source of truth for
the live page, the flow GIF and both mermaid diagrams; the character colour only identifies the bot.
"""
from __future__ import annotations

# Bot status words. A bot being "done" means its ANALYSIS is done — not that the project's tasks are.
BOT_STATUS_JA = {"idle": "待機", "working": "分析中", "done": "分析完了", "error": "エラー"}
ALL_DONE_CAPTION = "4体とも分析完了"

# Colour families never overlap, so bot state and task state can be told apart by colour alone.
# Bots = slate / violet / indigo / fuchsia (cool purples). Tasks = traffic-light green / cyan / yellow / red,
# plus orange for the delay impact and dark red for invalid tasks.
BOT_COLORS = {"idle": (148, 163, 184), "working": (139, 92, 246), "done": (67, 56, 202), "error": (192, 38, 211)}
BOT_STROKE = {"idle": (100, 116, 139), "working": (109, 40, 217), "done": (49, 46, 129), "error": (134, 25, 143)}
BOT_GLOW = ((237, 233, 254), (167, 139, 250))   # fill / outline behind the working bot
BOT_LINK_HOT = (124, 58, 237)                    # mermaid edge into the working bot
TASK_COLORS = {"done": (34, 197, 94), "in_progress": (8, 145, 178), "todo": (253, 224, 71), "blocked": (220, 38, 38)}
TASK_STROKE = {"done": (21, 128, 61), "in_progress": (14, 116, 144), "todo": (161, 98, 7), "blocked": (153, 27, 27)}
TASK_IMPACT, TASK_IMPACT_STROKE = (251, 146, 60), (194, 65, 12)
TASK_ERR, TASK_ERR_STROKE = (127, 29, 29), (69, 10, 10)
TASK_EDGE_HOT = (234, 88, 12)
TASK_INK_ON = {"todo", "impact"}                 # light fills -> dark text


def hexc(c) -> str:
    return "#%02x%02x%02x" % tuple(c)


def all_done(bots: dict) -> bool:
    """All 4 bots have finished their analysis (used only to word the caption, never as a task status)."""
    return all((bots.get(k) or {}).get("status") == "done" for k in PERSONAS)


PERSONAS: dict[str, dict] = {
    "pm": {
        "name": "TaMap PM", "emoji": "📋", "role": "まとめ役",
        "motif": "旗つきアンテナとヘッドセット",
        "trait": "しっかり者で明るい。みんなに声をかけて、最後にまとめる",
        "color": (99, 102, 241),
        "lines": {"idle": "みんなの結果、待ってます…", "working": "まかせてください！",
                  "done": "まとまりました！", "error": "あわわ、確認します！"},
    },
    "map_architect": {
        "name": "Map Architect", "emoji": "🗺️", "role": "地図職人",
        "motif": "黄色いヘルメットと巻いた地図",
        "trait": "無口で几帳面な職人。短く「〜っす」と話す",
        "color": (20, 184, 166),
        "lines": {"idle": "（方眼紙の夢を見てる）", "working": "線、つなぐっす。",
                  "done": "地図、できたっす！", "error": "線がからまったっす…"},
    },
    "risk_analyst": {
        "name": "Risk Analyst", "emoji": "⚠️", "role": "心配性の探偵",
        "motif": "虫めがねと「！」のアンテナ",
        "trait": "心配性だけど鼻がきく。「…かも」が口ぐせ",
        "color": (245, 158, 11),
        "lines": {"idle": "（虫めがねをみがいてる）", "working": "ここ、あやしいかも…",
                  "done": "影響の先、見つけました！", "error": "手がかりが足りないかも…"},
    },
    "quality_reviewer": {
        "name": "Quality Reviewer", "emoji": "✅", "role": "赤ペン先生",
        "motif": "赤ペンとチェックのバッジ",
        "trait": "やさしいけど見逃さない。「〜ね」とやわらかく直す",
        "color": (236, 72, 153),
        "lines": {"idle": "（赤ペンを置いて休憩中）", "working": "ちょっとだけ直すね",
                  "done": "うん、これなら大丈夫！", "error": "読みきれなかった…ごめんね"},
    },
}

FACES = {"idle": "(-ω-)zz", "working": "(•ω•)✧", "done": "(^ω^)", "error": "(>ω<;)"}


def line(bot: str, status: str, say: str | None = None, quality_count: int = 0) -> str:
    if say:
        return say
    if bot == "quality_reviewer" and status == "done" and quality_count:
        return f"{quality_count}件直したよ！"
    return PERSONAS[bot]["lines"][status]
