"""Run from the project root: python -m unittest discover -s tests -p test_stage4.py"""
from __future__ import annotations

import importlib.util
import json
import tempfile
import threading
import unittest
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

MODULE_FILE = Path(__file__).resolve().parents[1] / "api_local.py"
spec = importlib.util.spec_from_file_location("local_api_for_test", MODULE_FILE)
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)


class Stage4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        api.ROOT = Path(cls.temp.name)
        api.JOBS = api.ROOT / "jobs"
        api.RESUMES = api.ROOT / "resumes"
        api.JOBS.mkdir()
        api.RESUMES.mkdir()
        api.SOURCES = [api.JOBS / "handshake_email_jobs.json", api.JOBS / "job_screen_results.json"]
        api.RESUME_STATE = api.JOBS / "resume_draft_state.json"
        (api.JOBS / "job_screen_results.json").write_text(json.dumps([
            {"job_id": "12345", "company": "Test Employer", "title": "Software Intern", "match_score": 87,
             "priority": "高匹配·优先核实", "flags": ["Confirm work eligibility"]}
        ]), encoding="utf-8")
        (api.JOBS / "12345_20261026_description.txt").write_text("Full saved JD: Python, SQL, and APIs", encoding="utf-8")
        (api.RESUMES / "12345_test_resume_draft.docx").write_bytes(b"PK\x03\x04FAKE")
        (api.RESUMES / "12345_test_resume_draft.md").write_text("# Mock private resume preview", encoding="utf-8")
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), api.Handler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.temp.cleanup()

    def query(self, path, origin="http://localhost:3000"):
        request = Request(f"http://127.0.0.1:{self.port}{path}", headers={"Origin": origin})
        with urlopen(request) as response:
            return response.status, response.headers, response.read()

    def test_summary(self):
        _, _, body = self.query("/api/jobs")
        payload = json.loads(body)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["jobs"][0]["resumeCount"], 1)
        self.assertTrue(payload["jobs"][0]["hasJd"])

    def test_full_jd(self):
        _, _, body = self.query("/api/jobs/12345/detail")
        payload = json.loads(body)
        self.assertIn("Python, SQL", payload["jdText"])
        self.assertEqual(payload["priority"], "高匹配·优先核实")

    def test_resume_list_preview_download(self):
        _, _, body = self.query("/api/resumes")
        payload = json.loads(body)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["resumes"][0]["jobId"], "12345")
        _, _, body = self.query("/api/resumes/12345/0/preview")
        self.assertIn("Mock private resume preview", json.loads(body)["text"])
        _, headers, body = self.query("/api/resumes/12345/0/download")
        self.assertEqual(body, b"PK\x03\x04FAKE")
        self.assertIn("attachment", headers["Content-Disposition"])

    def test_denied_origin(self):
        with self.assertRaises(HTTPError) as error:
            self.query("/api/jobs", origin="https://malicious.example")
        self.assertEqual(error.exception.code, 403)

    def test_unknown_ids_and_path(self):
        for path in ("/api/jobs/99999/detail", "/api/resumes/99999/0/download", "/api/resumes/12345/99/download", "/api/resumes/../token.json"):
            with self.subTest(path=path):
                with self.assertRaises(HTTPError) as error:
                    self.query(path)
                self.assertEqual(error.exception.code, 404)

    def test_outside_paths_rejected(self):
        outside = api.ROOT / "outside_resume_draft.docx"
        outside.write_bytes(b"private")
        api.RESUME_STATE.write_text(json.dumps({"12345": {"docx": str(outside)}}), encoding="utf-8")
        try:
            self.assertEqual(len(api.resumes_for("12345")), 1)
        finally:
            api.RESUME_STATE.unlink()


if __name__ == "__main__":
    unittest.main()
