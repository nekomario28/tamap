import json
import tempfile
import unittest
from pathlib import Path

from tamap import core, store

ROOT = Path(__file__).resolve().parent.parent


def sprites_first_color(bot, status):
    from tamap import sprites
    return sprites.bot_pixels(bot, status)[0][2]


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
        card = animate.render_team_card(Path(self.tmp.name) / "out")
        with Image.open(card["path"]) as img:
            self.assertEqual((img.format, img.n_frames), ("GIF", card["frames"]))

    def test_cycle_events_full_cycle(self):
        from tamap import animate
        mid = self.m["map_id"]
        hub = [("pm", "working"), ("map_architect", "working"), ("map_architect", "done"), ("pm", "working"),
               ("risk_analyst", "working"), ("risk_analyst", "done"), ("pm", "working"),
               ("quality_reviewer", "working"), ("quality_reviewer", "done"), ("pm", "done")]
        store.set_bot_status(mid, "map_architect", "done", "前回の名残")  # before the intake: skipped
        for bot, st in hub:
            m = store.set_bot_status(mid, bot, st)
        ev = animate.cycle_events(m["bot_history"])
        self.assertEqual((ev[0]["bot"], ev[0]["status"]), ("pm", "working"))
        self.assertEqual((ev[-1]["bot"], ev[-1]["status"]), ("pm", "done"))
        specialists = [(e["bot"], e["status"]) for e in ev if e["bot"] != "pm"]
        self.assertEqual(specialists, [("map_architect", "working"), ("map_architect", "done"),
                                       ("risk_analyst", "working"), ("risk_analyst", "done"),
                                       ("quality_reviewer", "working"), ("quality_reviewer", "done")])
        # A second cycle: only it is replayed; an in-progress cycle is replayed from its intake.
        for bot, st in hub[:5]:
            m = store.set_bot_status(mid, bot, st)
        ev2 = animate.cycle_events(m["bot_history"])
        self.assertEqual(ev2[0]["at"], m["bot_history"][len(m["bot_history"]) - len(ev2)]["at"])
        self.assertEqual([(e["bot"], e["status"]) for e in ev2 if e["bot"] != "pm"],
                         [("map_architect", "working"), ("map_architect", "done"), ("risk_analyst", "working")])

    def test_history_trim_keeps_whole_cycles(self):
        cyc = [{"bot": "pm", "status": "working"}, {"bot": "map_architect", "status": "working"},
               {"bot": "map_architect", "status": "done"}, {"bot": "pm", "status": "done"}]
        hist = cyc * 60  # 240 entries
        out = store.trim_history(hist, 30)
        self.assertLessEqual(len(out), 30)
        self.assertEqual((out[0]["bot"], out[0]["status"]), ("pm", "working"))
        self.assertEqual(len(out) % 4, 0)
        self.assertEqual(store.trim_history(hist[:10], 30), hist[:10])

    def test_live_page_read_only_and_sse(self):
        import http.client
        import os
        import threading
        import time

        from tamap import live
        srv = live.make_server("127.0.0.1", 0, quiet=True)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        port = srv.server_address[1]
        mid = self.m["map_id"]
        path = store.DATA_DIR / f"{mid}.json"

        def req(method, url):
            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request(method, url)
            r = c.getresponse()
            body = r.read()
            c.close()
            return r.status, r.getheader("Content-Type"), body

        try:
            st, ct, body = req("GET", f"/live/{mid}")
            self.assertEqual((st, ct), (200, "text/html; charset=utf-8"))
            self.assertIn(b"EventSource", body)
            st, _, body = req("GET", f"/api/maps/{mid}")
            snap = json.loads(body)
            self.assertEqual((st, snap["revision"], len(snap["tasks"])), (200, 1, 7))
            spec = json.loads(req("GET", "/api/scene")[2])
            self.assertEqual(spec["sprites"]["pm"]["idle"][0][2], "#%02x%02x%02x" % sprites_first_color("pm", "idle"))
            before = path.read_bytes()
            for method in ("POST", "PUT", "DELETE", "PATCH", "OPTIONS"):
                for url in (f"/live/{mid}", f"/api/maps/{mid}", f"/events/{mid}", "/"):
                    self.assertEqual(req(method, url)[0], 405, f"{method} {url}")
            self.assertEqual(path.read_bytes(), before)
            self.assertEqual(sorted(os.listdir(store.DATA_DIR)), sorted([f"{mid}.json", ".lock"]))
            for url in ("/api/maps/nosuchmap", "/api/maps/..%2Fmaps", "/live/a/b", "/events/x"):
                self.assertEqual(req("GET", url)[0], 404, url)

            c = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
            c.request("GET", f"/events/{mid}")
            r = c.getresponse()
            self.assertEqual(r.getheader("Content-Type"), "text/event-stream; charset=utf-8")

            def next_snapshot():
                data = None
                while True:
                    line = r.fp.readline().decode()
                    if line.startswith("data: "):
                        data = json.loads(line[6:])
                    elif line == "\n" and data is not None:
                        return data

            self.assertEqual(next_snapshot()["bots"]["risk_analyst"]["status"], "idle")
            t0 = time.monotonic()
            store.set_bot_status(mid, "risk_analyst", "working", "T4を分析", say="あやしいかも…")
            s2 = next_snapshot()
            self.assertLess(time.monotonic() - t0, 3)
            self.assertEqual(s2["bots"]["risk_analyst"]["status"], "working")
            self.assertEqual((s2["events"][-1]["say"], s2["events"][-1]["line"]), ("あやしいかも…", "あやしいかも…"))
            store.update_map(mid, 1, [dict(t, status="done") if t["id"] == "T3" else t
                                      for t in load("readme_example.json")])
            s3 = next_snapshot()
            self.assertEqual(s3["revision"], 2)
            self.assertEqual({t["id"]: t["status"] for t in s3["tasks"]}["T3"], "done")
            c.close()

            os.environ["TAMAP_LIVE_TOKEN"] = "s3cret"
            try:
                self.assertEqual(req("GET", f"/live/{mid}")[0], 403)
                self.assertEqual(req("GET", f"/api/maps/{mid}?token=nope")[0], 403)
                self.assertEqual(req("GET", f"/live/{mid}?token=s3cret")[0], 200)
                self.assertEqual(req("GET", "/healthz")[0], 200)
                self.assertTrue(live.live_url(mid).endswith(f"/live/{mid}?token=s3cret"))
            finally:
                del os.environ["TAMAP_LIVE_TOKEN"]
        finally:
            srv.stopping.set()
            srv.shutdown()
            srv.server_close()

    def test_persona_say_and_status_chart(self):
        from tamap import persona, render
        mid = self.m["map_id"]
        m = store.set_bot_status(mid, "risk_analyst", "working", "T4を分析", say="T4、あやしいかも…" + "x" * 40)
        self.assertEqual(m["bots"]["risk_analyst"]["say"], ("T4、あやしいかも…" + "x" * 40)[:store.SAY_LIMIT])
        self.assertEqual(m["bot_history"][-1]["say"], m["bots"]["risk_analyst"]["say"])
        self.assertEqual(persona.line("quality_reviewer", "done", quality_count=2), "2件直したよ！")
        self.assertEqual(persona.line("map_architect", "working"), "線、つなぐっす。")
        self.assertEqual(set(persona.PERSONAS), set(store.BOT_KEYS))
        md = render.render_status(m)
        self.assertIn('"⚠️ Risk Analyst<br>(•ω•)✧ 作業中<br>「T4、あやしいかも…', md)
        self.assertIn('"📋 TaMap PM<br>(-ω-)zz 待機', md)


if __name__ == "__main__":
    unittest.main()
