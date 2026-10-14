import queue
import tempfile
import threading
import unittest
from unittest.mock import patch
import main


class ResumeTests(unittest.TestCase):
    def test_resume_limit_captcha_and_no_duplicate_evaluation(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = dict(main.DEFAULT_CONFIG, queries='synthetic', role_ids=['1'], split_roles=True, triage=False,
                       exclude_words='', include_words='', remote_extra=False, pages=1,
                       max_checks=1, min_delay=0, max_delay=0, manage_local_models=False,
                       recs_enabled=False, single_pass=False, hh_cookie='session=synthetic')
            items = [dict(id=str(i), name='Координатор', employer='Example', salary='?', url=str(i)) for i in range(3)]
            def run(resume=False):
                worker = main.Worker(dict(cfg, resume_queue_only=resume), 'synthetic', queue.Queue(), threading.Event())
                worker.run()
                messages = list(worker.q.queue)
                self.assertFalse(any('ОШИБКА:' in str(m) for m in messages), messages)
                return next(payload for kind, payload in messages if kind == 'done')
            with patch.object(main, 'RESULTS_DIR', folder), patch.object(main, 'CACHE_DIR', folder), \
                 patch.object(main.HHClient, 'search', return_value=(items, 0)) as search, \
                 patch.object(main.HHClient, 'description', autospec=True, return_value='description') as description, \
                 patch.object(main.LLMClient, 'check', return_value='synthetic'), \
                 patch.object(main.LLMClient, 'evaluate', return_value=('MATCH', 80, 'project', 'reason', 'project')) as evaluate, \
                 patch.object(main.Worker, 'pause'), patch.object(main.Worker, '_role_names', return_value={}) as roles:
                self.assertIn('Достигнут лимит', run())
                client = description.call_args.args[0]
                self.assertEqual(client.session.cookies.get('session'), 'synthetic')
                search.reset_mock()
                roles.reset_mock()
                description.side_effect = main.HHAccessRestriction(403, 'страница капчи', 'synthetic')
                self.assertIn('HH: страница капчи (HTTP 403)', run(True))
                self.assertEqual(evaluate.call_count, 1)
                description.side_effect = None
                self.assertIn('Осталось в очереди: 1', run(True))
                self.assertIn('Очередь обработана', run(True))
                self.assertIn('Нет сохранённой очереди', run(True))
                search.assert_not_called()
                roles.assert_not_called()
                self.assertEqual(evaluate.call_count, 3)

    def test_manual_stop_and_error_are_distinct(self):
        for error, expected in [(False, 'Остановлено вами'), (True, 'из-за ошибки')]:
            worker = main.Worker({}, '', queue.Queue(), threading.Event())
            worker.stop_event.set()
            with patch.object(worker, 'log'), patch.object(worker, '_run', side_effect=RuntimeError('synthetic') if error else None):
                worker.run()
            self.assertIn(expected, worker.q.get()[1])
