import os
import tempfile
from pathlib import Path
from unittest.mock import patch, Mock
import unittest
import tkinter as tk

import main


@unittest.skipUnless(os.name == "nt", "Windows desktop UI")
class DesktopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        profile = Path(self.temp.name) / "profile.txt"
        profile.write_text("Synthetic test profile", encoding="utf-8")
        self.root = tk.Tk()
        self.root.withdraw()
        cfg = dict(main.DEFAULT_CONFIG, hh_cookie="synthetic-secret", superjob_cookie="test-secret",
                   lm_model="test-model", telegram_channels="test_channel")
        self.patches = [patch.object(main, "load_config", return_value=cfg),
                        patch.object(main, "PROFILE_PATH", str(profile)),
                        patch.object(main.App, "_read_history_rows", return_value=[]),
                        patch.object(main, "save_config")]
        for item in self.patches:
            item.start()
        self.app = main.App(self.root)

    def tearDown(self):
        self.app.browser_queue.cancel(notify=False)
        self.root.destroy()
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    @staticmethod
    def row(name, verdict="MATCH", suitable=True):
        return {"name": name, "employer": "Test company", "score": 80,
                "verdict": verdict, "suitable": suitable, "reason": "Test explanation",
                "salary": "not listed", "direction": "данные", "resume": "общее",
                "url": "https://example.com"}

    def test_settings_roundtrip_including_hidden_cookies(self):
        before = dict(self.app.cfg)
        after = self.app._collect_config()
        for key in before:
            with self.subTest(key=key):
                self.assertEqual(after[key], before[key])
        self.assertEqual(self.app.txt_cookie.cget("state"), "disabled")
        self.assertEqual(self.app.txt_cookie.tag_cget("secret", "elide"), "1")

    def test_filters_do_not_lose_rows_and_clear_stale_details(self):
        ui = self.app.ui
        ui.add_result(self.row("Analyst"))
        ui.add_result(self.row("Other role", "REJECT", False))
        ui.add_result(self.row("Incomplete", "", None))
        self.assertEqual(len(self.app.tree.get_children()), 1)
        ui.filter.set("Все")
        self.assertEqual(len(self.app.tree.get_children()), 3)
        ui.query.set("ANALYST")
        self.assertEqual(len(self.app.tree.get_children()), 1)
        self.assertEqual(ui.detail_title.cget("text"), "Analyst")
        ui.query.set("no match")
        self.assertEqual(len(self.app.tree.get_children()), 0)
        self.assertTrue(ui.open_button.instate(["disabled"]))
        self.assertEqual(self.app.txt_reason.get("1.0", "end").strip(), "")
        ui.query.set("")
        ui.filter.set("На проверку")
        self.assertEqual(len(self.app.tree.get_children()), 1)
        ui.filter.set("Все")
        self.assertEqual(len(self.app.result_data), 3)

    def test_worker_events_update_counters_and_buttons(self):
        with patch.object(main, "Worker", return_value=Mock()) as worker:
            self.app.on_start()
            worker.return_value.start.assert_called_once()
        self.assertTrue(self.app.btn_start.instate(["disabled"]))
        self.app.queue.put(("result", self.row("Analyst")))
        self.app.queue.put(("stats", (8, 5, 3)))
        self.app.queue.put(("done", None))
        self.app._poll_queue()
        self.assertEqual([number.cget("text") for number in self.app.ui.metrics], ["5", "3", "8"])
        self.assertTrue(self.app.btn_stop.instate(["disabled"]))
        self.assertFalse(self.app.btn_start.instate(["disabled"]))

    def test_source_mode_summary_matches_settings(self):
        self.app.var_recs.set(True)
        self.app.var_resume_only.set(True)
        self.assertIn("только рекомендации HH", self.app.ui.mode.cget("text"))
        self.app.var_resume_only.set(False)
        self.assertIn("выбранным источникам", self.app.ui.mode.cget("text"))

    def test_bulk_open_waits_for_stop_and_includes_filtered_matches(self):
        ui = self.app.ui
        self.assertTrue(ui.bulk_button.instate(["disabled"]))
        with patch.object(main, "Worker", return_value=Mock()):
            self.app.on_start()
        ui.add_result(self.row("First"))
        ui.add_result(dict(self.row("Second"), url="https://example.com/2"))
        ui.add_result(dict(self.row("Rejected", "REJECT", False), url="https://example.com/3"))
        ui.query.set("First")
        self.app.on_stop()
        self.assertTrue(ui.bulk_button.instate(["disabled"]))
        self.app.queue.put(("done", None))
        self.app._poll_queue()
        self.assertFalse(ui.bulk_button.instate(["disabled"]))
        self.app.browser_queue.opener = Mock(return_value=True)
        self.app.on_open_all_vacancies()
        self.assertEqual(self.app.browser_queue.urls, ["https://example.com", "https://example.com/2"])
        self.app.browser_queue.opener.assert_called_once_with("https://example.com")
        self.app.on_open_all_vacancies()
        self.assertFalse(self.app.browser_queue.active)

    def test_new_search_cancels_browser_queue(self):
        self.app.ui.add_result(self.row("First"))
        self.app.ui.add_result(dict(self.row("Second"), url="https://example.com/2"))
        self.app.browser_queue.opener = Mock(return_value=True)
        self.app.on_open_all_vacancies()
        self.assertTrue(self.app.browser_queue.active)
        with patch.object(main, "Worker", return_value=Mock()):
            self.app.on_start()
        self.assertFalse(self.app.browser_queue.active)
        self.assertIsNone(self.app.browser_queue.pending)

    def test_startup_does_not_load_history_into_current_results(self):
        main.App._read_history_rows.assert_not_called()
        self.assertEqual(self.app.result_data, {})
        self.assertEqual(self.app.tree.get_children(), ())

    def test_new_search_clears_hidden_rows_but_preserves_history(self):
        ui = self.app.ui
        row = self.row("Previous match")
        with patch.object(main, "RESULTS_DIR", self.temp.name):
            writer = main.ResultWriter("test")
            writer.write({**row, "id": "test-id"}, 80, "MATCH", "данные", "общее", "Test reason", True)
        history = Path(writer.csv_path).read_bytes()
        ui.add_result(row)
        ui.add_result(self.row("Hidden rejection", "REJECT", False))
        old_ids = tuple(self.app.result_data)
        ui.query.set("Previous")
        with patch.object(main, "Worker", return_value=Mock()):
            self.app.on_start()
        self.assertEqual(self.app.result_data, {})
        self.assertTrue(all(not self.app.tree.exists(iid) for iid in old_ids))
        self.assertEqual(ui.query.get(), "")
        self.assertEqual(self.app.txt_reason.get("1.0", "end").strip(), "")
        self.assertTrue(ui.open_button.instate(["disabled"]))
        self.assertEqual(Path(writer.csv_path).read_bytes(), history)
        ui.add_result(self.row("New match"))
        self.assertEqual(len(self.app.tree.get_children()), 1)
        self.assertEqual(next(iter(self.app.result_data.values()))["name"], "New match")


if __name__ == "__main__":
    unittest.main()
