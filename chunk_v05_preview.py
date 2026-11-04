"""Offline chunk-v0.5 preview: one-page selection from the master, NO API call.

Usage (project root):
    python chunk_v05_preview.py --job-id 11651900
    python chunk_v05_preview.py --jd-file sample_jds\\frontend.txt
    python chunk_v05_preview.py --job-id 11651900 --no-page-check

Writes chunk_output/v05_preview/<name>_<time>_preview.docx and _report.md.
Bullets are the master's original wording (no polishing / merging here).
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
import re
import sys

from resume_chunks import parse_docx
from resume_layout import PageModel, count_pages
from resume_selector import export_report, render_selected_docx, select_chunks

ROOT = Path(__file__).resolve().parent
DEFAULT_MASTER = ROOT / 'Resume_Arnold Li.docx'
JOBS = ROOT / 'jobs'
OUT = ROOT / 'chunk_output' / 'v05_preview'


def find_jd(job_id: str) -> Path:
    if not re.fullmatch(r'\d+', job_id):
        raise SystemExit('Job ID must be numeric.')
    matches = list(JOBS.glob(f'{job_id}_*_description.txt'))
    if not matches:
        raise SystemExit(f'No saved JD for {job_id} in {JOBS}. Use --jd-file instead.')
    return max(matches, key=lambda p: (p.stat().st_mtime_ns, p.name))


def main() -> None:
    ap = argparse.ArgumentParser(description='Offline one-page chunk selection preview (no API).')
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument('--job-id')
    src.add_argument('--jd-file')
    ap.add_argument('--master', default=str(DEFAULT_MASTER))
    ap.add_argument('--no-page-check', action='store_true', help='skip Word/LibreOffice page count')
    args = ap.parse_args()

    jd_path = find_jd(args.job_id) if args.job_id else Path(args.jd_file)
    jd = jd_path.read_text(encoding='utf-8-sig', errors='replace')
    master_file = Path(args.master).resolve()
    master = parse_docx(master_file)
    model = PageModel(master_file, master)
    selection = select_chunks(master, jd, page_budget=model)

    OUT.mkdir(parents=True, exist_ok=True)
    stem = args.job_id or re.sub(r'[^A-Za-z0-9_-]', '_', jd_path.stem)[:60]
    prefix = OUT / f'{stem}_{datetime.now():%Y%m%d_%H%M%S}_preview'
    docx, report = prefix.with_suffix('.docx'), Path(str(prefix) + '_report.md')
    render_selected_docx(master_file, master, selection, docx)
    export_report(selection, report)

    plan = selection['page_plan']
    print(f'JD: {jd_path.name}')
    print('Role weights:', {k: v for k, v in selection['jd_role_priorities'].items() if v})
    print(f'Estimated: used {plan["used_pt"]}pt of {plan["budget_pt"]}pt '
          f'(spare ~{plan["remaining_pt"] / plan["line_pt"]:.1f} lines)')
    for entry in selection['entries']:
        marks = ''.join(('*' if b['selected'] else '.') for b in entry['bullets'])
        print(f'  [{marks:<4}] {entry["kind"]:<10} {entry["title"][:50]}')
    if not args.no_page_check:
        pages, backend = count_pages(docx)
        print(f'Rendered pages: {pages if pages is not None else "not checked"} ({backend})')
    print('Saved:', docx)
    print('Saved:', report)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError) as exc:
        print(f'Preview failed: {exc}', file=sys.stderr)
        raise SystemExit(1)
