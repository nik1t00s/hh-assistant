import unittest
from evidence_eval import VALUES, verify_facts, decide


class LiveRunOctoberTests(unittest.TestCase):
    def verify(self, source, key='experience', value='unknown', quote=''):
        facts = {k: dict(value='unknown', quote='') for k in VALUES}
        facts[key] = dict(value=value, quote=quote)
        return verify_facts(facts, source)

    def test_required_experience_before_optional_sector(self):
        for heading in ['Основные требования', 'Обязательные требования', 'Квалификационные требования']:
            q = 'Опыт управления проектами от 2–3 лет, желательно в питании'
            facts, issues = self.verify('О компании:\nИТ-компания\n'+heading+'\n'+q)
            self.assertEqual(decide(facts, issues)[0], 'REJECT')
        q = 'Опыт работы не менее 1 года с проектами городского развития (преимуществом будет опыт в секторе государственного управления)'
        facts, _ = self.verify('Требования:\n'+q)
        self.assertEqual(facts['experience']['value'], 'required')

    def test_optional_whole_experience_remains_optional(self):
        for q in ['Опыт управления проектами от 3 лет (приветствуется)',
                  'Опыт работы с проектами от 1 года будет преимуществом']:
            facts, _ = self.verify('Требования:\n'+q, 'experience', 'optional', q)
            self.assertEqual(facts['experience']['value'], 'optional')

    def test_general_employment_not_automatic_it_rejection(self):
        q = 'Опыт работы от 2 лет, желательно в медицине'
        facts, issues = self.verify('Требования:\n'+q, 'experience', 'optional', q)
        self.assertNotEqual(facts['experience']['value'], 'required')
        self.assertTrue(any('общий стаж' in i for i in issues))
        self.assertIn('общего стажа', decide(facts, issues)[3])

    def test_professional_crm_service_not_just_tool_knowledge(self):
        for q in ['Опыт работы с Битрикс24 от 1 года: внедрение, настройка, поддержка',
                  'Опыт работы с госконтрактами']:
            facts, _ = self.verify('Требования:\n'+q, 'experience', 'tools', q)
            self.assertEqual(facts['experience']['value'], 'required')
        for q in ['Опыт работы с Excel от 1 года', 'Опыт работы с Битрикс24',
                  'Учебный опыт работы с Битрикс24 от 1 года: настройка',
                  'Опыт работы с госконтрактами приветствуется']:
            facts, _ = self.verify('Требования:\n'+q, 'experience', 'tools', q)
            self.assertNotEqual(facts['experience']['value'], 'required')

    def test_ineligible_novices_not_invitation(self):
        source = ('Требования:\nОпыт управления проектами от 2 лет\n'
                  'Кому вакансия НЕ подойдёт\nКандидату без опыта ведения проектов\n'
                  'Мы предлагаем\nОбучение')
        facts, _ = self.verify(source)
        self.assertEqual(facts['experience']['value'], 'required')
        source = 'Требования:\nОпыт управления проектами от 2 лет\nРассмотрим кандидатов без опыта'
        facts, issues = self.verify(source)
        self.assertEqual(facts['experience']['value'], 'unknown')
        self.assertTrue(any('противоречие' in i for i in issues))

    def test_department_head_not_assistant_or_project_manager(self):
        for title in ['Руководитель центра управления проектами', 'Начальник отдела ИТ']:
            facts, _ = self.verify('Должность: '+title)
            self.assertEqual(facts['level']['value'], 'senior')
        for title in ['Помощник руководителя центра', 'Руководитель проектов', 'Администратор проектов']:
            facts, _ = self.verify('Должность: '+title)
            self.assertNotEqual(facts['level']['value'], 'senior')

    def test_school_support_not_technical_support(self):
        q = 'Помогать тьютору поддерживать темп работы и дисциплину в группе'
        facts, _ = self.verify(q, 'role', 'support', q)
        self.assertEqual(facts['role']['value'], 'unknown')
        q = 'Техническая поддержка пользователей школьной информационной системы'
        facts, _ = self.verify(q, 'role', 'support', q)
        self.assertEqual(facts['role']['value'], 'support')

    def test_law_education_and_data_entry_not_it_function(self):
        for q in ['Знание ФЗ № 149-ФЗ об информационных технологиях',
                  'Высшее образование (ИТ, телекоммуникации)',
                  'Обучаем программированию новое IT-поколение',
                  'Мониторинг проектов с использованием внутренней ИТ-платформы',
                  'Внесение и отражение данных в информационных системах']:
            facts, _ = self.verify(q, 'it', 'yes', q)
            self.assertEqual(facts['it']['value'], 'unknown', q)
        q = 'Разработка информационных систем'
        facts, _ = self.verify(q, 'it', 'yes', q)
        self.assertEqual(facts['it']['value'], 'yes')

    def test_expert_duties_require_review_not_optional_experience_reject(self):
        for q in ['Построение архитектуры систем защиты информации',
                  'Умение готовить экспертные заключения']:
            facts, _ = self.verify('Обязанности:\n'+q)
            self.assertEqual(facts['skills']['value'], 'advanced')
        facts, _ = self.verify('Обязанности:\nПод руководством наставника готовить экспертные заключения')
        self.assertNotEqual(facts['skills']['value'], 'advanced')
        facts, _ = self.verify('Мы ищем специалиста с предметной экспертизой в бухгалтерском учете')
        self.assertEqual(facts['skills']['value'], 'advanced')
        for q in ['Нам не нужен специалист с предметной экспертизой',
                  'Со временем вы станете специалистом с предметной экспертизой']:
            facts, _ = self.verify(q)
            self.assertNotEqual(facts['skills']['value'], 'advanced')

    def test_infrastructure_intern_is_reserve_direction(self):
        q = 'Участвовать во внедрении инфраструктурных сервисов'
        facts, _ = self.verify('Должность: Стажер-инженер по программной инфраструктуре\n'+q, 'role', 'implementation', q)
        self.assertEqual(facts['role']['value'], 'admin')
