"""Lenient extraction of a specialist bot's plain-text reply."""
import unittest

from tamap.handoff import HandoffError, parse_reply, summary_line


MA = {
    "title": "タスク管理",
    "tasks": [{"id": "T1", "title": "要件整理", "status": "done", "depends_on": []}],
    "say": "地図、できたっす！",
}


def _ma_text(**extra) -> str:
    import json
    payload = dict(MA)
    payload.update(extra)
    return (
        "地図、できたっす！前置きです。\n\n```json\n"
        + json.dumps(payload, ensure_ascii=False)
        + "\n```\n以上です。"
    )


class HandoffTest(unittest.TestCase):
    def test_fence_prose_trailing_comma_and_smart_quotes(self):
        text = (
            "できました。\n```json\n"
            '{"title": "タスク管理", "tasks": [{"id": "T1", "title": "要件整理", '
            '"status": "done", "depends_on": [],},], "say": “地図、できたっす！”}\n'
            "```\nよろしくお願いします。"
        )
        parsed = parse_reply(text, "map_architect")
        self.assertEqual(parsed["role"], "map_architect")
        self.assertEqual(parsed["data"]["tasks"][0]["id"], "T1")
        self.assertEqual(parsed["data"]["say"], "地図、できたっす！")
        self.assertEqual(parsed["warnings"], [])
        self.assertIn("tasks 1件", summary_line(parsed))

    def test_unfenced_object_and_mermaid_fence_ignored(self):
        text = (
            "図はこちら。\n```mermaid\ngraph LR\n  A-->B\n```\n"
            "結果は {\"summary\": \"2件修正\", \"items\": [], \"say\": \"指摘なしだよ\"} です。"
        )
        parsed = parse_reply(text, "quality_reviewer")
        self.assertEqual(parsed["data"]["items"], [])
        self.assertIn("指摘 0件", summary_line(parsed))

    def test_last_json_fence_wins_over_an_earlier_example(self):
        text = (
            "例:\n```json\n{\"items\": [{\"before\": \"古い\", \"text\": \"例\", \"reason\": \"例\"}]}\n```\n"
            "本番:\n```json\n{\"summary\": \"ok\", \"items\": []}\n```"
        )
        parsed = parse_reply(text, "QR")
        self.assertEqual(parsed["role"], "quality_reviewer")
        self.assertEqual(parsed["data"]["items"], [])

    def test_broken_last_fence_is_not_replaced_by_an_earlier_example(self):
        text = (
            "```json\n{\"items\": []}\n```\n"
            "```json\n{これは壊れ}\n```"
        )
        with self.assertRaises(HandoffError) as cm:
            parse_reply(text, "quality_reviewer")
        self.assertIn("JSON を読めませんでした", str(cm.exception))
        self.assertTrue(cm.exception.hint)

    def test_role_errors_are_specific(self):
        with self.assertRaises(HandoffError) as cm:
            parse_reply("```json\n{\"title\": \"x\"}\n```", "map architect")
        self.assertIn("tasks", str(cm.exception))
        with self.assertRaises(HandoffError) as cm:
            parse_reply("```json\n{\"items\": [{\"before\": \"a\"}]}\n```", "quality_reviewer")
        self.assertIn("text", str(cm.exception))
        with self.assertRaises(HandoffError) as cm:
            parse_reply("```json\n{\"say\": \"だけ\"}\n```", "risk")
        self.assertIn("summary", str(cm.exception))
        parsed = parse_reply(
            "```json\n{\"origin_ids\": [\"T4\"], \"items\": [\"確認する\"], \"summary\": \"T4\"}\n```",
            "risk_analyst")
        self.assertEqual(parsed["data"]["origin_ids"], ["T4"])
        self.assertIn("T4", summary_line(parsed))

    def test_empty_array_and_unknown_role(self):
        with self.assertRaises(HandoffError) as cm:
            parse_reply("   ")
        self.assertIn("空", str(cm.exception))
        with self.assertRaises(HandoffError) as cm:
            parse_reply("前置きだけでJSONがありません", "quality_reviewer")
        self.assertIn("JSON が見つかりません", str(cm.exception))
        with self.assertRaises(HandoffError) as cm:
            parse_reply("```json\n[{\"id\": \"T1\"}]\n```", "map_architect")
        self.assertIn("オブジェクト", str(cm.exception))
        with self.assertRaises(HandoffError) as cm:
            parse_reply("```json\n{}\n```", "designer")
        self.assertIn("role", str(cm.exception))

    def test_comma_inside_string_is_kept(self):
        text = '説明\n```json\n{"summary": "hello,}", "items": [],}\n```'
        parsed = parse_reply(text, "quality_reviewer")
        self.assertEqual(parsed["data"]["summary"], "hello,}")

    def test_missing_before_is_a_warning_not_an_error(self):
        text = '```json\n{"items": [{"text": "直した", "reason": "断定しすぎ"}]}\n```'
        parsed = parse_reply(text, "quality_reviewer")
        self.assertEqual(parsed["data"]["items"][0]["text"], "直した")
        self.assertTrue(any("before" in w for w in parsed["warnings"]))
        self.assertIn("注意", summary_line(parsed))

    def test_no_role_returns_the_object(self):
        parsed = parse_reply(_ma_text())
        self.assertIsNone(parsed["role"])
        self.assertEqual(parsed["data"]["title"], "タスク管理")
        self.assertIn("キー:", summary_line(parsed))


if __name__ == "__main__":
    unittest.main()
