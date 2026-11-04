"""Release tests run only on temp data; never contact Gmail or OpenAI."""
import importlib.util
import io
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError

API_FILE = Path(__file__).resolve().parents[1] / "api_local.py"
PROFILE_FILE = Path(__file__).resolve().parents[1] / "profile_resume_source.py"

spec=importlib.util.spec_from_file_location("api_release_v05", API_FILE)
api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
prof_spec=importlib.util.spec_from_file_location("profile_release_v05", PROFILE_FILE)
prof=importlib.util.module_from_spec(prof_spec);prof_spec.loader.exec_module(prof)

class ReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory()
        root=Path(cls.temp.name)
        api.ROOT=root;api.JOBS=root/'jobs';api.JOBS.mkdir();api.RESUMES=root/'resumes';api.RESUMES.mkdir()
        api.SOURCES=[api.JOBS/'handshake_email_jobs.json',api.JOBS/'job_screen_results.json']
        api.RESUME_STATE=api.JOBS/'resume_draft_state.json'
        api.TRACKER_FILE=root/'application_tracker.json'
        api.SCHEDULE_FILE=root/'discovery_schedule.json'
        api.HISTORY_FILE=root/'task_history.json'
        api.SOURCES[0].write_text(json.dumps([{'job_id':'12345','company':'Test Company','title':'SWE Intern'}]))
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),api.Handler)
        cls.port=cls.server.server_address[1]
        cls.thread=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown();cls.server.server_close();cls.temp.cleanup()

    def send(self, path, payload=None, origin="http://localhost:3000", action=True, content_type="application/json"):
        headers={'Origin':origin}
        if payload is not None:
            headers['Content-Type']=content_type
            if action: headers['X-Job-Agent-Action']='local-user-approved'
            body=json.dumps(payload).encode() if isinstance(payload,dict) else payload
        else: body=None
        with urlopen(Request(f'http://127.0.0.1:{self.port}{path}',headers=headers,data=body,method='POST' if body is not None else 'GET'),timeout=5) as response:
            if 'json' in response.headers.get('Content-Type',''):
                return response.status,json.load(response)
            return response.status,response.read()

    def test_tracker_round_trip_and_notes_preserved_when_bookmarked(self):
        code,reply=self.send('/api/tracker',{'jobId':'12345','status':'Applied','deadline':'2026-11-01','note':'Interview followup'})
        self.assertEqual(code,200)
        self.assertEqual(reply['application']['status'],'Applied')
        _,reply=self.send('/api/tracker',{'jobId':'12345','saved':True})
        self.assertTrue(reply['application']['saved'])
        self.assertEqual(reply['application']['status'],'Applied')
        self.assertEqual(reply['application']['note'],'Interview followup')
        _,reply=self.send('/api/tracker')
        self.assertTrue(reply['applications']['12345']['saved'])

    def test_cannot_write_other_job_or_invalid_deadline(self):
        for payload in ({'jobId':'999','status':'Saved'},{'jobId':'12345','deadline':'2026-02-31'}):
            with self.assertRaises(HTTPError) as ctx:self.send('/api/tracker',payload)
            self.assertEqual(ctx.exception.code,400)

    def test_schedule_opt_in_and_disable(self):
        with self.assertRaises(HTTPError) as ctx:self.send('/api/schedule',{'enabled':True,'frequency':'daily'})
        self.assertEqual(ctx.exception.code,400)
        code,reply=self.send('/api/schedule',{'enabled':True,'frequency':'weekly','weekday':3,'hour':8,'minute':20,'maxEmails':15,'confirmRead':True})
        self.assertEqual(code,200)
        self.assertTrue(reply['schedule']['enabled'])
        code,reply=self.send('/api/schedule',{'enabled':False,'frequency':'weekly','weekday':3,'hour':8,'minute':20,'maxEmails':15})
        self.assertFalse(reply['schedule']['enabled'])

    def test_word_version_upload_and_download(self):
        from docx import Document
        doc=Document();doc.add_paragraph('Test draft, not a real resume')
        buf=io.BytesIO();doc.save(buf)
        status,result=self.send('/api/resumes/12345/upload',buf.getvalue(),content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        self.assertEqual(status,201)
        self.assertEqual(len(api.resumes_for('12345')),1)
        status,payload=self.send('/api/resumes/12345/0/download')
        self.assertEqual(status,200)
        self.assertEqual(payload[:2],b'PK')
        with self.assertRaises(HTTPError) as ctx:self.send('/api/resumes/67890/upload',buf.getvalue(),content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document')
        self.assertEqual(ctx.exception.code,400)

    def test_profile_to_resume_does_not_invent_or_overwrite(self):
        payload=api.blank_profile();payload['personal']['fullName']='Jane Test';payload['education']=[{'school':'Test University','major':'CS','gpa':'3.8'}]
        text=prof.profile_to_text(payload)
        self.assertIn('Test University',text)
        self.assertIn('Jane Test',text)
        self.assertNotIn('Amazon',text)
        (api.ROOT/'profile_data.json').write_text(json.dumps(payload),encoding='utf-8')
        self.assertEqual(prof.read_profile_text(api.ROOT),text)
        self.assertFalse((api.ROOT/'profile.txt').exists())
        with self.assertRaises(ValueError):prof.profile_to_text(api.blank_profile())

    def test_csrf_guards(self):
        with self.assertRaises(HTTPError) as ctx:self.send('/api/tracker',{'jobId':'12345'},origin='https://attacker.invalid')
        self.assertEqual(ctx.exception.code,403)
        with self.assertRaises(HTTPError) as ctx:self.send('/api/schedule',{'enabled':False},action=False)
        self.assertEqual(ctx.exception.code,403)

if __name__=='__main__':unittest.main(verbosity=2)
