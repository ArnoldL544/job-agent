"""v0.4.1 regression tests: each case reproduces a problem found in v0.4 review."""
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
from test_chunk_composition_v04 import JD, MERGED, create_master

A = 'Developed interactive service listing, detail, and appointment interfaces using JavaScript, WXML, WXSS, and JSON.'
B = 'Implemented dynamic content rendering, page navigation, and event handling to support service browsing and booking-related interactions.'
C = 'Designed and integrated front-end components for service selection and appointment-related user interactions.'


class OwnershipMergeTests(unittest.TestCase):
    """Problem 1: a merge could move 'assisted' / 'implemented' onto other work."""

    Q1 = 'Assisted with data validation for the recommender under mentor guidance.'
    Q2 = 'Implemented SVD baseline in Python for the recommender.'

    def test_swapped_ownership_merge_is_rejected(self):
        swapped = 'Assisted with an SVD baseline in Python and implemented data validation for the recommender under mentor guidance.'
        issues = cw.check_merge([self.Q1, self.Q2], swapped)
        self.assertTrue(any('must stay separate' in x for x in issues), issues)

    def test_even_a_faithful_merge_of_limited_bullet_is_rejected(self):
        faithful = 'Implemented SVD baseline in Python and assisted with data validation for the recommender under mentor guidance.'
        self.assertTrue(any('must stay separate' in x for x in cw.check_merge([self.Q1, self.Q2], faithful)))

    def test_limited_bullets_marked_ineligible_and_entry_not_offered_for_merge(self):
        master = {'entries': [{'id': 'e1', 'title': 'Recommender', 'bullets': [
            {'id': 'b1', 'text': self.Q1, 'paragraph': 1},
            {'id': 'b2', 'text': self.Q2, 'paragraph': 2},
            {'id': 'b3', 'text': 'Supported weekly evaluation reports.', 'paragraph': 3}]}]}
        groups = cw._selected_groups(master, {'selected_bullet_ids': ['b1', 'b2', 'b3']})
        self.assertEqual([b['merge_eligible'] for b in groups[0]['bullets']], [False, True, False])
        self.assertFalse(groups[0]['merge_allowed'])  # only one eligible bullet left

    def test_both_action_verbs_must_survive(self):
        dropped_designed = ('Developed service listing, detail, and appointment interfaces using '
                            'JavaScript, WXML, WXSS, and JSON with integrated front-end components '
                            'for service selection and user interactions.')
        issues = cw.check_merge([A, C], dropped_designed)
        self.assertTrue(any('lost original action verb: designed' in x for x in issues), issues)

    def test_known_good_wechat_merge_still_passes(self):
        self.assertEqual(cw.check_merge([A, C], MERGED), [])


class HyphenAndTokenTests(unittest.TestCase):
    """Problem 2: end-to-end / real-time were split into pieces and never caught."""

    def test_tokens_keep_hyphens_and_drop_final_period(self):
        self.assertEqual(cw._words('Built an end-to-end pipeline for analysis.'),
                         {'built', 'an', 'end-to-end', 'pipeline', 'for', 'analysis'})
        self.assertIn('node.js', cw._words('Used Node.js daily.'))

    def test_hyphenated_strong_claims_are_caught(self):
        src = 'Built a booking interface in JavaScript.'
        for claim in ('end-to-end', 'end to end', 'real-time', 'fine-tuned'):
            with self.subTest(claim=claim):
                issues = cw.check_rewrite(src, f'Built a {claim} booking interface in JavaScript.')
                self.assertTrue(any('unsupported strong claim' in x for x in issues), issues)

    def test_sentence_final_strong_claim_is_caught(self):
        issues = cw.check_rewrite('Built a booking interface in JavaScript.',
                                  'Built a booking interface in JavaScript for users.')
        self.assertIn('unsupported strong claim: users', issues)

    def test_reordering_to_sentence_end_is_not_flagged(self):
        src = 'Processed 7.8 million ratings using Python and Pandas for analysis.'
        self.assertEqual(cw.check_rewrite(src, 'Processed 7.8 million ratings for analysis using Python and Pandas.'), [])


class LegacyRewriteTests(unittest.TestCase):
    """Problem 3: the v0.3.1 path accepted rewrites that DROPPED numbers or tools."""

    SRC = 'Processed 7.8 million ratings using Python and Pandas for analysis.'

    def test_dropped_number_and_tool_rejected(self):
        issues = cw.check_rewrite(self.SRC, 'Processed ratings using Python for analysis.')
        self.assertIn('numeric evidence added or removed', issues)
        self.assertIn('named technology added or removed', issues)

    def test_legacy_polish_retains_original_when_number_dropped(self):
        bullets = [{'bullet_id': 'b1', 'text': self.SRC, 'entry_id': 'e', 'entry_title': 'Amazon'}]
        payload = {'bullets': [{'bullet_id': 'b1', 'text': 'Processed ratings using Python for analysis.'}],
                   'review_notes': []}
        client = SimpleNamespace(responses=SimpleNamespace(create=lambda **k: SimpleNamespace(
            status='completed', output=[], output_text=json.dumps(payload))))
        applied, warnings, _, diag = cw.polish(client, JD, bullets)
        self.assertEqual(applied, {})
        self.assertEqual(diag['b1']['status'], 'rejected')


class LineBudgetTests(unittest.TestCase):
    """Problem 5: a merge must actually save a Word line."""

    def test_merge_without_line_saving_is_rejected(self):
        s1 = 'Built Python scripts to clean survey data for the course project.'
        s2 = 'Wrote Python summaries of survey responses for the course team.'
        padded = ('Built Python scripts to clean survey data for the course project and wrote Python '
                  'summaries of survey responses for the course team, documenting each cleaning step.')
        self.assertEqual((cw.estimate_lines(s1), cw.estimate_lines(s2)), (1, 1))
        issues = cw.check_merge([s1, s2], padded)
        self.assertTrue(any('saves no estimated Word line' in x for x in issues), issues)


class _Client:
    def __init__(self, build):
        self.build, self.responses = build, self

    def create(self, **kwargs):
        req = json.loads(kwargs['input'])
        self.request = req
        return SimpleNamespace(status='completed', output=[],
                               output_text=json.dumps({'entries': self.build(req), 'review_notes': []}))


class ComposeStructureTests(unittest.TestCase):
    """Problem 4: out-of-order groups aborted a paid draft."""

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        self.master = self.root / 'master.docx'
        create_master(self.master)

    def test_out_of_order_groups_are_sorted_not_fatal(self):
        def build(req):
            out = []
            for e in req['source_entries']:
                groups = [{'source_ids': [b['bullet_id']], 'text': b['text']} for b in e['bullets']]
                if e['entry_title'].startswith('WeChat'):
                    b = e['bullets']
                    groups = [{'source_ids': [b[1]['bullet_id']], 'text': b[1]['text']},
                              {'source_ids': [b[0]['bullet_id'], b[2]['bullet_id']], 'text': MERGED}]
                out.append({'entry_id': e['entry_id'], 'groups': groups})
            return out
        client = _Client(build)
        result = cw.generate(client, self.master, JD, '11651900', self.root / 'out')
        self.assertEqual(result['accepted_merges'], 1)
        self.assertEqual(result['entry_fallbacks'], 0)
        self.assertGreaterEqual(result['estimated_lines_saved'], 1)
        paras = [p.text for p in Document(result['docx']).paragraphs]
        self.assertLess(paras.index(MERGED), next(i for i, p in enumerate(paras) if p.startswith('Implemented dynamic')))
        audit = result['markdown'].read_text(encoding='utf-8')
        self.assertIn('Estimated Word lines saved by merges', audit)
        # Request now carries merge_eligible flags and no duplicated bullet list.
        self.assertNotIn('selected_source_bullets', client.request)
        self.assertTrue(all('merge_eligible' in b for e in client.request['source_entries'] for b in e['bullets']))

    def test_entry_missing_from_model_output_falls_back(self):
        def build(req):
            return [{'entry_id': e['entry_id'],
                     'groups': [{'source_ids': [b['bullet_id']], 'text': b['text']} for b in e['bullets']]}
                    for e in req['source_entries'] if not e['entry_title'].startswith('Job Agent')]
        result = cw.generate(_Client(build), self.master, JD, '11651900', self.root / 'out2')
        self.assertEqual(result['entry_fallbacks'], 1)
        txt = '\n'.join(p.text for p in Document(result['docx']).paragraphs)
        self.assertIn('Developed an automated job discovery pipeline', txt)

    def test_prepare_runs_once(self):
        real = cw.prepare
        calls = []
        def counting(*a, **k):
            calls.append(1)
            return real(*a, **k)
        def build(req):
            return [{'entry_id': e['entry_id'],
                     'groups': [{'source_ids': [b['bullet_id']], 'text': b['text']} for b in e['bullets']]}
                    for e in req['source_entries']]
        with mock.patch.object(cw, 'prepare', side_effect=counting):
            cw.generate(_Client(build), self.master, JD, '11651900', self.root / 'out3')
        self.assertEqual(len(calls), 1)


if __name__ == '__main__':
    unittest.main()
