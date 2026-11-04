"""job_screen: graduation-window conflicts and C++ keyword (offline)."""
import re
import unittest

import job_screen as js

EXP = (2029, 5)


class GraduationTests(unittest.TestCase):
    def conflict(self, text):
        return js.graduation_conflict(text, EXP)

    def test_graduates_by_earlier_date_is_conflict(self):
        reason, quote = self.conflict("What they're looking for\n- Graduates by September 2028")
        self.assertIn('2028年9月', reason)
        self.assertIn('Graduates by September 2028', quote)

    def test_graduating_by_later_date_is_fine(self):
        self.assertIsNone(self.conflict('Candidates graduating by December 2029 are welcome.'))
        self.assertIsNone(self.conflict('Graduates by May 2029'))

    def test_graduation_year_lists_and_ranges(self):
        self.assertIsNotNone(self.conflict('Open to students graduating in 2027 or 2028.'))
        self.assertIsNone(self.conflict('Open to students graduating in 2028 or 2029.'))
        self.assertIsNone(self.conflict('Graduation date between 2027 and 2030.'))
        self.assertIsNotNone(self.conflict('Graduation date between Fall 2026 and Spring 2028.'))

    def test_no_window_or_disabled_profile(self):
        self.assertIsNone(self.conflict('Rising juniors and seniors are encouraged to apply.'))
        self.assertIsNone(js.graduation_conflict('Graduates by September 2028', None))


class SkillRegexTests(unittest.TestCase):
    def test_cpp_matches(self):
        pattern = next(p for p, label, _ in js.SKILLS if label == 'CS fundamentals')
        self.assertTrue(re.search(pattern, 'Experience in C++ and Python', re.I))
        self.assertTrue(re.search(pattern, 'Java required', re.I))
        self.assertFalse(re.search(pattern, 'JavaScript only', re.I))


if __name__ == '__main__':
    unittest.main()
