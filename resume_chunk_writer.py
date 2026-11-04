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

chunk-v0.6 (still one API call, same generate() signature):
- The model first names what the role values (jd_focus) and rewrites each
  bullet to lead with the matching part, using only facts in the source.
- Wording rules are looser (equivalent leading verbs, up to 6 new words), while
  numbers, named tools, qualifiers, impact claims (improve/optimize/scalable...)
  and ownership escalation (led/managed/owned...) stay strictly checked. New
  words are listed in the report under "Wording to double-check".
- Bullets within an entry render in relevance order; skills lines are reordered
  (same items) so JD-relevant skills come first.
- The model asks up to 5 fact_questions for missing numbers/results instead of
  inventing them; answers belong in the master resume.
- Writer model defaults to gpt-5.4 (JOB_AGENT_WRITER_MODEL overrides), with one
  retry on gpt-5.4-mini if the default model is unavailable.
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
                             render_selected_docx, select_chunks, split_skill_line)

# v0.6: the writing step uses the stronger model by default. Override with the
# JOB_AGENT_WRITER_MODEL environment variable; if the default model is not
# available on the account, the call is retried once with FALLBACK_MODEL.
MODEL = os.environ.get('JOB_AGENT_WRITER_MODEL', 'gpt-5.4')
FALLBACK_MODEL = 'gpt-5.4-mini'


def _model_unavailable(exc: Exception) -> bool:
    name = type(exc).__name__
    text = str(exc).casefold()
    return name in {'NotFoundError', 'PermissionDeniedError'} or (
        'model' in text and any(s in text for s in ('not found', 'does not exist', 'not have access')))


def _create_response(client, **kwargs) -> tuple[object, str]:
    """One model call; on an unavailable default model, retry once with the fallback."""
    try:
        return client.responses.create(model=MODEL, **kwargs), MODEL
    except Exception as exc:
        if MODEL == FALLBACK_MODEL or not _model_unavailable(exc):
            raise
    return client.responses.create(model=FALLBACK_MODEL, **kwargs), FALLBACK_MODEL
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
# v0.6: base/-ing/noun forms of impact words are listed too ("improve data quality"
# was not caught when only "improved" was listed), since wording rules are looser.
STRONG_CLAIMS = {
    'production', 'deployed', 'launched', 'released', 'shipped', 'scalable',
    'improved', 'increased', 'reduced', 'accelerated', 'outperformed',
    'led', 'owned', 'architected', 'trained', 'optimized', 'fine-tuned',
    'cloud', 'distributed', 'revenue', 'users', 'real-time', 'end-to-end',
    'database', 'postgresql', 'sql', 'react', 'typescript', 'c++', 'aws',
    'improve', 'improves', 'improving', 'improvement', 'improvements',
    'increase', 'increasing', 'reduce', 'reducing', 'reduction',
    'optimize', 'optimizing', 'optimization', 'deploy', 'deploying', 'deployment',
    'scaling', 'scalability', 'production-ready', 'boosted', 'enhanced', 'enhancing',
    'efficient', 'efficiency', 'robust', 'reliable', 'reliability',
    'high-performance', 'faster', 'spearheaded', 'pioneered',
}
WRITER_VERSION = 'chunk-v0.6'
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

# v0.6: a leading verb may change only within the same group (same kind and
# strength of action) or to a verb already used later in the same source bullet
# ("Processed ..., filtering ..." -> "Filtered ...").
VERB_GROUPS = (
    {'developed', 'built', 'implemented', 'created', 'engineered', 'wrote', 'coded', 'programmed'},
    {'analyzed', 'evaluated', 'assessed', 'examined', 'compared', 'benchmarked', 'measured'},
    {'investigated', 'researched', 'explored', 'studied'},
    {'processed', 'cleaned', 'filtered', 'transformed', 'preprocessed', 'prepared', 'parsed', 'extracted'},
    {'integrated', 'connected', 'incorporated'},
    {'automated', 'scripted'},
    {'coordinated', 'organized', 'arranged', 'scheduled'},
    {'presented', 'visualized', 'reported', 'documented'},
)
# Verbs that claim leadership/ownership; never introduced unless already in the source.
ESCALATING_VERBS = {'led', 'lead', 'headed', 'directed', 'spearheaded', 'managed', 'owned',
                    'architected', 'pioneered', 'founded', 'launched', 'oversaw', 'supervised'}
MAX_NOVEL_WORDS = 6          # hard cap per rewritten bullet (was 2 before v0.6)
MAX_NOVEL_WORDS_MERGE = 6
MIN_RETAINED = .45           # share of the source's content words kept (was .55)


def _stem(word: str) -> str:
    word = word.casefold()
    for suffix in ('ing', 'ed', 'es', 's', 'e'):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            return word[:-len(suffix)]
    return word


def verbs_equivalent(old: str, new: str) -> bool:
    old, new = old.casefold(), new.casefold()
    return old == new or any(old in g and new in g for g in VERB_GROUPS)


def verb_change_issue(source: str, old: str, new: str) -> str | None:
    """None if replacing leading verb `old` with `new` keeps the same claim."""
    old, new = old.casefold(), new.casefold()
    if old == new:
        return None
    if old in LIMITED_OWNERSHIP_VERBS:
        return f'limited-ownership verb changed: {old} -> {new}'
    source_stems = {_stem(w) for w in _words(source)}
    if new in ESCALATING_VERBS and _stem(new) not in source_stems:
        return f'leading verb escalates ownership: {old} -> {new}'
    if verbs_equivalent(old, new) or _stem(new) in source_stems:
        return None
    return f'leading verb changed to a non-equivalent verb: {old} -> {new}'


_ESCALATING_STEMS = {_stem(v) for v in ESCALATING_VERBS}


def escalations(source: str, candidate: str) -> list[str]:
    """Leadership/ownership words (led, managing, oversaw...) not backed by the source."""
    src = {_stem(w) for w in _words(source)}
    return sorted({w for w in _words(candidate) if _stem(w) in _ESCALATING_STEMS and _stem(w) not in src})


def novel_terms(source: str, candidate: str) -> list[str]:
    """Content words in the rewrite that do not come from the source (for human review)."""
    src_stems = {_stem(w) for w in _words(source)}
    return sorted(w for w in _words(candidate) - _words(source) - SAFE_WORDS
                  if _stem(w) not in src_stems)


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
    # v0.6: an equivalent verb (Developed -> Built) or one already in the source is
    # allowed; ownership-limited or escalating verb changes are not.
    old_first = WORD_RE.search(source)
    new_first = WORD_RE.search(target)
    if old_first and new_first:
        problem = verb_change_issue(source, old_first.group(), new_first.group())
        if problem:
            issues.append(problem)
    src_lower, dst_lower = source.casefold(), target.casefold()
    for phrase in QUALIFIERS:
        if re.search(r'\b' + re.escape(phrase) + r'\b', src_lower) and not re.search(r'\b' + re.escape(phrase) + r'\b', dst_lower):
            issues.append('removed limiting qualifier: ' + phrase)
    for word in _new_strong_claims(source, target):
        issues.append('unsupported strong claim: ' + word)
    for word in escalations(source, target):
        if word not in STRONG_CLAIMS:
            issues.append('unsupported ownership claim: ' + word)
    new_terms = novel_terms(source, target)
    if len(new_terms) > MAX_NOVEL_WORDS:
        issues.append('too many novel content words: ' + ', '.join(new_terms[:8]))
    source_terms = {_stem(t) for t in _words(source) if len(t) >= 4 and t not in SAFE_WORDS}
    retained = source_terms & {_stem(t) for t in _words(target)}
    if source_terms and len(retained) / len(source_terms) < MIN_RETAINED:
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
    # v0.6: entries in resume order; within an entry keep the relevance order and
    # put refilled original bullets last.
    entry_position = {e['id']: i for i, e in enumerate(master['entries'])}
    rows.sort(key=lambda r: entry_position[r['entry_id']])
    after = used(rows)
    return rows, {'budget_pt': round(budget, 1), 'used_before_fit_pt': round(before, 1),
                  'used_pt': round(after, 1), 'remaining_pt': round(budget - after, 1),
                  'line_pt': plan.get('line_pt', 12.65), 'values': values,
                  'jd_signal_weak': plan.get('jd_signal_weak', False),
                  'refilled': refilled, 'dropped_for_space': [r['anchor_id'] for r in dropped]}


def reorder_skills(master: dict, jd: str, jd_focus: list[str] | None = None) -> dict[int, str]:
    """v0.6: within each skills line, move items the JD asks for to the front.

    Pure reordering (validated again by the renderer); lines with no technical
    items, such as spoken languages, are left alone.
    """
    jd_text = jd + '\n' + '\n'.join(jd_focus or [])
    jd_skills = detect_skills(jd_text)
    low = jd_text.casefold()

    def relevant(item: str) -> bool:
        if detect_skills(item) & jd_skills:
            return True
        name = item.casefold()
        return len(name) > 2 and re.search(r'(?<![a-z0-9])' + re.escape(name) + r'(?![a-z0-9+#])', low) is not None

    changes: dict[int, str] = {}
    for line in master.get('skills', []):
        label, items = split_skill_line(line['text'])
        if len(items) < 2 or not any(detect_skills(i) for i in items):
            continue
        ordered = sorted(items, key=lambda i: not relevant(i))  # stable
        if ordered != items:
            changes[line['paragraph']] = (f'{label}: ' if label else '') + ', '.join(ordered)
    return changes


def _render_fitted(master_file: Path, master: dict, selection: dict, rows: list[dict],
                   docx: Path, values: dict,
                   skill_lines: dict[int, str] | None = None) -> tuple[list[dict], dict, list[dict], dict]:
    """Render; when Word/LibreOffice is available and the result exceeds one page,
    drop the lowest-value bullet and re-render (at most MAX_RENDER_TRIMS times).
    v0.6: bullets render in the order of `rows` (relevance order within an entry)."""
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
        render_selected_docx(master_file, master, final, docx, bullet_replacements=replacements,
                             bullet_order=_chosen_from_rows(rows), skill_lines=skill_lines)
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
    response, _ = _create_response(
        client, instructions=INSTRUCTIONS,
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
            # v0.6: what the role values most, and questions for the applicant.
            'jd_focus': {'type': 'array', 'items': {'type': 'string'}},
            'fact_questions': {'type': 'array', 'items': {
                'type': 'object', 'additionalProperties': False,
                'properties': {'bullet_id': {'type': 'string'}, 'question': {'type': 'string'}},
                'required': ['bullet_id', 'question']}},
        },
        'required': ['jd_focus', 'entries', 'review_notes', 'fact_questions'],
    },
}
COMPOSE_INSTRUCTIONS = """You are a senior technical-resume editor tailoring a one-page resume to one job.
Return exactly the JSON schema. The job description tells you what to EMPHASIZE;
it is never evidence that the applicant has a skill or experience.

STEP 1 - jd_focus. Read the job description and write 3 to 5 short phrases naming
what this role values most (e.g. "data analysis to back decisions", "systems
programming", "shipping user-facing features"). Look past company boilerplate,
benefits and EEO text. Use these phrases to guide every edit below.

STEP 2 - rewrite. You receive source_entries; each has an immutable entry_id, a
merge_allowed flag and selected bullets with immutable bullet_id values. Every
bullet ID must appear exactly once in your output. Never invent, drop, swap or
duplicate IDs, or combine bullets from different entries.

Rewrite each bullet so a reviewer for THIS role sees the most relevant part first:
- Lead with the part of the source that best matches jd_focus (the data work, the
  system built, the measurable result), then the supporting detail.
- Prefer the source's concrete numbers, tools and outcomes over generic wording;
  cut filler ("various", "in order to", "related", "to support").
- Keep the leading verb, or replace it with an equivalent verb of the same strength
  (Developed -> Built/Implemented; Analyzed -> Evaluated) or with an action already
  described later in the same bullet (", filtering ..." -> "Filtered ...").
  Never strengthen ownership: no Led, Managed, Owned, Architected, Spearheaded
  unless the source says so. Keep Assisted / Supported / Contributed exactly.
- Keep every number, named tool/language, qualifier (only, under mentor guidance,
  planned, in progress, currently) and every distinct fact.
- Do NOT add impact or quality claims that are not in the source: no improved,
  increased, reduced, optimized, efficient, scalable, robust, production, users,
  real-time, end-to-end. If a bullet would be stronger with a result the source
  lacks, ask for it in fact_questions instead of writing it.
- About 1 to 2 printed lines per bullet; do not make bullets much longer.
- Keep a bullet unchanged only if it already leads with what matters for this role.

STEP 3 - merges. For entries with merge_allowed=true, merge TWO bullets of the
same entry into one only when they describe overlapping parts of the same work,
every distinct fact from both survives, and the result is clearly shorter. Never
merge a bullet whose merge_eligible is false. Every action verb must stay attached
to the work it described. Never merge more than two sources. For entries with
merge_allowed=false return exactly one group per bullet.

STEP 4 - order. Within each entry, return groups from MOST to LEAST relevant to
jd_focus. Entry order is fixed by the resume and does not matter in your output.

STEP 5 - fact_questions. Up to 5 short questions to the applicant, each tied to one
bullet_id, asking for a specific missing fact that would make that bullet stronger
for this role (a number, scale, result, or what they personally built). Ask only
for facts that plausibly exist; never suggest an answer.

review_notes: only ambiguities a person must check. Do not alter company names,
titles, dates, header, education or skills.

Illustrative example (NOT applicant data). Role values data analysis:
Source: 'Developed a dashboard using Python and Tableau to display weekly sales data
for 12 stores.'
Good: 'Built a Python and Tableau dashboard tracking weekly sales across 12 stores.'
Bad: 'Built a scalable dashboard that improved sales visibility for 12 stores.'
(adds unsupported "scalable" and "improved")
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
    for word in escalations(original, text):
        if word not in STRONG_CLAIMS:
            issues.append('unsupported ownership claim: ' + word)
    added = novel_terms(original, text)
    if len(added) > MAX_NOVEL_WORDS_MERGE:
        issues.append('excessive new content words: ' + ', '.join(added[:8]))
    for i, source in enumerate(sources, 1):
        terms = _meaningful_terms(source)
        if terms and len(new & terms) / len(terms) < .37:
            issues.append(f'insufficient evidence retained from source {i}')
    pooled = _meaningful_terms(original)
    if pooled and len(new & pooled) / len(pooled) < .56:
        issues.append('too much combined evidence removed')
    # v0.4.1: BOTH original action verbs must survive (was: any one of them).
    # v0.6: an equivalent verb counts (Developed -> Built), except for
    # ownership-limited verbs, which never reach here (merge_blockers).
    verbs = [m.group().casefold() for m in (WORD_RE.search(s) for s in sources) if m]
    lost = [v for v in verbs if not any(verbs_equivalent(v, w) for w in new)]
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


def compose(client, jd: str, entries: list[dict]) -> tuple[list[dict], list[str], list[str], dict[str, int], dict]:
    """One API call. Check provenance before accepting *any* structural edits.

    Unknown or cross-entry IDs abort before writing (provenance is broken).
    v0.4.1: an entry whose groups are otherwise malformed (omitted/duplicate IDs,
    illegal merge) falls back to its original bullets. If a proposed merge is
    unsafe, that pair reverts to originals.
    v0.6: groups keep the model's within-entry order (most relevant first); also
    returns extras = {'jd_focus', 'fact_questions', 'model'}.
    """
    request = {
        'job_description': jd[:14000],
        'source_entries': [
            {'entry_id': e['entry_id'], 'entry_title': e['entry_title'],
             'merge_allowed': e['merge_allowed'],
             'bullets': [{'bullet_id': b['bullet_id'], 'text': b['text'],
                          'merge_eligible': b['merge_eligible']} for b in e['bullets']]}
            for e in entries
        ],
    }
    response, model_used = _create_response(
        client, instructions=COMPOSE_INSTRUCTIONS,
        input=json.dumps(request, ensure_ascii=False),
        text={'format': COMPOSE_SCHEMA}, max_output_tokens=6000, store=False,
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
        # v0.6: keep the model's order (most relevant to the JD first).
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
    # Entries in resume order; within an entry, the model's relevance order is kept
    # (stable sort). Fallback entries keep their original Word order.
    entry_position = {e['entry_id']: i for i, e in enumerate(entries)}
    outputs.sort(key=lambda row: entry_position[row['entry_id']])
    covered = [x for row in outputs for x in row['source_ids']]
    if sorted(covered) != sorted(owner):
        raise AssertionError('Composition output does not cover every selected bullet exactly once.')
    notes = [x[:300] for x in payload['review_notes'][:10] if isinstance(x, str) and x.strip()]
    extras = {'model': model_used,
              'jd_focus': [x.strip()[:120] for x in (payload.get('jd_focus') or [])[:5]
                           if isinstance(x, str) and x.strip()],
              'fact_questions': [
                  {'bullet_id': q['bullet_id'], 'question': q['question'].strip()[:300]}
                  for q in (payload.get('fact_questions') or [])[:5]
                  if isinstance(q, dict) and q.get('bullet_id') in owner
                  and isinstance(q.get('question'), str) and q['question'].strip()]}
    return outputs, warnings, notes, dict(stats), extras


def _generate_composed(client, master_file: Path, jd: str, job_id: str, output_dir: Path,
                       prepared: tuple | None = None, groups: list[dict] | None = None) -> dict[str, Path | int]:
    """Review-only, provenance-tracked composition; use legacy Word renderer."""
    if not re.fullmatch(r'\d+', job_id) or len(jd.strip()) < 30:
        raise ValueError('Invalid job ID or incomplete JD.')
    master_file = Path(master_file).resolve()
    prepared = prepared or prepare(master_file, jd)
    master, selection, selected_bullets = prepared
    groups = groups if groups is not None else _selected_groups(master, selection)
    # v0.6: always this path (one call); entries without merge_allowed get
    # one-to-one JD-aware rewrites, so the old polish-only path is not needed.
    source_digest = hashlib.sha256(master_file.read_bytes()).hexdigest()
    composed, warnings, notes, counts, extras = compose(client, jd, groups)
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
    skill_lines = reorder_skills(master, jd, extras['jd_focus'])
    composed, final_selection, removed, check = _render_fitted(master_file, master, selection, composed, docx,
                                                               values, skill_lines=skill_lines)
    final_selection['writer_v06'] = {
        'version': WRITER_VERSION, 'model': extras['model'], 'jd_focus': extras['jd_focus'],
        'fact_questions': extras['fact_questions'],
        'skills_reordered': {str(k): v for k, v in skill_lines.items()},
        'bullet_order': _chosen_from_rows(composed)}
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
    index_text = {bid: b['text'] for bid, b in index.items()}
    to_check = []
    for row in composed:
        if row['status'] in ('rewritten', 'merged'):
            source = ' '.join(index_text[b] for b in row['source_ids'])
            terms = novel_terms(source, row['text'])
            if terms:
                to_check.append(f'{row["text"]}  \n  New wording: {", ".join(terms)}')
    lines = [
        f'# Chunk-tailored resume — {WRITER_VERSION} (human review required)', '',
        f'- Job ID: `{job_id}`',
        f'- Master source: `{master_file.name}` (SHA256: `{source_digest}`)',
        f'- Model: `{extras["model"]}`; selected source bullets: {original_selected}; final Word bullets: {len(composed)}',
        f'- Proposed merges: {counts.get("proposed_merges",0)}; accepted merges: {counts.get("accepted_merges",0)}; rejected merges: {counts.get("rejected_merges",0)}',
        f'- Rewritten singles: {counts.get("rewritten",0)}; unchanged singles: {counts.get("unchanged",0)}; rejected singles: {counts.get("rejected_rewrites",0)}',
        f'- Entry fallbacks (malformed model output, originals kept): {counts.get("entry_fallbacks",0)}',
        f'- Estimated Word lines saved by merges: {lines_saved} (at {CHARS_PER_LINE} chars/line; confirm in Word)',
        '- Company, title, dates, education and header remain copied from Master; '
        'skills lines are only reordered (same items).',
        '- Bullets within each entry are ordered by relevance to this role.',
        '- No automatic job application; all candidate claims require human review.', '',
        '## What this role values (model reading of the JD)', '',
        *(['- ' + x for x in extras['jd_focus']] or ['- (none returned)']), '',
        '## Questions to strengthen your master resume', '',
        'Answer these in `Resume_*.docx` if true; the next draft can then use the facts.', '',
        *([f'- {q["question"]}  \n  Bullet: {index_text[q["bullet_id"]]}' for q in extras['fact_questions']]
          or ['- None']), '',
        '## Wording to double-check', '',
        'Words below are not in the source bullet. They passed the automatic checks, '
        'but confirm each one is accurate.', '',
        *(['- ' + x for x in to_check] or ['- None']), '',
        *(['## Skills reordered for this role', '', *[f'- {t}' for t in skill_lines.values()], '']
          if skill_lines else []),
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
            'page_count': check['pages'], 'page_check': check['backend'],
            'model': extras['model'], 'fact_questions': len(extras['fact_questions'])}


def generate(client, master_file: Path, jd: str, job_id: str,
             output_dir: Path) -> dict[str, Path | int]:
    """chunk-v0.6: one JD-aware composition call for every draft."""
    # prepare() has no API cost; v0.4.1 runs it once and passes the result on.
    master_file = Path(master_file).resolve()
    prepared = prepare(master_file, jd)
    groups = _selected_groups(prepared[0], prepared[1])
    return _generate_composed(client, master_file, jd, job_id, output_dir,
                              prepared=prepared, groups=groups)
