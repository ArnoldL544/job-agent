"""Phase 2: facts parsed from Handshake JDs and badge reasons (offline)."""
from __future__ import annotations
import importlib.util
import json
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

spec = importlib.util.spec_from_file_location("facts_api", Path(__file__).resolve().parents[1] / "api_local.py")
api = importlib.util.module_from_spec(spec)
spec.loader.exec_module(api)

UK_JD = """来源：https://example.joinhandshake.com/job-search/1

Example Ltd
Software
Numerical Software Engineer Intern
Posted 1 week ago∙Apply by November 13, 2026 at 6:59 PM

At a glance
£28K/yr
Hybrid, based in Cambridge, United Kingdom
Work in person for part of the week, from the location
Internship
Full-time∙From July 4, 2027 to June 30, 2028
US work authorization not required

What they're looking for
- Computer Science major
"""
US_JD = """Apply by November 7, 2026 at 2:59 AM

At a glance
$6–7K/mo
Medical coverage
Onsite, based in San Diego, CA
Internship
Part-time∙20 hours a week∙From June 29, 2026 to December 30, 2026
US work authorization required
Eligible for visa sponsorship

Job description
Build things.
"""


class JdFactsTests(unittest.TestCase):
    def test_uk_glance_block(self):
        self.assertEqual(api.jd_facts(UK_JD), {
            'deadline': '2026-11-13', 'pay': '£28K/yr', 'workplace': 'Hybrid',
            'location': 'Cambridge, United Kingdom', 'schedule': 'Full-time · Jul 2027 – Jun 2028',
            'usAuth': 'not required'})

    def test_us_glance_block_with_sponsorship(self):
        facts = api.jd_facts(US_JD)
        self.assertEqual(facts['pay'], '$6–7K/mo')
        self.assertEqual(facts['location'], 'San Diego, CA')
        self.assertEqual(facts['schedule'], 'Part-time · Jun 2026 – Dec 2026')
        self.assertEqual(api.work_auth_label(facts), 'US work authorization required · sponsors visas')

    def test_missing_block_is_empty_not_error(self):
        self.assertEqual(api.jd_facts('No header here'), {})
        self.assertEqual(api.work_auth_label({}), '')
        self.assertEqual(api.work_auth_label({'usAuth': 'required', 'optCpt': True}), 'US work authorization required · OPT/CPT OK')


class JobUrlTests(unittest.TestCase):
    def test_https_from_screening_or_jd_source_line(self):
        self.assertEqual(api.job_url({'url': 'https://rochester.joinhandshake.com/job-search/1'}),
                         'https://rochester.joinhandshake.com/job-search/1')
        self.assertEqual(api.job_url({}, UK_JD), 'https://example.joinhandshake.com/job-search/1')

    def test_unsafe_or_missing_links_are_dropped(self):
        for bad in ('javascript:alert(1)', 'http://example.com/job', 'data:text/html,hi', '', None, 42):
            with self.subTest(bad=bad):
                self.assertEqual(api.job_url({'url': bad}), '')


class NormalizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        api.ROOT = Path(cls.temp.name)
        api.JOBS = api.ROOT / 'jobs'
        api.JOBS.mkdir()
        api.RESUMES = api.ROOT / 'resumes'
        api.RESUMES.mkdir()
        (api.JOBS / '111_20261025_000000_000000_description.txt').write_text(UK_JD, encoding='utf-8')

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def row(self, **extra):
        base = {'job_id': '111', 'company': 'Example Ltd', 'title': 'Intern', 'match_score': 90,
                'jd_file': 'jobs/111_20261025_000000_000000_description.txt'}
        return dict(base, **extra)

    def test_facts_and_deadline_days(self):
        soon = (date.today() + timedelta(days=3)).isoformat()
        job = api.normalize(self.row(priority='高匹配·优先核实', deadline=soon))
        self.assertEqual(job['location'], 'Cambridge, United Kingdom')
        self.assertEqual(job['arrangement'], 'Hybrid')
        self.assertEqual(job['pay'], '£28K/yr')
        self.assertEqual(job['deadline'], soon)
        self.assertEqual(job['deadlineDays'], 3)
        self.assertEqual(job['reason'], '')  # high matches show no warning line
        self.assertEqual(job['url'], 'https://example.joinhandshake.com/job-search/1')  # from the JD 来源 line

    def test_conflict_badge_and_specific_reason(self):
        flags = ['若在美国境内实习，需向 UR ISO 核实 CPT/OPT 等适用工作授权',
                 '申请截止不足或等于 7 天，建议尽快确认资格',
                 '岗位地点可能在美国境外；需分别核实',
                 '要求 2028年9月前毕业，PROFILE 预计 2029年5月毕业']
        job = api.normalize(self.row(priority='低优先级·明确冲突', flags=flags))
        self.assertEqual(job['match'], 'Conflict')
        self.assertTrue(job['reason'].startswith('要求 2028年9月前毕业'))

    def test_verify_badge_prefers_location_conflict(self):
        flags = ['Handshake 概览和雇主 W-2 要求可能被误解', 'Remote 限定居民所在州；当前地点存在冲突']
        job = api.normalize(self.row(priority='待核实·地点限制', flags=flags))
        self.assertEqual(job['match'], 'Verify Eligibility')
        self.assertTrue(job['reason'].startswith('Remote 限定'))


if __name__ == '__main__':
    unittest.main()
