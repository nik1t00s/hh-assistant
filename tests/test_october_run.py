import unittest
from evidence_eval import VALUES, verify_facts, decide

class OctoberRunTests(unittest.TestCase):
    def facts(self, source, field, value, quote):
        facts={k:dict(value='unknown',quote='') for k in VALUES}
        facts[field]=dict(value=value,quote=quote)
        return verify_facts(facts,source)

    def test_future_experience_is_not_required_experience(self):
        quote='Мечтаешь получить опыт в коммерческом отделе, готов обучаться новому.'
        facts,issues=self.facts('Требования:\n'+quote,'experience','required',quote)
        self.assertNotEqual(facts['experience']['value'],'required')
        facts,issues=self.facts('Требования:\n'+quote+'\nОпыт работы координатором от года','experience','required',quote)
        self.assertEqual(decide(facts,issues)[0],'REJECT')

    def test_relocation_alternative_for_local_resident(self):
        quote='Ты готов к переезду в Москву (или уже находишься в Москве)'
        facts,_=self.facts(quote,'relocation','required',quote)
        self.assertEqual(facts['relocation']['value'],'unknown')
        quote='Обязательный переезд в другой город'
        facts,_=self.facts(quote,'relocation','required',quote)
        self.assertEqual(facts['relocation']['value'],'required')

    def test_nontechnical_support_is_not_technical_role(self):
        for quote in ['поддержка HR процессов: адаптация и увольнения','поддержка продаж, без поиска клиентов']:
            facts,issues=self.facts('Описание: '+quote,'role','support',quote)
            self.assertEqual(facts['role']['value'],'unknown')
            self.assertTrue(any(i.startswith('role:') for i in issues))
        quote='Поддержка пользователей информационной системы'
        facts,_=self.facts('Описание: '+quote,'role','support',quote)
        self.assertEqual(facts['role']['value'],'support')

    def test_technical_project_is_not_coordination(self):
        quote='Участвовать в проектах запуска новых клиентов и разработке интеграций'
        facts,_=self.facts('Должность: Системный аналитик\nОписание: '+quote,'role','project',quote)
        self.assertEqual(facts['role']['value'],'unknown')

    def test_data_engineering_requires_clarification(self):
        quote='Должность: Стажер Инженер по данным (Data Engineer)'
        facts,_=self.facts(quote+'\nОписание: Разработка ETL','role','data',quote)
        self.assertEqual(facts['role']['value'],'unknown')

    def test_intern_and_practice_center_not_work_experience(self):
        quote='Мы в поисках стажера в роли Support Engineer в наш Центр практик.'
        facts,issues=self.facts('Описание: '+quote,'experience','required',quote)
        self.assertNotEqual(decide(facts,issues)[0],'REJECT')

    def test_ambiguous_fixed_term_contract_is_not_no_tk(self):
        quote='Оформление по срочному договору или ГПХ, с ИП или самозанятым'
        facts,_=self.facts(quote,'contract','no_tk',quote)
        self.assertEqual(facts['contract']['value'],'unknown')

    def test_retail_employer_does_not_disqualify_it_department(self):
        quote='Компания: Красное & Белое, розничная сеть'
        facts,_=self.facts('Должность: Младший системный аналитик департамента ИТ\n'+quote+'\nОписание: задачи','it','no',quote)
        self.assertEqual(facts['it']['value'],'unknown')
