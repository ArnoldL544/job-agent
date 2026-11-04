"""Evidence-constrained LLM bullet polish for selected resume chunks.

Master DOCX is the only source of candidate facts. JD is relevance data only.
Never edits identity, education, employer names, roles, dates or skills.
No API call occurs in this module until the caller explicitly invokes generate().

v0.4.1 safety fixes (no interface change for callers):
- Bullets with limited ownership (Assisted/Supported..., "under mentor guidance",
  "only", "planned"...) are never merged, so an action cannot be re-attached to
  someone else's work.
- Hyphenated claims (end-to-end, real-time, fine-tuned) are now detected.
- Single-bullet rewrites on BOTH paths must keep every number and named technology.
- Out-of-order groups are sorted instead of aborting; a structurally broken entry
  falls back to its original bullets. Cross-entry / unknown IDs still abort.
- A merge is accepted only if it saves at least one estimated Word line.

chunk-v0.5 (still one API call, same generate() signature):
- Selection fills ONE PAGE by estimated height (resume_layout.PageModel)
  instead of a fixed 8 bullets; leadership/awards may fill leftover space.
- After polishing/merging, freed space is refilled with ORIGINAL unselected
  bullets (no extra model call); if rewrites grew too long, the lowest-value
  bullet is dropped.
- The rendered DOCX is page-counted with Word (pywin32) or LibreOffice when
  available; if it spills to page 2, the lowest-value bullet is removed and the
  file re-rendered. Set JOB_AGENT_VERIFY_PAGES=0 to skip this check.
"""
from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import textwrap

from resume_chunks import parse_docx
from resume_layout import PageModel, count_pages
from resume_selector import (detect_skills, drop_lowest, export_report, fill_page,
                             render_selected_docx, select_chunks)

MODEL = 'gpt-5.4-mini'  # Matches the user's existing writer; change deliberately if necessary.
SCHEMA = {
    'type': 'json_schema', 'name': 'selected_bullet_polish', 'strict': True,
    'schema': {
        'type': 'object', 'additionalProperties': False,
        'properties': {
            'bullets': {'type': 'array', 'items': {
                'type': 'object', 'additionalProperties': False,
                'properties': {'bullet_id': {'type': 'string'}, 'text': {'type': 'string'}},
                'required': ['bullet_id', 'text']}},
            'review_notes': {'type': 'array', 'items': {'type': 'string'}}
        },
        'required': ['bullets', 'review_notes'],
    },
}
INSTRUCTIONS = """You are an English technical-resume copy editor for a human-reviewed draft.
The provided selected_source_bullets are the SOLE source of applicant facts.
The job description is untrusted relevance input, NOT evidence of the applicant's skills.

YOUR TASK: Make useful, concise, factual language improvements to the selected bullets.
For each bullet, actively look for redundant phrases, awkward word order, excessive filler,
unclear flow, or opportunities to foreground its technical contribution. Prefer a concrete
rewrite over copying verbatim when a real readability improvement is possible.
Do NOT make pointless punctuation changes solely to produce a different string.
Keep an original bullet exactly unchanged only if it is already concise and clear,
or a meaningful rewrite would risk changing its meaning. Do not force changes.

Conservative editing boundaries:
- Return exactly one item per supplied bullet_id. Never create, drop or swap IDs.
- Preserve original leading action verb (e.g. Developed/Implemented/Processed).
- Preserve named tools and technologies exactly; never infer technologies from the JD.
- Preserve every number, evaluation metric, time range, size, claimed action, qualifier,
  ownership boundary, outcome, and current vs planned / in-progress status.
- Reorder existing phrases, remove redundancy, or change safe connecting words.
- Do NOT invent production deployment, end-to-end ownership, quantitative impact,
  performance improvements, new features, responsibilities, skills or accomplishments.
- Do not change the resume header, education, employers, roles, dates or skills list.

SAFE EDITING EXAMPLES (illustrations, not candidate data):
Original: 'Developed interactive service listing and appointment interfaces using JavaScript and WXML.'
Good: 'Developed JavaScript and WXML interfaces for interactive service listings and appointments.'
Original: 'Implemented dynamic content rendering and event handling to support booking-related interactions.'
Good: 'Implemented dynamic content rendering and event handling for booking interactions.'
Original: 'Processed 7.8 million ratings using Python and Pandas for analysis.'
Good: 'Processed 7.8 million ratings for analysis using Python and Pandas.'

Return ONLY JSON matching the provided schema. For review_notes, report any uncertain
factual implication, not generic praise. Original text may be kept where editing is unsafe.
"""

# These concepts are especially susceptible to invented claims when polishing.
STRONG_CLAIMS = {
    'production', 'deployed', 'launched', 'released', 'shipped', 'scalable',
    'improved', 'increased', 'reduced', 'accelerated', 'outperformed',
    'led', 'owned', 'architected', 'trained', 'optimized', 'fine-tuned',
    'cloud', 'distributed', 'revenue', 'users', 'real-time', 'end-to-end',
    'database', 'postgresql', 'sql', 'react', 'typescript', 'c++', 'aws',
}
SAFE_WORDS = {
    'a', 'an', 'and', 'the', 'of', 'with', 'to', 'in', 'on', 'for', 'from',
    'by', 'as', 'at', 'through', 'across', 'using', 'via', 'into', 'that',
    'which', 'while', 'within', 'over', 'under', 'including', 'such', 'both',
    'also', 'supporting', 'support', 'supports', 'related', 'focused',
    'based', 'helping', 'used', 'use', 'built', 'created', 'developed',
    'designed', 'implemented', 'integrated', 'processed', 'evaluated',
    'analyzed', 'generated', 'building', 'developing', 'integrating',
    'resulting', 'enabling', 'provided', 'performed', 'leveraged',
}
NUMBER_RE = re.compile(r'(?<![\w])\d+(?:[,.]\d+)*(?:%)?', re.I)
# v0.4.1: keep hyphenated compounds as one token (end-to-end, front-end) and drop
# a sentence-final period ("analysis." -> "analysis") while keeping "node.js".
WORD_RE = re.compile(r"[a-z][a-z0-9+#]*(?:-[a-z0-9+#]+)*(?:\.[a-z0-9]+)*", re.I)
QUALIFIERS = ('not', 'without', 'only', 'under mentor guidance', 'in progress',
              'currently', 'planned', 'prototype', 'assisted', 'co-developed')
# Leading verbs that state a limited ownership boundary. Such a bullet is never
# merged: a merge could silently re-attach "assisted" or "implemented" to the
# wrong piece of work while every word still survives the mechanical checks.
LIMITED_OWNERSHIP_VERBS = {
    'assisted', 'supported', 'participated', 'contributed', 'helped',
    'collaborated', 'co-developed', 'shadowed', 'learned', 'observed',
}
# Rough Word line estimate for the template body (11pt Times New Roman,
# bullet indent). Calibrate after checking one real rendered resume.
CHARS_PER_LINE = 95
MAX_MERGED_LINES = 3


def _words(text: str) -> set[str]:
    return set(WORD_RE.findall(text.casefold()))


def _term_regex(term: str) -> re.Pattern:
    # "end-to-end" also matches "end to end"; "c++" must not match inside words.
    body = r'[-\s]?'.join(re.escape(part) for part in term.split('-'))
    return re.compile(r'(?<![a-z0-9])' + body + r'(?![a-z0-9+#])', re.I)


STRONG_CLAIM_RES = {word: _term_regex(word) for word in STRONG_CLAIMS}


def _new_strong_claims(source: str, target: str) -> list[str]:
    return sorted(w for w, rx in STRONG_CLAIM_RES.items() if rx.search(target) and not rx.search(source))


def estimate_lines(text: str, width: int = CHARS_PER_LINE) -> int:
    return max(1, len(textwrap.wrap(' '.join(text.split()), width=width)))


def merge_blockers(text: str) -> list[str]:
    """Reasons a source bullet must stay separate (ownership/status limits)."""
    reasons = []
    first = WORD_RE.search(text)
    if first and first.group().casefold() in LIMITED_OWNERSHIP_VERBS:
        reasons.append('limited-ownership verb: ' + first.group())
    low = text.casefold()
    for phrase in QUALIFIERS:
        if re.search(r'\b' + re.escape(phrase) + r'\b', low):
            reasons.append('limiting qualifier: ' + phrase)
    return reasons


def check_rewrite(source: str, candidate: str) -> list[str]:
    """Conservative mechanical guards; semantic correctness still needs review."""
    issues: list[str] = []
    target = ' '.join(candidate.split())
    if not target or '\n' in candidate or len(target) > 350:
        return ['empty/multiline/overlong bullet']
    if len(target) > max(130, len(source) * 1.5):
        issues.append('much longer than evidence')
    # v0.4.1: one-to-one rewrites must keep EVERY number and named technology,
    # not merely avoid adding new ones (dropping "7.8 million" is a fact change).
    if Counter(NUMBER_RE.findall(target)) != Counter(NUMBER_RE.findall(source)):
        issues.append('numeric evidence added or removed')
    if detect_skills(target) != detect_skills(source):
        issues.append('named technology added or removed')
    old_first = WORD_RE.search(source)
    new_first = WORD_RE.search(target)
    if old_first and new_first and old_first.group().lower() != new_first.group().lower():
        issues.append('original leading action verb changed')
    src_lower, dst_lower = source.casefold(), target.casefold()
    for phrase in QUALIFIERS:
        if re.search(r'\b' + re.escape(phrase) + r'\b', src_lower) and not re.search(r'\b' + re.escape(phrase) + r'\b', dst_lower):
            issues.append('removed limiting qualifier: ' + phrase)
    for word in _new_strong_claims(source, target):
        issues.append('unsupported strong claim: ' + word)
    new_terms = _words(target) - _words(source) - SAFE_WORDS
    if len(new_terms) > 2:
        issues.append('too many novel content words: ' + ', '.join(sorted(new_terms)[:6]))
    source_terms = {t for t in _words(source) if len(t) >= 4 and t not in SAFE_WORDS}
    retained = source_terms & _words(target)
    if source_terms and len(retained) / len(source_terms) < .55:
        issues.append('too much of source evidence removed')
    return issues


def prepare(master_file: Path, jd: str) -> tuple[dict, dict, list[dict]]:
    master = parse_docx(master_file)
    # chunk-v0.5: one-page budget from the master's own geometry and fonts.
    selection = select_chunks(master, jd, page_budget=PageModel(master_file, master))
    selected_ids = set(selection['selected_bullet_ids'])
    bullets = [
        {'bullet_id': b['id'], 'text': b['text'], 'entry_id': entry['id'], 'entry_title': entry['title']}
        for entry in master['entries'] for b in entry['bullets']
        if b['id'] in selected_ids
    ]
    if not bullets or len(bullets) != len(selected_ids):
        raise ValueError('No valid unique selected bullets; check the master resume.')
    return master, selection, bullets


# ---------------------------------------------------------------------------
# chunk-v0.5: fit the final (polished / merged) bullets to one page
# ---------------------------------------------------------------------------
MAX_RENDER_TRIMS = 5


def _bullet_index(master: dict) -> dict[str, dict]:
    return {b['id']: b for e in master['entries'] for b in e['bullets']}


def _chosen_from_rows(rows: list[dict]) -> dict[str, list[str]]:
    chosen: dict[str, list[str]] = {}
    for row in rows:
        chosen.setdefault(row['entry_id'], []).append(row['anchor_id'])
    return chosen


def _finalize_page(master_file: Path, master: dict, jd: str, selection: dict,
                   rows: list[dict]) -> tuple[list[dict], dict | None]:
    """Estimated fit: drop lowest-value rows if over budget, then refill freed space
    with ORIGINAL unselected bullets. Absorbed merge sources are never re-added."""
    plan = selection.get('page_plan')
    if not plan:
        return rows, None  # legacy fixed-count selection: nothing to fit
    model = PageModel(master_file, master)
    index = _bullet_index(master)
    values = dict(plan.get('values', {}))
    rows = [dict(r) for r in rows]

    def used(current):
        grouped: dict[str, list] = {}
        for r in current:
            grouped.setdefault(r['entry_id'], []).append((index[r['anchor_id']], r['text']))
        return model.plan_pt(grouped)

    budget = model.budget_pt()
    before = used(rows)
    dropped: list[dict] = []
    while used(rows) > budget and len(rows) > 1:
        bid = drop_lowest(_chosen_from_rows(rows), values)
        if bid is None:
            break
        dropped.append(next(r for r in rows if r['anchor_id'] == bid))
        rows = [r for r in rows if r['anchor_id'] != bid]
    excluded = {x for r in rows + dropped for x in r['source_ids']}
    _, log = fill_page(master, jd, model, chosen=_chosen_from_rows(rows),
                       texts={r['anchor_id']: r['text'] for r in rows},
                       excluded_ids=excluded, phases=('relevance', 'fill', 'activity'), label='refill')
    refilled = []
    for item in log:
        bullet = index[item['bullet_id']]
        rows.append({'entry_id': item['entry_id'], 'anchor_id': bullet['id'], 'source_ids': [bullet['id']],
                     'text': bullet['text'], 'proposed': '', 'status': 'refill',
                     'reasons': ['original master bullet added to use space freed by merging/polishing']})
        values[bullet['id']] = {'phase': 'refill', 'value': item['value']}
        refilled.append(bullet['id'])
    rows.sort(key=lambda r: index[r['anchor_id']]['paragraph'])
    after = used(rows)
    return rows, {'budget_pt': round(budget, 1), 'used_before_fit_pt': round(before, 1),
                  'used_pt': round(after, 1), 'remaining_pt': round(budget - after, 1),
                  'line_pt': plan.get('line_pt', 12.65), 'values': values,
                  'jd_signal_weak': plan.get('jd_signal_weak', False),
                  'refilled': refilled, 'dropped_for_space': [r['anchor_id'] for r in dropped]}


def _render_fitted(master_file: Path, master: dict, selection: dict, rows: list[dict],
                   docx: Path, values: dict) -> tuple[list[dict], dict, list[dict], dict]:
    """Render; when Word/LibreOffice is available and the result exceeds one page,
    drop the lowest-value bullet and re-render (at most MAX_RENDER_TRIMS times)."""
    index = _bullet_index(master)
    verify = selection.get('page_plan') is not None and os.environ.get('JOB_AGENT_VERIFY_PAGES', '1') != '0'
    removed: list[dict] = []
    check = {'pages': None, 'backend': 'skipped' if not verify else 'none available'}
    final = selection
    for _ in range(MAX_RENDER_TRIMS + 1):
        final = deepcopy(selection)
        final['selected_bullet_ids'] = sorted(r['anchor_id'] for r in rows)
        final['selected_entry_ids'] = sorted({r['entry_id'] for r in rows})
        replacements = {r['anchor_id']: r['text'] for r in rows if r['text'] != index[r['anchor_id']]['text']}
        docx.unlink(missing_ok=True)
        render_selected_docx(master_file, master, final, docx, bullet_replacements=replacements)
        if not verify:
            break
        pages, backend = count_pages(docx)
        check = {'pages': pages, 'backend': backend}
        if pages is None or pages <= 1 or len(rows) <= 1:
            break
        bid = drop_lowest(_chosen_from_rows(rows), values)
        if bid is None:
            break
        removed.append(next(r for r in rows if r['anchor_id'] == bid))
        rows = [r for r in rows if r['anchor_id'] != bid]
    return rows, final, removed, check


def _page_report(page: dict | None, check: dict, removed: list[dict], index: dict) -> list[str]:
    if page is None:
        return []
    lp = page.get('line_pt', 12.65)
    lines = ['## Page fit (chunk-v0.5)', '']
    if page.get('jd_signal_weak'):
        lines += ['> **JD signal too weak to tailor:** no recognised role keywords, so bullets were '
                  'chosen by general value only. Check the extracted JD text before applying.', '']
    lines += [
             f'- Estimated budget for experience sections: {page["budget_pt"]}pt; used after polishing/merging: '
             f'{page["used_before_fit_pt"]}pt; final: {page["used_pt"]}pt; spare: {page["remaining_pt"]}pt '
             f'(~{page["remaining_pt"] / lp:.1f} lines)']
    if check.get('pages') is not None:
        lines.append(f'- Rendered page count ({check["backend"]}): {check["pages"]}')
    else:
        lines.append(f'- Rendered page count: not verified ({check.get("backend")}); open the DOCX in Word to confirm one page.')
    lines += ['', '**Refilled with original master bullets (freed space):**', '']
    lines += [f'- `{b}` {index[b]["text"]}' for b in page['refilled']] or ['- None']
    lines += ['', '**Dropped to fit one page (lowest value first):**', '']
    gone = [index[b]['text'] for b in page['dropped_for_space']] + [r['text'] for r in removed]
    lines += [f'- {t}' for t in gone] or ['- None']
    return lines + ['']


def polish(client, jd: str, bullets: list[dict]) -> tuple[dict[str, str], list[str], list[str], dict[str, dict]]:
    """Call the LLM once; fail closed for malformed identity, fallback per invalid bullet."""
    request = {
        'job_description_for_style_only': jd[:14000],
        'selected_source_bullets': bullets,
    }
    response = client.responses.create(
        model=MODEL, instructions=INSTRUCTIONS,
        input=json.dumps(request, ensure_ascii=False),
        text={'format': SCHEMA}, max_output_tokens=3000, store=False,
    )
    if getattr(response, 'status', None) != 'completed':
        raise ValueError('Model response was incomplete; no draft saved.')
    for item in getattr(response, 'output', None) or []:
        for part in getattr(item, 'content', None) or []:
            if getattr(part, 'type', None) == 'refusal':
                raise ValueError('Model declined to polish; no draft saved.')
    try:
        payload = json.loads(getattr(response, 'output_text', '') or '')
    except (TypeError, ValueError) as exc:
        raise ValueError('Model returned malformed JSON; no draft saved.') from exc
    if not isinstance(payload, dict) or not isinstance(payload.get('bullets'), list) or not isinstance(payload.get('review_notes'), list):
        raise ValueError('Model returned incomplete rewrite schema.')
    expected = {b['bullet_id']: b['text'] for b in bullets}
    received: dict[str, str] = {}
    for row in payload['bullets']:
        if not isinstance(row, dict) or set(row) != {'bullet_id', 'text'}:
            raise ValueError('Invalid rewrite item fields.')
        bullet_id = row['bullet_id']
        if not isinstance(bullet_id, str) or bullet_id not in expected or bullet_id in received or not isinstance(row['text'], str):
            raise ValueError('Unknown/duplicate bullet ID in model output; no draft saved.')
        received[bullet_id] = row['text']
    if received.keys() != expected.keys():
        raise ValueError('Missing selected bullet ID(s) in model output; no draft saved.')
    applied: dict[str, str] = {}
    warnings: list[str] = []
    diagnostics: dict[str, dict] = {}
    for bullet_id, source in expected.items():
        text = ' '.join(received[bullet_id].split())
        issues = check_rewrite(source, text)
        if issues:
            warnings.append(f'{bullet_id}: rewrite rejected; original retained ({"; ".join(issues)}).')
            diagnostics[bullet_id] = {'status': 'rejected', 'proposed': text, 'reasons': issues}
        elif text != source:
            applied[bullet_id] = text
            diagnostics[bullet_id] = {'status': 'accepted', 'proposed': text, 'reasons': []}
        else:
            diagnostics[bullet_id] = {'status': 'unchanged', 'proposed': text, 'reasons': []}
    review_notes = [x[:300] for x in payload['review_notes'][:10] if isinstance(x, str) and x.strip()]
    return applied, warnings, review_notes, diagnostics


def _generate_legacy(client, master_file: Path, jd: str, job_id: str, output_dir: Path,
                     prepared: tuple | None = None) -> dict[str, Path | int]:
    """Generate a review-only DOCX, Markdown audit and selection JSON; never overwrite."""
    if not re.fullmatch(r'\d+', job_id):
        raise ValueError('Job ID must be numeric.')
    if not jd.strip() or len(jd.strip()) < 30:
        raise ValueError('Job description is incomplete.')
    master_file = Path(master_file).resolve()
    master, selection, bullets = prepared or prepare(master_file, jd)
    source_digest = hashlib.sha256(master_file.read_bytes()).hexdigest()
    rewrites, warnings, model_notes, diagnostics = polish(client, jd, bullets)
    counts = Counter(item['status'] for item in diagnostics.values())
    if hashlib.sha256(master_file.read_bytes()).hexdigest() != source_digest:
        raise ValueError('Master was changed during generation; aborting.')
    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    prefix = f'{job_id}_{timestamp}_chunk_tailored'
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    docx = folder / (prefix + '.docx')
    md = folder / (prefix + '.md')
    selection_json = folder / (prefix + '.selection.json')
    # Selected content always retains the master document layout and immutable fields.
    rows = [{'entry_id': b['entry_id'], 'anchor_id': b['bullet_id'], 'source_ids': [b['bullet_id']],
             'text': rewrites.get(b['bullet_id'], b['text']), 'proposed': diagnostics[b['bullet_id']]['proposed'],
             'status': diagnostics[b['bullet_id']]['status'], 'reasons': diagnostics[b['bullet_id']]['reasons']}
            for b in bullets]
    rows, page = _finalize_page(master_file, master, jd, selection, rows)
    values = page['values'] if page else {}
    rows, final_selection, removed, check = _render_fitted(master_file, master, selection, rows, docx, values)
    from docx import Document
    final_texts = '\n'.join(p.text for p in Document(docx).paragraphs)
    for row in rows:
        if row['text'] not in final_texts:
            docx.unlink(missing_ok=True)
            raise ValueError('Rendered DOCX does not contain an output bullet.')
    if page:
        final_selection['page_fit_v05'] = {k: v for k, v in page.items() if k != 'values'} | {
            'render_check': check, 'removed_after_render': [r['anchor_id'] for r in removed]}
    lines = [
        '# Chunk-tailored resume — human review required', '',
        f'- Job ID: `{job_id}`',
        f'- Master source: `{master_file.name}` (SHA256: `{source_digest}`)',
        f'- Model: `{MODEL}`; selected bullets: {len(bullets)}; accepted polishes: {len(rewrites)}',
        f'- Model unchanged: {counts["unchanged"]}; validation rejected: {counts["rejected"]}; accepted: {counts["accepted"]}',
        '- Master header, education, employers, dates and skills copied unchanged.',
        '- JD is untrusted relevance input; no job application was submitted.', '',
        '## Bullet-level change review', '',
    ]
    for b in bullets:
        edited = rewrites.get(b['bullet_id'], b['text'])
        diag = diagnostics[b['bullet_id']]
        lines.extend([f'### {b["entry_title"]}', '', f'- Source (`{b["bullet_id"]}`): {b["text"]}',
                      f'- Model proposal: {diag["proposed"]}',
                      f'- Output: {edited}',
                      f'- Status: {diag["status"]}',
                      *([f'- Rejection reasons: {"; ".join(diag["reasons"])}'] if diag['reasons'] else []),
                      ''])
    lines.extend(['## Automatic validation warnings', ''])
    lines += ['- ' + x for x in warnings] if warnings else ['- None detected by local checks.']
    if not rewrites and counts['unchanged'] == len(bullets):
        lines += ['', '**Diagnostic:** All bullets were copied unchanged by the model; no local rewrite was rejected.', '']
    lines += ['', '## Model review notes', '']
    lines += ['- ' + x for x in model_notes] if model_notes else ['- None']
    lines += ['']
    lines += _page_report(page, check, removed, _bullet_index(master))
    lines += ['## Required skills not evidenced in source', '',
              ', '.join(selection['required_not_evidenced_in_resume']) or 'None detected', '',
              '## Reminder', '',
              'Automatic checks cannot establish semantic truth; manually review every rewritten claim,',
              'Word pagination, skill ownership, dates and eligibility before applying.', '']
    with md.open('x', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    with selection_json.open('x', encoding='utf-8') as f:
        json.dump(final_selection, f, ensure_ascii=False, indent=2)
    if hashlib.sha256(master_file.read_bytes()).hexdigest() != source_digest:
        raise AssertionError('Unexpected master mutation after render.')
    return {'docx': docx, 'markdown': md, 'selection_json': selection_json,
            'accepted_rewrites': len(rewrites), 'selected_bullets': len(bullets),
            'unchanged_by_model': counts['unchanged'], 'rejected_rewrites': counts['rejected'],
            'final_bullets': len(rows), 'refilled': len(page['refilled']) if page else 0,
            'dropped_for_space': (len(page['dropped_for_space']) if page else 0) + len(removed),
            'page_count': check['pages'], 'page_check': check['backend']}


# v0.4: Compose selected bullets *within* one entry. Unlike ordinary one-to-one
# polishing, this permits an auditable 2 -> 1 merge for redundant evidence.
# It is deliberately limited to entries with >=3 selected bullets;
# smaller entries continue through the tested v0.3.1 pathway.
# v0.4.1: bullets with limited ownership/status are marked merge_eligible=false
# and are rejected locally even if the model merges them anyway.
COMPOSE_SCHEMA = {
    'type': 'json_schema', 'name': 'evidence_bullet_composition_v04', 'strict': True,
    'schema': {
        'type': 'object', 'additionalProperties': False,
        'properties': {
            'entries': {'type': 'array', 'items': {
                'type': 'object', 'additionalProperties': False,
                'properties': {
                    'entry_id': {'type': 'string'},
                    'groups': {'type': 'array', 'items': {
                        'type': 'object', 'additionalProperties': False,
                        'properties': {
                            'source_ids': {'type': 'array', 'items': {'type': 'string'}},
                            'text': {'type': 'string'},
                        },
                        'required': ['source_ids', 'text'],
                    }},
                },
                'required': ['entry_id', 'groups'],
            }},
            'review_notes': {'type': 'array', 'items': {'type': 'string'}},
        },
        'required': ['entries', 'review_notes'],
    },
}
COMPOSE_INSTRUCTIONS = """You are a precise, evidence-constrained technical resume editor.
Return exactly the JSON schema. Job description is ONLY a relevance signal, never
proof the applicant possesses a technology or experience.

You will receive source_entries: each entry has an immutable entry_id, a
merge_allowed flag and its selected bullets with immutable bullet_id values.
All selected bullet IDs must appear exactly once in your output. Never invent,
remove, swap or duplicate sources, or combine sources from different entries.
For entries with merge_allowed=false, return exactly one group per original bullet.
For entries with merge_allowed=true, look seriously for redundancy. Where two
bullets describe overlapping aspects of the same work, merge those TWO into one
concise bullet if ALL DISTINCT FACTS from both remain. If there is no safe
redundancy to remove, keep the bullets separate. Never merge more than two
sources into a single bullet. Do not split one source into multiple.
NEVER merge a bullet whose merge_eligible is false; return it as its own group.
In a merge, every action verb must stay attached to the same work it described in
its source. Never move "assisted", "designed", "implemented" etc. onto another task.
A merge must be clearly shorter than the two sources together.
Return groups in the order of their earliest source bullet in the master.

You may improve clarity, technical emphasis and ordering based on the JD.
Preserve ALL original facts, actions, ownership qualifiers, tools, languages,
numbers, metrics, uncertainty and planned/in-progress status. Never invent
work, tools, deployments, impact, performance, proficiency or business outcomes.
Do not alter company names, titles, dates, header, education or skills.
Only evidence already present in the attached source bullet(s) may be expressed.
Avoid filler, generic praise and superficial preposition-only edits.

Example of a SAFE merge using illustrative data ONLY:
Source A: 'Developed navigation and appointment interfaces using JavaScript.'
Source B: 'Designed and integrated components for appointment selection.'
Combined: 'Developed JavaScript navigation and appointment interfaces, designing
and integrating components for appointment selection.'
The combined text preserves BOTH actions, each on its own work, and all distinct facts.

It is preferable to leave an already clear bullet unchanged instead of inventing
new claims. review_notes only when an ambiguity needs a person's attention.
"""


def _meaningful_terms(text: str) -> set[str]:
    """Approximate evidence footprint; cannot establish semantic truth."""
    return {w for w in _words(text) if len(w) > 3 and w not in SAFE_WORDS}


def check_merge(sources: list[str], candidate: str) -> list[str]:
    """Fail-closed mechanical checks for joining two evidence bullets."""
    issues: list[str] = []
    text = ' '.join(candidate.split())
    if len(sources) != 2 or not text or '\n' in candidate or len(text) > 350:
        return ['invalid merged text or source count']
    # v0.4.1: ownership-limited bullets never merge (verb/qualifier re-attachment risk).
    for i, source in enumerate(sources, 1):
        for reason in merge_blockers(source):
            issues.append(f'source {i} must stay separate ({reason})')
    original = ' '.join(sources)
    # v0.4.1: the point of merging is page space, so measure lines, not characters.
    before = sum(estimate_lines(s) for s in sources)
    after = estimate_lines(text)
    if after >= before:
        issues.append(f'merge saves no estimated Word line ({before} -> {after})')
    if after > MAX_MERGED_LINES:
        issues.append(f'merged bullet too long ({after} estimated lines)')
    if set(NUMBER_RE.findall(original)) != set(NUMBER_RE.findall(text)):
        issues.append('numeric evidence added or removed')
    if detect_skills(text) != detect_skills(original):
        issues.append('named technology added or removed')
    old, new = _words(original), _words(text)
    for word in _new_strong_claims(original, text):
        issues.append('unsupported strong claim: ' + word)
    added = new - old - SAFE_WORDS
    if len(added) > 4:
        issues.append('excessive new content words: ' + ', '.join(sorted(added)[:8]))
    for i, source in enumerate(sources, 1):
        terms = _meaningful_terms(source)
        if terms and len(new & terms) / len(terms) < .37:
            issues.append(f'insufficient evidence retained from source {i}')
    pooled = _meaningful_terms(original)
    if pooled and len(new & pooled) / len(pooled) < .56:
        issues.append('too much combined evidence removed')
    # v0.4.1: BOTH original action verbs must survive (was: any one of them).
    verbs = [m.group().casefold() for m in (WORD_RE.search(s) for s in sources) if m]
    lost = [v for v in verbs if v not in new]
    if lost:
        issues.append('lost original action verb: ' + ', '.join(lost))
    return issues


def _selected_groups(master: dict, selection: dict) -> list[dict]:
    selected = set(selection['selected_bullet_ids'])
    entries = []
    for entry in master['entries']:
        bullets = [
            {'bullet_id': b['id'], 'text': b['text'], 'paragraph': b['paragraph'],
             'merge_eligible': not merge_blockers(b['text'])}
            for b in entry['bullets'] if b['id'] in selected
        ]
        if bullets:
            eligible = sum(b['merge_eligible'] for b in bullets)
            entries.append({
                'entry_id': entry['id'], 'entry_title': entry['title'],
                'merge_allowed': len(bullets) >= 3 and eligible >= 2, 'bullets': bullets,
            })
    return entries


def _fallback_rows(entry: dict, reason: str) -> list[dict]:
    return [{'entry_id': entry['entry_id'], 'anchor_id': b['bullet_id'], 'source_ids': [b['bullet_id']],
             'text': b['text'], 'proposed': '', 'status': 'entry_fallback', 'reasons': [reason]}
            for b in entry['bullets']]


def compose(client, jd: str, entries: list[dict]) -> tuple[list[dict], list[str], list[str], dict[str, int]]:
    """One API call. Check provenance before accepting *any* structural edits.

    Unknown or cross-entry IDs abort before writing (provenance is broken).
    v0.4.1: an entry whose groups are otherwise malformed (omitted/duplicate IDs,
    illegal merge) falls back to its original bullets; out-of-order groups are
    simply sorted. If a proposed merge is unsafe, that pair reverts to originals.
    """
    request = {
        'job_description_for_style_only': jd[:14000],
        'source_entries': [
            {'entry_id': e['entry_id'], 'entry_title': e['entry_title'],
             'merge_allowed': e['merge_allowed'],
             'bullets': [{'bullet_id': b['bullet_id'], 'text': b['text'],
                          'merge_eligible': b['merge_eligible']} for b in e['bullets']]}
            for e in entries
        ],
    }
    response = client.responses.create(
        model=MODEL, instructions=COMPOSE_INSTRUCTIONS,
        input=json.dumps(request, ensure_ascii=False),
        text={'format': COMPOSE_SCHEMA}, max_output_tokens=4300, store=False,
    )
    if getattr(response, 'status', None) != 'completed':
        raise ValueError('Incomplete composition response; no draft saved.')
    for item in getattr(response, 'output', None) or []:
        for part in getattr(item, 'content', None) or []:
            if getattr(part, 'type', None) == 'refusal':
                raise ValueError('Model refused composition; no draft saved.')
    try:
        payload = json.loads(getattr(response, 'output_text', '') or '')
    except (TypeError, ValueError) as exc:
        raise ValueError('Malformed composition JSON; no draft saved.') from exc
    if not isinstance(payload, dict) or not isinstance(payload.get('entries'), list) or not isinstance(payload.get('review_notes'), list):
        raise ValueError('Incomplete composition schema; no draft saved.')
    by_entry = {e['entry_id']: e for e in entries}
    owner = {b['bullet_id']: e['entry_id'] for e in entries for b in e['bullets']}
    got_ids: set[str] = set()
    outputs: list[dict] = []
    warnings: list[str] = []
    stats = Counter()
    for model_entry in payload['entries']:
        if not isinstance(model_entry, dict) or set(model_entry) != {'entry_id', 'groups'}:
            raise ValueError('Invalid composition entry fields.')
        eid = model_entry['entry_id']
        if not isinstance(eid, str) or eid not in by_entry or eid in got_ids or not isinstance(model_entry['groups'], list):
            raise ValueError('Unknown or duplicate entry ID in composition.')
        got_ids.add(eid)
        original = by_entry[eid]
        by_id = {b['bullet_id']: b for b in original['bullets']}
        used: set[str] = set()
        group_rows: list[tuple[list[str], str]] = []
        problem = None
        for group in model_entry['groups']:
            if not isinstance(group, dict) or set(group) != {'source_ids', 'text'}:
                raise ValueError('Invalid composition bullet group fields.')
            ids, text = group['source_ids'], group['text']
            if not isinstance(ids, list) or any(not isinstance(x, str) for x in ids) or not isinstance(text, str):
                raise ValueError('Malformed composition group.')
            foreign = [x for x in ids if x not in by_id]
            if foreign:
                # Unknown or another entry's bullet: provenance itself is unreliable.
                raise ValueError('Cross-entry or unknown source ID in composition.')
            if problem:
                continue
            if not 1 <= len(ids) <= 2:
                problem = 'group with zero or more than two sources'
            elif not original['merge_allowed'] and len(ids) != 1:
                problem = 'merge attempted for an ineligible entry'
            elif len(ids) != len(set(ids)) or used & set(ids):
                problem = 'duplicate source ID'
            else:
                used.update(ids)
                group_rows.append((ids, text))
        if not problem and used != set(by_id):
            problem = 'omitted source ID(s)'
        if problem:
            stats['entry_fallbacks'] += 1
            warnings.append(f'{eid}: {problem}; entry kept as original bullets.')
            outputs.extend(_fallback_rows(original, problem))
            continue
        # v0.4.1: order is cosmetic; sort rather than abort a paid draft.
        group_rows.sort(key=lambda row: min(by_id[x]['paragraph'] for x in row[0]))
        for ids, proposal in group_rows:
            source = [by_id[x]['text'] for x in ids]
            proposed = ' '.join(proposal.split())
            lines_before = lines_after = None
            if len(ids) == 2:
                stats['proposed_merges'] += 1
                problems = check_merge(source, proposal)
                lines_before = sum(estimate_lines(s) for s in source)
                lines_after = estimate_lines(proposed) if proposed else lines_before
                if problems:
                    stats['rejected_merges'] += 1
                    warnings.append(f'{eid} {ids}: merge rejected ({"; ".join(problems)}); both sources retained.')
                    for bid in sorted(ids, key=lambda x: by_id[x]['paragraph']):
                        outputs.append({'entry_id': eid, 'anchor_id': bid, 'source_ids': [bid],
                                        'text': by_id[bid]['text'], 'proposed': proposed,
                                        'status': 'merge_rejected_fallback', 'reasons': problems})
                    continue
                stats['accepted_merges'] += 1
                stats['estimated_lines_saved'] += lines_before - lines_after
                status = 'merged'
            else:
                # v0.4.1: number/technology equality now lives inside check_rewrite.
                problems = check_rewrite(source[0], proposal)
                if problems:
                    stats['rejected_rewrites'] += 1
                    warnings.append(f'{ids[0]}: rewrite rejected ({"; ".join(problems)}); original retained.')
                    status = 'rejected'
                else:
                    status = 'rewritten' if proposed != source[0] else 'unchanged'
                    stats[status] += 1
            anchor = min(ids, key=lambda x: by_id[x]['paragraph'])
            row = {'entry_id': eid, 'anchor_id': anchor, 'source_ids': ids,
                   'text': source[0] if status == 'rejected' else proposed,
                   'proposed': proposed, 'status': status, 'reasons': problems}
            if lines_before is not None:
                row.update(lines_before=lines_before, lines_after=lines_after)
            outputs.append(row)
    for eid in by_entry.keys() - got_ids:
        stats['entry_fallbacks'] += 1
        warnings.append(f'{eid}: entry missing from model output; kept as original bullets.')
        outputs.extend(_fallback_rows(by_entry[eid], 'entry missing from model output'))
    # Return in actual Word paragraph order, independent of model response order.
    anchor_position = {b['bullet_id']: b['paragraph'] for e in entries for b in e['bullets']}
    outputs.sort(key=lambda row: anchor_position[row['anchor_id']])
    covered = [x for row in outputs for x in row['source_ids']]
    if sorted(covered) != sorted(owner):
        raise AssertionError('Composition output does not cover every selected bullet exactly once.')
    notes = [x[:300] for x in payload['review_notes'][:10] if isinstance(x, str) and x.strip()]
    return outputs, warnings, notes, dict(stats)


def _generate_composed(client, master_file: Path, jd: str, job_id: str, output_dir: Path,
                       prepared: tuple | None = None, groups: list[dict] | None = None) -> dict[str, Path | int]:
    """Review-only, provenance-tracked composition; use legacy Word renderer."""
    if not re.fullmatch(r'\d+', job_id) or len(jd.strip()) < 30:
        raise ValueError('Invalid job ID or incomplete JD.')
    master_file = Path(master_file).resolve()
    prepared = prepared or prepare(master_file, jd)
    master, selection, selected_bullets = prepared
    groups = groups if groups is not None else _selected_groups(master, selection)
    if not any(e['merge_allowed'] for e in groups):
        return _generate_legacy(client, master_file, jd, job_id, output_dir, prepared=prepared)
    source_digest = hashlib.sha256(master_file.read_bytes()).hexdigest()
    composed, warnings, notes, counts = compose(client, jd, groups)
    if hashlib.sha256(master_file.read_bytes()).hexdigest() != source_digest:
        raise ValueError('Master changed during generation.')
    # Reuse v0.3 renderer by mapping each composed line to its earliest source
    # paragraph and pruning only the IDs absorbed into an accepted merge.
    index = _bullet_index(master)
    source_map = {bid: b['text'] for bid, b in index.items()}
    # chunk-v0.5: refill space freed by merges (original bullets only), trim on overflow.
    composed, page = _finalize_page(master_file, master, jd, selection, composed)
    values = page['values'] if page else {}
    stamp = datetime.now().strftime('%Y%m%d_%H%M%S_%f')
    prefix = f'{job_id}_{stamp}_chunk_tailored'
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    docx = folder / (prefix + '.docx')
    md = folder / (prefix + '.md')
    selection_json = folder / (prefix + '.selection.json')
    composed, final_selection, removed, check = _render_fitted(master_file, master, selection, composed, docx, values)
    final_selection['composition_v04'] = [
        {k: x[k] for k in ('entry_id', 'source_ids', 'anchor_id', 'status', 'text', 'proposed', 'reasons',
                           'lines_before', 'lines_after') if k in x}
        for x in composed
    ]
    if page:
        final_selection['page_fit_v05'] = {k: v for k, v in page.items() if k != 'values'} | {
            'render_check': check, 'removed_after_render': [r['anchor_id'] for r in removed]}
    from docx import Document
    rendered = '\n'.join(p.text for p in Document(docx).paragraphs)
    for row in composed:
        if row['text'] not in rendered:
            docx.unlink(missing_ok=True)
            raise ValueError('Rendered Word is missing an output bullet.')
    original_selected = len(selected_bullets)
    accepted_rewrites = counts.get('rewritten', 0) + counts.get('accepted_merges', 0)
    lines_saved = counts.get('estimated_lines_saved', 0)
    lines = [
        '# Chunk-tailored resume — chunk-v0.5 composition (human review required)', '',
        f'- Job ID: `{job_id}`',
        f'- Master source: `{master_file.name}` (SHA256: `{source_digest}`)',
        f'- Model: `{MODEL}`; selected source bullets: {original_selected}; final Word bullets: {len(composed)}',
        f'- Proposed merges: {counts.get("proposed_merges",0)}; accepted merges: {counts.get("accepted_merges",0)}; rejected merges: {counts.get("rejected_merges",0)}',
        f'- Rewritten singles: {counts.get("rewritten",0)}; unchanged singles: {counts.get("unchanged",0)}; rejected singles: {counts.get("rejected_rewrites",0)}',
        f'- Entry fallbacks (malformed model output, originals kept): {counts.get("entry_fallbacks",0)}',
        f'- Estimated Word lines saved by merges: {lines_saved} (at {CHARS_PER_LINE} chars/line; confirm in Word)',
        '- Company, title, dates, education, skills and header remain copied from Master.',
        '- No automatic job application; all candidate claims require human review.', '',
        '## Source-linked output bullets', '',
    ]
    name_map = {e['id']: e['title'] for e in master['entries']}
    for row in composed:
        lines.extend([f'### {name_map[row["entry_id"]]} — {row["status"]}', '',
                      f'- Source IDs: {", ".join("`"+x+"`" for x in row["source_ids"])}',
                      *[f'- Source {i+1}: {source_map[bid]}' for i, bid in enumerate(row['source_ids'])],
                      f'- Model proposal: {row["proposed"] or "(none)"}',
                      f'- Final output: {row["text"]}',
                      *([f'- Estimated lines: {row["lines_before"]} -> {row["lines_after"]}'] if 'lines_before' in row else []),
                      *([f'- Validation: {"; ".join(row["reasons"])}'] if row['reasons'] else []), ''])
    lines += ['## Validation warnings', '']
    lines += ['- '+x for x in warnings] if warnings else ['- None detected by mechanical checks.']
    lines += ['', '## Model review notes', '']
    lines += ['- '+x for x in notes] if notes else ['- None']
    lines += ['']
    lines += _page_report(page, check, removed, index)
    lines += ['## Required skills not evidenced', '',
              ', '.join(selection['required_not_evidenced_in_resume']) or 'None detected', '',
              '## Human review reminder', '',
              'For every merged bullet: is each fact from BOTH sources still present, and is',
              'each action verb still attached to the same work? Check numbers, technologies,',
              'Word pagination and eligibility. Mechanical checks cannot prove semantic truth.', '']
    # Only after successful rendering and validation, write audit artifacts.
    with md.open('x', encoding='utf-8') as f:
        f.write('\n'.join(lines))
    with selection_json.open('x', encoding='utf-8') as f:
        json.dump(final_selection, f, ensure_ascii=False, indent=2)
    if hashlib.sha256(master_file.read_bytes()).hexdigest() != source_digest:
        raise AssertionError('Unexpected Master mutation.')
    return {'docx': docx, 'markdown': md, 'selection_json': selection_json,
            'accepted_rewrites': accepted_rewrites, 'selected_bullets': original_selected,
            'final_bullets': len(composed), 'accepted_merges': counts.get('accepted_merges',0),
            'rejected_merges': counts.get('rejected_merges',0),
            'unchanged_by_model': counts.get('unchanged',0),
            'rejected_rewrites': counts.get('rejected_rewrites',0),
            'entry_fallbacks': counts.get('entry_fallbacks',0),
            'estimated_lines_saved': lines_saved,
            'refilled': len(page['refilled']) if page else 0,
            'dropped_for_space': (len(page['dropped_for_space']) if page else 0) + len(removed),
            'page_count': check['pages'], 'page_check': check['backend']}


def generate(client, master_file: Path, jd: str, job_id: str,
             output_dir: Path) -> dict[str, Path | int]:
    """v0.4 entry-aware composition when meaningful; v0.3.1 otherwise."""
    # prepare() has no API cost; v0.4.1 runs it once and passes the result on.
    master_file = Path(master_file).resolve()
    prepared = prepare(master_file, jd)
    groups = _selected_groups(prepared[0], prepared[1])
    if any(e['merge_allowed'] for e in groups):
        return _generate_composed(client, master_file, jd, job_id, output_dir,
                                  prepared=prepared, groups=groups)
    return _generate_legacy(client, master_file, jd, job_id, output_dir, prepared=prepared)
