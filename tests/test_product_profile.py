"""Offline tests: never use real Gmail, actual resume or OpenAI services."""
import importlib.util
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

spec = importlib.util.spec_from_file_location('product_api', Path(__file__).resolve().parents[1] / 'api_local.py')
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


class ProductProfileTests(unittest.TestCase):
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
        cls.server = ThreadingHTTPServer(('127.0.0.1', 0), api.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    def get(self):
        req = Request(f'http://127.0.0.1:{self.port}/api/profile', headers={'Origin':'http://localhost:3000'})
        with urlopen(req, timeout=4) as res:
            return res.status, json.load(res)

    def post(self, data, origin='http://localhost:3000', action_header=True):
        headers={'Origin':origin, 'Content-Type':'application/json'}
        if action_header: headers['X-Job-Agent-Action'] = 'local-user-approved'
        return Request(f'http://127.0.0.1:{self.port}/api/profile',
                       data=json.dumps(data).encode('utf-8'), headers=headers, method='POST')

    def test_blank_get(self):
        status, payload = self.get()
        self.assertEqual(status, 200)
        self.assertEqual(payload['profile']['education'], [])
        self.assertEqual(payload['profile']['personal']['email'], '')

    def test_round_trip_and_allowlist(self):
        profile = api.blank_profile()
        profile['personal']['fullName'] = 'Test Person'
        profile['personal']['email'] = 'local-test@example.invalid'
        profile['personal']['access_token'] = 'unsafe'  # Should not be persisted
        profile['work'].append({'id':'work_01','title':'Intern','organization':'Test Org','role':'Developer',
                                'period':'Summer','location':'Remote','description':'Implemented a tool', 'secret':'remove'})
        with urlopen(self.post({'profile':profile}), timeout=4) as res:
            saved=json.load(res)['profile']
        self.assertEqual(saved['personal']['fullName'], 'Test Person')
        self.assertNotIn('access_token', saved['personal'])
        self.assertNotIn('secret',saved['work'][0])
        _, body = self.get()
        self.assertEqual(body['profile'],saved)
        self.assertTrue((api.ROOT/'profile_data.json').is_file())

    def test_post_denied_without_origin_or_header(self):
        for options in ({'origin':'https://malicious.example'}, {'action_header':False}):
            with self.subTest(options=options):
                with self.assertRaises(HTTPError) as error:
                    urlopen(self.post({'profile':api.blank_profile()}, **options), timeout=4)
                self.assertEqual(error.exception.code,403)

    def test_profile_validation_rejects_bad_types_and_duplicates(self):
        for bad in (None, {'work':{'x':1}}, {'education':[{'id':'../../outside'}]},
                    {'personal':{'fullName':123}}, {'skills':{'languages':'A'*2501}}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    api.validate_profile(bad)
        profile=api.blank_profile()
        profile['education']=[{'id':'same'}, {'id':'same'}]
        with self.assertRaises(ValueError):api.validate_profile(profile)

    def test_no_unintended_legacy_profile_update(self):
        self.assertFalse((api.ROOT/'profile.txt').exists())


if __name__ == '__main__':unittest.main()
