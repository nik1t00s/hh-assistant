import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import main
from evidence_eval import VALUES, verify_facts, decide, valid_facts, salary_state, audit_path, save_audit, materialize, numbered_source


def blank():
    return {key: dict(value='unknown', quote='') for key in VALUES}


class EvidenceTests(unittest.TestCase):
    def test_fabricated_quote_cannot_reject_or_accept(self):
        for field, value in [('experience', 'required'), ('experience', 'no_experience')]:
            data = blank();data[field] = dict(value=value, quote='Обязателен коммерческий опыт от года')
            facts, issues = verify_facts(data, 'Описание: Предоставляем наставника.')
            self.assertTrue(issues)
            self.assertEqual(decide(facts, issues)[0], 'REVIEW')

    def test_tracker_experience_and_hh_tag_are_not_commercial_experience(self):
        data = blank();data['experience'] = dict(value='required', quote='Опыт работы с Jira и Confluence')
        facts, issues = verify_facts(data, 'Описание: Опыт работы с Jira и Confluence')
        self.assertEqual(facts['experience']['value'], 'unknown')
        self.assertEqual(decide(facts, issues)[0], 'REVIEW')
        data['experience']['quote'] = 'Тег HH: опыт работы в аналогичной должности от года'
        facts, issues = verify_facts(data, data['experience']['quote']+'\nОписание: Обучение с нуля')
        self.assertTrue(issues)

    def test_mentoring_does_not_mean_no_experience(self):
        data = blank();data['experience'] = dict(value='no_experience', quote='Система наставничества и адаптация')
        facts, issues = verify_facts(data, data['experience']['quote'])
        self.assertTrue(issues)
        self.assertEqual(facts['experience']['value'], 'unknown')

    def test_supported_requirement_is_rejected_with_quote(self):
        data = blank();quote='Обязателен коммерческий опыт от одного года'
        data['experience'] = dict(value='required', quote=quote)
        facts, issues = verify_facts(data, 'Описание: '+quote)
        result = decide(facts, issues)
        self.assertEqual(result[0], 'REJECT');self.assertIn(quote, result[3])

    def test_ranges_gross_unknown_and_below_threshold(self):
        self.assertEqual(salary_state('25 000–45 000 ₽ на руки в месяц'), 'unknown')
        self.assertEqual(salary_state('до 35 000 ₽ на руки в месяц'), 'below')
        self.assertEqual(salary_state('от 35 000 ₽ на руки в месяц'), 'unknown')
        self.assertEqual(salary_state('50 000 ₽ до вычета налогов в месяц'), 'unknown')
        self.assertEqual(salary_state('40 000 ₽ на руки в месяц'), 'ok')

    def test_unknown_contract_and_advanced_skills_need_review(self):
        data = blank()
        for field,value,quote in [('it','yes','Работа в IT-компании'),('role','project','Координация IT-проектов'),
                                  ('salary','stated','60 000 ₽ на руки в месяц')]:
            data[field] = dict(value=value,quote=quote)
        source='\n'.join(f['quote'] for f in data.values())
        facts,issues=verify_facts(data,source)
        self.assertEqual(decide(facts,issues)[0],'MATCH')
        self.assertIn('Уточнить у работодателя',decide(facts,issues)[3])
        data['contract']=dict(value='tk',quote='Оформление по ТК РФ')
        source+='\nОформление по ТК РФ'
        facts,issues=verify_facts(data,source)
        self.assertEqual(decide(facts,issues)[0],'MATCH')
        data['skills']=dict(value='advanced',quote='Глубокое знание Битрикс24')
        facts,issues=verify_facts(data,source+'\nГлубокое знание Битрикс24')
        self.assertEqual(decide(facts,issues)[0],'REVIEW')

    def test_extraction_integration_and_snapshot(self):
        data=blank();data['experience']=dict(value='required',quote='Обязателен коммерческий опыт от года')
        extracted={key: dict(value=value['value'], line=1 if key=='experience' else None) for key,value in data.items()}
        self.assertTrue(valid_facts(json.dumps(extracted)))
        client=main.LLMClient('http://example.invalid','test',lambda _:None)
        with patch.object(client,'_chat',return_value=json.dumps(extracted)):
            result=client.evaluate('profile','Описание: Обязателен коммерческий опыт от года')
        self.assertEqual(result[0],'REJECT')
        self.assertIn('verified',client.last_evidence)
        with tempfile.TemporaryDirectory() as folder:
            path=audit_path(folder,'v1',{'id':'../../unsafe'},'text')
            self.assertEqual(path.parent,Path(folder)/'descriptions')
            save_audit(path,{'id':'test'},'full description','v1','model','private profile',evidence=client.last_evidence)
            stored=json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(stored['source'],'full description')
            self.assertNotIn('private profile',path.read_text(encoding='utf-8'))

    def test_review_is_separate_in_ui_and_bulk_open(self):
        from browser_queue import suitable_urls
        self.assertEqual(suitable_urls([dict(url='https://hh.ru/vacancy/1',verdict='REVIEW',suitable=True)]),[])

    def test_line_references_cannot_invent_quotes(self):
        lines,_=numbered_source('Описание: Первая строка\nВторая строка')
        data={key:dict(value='unknown',line=None) for key in VALUES}
        data['experience']=dict(value='required',line=999)
        facts,issues=verify_facts(materialize(data,lines),'Первая строка\nВторая строка')
        self.assertTrue(issues)
        self.assertEqual(decide(facts,issues)[0],'REVIEW')

    def test_business_processes_are_not_automatically_bpmn(self):
        data=blank();data['bpmn']=dict(value='main',quote='Внедрением бизнес-процессов;')
        facts,issues=verify_facts(data,'Внедрением бизнес-процессов;')
        self.assertEqual(facts['bpmn']['value'],'unknown')
        self.assertEqual(decide(facts,issues)[0],'REVIEW')

    def test_schema_is_removed_after_failed_extraction(self):
        client=main.LLMClient('http://example.invalid','test',lambda _:None)
        with patch.object(client,'_chat',return_value='bad'):
            with self.assertRaises(main.EvaluationExhausted):client.evaluate('profile','vacancy')
        self.assertIsNone(client.response_schema)

    def test_sales_department_and_remote_work_do_not_prove_hard_stops(self):
        for key,value,quote in [('sales','main','Координатор отдела IT продаж'),
                                ('it','no','Удалённая работа, полная занятость'),
                                ('sales','main','Без холодных звонков и продаж'),
                                ('level','senior','Ваш наставник — Senior Project Manager'),
                                ('development','main','Координация разработки программного обеспечения')]:
            data=blank();data[key]=dict(value=value,quote=quote)
            facts,issues=verify_facts(data,quote)
            self.assertEqual(facts[key]['value'],'unknown')
            self.assertEqual(decide(facts,issues)[0],'REVIEW')

    def test_review_is_saved_separately_and_not_in_top(self):
        import queue, threading
        with tempfile.TemporaryDirectory() as folder, patch.object(main,'RESULTS_DIR',None):
            main.RESULTS_DIR=folder
            writer=main.ResultWriter('version')
            item=dict(id='test',name='Needs clarification',employer='Example',salary='?',url='https://example.com')
            writer.write(item,0,'REVIEW',None,'общее','Нужно уточнить зарплату',None)
            worker=main.Worker(main.DEFAULT_CONFIG,'profile',queue.Queue(),threading.Event())
            worker._write_top(writer,main.DEFAULT_CONFIG)
            self.assertIn('Needs clarification',Path(folder,'review.md').read_text(encoding='utf-8'))
            self.assertNotIn('Needs clarification',Path(folder,'top.md').read_text(encoding='utf-8'))


if __name__ == '__main__':unittest.main()
