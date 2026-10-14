import queue
import tempfile
import threading
import unittest
from unittest.mock import patch
import main
from storage import SearchCache
from pathlib import Path


class ForbiddenTests(unittest.TestCase):
    def test_isolated_forbidden_keeps_queue_and_evaluates_next(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = dict(main.DEFAULT_CONFIG, queries='synthetic', role_ids=[], triage=False,
                       exclude_words='', include_words='', remote_extra=False, pages=1,
                       min_delay=0, max_delay=0, manage_local_models=False, recs_enabled=False,
                       single_pass=True)
            items = [dict(id=str(i), name='Координатор', employer='Example', salary='?', url=str(i)) for i in range(3)]
            stop = threading.Event()
            worker = main.Worker(cfg, 'synthetic', queue.Queue(), stop)
            with patch.object(main, 'RESULTS_DIR', folder), patch.object(main, 'CACHE_DIR', folder), \
                 patch.object(main.HHClient, 'search', return_value=(items, 0)), \
                 patch.object(main.HHClient, 'description', side_effect=[main.HHAccessRestriction(403, 'доступ запрещён', ''), 'description', 'description']) as desc, \
                 patch.object(main.LLMClient, 'check', return_value='synthetic'), \
                 patch.object(main.LLMClient, 'evaluate', return_value=('MATCH',80,'project','reason','project')) as evaluate, \
                 patch.object(main.Worker, 'pause'), patch.object(stop, 'wait', return_value=False) as wait:
                worker.run()
            self.assertEqual(desc.call_count, 3)
            self.assertEqual(evaluate.call_count, 2)
            wait.assert_any_call(60)
            self.assertFalse(stop.is_set())
            cache = SearchCache(str(Path(folder)/'search.sqlite3'))
            try:
                self.assertEqual(cache.pending(worker.queue_scope), [])
                self.assertEqual(cache.deferred_ids(worker.queue_scope), {'0'})
                self.assertEqual([i['id'] for i in cache.pending(worker.queue_scope, include_deferred=True)], ['0'])
            finally:
                cache.close()
            self.assertFalse(any('ОШИБКА:' in str(x) for x in worker.q.queue))

    def test_consecutive_and_total_thresholds(self):
        for separated in (False, True):
            worker = main.Worker({}, '', queue.Queue(), threading.Event())
            with patch.object(worker, 'log'), patch.object(worker.stop_event, 'wait', return_value=False):
                for i in range(3 if separated else 2):
                    if separated: worker.hh_forbidden_streak = 0
                    worker._handle_description_restriction(main.HHAccessRestriction(403,'доступ запрещён',''))
                    self.assertEqual(worker.stop_event.is_set(), i == (2 if separated else 1))

    def test_captcha_rate_limit_and_manual_stop(self):
        for status, category in [(429,'слишком много запросов'),(403,'страница капчи'),(200,'страница капчи')]:
            worker = main.Worker({}, '', queue.Queue(), threading.Event())
            with patch.object(worker, 'log'), patch.object(worker.stop_event, 'wait') as wait:
                worker._handle_description_restriction(main.HHAccessRestriction(status, category, ''))
                self.assertTrue(worker.stop_event.is_set())
                wait.assert_not_called()
        worker = main.Worker({}, '', queue.Queue(), threading.Event())
        with patch.object(worker, 'log'), patch.object(worker.stop_event, 'wait', side_effect=lambda _: worker.stop_event.set()):
            worker._handle_description_restriction(main.HHAccessRestriction(403,'доступ запрещён',''))
        self.assertTrue(worker.stop_event.is_set())
        self.assertIsNone(worker.finish_reason)
