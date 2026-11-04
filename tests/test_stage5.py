"""API task safety tests; never call Gmail/OpenAI/real user scripts."""
from __future__ import annotations
import importlib.util
import json
import tempfile
import threading
import time
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

spec = importlib.util.spec_from_file_location("stage5_api", Path(__file__).resolve().parents[1] / "api_local.py")
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)

class TaskTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        api.ROOT = Path(cls.temp.name)
        api.JOBS = api.ROOT / 'jobs'
        api.JOBS.mkdir()
        api.RESUMES = api.ROOT / 'resumes'
        api.RESUMES.mkdir()
        api.SOURCES = [api.JOBS / 'handshake_email_jobs.json', api.JOBS / 'job_screen_results.json']
        api.RESUME_STATE = api.JOBS / 'resume_draft_state.json'
        api.HISTORY_FILE = api.ROOT / 'task_history.json'
        api.TRACKER_FILE = api.ROOT / 'application_tracker.json'
        api.SCHEDULE_FILE = api.ROOT / 'discovery_schedule.json'
        (api.ROOT / 'run_email_jobs.py').write_text('print("mock screen done")\n',encoding='utf-8')
        (api.ROOT / 'run_full_agent.py').write_text('print("fake importer")\n',encoding='utf-8')
        (api.ROOT / 'run_screened_resumes.py').write_text('print("fake resume")\n',encoding='utf-8')
        (api.JOBS / 'job_screen_results.json').write_text(json.dumps([{'job_id':'12345','priority':'高匹配·优先核实'}]),encoding='utf-8')
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), api.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.temp.cleanup()

    def req(self, data, origin='http://localhost:3000', header=True):
        headers={'Origin':origin, 'Content-Type':'application/json'}
        if header: headers['X-Job-Agent-Action']='local-user-approved'
        return Request(f'http://127.0.0.1:{self.port}/api/tasks',
                       data=json.dumps(data).encode('utf-8'),headers=headers,method='POST')

    def error(self, data, status, **kw):
        with self.assertRaises(HTTPError) as raised:
            urlopen(self.req(data,**kw),timeout=4)
        self.assertEqual(raised.exception.code,status)

    def test_requires_local_origin_and_action_header(self):
        self.error({'action':'screen'},403,origin='https://bad.example')
        self.error({'action':'screen'},403,header=False)

    def test_no_paid_work_without_explicit_confirmation(self):
        self.error({'action':'resume','jobId':'12345'},400)
        self.error({'action':'resume','jobId':'99999','confirmPaid':True},404)
        self.error({'action':'import','maxEmails':20},400)
        self.error({'action':'import','maxEmails':100,'confirmRead':True},400)
        self.error({'action':'arbitrary_shell_command'},400)

    def test_only_allowlisted_python_script(self):
        with urlopen(self.req({'action':'screen'}),timeout=4) as response:
            self.assertEqual(response.status,202)
        for _ in range(180):
            t=api.public_task()
            if t and t['status'] in ('succeeded','failed'):break
            time.sleep(.025)
        self.assertEqual(t['status'],'succeeded')
        self.assertEqual(t['returnCode'],0)
        self.assertTrue(any('mock screen done' in ln for ln in t['logs']))

if __name__=='__main__':unittest.main()
