import copy
import queue
import tempfile
import threading
import unittest
from unittest.mock import patch
from requests.utils import select_proxy
import requests

import main
from evidence_eval import VALUES, decide
from storage import SearchCache, entry_search_passes, ordered_search_passes, prioritize
from vacancy_rules import short_profile
from llm_client import StreamingLLMClient


class EntryPriorityTests(unittest.TestCase):
    def test_local_llm_bypasses_proxy_but_remote_does_not(self):
        environment = {'HTTP_PROXY': 'http://proxy.invalid:1234', 'HTTPS_PROXY': 'http://proxy.invalid:1234',
                       'ALL_PROXY': 'http://proxy.invalid:1234', 'NO_PROXY': ''}
        with patch.dict('os.environ', environment, clear=True):
            for url in ['http://localhost:1234/v1', 'http://127.0.0.1:1234/v1', 'http://[::1]:1234/v1']:
                client = StreamingLLMClient(url, 'test', lambda _: None)
                options = client._connection_options()
                with requests.Session() as session:
                    merged = session.merge_environment_settings(url, dict(options['proxies']), True, None, None)
                self.assertFalse(select_proxy(url, merged['proxies']))
                with patch('llm_client.requests.get') as get:
                    get.return_value.json.return_value = {'data': [{'id': 'test'}]}
                    self.assertEqual(client.list_models(), ['test'])
                    self.assertEqual(get.call_args.kwargs['proxies'], options['proxies'])
            remote = StreamingLLMClient('https://example.invalid/v1', 'test', lambda _: None)
            self.assertEqual(remote._connection_options(), {})

    def test_entry_queue_is_stable_and_does_not_drop_other_directions(self):
        items = [dict(id='experienced', name='Support', experience='between1And3'),
                 dict(id='project', name='Project assistant', experience='noExperience'),
                 dict(id='technical', name='Application support', experience='noExperience'),
                 dict(id='intern', name='Стажёр QA'),
                 dict(id='junior', name='Junior infrastructure'),
                 dict(id='unknown', name='Специалист'),
                 dict(id='senior', name='Стажёр отдела', experience='moreThan6')]
        ordered = prioritize(items, entry_first=True)
        self.assertEqual([x['id'] for x in ordered],
                         ['technical', 'project', 'intern', 'junior', 'unknown', 'experienced', 'senior'])
        self.assertEqual(items[0]['id'], 'experienced')

    def test_sources_and_cursor_keep_entry_sources_first(self):
        passes = entry_search_passes([('a', {'query': 'a'}), ('b', {'query': 'b'}),
                                     ('extra', {'source': 'habr', 'query': 'a'})])
        self.assertEqual([src.get('experience') for _, src in passes],
                         ['noExperience', 'noExperience', 'between1And3', 'between1And3', None])
        for offset in range(len(passes)):
            ordered = ordered_search_passes(passes, offset)
            self.assertEqual({index for index, _ in ordered}, set(range(len(passes))))
            self.assertTrue(all(src['experience'] == 'noExperience' for _, (_, src) in ordered[:2]))
            self.assertTrue(all(passes[index] == entry for index, entry in ordered))

    def test_reloaded_queue_uses_the_same_priority(self):
        with tempfile.TemporaryDirectory() as folder:
            path = folder + '/queue.sqlite3'
            cache = SearchCache(path)
            cache.enqueue('scope', [dict(id='old', name='Support', experience='between1And3'),
                                    dict(id='entry', name='Support', experience='noExperience')])
            cache.close()
            cache = SearchCache(path)
            self.assertEqual(prioritize(cache.pending('scope'), entry_first=True)[0]['id'], 'entry')
            cache.close()

    def test_technical_roles_are_primary_without_weakening_hard_stops(self):
        facts = {key: dict(value='unknown', quote='') for key in VALUES}
        facts['it'] = dict(value='yes', quote='IT')
        policy = {'preferred_roles': ['support', 'admin', 'implementation', 'project']}
        scores = []
        for role in policy['preferred_roles']:
            facts['role'] = dict(value=role, quote='Рабочие задачи')
            result = decide(facts, [], policy)
            self.assertEqual(result[0], 'MATCH')
            self.assertIn('зарплата', result[3])
            scores.append(result[1])
        self.assertEqual(scores, sorted(scores, reverse=True))
        for role in ['qa', 'data']:
            facts['role']['value'] = role
            self.assertEqual(decide(facts, [], policy)[0], 'WEAK')
        facts['role']['value'] = 'support'
        for field, value in [('experience', 'required'), ('night', 'required'), ('contract', 'no_tk')]:
            facts[field] = dict(value=value, quote='Явное требование')
            self.assertEqual(decide(facts, [], policy)[0], 'REJECT')
            facts[field] = dict(value='unknown', quote='')
        facts['salary'] = dict(value='stated', quote='30 000 рублей на руки в месяц')
        self.assertEqual(decide(facts, [], policy)[0], 'REJECT')

    def test_short_profile_reads_new_summary_heading(self):
        self.assertEqual(short_profile('# Профиль\n' + 'контекст ' * 300 +
                                       '\n## Коротко\nApplication Support\n\n## Очередь\nДругое'),
                         'Application Support')

    def test_start_form_preserves_role_priorities(self):
        class Value:
            def __init__(self, value): self.value = value
            def get(self, *args): return self.value
        class Inputs:
            def __getattr__(self, name): return Value('1')
        app = Inputs()
        app.cfg = copy.deepcopy(main.DEFAULT_CONFIG)
        app.cfg['decision_policy']['preferred_roles'] = ['support', 'admin', 'project']
        app.var_dmin, app.var_dmax = Value(20), Value(30)
        app.ui = Inputs()
        app.ui.policy_vars = {'reject_experience': Value(True)}
        app.ui.minimum_salary = Value('40000')
        with patch.object(main, 'save_config') as save:
            cfg = main.App._collect_config(app)
        self.assertEqual(cfg['decision_policy']['preferred_roles'], ['support', 'admin', 'project'])
        self.assertEqual(save.call_args.args[0]['decision_policy']['minimum_net_salary'], 40000)

    def test_worker_collects_and_evaluates_entry_first_without_network(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = dict(main.DEFAULT_CONFIG, queries='alpha\nbeta', role_ids=[], pages=1,
                       triage=False, include_words='', exclude_words='', remote_extra=False,
                       experience='Без опыта + 1–3 года', search_mode='Расширенный', max_checks=0)
            requested, evaluated = [], []
            def search(query, area, experience, *args, **kwargs):
                requested.append(experience)
                identity = query + '-' + experience
                return [dict(id=identity, name='Support', experience=experience,
                             employer='Example', salary='', url=identity)], 0
            def evaluate(profile, source):
                evaluated.append('noExperience' if 'noExperience' in source else 'between1And3')
                return 'MATCH', 80, 'техподдержка', 'reason', 'общее'
            worker = main.Worker(cfg, 'Synthetic profile', queue.Queue(), threading.Event())
            with patch.object(main, 'RESULTS_DIR', folder), patch.object(main, 'CACHE_DIR', folder), \
                 patch.object(main.HHClient, 'search', side_effect=search), \
                 patch.object(main.HHClient, 'description', side_effect=lambda url: url), \
                 patch.object(main.LLMClient, 'check', return_value='test'), \
                 patch.object(main.LLMClient, 'evaluate', side_effect=evaluate), \
                 patch.object(main.Worker, 'pause'):
                worker.run()
            self.assertEqual(requested, ['noExperience'] * 2 + ['between1And3'] * 2)
            self.assertEqual(evaluated, ['noExperience'] * 2 + ['between1And3'] * 2)
            self.assertFalse(any('ОШИБКА:' in str(event) for event in worker.q.queue))
