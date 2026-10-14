import unittest
from evidence_eval import VALUES, verify_facts, decide, learning_only_quote


class LearningSalaryTests(unittest.TestCase):
    def facts(self):
        facts = {k: dict(value='unknown', quote='') for k in VALUES}
        facts['role'] = dict(value='project', quote='Координация IT-проектов')
        facts['it'] = dict(value='yes', quote='Координация IT-проектов')
        facts['contract'] = dict(value='tk', quote='Трудовой договор')
        return facts

    def test_unknown_salary_is_match_with_clarification_not_rejection(self):
        facts = self.facts()
        result = decide(facts, [])
        self.assertEqual(result[0], 'MATCH')
        self.assertEqual(result[1], 65)
        self.assertIn('зарплата', result[3])
        facts['role'] = dict(value='support', quote='Техническая поддержка пользователей')
        self.assertEqual(decide(facts, [])[0], 'WEAK')

    def test_known_low_net_and_unknown_gross_are_distinct(self):
        facts = self.facts()
        facts['salary'] = dict(value='stated', quote='30 000 рублей на руки в месяц')
        self.assertEqual(decide(facts, [])[0], 'REJECT')
        facts['salary']['quote'] = 'от 40 000 рублей до вычета налогов'
        self.assertEqual(decide(facts, [])[0], 'MATCH')

    def test_learning_outcome_cannot_prove_project_role(self):
        quote = 'Проектные технологии внедрения и сопровождения систем.'
        source = 'Должность: Стажёр аналитик\nОписание: Что ты будешь делать:\nОписывать требования разработчикам.\nЧто ты узнаешь за 3-12 месяцев:\n'+quote+'\nЧто мы предлагаем:\nОбучение.'
        facts = self.facts()
        facts['role'] = dict(value='project',quote=quote)
        checked, issues = verify_facts(facts, source)
        self.assertEqual(checked['role']['value'], 'unknown')
        self.assertEqual(decide(checked, issues)[0], 'REVIEW')

    def test_real_duties_after_learning_section_are_allowed(self):
        quote = 'Координация IT-проектов'
        source = 'Чему мы научим:\n'+quote+'\nОбязанности:\n'+quote
        self.assertFalse(learning_only_quote(quote, source))
        self.assertFalse(learning_only_quote(quote, 'Обязанности:\n'+quote))
