"""Read Handshake job descriptions, manually or from verified Gmail job links.

Manual, original behavior:
    python job_reader.py
    python job_reader.py --url "https://rochester.joinhandshake.com/job-search/11627235"

Gmail batch (requires handshake_email_import.py to have produced the JSON):
    python job_reader.py --from-email --dry-run
    python job_reader.py --from-email --match "Clark Associates" --limit 1
    python job_reader.py --from-email

Uses the same browser_session/ as the email importer. Only one process may
use this persistent Playwright profile at a time.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import sync_playwright

VERSION = "jd-reader-2026-10-22-v4"

PROJECT_FOLDER = Path(__file__).resolve().parent
SESSION_FOLDER = PROJECT_FOLDER / "browser_session"
JOBS_FOLDER = PROJECT_FOLDER / "jobs"
EMAIL_JOBS_FILE = JOBS_FOLDER / "handshake_email_jobs.json"
STATE_FILE = JOBS_FOLDER / "handshake_jd_state.json"

# Retain the original single-job default for backwards compatibility.
DEFAULT_URL = (
    "https://app.joinhandshake.com/jobs/11694997"
    "?searchId=a68d55ec-95b8-4f2b-b15b-ddf28f424658S"
)
ALLOWED_HOSTS = {"app.joinhandshake.com", "rochester.joinhandshake.com"}
JOB_PATH = re.compile(r"^/(?:jobs|job-search)/(\d+)(?:/|$)")


def job_id_from_url(url):
    """Accept only Handshake job-detail URLs, not redirects or search pages."""
    parsed = urlsplit(url)
    if parsed.scheme != "https" or parsed.username or parsed.password:
        raise ValueError("The URL must be an HTTPS Handshake job-detail URL")
    if (parsed.hostname or "").lower() not in ALLOWED_HOSTS:
        raise ValueError("The URL host is not an approved Handshake host")
    match = JOB_PATH.match(parsed.path)
    if not match:
        raise ValueError("The URL does not point to an individual Handshake job")
    return match.group(1)


def normalized(text):
    return " ".join(str(text).casefold().split())


def read_json(path, expected_type):
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, expected_type):
        raise ValueError(f"Wrong JSON format in {path}")
    return data


def read_state():
    if not STATE_FILE.exists():
        return {}
    return read_json(STATE_FILE, dict)


def save_state(state):
    """Write progress atomically so interrupted runs do not corrupt state."""
    JOBS_FOLDER.mkdir(parents=True, exist_ok=True)
    temporary = STATE_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(STATE_FILE)


def get_email_jobs(match_text=""):
    """Load verified emails; never use arbitrary URLs in the JSON as-is."""
    rows = read_json(EMAIL_JOBS_FILE, list)
    jobs = []
    seen = set()
    for index, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            print(f"Skipping record {index}: not an object")
            continue
        try:
            url = row["url"]
            title = str(row["title"]).strip()
            company = str(row["company"]).strip()
            job_id = job_id_from_url(url)
            if str(row.get("job_id", "")) != job_id or not title or not company:
                raise ValueError("Missing/mismatched job ID, company, or title")
        except (KeyError, TypeError, ValueError) as exc:
            print(f"Skipping record {index}: {exc}")
            continue
        if match_text and normalized(match_text) not in normalized(title + " " + company):
            continue
        if job_id in seen:
            continue
        seen.add(job_id)
        jobs.append({"job_id": job_id, "url": url, "title": title, "company": company})
    return jobs


def validated_title(page, expected_title):
    """Find the *detail-panel* heading, not just any H1 on the jobs page.

    Handshake's search UI can render multiple H1s (and often puts job cards
    beside the detail pane). The previous `h1.count() == 1` check was too
    strict and failed even though the correct JD was visible.

    For imported jobs, require the visible heading to match the verified email
    title. If there are duplicates (e.g. a matching title in the left list),
    use the position of the right-side `At a glance` panel to disambiguate.
    Never silently select an unrelated heading.
    """
    headings = page.locator("h1, h2")
    if expected_title:
        # The importer already successfully verified titles using h1/h2.
        # Wait for client-side rendering, rather than assuming DOM readiness
        # after the Job description heading becomes visible.
        try:
            headings.filter(has_text=re.compile(re.escape(expected_title), re.I)).first.wait_for(
                state="visible", timeout=15000
            )
        except Exception:
            pass  # Produce a useful diagnostic below rather than a raw timeout.

    visible = []
    for i in range(headings.count()):
        node = headings.nth(i)
        try:
            if not node.is_visible():
                continue
            title = node.inner_text(timeout=3000).strip()
            if title:
                visible.append((node, title))
        except Exception:
            continue

    if expected_title:
        expected = normalized(expected_title)
        exact = [(node, label) for node, label in visible if normalized(label) == expected]
        matches = exact or [
            (node, label) for node, label in visible
            if expected in normalized(label) or normalized(label) in expected
        ]
        if not matches:
            observed = " | ".join(label[:90] for _, label in visible[:10]) or "无可见标题"
            raise RuntimeError(
                f"职位标题尚未在详情页找到：{expected_title!r}。"
                f"可见标题：{observed}。URL: {page.url}"
            )
    else:
        # Preserve original manual mode's unambiguous-H1 behavior.
        primary = page.locator("h1")
        candidates = [(node, label) for node, label in visible
                      if node.evaluate("el => el.tagName.toLowerCase()") == "h1"]
        if len(candidates) != 1:
            raise RuntimeError(
                f"手动模式发现 {len(candidates)} 个可见 h1，无法确定职位标题。"
            )
        return candidates[0][0]

    if len(matches) == 1:
        return matches[0][0]

    # Repeated titles can occur in both the search list and job-detail pane.
    # The detail title is above / horizontally aligned with `At a glance`.
    glance = page.get_by_role("heading", name="At a glance", exact=True)
    glance_boxes = []
    for i in range(glance.count()):
        item = glance.nth(i)
        if item.is_visible():
            bbox = item.bounding_box()
            if bbox:
                glance_boxes.append(bbox)

    if len(glance_boxes) == 1:
        anchor = glance_boxes[0]
        located = []
        for node, label in matches:
            box = node.bounding_box()
            if box:
                located.append((node, label, box))
        # A heading from the left job list will be far left of this anchor.
        right_panel = [
            (node, label, box) for node, label, box in located
            if box["x"] >= anchor["x"] - 130 and box["y"] < anchor["y"] + 20
        ]
        if len(right_panel) == 1:
            return right_panel[0][0]

    raise RuntimeError(
        f"找到 {len(matches)} 个可见、匹配的职位标题，无法确定哪一个在详情区域。"
        "请保留运行时的浏览器页面供检查；本次不保存。"
    )


def extract_one(page, url, expected_title="", expected_company="", interactive=False):
    """Reuse the original selectors, with automated navigation in batch mode."""
    requested_id = job_id_from_url(url)
    page.goto(url, wait_until="domcontentloaded", timeout=60000)

    if interactive:
        print("如果需要登录，请在浏览器里完成登录。")
        print("然后回到这个标签页的目标岗位。")
        input("确认岗位页面已显示后，回到终端按 Enter：")

    page.get_by_text("Job description", exact=True).wait_for(
        state="visible", timeout=20000
    )
    # A login page or an unrelated recommendation must never be saved as this JD.
    actual_id = job_id_from_url(page.url)
    if actual_id != requested_id:
        raise RuntimeError(
            f"实际页面的职位编号 {actual_id} 与请求的 {requested_id} 不一致，本次不保存。"
        )

    title_heading = validated_title(page, expected_title)
    if expected_company and normalized(expected_company) not in normalized(
        page.locator("body").inner_text()
    ):
        raise RuntimeError(f"网页中未发现预期公司 {expected_company}，本次不保存。")

    # 1. Locate the JD section BEFORE searching for its expansion control.
    # The search sidebar and other sections can each have their own "More".
    # Never click a page-global "More" just because it is visible.
    heading = page.get_by_role("heading", name="Job description", exact=True)
    if heading.count() != 1:
        raise RuntimeError("无法唯一定位 Job description 标题，本次不保存。")

    # Retain the original description selector for compatibility with resume code.
    description_box = heading.locator("xpath=../following-sibling::div[1]")
    if description_box.count() != 1:
        raise RuntimeError("无法唯一定位职位正文，请检查网页结构，本次不保存。")

    def visible_nodes(locator):
        nodes = []
        for i in range(locator.count()):
            node = locator.nth(i)
            if node.is_visible():
                nodes.append(node)
        return nodes

    # Prefer an expansion link inside the actual description element.
    relevant_more = visible_nodes(description_box.get_by_text("More", exact=True))
    if len(relevant_more) > 1:
        raise RuntimeError("职位正文内部存在多个 More，无法安全展开；本次不保存。")

    if not relevant_more:
        # Some versions of Handshake put the toggle NEXT TO the description
        # element. Restrict candidates to the enclosing JD section, then
        # require the candidate to be adjacent to the description's bottom.
        section = heading.locator("xpath=../..")
        box = description_box.bounding_box()
        if box:
            for node in visible_nodes(section.get_by_text("More", exact=True)):
                bounds = node.bounding_box()
                if not bounds:
                    continue
                center_x = bounds["x"] + bounds["width"] / 2
                center_y = bounds["y"] + bounds["height"] / 2
                same_column = box["x"] - 20 <= center_x <= box["x"] + box["width"] + 20
                near_bottom = box["y"] + box["height"] - 35 <= center_y <= box["y"] + box["height"] + 45
                if same_column and near_bottom:
                    relevant_more.append(node)
        if len(relevant_more) > 1:
            raise RuntimeError("职位介绍附近存在多个 More，无法安全展开；本次不保存。")

    if relevant_more:
        before = description_box.inner_text().strip()
        relevant_more[0].click(timeout=5000)
        page.wait_for_timeout(450)
        after = description_box.inner_text().strip()
        section = heading.locator("xpath=../..")
        less_visible = bool(visible_nodes(section.get_by_text("Less", exact=True)))
        if len(after) <= len(before) and not less_visible:
            raise RuntimeError("点击职位介绍的 More 后没有确认展开成功，本次不保存。")
        print("  Expanded the Job description section.")
    else:
        print("  No Job description More control found; reading visible description.")

    raw_text = page.locator("body").inner_text()
    description_text = description_box.inner_text().strip()
    if not description_text:
        raise RuntimeError("职位正文为空，本次不保存。")

    glance_heading = page.get_by_role("heading", name="At a glance", exact=True)
    glance_heading.wait_for(state="visible", timeout=15000)
    glance_box = glance_heading.locator("xpath=../..")
    if glance_box.count() != 1:
        raise RuntimeError("无法唯一定位岗位概览，本次不保存。")
    glance_text = glance_box.inner_text().strip()

    header_box = title_heading.locator("xpath=../..")
    header_text = header_box.inner_text().strip()
    if not header_text:
        raise RuntimeError("岗位顶部信息为空，本次不保存。")

    qualifications_heading = page.get_by_role(
        "heading", name="What they're looking for", exact=True
    )
    qualifications_text = "未提取到条件标签（不代表没有要求）。"
    if qualifications_heading.count() == 1:
        qualifications_box = qualifications_heading.locator("xpath=../..")
        pills = qualifications_box.locator('[data-hook="qualification-pill"]')
        items = [pills.nth(i).inner_text().strip() for i in range(pills.count())]
        items = [item for item in items if item]
        if items:
            qualifications_text = "\n".join(f"- {item}" for item in items)
    elif qualifications_heading.count() > 1:
        raise RuntimeError("发现多个候选人条件区域，请检查页面。")

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    prefix = f"{requested_id}_{timestamp}"
    JOBS_FOLDER.mkdir(parents=True, exist_ok=True)
    raw_path = JOBS_FOLDER / f"{prefix}_raw.txt"
    description_path = JOBS_FOLDER / f"{prefix}_description.txt"
    description_content = (
        f"来源：{page.url}\n\n"
        f"{header_text}\n\n"
        f"{glance_text}\n\n"
        "What they're looking for（网站列出的条件／偏好）\n"
        f"{qualifications_text}\n\n"
        f"Job description\n{description_text}"
    )
    raw_path.write_text(raw_text, encoding="utf-8")
    description_path.write_text(description_content, encoding="utf-8")
    print("原始页面已保存到：", raw_path)
    print("职位正文已保存到：", description_path)
    return {"raw_path": str(raw_path), "description_path": str(description_path)}


def process_email_jobs(match="", limit=0, dry_run=False, force=False):
    jobs = get_email_jobs(match)
    state = read_state()
    pending = []
    for job in jobs:
        stored = state.get(job["job_id"], {})
        already_done = (
            isinstance(stored, dict)
            and stored.get("description_path")
            and Path(stored["description_path"]).is_file()
        )
        if already_done and not force:
            continue
        pending.append(job)
    if limit:
        pending = pending[:limit]

    print(f"Verified jobs in JSON: {len(jobs)}")
    print(f"Pending JD extraction: {len(pending)}")
    if dry_run:
        for job in pending:
            print(f"  {job['job_id']} | {job['company']} | {job['title']}")
        print("Dry run: no browser opened and no files modified.")
        return 0
    if not pending:
        print("No new job descriptions to process.")
        return 0

    successes = 0
    failures = 0
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_FOLDER), headless=False, no_viewport=True
        )
        try:
            page = context.new_page()
            for idx, job in enumerate(pending, start=1):
                print(f"\n[{idx}/{len(pending)}] {job['company']} — {job['title']}")
                try:
                    paths = extract_one(
                        page, job["url"], job["title"], job["company"],
                        interactive=False,
                    )
                    state[job["job_id"]] = {
                        **job,
                        **paths,
                        "saved_at": datetime.now().isoformat(timespec="seconds"),
                    }
                    save_state(state)
                    successes += 1
                    print("  SUCCESS: JD saved and marked complete")
                except Exception as exc:
                    failures += 1
                    print(f"  FAILED: {type(exc).__name__}: {exc}")
                    print("  Not marked complete; will retry next run.")
            page.close()
        finally:
            context.close()
    print(f"\nDone. New JDs: {successes}; failed: {failures}; not attempted (done or beyond limit): {len(jobs) - len(pending)}")
    print(f"Progress file: {STATE_FILE}")
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(description="Read Handshake job descriptions")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--from-email", action="store_true", help="Batch read verified Gmail jobs")
    mode.add_argument("--url", help="Read one Handshake job URL (manual mode)")
    parser.add_argument("--match", default="", help="Batch: filter by company or job title")
    parser.add_argument("--limit", type=int, default=0, help="Batch: maximum JDs to attempt (0=all)")
    parser.add_argument("--dry-run", action="store_true", help="Batch: list pending jobs without opening browser")
    parser.add_argument("--force", action="store_true", help="Batch: re-read already completed jobs")
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit cannot be negative")
    if args.from_email:
        return process_email_jobs(args.match, args.limit, args.dry_run, args.force)
    if args.dry_run or args.match or args.limit or args.force:
        parser.error("--match, --limit, --dry-run and --force require --from-email")

    # Original behavior: reading a single job waits for a human login/check.
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(SESSION_FOLDER), headless=False, no_viewport=True
        )
        try:
            page = context.new_page()
            extract_one(page, args.url or DEFAULT_URL, interactive=True)
            page.close()
        finally:
            context.close()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
