"""Strict, privacy-preserving conversion of My Profile JSON into resume input text.

Existing resume generator continues to work with `profile.txt` by default.
Nothing writes to or overwrites legacy profile.txt.
"""
from __future__ import annotations

import json
from pathlib import Path

SECTIONS = (
    ("education", "EDUCATION"), ("projects", "PROJECTS AND ACTIVITIES"),
    ("work", "WORK EXPERIENCE"), ("research", "RESEARCH EXPERIENCE"),
    ("leadership", "LEADERSHIP"),
)

def profile_to_text(payload: object) -> str:
    if not isinstance(payload, dict):
        raise ValueError("My Profile must be a JSON object")
    personal = payload.get("personal", {})
    if not isinstance(personal, dict):
        raise ValueError("Invalid Personal Information")
    lines = ["VERIFIED USER-PROVIDED CAREER PROFILE", "Use only facts supplied below; do not invent achievements, dates, or metrics."]
    fields = [("fullName", "Full name"), ("email", "Email"), ("phone", "Phone"),
              ("location", "Location"), ("linkedin", "LinkedIn"), ("github", "GitHub"), ("website", "Website")]
    for key, label in fields:
        val = personal.get(key, "")
        if isinstance(val, str) and val.strip():
            lines.append(f"{label}: {val.strip()[:500]}")
    substantive = 0
    for key, label in SECTIONS:
        entries = payload.get(key, [])
        if not isinstance(entries, list):
            raise ValueError(f"Invalid {key} section")
        lines.append("\n" + label)
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("Invalid profile entry")
            parts = []
            for fld in (("school", "degree", "major", "gpa", "startDate", "endDate", "courses") if key == "education"
                        else (("title", "organization", "role", "startDate", "endDate", "location", "description")
                              if entry.get("startDate") or entry.get("endDate")
                              else ("title", "organization", "role", "period", "location", "description"))):
                value = entry.get(fld, "")
                if isinstance(value, str) and value.strip():
                    parts.append(f"{fld}: {value.strip()[:10000]}")
            if parts:
                lines.extend(["- " + parts[0]] + ["  " + x for x in parts[1:]])
                substantive += 1
    skills = payload.get("skills", {})
    if not isinstance(skills, dict):
        raise ValueError("Invalid Technical Skills")
    lines.append("\nTECHNICAL SKILLS")
    for key in ("languages", "frameworks", "tools", "other"):
        val = skills.get(key, "")
        if isinstance(val, str) and val.strip():
            lines.append(f"{key}: {val.strip()[:2500]}")
            substantive += 1
    if substantive == 0:
        raise ValueError("My Profile needs at least one education, experience or skill entry before generating a resume")
    return "\n".join(lines)

def read_profile_text(project_root: Path) -> str:
    path = project_root / "profile_data.json"
    if not path.is_file():
        raise ValueError("My Profile is not saved yet. Open My Profile and save your details.")
    if path.stat().st_size > 150000:
        raise ValueError("My Profile file exceeds allowed size")
    return profile_to_text(json.loads(path.read_text(encoding="utf-8-sig")))
