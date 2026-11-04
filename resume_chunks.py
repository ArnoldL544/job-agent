"""Extract structured, source-linked resume chunks from a Word master resume.

Only parses user-provided source material. This module never invents claims,
modifies source documents, or calls an LLM.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

SECTION_NAMES = {
    'EDUCATION': 'education',
    'INTERNSHIP': 'internship',
    'INTERNSHIPS': 'internship',
    'WORK EXPERIENCE': 'experience',
    'PROFESSIONAL EXPERIENCE': 'experience',
    'EXPERIENCE': 'experience',
    'PROJECTS': 'projects',
    'TECHNICAL PROJECTS': 'projects',
    'RESEARCH': 'research',
    'RESEARCH EXPERIENCE': 'research',
    'LEADERSHIP': 'leadership',
    'LEADERSHIP ACTIVITIES': 'leadership',
    'HONORS & AWARDS': 'awards',
    'HONORS AND AWARDS': 'awards',
    'AWARDS': 'awards',
    'SKILLS': 'skills',
    'TECHNICAL SKILLS': 'skills',
}
ENTRY_SECTIONS = {'internship', 'experience', 'projects', 'research', 'leadership', 'awards'}
# chunk-v0.5: headings not in SECTION_NAMES (e.g. "CAMPUS LEADERSHIP ACTIVITIES")
# are recognised by keyword when the paragraph is a short ALL-CAPS heading.
# Order matters: "RESEARCH EXPERIENCE" -> research, "HONORS & AWARDS" -> awards.
HEADING_KEYWORDS = (
    ('EDUCATION', 'education'), ('SKILL', 'skills'), ('AWARD', 'awards'), ('HONOR', 'awards'),
    ('LEADERSHIP', 'leadership'), ('ACTIVIT', 'leadership'), ('INVOLVEMENT', 'leadership'),
    ('VOLUNTEER', 'leadership'), ('RESEARCH', 'research'), ('PROJECT', 'projects'),
    ('INTERNSHIP', 'internship'), ('EXPERIENCE', 'experience'), ('EMPLOYMENT', 'experience'),
)


def _section_for_heading(text: str) -> str | None:
    key = re.sub(r'\s+', ' ', text.strip().upper())
    if key in SECTION_NAMES:
        return SECTION_NAMES[key]
    if len(key) > 40 or text.strip() != text.strip().upper() or '\t' in text:
        return None
    for word, section in HEADING_KEYWORDS:
        if word in key:
            return section
    return None


def _stable_id(prefix: str, *values: str) -> str:
    raw = '|'.join(v.strip().casefold() for v in values)
    return f'{prefix}_{hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]}'


def _split_tab_line(line: str) -> tuple[str, str]:
    parts = [p.strip() for p in re.split(r'\t+', line) if p.strip()]
    if len(parts) < 2:
        return (line.strip(), '')
    return (parts[0], parts[-1])


def _looks_bullet(paragraph: Any) -> bool:
    name = paragraph.style.name.lower() if paragraph.style else ''
    if 'list' in name:
        return True
    if paragraph._p.pPr is not None and paragraph._p.pPr.numPr is not None:
        return True
    return bool(re.match(r'^\s*[•\u2022\uf0b7]\s+', paragraph.text))


def parse_docx(path: str | Path) -> dict[str, Any]:
    """Return user-authored source chunks with paragraph indices for safe editing.

    Supports one-paragraph title and role/date headers, including tab-separated
    right-aligned locations. If the template differs, verify the preview first.
    """
    try:
        from docx import Document
    except ImportError as exc:
        raise RuntimeError('Install dependency: python -m pip install python-docx') from exc
    source = Path(path)
    if source.suffix.lower() != '.docx' or not source.is_file():
        raise FileNotFoundError(f'Expected existing .docx file: {source}')
    document = Document(str(source))
    if document.tables:
        raise ValueError('Table-based resume templates are not yet supported; no output was modified.')

    paragraphs = document.paragraphs
    result: dict[str, Any] = {
        'schema_version': 1,
        'source_file': source.name,
        'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'header': [],
        'education': [],
        'skills': [],
        'entries': [],
        'section_headings': [],
        'warnings': [],
    }
    section: str | None = None
    current: dict[str, Any] | None = None
    expecting_role = False
    for i, paragraph in enumerate(paragraphs):
        text = paragraph.text.strip()
        if not text:
            continue
        section_id = _section_for_heading(text)
        if section_id and not _looks_bullet(paragraph):
            if current is not None and not current.get('role'):
                result['warnings'].append(f'Entry lacks role/date near paragraph {current["title_paragraph"]}: {current["title"]}')
            current = None
            expecting_role = False
            section = section_id
            result['section_headings'].append({'section': section, 'paragraph': i, 'text': text})
            continue
        if section is None:
            result['header'].append({'text': text, 'paragraph': i})
        elif section in ('education', 'skills'):
            result[section].append({'text': text, 'paragraph': i, 'is_bullet': _looks_bullet(paragraph)})
        elif section in ENTRY_SECTIONS:
            if _looks_bullet(paragraph):
                if current is None:
                    result['warnings'].append(f'Orphan bullet in {section}, paragraph {i}')
                    continue
                current['bullets'].append({
                    'id': _stable_id('bullet', current['id'], text),
                    'text': text,
                    'paragraph': i,
                    'source': 'master_resume',
                    'verification_status': 'user_provided',
                })
                expecting_role = False
                continue
            if current is not None and expecting_role:
                role, dates = _split_tab_line(text)
                current.update({'role': role, 'dates': dates, 'role_paragraph': i})
                # Different internships at the same employer must get distinct IDs.
                candidate_id = _stable_id('entry', section, current['title'], role, dates)
                existing = {e['id'] for e in result['entries'] if e is not current}
                suffix = 2
                unique_id = candidate_id
                while unique_id in existing:
                    unique_id = f'{candidate_id}_{suffix}'
                    suffix += 1
                current['id'] = unique_id
                expecting_role = False
                if not dates:
                    result['warnings'].append(f'No date extracted for {current["title"]}; check template alignment.')
            else:
                title, location = _split_tab_line(text)
                kind = section
                if section == 'experience':
                    # Wait for role to classify the entry; default is projects.
                    kind = 'projects'
                entry = {
                    'id': _stable_id('entry', section, title),
                    'source_section': section,
                    'kind': kind,
                    'title': title,
                    'location': location,
                    'role': '',
                    'dates': '',
                    'title_paragraph': i,
                    'role_paragraph': None,
                    'bullets': [],
                    'verification_status': 'user_provided',
                }
                result['entries'].append(entry)
                current = entry
                expecting_role = True
        else:
            result['warnings'].append(f'Unrecognized section content at paragraph {i}: {text[:60]}')

    for entry in result['entries']:
        if entry['source_section'] == 'experience':
            if re.search(r'\b(intern|internship|co-op)\b', entry['role'], re.I):
                entry['kind'] = 'internship'
            elif re.search(r'\b(research|researcher)\b', entry['role'], re.I):
                entry['kind'] = 'research'
        if not entry['bullets']:
            result['warnings'].append(f'No bullet text found for {entry["title"]}; review source format.')
    if not result['entries']:
        raise ValueError('No entries extracted. The document may use a template this parser does not support.')
    return result


def export_chunks(master: str | Path, output_json: str | Path) -> dict[str, Any]:
    parsed = parse_docx(master)
    output = Path(output_json)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(parsed, ensure_ascii=False, indent=2), encoding='utf-8')
    return parsed
