import json
from pathlib import Path
import tempfile
import unittest
from task_backend.service import BackendService


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.service=BackendService(self.root)

    def tearDown(self):
        self.service.close();self.temp.cleanup()

    def settings(self,**extra):
        return dict(baseUrl='https://example.com/v1',model='fixture',apiKey='test-private-marker',**extra)

    def test_settings_encrypts_key_and_clearing_preserves_endpoint(self):
        saved=self.service.call('saveSettings',self.settings())
        self.assertTrue(saved['hasApiKey'])
        self.assertNotIn('test-private-marker',(self.root/'settings.json').read_text())
        self.assertEqual(self.service.settings.for_request()['apiKey'],'test-private-marker')
        self.service.call('clearKey')
        self.assertFalse(self.service.call('getSettings')['hasApiKey'])
        self.assertEqual(self.service.call('getSettings')['model'],'fixture')

    def test_endpoint_change_requires_new_key_and_http_rejected(self):
        self.service.call('saveSettings',self.settings())
        for value in (dict(baseUrl='https://other.example/v1',model='fixture',apiKey=''),dict(baseUrl='http://example.com',model='fixture',apiKey='key')):
            with self.assertRaises(ValueError): self.service.call('saveSettings',value)
        self.assertEqual(self.service.call('getSettings')['baseUrl'],'https://example.com/v1')

    def test_ai_extract_validates_output_without_saving_and_confirmation_writes(self):
        requests=[]
        def request(url,body,headers,limit,timeout):
            requests.append((url,json.loads(body),headers))
            return json.dumps({'choices':[{'message':{'content':json.dumps({'drafts':[{'tempId':'a','parentTempId':None,'title':'行动'}],'notes':'summary'})}}]}).encode()
        self.service.request=request
        self.service.call('saveSettings',self.settings())
        result=self.service.call('extract','untrusted original')
        self.assertEqual(self.service.call('listTodos'),[])
        self.assertEqual(result['drafts'][0]['title'],'行动')
        self.assertEqual(requests[0][0],'https://example.com/v1/chat/completions')
        self.assertEqual(requests[0][1]['messages'][1]['content'],'untrusted original')
        self.assertEqual(self.service.call('saveDrafts',result['drafts'],result['confirmationToken'])['value'],1)

    def test_malformed_ai_output_never_saves(self):
        self.service.request=lambda *args: b'{"choices":[{"message":{"content":"not JSON"}}]}'
        self.service.call('saveSettings',self.settings())
        with self.assertRaises(ValueError): self.service.call('extract','text')
        self.assertEqual(self.service.call('listTodos'),[])

    def test_text_and_html_mail_import_are_plain_text(self):
        file=self.root/'input.txt';file.write_text('\ufeff中文',encoding='utf-8')
        self.assertEqual(self.service.call('importTextFile',str(file))['text'],'中文')
        file=self.root/'input.eml';file.write_bytes(b'Subject: fixture\r\nContent-Type: text/html; charset=utf-8\r\n\r\n<p>hello</p><script>bad()</script>')
        parsed=self.service.call('importTextFile',str(file))
        self.assertIn('hello',parsed['text']);self.assertNotIn('bad()',parsed['text'])

    def test_backup_file_roundtrip_and_malformed_file_does_not_save(self):
        file=self.root/'backup.json'
        self.assertTrue(self.service.call('exportBackupFile',str(file)))
        self.assertTrue(self.service.call('importBackupFile',str(file)))
        file.write_text('bad')
        with self.assertRaises(ValueError): self.service.call('importBackupFile',str(file))
