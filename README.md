# AI Job Agent

A local job-search assistant. It reads Handshake job notifications from Gmail, extracts each job description, screens it for fit and eligibility, and drafts a one-page Word resume tailored to the job from your master resume. A Next.js dashboard drives everything through a local Python API.

Nothing is submitted automatically. Every resume is a draft for you to review, and paid OpenAI calls only run after you approve them for a specific job.

## Features

- Gmail API import of Handshake job notification emails (read-only scope)
- Job description extraction with Playwright
- Rule-based screening: match level, OPT/CPT and eligibility flags, location
- Chunk-based resume tailoring: picks the most relevant sections and bullets from your master resume, fills exactly one page, and polishes bullets with one OpenAI call
- Offline preview of the chunk selection, with no API call
- Next.js dashboard: job list, job details, resume preview/download/upload, profile editor, application tracker, schedule
- Local-only API on `127.0.0.1:8765`

## Architecture

```text
frontend/ (Next.js, localhost:3000)
        │  HTTP
        ▼
api_local.py  (127.0.0.1:8765)
        ├─ profile_resume_source.py        profile_data.json → resume input
        ├─ run_full_agent.py               full pipeline
        ├─ run_email_jobs.py               import + read + screen
        │     ├─ handshake_email_import.py ─ gmail_reader.py
        │     ├─ job_reader.py             Playwright JD extraction
        │     └─ job_screen.py             fit / eligibility screening
        └─ run_screened_resumes.py         resume drafts for screened jobs
              ├─ resume_writer.py ─ resume_docx.py      template-based draft
              └─ resume_chunk_writer.py                 chunk-tailored draft
                    ├─ resume_chunks.py     parse master .docx into chunks
                    ├─ resume_selector.py   choose chunks for the JD
                    └─ resume_layout.py     one-page fit and page check
```

## Setup

### 1. Python

```bash
pip install -r requirements.txt
python -m playwright install chromium
```

Optional, for the real page-count check in `resume_layout.py`: Microsoft Word with `pywin32`, or LibreOffice.

### 2. Frontend

```bash
cd frontend
npm install
```

### 3. Private files

Put keys and OAuth files in `secrets/`. That folder is git-ignored.

| File | Purpose |
|---|---|
| `secrets/APIkey.env` | `OPENAI_API_KEY=...` |
| `secrets/credentials.json` | Google OAuth client (Gmail read-only) |
| `secrets/token.json` | Created on first Gmail sign-in |

Personal files in the project root, also git-ignored:

| File | Purpose |
|---|---|
| `Resume_<Name>.docx` | Master resume that chunks are selected from |
| `resume-template.docx` | Word template for template-based drafts |
| `profile_data.json` | Profile edited in the dashboard |
| `profile.txt` | Legacy plain-text profile |

## Run

Start the local API and the dashboard in two terminals:

```bash
python api_local.py
```

```bash
cd frontend
npm run dev
```

Open http://localhost:3000.

### Command line

```bash
python run_full_agent.py                    # import, read, screen
python run_email_jobs.py --screen-only      # re-screen saved JDs only
python run_screened_resumes.py --list       # list screened jobs
python run_screened_resumes.py --job-id JOB_ID --chunk-tailored   # tailored draft (one OpenAI call)
python chunk_v05_preview.py --job-id JOB_ID # offline chunk preview, no API call
```

## Output folders (git-ignored)

| Folder | Contents |
|---|---|
| `jobs/` | Imported links, raw and cleaned JDs, screening report |
| `resumes/` | Generated resume drafts (.docx, .md, selection .json) |
| `chunk_output/` | Offline chunk previews |
| `browser_session/` | Playwright browser profile with your Handshake login |

## Tests

From the project root (PowerShell):

```powershell
$env:PYTHONPATH = "."
Get-ChildItem tests\test_*.py | ForEach-Object { python $_.FullName }
```

## Cloud (not live)

`cloud/` holds an optional Supabase + Google sign-in starter and database schema. It is not wired into the app yet. See [cloud/README_CLOUD_SETUP.md](cloud/README_CLOUD_SETUP.md).

## Security

- `api_local.py` binds to `127.0.0.1` only. Never deploy it or expose its port.
- `secrets/`, `browser_session/`, personal profiles, resumes and job data are git-ignored.
- Gmail access uses the `gmail.readonly` scope.

## Old files

Superseded scripts and earlier upgrade notes are kept locally in `oldfolder/`, which is git-ignored.

## Disclaimer

Match levels are heuristic estimates. They are not hiring probabilities or immigration authorization decisions. The system never submits applications.
