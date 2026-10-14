import queue
import threading
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import main
from evidence_eval import VALUES, verify_facts, decide
from storage import SearchCache, search_scope

class SearchReliabilityTests(unittest.TestCase):
    def test_optional_conditions_never_become_hard_rejects(self):
        for key,value,quote in [
            ('travel','regular','Регулярные командировки не требуются.'),
            ('night','required','Ночные смены возможны по желанию.'),
            ('travel','regular','Разъездная работа по желанию.'),
            ('experience','required','Опыт работы координатором в учебном проекте.'),
        ]:
            with self.subTest(quote=quote):
                source='Должность: Координатор IT проектов\nОписание: Требования:\n'+quote
                facts={k:dict(value='unknown',quote='') for k in VALUES}
                facts[key]=dict(value=value,quote=quote)
                self.assertNotEqual(decide(*verify_facts(facts, source))[0], 'REJECT')

    def test_real_requirements_still_reject(self):
        for key,value,quote in [('travel','regular','Регулярные командировки каждую неделю.'),
                                 ('night','required','Обязательные ночные смены.'),
                                 ('experience','required','Коммерческий опыт работы координатором от 2 лет.')]:
            facts={k:dict(value='unknown',quote='') for k in VALUES}
            facts[key]=dict(value=value,quote=quote)
            self.assertEqual(decide(*verify_facts(facts,'Описание: Требования:\n'+quote))[0], 'REJECT')

    def test_queue_survives_new_rules_but_not_new_filters(self):
        self.assertEqual(search_scope({'area':'Москва'},'old'),search_scope({'area':'Москва'},'new'))
        self.assertNotEqual(search_scope({'exclude_words':'повар'},'v'),search_scope({'exclude_words':'врач'},'v'))

    def test_description_expires_and_cursor_persists(self):
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'test.db');cache=SearchCache(path)
            with patch('storage.time.time',return_value=100000):cache.save_description('url','body')
            with patch('storage.time.time',return_value=100010):self.assertEqual(cache.cached_description('url'),'body')
            with patch('storage.time.time',return_value=200000):self.assertIsNone(cache.cached_description('url'))
            cache.set_source_position('scope',3);cache.close()
            cache=SearchCache(path);self.assertEqual(cache.source_position('scope'),3);cache.close()

    def test_rejections_remain_in_history_without_becoming_suitable(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(main,'RESULTS_DIR',folder):
            writer=main.ResultWriter('v')
            item=dict(id='test',url='https://example.org/1',name='Test',employer='Example',salary='?')
            writer.write(item,0,'REJECT',None,'общее','reason',False)
            app=object.__new__(main.App)
            rows=app._read_history_rows()
            self.assertEqual(rows[0]['verdict'],'REJECT');self.assertFalse(rows[0]['suitable'])

    def test_worker_resumes_after_rule_change_and_uses_description_cache(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg=dict(main.DEFAULT_CONFIG,queries='example',role_ids=[],triage=False,
                     include_words='',exclude_words='',exclude_companies='',pages=1,
                     max_checks=1,min_delay=0,max_delay=0,manage_local_models=False,
                     recs_enabled=False,remote_extra=False,single_pass=True,
                     habr_enabled=False,telegram_enabled=False,superjob_enabled=False)
            items=[dict(id=str(i),name='Координатор',employer='Example',salary='?',url=str(i)) for i in range(2)]
            def run(resume=False):
                w=main.Worker(dict(cfg,resume_queue_only=resume),'example',queue.Queue(),threading.Event())
                w.run()
                self.assertFalse(any('ОШИБКА:' in str(m) for m in w.q.queue))
            with patch.object(main,'RESULTS_DIR',folder),patch.object(main,'CACHE_DIR',folder), \
                 patch.object(main.HHClient,'search',return_value=(items,0)) as search, \
                 patch.object(main.HHClient,'description',return_value='description') as description, \
                 patch.object(main.LLMClient,'check',return_value='test'), \
                 patch.object(main.LLMClient,'evaluate',return_value=('MATCH',80,'project','reason','project')) as evaluate:
                run()
                cfg['lm_reasoning_effort']='low'
                search.reset_mock()
                run(True)
                search.assert_not_called()
                self.assertEqual(evaluate.call_count,2)
                # New rule version rediscovers the first item, but reuses its description.
                run()
                self.assertEqual(description.call_count,2)
                self.assertEqual(evaluate.call_count,3)

    def test_auto_start_consumes_queue_then_collects_with_shared_budget(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg=dict(main.DEFAULT_CONFIG,queries='example',role_ids=[],triage=False,
                     include_words='',exclude_words='',exclude_companies='',pages=1,
                     max_checks=0,min_delay=0,max_delay=0,manage_local_models=False,
                     recs_enabled=False,remote_extra=False,single_pass=True,
                     habr_enabled=False,telegram_enabled=False,superjob_enabled=False,
                     auto_continue_queue=True)
            def item(i):return dict(id=str(i),name='Координатор',employer='Example',salary='?',url=str(i))
            cache=SearchCache(str(Path(folder)/'search.sqlite3'))
            cache.enqueue(search_scope(cfg,'v'),[item(1)]);cache.close()
            order=[]
            def search(*a,**k):order.append('search');return [item(1),item(2)],0
            def evaluate(*a,**k):order.append('evaluate');return ('MATCH',80,'project','reason','project')
            with patch.object(main,'RESULTS_DIR',folder),patch.object(main,'CACHE_DIR',folder), \
                 patch.object(main.HHClient,'search',side_effect=search), \
                 patch.object(main.HHClient,'description',return_value='description'), \
                 patch.object(main.LLMClient,'check',return_value='test'), \
                 patch.object(main.LLMClient,'evaluate',side_effect=evaluate),patch.object(main.Worker,'pause'):
                w=main.Worker(cfg,'example',queue.Queue(),threading.Event());w.run()
            self.assertEqual(order,['evaluate','search','evaluate'])
            self.assertEqual(w.checked_count,2)
            self.assertFalse(any('ОШИБКА:' in str(m) for m in w.q.queue))

    def test_hh_wait_can_be_cancelled_before_network(self):
        from unittest.mock import Mock
        w=main.Worker({'min_delay':20,'max_delay':30},'',queue.Queue(),threading.Event())
        w._last_hh_request=100
        w.stop_event=Mock();w.stop_event.is_set.return_value=False;w.stop_event.wait.return_value=True
        client=main.HHClient(lambda _:None);client.before_request=w._before_hh_request
        client.session.get=Mock()
        with patch('main.time.monotonic',return_value=105),patch('main.random.uniform',return_value=20):
            with self.assertRaises(RuntimeError):client._get('https://hh.ru/vacancy/1')
        client.session.get.assert_not_called()
        w.stop_event.wait.assert_called_once_with(15)
