"""chunk-v0.5: page-budget selection, JD noise fixes, refill and page trimming (offline)."""
import json
import os
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from docx import Document

os.environ.setdefault('JOB_AGENT_VERIFY_PAGES', '0')  # tests never launch Word
import resume_chunk_writer as cw
import resume_chunks as rc
import resume_layout as rl
import resume_selector as rs

FRONTEND_JD = '''Software Engineering Intern
Job description
About the role
Build user-facing features for our web application across the front-end and back-end.
Responsibilities
- Develop user interfaces in JavaScript and React for booking flows
- Integrate REST APIs with server-side services
Requirements
- Experience with JavaScript, HTML/CSS
- Familiarity with Python
About Acme
We offer a hybrid work model, networking opportunities and the rest of our benefits.
Our network of partners is interactive and automated.
'''
BOILERPLATE_ONLY = '''About us
We offer a hybrid work model, networking events, and the rest of our benefits.
Benefits
Interactive onboarding with automated tools and our network of partners.
'''


def create_master_v05(path, campus_heading='CAMPUS LEADERSHIP ACTIVITIES'):
    d = Document()
    bullet = lambda t: d.add_paragraph(t, style='List Paragraph')
    for t in ('Candidate Name', 'student@example.edu', 'EDUCATION', 'Example University\tNY',
              'BS Computer Science\tMay 2029'):
        d.add_paragraph(t)
    bullet('GPA 3.82')
    d.add_paragraph('EXPERIENCE')
    d.add_paragraph('Amazon China\tBeijing, China')
    d.add_paragraph('Data Analysis Intern\tAug 2026 – Oct 2026')
    bullet('Processed 7.8 million ratings using Python and Pandas for recommendation modeling.')
    bullet('Benchmarked four recommendation algorithms, reaching a Hit Rate@10 of 12.12% with item-based CF.')
    d.add_paragraph('WeChat Mini Program — Beauty Service Booking Application\tRemote')
    d.add_paragraph('Independent Software Developer\tJun 2026 – Oct 2026')
    bullet('Developed interactive service listing, detail, and appointment interfaces using JavaScript, WXML, WXSS, and JSON.')
    bullet('Implemented dynamic content rendering, page navigation, and event handling to support service browsing and booking-related interactions.')
    bullet('Designed and integrated front-end components for service selection and appointment-related user interactions.')
    d.add_paragraph('Job Agent Development\tRochester, NY')
    d.add_paragraph('Independent Software Developer\tOct 2026 – Present')
    bullet('Developed an automated job discovery pipeline using Python, Gmail API, and Playwright.')
    bullet('Implemented job matching with an interactive dashboard to track job listings.')
    d.add_paragraph(campus_heading)
    d.add_paragraph('University of Rochester, URCSA\tRochester, NY')
    d.add_paragraph('Event Planning Manager\tAug 2026 – Present')
    bullet('Lead the event planning department, coordinating team members and event preparation.')
    bullet('Organize cultural and social events for Chinese students.')
    d.add_paragraph('SKILLS')
    bullet('Python, JavaScript, C, Git')
    d.save(path)


class JdNoiseTests(unittest.TestCase):
    def test_prose_does_not_create_skills(self):
        prose = ('You will have the rest of the summer. We offer a hybrid work model, '
                 'networking opportunities, and C-suite exposure; Objective-C is not used.')
        self.assertEqual(rs.detect_skills(prose), set())

    def test_real_skills_still_detected(self):
        found = rs.detect_skills('Build REST APIs in C and C++; train predictive models; network protocols.')
        self.assertTrue({'api', 'c', 'c++', 'modeling', 'networking'} <= found, found)

    def test_boilerplate_is_ignored_and_fallback_used(self):
        self.assertEqual(rs.parse_jd(BOILERPLATE_ONLY), {'required': [], 'preferred': [], 'mentioned': []})
        weights = rs.job_priorities(BOILERPLATE_ONLY)
        self.assertEqual({k: v for k, v in weights.items() if v}, {'backend_api': .25})

    def test_weights_are_graded_and_focused(self):
        w = rs.job_priorities(FRONTEND_JD)
        self.assertEqual(w['frontend_ui'], 1.0)
        self.assertTrue(0 < w['backend_api'] < 1.0, w)
        self.assertEqual(w['data_ml'], 0.0)
        self.assertEqual(w['systems'], 0.0)

    def test_long_sentence_does_not_switch_section(self):
        jd = 'Requirements\n- Python\nRequirements gathering with stakeholders is part of the job; ' \
             'you will also document workflows and collaborate with product teams on Java tools.\n'
        rows = rs.segment_jd(jd)
        self.assertEqual([s for s, _ in rows], ['required', 'required', 'required'])


COMPANY_FIRST_JD = '''Software Engineer Intern
At a glance
£50K/yr
Job description
About Arctic Lake
We build trading technology. You could go deep in systems programming on one project.
Throughout it all, you will rely on data analysis.
A Day at Arctic Lake
We are big believers in the power of being in the room.
During your internship, you will probably work on one of the following projects
ALX Trading Engine: Low-latency processing for market data and order routing.
Hardware Acceleration: FPGA-based system for offloading time sensitive logic checks.
Who this is for
If you value depth over brand names, this will suit you.
The Challenge: Our Technical Assessment
Our initial coding challenge is in Java. You will use Python, TypeScript and Kubernetes.
The Package
Salary: £50,000 per annum. Perks: social events, networking.
'''


class CompanyFirstJdTests(unittest.TestCase):
    """v0.5.1 regression: a JD that opens with "About <Company>" lost its whole body."""

    def test_body_after_company_intro_is_not_skipped(self):
        found = set(rs.parse_jd(COMPANY_FIRST_JD)['mentioned'])
        self.assertTrue({'java', 'python', 'typescript', 'kubernetes', 'data analysis'} <= found, found)

    def test_internship_projects_count_as_responsibilities(self):
        rows = dict((line[:20], section) for section, line in rs.segment_jd(COMPANY_FIRST_JD))
        self.assertEqual(rows['ALX Trading Engine: '], 'responsibilities')
        self.assertEqual(rows['About Arctic Lake'], 'company')
        self.assertEqual(rows['Salary: £50,000 per '], 'boilerplate')

    def test_systems_role_is_strongest(self):
        w = rs.job_priorities(COMPANY_FIRST_JD)
        self.assertEqual(max(w, key=w.get), 'systems')
        self.assertGreaterEqual(rs.jd_signal(COMPANY_FIRST_JD), rs.WEAK_JD_SIGNAL)

    def test_bulleted_short_requirements_do_not_reset_section(self):
        jd = 'About Acme\n- Health Insurance\n- Free Lunch\nWe build APIs.\n'
        self.assertEqual([s for s, _ in rs.segment_jd(jd)], ['company'] * 4)


class HeadingTests(unittest.TestCase):
    def test_campus_leadership_heading_recognised(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'm.docx'
            create_master_v05(path)
            master = rc.parse_docx(path)
        urcsa = next(e for e in master['entries'] if e['title'].startswith('University of Rochester'))
        self.assertEqual(urcsa['kind'], 'leadership')
        self.assertEqual(urcsa['role'], 'Event Planning Manager')
        self.assertFalse(any(e['title'] == 'CAMPUS LEADERSHIP ACTIVITIES' for e in master['entries']))


class LayoutTests(unittest.TestCase):
    """Line counts measured on a real render of the user's master (Cambria 11pt, 482pt)."""

    CASES = [
        ('Designed and integrated front-end components for service selection and appointment-related user interactions.', 2),
        ('Developed interactive service listing, detail, and appointment interfaces using JavaScript, WXML, WXSS, and JSON.', 2),
        ('Developed interactive service listing, detail, and appointment interfaces using JavaScript, WXML, WXSS, and JSON; '
         'implemented dynamic content rendering, page navigation, and event handling for service browsing and booking interactions.', 3),
        ('Programming Languages: Python, Java, C, JavaScript, R, MATLAB', 1),
    ]

    def test_wrap_matches_measured_render(self):
        for text, lines in self.CASES:
            with self.subTest(text=text[:40]):
                self.assertEqual(rl.wrap_line_count(text, 482.0, 11.0), lines)


class _Fixture(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.master_file = self.root / 'master.docx'
        create_master_v05(self.master_file)
        self.master = rc.parse_docx(self.master_file)
        self.model = rl.PageModel(self.master_file, self.master)
        patcher = mock.patch.dict(os.environ, {'JOB_AGENT_VERIFY_PAGES': '0'})
        patcher.start()
        self.addCleanup(patcher.stop)

    def by_title(self, selection, prefix):
        return next(e for e in selection['entries'] if e['title'].startswith(prefix))


class PageSelectionTests(_Fixture):
    def test_large_page_takes_all_technical_then_activity_in_master_order(self):
        sel = rs.select_chunks(self.master, FRONTEND_JD, page_budget=self.model)
        self.assertLessEqual(sel['page_plan']['used_pt'], sel['page_plan']['budget_pt'])
        for prefix in ('Amazon', 'WeChat', 'Job Agent'):
            self.assertTrue(all(b['selected'] for b in self.by_title(sel, prefix)['bullets']), prefix)
        urcsa = self.by_title(sel, 'University of Rochester')
        self.assertTrue(urcsa['bullets'][0]['selected'])  # first (context) bullet comes first
        self.assertEqual(urcsa['bullets'][0]['phase'], 'activity')

    def test_tight_page_keeps_internship_and_relevant_work(self):
        with mock.patch.object(rl.PageModel, 'budget_pt', return_value=160.0):
            sel = rs.select_chunks(self.master, FRONTEND_JD, page_budget=self.model)
        self.assertLessEqual(sel['page_plan']['used_pt'], 160.0)
        self.assertTrue(self.by_title(sel, 'Amazon')['selected'])        # internship anchor
        self.assertTrue(self.by_title(sel, 'WeChat')['selected'])        # most relevant to frontend
        self.assertFalse(self.by_title(sel, 'University of Rochester')['selected'])

    def test_weak_jd_is_flagged_and_nothing_labelled_relevant(self):
        sel = rs.select_chunks(self.master, BOILERPLATE_ONLY, page_budget=self.model)
        self.assertTrue(sel['page_plan']['jd_signal_weak'])
        phases = {b.get('phase') for e in sel['entries'] for b in e['bullets'] if b['selected']}
        self.assertNotIn('relevance', phases)
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / 'r.md'
            rs.export_report(sel, report)
            self.assertIn('JD signal too weak to tailor', report.read_text(encoding='utf-8'))

    def test_legacy_mode_unchanged_without_page_budget(self):
        sel = rs.select_chunks(self.master, FRONTEND_JD)
        self.assertNotIn('page_plan', sel)
        self.assertLessEqual(len(sel['selected_bullet_ids']), 8)


MERGE = ('Developed interactive service listing, detail, and appointment interfaces using JavaScript, WXML, WXSS, and JSON; '
         'implemented dynamic content rendering, page navigation, and event handling for service browsing and booking interactions.')


class _Client:
    """Mock model: merges WeChat bullets 1+2 like the user's real v0.4.1 run."""
    def __init__(self):
        self.responses = self

    def create(self, **kwargs):
        req = json.loads(kwargs['input'])
        if 'source_entries' in req:
            out = []
            for e in req['source_entries']:
                b = e['bullets']
                if e['entry_title'].startswith('WeChat') and len(b) >= 3:
                    groups = [{'source_ids': [b[0]['bullet_id'], b[1]['bullet_id']], 'text': MERGE}]
                    groups += [{'source_ids': [x['bullet_id']], 'text': x['text']} for x in b[2:]]
                else:
                    groups = [{'source_ids': [x['bullet_id']], 'text': x['text']} for x in b]
                out.append({'entry_id': e['entry_id'], 'groups': groups})
            payload = {'entries': out, 'review_notes': []}
        else:
            payload = {'bullets': [{'bullet_id': b['bullet_id'], 'text': b['text']}
                                   for b in req['selected_source_bullets']], 'review_notes': []}
        return SimpleNamespace(status='completed', output=[], output_text=json.dumps(payload))


class WriterPageFitTests(_Fixture):
    def _budget_leaving_out_activity(self):
        # Everything technical fits; the activity needs ~1 more line than is left.
        sel = rs.select_chunks(self.master, FRONTEND_JD, page_budget=self.model)
        index = {b['id']: b for e in self.master['entries'] for b in e['bullets']}
        tech = {e: [(index[b], index[b]['text']) for b in ids]
                for e, ids in rs.fill_page(self.master, FRONTEND_JD, self.model,
                                           allow_activity_fill=False, budget_pt=1e6)[0].items()}
        tech_pt = self.model.plan_pt(tech)
        urcsa = next(e for e in self.master['entries'] if e['kind'] == 'leadership')
        one_activity = dict(tech, **{urcsa['id']: [(urcsa['bullets'][0], urcsa['bullets'][0]['text'])]})
        need = self.model.plan_pt(one_activity) - tech_pt
        return tech_pt + need - 6.0  # 6pt short: only a saved line makes room

    def test_merge_frees_space_and_activity_is_refilled_with_original_text(self):
        budget = self._budget_leaving_out_activity()
        with mock.patch.object(rl.PageModel, 'budget_pt', return_value=budget):
            result = cw.generate(_Client(), self.master_file, FRONTEND_JD, '11651900', self.root / 'out')
        self.assertEqual(result['accepted_merges'], 1)
        self.assertGreaterEqual(result['refilled'], 1)
        text = '\n'.join(p.text for p in Document(result['docx']).paragraphs)
        self.assertIn(MERGE, text)
        self.assertIn('Lead the event planning department', text)       # refilled, verbatim
        self.assertEqual(text.count('Implemented dynamic content rendering'), 0)  # absorbed source not re-added
        sel = json.loads(result['selection_json'].read_text(encoding='utf-8'))
        refill_rows = [r for r in sel['composition_v04'] if r['status'] == 'refill']
        self.assertTrue(refill_rows and all(len(r['source_ids']) == 1 for r in refill_rows))
        self.assertIn('Refilled with original master bullets', result['markdown'].read_text(encoding='utf-8'))

    def test_render_overflow_drops_lowest_value_bullet(self):
        os.environ['JOB_AGENT_VERIFY_PAGES'] = '1'
        calls = iter([(2, 'mock'), (1, 'mock')])
        with mock.patch.object(cw, 'count_pages', side_effect=lambda p: next(calls)):
            result = cw.generate(_Client(), self.master_file, FRONTEND_JD, '11651900', self.root / 'out2')
        self.assertEqual(result['page_count'], 1)
        self.assertEqual(result['dropped_for_space'], 1)
        text = '\n'.join(p.text for p in Document(result['docx']).paragraphs)
        # An activity bullet (lowest phase) goes first; relevant WeChat/Amazon work stays.
        activity_left = sum(s in text for s in ('Lead the event planning department',
                                                'Organize cultural and social events'))
        self.assertEqual(activity_left, 1)
        self.assertIn('Processed 7.8 million ratings', text)
        self.assertIn(MERGE, text)

    def test_page_check_can_be_disabled(self):
        with mock.patch.object(cw, 'count_pages') as counter:
            result = cw.generate(_Client(), self.master_file, FRONTEND_JD, '11651900', self.root / 'out3')
        counter.assert_not_called()
        self.assertEqual(result['page_check'], 'skipped')


if __name__ == '__main__':
    unittest.main()
