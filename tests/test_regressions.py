import copy
from contextlib import closing
import json
import os
from pathlib import Path
import queue
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

import main
import resume_tailor
import settings
from storage import EvaluationStore, evaluation_fingerprint, read_json, write_json
from vacancy_rules import extract_jobposting_description, score_cap


class RulesTests(unittest.TestCase):
    def test_day_shifts_are_not_nights(self):
        for text in ["График 2/2, только дневные смены, 09:00–18:00.",
                     "График 3/3.", "График 5/2, без ночных смен."]:
            with self.subTest(text=text):
                self.assertIsNone(score_cap("Специалист поддержки", text))

    def test_negated_rotation_is_not_rejected(self):
        for text in ["Без вахты и командировок.", "Вахтового метода нет.",
                     "Не вахта.", "Вахта не предусмотрена."]:
            with self.subTest(text=text):
                self.assertIsNone(score_cap("Специалист", text))
        self.assertIsNotNone(score_cap("Специалист", "Работа вахтовым методом 15/15."))

    def test_optional_experience(self):
        self.assertIsNone(score_cap("Специалист", "Будет плюсом опыт работы от 3 лет."))
        self.assertIsNotNone(score_cap("Специалист", "Обязателен опыт работы от 3 лет."))

    def test_jsonld_forms_and_malformed_blocks(self):
        item = {"@type": "JobPosting", "description": "<p>Задачи</p><p>Условия &amp; график</p>"}
        for value in [item, [item], {"@graph": [None, item]},
                      {**item, "@type": ["Thing", "JobPosting"]}]:
            page = "<script type='application/ld+json'>broken</script>"
            page += "<SCRIPT TYPE='application/ld+json'>" + json.dumps(value) + "</SCRIPT>"
            self.assertEqual(extract_jobposting_description(page), "Задачи\nУсловия & график")
        self.assertEqual(extract_jobposting_description(
            '<script type="application/ld+json">null</script>'), "")

    def test_hh_missing_search_shape_is_error(self):
        client = main.HHClient(lambda _: None)
        client._get = Mock(return_value=Mock(text='<template id="HH-Lux-InitialState">{}</template>'))
        with self.assertRaisesRegex(RuntimeError, "формат"):
            client.search("test", "1", "", False, False, 0)


class StorageTests(unittest.TestCase):
    def test_statuses_and_rule_versions(self):
        with tempfile.TemporaryDirectory() as folder:
            path = os.path.join(folder, "state.db")
            store = EvaluationStore(path, "v1")
            for status in ["evaluated", "skipped", "failed", "incomplete"]:
                store.mark(status, status, "reason")
            store.close()
            store = EvaluationStore(path, "v1")
            self.assertEqual(store.completed_ids(), {"evaluated", "skipped"})
            store.close()
            store = EvaluationStore(path, "v2")
            self.assertEqual(store.completed_ids(), set())
            store.close()

    def test_fingerprint_changes_for_all_evaluation_inputs(self):
        cfg = {"exclude_words": "old", "triage": True}
        original = evaluation_fingerprint("profile", cfg, "model", "fast", ["prompt"])
        variants = [("new", cfg, "model", "fast", ["prompt"]),
                    ("profile", {**cfg, "exclude_words": "new"}, "model", "fast", ["prompt"]),
                    ("profile", cfg, "new", "fast", ["prompt"]),
                    ("profile", cfg, "model", "new", ["prompt"]),
                    ("profile", cfg, "model", "fast", ["new"])]
        for args in variants:
            self.assertNotEqual(original, evaluation_fingerprint(*args))

    def test_atomic_write_preserves_previous_file_on_failure(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            write_json(path, {"value": 1})
            with patch("storage.os.replace", side_effect=OSError("locked")):
                with self.assertRaises(OSError):
                    write_json(path, {"value": 2})
            self.assertEqual(read_json(path), {"value": 1})
            self.assertEqual(len(list(Path(folder).iterdir())), 1)

    def test_corrupt_json_is_not_silently_reset(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "config.json"
            path.write_text('{"broken":', encoding="utf-8")
            with self.assertRaises(RuntimeError):
                settings.load_settings(path, {})
            self.assertEqual(path.read_text(encoding="utf-8"), '{"broken":')


class VaultTests(unittest.TestCase):
    def setUp(self):
        self.values = {}
        self.vault = Mock()
        self.vault.set_password.side_effect = lambda service, key, value: self.values.__setitem__((service, key), value)
        self.vault.get_password.side_effect = lambda service, key: self.values.get((service, key))
        self.vault.delete_password.side_effect = lambda service, key: self.values.pop((service, key), None)

    def test_long_cookie_migration_round_trip_and_removal(self):
        with tempfile.TemporaryDirectory() as folder, patch("settings._keyring", return_value=self.vault):
            path = Path(folder) / "config.json"
            cfg = {"hh_cookie": "test-only-" * 1000, "superjob_cookie": "sample", "pages": 2}
            write_json(path, cfg)
            settings.save_settings(path, cfg)
            self.assertNotIn("test-only", path.read_text())
            self.assertEqual(settings.load_settings(path, {})["hh_cookie"], cfg["hh_cookie"])
            self.assertTrue(all(len(value) <= 500 for value in self.values.values()))
            settings.save_settings(path, {**cfg, "hh_cookie": "", "superjob_cookie": ""})
            self.assertEqual(self.values, {})

    def test_failed_save_preserves_existing_credentials(self):
        with tempfile.TemporaryDirectory() as folder, patch("settings._keyring", return_value=self.vault):
            path = Path(folder) / "config.json"
            settings.save_settings(path, {"hh_cookie": "original"})
            old = path.read_bytes()
            with patch("storage.os.replace", side_effect=OSError("locked")):
                with self.assertRaises(RuntimeError):
                    settings.save_settings(path, {"hh_cookie": "replacement"})
            self.assertEqual(path.read_bytes(), old)
            self.assertEqual(settings.load_settings(path, {})["hh_cookie"], "original")
            self.assertEqual(list(self.values.values()), ["original"])


class ResumeTests(unittest.TestCase):
    def setUp(self):
        self.original = {
            "target_titles": ["Junior"], "summary": "Original", "additional": "Original",
            "skill_groups": {"Tools": ["Python", "SQL"]},
            "experience": [{"title": "Assistant", "company": "Example", "bullets": ["One"]}],
            "education": [{"school": "Example University", "relevant_courses": ["Math"]}],
        }

    def test_no_invented_skills_courses_or_extra_bullets(self):
        untouched = copy.deepcopy(self.original)
        draft = {"skills": {"Tools": ["Invented", "sql", "SQL"]},
                 "education_courses": {"Example University": ["Invented", "Math"]},
                 "experience": {"Assistant — Example": ["Reworded", "Extra"]}}
        merged = resume_tailor.merge_tailored(self.original, draft)
        self.assertEqual(merged["skill_groups"]["Tools"], ["SQL"])
        self.assertEqual(merged["education"][0]["relevant_courses"], ["Math"])
        self.assertEqual(merged["experience"][0]["bullets"], ["Reworded"])
        self.assertEqual(self.original, untouched)

    def test_invalid_resume_types_are_retried(self):
        payload = {"target_title": "Junior", "summary": "Test", "additional": "Test",
                   "skills": [], "experience": {}}
        self.assertIsNone(resume_tailor.LLMClient._parse(json.dumps(payload)))

    @unittest.skipUnless(os.name == "nt", "PDF requires Windows fonts")
    def test_pdf_with_literal_markup(self):
        example = Path(__file__).resolve().parents[1] / "examples" / "resume_data.example.json"
        original = json.loads(example.read_text(encoding="utf-8"))
        merged = resume_tailor.merge_tailored(original, {"summary": "Literal <test> & text"})
        with tempfile.TemporaryDirectory() as folder, patch.object(resume_tailor, "PHOTO_PATH", None):
            path = Path(folder) / "test.pdf"
            resume_tailor.build_pdf(merged, str(path))
            self.assertTrue(path.read_bytes().startswith(b"%PDF-"))
            self.assertGreater(path.stat().st_size, 1000)


class LLMTests(unittest.TestCase):
    def test_bad_verdict_is_not_a_success(self):
        client = main.LLMClient("http://example.invalid/v1", "test", lambda _: None)
        content = json.dumps({"verdict": "INVALID", "score": 90, "reason": "Detailed reason for testing"})
        with patch.object(client, "_chat", return_value=content):
            with self.assertRaises(main.EvaluationExhausted):
                client.evaluate("profile", "vacancy")

    def test_escaped_reason_is_decoded(self):
        payload = {"verdict": "MATCH", "score": 80, "direction": "данные", "reason": "Подходящие задачи и обучение"}
        self.assertEqual(main.LLMClient._parse(json.dumps(payload))[3], payload["reason"])


class WorkerTests(unittest.TestCase):
    def test_full_description_failures_and_restart(self):
        with tempfile.TemporaryDirectory() as folder:
            results = os.path.join(folder, "results")
            cache = os.path.join(folder, "cache")
            items = [{"id": vid, "name": vid, "employer": "Example", "salary": "?", "url": vid}
                     for vid in ["missing", "failed", "good"]]
            long_text = "x" * 5000 + "END OF DESCRIPTION"
            cfg = dict(main.DEFAULT_CONFIG, role_ids=[], queries="test", triage=False,
                       exclude_words="", include_words="", pages=1, remote_extra=False)

            def run_once():
                stop = threading.Event()
                worker = main.Worker(cfg, "profile", queue.Queue(), stop)
                evaluated = []
                def evaluate(profile, text):
                    evaluated.append(text)
                    if "Должность: failed\n" in text:
                        raise main.EvaluationExhausted("test failure")
                    return "MATCH", 80, "данные", "Detailed reason", "общее"
                calls = []
                original_top = main.Worker._write_top
                def top(writer, settings):
                    original_top(worker, writer, settings)
                    calls.append(1)
                    if len(calls) >= 2:
                        stop.set()
                worker._write_top = top
                with patch.object(main, "RESULTS_DIR", results), patch.object(main, "CACHE_DIR", cache), \
                     patch.object(main.HHClient, "search", return_value=(items, 0)), \
                     patch.object(main.HHClient, "description", side_effect=lambda url: "" if url == "missing" else long_text), \
                     patch.object(main.LLMClient, "check", return_value="test"), \
                     patch.object(main.LLMClient, "evaluate", side_effect=evaluate), \
                     patch.object(main.Worker, "pause"):
                    worker.run()
                self.assertFalse(any("ОШИБКА:" in str(event) for event in list(worker.q.queue)))
                return evaluated

            first = run_once()
            self.assertEqual(len(first), 2)
            self.assertTrue(all(text.endswith("END OF DESCRIPTION") for text in first))
            second = run_once()
            self.assertEqual(len(second), 1)
            self.assertIn("Должность: failed", second[0])
            with closing(sqlite3.connect(os.path.join(cache, "evaluations.sqlite3"))) as db:
                states = dict(db.execute("SELECT id,status FROM evaluations"))
            self.assertEqual(states, {"missing": "incomplete", "failed": "failed", "good": "evaluated"})


if __name__ == "__main__":
    unittest.main()
