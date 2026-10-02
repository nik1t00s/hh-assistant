import json
import unittest
from browser_queue import group_vacancies, variant_details, suitable_urls
from evidence_eval import VALUES, verify_facts, decide

class TravelGroupsTests(unittest.TestCase):
    def test_experience_forms(self):
        for quote in ['Опыт работы супервайзером, координатором от 2х лет',
                      'Работали ассистентом или проектным менеджером от одного года.']:
            data={k:dict(value='unknown',quote='') for k in VALUES}
            facts,issues=verify_facts(data,'Вы нам подойдёте, если\n'+quote)
            self.assertEqual(decide(facts,issues)[0],'REJECT')
        quote='Будет плюсом:\nРаботали ассистентом от одного года'
        data['experience']=dict(value='required',quote=quote.splitlines()[-1])
        facts,issues=verify_facts(data,quote)
        self.assertEqual(facts['experience']['value'],'optional')

    def test_travel_condition_is_found_independently(self):
        data={k:dict(value='unknown',quote='') for k in VALUES}
        for quote, expected in [('Разъездная работа по Москве и области','regular'),
                                ('Разъездной характер работы','regular'),
                                ('Редкие командировки раз в квартал','unknown'),
                                ('Разъездная работа не предусмотрена','unknown'),
                                ('Не требуется разъездная работа','unknown')]:
            facts,_=verify_facts(data,quote)
            self.assertEqual(facts['travel']['value'],expected)

    def test_group_keeps_different_conditions_and_links(self):
        common='Поддержка пользователей и оборудования. '*30
        base=dict(name='Инженер',employer='Example',verdict='WEAK',suitable=True,salary='?',score=50)
        first=dict(base,url='https://hh.ru/vacancy/1',source='Описание: '+common+'\nОбразование: высшее.')
        second=dict(base,url='https://hh.ru/vacancy/2',source='Описание: '+common+'\nОбразование: высшее техническое.')
        groups=group_vacancies([first,second])
        self.assertEqual(len(groups),1)
        self.assertEqual(len(groups[0]['variants']),2)
        self.assertIn('высшее техническое',variant_details(groups[0]))
        self.assertIn(first['url'],variant_details(groups[0]))
        self.assertEqual(suitable_urls(groups),[first['url'],second['url']])
        json.dumps(groups)  # no circular references
        self.assertNotIn('variants',first)
        for changed in [dict(second,employer='Other'),dict(second,verdict='REJECT'),
                        dict(second,source='Иная работа '*30),dict(second,source='')]:
            self.assertEqual(len(group_vacancies([first,changed])),2)

if __name__ == '__main__':unittest.main()
