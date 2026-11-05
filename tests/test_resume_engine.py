"""Frontend 'Generate review draft' -> chunk editor wiring; never calls OpenAI."""
from __future__ import annotations
import importlib.util
import json
import shutil
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

    def test_master_overview_and_open(self):
        from resume_chunks import parse_docx
        from test_chunk_composition_v04 import create_master
        self.assertEqual(api.master_overview(), {'found': False})
        master = api.ROOT / 'Resume_Master Test.docx'
        create_master(master)
        selection = api.RESUMES / '12345_20261104_131313_000003_chunk_tailored.selection.json'
        try:
            bullet = parse_docx(master)['entries'][0]['bullets'][0]
            selection.write_text(json.dumps({'writer_v06': {'fact_questions': [
                {'bullet_id': bullet['id'], 'question': 'How long did processing take?'},
                {'bullet_id': bullet['id'], 'question': 'how long did processing take?'},  # duplicate, merged
                {'bullet_id': 'bullet_edited_away', 'question': 'Old question'}]}}), encoding='utf-8')
            overview = api.master_overview()
            self.assertTrue(overview['found'])
            self.assertEqual(overview['filename'], 'Resume_Master Test.docx')
            self.assertEqual(overview['entries'][0]['title'], 'Amazon China')
            self.assertEqual(len(overview['openQuestions']), 1)
            self.assertEqual(overview['openQuestions'][0]['bullet'], bullet['text'])
            self.assertEqual(overview['openQuestions'][0]['questions'],
                             [{'question': 'How long did processing take?', 'jobs': ['Acme — SWE Intern']}])
            self.assertEqual(overview['resolvedQuestions'], 1)
            opened = []
            original = api.OPEN_FILE
            try:
                api.OPEN_FILE = opened.append
                self.assertEqual(self.status_of_path('/api/master/open', {}), 200)
                self.assertEqual(opened, [str(master)])
                api.OPEN_FILE = None
                self.assertEqual(self.status_of_path('/api/master/open', {}), 501)
            finally:
                api.OPEN_FILE = original
        finally:
            master.unlink(missing_ok=True)
            selection.unlink(missing_ok=True)

    def status_of_path(self, path, data):
        req = Request(f'http://127.0.0.1:{self.port}{path}', data=json.dumps(data).encode('utf-8'),
                      headers={'Origin': 'http://localhost:3000', 'Content-Type': 'application/json',
                               'X-Job-Agent-Action': 'local-user-approved'}, method='POST')
        try:
            with urlopen(req, timeout=4) as response:
                return response.status
        except HTTPError as exc:
            exc.close()
            return exc.code

    def test_download_is_named_after_the_job(self):
        self.assertEqual(api.download_name('Software Engineer Intern'), 'Software Engineer Intern_resume.docx')
        self.assertEqual(api.download_name('Gameplay Programmer Intern / 游戏客户端程序实习'),
                         'Gameplay Programmer Intern 游戏客户端程序实习_resume.docx')
        self.assertEqual(api.download_name('A: B? "C" <D>|E*'), 'A B C D E_resume.docx')
        self.assertEqual(api.download_name(None), 'Job_resume.docx')
        docx = api.RESUMES / '12345_20261104_141414_000004_chunk_tailored.docx'
        docx.write_bytes(b'PK\x03\x04FAKE')
        self.addCleanup(docx.unlink, missing_ok=True)
        index = next(i for i, p in enumerate(api.resumes_for('12345')) if p.name == docx.name)
        req = Request(f'http://127.0.0.1:{self.port}/api/resumes/12345/{index}/download', headers={'Origin': 'http://localhost:3000'})
        with urlopen(req, timeout=4) as response:
            disposition = response.headers['Content-Disposition']
            self.assertEqual(response.read(), b'PK\x03\x04FAKE')
        self.assertIn('filename="SWE Intern_resume.docx"', disposition)
        self.assertIn("filename*=UTF-8''SWE%20Intern_resume.docx", disposition)
        entry = next(e for e in api.resume_entries() if e['filename'] == docx.name)
        self.assertEqual(entry['downloadName'], 'SWE Intern_resume.docx')

    def test_save_folder_and_save_copy(self):
        target = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, target, ignore_errors=True)
        self.addCleanup(lambda: api.settings_file().unlink(missing_ok=True))
        # Unset: saving needs a folder; relative, missing and secrets/ folders are rejected.
        self.assertEqual(api.get_save_folder(), '')
        self.assertEqual(self.status_of_path('/api/save-folder', {'folder': 'relative/path'}), 400)
        self.assertEqual(self.status_of_path('/api/save-folder', {'folder': str(target / 'missing')}), 400)
        (api.ROOT / 'secrets').mkdir(exist_ok=True)
        self.assertEqual(self.status_of_path('/api/save-folder', {'folder': str(api.ROOT / 'secrets')}), 400)
        docx = api.RESUMES / '12345_20261104_151515_000005_chunk_tailored.docx'
        docx.write_bytes(b'PK\x03\x04SAVE')
        self.addCleanup(docx.unlink, missing_ok=True)
        index = next(i for i, p in enumerate(api.resumes_for('12345')) if p.name == docx.name)
        self.assertEqual(self.status_of_path(f'/api/resumes/12345/{index}/save', {}), 400)
        # Set (quotes are tolerated, as pasted from Explorer), then save twice: no overwrite.
        self.assertEqual(self.status_of_path('/api/save-folder', {'folder': f'"{target}"'}), 200)
        self.assertEqual(api.get_save_folder(), str(target.resolve()))
        self.assertEqual(self.status_of_path(f'/api/resumes/12345/{index}/save', {}), 201)
        self.assertEqual(self.status_of_path(f'/api/resumes/12345/{index}/save', {}), 201)
        self.assertEqual(sorted(p.name for p in target.iterdir()),
                         ['SWE Intern_resume (2).docx', 'SWE Intern_resume.docx'])
        self.assertEqual((target / 'SWE Intern_resume.docx').read_bytes(), b'PK\x03\x04SAVE')
        # Browse uses the native picker seam; cancel keeps the folder.
        original = api.BROWSE_FOLDER
        try:
            api.BROWSE_FOLDER = lambda initial: ''
            self.assertEqual(self.status_of_path('/api/save-folder/browse', {}), 200)
            self.assertEqual(api.get_save_folder(), str(target.resolve()))
            api.BROWSE_FOLDER = None
            self.assertEqual(self.status_of_path('/api/save-folder/browse', {}), 501)
        finally:
            api.BROWSE_FOLDER = original
        # Clearing returns to browser downloads.
        self.assertEqual(self.status_of_path('/api/save-folder', {'folder': ''}), 200)
        self.assertEqual(api.get_save_folder(), '')

    def test_draft_summary_for_review_page(self):
        docx = api.RESUMES / '12345_20261104_121212_000002_chunk_tailored.docx'
        docx.write_bytes(b'PK\x03\x04FAKE')
        self.addCleanup(docx.unlink, missing_ok=True)
        self.addCleanup(docx.with_suffix('.selection.json').unlink, missing_ok=True)
        docx.with_suffix('.selection.json').write_text(json.dumps({
            'entries': [{'id': 'e1', 'title': 'Amazon China', 'bullets': [
                {'id': 'b1', 'text': 'Processed 7.8 million ratings.'}, {'id': 'b2', 'text': 'Benchmarked four models.'}]}],
            'selected_bullet_ids': ['b1', 'b2'],
            'writer_v06': {'model': 'gpt-5.4', 'jd_focus': ['data analysis'],
                           'fact_questions': [{'bullet_id': 'b2', 'question': 'Which metric improved?'}],
                           'skills_reordered': {'58': 'Programming Languages: Python, C'}},
            'composition_v04': [{'entry_id': 'e1', 'source_ids': ['b1'], 'status': 'rewritten', 'text': 'Filtered 7.8 million ratings.'},
                                {'entry_id': 'e1', 'source_ids': ['b2'], 'status': 'unchanged', 'text': 'Benchmarked four models.'}],
            'page_fit_v05': {'render_check': {'pages': 1}}}), encoding='utf-8')
        summary = api.draft_summary(docx)
        self.assertEqual(summary['focus'], ['data analysis'])
        self.assertEqual(summary['questions'], [{'question': 'Which metric improved?', 'bullet': 'Benchmarked four models.'}])
        self.assertEqual(summary['changes'], [{'section': 'Amazon China', 'kind': 'rewritten',
                                               'before': ['Processed 7.8 million ratings.'], 'after': 'Filtered 7.8 million ratings.'}])
        self.assertEqual(summary['pageCount'], 1)
        self.assertEqual(api.draft_kind(api.RESUMES / '12345_manual_x_resume_draft.docx'), 'uploaded')
        self.assertIsNone(api.draft_summary(api.RESUMES / '12345_old_resume_draft.docx'))


if __name__ == '__main__':
    unittest.main()
