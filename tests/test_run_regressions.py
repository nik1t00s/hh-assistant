import unittest
from evidence_eval import VALUES, verify_facts, decide
from vacancy_rules import explicit_seniority


def check(source, field=None, value=None, quote=None):
    data = {k: dict(value='unknown', quote='') for k in VALUES}
    if field:
        data[field] = dict(value=value, quote=quote or source)
    return verify_facts(data, source)


class RunRegressions(unittest.TestCase):
    def test_wishes_heading_does_not_cancel_two_year_requirement(self):
        quote = 'Подтверждённый опыт на позиции администратора проектов не менее 2 лет'
        facts, issues = check('Описание: Наши пожелания:\n'+quote, 'experience', 'optional', quote)
        self.assertEqual(facts['experience']['value'], 'required')
        self.assertEqual(decide(facts, issues)[0], 'REJECT')

    def test_explicit_bonus_and_welcomed_experience_remain_optional(self):
        for source in ['Будет плюсом:\nОпыт работы консультантом',
                       'Наши пожелания:\nОпыт работы координатором приветствуется']:
            facts, _ = check('Описание: '+source, 'experience', 'required', source.splitlines()[-1])
            self.assertEqual(facts['experience']['value'], 'optional')

    def test_new_requirements_end_bonus_section(self):
        facts, _ = check('Описание: Будет плюсом:\nОпыт работы координатором\nВам потребуется:\nОпыт работы консультантом')
        self.assertEqual(facts['experience']['value'], 'required')

    def test_consultant_role_experience_not_tool_experience(self):
        for quote in ['Опыт работы консультантом, администратором, специалистом технической поддержки',
                      'Опыт работы специалистом технической поддержки']:
            facts, _ = check('Описание: '+quote)
            self.assertEqual(facts['experience']['value'], 'required')
        facts, _ = check('Описание: Опыт работы с 1С и Windows')
        self.assertEqual(facts['experience']['value'], 'unknown')

    def test_tool_evidence_repairs_false_novice_claim_without_overriding_role_experience(self):
        source = 'Описание: Опыт работы с Windows и Linux для базовых задач\nГотовность постепенно брать более сложные задачи'
        facts, issues = check(source, 'experience', 'no_experience', source.splitlines()[-1])
        self.assertEqual(facts['experience']['value'], 'tools')
        self.assertFalse(issues)
        facts, _ = check(source+'\nОпыт работы системным администратором от года',
                         'experience', 'no_experience', source.splitlines()[-1])
        self.assertEqual(facts['experience']['value'], 'required')

    def test_team_seniority_not_candidate_seniority(self):
        quote = 'Отдел из восьми разработчиков уровня Middle, Senior реализует задачи'
        facts, issues = check(quote, 'level', 'senior')
        self.assertEqual(facts['level']['value'], 'unknown')
        self.assertNotEqual(decide(facts, issues)[0], 'REJECT')
        self.assertIsNone(explicit_seniority('', quote))
        self.assertTrue(explicit_seniority('', 'Ищем администратора уровня Middle в команду'))
        self.assertTrue(explicit_seniority('Senior разработчик', 'Работа в команде'))

    def test_it_evidence_accepts_medtech_and_digital_software(self):
        for quote in ['Развитие в крупной MedTech компании',
                      'Разработка и поддержка digital-решений от веб-сайтов до приложений']:
            facts, issues = check(quote, 'it', 'yes')
            self.assertEqual(facts['it']['value'], 'yes')
            self.assertFalse(issues)
        facts, _ = check('Мы digital-маркетинговое агентство', 'it', 'yes')
        self.assertEqual(facts['it']['value'], 'unknown')

    def test_coordination_is_not_implementation(self):
        quote = 'Помогать синхронизировать статус по кросс-функциональным задачам'
        facts, _ = check(quote, 'role', 'implementation')
        self.assertEqual(facts['role']['value'], 'project')
        facts, _ = check('Внедрение информационных систем', 'role', 'implementation')
        self.assertEqual(facts['role']['value'], 'implementation')

    def test_bpmn_tool_is_not_primary_duty(self):
        for quote in ['Опыт работы с BPMN-движками для автоматизации процессов',
                      'Иногда описывать процессы и готовить схемы в BPMN',
                      'Не основная задача — моделирование в BPMN']:
            facts, issues = check(quote, 'bpmn', 'main')
            self.assertEqual(facts['bpmn']['value'], 'unknown')
            self.assertNotEqual(decide(facts, issues)[0], 'REJECT')
        facts, issues = check('Основная задача — моделирование бизнес-процессов в BPMN', 'bpmn', 'main')
        self.assertEqual(decide(facts, issues)[0], 'REJECT')


if __name__ == '__main__':
    unittest.main()
