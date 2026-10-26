"""Import verified Handshake single-job links from Gmail.

Requires gmail_reader.py with connect_gmail() and an existing Playwright
persistent profile directory named browser_session/.

First test:
    python handshake_email_import.py --match "Clark Associates"
Then:
    python handshake_email_import.py

This program never applies to jobs, modifies email, or generates resumes.
"""

import argparse
import base64
import json
import re
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr
from pathlib import Path
from urllib.parse import urlsplit

from bs4 import BeautifulSoup
from playwright.sync_api import Error as PlaywrightError
from playwright.sync_api import sync_playwright

from gmail_reader import connect_gmail

ROOT = Path(__file__).resolve().parent
PROFILE_DIR = ROOT / "browser_session"
OUTPUT_FILE = ROOT / "jobs" / "handshake_email_jobs.json"
ALLOWED_SENDERS = {"handshake@notifications.joinhandshake.com"}
TRACKING_HOSTS = {"email.notifications.joinhandshake.com"}
JOB_HOST = "rochester.joinhandshake.com"
JOB_PATH_PATTERN = re.compile(r"^/job-search/(\d+)(?:/|$)")
SINGLE_JOB_SUBJECT = re.compile(r"^New\s+(.+?)\s+at\s+(.+?)\s*$", re.IGNORECASE)
SKIP_LABELS = (
    "unsubscribe", "preferences", "career interests", "privacy policy",
    "terms of", "view more jobs", "contact us", "help center",
    "email settings", "notifications", "manage email",
)


def normalized(value):
    return " ".join(value.casefold().split())


def safe_candidate(url):
    """Only follow known Handshake job links and click-tracking links."""
    try:
        parsed = urlsplit(url)
    except ValueError:
        return False
    if parsed.scheme != "https" or parsed.username or parsed.password:
        return False
    hostname = (parsed.hostname or "").lower()
    if hostname in TRACKING_HOSTS:
        return parsed.path.startswith("/c/")
    if hostname == JOB_HOST:
        return bool(JOB_PATH_PATTERN.match(parsed.path))
    return False


def candidates_from_html(html):
    """Rank plausible job anchors; never follow unsubscribe/settings links."""
    soup = BeautifulSoup(html, "html.parser")
    ranked = []
    seen = set()

    for order, anchor in enumerate(soup.find_all("a", href=True)):
        url = anchor.get("href", "").strip()
        if url in seen or not safe_candidate(url):
            continue
        seen.add(url)

        text = anchor.get_text(" ", strip=True)
        image_alts = " ".join(img.get("alt", "") for img in anchor.find_all("img"))
        label = normalized(" ".join([text, image_alts, anchor.get("title", "")]))
        if any(block in label for block in SKIP_LABELS):
            continue

        if JOB_PATH_PATTERN.match(urlsplit(url).path):
            score = 0
        elif "view job" in label or "view role" in label:
            score = 1
        elif "a new role" in label:
            score = 2
        elif not label:
            score = 3  # HTML emails often wrap job images in unlabeled links.
        else:
            score = 4
        ranked.append((score, order, url, label))

    return [(url, label) for _, _, url, label in sorted(ranked)]


def fetch_single_job_messages(service, max_emails, match_text):
    """Retrieve only notifications with a recognizable single-job subject."""
    result = service.users().messages().list(
        userId="me",
        q="from:handshake@notifications.joinhandshake.com",
        maxResults=max_emails,
    ).execute()

    for entry in result.get("messages", []):
        result = service.users().messages().get(
            userId="me", id=entry["id"], format="raw"
        ).execute()
        raw_email = base64.urlsafe_b64decode(result["raw"])
        mail = BytesParser(policy=policy.default).parsebytes(raw_email)

        sender = parseaddr(str(mail.get("From", "")))[1].lower()
        if sender not in ALLOWED_SENDERS:
            continue

        subject = str(mail.get("Subject", ""))
        if match_text and normalized(match_text) not in normalized(subject):
            continue
        match = SINGLE_JOB_SUBJECT.match(subject)
        if not match:
            continue  # Digests contain several jobs; handle in a later phase.

        html_part = mail.get_body(preferencelist=("html",))
        if html_part is None:
            continue
        html = html_part.get_content()
        yield {
            "message_id": entry["id"],
            "subject": subject,
            "title": match.group(1).strip(),
            "company": match.group(2).strip(),
            "candidates": candidates_from_html(html),
        }


def verify_job_page(page, title, company):
    """Return (id, canonical_url) only for a matching Handshake job page."""
    parsed = urlsplit(page.url)
    if (parsed.hostname or "").lower() != JOB_HOST:
        return None
    job_match = JOB_PATH_PATTERN.match(parsed.path)
    if not job_match:
        return None

    try:
        # Wait until the actual target job heading is client-rendered.
        page.locator("h1, h2").filter(has_text=title).first.wait_for(timeout=12000)
        heading_texts = page.locator("h1, h2").all_text_contents()
        body_text = page.locator("body").inner_text(timeout=8000)
    except PlaywrightError:
        return None

    target = normalized(title)
    heading_match = any(
        normalized(heading) == target or target in normalized(heading)
        for heading in heading_texts
    )
    company_match = normalized(company) in normalized(body_text)
    if not (heading_match and company_match):
        return None

    job_id = job_match.group(1)
    return job_id, f"https://{JOB_HOST}/job-search/{job_id}"


def load_existing():
    if not OUTPUT_FILE.exists():
        return []
    try:
        data = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        raise RuntimeError(f"Cannot safely read {OUTPUT_FILE}: {exc}") from exc
    if not isinstance(data, list):
        raise RuntimeError(f"Expected a list in {OUTPUT_FILE}; nothing was overwritten")
    return data


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--match", default="", help="Only emails whose subjects contain this text")
    parser.add_argument("--max-emails", type=int, default=20)
    parser.add_argument("--max-links", type=int, default=10)
    args = parser.parse_args()
    if args.max_emails < 1 or args.max_links < 1:
        parser.error("--max-emails and --max-links must be positive")

    emails = list(fetch_single_job_messages(connect_gmail(), args.max_emails, args.match))
    print(f"Single-job messages to check: {len(emails)}")
    if not emails:
        print("No matching individual job notification emails found.")
        return

    records = load_existing()
    known_ids = {str(row.get("job_id")) for row in records if isinstance(row, dict)}
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        # Reuse the same persistent browser profile as the existing job_reader.py.
        # Close other Playwright browser windows using this profile first.
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            headless=False,
            no_viewport=True,
        )
        try:
            page = context.new_page()
            page.set_default_navigation_timeout(35000)

            for email in emails:
                print(f"\nEmail: {email['subject']}")
                if not email["candidates"]:
                    print("  No plausible links in email HTML.")
                    continue

                matched = False
                for idx, (url, label) in enumerate(email["candidates"][:args.max_links], 1):
                    print(f"  Checking candidate {idx} ({label[:35] or 'unlabeled link'})...")
                    try:
                        page.goto(url, wait_until="domcontentloaded", timeout=35000)
                        # Some redirects are handled by the Handshake frontend.
                        try:
                            page.wait_for_url(re.compile(r".*/job-search/\d+.*"), timeout=2500)
                        except PlaywrightError:
                            pass
                        verified = verify_job_page(page, email["title"], email["company"])
                    except PlaywrightError as exc:
                        print(f"    Browser navigation failed: {type(exc).__name__}")
                        continue

                    if verified is None:
                        continue
                    job_id, canonical_url = verified
                    print(f"  VERIFIED: {email['company']} - {email['title']}")
                    print(f"  URL: {canonical_url}")
                    matched = True
                    if job_id not in known_ids:
                        records.append({
                            "job_id": job_id,
                            "company": email["company"],
                            "title": email["title"],
                            "url": canonical_url,
                            "gmail_message_id": email["message_id"],
                            "email_subject": email["subject"],
                        })
                        OUTPUT_FILE.write_text(
                            json.dumps(records, indent=2, ensure_ascii=False),
                            encoding="utf-8",
                        )
                        known_ids.add(job_id)
                        print(f"  Saved to {OUTPUT_FILE.name}")
                    else:
                        print("  Already recorded; skipped duplicate.")
                    break
                if not matched:
                    print("  UNVERIFIED: no exact matching job page. Nothing was saved.")

            page.close()
        finally:
            context.close()

    print(f"\nFinished. Verified jobs in database: {len(known_ids)}")
    print(f"Output: {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
