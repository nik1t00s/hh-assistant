import tempfile
import unittest
from pathlib import Path
import requests
from main import hh_response_diagnostic
from storage import SearchCache, EvaluationStore


class DeferredTests(unittest.TestCase):
    def test_persists_excludes_rediscovery_and_restores_explicitly(self):
        with tempfile.TemporaryDirectory() as folder:
            path = str(Path(folder)/'queue.db')
            cache = SearchCache(path)
            cache.enqueue('a', [dict(id='1'), dict(id='2')])
            cache.enqueue('b', [dict(id='1')])
            cache.migrate_deferred('a', {'1'})
            cache.close()
            cache = SearchCache(path)
            try:
                cache.enqueue('a', [dict(id='1')])
                self.assertEqual(cache.pending('a'), [dict(id='2')])
                self.assertEqual(cache.pending('b'), [dict(id='1')])
                self.assertEqual(cache.restore_deferred('a'), 1)
                cache.migrate_deferred('a', {'1'})
                self.assertEqual(len(cache.pending('a')), 2)
                cache.defer('a', '1')
                cache.remove('a', '1')
                self.assertEqual(cache.deferred_ids('a'), set())
            finally: cache.close()

    def test_migration_uses_only_incomplete_forbidden_in_current_version(self):
        with tempfile.TemporaryDirectory() as folder:
            store = EvaluationStore(str(Path(folder)/'eval.db'), 'v')
            try:
                store.mark('1', 'incomplete', 'доступ запрещён (HTTP 403)')
                store.mark('2', 'incomplete', 'страница капчи (HTTP 403)')
                store.mark('3', 'evaluated', 'доступ запрещён (HTTP 403)')
                self.assertEqual(store.forbidden_ids(), {'1'})
            finally: store.close()

    def test_diagnostic_does_not_echo_secrets(self):
        r = requests.Response()
        r.status_code = 403
        r.url = 'https://hh.ru/vacancy/123?token=SECRET'
        r.headers['Content-Type'] = 'text/html; private=SECRET'
        r.headers['Set-Cookie'] = 'SECRET'
        r._content = b'<title>SECRET</title>Forbidden proxy error'
        before = requests.Response()
        before.status_code = 302
        before.url = 'https://private-secret.example/account/SECRET'
        r.history = [before]
        message = hh_response_diagnostic(r)
        self.assertNotIn('SECRET', message)
        self.assertNotIn('private-secret', message)
        self.assertIn('403:HH/вакансия', message)
        self.assertIn('текст ошибки прокси', message)
