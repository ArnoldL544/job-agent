
# AI Job Agent

An AI-powered job discovery, screening, and resume generation system built with Python.

## Features

- Gmail API integration for Handshake job notifications
- Automated job URL verification
- Job description extraction using Playwright
- Rule-based job matching and eligibility screening
- AI-powered resume customization using OpenAI
- Word resume generation with python-docx
- Interactive Streamlit dashboard
- Duplicate detection and processing history
- Human review before any application

## Tech Stack

- **Language:** Python
- **Frontend:** Streamlit
- **Browser Automation:** Playwright
- **Email Integration:** Gmail API, OAuth 2.0
- **AI Model:** OpenAI GPT-5.4-mini
- **Web Parsing:** BeautifulSoup
- **Document Generation:** python-docx

## Architecture

```text
                 Gmail
                   |
                   v
        Handshake Email Import
                   |
                   v
         Job URL Verification
                   |
                   v
       Job Description Extraction
                   |
                   v
            Job Screening
                   |
                   v
         Resume Generation
          (GPT-5.4-mini)
                   |
                   v
        Word Document (.docx)
                   |
                   v
             Human Review
```

The system uses a modular Python architecture.
Each component handles a specific stage of the job application workflow.

## Installation

Clone the repository and install dependencies:

```bash
pip install -r requirements.txt
```

Install Playwright Chromium:

```bash
python -m playwright install chromium
```

Configure the following local files:

- `credentials.json` - Google OAuth client credentials
- `APIkey.env` - OpenAI API key
- `profile.txt` - Personal experience and project information
- `resume-template.docx` - Word resume template

These files are excluded from version control.

## Run Locally

Start the Streamlit dashboard:

```bash
python -m streamlit run web_app.py --server.address 127.0.0.1
```

Or run the complete pipeline:

```bash
python run_full_agent.py
```

To view screened job opportunities:

```bash
python run_screened_resumes.py --list
```

To generate a resume for a selected job:

```bash
python run_screened_resumes.py --job-id JOB_ID
```

Replace `JOB_ID` with the target Handshake job ID.

## Project Structure

```text
job-agent/
├── web_app.py
├── run_full_agent.py
├── run_email_jobs.py
├── run_screened_resumes.py
├── gmail_reader.py
├── handshake_email_import.py
├── job_reader.py
├── job_screen.py
├── resume_writer.py
├── resume_docx.py
├── resume_editor.py
├── requirements.txt
├── README.md
└── .gitignore
```

## Security

The repository excludes sensitive information, including:

- OpenAI API keys
- Gmail OAuth credentials and tokens
- Browser login sessions
- Personal profiles
- Generated resumes and job data

The application is currently designed for local execution.

## Deployment

Cloud deployment requires additional infrastructure for:

- Secure user authentication
- Persistent data storage
- Browser automation
- OAuth credential management
- Background job processing

## Disclaimer

Job matching scores are heuristic estimates and do not represent hiring probabilities or immigration authorization decisions.

The system does not automatically submit job applications. All generated resumes require human review.
