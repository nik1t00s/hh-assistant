import unittest
from evidence_eval import VALUES, verify_facts, decide, experience_evidence


def check(source, **fields):
    data = {k: dict(value='unknown', quote='') for k in VALUES}
    for k, (v, q) in fields.items():data[k] = dict(value=v, quote=q)
    return verify_facts(data, source)


class ContextEvidenceTests(unittest.TestCase):
    def test_professional_activity_with_duration(self):
        for quote in ['Опыт администрирования прикладного ПО от 2 лет',
                      'Опыт работы в сфере продаж цифровой рекламы от 2-х лет',
                      'Опыт работы от 1 года координатором проектов']:
            facts, issues = check('Описание: Требования:\n'+quote)
            self.assertEqual(decide(facts, issues)[0], 'REJECT')

    def test_same_activity_is_optional_only_in_bonus_section(self):
        quote = 'Опыт администрирования прикладного ПО от 2 лет'
        self.assertEqual(experience_evidence('Описание: Будет плюсом:\n'+quote)[0][0], 'optional')
        self.assertEqual(experience_evidence('Описание: Наши ожидания:\n'+quote)[0][0], 'required')

    def test_benefits_and_team_experience_are_not_requirements(self):
        for text in ['О компании:\nОпыт работы в IT от 10 лет',
                     'Условия:\nОбмен опытом работы в IT от 5 лет',
                     'У нас сотрудники с опытом работы в IT от 5 лет']:
            self.assertFalse(experience_evidence('Описание: '+text))

    def test_bonus_does_not_leak_into_next_section(self):
        source = 'Будет плюсом:\nОпыт работы координатором\nНаши ожидания:\nОпыт работы консультантом'
        self.assertEqual([v for v,q in experience_evidence(source)], ['optional','required'])
        source = 'Будет плюсом:\nОпыт работы координатором\nДругой раздел:\nОпыт работы консультантом'
        self.assertEqual([v for v,q in experience_evidence(source)], ['optional','required'])

    def test_semicolon_separates_optional_and_required_items(self):
        source = 'Требования:\nОпыт работы координатором от года; опыт работы с Excel будет плюсом'
        facts, issues = check(source)
        self.assertEqual(decide(facts, issues)[0], 'REJECT')

    def test_tool_evidence_does_not_override_unrecognized_experience(self):
        quote = 'Опыт редкой профессиональной деятельности от двух лет'
        facts, issues = check('Требования:\n'+quote+'\nОпыт работы с Excel', experience=('required',quote))
        self.assertEqual(facts['experience']['value'], 'unknown')
        self.assertTrue(any(i.startswith('experience:') for i in issues))

    def test_working_skill_is_neither_basic_nor_expert(self):
        quote = 'Свободное владение офисными программами'
        facts, issues = check(quote, skills=('advanced',quote))
        self.assertEqual(facts['skills']['value'], 'working')
        self.assertFalse(issues)
        facts['it'] = dict(value='yes',quote='IT-компания')
        facts['role'] = dict(value='support',quote='Поддержка пользователей')
        verdict = decide(facts,issues)
        self.assertEqual(verdict[0], 'WEAK')
        self.assertIn('соответствие практических навыков', verdict[3])

    def test_true_expertise_still_requires_review(self):
        quote = 'Глубокие знания серверной инфраструктуры'
        facts, issues = check(quote, skills=('advanced',quote))
        self.assertEqual(facts['skills']['value'], 'advanced')
        self.assertEqual(decide(facts,issues)[0], 'REVIEW')

    def test_false_expertise_quote_is_not_silently_accepted(self):
        facts, issues = check('Обучение на старте', skills=('advanced','Уверенные знания Linux'))
        self.assertTrue(issues)
        self.assertEqual(facts['skills']['value'], 'unknown')

    def test_it_function_does_not_depend_on_employer_industry(self):
        quote = 'Поддерживать Windows и Linux, серверы и сетевые сервисы'
        facts, issues = check(quote, it=('yes',quote))
        self.assertEqual(facts['it']['value'], 'yes')
        self.assertFalse(issues)

    def test_own_software_and_cashier_are_not_it_support(self):
        text = 'Своя IT-система. Автоматизируем работу.\nРаботать с кассой'
        facts, issues = check(text, it=('yes',text.splitlines()[0]),role=('support',text.splitlines()[1]))
        self.assertEqual(facts['it']['value'], 'unknown')
        self.assertEqual(facts['role']['value'], 'unknown')
        self.assertEqual(decide(facts,issues)[0], 'REVIEW')

    def test_it_recovery_requires_an_actual_technical_duty(self):
        bad = 'Мы продаём одежду на маркетплейсах'
        duty = 'Поддерживать Windows и Linux, серверы и сетевые сервисы'
        for section, expected in [('Чем предстоит заниматься:', 'yes'), ('Требования:', 'unknown')]:
            facts, _ = check(bad+'\n'+section+'\n'+duty, it=('yes',bad))
            self.assertEqual(facts['it']['value'], expected)

    def test_working_skill_still_requires_evidence(self):
        facts, issues = check('Дружный коллектив и корпоративы', skills=('working','Дружный коллектив и корпоративы'))
        self.assertEqual(facts['skills']['value'], 'unknown')
        self.assertTrue(issues)

    def test_account_provisioning_is_support_but_cashier_is_not(self):
        quote = 'Создавать и настраивать рабочие учётные записи и доступы'
        facts, issues = check(quote, role=('support',quote))
        self.assertEqual(facts['role']['value'], 'support')
        self.assertFalse(issues)

    def test_optional_training_is_not_zero_experience_claim(self):
        quote = 'Учебная или рабочая практика с серверами'
        source = 'Преимуществом будет:\n'+quote
        facts, issues = check(source,experience=('no_experience',quote))
        self.assertEqual(facts['experience']['value'], 'optional')
        self.assertFalse(issues)

if __name__ == '__main__':unittest.main()
