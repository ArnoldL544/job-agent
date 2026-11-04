import hashlib
import tempfile
import unittest
from pathlib import Path
from docx import Document

from resume_chunks import parse_docx
from resume_selector import detect_skills, parse_jd, score_bullet, select_chunks, render_selected_docx


class ResumeUpgradeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.master_path = Path(self.tmp.name)/'resume.docx'
        d = Document()
        d.add_paragraph('Candidate Name')
        d.add_paragraph('candidate@example.org')
        d.add_paragraph('EDUCATION')
        d.add_paragraph('University of Example\tNY')
        d.add_paragraph('Computer Science\tMay 2029')
        d.add_paragraph('GPA 3.82 out of 4.00', style='List Paragraph')
        d.add_paragraph('EXPERIENCE')
        d.add_paragraph('Data Internship\tNY')
        d.add_paragraph('Data Analyst Intern\tAug 2026 – Oct 2026')
        d.add_paragraph('Processed 7.8 million ratings using Python and Pandas.', style='List Paragraph')
        d.add_paragraph('Benchmarked algorithms using Python.', style='List Paragraph')
        d.add_paragraph('Agent Builder\tRemote')
        d.add_paragraph('Independent Software Developer\t2026 – Present')
        d.add_paragraph('Integrated Python API workflows and Playwright.', style='List Paragraph')
        d.add_paragraph('Developed a JavaScript front-end.', style='List Paragraph')
        d.add_paragraph('HONORS & AWARDS')
        d.add_paragraph('Old Prize\tNY')
        d.add_paragraph('Student Award\t2023')
        d.add_paragraph('Won a student award.', style='List Paragraph')
        d.add_paragraph('SKILLS')
        d.add_paragraph('Languages: C, Python, JavaScript', style='List Paragraph')
        d.save(str(self.master_path))
        self.master = parse_docx(self.master_path)

    def test_extract_nested_entries_and_education(self):
        self.assertEqual(len(self.master['entries']), 3)
        self.assertEqual(self.master['entries'][0]['kind'], 'internship')
        self.assertEqual(self.master['entries'][1]['kind'], 'projects')
        self.assertEqual(len(self.master['entries'][1]['bullets']), 2)
        self.assertEqual(self.master['education'][0]['text'], 'University of Example\tNY')

    def test_same_employer_different_internships_have_unique_ids(self):
        doc = Document(str(self.master_path))
        # Add another date-differentiated internship at the same employer.
        doc.add_paragraph('EXPERIENCE')
        doc.add_paragraph('Data Internship\tNY')
        doc.add_paragraph('Data Analyst Intern\tJun 2027 – Aug 2027')
        doc.add_paragraph('Developed SQL pipelines.', style='List Paragraph')
        doc.save(str(self.master_path))
        parsed = parse_docx(self.master_path)
        same = [e for e in parsed['entries'] if e['title'] == 'Data Internship']
        self.assertEqual(len(same), 2)
        self.assertNotEqual(same[0]['id'], same[1]['id'])

    def test_stable_identifiers(self):
        other = parse_docx(self.master_path)
        self.assertEqual(self.master['entries'][0]['id'], other['entries'][0]['id'])
        self.assertEqual(self.master['entries'][0]['bullets'][0]['id'], other['entries'][0]['bullets'][0]['id'])

    def test_strict_skill_boundaries(self):
        self.assertNotIn('c++', detect_skills('C programming; JavaScript and Next.js'))
        self.assertNotIn('java', detect_skills('JavaScript'))
        self.assertNotIn('c', detect_skills('C++ and C#'))
        self.assertEqual({'c++','c#'}, detect_skills('C++ and C#') & {'c++','c#','c'})
        self.assertNotIn('r', detect_skills('are'))

    def test_required_gap_is_not_a_hallucinated_skill(self):
        jd = 'Required: C++, SQL, Python\nPreferred: JavaScript'
        decision = select_chunks(self.master, jd)
        self.assertIn('c++', decision['required_not_evidenced_in_resume'])
        self.assertIn('sql', decision['required_not_evidenced_in_resume'])
        self.assertNotIn('python', decision['required_not_evidenced_in_resume'])
        all_selected_text = [b['text'] for e in decision['entries'] for b in e['bullets'] if b['selected']]
        source_text = {b['text'] for e in self.master['entries'] for b in e['bullets']}
        self.assertTrue(set(all_selected_text) <= source_text)

    def test_section_heading_parsed_without_leaking_requirement_context(self):
        jd = 'Required Qualifications:\nPython, Git\nPreferred Qualifications:\nJavaScript\nResponsibilities:\nC++ parser'
        self.assertEqual(parse_jd(jd), {
            'required': ['git', 'python'],
            'preferred': ['javascript'],
            'mentioned': ['c++', 'parsing'],
        })

    def test_keep_at_least_one_internship_and_budget(self):
        decision = select_chunks(self.master, 'Required: JavaScript and Python', max_entries=2, max_bullets=2)
        self.assertEqual(len(decision['selected_entry_ids']), 2)
        self.assertEqual(len(decision['selected_bullet_ids']), 2)
        intern_id = self.master['entries'][0]['id']
        self.assertIn(intern_id, decision['selected_entry_ids'])

    def test_preview_preserves_immutable_fields_and_source_bytes(self):
        before = hashlib.sha256(self.master_path.read_bytes()).hexdigest()
        decision = select_chunks(self.master, 'Required: Python, Git, API', max_entries=2, max_bullets=2)
        out = Path(self.tmp.name) / 'preview.docx'
        render_selected_docx(self.master_path, self.master, decision, out)
        after = hashlib.sha256(self.master_path.read_bytes()).hexdigest()
        self.assertEqual(before, after)
        text = '\n'.join(p.text for p in Document(str(out)).paragraphs)
        for literal in ['Candidate Name', 'candidate@example.org', 'University of Example', 'GPA 3.82', 'Languages: C, Python, JavaScript']:
            self.assertIn(literal, text)
        self.assertNotIn('Old Prize', text)
        self.assertNotIn('Won a student award', text)
        self.assertNotIn('HONORS & AWARDS', text)

    def test_reject_modified_master(self):
        dec = select_chunks(self.master, 'Required: Python')
        self.master_path.write_bytes(self.master_path.read_bytes() + b'junk')
        with self.assertRaises(ValueError):
            render_selected_docx(self.master_path, self.master, dec, Path(self.tmp.name)/'out.docx')


if __name__ == '__main__':
    unittest.main()
