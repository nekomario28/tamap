import json
import multiprocessing as mp
import tempfile
import time
import unittest
from pathlib import Path

from tamap import core, store


def _conc_status_worker(data_dir: str, map_id: str, i: int) -> None:
    """One process in the store stress test. Sleeps inside the locked write to widen the race."""
    from tamap import store as st
    st.DATA_DIR = Path(data_dir)
    orig = st._write

    def slow(map_):
        time.sleep(0.02)
        orig(map_)

    st._write = slow
    bot = "pm" if i % 2 == 0 else "map_architect"
    st.set_bot_status(map_id, bot, "done" if i % 3 == 0 else "working", note=f"n{i}")


def _conc_update_worker(data_dir: str, map_id: str, title: str) -> None:
    from tamap import store as st
    st.DATA_DIR = Path(data_dir)
    orig = st.read_map

    def slow(mid):
        loaded = orig(mid)
        time.sleep(0.03)
        return loaded

    st.read_map = slow
    path = Path(data_dir) / f"update-{title}"
    try:
        st.update_map(map_id, 1, title=title)
        path.write_text("ok", encoding="utf-8")
    except st.RevisionConflict:
        path.write_text("conflict", encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        path.write_text(f"err {type(e).__name__}: {e}", encoding="utf-8")

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
                         "変更点：T4 未着手→ブロック中 ／ ボトルネック：T3→T4 ／ "
                         "影響先：T4・T6・T7→T6・T7（T4はボトルネックに）")
        done = [dict(t, status="done") if t["id"] == "T3" else t for t in blocked]
        d = store.update_map(self.m["map_id"], 2, done)["last_diff"]
        self.assertEqual(d["text"], "変更点：T3 進行中→完了 ／ ボトルネック：変化なし（T4） ／ 影響先：変化なし（T6・T7）")
        self.assertEqual(d["task_changes"], [{"id": "T3", "kind": "status", "from": "in_progress", "to": "done",
                                              "text": "T3 進行中→完了"}])
        self.assertEqual((d["from_revision"], d["to_revision"]), (2, 3))
        d = store.update_map(self.m["map_id"], 3, analysis={"pm": "x"})["last_diff"]
        self.assertTrue(d["text"].startswith("変更点：分析のみ更新（タスク変化なし）"))

    @staticmethod
    def _tasks(spec):
        return [{"id": i, "title": i, "status": s, "depends_on": d} for i, s, d in spec]

    def test_diff_merge_point_with_done_upstream_is_not_a_tied_bottleneck(self):
        tasks = self._tasks([("T1", "done", []), ("T2", "done", ["T1"]), ("T3", "todo", ["T1"]),
                             ("T4", "todo", ["T3"]), ("T5", "todo", ["T2", "T4"]), ("T6", "todo", ["T5"])])
        m = store.create_map("real run", tasks)
        self.assertEqual(store.top_bottlenecks(m["graph"]), ["T3"])
        done = [dict(t, status="done") if t["id"] == "T3" else t for t in tasks]
        m = store.update_map(m["map_id"], 1, done)
        # T5 waits only on T4 now (T2 is done), so it must not tie with T4; it stays a merge point.
        self.assertEqual(store.top_bottlenecks(m["graph"]), ["T4"])
        self.assertTrue(m["graph"]["metrics"]["T5"]["is_merge_point"])
        self.assertEqual(m["last_diff"]["text"],
                         "変更点：T3 未着手→完了 ／ ボトルネック：T3→T4（T3は完了） ／ "
                         "影響先：T4・T5・T6→T5・T6（T4はボトルネックに）")
        self.assertEqual(m["last_diff"]["impacted"]["dropped"], {"ボトルネックに": ["T4"]})

    def test_diff_single_to_multiple_bottlenecks(self):
        tasks = self._tasks([("T1", "todo", []), ("T2", "todo", ["T1"]), ("T3", "todo", ["T2"]),
                             ("T4", "todo", ["T1"]), ("T5", "todo", ["T4"])])
        m = store.create_map("split", tasks)
        done = [dict(t, status="done") if t["id"] == "T1" else t for t in tasks]
        d = store.update_map(m["map_id"], 1, done)["last_diff"]
        self.assertEqual(d["bottleneck"]["after"], ["T2", "T4"])
        # 影響先 covers what every bottleneck holds up, not just the first one.
        self.assertEqual(d["impacted"]["after"], ["T3", "T5"])
        self.assertEqual(d["text"],
                         "変更点：T1 未着手→完了 ／ ボトルネック：T1→T2・T4（T1は完了） ／ "
                         "影響先：T2・T3・T4・T5→T3・T5（T2・T4はボトルネックに）")

    def test_impacted_includes_bottleneck_downstream_of_another(self):
        tasks = core.process(self._tasks([("A", "todo", []), ("B", "todo", ["A"]), ("C", "todo", ["B"]),
                                          ("D", "done", ["C"])]))["tasks"]
        self.assertEqual(store.impacted_by(tasks, ["A", "B"]), ["B", "C"])

    def test_diff_impact_dropped_reasons(self):
        tasks = self._tasks([("T1", "todo", []), ("T2", "todo", ["T1"]), ("T3", "todo", ["T2"]),
                             ("T4", "todo", [])])
        m = store.create_map("reasons", tasks)
        # T1 stays the bottleneck; T3 is dropped from the map and T2 no longer depends on T1.
        tasks2 = self._tasks([("T1", "todo", []), ("T2", "todo", []), ("T4", "todo", ["T1"])])
        d = store.update_map(m["map_id"], 1, tasks2)["last_diff"]
        self.assertEqual(d["text"].split(" ／ ")[1:],
                         ["ボトルネック：変化なし（T1）",
                          "影響先：T2・T3→T4（T2はボトルネックの下流から外れた、T3は削除）"])

    def test_noop_update_keeps_revision(self):
        mid = self.m["map_id"]
        path = store._path(mid)
        before = path.read_bytes()
        stored = json.loads(before)
        incoming = []
        for t in stored["tasks"]:
            t = dict(t)
            t["priority"] = 1  # dropped by normalization
            t["title"] = f"  {t['title']}  "
            if t["status"] == "done":
                t["status"] = "完了"
            if t["depends_on"]:
                t["depends_on"] = "、".join(f" {d} " for d in t["depends_on"])
            incoming.append(t)
        m = store.update_map(mid, "1", incoming, analysis={"assumptions": []}, title="  t  ", source="same again")
        self.assertTrue(m["unchanged"])
        self.assertEqual(m["revision"], 1)
        self.assertEqual(m["source"], "unknown")
        self.assertEqual(m["updated_at"], stored["updated_at"])
        self.assertEqual(len(m["history"]), 1)
        self.assertEqual(path.read_bytes(), before)
        self.assertNotIn("unchanged", json.loads(path.read_text()))
        # A real change still bumps, and a second identical call does not.
        blocked = [dict(t, status="blocked") if t["id"] == "T4" else t for t in stored["tasks"]]
        m = store.update_map(mid, 1, blocked, source="block T4")
        self.assertFalse(m["unchanged"])
        self.assertEqual(m["revision"], 2)
        self.assertEqual(m["source"], "block T4")
        again = store.update_map(mid, 2, blocked, source="block T4 again")
        self.assertTrue(again["unchanged"])
        self.assertEqual(again["revision"], 2)
        self.assertEqual(store.read_map(mid)["source"], "block T4")
        # Stale expected_revision is rejected even when the payload matches the current map.
        with self.assertRaises(store.RevisionConflict):
            store.update_map(mid, 1, blocked)
        self.assertEqual(store.read_map(mid)["revision"], 2)
        with self.assertRaises(store.StoreError):
            store.update_map(mid, 2)

    def test_noop_analysis_and_title_only_change(self):
        mid = self.m["map_id"]
        m = store.update_map(mid, 1, analysis={"pm": {"summary": "s", "actions": ["やる"]}})
        self.assertEqual(m["revision"], 2)
        m = store.update_map(mid, 2, analysis={"pm": {"summary": " s ", "actions": [{"text": "やる"}]}})
        self.assertTrue(m["unchanged"])
        self.assertEqual(m["revision"], 2)
        m = store.update_map(mid, 2, title="新しい名前")
        self.assertFalse(m["unchanged"])
        self.assertEqual(m["revision"], 3)
        self.assertIn("タイトルのみ更新", m["last_diff"]["text"])
        reordered = list(reversed(store.read_map(mid)["tasks"]))
        m = store.update_map(mid, 3, reordered)
        self.assertFalse(m["unchanged"])
        self.assertEqual(m["revision"], 4)

    def test_say_embedded_in_note(self):
        mid = self.m["map_id"]
        m = store.set_bot_status(mid, "pm", "working", "受付 ｜ say:まかせてください！")
        self.assertEqual(m["bots"]["pm"]["note"], "受付")
        self.assertEqual(m["bots"]["pm"]["say"], "まかせてください！")
        m = store.set_bot_status(mid, "map_architect", "working", "分解中 | say：線、つなぐっす。")
        self.assertEqual(m["bots"]["map_architect"]["note"], "分解中")
        self.assertEqual(m["bots"]["map_architect"]["say"], "線、つなぐっす。")
        # Explicit say wins, and the embedded marker is still stripped from the factual note.
        m = store.set_bot_status(mid, "pm", "done", "まとめた ｜ say:まちがい", say="まとまりました！")
        self.assertEqual(m["bots"]["pm"]["note"], "まとめた")
        self.assertEqual(m["bots"]["pm"]["say"], "まとまりました！")
        m = store.set_bot_status(mid, "risk_analyst", "working",
                                 '{"note": "T4を見ている", "say": "ここ、あやしいかも…",}')
        self.assertEqual(m["bots"]["risk_analyst"]["note"], "T4を見ている")
        self.assertEqual(m["bots"]["risk_analyst"]["say"], "ここ、あやしいかも…")
        m = store.set_bot_status(mid, "quality_reviewer", "done",
                                 '{"note":“検査した”,"say":“ちょっとだけ直すね”}')
        self.assertEqual(m["bots"]["quality_reviewer"]["note"], "検査した")
        self.assertEqual(m["bots"]["quality_reviewer"]["say"], "ちょっとだけ直すね")
        m = store.set_bot_status(mid, "quality_reviewer", "working", '赤ペン {"say": "見るね"}')
        self.assertEqual(m["bots"]["quality_reviewer"]["note"], "赤ペン")
        self.assertEqual(m["bots"]["quality_reviewer"]["say"], "見るね")
        m = store.set_bot_status(mid, "pm", "idle", "A | B の確認")
        self.assertEqual(m["bots"]["pm"]["note"], "A | B の確認")
        self.assertNotIn("say", m["bots"]["pm"])
        long = "あ" * 40
        m = store.set_bot_status(mid, "pm", "working", f"受付 ｜ say:{long}")
        self.assertEqual(m["bots"]["pm"]["say"], "あ" * store.SAY_LIMIT)
        self.assertEqual(m["bots"]["pm"]["note"], "受付")

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
        # Done and error show the passed say (not only the working bubble), same as the GIF / live page.
        m = store.set_bot_status(mid, "map_architect", "done", "7本つないだ", say="7本、つないだっす")
        md = render.render_status(m)
        self.assertIn("🗺️ Map Architect<br>(^ω^) 完了<br>「7本、つないだっす」", md)
        self.assertNotIn("地図、できたっす！", md)
        m = store.set_bot_status(mid, "quality_reviewer", "error", "60秒応答なし", say="ここ、直したいね")
        md = render.render_status(m)
        self.assertIn("「ここ、直したいね」", md)
        self.assertNotIn("読みきれなかった…ごめんね", md)
        m = store.set_bot_status(mid, "risk_analyst", "done", "影響を記録")
        md = render.render_status(m)
        self.assertIn("⚠️ Risk Analyst<br>(^ω^) 完了<br>「影響の先、見つけました！」", md)

    def _join(self, procs):
        for p in procs:
            p.join(30)
            if p.is_alive():
                p.kill()
                p.join(5)
                self.fail(f"worker {p.pid} did not finish")
            self.assertEqual(p.exitcode, 0, f"worker exit {p.exitcode}")

    def test_concurrent_writers_keep_every_update(self):
        """N processes, each sleeping inside the locked write. Every history note must survive."""
        mid = self.m["map_id"]
        data_dir = str(store.DATA_DIR)
        n = 12
        ctx = mp.get_context("fork")
        procs = [ctx.Process(target=_conc_status_worker, args=(data_dir, mid, i)) for i in range(n)]
        for p in procs:
            p.start()
        self._join(procs)
        got = store.read_map(mid)
        notes = [h.get("note") for h in got["bot_history"]]
        self.assertEqual({x for x in notes if x and str(x).startswith("n")}, {f"n{i}" for i in range(n)})
        # The lock file is the stable sentinel, not a map JSON that os.replace swaps out.
        self.assertTrue((store.DATA_DIR / ".lock").is_file())
        self.assertFalse(any(p.name == ".lock" for p in store.DATA_DIR.glob("*.json")))

    def test_concurrent_update_map_allows_one_winner(self):
        mid = self.m["map_id"]
        data_dir = str(store.DATA_DIR)
        titles = [f"t{i}" for i in range(6)]
        ctx = mp.get_context("fork")
        procs = [ctx.Process(target=_conc_update_worker, args=(data_dir, mid, title)) for title in titles]
        for p in procs:
            p.start()
        self._join(procs)
        texts = [(store.DATA_DIR / f"update-{title}").read_text(encoding="utf-8") for title in titles]
        self.assertEqual(texts.count("ok"), 1, texts)
        self.assertEqual(texts.count("conflict"), len(titles) - 1, texts)
        got = store.read_map(mid)
        self.assertEqual(got["revision"], 2)
        self.assertIn(got["title"], titles)


if __name__ == "__main__":
    unittest.main()
