import json
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from evidence_eval import VALUES
from storage import SearchCache, extraction_key, prioritize, search_scope


class OptimizationTests(unittest.TestCase):
    def test_queue_and_actions_survive_restart_and_are_scoped(self):
        with tempfile.TemporaryDirectory() as folder:
            path=str(Path(folder)/'state.sqlite3')
            cache=SearchCache(path)
            item=dict(id='1',name='Project assistant',url='https://hh.ru/vacancy/1')
            cache.enqueue('a',[item,item]);cache.set_action(item['url'],'Откликнулся');cache.close()
            cache=SearchCache(path)
            self.assertEqual(cache.pending('a'),[item]);self.assertEqual(cache.pending('b'),[])
            self.assertEqual(cache.action(item['url']),'Откликнулся')
            cache.remove('a','1');self.assertEqual(cache.pending('a'),[]);cache.close()

    def test_facts_reused_but_changed_content_calls_model(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchCache(str(Path(folder)/'state.sqlite3'))
            client=main.LLMClient('http://invalid','model',lambda _:None)
            client.fact_cache=cache
            raw={k:dict(value='unknown',line=None) for k in VALUES}
            with patch.object(client,'_chat_retrying',return_value=json.dumps(raw)) as call:
                first=client.evaluate('profile1','Описание: Текст вакансии')
                self.assertEqual(first,client.evaluate('profile2','Описание: Текст вакансии'))
                self.assertEqual(call.call_count,1)
                self.assertTrue(client.last_evidence['cache_hit'])
                client.evaluate('profile2','Описание: Изменённый текст')
                self.assertEqual(call.call_count,2)
            cache.close()

    def test_protected_titles_do_not_call_model(self):
        client=main.LLMClient('http://invalid','fast',lambda _:None)
        with patch.object(client,'_chat_retrying',side_effect=AssertionError('unnecessary inference')):
            self.assertEqual(client.triage('profile',[dict(id='1',name='Junior Project Manager'),dict(id='2',name='Неизвестная роль')]),{'1','2'})

    def test_priority_keeps_reserve_quota(self):
        items=[dict(id=str(i),name='Координатор',experience='between1And3') for i in range(8)]
        items += [dict(id='reserve',name='Support'),dict(id='new',name='Координатор',experience='noExperience')]
        ordered=prioritize(items)
        self.assertEqual(ordered[0]['id'],'new');self.assertEqual(ordered[4]['id'],'reserve')
        self.assertEqual(len(ordered),len(items))

    def test_limit_resume_and_both_experience_streams(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg=dict(main.DEFAULT_CONFIG,queries='test',role_ids=[],triage=False,pages=1,
                experience='Без опыта + 1–3 года',exclude_words='',include_words='',remote_extra=False,
                max_checks=1,min_delay=0,max_delay=0,recs_enabled=False,manage_local_models=False)
            items=[dict(id=str(i),name=f'Координатор {i}',employer='Example',salary='?',url=str(i)) for i in range(3)]
            requested=[];evaluated=[]
            def search(*args,**kwargs):
                requested.append(args[2]);return items,0
            def evaluate(_self,profile,text):
                evaluated.append(text);return 'MATCH',80,'координация','reason','координатор'
            with patch.object(main,'RESULTS_DIR',folder),patch.object(main,'CACHE_DIR',folder),patch.object(main.HHClient,'search',side_effect=search),patch.object(main.HHClient,'description',return_value='description'),patch.object(main.LLMClient,'check',return_value='test'),patch.object(main.LLMClient,'evaluate',evaluate),patch.object(main.Worker,'pause'):
                for _ in range(3):
                    worker=main.Worker(cfg,'profile',queue.Queue(),threading.Event());worker.run()
                    self.assertFalse(any('ОШИБКА:' in str(x) for x in worker.q.queue))
            self.assertEqual(len(evaluated),3);self.assertEqual(len(set(evaluated)),3)
            self.assertIn('noExperience',requested);self.assertIn('between1And3',requested)
            cache=SearchCache(str(Path(folder)/'search.sqlite3'))
            self.assertEqual(cache.db.execute('SELECT COUNT(*) FROM pending').fetchone()[0],0)
            cache.close()

    def test_policy_changes_decision_without_regenerating_facts(self):
        with tempfile.TemporaryDirectory() as folder:
            cache=SearchCache(str(Path(folder)/'state.sqlite3'))
            client=main.LLMClient('http://invalid','model',lambda _:None);client.fact_cache=cache
            raw={k:dict(value='unknown',line=None) for k in VALUES}
            with patch.object(client,'_chat_retrying',return_value=json.dumps(raw)) as call:
                text='Описание: Требования:\nОпыт работы координатором от года'
                self.assertEqual(client.evaluate('profile',text)[0],'REJECT')
                client.decision_policy={'reject_experience':False}
                self.assertNotEqual(client.evaluate('profile',text)[0],'REJECT')
                self.assertEqual(call.call_count,1)
            cache.close()

    def test_repair_accepts_only_requested_fields(self):
        client=main.LLMClient('http://invalid','model',lambda _:None)
        raw={k:dict(value='unknown',line=None) for k in VALUES}
        raw['experience']=dict(value='required',line=1)
        def chat(*args,**kwargs):
            if client.response_schema == main.FACT_SCHEMA:
                return json.dumps(raw)
            response=json.dumps({'experience':dict(value='unknown',line=None)})
            self.assertEqual(client.response_schema['required'],['experience'])
            self.assertTrue(kwargs['validator'](response))
            self.assertFalse(kwargs['validator']('{}'))
            return response
        with patch.object(client,'_chat_retrying',side_effect=chat) as call:
            client.evaluate('profile','Описание: Просто описание компании')
            self.assertEqual(call.call_count,2)
            self.assertEqual(client.last_evidence['raw']['experience']['value'],'unknown')

    def test_scope_ignores_limits_but_respects_filters(self):
        self.assertEqual(search_scope({'max_checks':1},'v'),search_scope({'max_checks':200},'v'))
        self.assertNotEqual(search_scope({'area':'Москва'},'v'),search_scope({'area':'Вся Россия'},'v'))


if __name__ == '__main__': unittest.main()
