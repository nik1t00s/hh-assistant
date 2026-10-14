import unittest
import json
from unittest.mock import patch
from main import LLMClient
from evidence_eval import VALUES, verify_facts, decide, mixed_duty_evidence, description_salary


class MixedDutyTests(unittest.TestCase):
    def test_evaluation_does_not_try_to_repair_policy_issue(self):
        source = 'Обязанности:\nКоординация IT проектов\nМоделирование бизнес-процессов\nСбор бизнес потребностей, декомпозиция'
        raw = {k: dict(value='unknown', line=None) for k in VALUES}
        raw['role'] = dict(value='project', line=2)
        raw['it'] = dict(value='yes', line=2)
        client = LLMClient('http://localhost:1234/v1', 'test', lambda _: None)
        with patch.object(client, '_chat_retrying', return_value=json.dumps(raw)) as chat:
            result = client.evaluate('', source)
        self.assertEqual(result[0], 'REVIEW')
        self.assertEqual(chat.call_count, 1)
        self.assertTrue(any(i.startswith('mixed_role:') for i in client.last_evidence['issues']))

    def test_evaluation_repairs_fact_alongside_policy_issue(self):
        source = 'Обязанности:\nКоординация IT проектов\nМоделирование бизнес-процессов\nСбор бизнес потребностей, декомпозиция'
        raw = {k: dict(value='unknown', line=None) for k in VALUES}
        raw.update(role=dict(value='project', line=2), it=dict(value='yes', line=2), experience=dict(value='required', line=999))
        client = LLMClient('http://localhost:1234/v1', 'test', lambda _: None)
        def answer(*args, **kwargs):
            if answer.first:
                answer.first = False
                return json.dumps(raw)
            self.assertEqual(client.response_schema['required'], ['experience'])
            return json.dumps({'experience': dict(value='unknown', line=None)})
        answer.first = True
        with patch.object(client, '_chat_retrying', side_effect=answer) as chat:
            result = client.evaluate('', source)
        self.assertEqual(chat.call_count, 2)
        self.assertEqual(result[0], 'REVIEW')
        self.assertTrue(any(i.startswith('mixed_role:') for i in client.last_evidence['issues']))

    def test_mixed_duties_require_review_even_with_project_quote(self):
        quote = 'Координация IT проектов'
        for extra in [
            'Моделирование бизнес-процессов\nСбор бизнес потребностей, декомпозиция',
            'Проектировать AI-агентов\nФормулировать требования к IT-системам',
            'Разработка локальной сети с нуля\nВедение педагогической деятельности',
        ]:
            source = 'Описание: Обязанности:\n'+quote+'\n'+extra+'\nУсловия:\nОплата – 90 000 рублей до вычета налогов'
            facts = {k: dict(value='unknown',quote='') for k in VALUES}
            facts['role'] = dict(value='project',quote=quote)
            facts['it'] = dict(value='yes',quote=quote)
            verified, issues = verify_facts(facts, source)
            result = decide(verified, issues)
            self.assertEqual(result[0], 'REVIEW')
            self.assertIn('доля задачи', result[3])
            self.assertIn('90 000', result[3])

    def test_tools_and_learning_are_not_mixed_duties(self):
        for source in [
            'Обязанности:\nКоординация проектов\nРабота с Jira\nТребования:\nЗнание BPMN',
            'Чему мы научим:\nМоделирование бизнес-процессов\nФормулировать требования к IT-системам',
            'Обязанности:\nНе нужно проектировать AI-агентов\nФормулировать требования к IT-системам',
        ]:
            self.assertEqual(mixed_duty_evidence(source, 'project'), [])

    def test_salary_recovery_and_benefit_exclusion(self):
        self.assertEqual(description_salary('Оплата обучения 20 000 рублей\nКомпенсация проезда 3 000 рублей'), [])
        self.assertEqual(description_salary('Оплата — 90 000 рублей до вычета налогов'), ['Оплата — 90 000 рублей до вычета налогов'])
        self.assertEqual(description_salary('Зарплата не указана'), [])
