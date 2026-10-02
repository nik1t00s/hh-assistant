import unittest
from evidence_eval import VALUES, verify_facts

class SkillStatementTests(unittest.TestCase):
    def test_skill_meaning_not_missing_adjective(self):
        for quote, expected in [
            ('Опыт работы с таск-трекерами и базами знаний', 'working'),
            ('Windows и Linux: как работать с ОС и пользователями', 'working'),
            ('Умеет работать с информацией: аккуратно ведёт таблицы', 'working'),
            ('Базовое понимание сетевых технологий и API', 'basic'),
            ('Глубокие знания Linux', 'advanced'),
        ]:
            for claimed in ['working', 'advanced', 'basic']:
                data = {k:dict(value='unknown',quote='') for k in VALUES}
                data['skills']=dict(value=claimed,quote=quote)
                facts, issues=verify_facts(data,quote)
                self.assertEqual(facts['skills']['value'],expected)
                self.assertFalse(issues)

    def test_company_benefit_is_not_a_skill(self):
        quote='Дружный коллектив и корпоративные мероприятия'
        data={k:dict(value='unknown',quote='') for k in VALUES}
        data['skills']=dict(value='working',quote=quote)
        facts,issues=verify_facts(data,quote)
        self.assertEqual(facts['skills']['value'],'unknown')
        self.assertTrue(issues)

    def test_multiline_prior_role_is_not_lost(self):
        source='Для кандидатов с меньшим опытом готовы рассматривать опыт работы:\nаналитиком;\nинженером внедрения;'
        data={k:dict(value='unknown',quote='') for k in VALUES}
        facts,issues=verify_facts(data,source)
        self.assertEqual(facts['experience']['value'],'required')
        self.assertIn('аналитиком',facts['experience']['quote'])

    def test_expert_duties_are_not_hidden_by_basic_skill_quote(self):
        source='Обязанности:\nЭкспертная поддержка пользователей (3-я линия)\nТребования:\nБазовое понимание сетей'
        data={k:dict(value='unknown',quote='') for k in VALUES}
        data['skills']=dict(value='basic',quote='Базовое понимание сетей')
        facts,issues=verify_facts(data,source)
        self.assertEqual(facts['skills']['value'],'advanced')

if __name__ == '__main__': unittest.main()
