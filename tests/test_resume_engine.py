"""Frontend 'Generate review draft' -> chunk editor wiring; never calls OpenAI."""
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

spec = importlib.util.spec_from_file_location("engine_api", Path(__file__).resolve().parents[1] / "api_local.py")
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


class ResumeEngineTests(unittest.TestCase):
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
        (api.ROOT / 'run_screened_resumes.py').write_text('import sys\nprint("ARGS", sys.argv[1:])\n', encoding='utf-8')
        (api.JOBS / 'job_screen_results.json').write_text(
            json.dumps([{'job_id': '12345', 'priority': '高匹配·优先核实', 'company': 'Acme', 'title': 'SWE Intern'}]),
            encoding='utf-8')
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), api.Handler)
        cls.port = cls.server.server_address[1]
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    def post(self, data):
        req = Request(f'http://127.0.0.1:{self.port}/api/tasks', data=json.dumps(data).encode('utf-8'),
                      headers={'Origin': 'http://localhost:3000', 'Content-Type': 'application/json',
                               'X-Job-Agent-Action': 'local-user-approved'}, method='POST')
        return urlopen(req, timeout=4)

    def status_of(self, data):
        try:
            with self.post(data) as response:
                return response.status
        except HTTPError as exc:
            exc.close()
            return exc.code

    def wait(self):
        for _ in range(200):
            t = api.public_task()
            if t and t['status'] in ('succeeded', 'failed'):
                return t
            time.sleep(.025)
        self.fail('task did not finish')

    def test_engine_validation_and_master_required(self):
        base = {'action': 'resume', 'jobId': '12345', 'confirmPaid': True}
        self.assertEqual(self.status_of(dict(base, engine='bogus')), 400)
        master = api.ROOT / 'Resume_Test User.docx'
        master.unlink(missing_ok=True)
        self.assertEqual(self.status_of(base), 409)  # default engine needs the master resume

    def test_default_engine_runs_chunk_editor_with_master(self):
        (api.ROOT / 'Resume_Test User.docx').write_bytes(b'PK\x03\x04FAKE')
        try:
            self.assertEqual(self.status_of({'action': 'resume', 'jobId': '12345', 'confirmPaid': True}), 202)
            task = self.wait()
            args = next(ln for ln in task['logs'] if 'ARGS' in ln)
            self.assertIn('--chunk-tailored', args)
            self.assertIn("'--master-resume', 'Resume_Test User.docx'", args)
            self.assertNotIn('--profile-source', args)
            # The older profile writer stays available explicitly.
            self.assertEqual(self.status_of({'action': 'resume', 'jobId': '12345', 'confirmPaid': True,
                                             'engine': 'profile', 'profileSource': 'legacy'}), 202)
            args = next(ln for ln in self.wait()['logs'] if 'ARGS' in ln)
            self.assertNotIn('--chunk-tailored', args)
        finally:
            (api.ROOT / 'Resume_Test User.docx').unlink(missing_ok=True)

    def test_chunk_drafts_are_listed_and_previewed(self):
        (api.RESUMES / '12345_20261104_101010_000001_chunk_tailored.docx').write_bytes(b'PK\x03\x04FAKE')
        (api.RESUMES / '12345_20261104_101010_000001_chunk_tailored.md').write_text(
            '## What this role values\n- data analysis', encoding='utf-8')
        (api.RESUMES / '12345_20261104_101010_000001_chunk_tailored.selection.json').write_text('{}', encoding='utf-8')
        entries = [e for e in api.resume_entries() if e['filename'].endswith('_chunk_tailored.docx')]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['kind'], 'tailored')
        self.assertTrue(entries[0]['hasTextPreview'])
        self.assertTrue(all(p.suffix == '.docx' for p in api.resumes_for('12345')))


if __name__ == '__main__':
    unittest.main()
