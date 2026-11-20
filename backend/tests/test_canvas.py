from datetime import datetime,timezone
from pathlib import Path
import tempfile
import unittest
from task_backend.canvas import parse_feed
from task_backend.service import BackendService

NOW=datetime(2026,11,12,12,tzinfo=timezone.utc)

def event(*lines): return '\r\n'.join(['BEGIN:VEVENT',*lines,'END:VEVENT'])
def feed(*events): return '\r\n'.join(['BEGIN:VCALENDAR','VERSION:2.0',*events,'END:VCALENDAR'])


class CanvasTests(unittest.TestCase):
    def test_precision_plain_text_and_stable_identity(self):
        raw=feed(event('UID:a','DTSTART:20261113T143000Z','SUMMARY:Essay','DESCRIPTION:<p>Read &amp; write</p><script>bad()</script>'),event('UID:b','DTSTART;VALUE=DATE:20261114','SUMMARY:All day'))
        result=parse_feed(raw,NOW)
        self.assertEqual(result['issues'],[])
        self.assertEqual(result['items'][0]['due']['value'],dict(kind='minute',at='2026-11-13T14:30:00.000Z',timeZone='UTC'))
        self.assertEqual(result['items'][0]['description'],'Read & write')
        self.assertEqual(result['items'][1]['due']['value'],dict(kind='date',date='2026-11-14'))
        self.assertEqual(result['items'][0]['key'],'["a"]')

    def test_recurring_exclusion_override_and_cancellation(self):
        raw=feed(event('UID:x','DTSTART:20261111T100000Z','RRULE:FREQ=DAILY;COUNT=5','EXDATE:20261112T100000Z','SUMMARY:Daily'),event('UID:x','RECURRENCE-ID:20261113T100000Z','DTSTART:20261113T120000Z','SUMMARY:Moved'),event('UID:x','RECURRENCE-ID:20261114T100000Z','STATUS:CANCELLED'))
        result=parse_feed(raw,NOW)
        self.assertEqual(len(result['items']),3)
        moved=next(v for v in result['items'] if v['title']=='Moved')
        self.assertIn('2026-11-13T10:00:00.000Z',moved['key'])
        self.assertEqual(moved['due']['value']['at'],'2026-11-13T12:00:00.000Z')

    def test_bad_event_isolated_and_dst_gap_rejected(self):
        raw=feed(event('UID:bad','DTSTART;TZID=America/New_York:20260308T023000','SUMMARY:Gap'),event('UID:good','DTSTART;VALUE=DATE:20261113','SUMMARY:Good'))
        result=parse_feed(raw,NOW)
        self.assertEqual(len(result['issues']),1)
        self.assertEqual(result['items'][0]['title'],'Good')
        with self.assertRaises(ValueError): parse_feed('<html>login</html>',NOW)

    def test_sync_is_idempotent_preserves_local_state_and_skips_deleted(self):
        with tempfile.TemporaryDirectory() as folder:
            service=BackendService(Path(folder));service.clock=lambda:NOW
            raw=feed(event('UID:a','DTSTART;VALUE=DATE:20261113','SUMMARY:Course','DESCRIPTION:full description'))
            service.request=lambda *args:raw.encode()
            try:
                service.call('saveCanvasFeed','https://school.example/private.ics')
                self.assertNotIn('private.ics',(Path(folder)/'canvas-feed.json').read_text())
                self.assertEqual(service.call('syncCanvas')['added'],1)
                self.assertEqual(service.call('syncCanvas')['unchanged'],1)
                root=service.call('listTodos')[0]
                service.call('editTodo',root['id'],{'notes':'personal'},True,root['revision'])
                raw=raw.replace('SUMMARY:Course','SUMMARY:Updated')
                self.assertEqual(service.call('syncCanvas')['updated'],1)
                changed=service.call('listTodos')[0]
                self.assertTrue(changed['completed']);self.assertEqual(changed['notes'],'personal')
                service.call('trashTodo',changed['id'],changed['revision'])
                self.assertEqual(service.call('syncCanvas')['skipped'],1)
                self.assertEqual(service.call('listTodos'),[])
            finally: service.close()
