import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import main
from vacancy_rules import saved_hh_description


class BrowserImportTests(unittest.TestCase):
    def page(self, url='https://hh.ru/vacancy/123'):
        return '<link rel="canonical" href="'+url+'"><script type="application/ld+json">'+json.dumps({'@type':'JobPosting','description':'<p>Tasks</p><p>Requirements</p>'})+'</script>'

    def test_saved_page_parsed_without_scripts_or_related_vacancy(self):
        vid, text = saved_hh_description(self.page()+'<a href="https://hh.ru/vacancy/456">Related</a><script>secret()</script>')
        self.assertEqual((vid, text), ('123', 'Tasks\nRequirements'))
        self.assertNotIn('secret', text)

    def test_wrong_host_conflicting_ids_and_missing_description_rejected(self):
        for page in [self.page('https://hh.ru.evil.test/vacancy/123'),
                     self.page()+'<meta property="og:url" content="https://hh.ru/vacancy/456">',
                     '<link rel="canonical" href="https://hh.ru/vacancy/123">Login',
                     '<a href="https://hh.ru/vacancy/123">Related</a>']:
            with self.assertRaises(ValueError): saved_hh_description(page)

    def test_imported_description_skips_network_for_matching_id_only(self):
        with tempfile.TemporaryDirectory() as folder:
            directory = Path(folder)/'browser_descriptions'
            directory.mkdir()
            (directory/'123.json').write_text(json.dumps(dict(id='123',description='Saved description')),encoding='utf-8')
            client = main.HHClient(lambda _: None)
            with patch.object(main,'CACHE_DIR',folder), patch.object(client,'_get') as get:
                self.assertEqual(client.description('https://hh.ru/vacancy/123?from=search'),'Saved description')
                get.assert_not_called()
                get.return_value.text = self.page('https://hh.ru/vacancy/456')
                self.assertEqual(client.description('https://hh.ru/vacancy/456'),'Tasks\nRequirements')
                get.assert_called_once()
