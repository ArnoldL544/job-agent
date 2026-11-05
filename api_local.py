"""Local-only Job Agent API: read jobs/drafts and explicitly approved pipeline actions.

Keep this process on 127.0.0.1. NEVER deploy it to Vercel or expose its port.
POST requires exact local Origin, JSON content type and non-simple header.
Profile editing writes profile_data.json locally; Google sign-in is NOT implemented.
No automatic job application; paid OpenAI draft requires separate explicit approval.
"""
from __future__ import annotations

import json
import os
import tempfile
import io
import shutil
import re
import secrets
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone, date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, urlsplit

ROOT = Path(__file__).resolve().parent
JOBS = ROOT / "jobs"
RESUMES = ROOT / "resumes"
SOURCES = [JOBS / "handshake_email_jobs.json", JOBS / "job_screen_results.json"]
RESUME_STATE = JOBS / "resume_draft_state.json"
HOST, PORT = "127.0.0.1", 8765
ALLOWED_ORIGINS = {"http://localhost:3000", "http://127.0.0.1:3000", "http://localhost:3001", "http://127.0.0.1:3001"}
COLORS = ("mint", "blue", "purple", "orange", "pink")
JOB_ID = re.compile(r"^[0-9]{1,18}$")
MAX_JD_BYTES = 700_000
MAX_PREVIEW_BYTES = 180_000
MAX_DOCX_BYTES = 15_000_000
MAX_PROFILE_BYTES = 150_000
PROFILE_FILE = "profile_data.json"
TRACKER_FILE = ROOT / "application_tracker.json"
SCHEDULE_FILE = ROOT / "discovery_schedule.json"
HISTORY_FILE = ROOT / "task_history.json"
STORE_LOCK = threading.RLock()
STATUS_OPTIONS = {"Discovered", "Saved", "Applied", "Interview", "Offer", "Rejected", "Withdrawn"}
PERSONAL_FIELDS = ("fullName", "email", "phone", "location", "linkedin", "github", "website")
EDUCATION_FIELDS = ("id", "school", "degree", "major", "gpa", "startDate", "endDate", "courses")
EXPERIENCE_FIELDS = ("id", "title", "organization", "role", "period", "startDate", "endDate", "location", "description")
SKILL_FIELDS = ("languages", "frameworks", "tools", "other")
EXPERIENCE_GROUPS = ("projects", "work", "research", "leadership")
MAX_PROFILE_ENTRIES = 30


def blank_profile() -> dict:
    return {"personal": {key: "" for key in PERSONAL_FIELDS},
            "education": [], **{key: [] for key in EXPERIENCE_GROUPS},
            "skills": {key: "" for key in SKILL_FIELDS}}


def validate_profile(value: object) -> dict:
    """Apply exact field allowlists; never store arbitrary user-submitted keys."""
    if not isinstance(value, dict):
        raise ValueError("Profile must be an object")
    result = blank_profile()

    def cleaned(record: object, fields: tuple[str, ...]) -> dict:
        if not isinstance(record, dict):
            raise ValueError("Profile entry must be an object")
        output = {}
        for key in fields:
            text = record.get(key, "")
            if not isinstance(text, str):
                raise ValueError(f"Invalid value for {key}")
            limit = 10000 if key in {"description", "courses"} else 2500 if key in SKILL_FIELDS else 500
            if len(text) > limit or "\x00" in text:
                raise ValueError(f"Value too long or invalid: {key}")
            output[key] = text
        return output

    result["personal"] = cleaned(value.get("personal", {}), PERSONAL_FIELDS)
    result["skills"] = cleaned(value.get("skills", {}), SKILL_FIELDS)
    for group in ("education", *EXPERIENCE_GROUPS):
        records = value.get(group, [])
        if not isinstance(records, list) or len(records) > MAX_PROFILE_ENTRIES:
            raise ValueError(f"Too many entries in {group}")
        fields = EDUCATION_FIELDS if group == "education" else EXPERIENCE_FIELDS
        items = [cleaned(record, fields) for record in records]
        for record in items:
            if not re.fullmatch(r"[A-Za-z0-9_-]{1,90}", record["id"]):
                raise ValueError("Invalid profile entry ID")
        ids = [record["id"] for record in items]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate profile entry ID")
        result[group] = items
    return result


def get_profile() -> dict:
    path = ROOT / PROFILE_FILE
    if not path.is_file():
        return blank_profile()
    try:
        if path.stat().st_size > MAX_PROFILE_BYTES:
            return blank_profile()
        return validate_profile(read_json(path, {}))
    except (OSError, ValueError):
        return blank_profile()


def save_profile(profile: dict) -> None:
    """Atomic local-only update; do not touch legacy profile.txt or user resumes."""
    target = ROOT / PROFILE_FILE
    data = (json.dumps(profile, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    if len(data) > MAX_PROFILE_BYTES:
        raise ValueError("Profile is too large")
    fd, tmp_name = tempfile.mkstemp(prefix=".profile_data_", suffix=".tmp", dir=str(ROOT))
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(tmp_name, target)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)




def atomic_json(path: Path, data: dict | list) -> None:
    """Atomic local write of private JSON. Existing backups are not deleted."""
    encoded = (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    fd, temporary = tempfile.mkstemp(prefix=f".{path.stem}_", suffix=".tmp", dir=str(ROOT))
    try:
        if os.name != "nt":
            os.fchmod(fd, 0o600)
        with os.fdopen(fd, "wb") as writer:
            writer.write(encoded)
            writer.flush()
            os.fsync(writer.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.isfile(temporary):
            os.unlink(temporary)


def read_tracker() -> dict:
    raw = read_json(TRACKER_FILE, {})
    if not isinstance(raw, dict):
        return {}
    return {jid: item for jid, item in raw.items()
            if JOB_ID.fullmatch(jid) and isinstance(item, dict)}


def update_tracker(payload: dict) -> dict:
    jid = payload.get("jobId")
    if not isinstance(jid, str) or not JOB_ID.fullmatch(jid) or jid not in merged_jobs():
        raise ValueError("Unknown job ID")
    with STORE_LOCK:
        values = read_tracker()
        old = values.get(jid, {})
        status = payload.get("status", old.get("status", "Discovered"))
        if status not in STATUS_OPTIONS:
            raise ValueError("Unknown application status")
        deadline = payload.get("deadline", old.get("deadline", ""))
        note = payload.get("note", old.get("note", ""))
        saved = payload.get("saved", old.get("saved", False))
        if (not isinstance(deadline, str) or len(deadline) > 10 or
                not isinstance(note, str) or len(note) > 4000 or type(saved) is not bool):
            raise ValueError("Invalid application metadata")
        if deadline:
            try:
                if date.fromisoformat(deadline).isoformat() != deadline:
                    raise ValueError("Deadline must be YYYY-MM-DD")
            except ValueError as exc:
                raise ValueError("Deadline must be YYYY-MM-DD") from exc
        values[jid] = {"jobId": jid, "status": status, "deadline": deadline,
                       "note": note, "saved": saved,
                       "updatedAt": datetime.now(timezone.utc).isoformat()}
        atomic_json(TRACKER_FILE, values)
        return values[jid]


def public_schedule() -> dict:
    raw = read_json(SCHEDULE_FILE, {})
    if not isinstance(raw, dict):
        raw = {}
    return {"enabled": raw.get("enabled") is True,
            "frequency": raw.get("frequency") if raw.get("frequency") in {"daily", "weekly"} else "weekly",
            "hour": raw.get("hour") if isinstance(raw.get("hour"), int) else 9,
            "minute": raw.get("minute") if isinstance(raw.get("minute"), int) else 0,
            "weekday": raw.get("weekday") if isinstance(raw.get("weekday"), int) else 0,
            "maxEmails": raw.get("maxEmails") if isinstance(raw.get("maxEmails"), int) else 20,
            "lastRunDate": str(raw.get("lastRunDate", "")),
            "lastError": str(raw.get("lastError", ""))[:400]}


def configure_schedule(payload: dict) -> dict:
    enabled = payload.get("enabled")
    frequency = payload.get("frequency", "weekly")
    hour = payload.get("hour", 9)
    minute = payload.get("minute", 0)
    weekday = payload.get("weekday", 0)
    emails = payload.get("maxEmails", 20)
    if type(enabled) is not bool or frequency not in {"daily", "weekly"} or not all(type(x) is int for x in (hour, minute, weekday, emails)):
        raise ValueError("Invalid scheduling options")
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= weekday <= 6 and 1 <= emails <= 50):
        raise ValueError("Schedule values outside permitted range")
    if enabled and payload.get("confirmRead") is not True:
        raise ValueError("Explicit approval to read Gmail on a recurring schedule is required")
    with STORE_LOCK:
        old = public_schedule()
        # Enabling after today's scheduled wall-clock time starts at the NEXT occurrence;
        # it must not silently read Gmail immediately on Save.
        now = datetime.now().astimezone()
        last_date = old["lastRunDate"]
        if enabled and not old["enabled"] and (now.hour, now.minute) >= (hour, minute) and (frequency == "daily" or now.weekday() == weekday):
            last_date = now.date().isoformat()
        new = {"enabled": enabled, "frequency": frequency, "hour": hour,
               "minute": minute, "weekday": weekday, "maxEmails": emails,
               "lastRunDate": last_date, "lastError": ""}
        atomic_json(SCHEDULE_FILE, new)
        return public_schedule()


def schedule_loop() -> None:
    """Best-effort local scheduler; active only while api_local.py stays running."""
    while True:
        try:
            with STORE_LOCK:
                schedule = public_schedule()
                now = datetime.now().astimezone()
                eligible = (schedule["enabled"] and (schedule["frequency"] == "daily" or now.weekday() == schedule["weekday"])
                            and (now.hour, now.minute) >= (schedule["hour"], schedule["minute"])
                            and schedule["lastRunDate"] != now.date().isoformat())
                if eligible:
                    # Mark the date before running, to prevent duplicate jobs across polls.
                    schedule["lastRunDate"] = now.date().isoformat()
                    atomic_json(SCHEDULE_FILE, schedule)
            if eligible:
                result, status = start_task({"action": "import", "maxEmails": schedule["maxEmails"], "confirmRead": True})
                if status != 202:
                    with STORE_LOCK:
                        schedule["lastRunDate"] = ""  # Retry after competing task finishes
                        schedule["lastError"] = str(result.get("error", "Task unavailable"))[:400]
                        atomic_json(SCHEDULE_FILE, schedule)
        except Exception as exc:
            print(f"Local schedule warning: {type(exc).__name__}")
        time.sleep(60)


def import_word_draft(jid: str, body: bytes) -> dict:
    """Safe user-uploaded Word version, without interpreting it as script or HTML."""
    if not JOB_ID.fullmatch(jid) or jid not in merged_jobs():
        raise ValueError("Unknown job ID")
    if len(body) < 100 or len(body) > MAX_DOCX_BYTES or not body.startswith(b"PK"):
        raise ValueError("The uploaded Word file is invalid or too large")
    from docx import Document
    from zipfile import ZipFile, BadZipFile
    try:
        with ZipFile(io.BytesIO(body)) as archive:
            members = archive.infolist()
            if len(members) > 250 or sum(item.file_size for item in members) > 32_000_000:
                raise ValueError("DOCX archive exceeds safe extraction limits")
            if "word/document.xml" not in archive.namelist():
                raise ValueError("Not a DOCX document")
        document = Document(io.BytesIO(body))
        if not any(p.text.strip() for p in document.paragraphs):
            raise ValueError("The Word file has no paragraphs to review")
    except Exception as exc:
        raise ValueError("The uploaded document is not a readable .docx") from exc
    RESUMES.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S_%f")
    destination = RESUMES / f"{jid}_manual_{stamp}_resume_draft.docx"
    fd, tmp_name = tempfile.mkstemp(prefix=".word_upload_", suffix=".tmp", dir=str(RESUMES))
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(body)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_name, destination)
    finally:
        if os.path.isfile(tmp_name):
            os.unlink(tmp_name)
    return {"jobId": jid, "filename": destination.name, "saved": True}


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeError):
        return default


def read_records(path: Path) -> list[dict]:
    records = read_json(path, [])
    return [r for r in records if isinstance(r, dict)] if isinstance(records, list) else []


def merged_jobs() -> dict[str, dict]:
    merged: dict[str, dict] = {}
    for source in SOURCES:
        for row in read_records(source):
            jid = str(row.get("job_id") or "").strip()
            if JOB_ID.fullmatch(jid):
                merged[jid] = {**merged.get(jid, {}), **row, "job_id": jid}
    return merged


def jd_path(row: dict) -> Path | None:
    """Only permit description files inside our private jobs folder for this job ID."""
    jid = str(row["job_id"])
    candidates: list[Path] = []
    stored = row.get("jd_file") or row.get("description_path")
    if isinstance(stored, str) and stored.strip():
        candidates.append(ROOT / stored)
    if JOBS.is_dir():
        candidates.extend(sorted(JOBS.glob(f"{jid}_*_description.txt"), key=lambda p: p.stat().st_mtime, reverse=True))
    for candidate in candidates:
        resolved = candidate.resolve()
        if (resolved.is_relative_to(JOBS.resolve()) and resolved.is_file()
                and resolved.name.startswith(jid + "_") and resolved.name.endswith("_description.txt")):
            return resolved
    return None


# Profile-based drafts and chunk-editor drafts (tailored from the master resume).
DRAFT_SUFFIXES = ("_resume_draft.docx", "_chunk_tailored.docx")


def master_resume() -> Path | None:
    """Newest Resume_<Name>.docx in the project root: the chunk editor's source."""
    files = [p for p in ROOT.glob("Resume_*.docx") if p.is_file()]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def resumes_for(jid: str) -> list[Path]:
    """Match generated Word drafts by numeric ID, never by user-supplied filename."""
    if not JOB_ID.fullmatch(jid):
        return []
    found: list[Path] = []
    if RESUMES.is_dir():
        for suffix in DRAFT_SUFFIXES:
            found.extend(RESUMES.glob(f"{jid}_*{suffix}"))
    state = read_json(RESUME_STATE, {})
    entry = state.get(jid) if isinstance(state, dict) else None
    if isinstance(entry, dict) and isinstance(entry.get("docx"), str):
        found.append(ROOT / entry["docx"])
    safe: dict[str, Path] = {}
    for candidate in found:
        p = candidate.resolve()
        if (p.is_relative_to(RESUMES.resolve()) and p.is_file()
                and p.name.startswith(jid + "_") and p.name.endswith(DRAFT_SUFFIXES)):
            safe[str(p)] = p
    return sorted(safe.values(), key=lambda p: p.stat().st_mtime, reverse=True)


_GLANCE_END = re.compile(r"^(What they.re looking for|Job description)", re.I)
_MONTH_DATE = r"([A-Z][a-z]+) \d{1,2}, (\d{4})"
# Flags that appear on almost every job; they are not useful as a badge reason.
_GENERIC_FLAGS = ("UR ISO", "截止不足或等于 7 天")
_REASON_KEYS = ("冲突", "毕业", "截止日期已过", "地点", "境外", "签证")


def jd_facts(text: str) -> dict:
    """Key facts from a Handshake JD's header and "At a glance" block.

    Handshake renders the block as one fact per line, e.g. "£28K/yr",
    "Hybrid, based in Cambridge, United Kingdom", "Full-time∙From July 4, 2027
    to June 30, 2028", "US work authorization required". Missing lines are skipped.
    """
    facts: dict = {}
    applied = re.search(r"Apply by ([A-Z][a-z]+ \d{1,2}, \d{4})", text)
    if applied:
        try:
            facts["deadline"] = datetime.strptime(applied.group(1), "%B %d, %Y").date().isoformat()
        except ValueError:
            pass
    lines = [line.strip() for line in text.splitlines()]
    if "At a glance" not in lines:
        return facts
    start = lines.index("At a glance") + 1
    for line in lines[start:start + 15]:
        if _GLANCE_END.match(line):
            break
        if not line:
            continue
        if "pay" not in facts and re.match(r"^([$£€¥]|Paid$|Unpaid)", line):
            facts["pay"] = line[:60]
        where = re.match(r"^(Remote or onsite|Remote|Onsite|Hybrid), based in (.+)$", line)
        if where:
            facts["workplace"], facts["location"] = where.group(1), where.group(2)[:120]
        schedule = re.match(r"^(Full-time|Part-time)", line)
        if schedule:
            period = re.search(r"From " + _MONTH_DATE + r" to " + _MONTH_DATE, line)
            facts["schedule"] = schedule.group(1) + (
                f" · {period.group(1)[:3]} {period.group(2)} – {period.group(3)[:3]} {period.group(4)}" if period else "")
        auth = re.match(r"^US work authorization (not required|required|requirements unknown)", line)
        if auth:
            facts["usAuth"] = {"not required": "not required", "required": "required"}.get(auth.group(1), "unknown")
        if line.startswith("Eligible for visa sponsorship"):
            facts["sponsorship"] = True
        if "OPT/CPT" in line:
            facts["optCpt"] = True
    return facts


def job_url(row: dict, jd_text: str = "") -> str:
    """The posting's https link (from screening, else the JD's 来源 line); never other schemes."""
    candidates = [row.get("url")]
    source = re.search(r"来源：\s*(\S+)", jd_text[:500])
    if source:
        candidates.append(source.group(1))
    for value in candidates:
        if isinstance(value, str):
            parts = urlsplit(value.strip())
            if parts.scheme == "https" and parts.netloc and len(value) <= 500:
                return value.strip()
    return ""


def work_auth_label(facts: dict) -> str:
    auth = facts.get("usAuth")
    if auth == "not required":
        return "US work authorization not required"
    if auth == "required":
        extra = " · sponsors visas" if facts.get("sponsorship") else " · OPT/CPT OK" if facts.get("optCpt") else ""
        return "US work authorization required" + extra
    return "Work authorization not stated" if auth == "unknown" else ""


def normalize(row: dict) -> dict:
    jid = str(row["job_id"])
    company = str(row.get("company") or "Unknown company").strip()
    raw_score = row.get("match_score")
    score = max(0, min(100, int(raw_score))) if isinstance(raw_score, (int, float)) and not isinstance(raw_score, bool) else 0
    priority = str(row.get("priority") or "")
    match = ("High Match" if priority == "高匹配·优先核实" else
             "Conflict" if "冲突" in priority else
             "Verify Eligibility" if any(term in priority for term in ("地点限制", "待核实", "暂缓")) else "Review")
    skills = row.get("matched_skills", [])
    keywords = row.get("jd_keywords", [])
    flags = row.get("flags", [])
    flags = [str(v)[:700] for v in flags[:25] if isinstance(v, (str, int, float))] if isinstance(flags, list) else []
    specific = [f for f in flags if not any(g in f for g in _GENERIC_FLAGS)]
    # The badge shows the flag that best explains the priority, most decisive first.
    reason = next((f for key in _REASON_KEYS for f in specific if key in f), specific[0] if specific else "")
    jd = jd_path(row)
    try:
        jd_text = jd.read_text(encoding="utf-8-sig", errors="replace")[:60000] if jd else ""
    except OSError:
        jd_text = ""
    facts = jd_facts(jd_text)
    deadline = str(row.get("deadline") or facts.get("deadline") or "")[:10]
    try:
        deadline_days = (date.fromisoformat(deadline) - date.today()).days if deadline else None
    except ValueError:
        deadline, deadline_days = "", None
    return {
        "id": jid, "company": company[:180], "title": str(row.get("title") or "Untitled position")[:200],
        "location": facts.get("location", "Location not verified"),
        "arrangement": facts.get("workplace", "Verify job details"), "score": score,
        "pay": facts.get("pay", ""), "schedule": facts.get("schedule", ""), "workAuth": work_auth_label(facts),
        "url": job_url(row, jd_text),
        "deadline": deadline, "deadlineDays": deadline_days, "reason": reason[:300] if match != "High Match" else "",
        "match": match, "priority": priority[:150],
        "initials": "".join(s[0] for s in company.split()[:2]).upper() or "?",
        "color": COLORS[sum(ord(ch) for ch in company) % len(COLORS)],
        "skills": [str(v)[:70] for v in skills[:12]] if isinstance(skills, list) else [],
        "summary": str(row.get("recommended_action") or "Review the saved JD before applying.")[:900],
        "requirements": [str(v)[:120] for v in keywords[:20]] if isinstance(keywords, list) and keywords else ["See saved job description"],
        "flags": flags or ["Work authorization and location require independent verification"],
        "hasJd": jd_path(row) is not None, "resumeCount": len(resumes_for(jid)),
    }


def job_summaries() -> list[dict]:
    result = [normalize(row) for row in merged_jobs().values()]
    result.sort(key=lambda r: (-r["score"], r["company"].casefold()))
    return result


def safe_read_text(path: Path, limit: int) -> str:
    if path.stat().st_size > limit:
        return f"This document is larger than the preview limit ({limit:,} bytes). Open it locally to review."
    return path.read_text(encoding="utf-8-sig", errors="replace")


def download_name(title: object) -> str:
    """'<Job title>_resume.docx' with characters Windows forbids in file names removed.

    Files on disk keep their unique '<job id>_<timestamp>_...' names; only the
    downloaded copy is named after the job.
    """
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", str(title or ""))
    clean = re.sub(r"\s+", " ", clean).strip(" .")[:100].strip(" .")
    return f"{clean or 'Job'}_resume.docx"


def draft_kind(path: Path) -> str:
    if path.name.endswith("_chunk_tailored.docx"):
        return "tailored"
    return "uploaded" if "_manual_" in path.name else "profile"


def draft_summary(docx: Path) -> dict | None:
    """Readable review data for a chunk-tailored draft (from its selection JSON).

    Returns None for other drafts; the raw text preview is still available.
    """
    selection = docx.with_suffix(".selection.json")
    if not selection.is_file() or selection.stat().st_size > 2_000_000:
        return None
    try:
        data = json.loads(selection.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    source = {str(b.get("id")): str(b.get("text", ""))
              for e in data.get("entries", []) if isinstance(e, dict)
              for b in e.get("bullets", []) if isinstance(b, dict)}
    titles = {str(e.get("id")): str(e.get("title", "")) for e in data.get("entries", []) if isinstance(e, dict)}
    writer = data.get("writer_v06") if isinstance(data.get("writer_v06"), dict) else {}
    changes = []
    for row in data.get("composition_v04", []):
        if not isinstance(row, dict) or row.get("status") not in ("rewritten", "merged"):
            continue
        changes.append({"section": titles.get(str(row.get("entry_id")), "")[:160],
                        "kind": row["status"],
                        "before": [source.get(str(b), "")[:600] for b in row.get("source_ids", [])][:2],
                        "after": str(row.get("text", ""))[:900]})
    questions = [{"question": str(q.get("question", ""))[:300], "bullet": source.get(str(q.get("bullet_id")), "")[:600]}
                 for q in writer.get("fact_questions", []) if isinstance(q, dict)][:5]
    page = data.get("page_fit_v05") if isinstance(data.get("page_fit_v05"), dict) else {}
    check = page.get("render_check") if isinstance(page.get("render_check"), dict) else {}
    return {"model": str(writer.get("model", ""))[:60],
            "focus": [str(x)[:160] for x in writer.get("jd_focus", [])][:5],
            "questions": questions,
            "changes": changes[:20],
            "skills": [str(v)[:300] for v in (writer.get("skills_reordered") or {}).values()][:6],
            "bulletCount": len(data.get("selected_bullet_ids", [])),
            "pageCount": check.get("pages")}


# os.startfile exists on Windows only; tests replace this seam.
OPEN_FILE = getattr(os, "startfile", None)


def master_overview() -> dict:
    """The master resume as the chunk editor sees it, plus open fact questions.

    Questions come from every chunk draft's review data. A question stays open
    while its bullet is unchanged in the master (bullet IDs hash the text), so
    editing that bullet in Word closes it.
    """
    master = master_resume()
    if master is None:
        return {"found": False}
    try:
        from resume_chunks import parse_docx
        parsed = parse_docx(master)
    except Exception as exc:  # parser errors are shown to the user, never fatal
        return {"found": True, "filename": master.name, "error": f"Could not read the master resume: {exc}"[:300]}
    bullets = {b["id"]: (e, b) for e in parsed["entries"] for b in e["bullets"]}
    titles = {jid: str(row.get("title") or "") for jid, row in merged_jobs().items()}
    companies = {jid: str(row.get("company") or "") for jid, row in merged_jobs().items()}
    open_q: dict[str, dict] = {}
    resolved = 0
    for path in sorted(RESUMES.glob("*_chunk_tailored.selection.json"), key=lambda p: p.stat().st_mtime) if RESUMES.is_dir() else []:
        if path.stat().st_size > 2_000_000:
            continue
        try:
            writer = json.loads(path.read_text(encoding="utf-8")).get("writer_v06") or {}
        except (OSError, ValueError, AttributeError):
            continue
        jid = path.name.split("_", 1)[0]
        for q in writer.get("fact_questions", []) if isinstance(writer, dict) else []:
            if not isinstance(q, dict) or not isinstance(q.get("question"), str):
                continue
            bid = str(q.get("bullet_id"))
            if bid not in bullets:
                resolved += 1
                continue
            entry, bullet = bullets[bid]
            item = open_q.setdefault(bid, {"bulletId": bid, "bullet": bullet["text"][:600], "section": entry["title"][:160], "questions": []})
            text = q["question"].strip()[:300]
            job = f"{companies.get(jid, '')} — {titles.get(jid, '')}".strip(" —")
            existing = next((x for x in item["questions"] if x["question"].casefold() == text.casefold()), None)
            if existing is None:
                item["questions"].append({"question": text, "jobs": [job] if job else []})
            elif job and job not in existing["jobs"]:
                existing["jobs"].append(job)
    return {
        "found": True, "filename": master.name,
        "updatedAt": datetime.fromtimestamp(master.stat().st_mtime, tz=timezone.utc).isoformat(),
        "header": [h["text"][:200] for h in parsed["header"]][:6],
        "education": [e["text"][:300] for e in parsed["education"]][:20],
        "skills": [s["text"][:300] for s in parsed["skills"]][:12],
        "entries": [{"title": e["title"][:160], "role": e.get("role", "")[:160], "dates": e.get("dates", "")[:80],
                     "kind": e.get("kind", ""), "bullets": [b["text"][:600] for b in e["bullets"]][:12]}
                    for e in parsed["entries"]][:30],
        "warnings": [str(w)[:200] for w in parsed.get("warnings", [])][:10],
        "openQuestions": list(open_q.values())[:30],
        "resolvedQuestions": resolved,
        "canOpen": OPEN_FILE is not None,
    }


def open_master() -> tuple[dict, int]:
    master = master_resume()
    if master is None:
        return {"error": "No Resume_<Name>.docx in the project folder"}, 404
    if OPEN_FILE is None:
        return {"error": "Opening files is only supported on Windows"}, 501
    OPEN_FILE(str(master))
    return {"opened": master.name}, 200


def resume_entries() -> list[dict]:
    rows = merged_jobs()
    entries = []
    for jid, row in rows.items():
        for idx, path in enumerate(resumes_for(jid)):
            md = path.with_suffix(".md")
            entries.append({"id": f"{jid}:{idx}", "jobId": jid, "index": idx,
                            "company": str(row.get("company") or "Unknown company")[:180],
                            "jobTitle": str(row.get("title") or "Untitled position")[:200],
                            "filename": path.name, "updatedAt": datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).isoformat(),
                            "kind": draft_kind(path), "downloadName": download_name(row.get("title")),
                            "hasTextPreview": md.is_file()})
    entries.sort(key=lambda item: item["updatedAt"], reverse=True)
    return entries


# In-memory task state. Reloading this local process clears history; output documents
# produced by the original Agent are still saved by those scripts.
TASK_LOCK = threading.RLock()
TASK: dict | None = None
TASK_ALLOWED = {"screen", "extract", "import", "resume"}
LOG_MAX_LINES = 160


def public_task() -> dict | None:
    with TASK_LOCK:
        if TASK is None:
            return None
        return {key: TASK[key] for key in ("id", "action", "status", "startedAt", "endedAt", "returnCode", "logs")}


def _redact(text: str) -> str:
    # Defense in depth; logs can still contain job/company names and personal details.
    text = re.sub(r"sk-[A-Za-z0-9_-]{12,}", "[REDACTED_KEY]", text)
    text = re.sub(r"(OPENAI_API_KEY|refresh_token|access_token)([\s:=\"']+)([^\s\"']+)", r"\1=REDACTED", text, flags=re.I)
    return text[:2400]


def _run_task(task_id: str, command: list[str]) -> None:
    global TASK
    with TASK_LOCK:
        if TASK is None or TASK["id"] != task_id:
            return
        TASK["status"] = "running"
    process = None
    try:
        env = os.environ.copy()
        env.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        process = subprocess.Popen([sys.executable, "-u", *command], cwd=str(ROOT), env=env,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                   stderr=subprocess.STDOUT, text=True, encoding="utf-8",
                                   errors="replace", bufsize=1)
        assert process.stdout is not None
        for raw in process.stdout:
            with TASK_LOCK:
                if TASK is None or TASK["id"] != task_id:
                    break
                TASK["logs"].append(_redact(raw.rstrip("\r\n")))
                TASK["logs"] = TASK["logs"][-LOG_MAX_LINES:]
        code = process.wait(timeout=15)
        with TASK_LOCK:
            if TASK is not None and TASK["id"] == task_id:
                TASK["returnCode"] = code
                TASK["status"] = "succeeded" if code == 0 else "failed"
    except Exception as exc:
        with TASK_LOCK:
            if TASK is not None and TASK["id"] == task_id:
                TASK["logs"].append(f"Task execution stopped: {type(exc).__name__}: {_redact(str(exc))}")
                TASK["status"] = "failed"
                TASK["returnCode"] = -1
    finally:
        with TASK_LOCK:
            if TASK is not None and TASK["id"] == task_id:
                TASK["endedAt"] = time.time()
                try:
                    with STORE_LOCK:
                        history = read_json(HISTORY_FILE, [])
                        if not isinstance(history, list):
                            history = []
                        history.insert(0, public_task())
                        atomic_json(HISTORY_FILE, history[:30])
                except OSError:
                    pass
        if process and process.stdout:
            process.stdout.close()


def start_task(payload: dict) -> tuple[dict, int]:
    global TASK
    action = payload.get("action")
    if action not in TASK_ALLOWED:
        return {"error": "Unsupported task action"}, 400
    command: list[str]
    if action == "screen":
        command = ["run_email_jobs.py", "--screen-only"]
    elif action == "extract":
        command = ["run_email_jobs.py", "--skip-email"]
    elif action == "import":
        max_emails = payload.get("maxEmails", 20)
        if isinstance(max_emails, bool) or not isinstance(max_emails, int) or not 1 <= max_emails <= 50:
            return {"error": "maxEmails must be an integer from 1 to 50"}, 400
        if payload.get("confirmRead") is not True:
            return {"error": "Explicit Gmail-read approval is required"}, 400
        command = ["run_full_agent.py", "--max-emails", str(max_emails)]
    else:
        jid = payload.get("jobId")
        if not isinstance(jid, str) or not JOB_ID.fullmatch(jid):
            return {"error": "Valid job ID required"}, 400
        if payload.get("confirmPaid") is not True:
            return {"error": "Explicit paid-model approval is required"}, 400
        report = {str(row.get("job_id")): row for row in read_records(JOBS / "job_screen_results.json")}
        row = report.get(jid)
        if not row:
            return {"error": "Job is not in the saved screening report"}, 404
        blocked = str(row.get("priority") or "") not in {"高匹配·优先核实", "中匹配·待核实"}
        if blocked and payload.get("allowRisk") is not True:
            return {"error": "This job needs separate acknowledgement of screening restrictions"}, 409
        command = ["run_screened_resumes.py", "--job-id", jid, "--yes"]
        engine = payload.get("engine", "chunk")
        if engine == "chunk":
            # Tailor from the master resume (chunk editor): selection, JD-aware
            # rewrites and fact questions. My Profile is not used in this mode.
            master = master_resume()
            if master is None:
                return {"error": "Put your master resume in the project folder as Resume_<Name>.docx"}, 409
            command += ["--chunk-tailored", "--master-resume", master.name]
        elif engine != "profile":
            return {"error": "Unknown resume engine"}, 400
        elif payload.get("profileSource", "json") == "json":
            # Do not silently fall back to stale profile.txt.
            from profile_resume_source import read_profile_text
            try:
                read_profile_text(ROOT)
            except (OSError, ValueError) as exc:
                return {"error": str(exc)}, 409
            command += ["--profile-source", "json"]
        elif payload.get("profileSource") != "legacy":
            return {"error": "Unknown profile source"}, 400
        if blocked:
            command.append("--allow-risk")
        if payload.get("force") is True:
            command.append("--force")
    if not (ROOT / command[0]).is_file():
        return {"error": f"Required local script missing: {command[0]}"}, 500
    with TASK_LOCK:
        if TASK is not None and TASK["status"] in {"queued", "running"}:
            return {"error": "Another task is already running. Wait for it to finish."}, 409
        task_id = secrets.token_urlsafe(16)
        TASK = {"id": task_id, "action": action, "status": "queued", "startedAt": time.time(),
                "endedAt": None, "returnCode": None, "logs": []}
        threading.Thread(target=_run_task, args=(task_id, command), daemon=True).start()
        return public_task(), 202


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if not self.valid_host():
            return self.send_json({"error": "Invalid Host"}, 403)
        origin = self.headers.get("Origin")
        if origin and origin not in ALLOWED_ORIGINS:
            self.send_json({"error": "Origin not allowed"}, 403)
            return
        path = urlsplit(self.path).path
        if path == "/api/health":
            return self.send_json({"ok": True, "mode": "local-only", "stage": "product-v1"})
        if path == "/api/profile":
            return self.send_json({"profile": get_profile()})
        if path == "/api/master":
            return self.send_json(master_overview())
        if path == "/api/tracker":
            return self.send_json({"applications": read_tracker()})
        if path == "/api/schedule":
            return self.send_json({"schedule": public_schedule()})
        if path == "/api/tasks/history":
            history = read_json(HISTORY_FILE, [])
            return self.send_json({"history": history if isinstance(history, list) else []})
        if path == "/api/tasks/current":
            return self.send_json({"task": public_task()})
        if path == "/api/jobs":
            jobs = job_summaries()
            return self.send_json({"count": len(jobs), "jobs": jobs})
        if path == "/api/resumes":
            resumes = resume_entries()
            return self.send_json({"count": len(resumes), "resumes": resumes})
        detail = re.fullmatch(r"/api/jobs/([0-9]{1,18})/detail", path)
        if detail:
            jid = detail.group(1)
            row = merged_jobs().get(jid)
            if not row:
                return self.send_json({"error": "Unknown job ID"}, 404)
            jd = jd_path(row)
            return self.send_json({"jobId": jid, "hasJd": jd is not None,
                                   "jdText": safe_read_text(jd, MAX_JD_BYTES) if jd else "",
                                   "jdFilename": jd.name if jd else None,
                                   "priority": str(row.get("priority") or ""),
                                   "screeningNotes": normalize(row)["flags"]})
        document = re.fullmatch(r"/api/resumes/([0-9]{1,18})/([0-9]{1,3})/(preview|download)", path)
        if document:
            jid, index_str, action = document.groups()
            if jid not in merged_jobs():
                return self.send_json({"error": "Unknown job ID"}, 404)
            paths = resumes_for(jid)
            idx = int(index_str)
            if idx >= len(paths):
                return self.send_json({"error": "Resume not found"}, 404)
            docx = paths[idx]
            if action == "download":
                return self.send_docx(docx, download_name(merged_jobs()[jid].get("title")))
            markdown = docx.with_suffix(".md")
            if markdown.is_file():
                preview = safe_read_text(markdown, MAX_PREVIEW_BYTES)
                source = "markdown"
            else:
                # Text-only fallback. This is NOT a faithful Word layout preview.
                try:
                    from docx import Document
                    preview = "\n".join(p.text for p in Document(str(docx)).paragraphs if p.text.strip())[:30000]
                    source = "docx-text"
                except Exception:
                    preview, source = "Text preview unavailable. Download the Word file to review.", "unavailable"
            return self.send_json({"jobId": jid, "filename": docx.name, "source": source, "text": preview,
                                   "summary": draft_summary(docx)})
        return self.send_json({"error": "Not found"}, 404)

    def do_POST(self) -> None:
        # Browser writes require exact local origin and a non-simple header to
        # prevent drive-by CSRF from arbitrary websites. No shell commands accepted.
        origin = self.headers.get("Origin")
        if not self.valid_host() or origin not in ALLOWED_ORIGINS:
            return self.send_json({"error": "Local browser Origin required"}, 403)
        if self.headers.get("X-Job-Agent-Action") != "local-user-approved":
            return self.send_json({"error": "Action header missing"}, 403)
        path = urlsplit(self.path).path
        upload = re.fullmatch(r"/api/resumes/([0-9]{1,18})/upload", path)
        if path not in {"/api/tasks", "/api/profile", "/api/tracker", "/api/schedule", "/api/master/open"} and not upload:
            return self.send_json({"error": "Not found"}, 404)
        if upload:
            if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/vnd.openxmlformats-officedocument.wordprocessingml.document":
                return self.send_json({"error": "Expected .docx content type"}, 415)
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                return self.send_json({"error": "Invalid upload length"}, 400)
            if not 100 <= length <= MAX_DOCX_BYTES:
                return self.send_json({"error": "Word file too large or empty"}, 413)
            try:
                result = import_word_draft(upload.group(1), self.rfile.read(length))
                return self.send_json(result, 201)
            except (ValueError, OSError) as exc:
                return self.send_json({"error": str(exc)}, 400)
        if self.headers.get("Content-Type", "").split(";")[0].strip().lower() != "application/json":
            return self.send_json({"error": "Expected application/json"}, 415)
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return self.send_json({"error": "Invalid content length"}, 400)
        limit = MAX_PROFILE_BYTES if path == "/api/profile" else 8192
        if length < 2 or length > limit:
            return self.send_json({"error": "Payload size rejected"}, 413)
        try:
            payload = json.loads(self.rfile.read(length))
        except (ValueError, UnicodeError):
            return self.send_json({"error": "Invalid JSON"}, 400)
        if not isinstance(payload, dict):
            return self.send_json({"error": "Expected JSON object"}, 400)
        if path == "/api/master/open":
            result, status = open_master()
            return self.send_json(result, status)
        if path == "/api/profile":
            try:
                cleaned = validate_profile(payload.get("profile"))
                save_profile(cleaned)
            except ValueError as error:
                return self.send_json({"error": str(error)}, 400)
            except OSError:
                return self.send_json({"error": "Unable to save local profile"}, 500)
            return self.send_json({"profile": cleaned, "saved": True})
        if path == "/api/tracker":
            try:
                return self.send_json({"application": update_tracker(payload)})
            except (ValueError, OSError) as exc:
                return self.send_json({"error": str(exc)}, 400)
        if path == "/api/schedule":
            try:
                return self.send_json({"schedule": configure_schedule(payload)})
            except (ValueError, OSError) as exc:
                return self.send_json({"error": str(exc)}, 400)
        result, status = start_task(payload)
        return self.send_json(result, status)

    def valid_host(self) -> bool:
        return self.headers.get("Host", "") in {f"localhost:{PORT}", f"127.0.0.1:{PORT}",
                                                      f"localhost:{self.server.server_address[1]}",
                                                      f"127.0.0.1:{self.server.server_address[1]}"}

    def do_OPTIONS(self) -> None:
        if not self.valid_host():
            return self.send_json({"error": "Invalid Host"}, 403)
        origin = self.headers.get("Origin")
        if origin and origin not in ALLOWED_ORIGINS:
            return self.send_json({"error": "Origin not allowed"}, 403)
        self.send_response(204)
        self.common_headers()
        self.end_headers()

    def common_headers(self) -> None:
        origin = self.headers.get("Origin")
        if origin in ALLOWED_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Job-Agent-Action")
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.common_headers()
        self.end_headers()
        self.wfile.write(body)

    def send_docx(self, path: Path, filename: str | None = None) -> None:
        if path.stat().st_size > MAX_DOCX_BYTES:
            return self.send_json({"error": "Word document exceeds download size limit"}, 413)
        data = path.read_bytes()
        name = filename or path.name
        # ASCII fallback for old clients plus the UTF-8 name (RFC 6266 / 5987).
        fallback = re.sub(r"[^A-Za-z0-9 ._()&,+-]", "", name).strip() or "resume.docx"
        self.send_response(200)
        self.send_header("Content-Type", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
        self.send_header("Content-Disposition", f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(name)}")
        self.send_header("Content-Length", str(len(data)))
        self.common_headers()
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt: str, *args: object) -> None:
        # Never log the body of a document or resume.
        print("Local API: " + (fmt % args))


if __name__ == "__main__":
    print(f"Local Job Agent API: http://{HOST}:{PORT}/api/health")
    print("Local-only with explicitly approved tasks; no automatic applications. Ctrl+C stops API.")
    threading.Thread(target=schedule_loop, daemon=True).start()
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
