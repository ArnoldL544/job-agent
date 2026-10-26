"""Conservative, auditable first-pass screening of saved Handshake job descriptions.

No OpenAI API calls. Does not apply, reject, or modify existing JDs.

Usage:
    python job_screen.py
    python job_screen.py --match "Clark Associates"
    python job_screen.py --dry-run

Reads jobs/handshake_email_jobs.json and each job's latest *_description.txt.
Writes jobs/job_screen_results.json, .csv, and job_screen_report.md.
IMPORTANT: screening is NOT an immigration/work-authorization determination.
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JOBS = ROOT / "jobs"
INDEX = JOBS / "handshake_email_jobs.json"
RESULT_JSON = JOBS / "job_screen_results.json"
RESULT_CSV = JOBS / "job_screen_results.csv"
RESULT_MD = JOBS / "job_screen_report.md"

# Local user preferences. Modify as needed; not an official eligibility determination.
PROFILE = {
    "degree": "Computer Science",
    "target": "Summer 2027 internship / undergraduate software or AI role",
    "planned_work_state": "NY",  # editable assumption; not proof of 2027 residency
    "f1_student": True,
    "authorization_for_future_job_confirmed": False,
}

# Verified experience based on user-provided projects. Edit this list as skills grow.
# An item in a JD is never treated as an existing user skill unless listed here.
DOCUMENTED_EXPERIENCE = {
    "Python", "Data analytics", "AI/ML", "LLM/NLP", "CS fundamentals"
}

# Score job *fit*, not visa eligibility. Keep evidence fields separate.
SKILLS = [
    (r"\bpython\b", "Python", 6),
    (r"\b(sql|postgresql|mysql)\b", "SQL", 5),
    (r"\b(data (analytics|analysis|science|mining))\b", "Data analytics", 6),
    (r"\b(machine learning|deep learning|artificial intelligence|\bai\b|\bml\b)\b", "AI/ML", 7),
    (r"\b(nlp|natural language processing|large language models?|llms?)\b", "LLM/NLP", 7),
    (r"\breact(?:\.js)?\b", "React", 4),
    (r"\btypescript\b", "TypeScript", 4),
    (r"\bjavascript\b", "JavaScript", 4),
    (r"\b(html|css)\b", "HTML/CSS", 3),
    (r"\b(api|apis|backend|back-end|full.?stack)\b", "API/backend", 3),
    (r"\b(c\+\+|java|algorithms?|data structures)\b", "CS fundamentals", 3),
]

TITLE_ROLES = [
    (r"\b(machine learning|ai engineer|ml engineer|research (intern|assistant))\b", 23),
    (r"\b(data (scientist|analyst|engineer)|analytics intern)\b", 20),
    (r"\b(software (engineer|developer|development)|programmer|full.?stack|front.?end|back.?end|web (developer|software))\b", 20),
]

CITIZEN_ONLY = [
    r"\bmust\s+be\s+(?:a\s+)?(?:u\.?s\.?|united states)\s+citizen\b",
    r"\b(?:u\.?s\.?|united states)\s+citizenship\s+(?:is\s+)?required\b",
    r"\bonly\s+(?:u\.?s\.?|united states)\s+citizens\b",
    r"\b(?:u\.?s\.?|united states)\s+citizens\s+only\b",
    r"\bcitizenship\s*:\s*(?:u\.?s\.?|united states)\b",
    r"\bmust\s+be\s+(?:a\s+)?(?:u\.?s\.?\s+citizen\s+or\s+(?:lawful\s+)?permanent\s+resident)\b",
]

PERMANENT_AUTH = [
    r"\b(?:permanent|unrestricted)\s+(?:u\.?s\.?\s+)?work\s+authoriz(?:ation|ed)\s+(?:is\s+)?required\b",
    r"\b(?:must|need)\s+(?:already\s+)?(?:have|possess)\s+(?:permanent|unrestricted)\s+(?:u\.?s\.?\s+)?work\s+authoriz(?:ation|ation status)\b",
]

NO_SPONSORSHIP = [
    r"\b(?:no|without)\s+(?:visa\s+)?sponsorship\b",
    r"\b(?:does\s+not|do\s+not|will\s+not|cannot|unable\s+to)\s+sponsor\b",
    r"\bsponsorship\s+(?:is\s+)?not\s+available\b",
    r"\bh-?1b\s+sponsorship\s+is\s+not\s+available\b",
]


def clean(text: str) -> str:
    return re.sub(r"\s+", " ", str(text)).strip()


def evidence(text: str, pattern: str, max_chars: int = 160) -> str | None:
    m = re.search(pattern, text, re.I | re.S)
    if not m:
        return None
    a = max(0, m.start() - 42)
    b = min(len(text), m.end() + 70)
    return clean(text[a:b])[:max_chars]


def latest_description(job_id: str) -> Path | None:
    # Avoid accidental path traversal if the index is corrupted.
    if not re.fullmatch(r"\d+", job_id):
        return None
    matches = list(JOBS.glob(f"{job_id}_*_description.txt"))
    if not matches:
        return None
    return max(matches, key=lambda p: (p.stat().st_mtime_ns, p.name))


def extract_deadline(text: str) -> date | None:
    # Handshake header: "Apply by November 8, 2026 at 11:59 PM".
    month = ("January February March April May June July August September "
             "October November December")
    found = re.search(
        rf"\bApply\s+by\s+({month.replace(' ', '|')})\s+(\d{{1,2}}),?\s+(20\d{{2}})\b",
        text, re.I,
    )
    if not found:
        return None
    months = month.lower().split()
    return date(int(found.group(3)), months.index(found.group(1).lower()) + 1,
                int(found.group(2)))


def restricted_remote_states(text: str) -> tuple[bool, list[str]]:
    """Detect EXPLICIT state lists, never infer a list from ordinary locations."""
    # Restriction must refer to eligibility/residency, not places the company has offices.
    m = re.search(
        r"\b(?:legal\s+residents|residents?|candidates)\s+(?:of|living\s+in|located\s+in)\s+"
        r"(?:one\s+of\s+)?(?:the\s+)?(?:following\s+)?states\s*:\s*([^\r\n]{4,500})",
        text, re.I,
    )
    if not m:
        return False, []
    # Limit to two-letter state codes in comma/"or"-separated context.
    values = [s.strip().upper() for s in re.split(r",|\bor\b", m.group(1), flags=re.I)]
    codes = [s for s in values if re.fullmatch(r"[A-Z]{2}", s)]
    return (len(codes) >= 3), codes


def classify(row: dict) -> dict:
    job_id = str(row.get("job_id", "")).strip()
    title = str(row.get("title", "")).strip()
    company = str(row.get("company", "")).strip()
    url = str(row.get("url", "")).strip()
    file = latest_description(job_id)
    base = {
        "job_id": job_id, "company": company, "title": title, "url": url,
        "jd_file": str(file.relative_to(ROOT)) if file else "",
        "match_score": None, "priority": "待提取 JD", "eligibility": "待核实",
        "deadline": "", "matched_skills": [], "jd_keywords": [], "flags": [], "evidence": [],
        "recommended_action": "先提取完整 JD", "screened_on": date.today().isoformat(),
    }
    if not file:
        return base
    text = file.read_text(encoding="utf-8-sig", errors="replace")
    if len(clean(text)) < 220 or "Job description" not in text:
        base["priority"] = "JD 需要复核"
        base["flags"].append("职位正文过短或缺少 Job description 标题，不能可靠筛选")
        base["recommended_action"] = "检查抓取结果，不要自动生成简历"
        return base

    score = 35
    joined = title + "\n" + text
    title_lower = title.lower()
    if re.search(r"\b(intern(ship)?|summer intern|co-?op|student program)\b", title_lower, re.I):
        score += 20
    elif re.search(r"\b(full.?time|senior|staff|principal|lead|manager|director)\b", title_lower, re.I):
        score -= 22
        base["flags"].append("职位名称不像本科实习岗位，需核对招聘对象")
    elif re.search(r"\b(internship|summer 2027)\b", joined, re.I):
        score += 10
    for pattern, points in TITLE_ROLES:
        if re.search(pattern, title_lower, re.I):
            score += points
            break
    else:
        # Other technical positions might still be relevant, but don't infer.
        if re.search(r"\b(computer science|software development|coding)\b", joined, re.I):
            score += 6

    skill_points = 0
    for pattern, label, points in SKILLS:
        if re.search(pattern, joined, re.I):
            base["jd_keywords"].append(label)
            if label in DOCUMENTED_EXPERIENCE:
                base["matched_skills"].append(label)
                skill_points += points
    score += min(skill_points, 22)

    if re.search(r"\b(summer\s+(?:of\s+)?2027|may\s+\d{1,2},?\s+2027|june\s+2027)\b", joined, re.I):
        score += 6
    if re.search(r"\b(3\+|4\+|5\+|three|four|five)\s+years?\s+of\s+(?:professional|industry|work)\s+experience\s+required\b", joined, re.I):
        score -= 18
        base["flags"].append("可能要求多年正式工作经验，需确认是否为硬性要求")

    blockers = []
    for pattern in CITIZEN_ONLY:
        found = evidence(text, pattern)
        if found:
            blockers.append("明确要求美国公民身份，当前 F-1 学生身份可能不符合")
            base["evidence"].append(found)
            break
    for pattern in PERMANENT_AUTH:
        found = evidence(text, pattern)
        if found:
            blockers.append("明确要求永久或不受限制的美国工作授权")
            base["evidence"].append(found)
            break

    # School graduation window / completed degree can be a hard employer requirement,
    # but the user's *expected graduation date* is not recorded in this script.
    # Keep it as a question, never invent a graduation year.
    grad_rule = evidence(text, r"\b(?:graduat(?:e|ing|ion)\s+(?:date\s+)?(?:in|between|by)\s+(?:20\d{2}|(?:spring|fall|summer)\s+20\d{2})|(?:only|exclusively)\s+(?:graduate|master.?s|ph\.?d\.?)\s+students?)\b")
    if grad_rule:
        base["flags"].append("发现毕业年份或学历层次限制，需结合实际预计毕业日期核实")
        base["evidence"].append(grad_rule)

    if re.search(r"\bUS work authorization not required\b", text, re.I) and re.search(
        r"\bW-?2 (?:candidates|employees)\b", text, re.I
    ):
        base["flags"].append("Handshake 概览和雇主 W-2 要求可能被误解，不能据此认定无需工作授权")

    for pattern in NO_SPONSORSHIP:
        found = evidence(text, pattern)
        if found:
            base["flags"].append("不提供签证赞助；不等于自动排除 CPT/OPT，但需向雇主确认")
            base["evidence"].append(found)
            break

    limited, codes = restricted_remote_states(text)
    if limited and PROFILE["planned_work_state"] not in codes:
        base["flags"].append(
            f"Remote 限定居民所在州，列表不包含预计工作州 {PROFILE['planned_work_state']}；"
            "除非允许迁居至合格州，否则当前地点存在冲突"
        )
        base["evidence"].append("允许州名单：" + ", ".join(codes))

    deadline = extract_deadline(text)
    if deadline:
        base["deadline"] = deadline.isoformat()
        if deadline < date.today():
            blockers.append("招聘截止日期已过（请留意页面是否重新开放）")
        elif (deadline - date.today()).days <= 7:
            base["flags"].append("申请截止不足或等于 7 天，建议尽快确认资格")

    if PROFILE["f1_student"] and not PROFILE["authorization_for_future_job_confirmed"]:
        # Inspect the heading/location area, not the entire JD: a US employer may
        # mention overseas offices in the description without being a foreign role.
        header = text.split("Job description", 1)[0][:2000]
        explicitly_abroad = bool(re.search(
            r"\b(shanghai|china|people.s republic of china|england|united kingdom|"
            r"london|canada|united kingdom|singapore|hong kong)\b", header, re.I,
        ))
        if explicitly_abroad:
            base["flags"].append(
                "岗位地点可能在美国境外；实际工作所在地、当地用工资格及美国境内远程工作授权需分别核实"
            )
        else:
            base["flags"].append(
                "若在美国境内实习，需向 UR ISO 核实 CPT/OPT 等适用工作授权；"
                "学校 2026 年公告了更严格的 CPT 限制"
            )

    score = max(0, min(100, score))
    base["match_score"] = score
    if blockers:
        base["priority"] = "低优先级·明确冲突"
        base["eligibility"] = "明确条件冲突（人工复核）"
        base["flags"] = blockers + base["flags"]
        base["recommended_action"] = "先确认是否存在资格例外，不自动生成简历"
    elif limited and PROFILE["planned_work_state"] not in codes:
        base["priority"] = "待核实·地点限制"
        base["eligibility"] = "居住州可能不符合"
        base["recommended_action"] = "先确认远程岗位是否允许在预计工作州工作、是否可迁居，核实授权后再生成简历"
    elif score >= 72:
        base["priority"] = "高匹配·优先核实"
        base["eligibility"] = "尚未确认"
        base["recommended_action"] = "优先核实申请资格与工作授权，确认后定制简历"
    elif score >= 52:
        base["priority"] = "中匹配·待核实"
        base["eligibility"] = "尚未确认"
        base["recommended_action"] = "查看岗位要求，确认条件后决定是否生成简历"
    else:
        base["priority"] = "低匹配·暂缓"
        base["eligibility"] = "尚未确认"
        base["recommended_action"] = "低优先级，除非特别感兴趣否则暂缓生成简历"
    return base


def mdcell(value) -> str:
    return clean(str(value)).replace("|", "\\|").replace("`", "'")


def safe_csv_cell(value):
    """Avoid CSV formula injection when the report is opened in Excel."""
    value = str(value)
    if value.lstrip().startswith(("=", "+", "-", "@")) or value.startswith(("\t", "\r", "\n")):
        return "'" + value
    return value


def write_outputs(records: list[dict]):
    JOBS.mkdir(parents=True, exist_ok=True)
    RESULT_JSON.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
    columns = ["job_id", "company", "title", "match_score", "priority", "eligibility",
               "deadline", "matched_skills", "jd_keywords", "flags", "recommended_action", "url", "jd_file"]
    with RESULT_CSV.open("w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in records:
            d = row.copy()
            d["matched_skills"] = ", ".join(row["matched_skills"])
            d["jd_keywords"] = ", ".join(row["jd_keywords"])
            d["flags"] = "；".join(row["flags"])
            writer.writerow({k: safe_csv_cell(v) for k, v in d.items() if k in columns})
    lines = [
        "# Handshake 职位初筛报告", "",
        f"生成日期：{date.today().isoformat()}。基于已保存的 JD，非法律或雇主资格裁定。", "",
        "匹配分仅表示技术方向的启发式接近程度；不能代表录取几率、真实技能熟练度或工作许可。", "",
        "已确认的项目经验关键词（可在脚本中修改）：" + ", ".join(sorted(DOCUMENTED_EXPERIENCE)) + "。", "",
        "| 匹配分 | 优先级 | 公司 | 职位 | 资格疑点 |",
        "|---:|---|---|---|---|",
    ]
    for row in records:
        skills = ", ".join(row["matched_skills"])
        flags = "；".join(row["flags"]) or "尚未发现明确 JD 冲突；工作资格仍需确认"
        lines.append("| " + " | ".join(map(mdcell, [row["match_score"] if row["match_score"] is not None else "—",
            row["priority"], row["company"], row["title"], flags])) + " |")
    lines.extend(["", "## 个别岗位核实事项", ""])
    for row in records:
        lines.append(f"### {row['company']} — {row['title']} ({row['job_id']})")
        lines.append(f"- 推荐动作：{row['recommended_action']}")
        lines.append(f"- JD 提及关键词：{', '.join(row['jd_keywords']) or '未检测到'}")
        lines.append(f"- 与已提供经历重合：{', '.join(row['matched_skills']) or '尚未检测到（不代表你不会）'}")
        lines.append(f"- 已提取截止日期：{row['deadline'] or '未提取（需人工检查）'}")
        for reason in row["flags"]:
            lines.append(f"- 需核实：{reason}")
        for quote in row["evidence"]:
            lines.append(f"- JD 原文依据：{quote}")
        lines.append("")
    lines.extend([
        "## 使用说明", "",
        "- 没提及签证要求，不等于允许国际学生申请。",
        "- 不提供 H-1B sponsor，并不自动表示不能使用获批 CPT/OPT 工作。",
        "- 学校目前的 CPT 规则需与 ISO 再核实；美国境内的远程实习同样需要合适授权。",
        "- 预计工作州暂按 NY；如 2027 年计划搬迁，须在 job_screen.py 的 PROFILE 中修改。",
        "- 技能重合仅基于 DOCUMENTED_EXPERIENCE，JD 含关键词不等于你已经掌握该技能。",
        "- 没有自动拒绝任何申请，也没有调用简历模型。",
        "- 官方页面：https://www.rochester.edu/iso/current-students/working/f-1-cpt/", "",
    ])
    RESULT_MD.write_text("\n".join(lines), encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description="Screen saved Handshake JDs without AI API calls")
    parser.add_argument("--match", default="", help="Only job titles/companies containing this text")
    parser.add_argument("--dry-run", action="store_true", help="Print ranking only; do not write reports")
    args = parser.parse_args()
    if not INDEX.exists():
        parser.error(f"Missing {INDEX}; run Handshake email importer first")
    rows = json.loads(INDEX.read_text(encoding="utf-8-sig"))
    if not isinstance(rows, list):
        parser.error("handshake_email_jobs.json must be a JSON list")
    records = []
    seen = set()
    for row in rows:
        if not isinstance(row, dict):
            continue
        jid = str(row.get("job_id", ""))
        if not re.fullmatch(r"\d+", jid) or jid in seen:
            continue
        if args.match and args.match.casefold() not in (
            str(row.get("company", "")) + " " + str(row.get("title", ""))
        ).casefold():
            continue
        seen.add(jid)
        records.append(classify(row))
    priority_order = {
        "高匹配·优先核实": 0,
        "中匹配·待核实": 1,
        "待核实·地点限制": 2,
        "低匹配·暂缓": 3,
        "低优先级·明确冲突": 4,
        "JD 需要复核": 5,
        "待提取 JD": 6,
    }
    records.sort(key=lambda d: (
        priority_order.get(d["priority"], 9),
        -(d["match_score"] or 0),
        d["company"].lower(),
    ))
    print(f"Screened jobs: {len(records)}")
    for r in records:
        points = f"{r['match_score']:3}" if r["match_score"] is not None else "  —"
        print(f"[{points}] {r['priority']} | {r['company']} | {r['title']}")
        for flag in r["flags"][:2]:
            print("      ! " + flag)
    if args.dry_run:
        print("Dry run: no report files modified.")
        return
    write_outputs(records)
    print("Saved:", RESULT_JSON)
    print("Saved:", RESULT_CSV)
    print("Saved:", RESULT_MD)
    print("Review important eligibility flags before asking the resume model to draft.")


if __name__ == "__main__":
    try:
        main()
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"Screening failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
