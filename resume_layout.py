"""chunk-v0.5 page-space model for the master resume template.

Estimates how much vertical space (in points) each paragraph of the master will
take, so the selector can fill one page instead of using a fixed bullet count.

Calibrated against a real render of Resume_Arnold Li.docx:
- body font Cambria 11pt (theme font), single spacing -> 12.65pt per line;
- bullet text box ~482pt wide; section headings ~15.5pt incl. bottom border.
Character widths below are Caladea's, which is metric-compatible with Cambria,
so the word-wrap simulation needs no font files on the user's computer.

count_pages() optionally confirms the real page count with Microsoft Word
(pywin32) or LibreOffice. It never edits the master and returns None when no
renderer is available.
"""
from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess
import tempfile

# Advance widths in em (Caladea == Cambria metrics), ASCII 32..126 plus a few.
_CHARS = (' !"#$%&\'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`'
          'abcdefghijklmnopqrstuvwxyz{|}~–—•’“”é')
_WIDTHS = [0.22, 0.286, 0.393, 0.619, 0.506, 0.89, 0.687, 0.237, 0.382, 0.382, 0.427, 0.554,
           0.205, 0.329, 0.206, 0.49, 0.517, 0.362, 0.472, 0.461, 0.492, 0.475, 0.47, 0.47,
           0.485, 0.478, 0.264, 0.264, 0.554, 0.554, 0.554, 0.422, 0.885, 0.599, 0.579, 0.519,
           0.625, 0.54, 0.509, 0.539, 0.696, 0.343, 0.304, 0.63, 0.501, 0.888, 0.693, 0.599,
           0.533, 0.599, 0.613, 0.453, 0.557, 0.687, 0.598, 0.889, 0.571, 0.557, 0.507, 0.35,
           0.49, 0.35, 0.554, 0.371, 0.151, 0.47, 0.52, 0.421, 0.52, 0.441, 0.313, 0.459, 0.554,
           0.277, 0.255, 0.525, 0.271, 0.813, 0.558, 0.48, 0.52, 0.501, 0.396, 0.392, 0.325,
           0.546, 0.47, 0.72, 0.483, 0.482, 0.428, 0.387, 0.316, 0.387, 0.712, 0.5, 1.0, 0.443,
           0.221, 0.375, 0.375, 0.441]
CHAR_EM = dict(zip(_CHARS, _WIDTHS))
DEFAULT_EM = 0.52            # unknown glyphs (CJK etc.): slightly wide on purpose

LINE_FACTOR = 1.15           # measured 12.65pt pitch at 11pt
BULLET_INDENT_PT = 22.0      # bullet text starts ~22pt right of the margin
BORDER_PAD_PT = 1.7          # section headings carry a bottom border
SAFETY_PT = 10.0             # keep ~0.8 line spare for estimate error
ENTRY_GAP_FIRST_PT = 2.0     # render_selected_docx: first entry in a section
ENTRY_GAP_NEXT_PT = 7.0      # render_selected_docx: following entries

_BREAK_TOKENS = re.compile(r'\s+|[^\s\-—/]*[\-—/]|[^\s\-—/]+')


def text_width_pt(text: str, size: float) -> float:
    return sum(CHAR_EM.get(ch, DEFAULT_EM) for ch in text) * size


def wrap_line_count(text: str, width_pt: float, size: float = 11.0) -> int:
    """Greedy word wrap like Word: break at spaces and after - — / ."""
    text = ' '.join(text.split())
    if not text:
        return 1
    lines, current, pending = 1, 0.0, 0.0
    for token in _BREAK_TOKENS.findall(text):
        width = text_width_pt(token, size)
        if token.isspace():
            pending += width
            continue
        if current > 0 and current + pending + width > width_pt:
            lines += 1
            current = width
        else:
            current += pending + width
        pending = 0.0
    return lines


def _doc_default_size(document) -> float:
    try:
        ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
        sz = document.styles.element.find(f'{ns}docDefaults/{ns}rPrDefault/{ns}rPr/{ns}sz')
        return int(sz.get(f'{ns}val')) / 2.0
    except Exception:
        return 12.0


def _is_bullet(paragraph) -> bool:
    name = paragraph.style.name.lower() if paragraph.style is not None else ''
    if 'list' in name:
        return True
    ppr = paragraph._p.pPr
    return ppr is not None and ppr.numPr is not None


def _has_bottom_border(paragraph) -> bool:
    ppr = paragraph._p.pPr
    if ppr is None:
        return False
    ns = '{http://schemas.openxmlformats.org/wordprocessingml/2006/main}'
    return ppr.find(f'{ns}pBdr') is not None


def _spacing(paragraph, attr: str) -> float:
    value = getattr(paragraph.paragraph_format, attr)
    if value is None and paragraph.style is not None:
        value = getattr(paragraph.style.paragraph_format, attr)
    return value.pt if value is not None else 0.0


class PageModel:
    """Vertical-space estimates for one master DOCX (letter page, one column)."""

    def __init__(self, master_file: str | Path, master: dict):
        from docx import Document
        self.document = Document(str(master_file))
        section = self.document.sections[0]
        self.usable_pt = (section.page_height - section.top_margin - section.bottom_margin) / 12700
        self.text_width_pt = (section.page_width - section.left_margin - section.right_margin) / 12700
        self.default_size = _doc_default_size(self.document)
        self.paragraphs = self.document.paragraphs
        self.master = master
        self.heading_pt = {h['section']: self.paragraph_pt(h['paragraph'])
                           for h in master.get('section_headings', [])}
        self.fixed_pt = self._fixed_pt()

    # -- paragraph level -------------------------------------------------
    def _size(self, paragraph) -> float:
        sizes = [r.font.size.pt for r in paragraph.runs if r.font.size is not None and r.text.strip()]
        if sizes:
            return max(sizes)
        if paragraph.style is not None and paragraph.style.font.size is not None:
            return paragraph.style.font.size.pt
        return self.default_size

    def _info(self, index: int) -> tuple:
        """Static formatting of one paragraph (style lookups are slow; cache them)."""
        cache = self.__dict__.setdefault('_info_cache', {})
        if index not in cache:
            p = self.paragraphs[index]
            cache[index] = (self._size(p), _is_bullet(p), p.text,
                            _spacing(p, 'space_before') + _spacing(p, 'space_after'),
                            BORDER_PAD_PT if _has_bottom_border(p) else 0.0)
        return cache[index]

    def paragraph_pt(self, index: int, text: str | None = None) -> float:
        size, bullet, own_text, spacing, border = self._info(index)
        body = own_text if text is None else text
        if '\t' in body:
            lines = 1  # title/role rows: left text + right-aligned tab stop
        else:
            width = self.text_width_pt - (BULLET_INDENT_PT if bullet else 0.0)
            lines = wrap_line_count(body, width, size)
        return lines * size * LINE_FACTOR + spacing + border

    # -- resume level ----------------------------------------------------
    def _fixed_pt(self) -> float:
        """Header, education and skills: always kept; empty paragraphs are removed on render."""
        master = self.master
        indices = [h['paragraph'] for h in master['header']]
        for block in ('education', 'skills'):
            indices += [x['paragraph'] for x in master[block]]
        indices += [h['paragraph'] for h in master['section_headings'] if h['section'] in ('education', 'skills')]
        return sum(self.paragraph_pt(i) for i in indices if self.paragraphs[i].text.strip())

    def entry_open_pt(self, entry: dict, first_in_section: bool) -> float:
        height = ENTRY_GAP_FIRST_PT if first_in_section else ENTRY_GAP_NEXT_PT
        # render_selected_docx overwrites the title's space_before with the gap above.
        height += self.paragraph_pt(entry['title_paragraph'])
        height -= self.__dict__.setdefault('_title_sb', {}).setdefault(
            entry['title_paragraph'], _spacing(self.paragraphs[entry['title_paragraph']], 'space_before'))
        if entry.get('role_paragraph') is not None:
            height += self.paragraph_pt(entry['role_paragraph'])
        return height

    def bullet_pt(self, bullet: dict, text: str | None = None) -> float:
        return self.paragraph_pt(bullet['paragraph'], text)

    def budget_pt(self) -> float:
        return self.usable_pt - self.fixed_pt - SAFETY_PT

    def plan_pt(self, chosen: dict[str, list[tuple[dict, str]]]) -> float:
        """Variable height of a plan: {entry_id: [(bullet, final_text), ...]}."""
        entries = {e['id']: e for e in self.master['entries']}
        total, open_sections = 0.0, set()
        for entry in self.master['entries']:  # master order == render order
            rows = chosen.get(entry['id'])
            if not rows:
                continue
            section = entry['source_section']
            if section not in open_sections:
                total += self.heading_pt.get(section, 0.0)
            total += self.entry_open_pt(entries[entry['id']], section not in open_sections)
            open_sections.add(section)
            total += sum(self.bullet_pt(b, t) for b, t in rows)
        return total

    def rendered_estimate_pt(self, docx_path: str | Path) -> float:
        """Estimate the total content height of an already rendered DOCX."""
        from docx import Document
        doc = Document(str(docx_path))
        saved, saved_cache = self.paragraphs, self.__dict__.pop('_info_cache', {})
        try:
            self.paragraphs = doc.paragraphs
            return sum(self.paragraph_pt(i) for i, p in enumerate(doc.paragraphs) if p.text.strip())
        finally:
            self.paragraphs, self._info_cache = saved, saved_cache


# -- optional real page count ---------------------------------------------
def _count_pdf_pages(pdf: Path) -> int:
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(pdf)).pages)
    except ImportError:
        return len(re.findall(rb'/Type\s*/Page(?![a-zA-Z])', pdf.read_bytes()))


def _pages_with_word(docx: Path) -> int | None:
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        return None
    pythoncom.CoInitialize()
    word = doc = None
    try:
        word = win32com.client.DispatchEx('Word.Application')  # separate hidden instance
        word.Visible = False
        word.DisplayAlerts = 0
        doc = word.Documents.Open(str(docx.resolve()), ReadOnly=True, AddToRecentFiles=False, Visible=False)
        doc.Repaginate()
        return int(doc.ComputeStatistics(2))  # wdStatisticPages
    except Exception:
        return None
    finally:
        try:
            if doc is not None:
                doc.Close(False)
            if word is not None:
                word.Quit()
        finally:
            pythoncom.CoUninitialize()


def _pages_with_libreoffice(docx: Path) -> int | None:
    exe = shutil.which('soffice') or shutil.which('libreoffice')
    for guess in (r'C:\Program Files\LibreOffice\program\soffice.exe',
                  r'C:\Program Files (x86)\LibreOffice\program\soffice.exe'):
        if not exe and Path(guess).is_file():
            exe = guess
    if not exe:
        return None
    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run([exe, '--headless', '--convert-to', 'pdf', '--outdir', tmp, str(docx)],
                           check=True, capture_output=True, timeout=120)
        except (OSError, subprocess.SubprocessError):
            return None
        pdf = Path(tmp) / (docx.stem + '.pdf')
        return _count_pdf_pages(pdf) if pdf.is_file() else None


def count_pages(docx_path: str | Path) -> tuple[int | None, str]:
    """Return (pages, backend). Word first (exact on Windows), then LibreOffice."""
    docx = Path(docx_path)
    pages = _pages_with_word(docx)
    if pages is not None:
        return pages, 'Microsoft Word'
    pages = _pages_with_libreoffice(docx)
    if pages is not None:
        return pages, 'LibreOffice'
    return None, 'none available'
