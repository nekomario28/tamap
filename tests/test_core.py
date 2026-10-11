import json
import tempfile
import unittest
from pathlib import Path

from tamap import core, store

ROOT = Path(__file__).resolve().parent.parent


def load(name):
    return json.loads((ROOT / "samples" / name).read_text())["tasks"]


class CoreTest(unittest.TestCase):
    def test_readme_example(self):
        r = core.process(load("readme_example.json"))
        self.assertTrue(r["validation"]["ok"])
        self.assertEqual([m["id"] for m in r["graph"]["merge_points"]], ["T6"])
        self.assertEqual(core.simulate_delay(r["tasks"], "T4")["impacted_ids"], ["T6", "T7"])
        self.assertEqual(core.simulate_delay(r["tasks"], "T3")["impacted_ids"], ["T4", "T6", "T7"])
        self.assertEqual(core.simulate_delay(r["tasks"], "T7")["impacted_ids"], [])
        self.assertEqual(r["graph"]["critical_path_candidates"][0]["path"], ["T1", "T3", "T4", "T6", "T7"])
        self.assertEqual(r["graph"]["bottlenecks"][0]["id"], "T3")

    def test_broken_example(self):
        r = core.process(load("broken_example.json"))
        codes = {e["code"] for e in r["validation"]["errors"]}
        self.assertEqual(codes, {"duplicate_id", "unknown_reference", "cycle"})
        self.assertEqual([sorted(c) for c in r["validation"]["cycles"]], [["T6", "T7"]])
        self.assertEqual(r["graph"]["critical_path_candidates"], [])
        # Impact computation must terminate on cycles.
        self.assertEqual(core.simulate_delay(r["tasks"], "T6")["impacted_ids"], ["T7"])

    def test_self_and_status(self):
        r = core.process([{"id": "A", "title": "a", "status": "weird", "depends_on": ["A"]}])
        codes = {e["code"] for e in r["validation"]["errors"]}
        self.assertEqual(codes, {"invalid_status", "self_dependency"})

    def test_longer_cycle(self):
        tasks = [{"id": x, "title": x, "status": "todo", "depends_on": [d]} for x, d in
                 [("A", "C"), ("B", "A"), ("C", "B"), ("D", "C")]]
        r = core.process(tasks)
        self.assertEqual(len(r["validation"]["cycles"]), 1)
        self.assertEqual(sorted(r["validation"]["cycles"][0]), ["A", "B", "C"])


class StoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self._data_dir = store.DATA_DIR
        store.DATA_DIR = Path(self.tmp.name) / "maps"
        self.m = store.create_map("t", load("readme_example.json"))

    def tearDown(self):
        store.DATA_DIR = self._data_dir
        self.tmp.cleanup()

    def test_specialist_working_puts_pm_idle(self):
        mid = self.m["map_id"]
        store.set_bot_status(mid, "pm", "working", "受付")
        m = store.set_bot_status(mid, "map_architect", "working", "分解中")
        self.assertEqual(m["bots"]["pm"]["status"], "idle")
        self.assertEqual(m["bots"]["pm"]["note"], "Map Architectの結果待ち")
        self.assertEqual([(h["bot"], h["status"]) for h in m["bot_history"]],
                         [("pm", "working"), ("pm", "idle"), ("map_architect", "working")])
        # PM already idle: no extra history entry; PM working while specialists are done stays allowed.
        store.set_bot_status(mid, "map_architect", "done")
        m = store.set_bot_status(mid, "risk_analyst", "working")
        self.assertEqual(len(m["bot_history"]), 5)
        m = store.set_bot_status(mid, "pm", "working", "統合中")
        self.assertEqual(m["bots"]["pm"]["status"], "working")
        self.assertEqual(m["revision"], 1)

    def test_update_diff(self):
        tasks = load("readme_example.json")
        blocked = [dict(t, status="blocked") if t["id"] == "T4" else t for t in tasks]
        m = store.update_map(self.m["map_id"], 1, blocked)
        self.assertEqual(m["last_diff"]["text"],
                         "変更点：T4 未着手→ブロック中 ／ ボトルネック：T3→T4 ／ 影響先：T4・T6・T7→T6・T7")
        done = [dict(t, status="done") if t["id"] == "T3" else t for t in blocked]
        d = store.update_map(self.m["map_id"], 2, done)["last_diff"]
        self.assertEqual(d["text"], "変更点：T3 進行中→完了 ／ ボトルネック：変化なし（T4） ／ 影響先：変化なし（T6・T7）")
        self.assertEqual(d["task_changes"], [{"id": "T3", "kind": "status", "from": "in_progress", "to": "done",
                                              "text": "T3 進行中→完了"}])
        self.assertEqual((d["from_revision"], d["to_revision"]), (2, 3))
        d = store.update_map(self.m["map_id"], 3, analysis={"pm": "x"})["last_diff"]
        self.assertTrue(d["text"].startswith("変更点：分析のみ更新（タスク変化なし）"))

    def test_quality_items_keep_before(self):
        a = store.normalize_analysis({"quality": {"items": [
            {"before": "原因はDB設計", "text": "原因はDB設計の可能性あり（推定）", "reason": "断定しすぎ"},
            {"before": "モックで並行開発する", "after": "T5→T4の依存がある場合のみモックで進める"}]}})
        self.assertEqual(a["quality"]["items"][0], {"text": "原因はDB設計の可能性あり（推定）",
                                                    "before": "原因はDB設計", "reason": "断定しすぎ"})
        self.assertEqual(a["quality"]["items"][1]["text"], "T5→T4の依存がある場合のみモックで進める")

    def test_flow_gif(self):
        from PIL import Image

        from tamap import animate
        mid = self.m["map_id"]
        store.update_map(mid, 1, analysis={"pm": {"actions": ["a", "b", "c"]},
                                           "quality": {"items": [{"before": "x", "text": "y"}]}})
        for bot, st in [("pm", "working"), ("map_architect", "working"), ("map_architect", "done"),
                        ("risk_analyst", "working"), ("risk_analyst", "done"), ("quality_reviewer", "working"),
                        ("quality_reviewer", "done"), ("pm", "working"), ("pm", "done")]:
            m = store.set_bot_status(mid, bot, st)
        self.assertEqual(len(animate.cycle_events(m["bot_history"])), 10)
        r = animate.render_flow_gif(m, Path(self.tmp.name) / "out")
        self.assertTrue(r["path"].endswith(f"{mid}_flow.gif"))
        with Image.open(r["path"]) as img:
            self.assertEqual(img.format, "GIF")
            self.assertEqual(img.n_frames, r["frames"])
            self.assertGreater(img.n_frames, 20)


if __name__ == "__main__":
    unittest.main()
