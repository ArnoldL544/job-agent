"""chunk-v0.6: JD-aware rewrites, looser wording rules with strict fact guards,
relevance ordering, skills reordering, fact questions and model fallback."""
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
import resume_selector as rs
from resume_chunks import parse_docx
from test_chunk_composition_v04 import JD, create_master

RATINGS = ('Processed over 7.8 million user-item ratings using Python and Pandas, filtering sparse '
           'interactions to construct a dataset of 183,575 ratings for recommendation modeling.')
WECHAT = 'Developed interactive service listing, detail, and appointment interfaces using JavaScript, WXML, WXSS, and JSON.'


class LooserWordingTests(unittest.TestCase):
    def test_equivalent_leading_verb_is_accepted(self):
        self.assertEqual(cw.check_rewrite(
            WECHAT, 'Built interactive service listing, detail, and appointment interfaces using JavaScript, WXML, WXSS, and JSON.'), [])

    def test_verb_from_later_in_source_is_accepted(self):
        good = ('Filtered over 7.8 million user-item ratings with Python and Pandas into a dataset of '
                '183,575 ratings for recommendation modeling, removing sparse interactions.')
        self.assertEqual(cw.check_rewrite(RATINGS, good), [])

    def test_non_equivalent_verb_is_rejected(self):
        bad = ('Designed a dataset of 183,575 ratings for recommendation modeling from over 7.8 million '
               'user-item ratings using Python and Pandas, filtering sparse interactions.')
        self.assertTrue(any('non-equivalent verb' in x for x in cw.check_rewrite(RATINGS, bad)))

    def test_ownership_escalation_is_rejected(self):
        led = 'Led ' + RATINGS[0].lower() + RATINGS[1:]
        self.assertTrue(any('escalates ownership' in x for x in cw.check_rewrite(RATINGS, led)))
        managing = WECHAT[:-1] + ', managing the front-end team.'
        self.assertIn('unsupported ownership claim: managing', cw.check_rewrite(WECHAT, managing))

    def test_base_form_impact_claim_is_rejected(self):
        bad = ('Filtered over 7.8 million user-item ratings with Python and Pandas into a dataset of '
               '183,575 ratings, removing sparse interactions to improve recommendation modeling.')
        self.assertIn('unsupported strong claim: improve', cw.check_rewrite(RATINGS, bad))

    def test_limited_ownership_verb_must_stay(self):
        src = 'Assisted coaches in supervising team members during regional competitions.'
        issues = cw.check_rewrite(src, 'Supported coaches in supervising team members during regional competitions.')
        self.assertTrue(any('limited-ownership verb changed' in x for x in issues), issues)

    def test_novel_word_cap(self):
        src = 'Developed booking interfaces using JavaScript.'
        six = 'Developed clear, responsive, accessible, consistent, polished, intuitive booking interfaces using JavaScript.'
        self.assertEqual(len(cw.novel_terms(src, six)), 6)
        self.assertFalse(any('novel content words' in x for x in cw.check_rewrite(src, six)))
        seven = six.replace('intuitive', 'intuitive, modern')
        self.assertTrue(any('novel content words' in x for x in cw.check_rewrite(src, seven)))

    def test_merge_accepts_equivalent_verb(self):
        c = 'Designed and integrated front-end components for service selection and appointment-related user interactions.'
        merged = ('Built service listing, detail, and appointment interfaces using JavaScript, WXML, WXSS, and JSON; '
                  'designed and integrated front-end components for service selection and user interactions.')
        self.assertEqual(cw.check_merge([WECHAT, c], merged), [])


def _labeled_master(path):
    d = Document()
    for t in ('Candidate Name', 'student@example.edu', 'EDUCATION', 'Example University\tNY',
              'BS Computer Science\tMay 2029', 'EXPERIENCE', 'Job Agent Development\tRochester, NY',
              'Independent Software Developer\tOct 2026 – Present'):
        d.add_paragraph(t)
    d.add_paragraph('Developed an automated job discovery pipeline using Python, Gmail API, and Playwright.',
                    style='List Paragraph')
    d.add_paragraph('SKILLS')
    for label, items in (('Programming Languages', ': Python, Java, C, JavaScript'),
                         ('Languages', ': Mandarin Chinese, English')):
        p = d.add_paragraph(style='List Paragraph')
        p.add_run(label).bold = True
        p.add_run(items)
    d.save(path)


class SkillsReorderTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.file = self.root / 'master.docx'
        _labeled_master(self.file)
        self.master = parse_docx(self.file)

    def test_jd_skills_move_first_and_spoken_languages_untouched(self):
        changes = cw.reorder_skills(self.master, 'We build frontends in JavaScript and Java.')
        self.assertEqual(list(changes.values()), ['Programming Languages: Java, JavaScript, Python, C'])

    def test_renderer_keeps_label_run_and_rejects_non_permutation(self):
        sel = {'source_sha256': self.master['source_sha256'],
               'selected_entry_ids': [e['id'] for e in self.master['entries']],
               'selected_bullet_ids': [b['id'] for e in self.master['entries'] for b in e['bullets']]}
        changes = cw.reorder_skills(self.master, 'JavaScript role')
        out = self.root / 'out.docx'
        rs.render_selected_docx(self.file, self.master, sel, out, skill_lines=changes)
        para = next(p for p in Document(out).paragraphs if p.text.startswith('Programming'))
        self.assertEqual(para.text, 'Programming Languages: JavaScript, Python, Java, C')
        self.assertTrue(para.runs[0].bold)
        idx = next(iter(changes))
        with self.assertRaises(ValueError):
            rs.render_selected_docx(self.file, self.master, sel, self.root / 'bad.docx',
                                    skill_lines={idx: 'Programming Languages: JavaScript, Python, Java, C, Rust'})


class _Client:
    """Returns jd_focus, fact questions and WeChat bullets in reversed (relevance) order."""
    def __init__(self, fail_first=None):
        self.responses, self.models, self.fail_first = self, [], fail_first

    def create(self, **kwargs):
        self.models.append(kwargs['model'])
        if self.fail_first and len(self.models) == 1:
            raise self.fail_first
        req = json.loads(kwargs['input'])
        self.request = req
        entries, first_id = [], None
        for e in req['source_entries']:
            bullets = e['bullets']
            first_id = first_id or bullets[0]['bullet_id']
            if e['entry_title'].startswith('WeChat'):
                bullets = list(reversed(bullets))
            entries.append({'entry_id': e['entry_id'],
                            'groups': [{'source_ids': [b['bullet_id']], 'text': b['text']} for b in bullets]})
        payload = {'jd_focus': ['frontend booking interfaces', 'Python automation'],
                   'entries': entries, 'review_notes': [],
                   'fact_questions': [{'bullet_id': first_id, 'question': 'How many ratings remained after filtering?'},
                                      {'bullet_id': 'bullet_unknown', 'question': 'dropped'}]}
        return SimpleNamespace(status='completed', output=[], output_text=json.dumps(payload))


class NotFoundError(Exception):
    pass


class GenerateV06Tests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.master = self.root / 'master.docx'
        create_master(self.master)

    def test_relevance_order_focus_and_questions_reach_outputs(self):
        client = _Client()
        result = cw.generate(client, self.master, JD, '11651900', self.root / 'out')
        self.assertIn('job_description', client.request)
        paras = [p.text for p in Document(result['docx']).paragraphs]
        designed = next(i for i, p in enumerate(paras) if p.startswith('Designed and integrated'))
        developed = next(i for i, p in enumerate(paras) if p.startswith('Developed interactive'))
        self.assertLess(designed, developed)  # model order kept within the entry
        self.assertLess(paras.index('Data Analysis Intern\tAug 2026 – Oct 2026'), designed)  # entries stay put
        audit = result['markdown'].read_text(encoding='utf-8')
        for heading in ('What this role values', 'Questions to strengthen your master resume',
                        'Wording to double-check', 'frontend booking interfaces',
                        'How many ratings remained after filtering?'):
            self.assertIn(heading, audit)
        self.assertNotIn('dropped', audit.split('## Questions')[1].split('##')[0])
        extra = json.loads(result['selection_json'].read_text(encoding='utf-8'))['writer_v06']
        self.assertEqual(extra['model'], cw.MODEL)
        self.assertEqual(len(extra['fact_questions']), 1)
        self.assertEqual(result['fact_questions'], 1)

    def test_unavailable_model_falls_back_once(self):
        if cw.MODEL == cw.FALLBACK_MODEL:
            self.skipTest('default model already equals fallback')
        client = _Client(fail_first=NotFoundError('The model gpt-x does not exist'))
        result = cw.generate(client, self.master, JD, '11651900', self.root / 'fb')
        self.assertEqual(client.models, [cw.MODEL, cw.FALLBACK_MODEL])
        self.assertEqual(result['model'], cw.FALLBACK_MODEL)

    def test_other_errors_are_not_retried(self):
        client = _Client(fail_first=RuntimeError('rate limited'))
        with self.assertRaises(RuntimeError):
            cw.generate(client, self.master, JD, '11651900', self.root / 'err')
        self.assertEqual(len(client.models), 1)


if __name__ == '__main__':
    unittest.main()
