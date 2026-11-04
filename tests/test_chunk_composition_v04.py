"""v0.4 composition with verified provenance and Word rendering (offline mocks)."""
import hashlib
import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest import mock
from docx import Document

import os
os.environ.setdefault('JOB_AGENT_VERIFY_PAGES', '0')  # tests never launch Word
import resume_chunk_writer as cw

JD = ('Job description: Build frontend user interfaces for service listings, '
      'booking navigation and appointment applications using JavaScript. '
      'Also use APIs, automated pipelines and Python. ' * 8)


def create_master(path):
    d=Document()
    for t in ('Candidate Name', 'student@example.edu', 'EDUCATION',
              'Example University\tNY', 'BS Computer Science\tMay 2029'):
        d.add_paragraph(t)
    d.add_paragraph('GPA 3.82',style='List Paragraph')
    d.add_paragraph('EXPERIENCE')
    d.add_paragraph('Amazon China\tBeijing, China')
    d.add_paragraph('Data Analysis Intern\tAug 2026 – Oct 2026')
    d.add_paragraph('Processed 7.8 million ratings using Python and Pandas.', style='List Paragraph')
    d.add_paragraph('WeChat Mini Program — Beauty Service Booking Application\tRemote')
    d.add_paragraph('Independent Software Developer\tJun 2026 – Oct 2026')
    d.add_paragraph('Developed interactive service listing, detail, and appointment interfaces using JavaScript, WXML, WXSS, and JSON.',style='List Paragraph')
    d.add_paragraph('Implemented dynamic content rendering, page navigation, and event handling to support service browsing and booking-related interactions.',style='List Paragraph')
    d.add_paragraph('Designed and integrated front-end components for service selection and appointment-related user interactions.',style='List Paragraph')
    d.add_paragraph('Job Agent Development\tRochester, NY')
    d.add_paragraph('Independent Software Developer\tOct 2026 – Present')
    d.add_paragraph('Developed an automated job discovery pipeline using Python, Gmail API, and Playwright.',style='List Paragraph')
    d.add_paragraph('SKILLS')
    d.add_paragraph('Python, JavaScript, C, Git',style='List Paragraph')
    d.save(path)


MERGED = ('Developed service listing, detail, and appointment interfaces using '
          'JavaScript, WXML, WXSS, and JSON; designed and integrated front-end '
          'components for service selection and user interactions.')

class GroupClient:
    def __init__(self, invalid=None):
        self.invalid = invalid
        self.responses = self
        self.calls = 0
    def create(self, **kwargs):
        self.calls += 1
        req = json.loads(kwargs['input'])
        out=[]
        for e in req['source_entries']:
            bullets=e['bullets']
            if e['merge_allowed'] and len(bullets)>=3 and e['entry_title'].startswith('WeChat'):
                merged=MERGED
                if self.invalid=='invent':
                    merged += ' Deployed React and improved conversions by 70%.'
                if self.invalid=='missing':
                    group=[{'source_ids':[bullets[0]['bullet_id'],bullets[2]['bullet_id']], 'text': merged}]
                elif self.invalid=='cross':
                    foreign=req['source_entries'][0]['bullets'][0]['bullet_id']
                    group=[{'source_ids':[bullets[0]['bullet_id'],foreign], 'text': merged},
                           {'source_ids':[bullets[1]['bullet_id']], 'text':bullets[1]['text']}]
                else:
                    group=[{'source_ids':[bullets[0]['bullet_id'],bullets[2]['bullet_id']], 'text':merged},
                           {'source_ids':[bullets[1]['bullet_id']], 'text':bullets[1]['text']}]
            else:
                group=[{'source_ids':[b['bullet_id']], 'text':b['text']} for b in bullets]
            out.append({'entry_id': e['entry_id'], 'groups':group})
        return SimpleNamespace(status='completed',output=[], output_text=json.dumps({'entries':out,'review_notes':[]}))


class CompositionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.master=self.root/'master.docx'
        create_master(self.master)
        self.original_prepare=cw.prepare
        def full_wechat(master_file,jd):
            master, selection, bullets=self.original_prepare(master_file,jd)
            w=next(e for e in master['entries'] if e['title'].startswith('WeChat'))
            ids={b['id'] for b in w['bullets']}
            selection=deepcopy(selection)
            selection['selected_bullet_ids']=sorted(set(selection['selected_bullet_ids'])|ids)
            selection['selected_entry_ids']=sorted(set(selection['selected_entry_ids'])|{w['id']})
            full_bullets=[{'bullet_id':b['id'],'text':b['text'],'entry_id':e['id'],'entry_title':e['title']}
                for e in master['entries'] for b in e['bullets'] if b['id'] in selection['selected_bullet_ids']]
            return master,selection,full_bullets
        self.patch=mock.patch.object(cw,'prepare',side_effect=full_wechat)
        self.patch.start();self.addCleanup(self.patch.stop)

    def test_successful_two_to_one_merge_keeps_source_provenance(self):
        before=hashlib.sha256(self.master.read_bytes()).hexdigest()
        client=GroupClient()
        result=cw.generate(client,self.master,JD,'11651900',self.root/'resumes')
        self.assertEqual(client.calls,1)
        self.assertEqual(result['accepted_merges'],1)
        self.assertEqual(result['selected_bullets']-result['final_bullets'],1)
        document=Document(result['docx'])
        text='\n'.join(p.text for p in document.paragraphs)
        self.assertIn(MERGED,text)
        self.assertEqual(text.count(MERGED),1)
        self.assertIn('Implemented dynamic content rendering', text)
        self.assertIn('Python, JavaScript, C, Git',text)
        self.assertIn('May 2029', text)
        self.assertEqual(hashlib.sha256(self.master.read_bytes()).hexdigest(),before)
        audit=result['markdown'].read_text(encoding='utf-8')
        self.assertIn('accepted merges: 1',audit)
        selection=json.loads(result['selection_json'].read_text(encoding='utf-8'))
        merged=[g for g in selection['composition_v04'] if g['status']=='merged']
        self.assertEqual(len(merged),1)
        self.assertEqual(len(merged[0]['source_ids']),2)
        self.assertEqual(len(selection['selected_bullet_ids']), result['final_bullets'])
        w=next(p for p in document.paragraphs if p.text.startswith('WeChat Mini Program'))
        self.assertFalse(w.paragraph_format.keep_with_next)
        self.assertGreater(w.paragraph_format.space_before.pt,0)

    def test_invented_technology_and_metric_fallback_to_two_originals(self):
        result=cw.generate(GroupClient('invent'),self.master,JD,'11651900',self.root/'resumes')
        self.assertEqual(result['accepted_merges'],0)
        self.assertEqual(result['rejected_merges'],1)
        txt='\n'.join(p.text for p in Document(result['docx']).paragraphs)
        self.assertNotIn('React',txt)
        self.assertNotIn('70%',txt)
        self.assertIn('Designed and integrated front-end components',txt)
        self.assertIn('merge rejected',result['markdown'].read_text(encoding='utf-8'))

    def test_cross_entry_source_fails_without_files(self):
        folder=self.root/'cross'
        with self.assertRaises(ValueError):
            cw.generate(GroupClient('cross'),self.master,JD,'11651900',folder)
        self.assertEqual(list(folder.glob('*.docx')) if folder.exists() else [],[])

    def test_missing_source_falls_back_to_originals_for_that_entry(self):
        # v0.4.1: an omitted ID no longer wastes the whole paid draft; only the
        # broken entry reverts to its original, source-identical bullets.
        result=cw.generate(GroupClient('missing'),self.master,JD,'11651900',self.root/'missing')
        self.assertEqual(result['entry_fallbacks'],1)
        self.assertEqual(result['accepted_merges'],0)
        txt='\n'.join(p.text for p in Document(result['docx']).paragraphs)
        self.assertNotIn(MERGED,txt)
        for s in ('Developed interactive service listing','Implemented dynamic content rendering',
                  'Designed and integrated front-end components'):
            self.assertIn(s,txt)

    def test_merge_guards_qualifiers_and_numbers(self):
        self.assertTrue(cw.check_merge([
            'Developed a booking prototype with Python for only 12 users.',
            'Assisted with data validation under mentor guidance.'
        ],'Developed a scalable booking platform with Python for 20 users.'))
        self.assertEqual(cw.check_merge([
            'Developed interactive service listing, detail, and appointment interfaces using JavaScript, WXML, WXSS, and JSON.',
            'Designed and integrated front-end components for service selection and appointment-related user interactions.'
        ],MERGED),[])

if __name__=='__main__':unittest.main()
