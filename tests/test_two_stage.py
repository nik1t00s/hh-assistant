import json
import queue
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import main
from evidence_eval import VALUES, verify_facts, decide
from llm_client import LocalModelManager, StreamingLLMClient
from storage import evaluation_fingerprint


class TwoStageTests(unittest.TestCase):
    def test_reasoning_and_context_change_cache_version(self):
        baseline = evaluation_fingerprint('profile', {}, 'main', 'fast', [])
        for cfg in [{'lm_reasoning_effort':'high'}, {'model_context':16384}]:
            self.assertNotEqual(baseline, evaluation_fingerprint('profile', cfg, 'main', 'fast', []))

    def test_reasoning_stream_is_not_mixed_into_final_json(self):
        class Response:
            status_code = 200
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def iter_lines(self, **kwargs):
                for event in [
                    {'choices':[{'delta':{'reasoning_content':'synthetic reasoning'}}]},
                    {'choices':[{'delta':{'content':'{"ok":true}'},'finish_reason':'stop'}]},
                    {'choices':[], 'usage':{'prompt_tokens':100,'completion_tokens':20,'total_tokens':120}},
                ]:
                    yield ('data: '+json.dumps(event)).encode()
                yield b'data: [DONE]'
        client = StreamingLLMClient('http://example.invalid','test',lambda _:None)
        client.reasoning_effort = 'high'
        with patch('llm_client.requests.post', return_value=Response()) as call:
            self.assertEqual(client._chat('system','user',0.1,4000), '{"ok":true}')
            self.assertEqual(call.call_args.kwargs['json']['reasoning_effort'], 'high')
        self.assertGreater(client.last_reasoning_chars, 0)
        self.assertEqual(client.last_usage['total_tokens'], 120)

    def test_model_selection_never_silently_substitutes(self):
        client = StreamingLLMClient('http://example.invalid', 'missing', lambda _: None)
        with patch.object(client, 'list_models', return_value=['small','large']):
            with self.assertRaises(RuntimeError): client.check()
        client.model = 'gemma'
        with patch.object(client, 'list_models', return_value=['gemma-12','gemma-26']):
            with self.assertRaises(RuntimeError): client.check()
        client.model = 'gemma-26'
        with patch.object(client, 'list_models', return_value=['gemma-26-draft','gemma-26']):
            self.assertEqual(client.check(), 'gemma-26')

    def test_omitted_seniority_is_found_but_junior_middle_survives(self):
        facts = {k: dict(value='unknown', quote='') for k in VALUES}
        checked, issues = verify_facts(facts, 'Должность: Middle Project Manager\nОписание: задачи')
        self.assertEqual(decide(checked, issues)[0], 'REJECT')
        checked, _ = verify_facts(facts, 'Должность: Junior/Middle Project Manager\nОписание: задачи')
        self.assertEqual(checked['level']['value'], 'unknown')

    def test_non_it_company_with_it_function_is_not_rejected_by_company(self):
        facts = {k: dict(value='unknown', quote='') for k in VALUES}
        facts['it'] = dict(value='no', quote='Компания занимается розничной торговлей')
        checked, issues = verify_facts(facts, 'Описание: Компания занимается розничной торговлей\nРабота в IT-отделе')
        self.assertEqual(checked['it']['value'], 'unknown')
        self.assertEqual(decide(checked, issues)[0], 'REVIEW')

    def test_section_heading_is_not_role_evidence(self):
        facts = {k: dict(value='unknown', quote='') for k in VALUES}
        facts['role'] = dict(value='support', quote='Обязанности:')
        verified, issues = verify_facts(facts, 'Описание: Обязанности:\nВедение кадровых документов')
        self.assertEqual(verified['role']['value'], 'unknown')
        self.assertEqual(decide(verified, issues)[0], 'REVIEW')

    def test_experience_sections_and_missing_model_requirement(self):
        for text, expected in [
            ('Требования:\nОпыт работы ассистентом проекта;', 'required'),
            ('Требования:\nОпыт аналогичной работы не менее 1 года;', 'required'),
            ('Требования:\nОпыт работы в технической поддержке пользователей (от 3 лет)', 'required'),
            ('Наши пожелания к кандидату\nОпыт работы на аналогичной должности', 'optional'),
            ('Будет преимуществом:\nОпыт работы координатором\nТребования:\nОпыт работы ассистентом проекта', 'required'),
            ('Requirements:\nMinimum of 1.5 years of experience as a personal assistant', 'required'),
        ]:
            facts = {k: dict(value='unknown', quote='') for k in VALUES}
            facts['experience'] = dict(value='required', quote=text.splitlines()[-1])
            verified, issues = verify_facts(facts, 'Описание: '+text)
            self.assertEqual(verified['experience']['value'], expected, text)
            self.assertFalse(any(i.startswith('experience:') for i in issues), text)

    def test_conflicting_beginner_allowance_requires_review(self):
        facts = {k: dict(value='unknown', quote='') for k in VALUES}
        verified, issues = verify_facts(facts, 'Описание: Требования:\nОпыт работы координатором от года\nРассмотрим без опыта')
        self.assertEqual(decide(verified, issues)[0], 'REVIEW')
        self.assertTrue(any('противоречие' in i for i in issues))

    def test_unknown_conditions_do_not_hide_project_role(self):
        facts = {k: dict(value='unknown', quote='') for k in VALUES}
        facts['it'] = dict(value='yes', quote='Координация IT-проектов')
        facts['role'] = dict(value='project', quote='Координация IT-проектов')
        verdict, score, _, reason, _ = decide(facts, [])
        self.assertEqual(verdict, 'MATCH')
        self.assertLess(score, 80)
        self.assertIn('зарплата', reason)
        self.assertIn('ТК', reason)
        facts['contract'] = dict(value='no_tk', quote='Только самозанятость')
        self.assertEqual(decide(facts, [])[0], 'REJECT')

    def test_triage_only_titles_and_protected_roles(self):
        client = main.LLMClient('http://example.invalid', 'fast', lambda _: None)
        items = [dict(id='1', name='Junior/Middle project manager', employer='SECRET', salary='SECRET', experience='between3And6'),
                 dict(id='2', name='Повар', employer='SECRET', salary='SECRET'),
                 dict(id='3', name='Специалист по информационным технологиям'),
                 dict(id='4', name='Младший проджект-менеджер (IT)'),
                 dict(id='5', name='Неоднозначное название'),
                 dict(id='6', name='Руководитель направления'),
                 dict(id='7', name='Водитель')]
        with patch.object(client, '_chat_retrying', return_value='{"exclude_ids":["1","2","3","4","5","6","7","foreign"]}') as call:
            self.assertEqual(client.triage('profile', items), {'1','3','4','5','6'})
            prompt = call.call_args.args[1]
            self.assertNotIn('SECRET', prompt)
            self.assertNotIn('опыт:', prompt)

    def test_model_switch_unloads_configured_model_before_load(self):
        manager = LocalModelManager.__new__(LocalModelManager)
        manager.active = None; manager.models = {'small', 'large'}
        manager.stop_event = threading.Event(); manager.log = lambda _: None; manager.gpu = {'large': 0.3}
        manager.context_length = 8192
        loaded = [dict(type='llm', modelKey='small', identifier='small', status='idle')]
        with patch.object(manager, '_run', side_effect=[json.dumps(loaded), '', '']) as run:
            manager.activate('large')
            self.assertEqual(run.call_args_list[1].args, ('unload', 'small'))
            self.assertEqual(run.call_args_list[2].args[:2], ('load', 'large'))
            manager.activate('large')
            self.assertEqual(run.call_count, 3)

    def test_model_switch_does_not_unload_unrelated_model(self):
        manager = LocalModelManager.__new__(LocalModelManager)
        manager.active = None; manager.models = {'small', 'large'}
        manager.stop_event = threading.Event()
        with patch.object(manager, '_run', return_value=json.dumps([dict(type='llm',modelKey='other',status='idle')])) as run:
            with self.assertRaises(RuntimeError): manager.activate('large')
            self.assertEqual(run.call_count, 1)

    def test_context_change_reloads_matching_model(self):
        manager = LocalModelManager.__new__(LocalModelManager)
        manager.active = None; manager.models = {'large'}; manager.context_length = 16384
        manager.stop_event = threading.Event(); manager.log = lambda _: None; manager.gpu = {}
        loaded = [dict(type='llm', modelKey='large', identifier='large', status='idle', contextLength=8192)]
        with patch.object(manager, '_run', side_effect=[json.dumps(loaded), '', '']) as run:
            manager.activate('large')
            self.assertEqual(run.call_args_list[1].args, ('unload', 'large'))
            self.assertIn('16384', run.call_args_list[2].args)

    def test_all_sources_collected_before_evaluation_and_queue_deduplicated(self):
        with tempfile.TemporaryDirectory() as folder:
            cfg = dict(main.DEFAULT_CONFIG, role_ids=[], queries='one\ntwo', triage=False,
                       exclude_words='', include_words='', pages=1, remote_extra=False)
            stop = threading.Event(); events = []
            worker = main.Worker(cfg, 'profile', queue.Queue(), stop)
            item = dict(id='same', name='Координатор', employer='Example', salary='?', url='same')
            def search(*a, **k): events.append('search'); return [item], 0
            def evaluate(*a): events.append('evaluate'); stop.set(); return 'MATCH',80,'координация','reason','координатор'
            with patch.object(main,'RESULTS_DIR',folder), patch.object(main,'CACHE_DIR',folder), \
                 patch.object(main.HHClient,'search',side_effect=search), \
                 patch.object(main.HHClient,'description',return_value='Description'), \
                 patch.object(main.LLMClient,'check',return_value='test'), \
                 patch.object(main.LLMClient,'evaluate',side_effect=evaluate), patch.object(main.Worker,'pause'):
                worker.run()
            self.assertEqual(events, ['search','search','evaluate'])


if __name__ == '__main__': unittest.main()
