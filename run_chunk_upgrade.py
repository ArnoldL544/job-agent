"""Stand-alone, safe test entry point; does not alter existing Job Agent files."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from resume_chunks import parse_docx
from resume_selector import select_chunks, export_report, render_selected_docx


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description='Select resume chunks for a JD; originals are read-only.')
    parser.add_argument('--master', required=True, help='Existing master .docx')
    parser.add_argument('--jd', required=True, help='Plain text Job Description .txt')
    parser.add_argument('--outdir', default='chunk_output', help='Separate output directory')
    parser.add_argument('--preview-docx', action='store_true', help='Export conservative filtered DOCX copy')
    parser.add_argument('--max-entries', type=int, default=4)
    parser.add_argument('--max-bullets', type=int, default=8)
    parser.add_argument('--max-bullets-per-entry', type=int, default=3)
    parser.add_argument('--include-leadership', action='store_true')
    options = parser.parse_args(argv)
    try:
        master_path = Path(options.master)
        jd_path = Path(options.jd)
        if not jd_path.is_file():
            raise FileNotFoundError(jd_path)
        jd_text = jd_path.read_text(encoding='utf-8-sig')
        if len(jd_text.strip()) < 15:
            raise ValueError('JD is too short. Please provide an actual job description.')
        outdir = Path(options.outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        master = parse_docx(master_path)
        decision = select_chunks(master, jd_text,
                                 max_entries=options.max_entries,
                                 max_bullets=options.max_bullets,
                                 max_bullets_per_entry=options.max_bullets_per_entry,
                                 include_leadership=options.include_leadership)
        (outdir/'master_chunks.json').write_text(json.dumps(master, ensure_ascii=False, indent=2), encoding='utf-8')
        (outdir/'selection.json').write_text(json.dumps(decision, ensure_ascii=False, indent=2), encoding='utf-8')
        export_report(decision, outdir/'selection_review.md')
        if options.preview_docx:
            render_selected_docx(master_path, master, decision, outdir/'selected_resume_preview.docx')
        print('SUCCESS — original master resume unchanged')
        print('Entries parsed:', len(master['entries']))
        print('Entries selected:', len(decision['selected_entry_ids']))
        print('Bullets selected:', len(decision['selected_bullet_ids']))
        print('Required JD skills not evidenced:', ', '.join(decision['required_not_evidenced_in_resume']) or 'none detected')
        print('Review:', outdir / 'selection_review.md')
        if options.preview_docx:
            print('Word preview:', outdir / 'selected_resume_preview.docx')
            print('WARNING: Check Word pagination and confirm factual claims before applying.')
        if master.get('warnings'):
            print('Parser warnings:', *master['warnings'], sep='\n- ')
        return 0
    except (FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f'ERROR: {exc}', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
