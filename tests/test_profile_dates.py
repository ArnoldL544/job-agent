"""Offline checks. Import API modules without starting a production server."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class DateFieldsTest(unittest.TestCase):
    def test_preserves_legacy_period_and_new_dates(self):
        api = load_module("api_date_check", ROOT / "api_local.py")
        obj = api.blank_profile()
        for group in ("projects", "work", "research", "leadership"):
            obj[group] = [{"id": f"{group}_01", "title": group,
                           "period": "Fall 2026", "startDate": "08/2026", "endDate": "Present"}]
        result = api.validate_profile(obj)
        for group in ("projects", "work", "research", "leadership"):
            record = result[group][0]
            self.assertEqual(record["period"], "Fall 2026")
            self.assertEqual(record["startDate"], "08/2026")
            self.assertEqual(record["endDate"], "Present")

    def test_old_profiles_still_load(self):
        api = load_module("api_date_check", ROOT / "api_local.py")
        profile = api.blank_profile()
        profile["projects"] = [{"id":"old_01", "title":"Old project", "period":"Summer 2026"}]
        obj = api.validate_profile(profile)
        self.assertEqual(obj["projects"][0]["period"], "Summer 2026")
        self.assertEqual(obj["projects"][0]["startDate"], "")
        self.assertEqual(obj["projects"][0]["endDate"], "")

    def test_resume_uses_new_dates_when_present(self):
        mod = load_module("resume_dates_check", ROOT / "profile_resume_source.py")
        profile = {"personal":{}, "education":[], "projects": [{"title":"Project", "period":"Old Summer", "startDate":"08/2026", "endDate":"10/2026"}], "work":[], "research":[], "leadership":[], "skills":{}}
        text = mod.profile_to_text(profile)
        self.assertIn("startDate: 08/2026", text)
        self.assertIn("endDate: 10/2026", text)
        self.assertNotIn("Old Summer", text)
        profile["projects"][0]["startDate"] = ""
        profile["projects"][0]["endDate"] = ""
        self.assertIn("period: Old Summer", mod.profile_to_text(profile))


if __name__ == "__main__":
    unittest.main()
