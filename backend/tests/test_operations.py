import time
from pathlib import Path
import tempfile
import unittest
from task_backend.service import BackendService


class OperationTests(unittest.TestCase):
    def test_job_checkpoint_survives_restart_and_requires_explicit_resume(self):
        with tempfile.TemporaryDirectory() as folder:
            service=BackendService(Path(folder),worker=True)
            job=service.call('mail-operations:startImport',dict(bindingIds=['missing'],onlyNew=True))
            self.assertEqual(job['state'],'queued')
            service.call('mail-operations:pauseJob',job['id'])
            self.assertEqual(service.call('mail-operations:getJob',job['id'])['state'],'paused')
            service.close()
            service=BackendService(Path(folder),worker=True)
            try:
                self.assertEqual(service.call('mail-operations:getJob',job['id'])['state'],'paused')
                service.call('mail-operations:cancelJob',job['id'])
                self.assertEqual(service.call('mail-operations:getJob',job['id'])['state'],'canceled')
                service.call('mail-operations:acknowledgeJob',job['id'])
                self.assertTrue(service.call('mail-operations:getJob',job['id'])['notificationAcknowledged'])
            finally: service.close()

    def test_background_import_failure_report_is_persisted(self):
        with tempfile.TemporaryDirectory() as folder:
            service=BackendService(Path(folder))
            try:
                job=service.call('mail-operations:startImport',dict(bindingIds=['missing'],onlyNew=True))
                end=time.monotonic()+15
                while time.monotonic()<end:
                    current=service.call('mail-operations:getJob',job['id'])
                    if current['state'] in ('completed','failed'): break
                    time.sleep(.1)
                self.assertEqual(current['state'],'completed')
                self.assertEqual(current['report']['failed'],1)
                self.assertEqual(current['report']['mailboxErrors'][0]['bindingId'],'missing')
            finally: service.close()

class AnalysisCheckpointTests(unittest.TestCase):
    def test_successful_segments_are_not_requested_again_after_pause_and_restart(self):
        import json
        from task_backend.operations import JobStop
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);service=BackendService(root,worker=True)
            service.call('saveSettings',dict(baseUrl='https://fixture.invalid/v1',model='fixture',apiKey='synthetic'))
            id=service.mail.store.put('binding','identity','user',dict(id='remote',subject='Long',sender='sender',receivedAt='2026-11-12T00:00:00Z',preview='',unread=True,webUrl='',imported=False,body='x'*21000))['localId']
            calls=[]
            answer=json.dumps({'choices':[{'message':{'content':json.dumps({'drafts':[dict(tempId='a',parentTempId=None,title='One task')],'notes':'summary'})}}]}).encode()
            def first(*args):
                calls.append(args)
                if len(calls)==2:raise JobStop('paused')
                return answer
            service.request=first
            job=service.call('mail-operations:startAnalysis',dict(messageIds=[id],instructions='',target=dict(baseUrl='https://fixture.invalid/v1',model='fixture')))
            service.operations.run_next()
            self.assertEqual(service.call('mail-operations:getJob',job['id'])['state'],'paused')
            self.assertEqual(service.call('mail-workspace:getLocal',id)['status'],'unanalyzed')
            service.close();service=BackendService(root,worker=True)
            resumed=[]
            service.request=lambda *args:(resumed.append(args) or answer)
            try:
                service.call('mail-operations:resumeJob',job['id']);service.operations.run_next()
                done=service.call('mail-operations:getJob',job['id'])
                self.assertEqual(done['state'],'completed');self.assertEqual(len(resumed),1)
                analysis=service.call('mail-workspace:getAnalysis',done['analysisIds'][0])
                self.assertEqual(len(analysis['drafts']),1)
                self.assertEqual(service.call('mail-workspace:getLocal',id)['status'],'analyzed')
            finally:service.close()
