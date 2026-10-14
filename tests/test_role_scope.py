import unittest
from evidence_eval import VALUES, verify_facts, decide, scope_review_evidence

class RoleScopeTests(unittest.TestCase):
    def test_title_cannot_hide_full_product_ownership(self):
        source = ('Должность: Project Manager\nОписание: IT продукты\nНам важно:\n'
                  'Английский язык на уровне B2 или выше\nЧем предстоит заниматься:\n'
                  'Полностью вести жизненный цикл продукта от идеи до масштабирования\n'
                  'Нанимать и руководить кросс-функциональной командой\nУправлять бюджетом продукта')
        facts = {k: dict(value='unknown', quote='') for k in VALUES}
        facts.update(role=dict(value='project', quote='Должность: Project Manager'),
                     it=dict(value='yes', quote='IT продукты'))
        checked, issues = verify_facts(facts, source)
        result = decide(checked, issues)
        self.assertEqual(result[0], 'REVIEW')
        self.assertIn('английского', result[3])
        self.assertIn('найм', result[3])

    def test_optional_language_and_assistance_do_not_block(self):
        for language in ['Будет плюсом:\nАнглийский B2', 'Нам важно:\nАнглийский B2 желателен',
                         'Нам важно:\nАнглийский B1', 'Мы предлагаем:\nОбучение английскому до B2']:
            source = ('Описание: '+language+'\nОбязанности:\nПомогать нанимать команду\n'
                      'Под руководством наставника управлять бюджетом продукта\nКоординировать встречи команды')
            self.assertEqual(scope_review_evidence(source), [])

    def test_individual_coordination_tasks_are_not_product_ownership(self):
        self.assertEqual(scope_review_evidence('Описание: Обязанности:\nУправлять бюджетом продукта\nКоординировать команду'), [])

    def test_required_language_after_duties_is_not_a_duty(self):
        result = scope_review_evidence('Описание: Обязанности:\nКоординировать проекты\nНам важно:\nEnglish C1')
        self.assertEqual(len(result), 1)

    def test_learning_outcomes_are_not_ownership(self):
        self.assertEqual(scope_review_evidence('Описание: Чему мы научим:\nНанимать и руководить командой\nУправлять бюджетом продукта'), [])
