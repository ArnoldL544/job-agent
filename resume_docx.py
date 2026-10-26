"""按用户提供的 resume-template.docx 输出 Word 简历。

需要 python-docx：python -m pip install python-docx
原模板仅提供版式及已填写的个人基本信息；不会复制经历示例。
"""

from copy import deepcopy
from io import BytesIO
from pathlib import Path
import re

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_TAB_ALIGNMENT
from docx.shared import Pt, RGBColor
from docx.text.paragraph import Paragraph


def _text(value):
    return " ".join(value.split())


def _unbracket(value):
    return re.sub(r"\[\s*(.*?)\s*\]", r"\1", value).strip()


def _read_template(template_path):
    document = Document(template_path)
    paragraphs = document.paragraphs
    # 这份导出器对应本次用户提供的模板；避免错用另一种模板后替换错位置。
    expected = {3: "EDUCATION", 11: "EXPERIENCE", 29: "CAMPUS LEADERSHIP ACTIVITIES", 40: "SKILLS"}
    if len(paragraphs) < 44 or any(paragraphs[i].text.strip() != label for i, label in expected.items()):
        raise ValueError("模板结构已变化，请使用配套的 resume-template.docx。")
    return document


def template_context(template_path):
    """只读取模板中已填写的抬头和教育信息，不把实习/项目示例当事实。"""
    document = _read_template(template_path)
    paragraphs = document.paragraphs
    return "\n".join([
        "当前简历模板中提供的基本信息（用于姓名、联系方式及教育栏）：",
        _unbracket(paragraphs[0].text),
        _unbracket(paragraphs[1].text),
        _unbracket(paragraphs[4].text),
        _unbracket(paragraphs[5].text),
        _unbracket(paragraphs[7].text),
    ])


def save_template_resume(data, template_path, output_path):
    """data 必须为 resume_writer 检查引用后返回的内容；不附带中文核对说明。"""
    if len(data["entries"]) > 3 or len(data.get("activities", [])) > 1:
        raise ValueError("模板版最多容纳三段实习/项目与一段校园活动。")
    document = _read_template(template_path)
    paragraphs = document.paragraphs
    prototypes = {i: deepcopy(paragraphs[i]._p) for i in [0, 1, 3, 4, 5, 7, 12, 13, 14, 30, 31, 32, 41]}
    header_name = _unbracket(paragraphs[0].text)
    header_contact = _unbracket(paragraphs[1].text)
    education = [_unbracket(paragraphs[i].text) for i in [4, 5, 7]]

    body = document._element.body
    for child in list(body):
        if child is not body.sectPr:
            body.remove(child)
    section = document.sections[0]
    width = section.page_width - section.left_margin - section.right_margin

    def paragraph(index, text, bold=False, italic=False, size=11, before=0, after=0, keep=False):
        node = deepcopy(prototypes[index])
        for child in list(node):
            if child.tag.rsplit("}", 1)[-1] != "pPr":
                node.remove(child)
        body.insert(len(body) - 1, node)
        p = Paragraph(node, document._body)
        fmt = p.paragraph_format
        fmt.space_before = Pt(before)
        fmt.space_after = Pt(after)
        fmt.line_spacing = 1.0
        fmt.keep_with_next = False
        fmt.keep_together = False
        fmt.tab_stops.clear_all()
        fmt.tab_stops.add_tab_stop(width, WD_TAB_ALIGNMENT.RIGHT)
        run = p.add_run(text)
        run.font.name = "Times New Roman"
        run.font.size = Pt(size)
        run.font.color.rgb = RGBColor(0, 0, 0)
        run.bold = bold
        run.italic = italic
        return p

    def heading(label):
        paragraph(3, label, bold=True, size=12, before=9, after=3, keep=True)

    def pair(index, left, right, **options):
        left, right = _text(left), _text(right)
        return paragraph(index, left + ("\t" + right if right else ""), **options)

    def bullet(text, keep=False):
        p = paragraph(14, _text(text), after=3, keep=keep)
        p.paragraph_format.left_indent = Pt(14)
        p.paragraph_format.first_line_indent = Pt(-14)
        return p

    # 抬头与教育基本信息来自用户实际填写的模板，可直接在模板中更新。
    paragraph(0, header_name, bold=True, size=18, after=2, keep=True).alignment = WD_ALIGN_PARAGRAPH.CENTER
    paragraph(1, header_contact, after=2, keep=True).alignment = WD_ALIGN_PARAGRAPH.CENTER
    heading("EDUCATION")
    for index, value in enumerate(education[:2]):
        left, _, right = value.partition("\t")
        pair(4 if index == 0 else 5, left, right, bold=index == 0, italic=index == 1, keep=True)
    if education[2]:
        bullet(education[2])

    def add_entry(entry, index):
        pair(12, entry["title"], entry.get("location", ""), bold=True, before=5 if index else 0, keep=True)
        pair(13, entry.get("role", ""), entry["dates"], italic=True, after=2, keep=True)
        for i, item in enumerate(entry["bullets"]):
            bullet(item["text"], keep=i < len(entry["bullets"]) - 1)

    # 模板的 EXPERIENCE 栏同时容纳实习与相关项目，保持原栏目顺序。
    heading("EXPERIENCE")
    for index, entry in enumerate(data["entries"]):
        add_entry(entry, index)

    if data.get("activities"):
        heading("CAMPUS LEADERSHIP ACTIVITIES")
        for index, entry in enumerate(data["activities"]):
            add_entry(entry, index)

    if data["skills"]:
        heading("SKILLS")
        bullet("Technical: " + ", ".join(item["name"] for item in data["skills"]))

    # 生成新的文件，不修改模板；清除模板原来的作者等文档属性。
    document.core_properties.title = "Resume"
    document.core_properties.author = header_name
    document.core_properties.last_modified_by = header_name
    document.core_properties.subject = ""
    document.core_properties.comments = ""
    stream = BytesIO()
    document.save(stream)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("xb") as output:
        output.write(stream.getvalue())
    return output_path
