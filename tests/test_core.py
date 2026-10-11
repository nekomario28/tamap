import json
import unittest
from pathlib import Path

from tamap import core

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


if __name__ == "__main__":
    unittest.main()
