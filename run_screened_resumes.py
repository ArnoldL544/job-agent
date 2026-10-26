"""Generate *review drafts* from the existing Handshake screening report.

Does not browse, submit applications, or decide work authorization. No API calls
unless explicit --job-id selection plus a yes confirmation (or --yes).

Commands:
  python run_screened_resumes.py --list
  python run_screened_resumes.py --job-id 11651900
  python run_screened_resumes.py --job-id 11651900 --yes
  python run_screened_resumes.py --job-id 11651900 --force

Uses existing resume_writer.generate_resume_draft, resume_docx and Word template.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
JOBS_DIR = ROOT / "jobs"
REPORT = JOBS_DIR / "job_screen_results.json"
STATE_FILE = JOBS_DIR / "resume_draft_state.json"
PROFILE_FILE = ROOT / "profile.txt"
TEMPLATE_FILE = ROOT / "resume-template.docx"
DETAILS_FILE = ROOT / "resume_details.txt"
KEY_FILE = ROOT / "APIkey.env"

ACCEPTED_PRIORITIES = {"高匹配·优先核实", "中匹配·待核实"}
MODEL_NAME = "gpt-5.4-mini"  # Provided by the user's existing resume_writer.py


def load_report() -> list[dict]:
    if not REPORT.is_file():
        raise ValueError("没有筛选结果。先执行：python run_email_jobs.py --screen-only")
    records = json.loads(REPORT.read_text(encoding="utf-8-sig"))
    if not isinstance(records, list):
        raise ValueError("job_screen_results.json 需要是 JSON 列表")
    result, seen = [], set()
    for row in records:
        if not isinstance(row, dict):
            continue
        jid = str(row.get("job_id", "")).strip()
        if not re.fullmatch(r"\d+", jid) or jid in seen:
            continue
        seen.add(jid)
        result.append(row)
    return result


def find_jd(row: dict) -> Path | None:
    """Accept only an existing *_description.txt under this project's jobs/."""
    jid = str(row.get("job_id", ""))
    if not re.fullmatch(r"\d+", jid):
        return None
    stored = str(row.get("jd_file", "")).strip()
    if not stored:
        return None
    candidate = (ROOT / stored).resolve()
    jobs_root = JOBS_DIR.resolve()
    if not candidate.is_relative_to(jobs_root):
        return None
    if not candidate.name.startswith(jid + "_") or not candidate.name.endswith("_description.txt"):
        return None
    return candidate if candidate.is_file() else None


def restrictions(row: dict) -> list[str]:
    """Guardrails for *drafting priority*, not a legal authorization decision."""
    reasons = []
    priority = str(row.get("priority", ""))
    if priority not in ACCEPTED_PRIORITIES:
        reasons.append(f"筛选等级为：{priority or '未知'}")
    if row.get("match_score") is None:
        reasons.append("没有有效的技术匹配评分")
    deadline = str(row.get("deadline", ""))
    if deadline:
        try:
            d = date.fromisoformat(deadline)
            if d < date.today():
                reasons.append(f"截止日期 {deadline} 已过；请重新核实招聘是否仍开放")
        except ValueError:
            reasons.append("筛选结果的截止日期格式无效")
    return reasons


def eligibility_notes(row: dict) -> list[str]:
    notes = row.get("flags", [])
    return [str(item) for item in notes if str(item).strip()] if isinstance(notes, list) else []


def read_state() -> dict:
    if not STATE_FILE.exists():
        return {}
    value = json.loads(STATE_FILE.read_text(encoding="utf-8-sig"))
    if not isinstance(value, dict):
        raise ValueError("resume_draft_state.json 不是对象；请先备份并检查内容")
    return value


def save_state(state: dict) -> None:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    temp = STATE_FILE.with_suffix(".json.tmp")
    temp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    temp.replace(STATE_FILE)


def input_fingerprint(jd_file: Path) -> str:
    """New JD/profile/template/supplement -> draft allowed even if previously done."""
    digest = hashlib.sha256()
    digest.update(MODEL_NAME.encode("utf-8"))
    for item in (jd_file, PROFILE_FILE, TEMPLATE_FILE, DETAILS_FILE):
        digest.update(item.name.encode("utf-8"))
        digest.update(item.read_bytes() if item.is_file() else b"<missing>")
    return digest.hexdigest()


def completed_before(row: dict, state: dict, fingerprint: str) -> bool:
    previous = state.get(str(row["job_id"]), {})
    if not isinstance(previous, dict) or previous.get("fingerprint") != fingerprint:
        return False
    for key in ("markdown", "docx"):
        recorded = previous.get(key)
        if not isinstance(recorded, str) or not recorded:
            return False
        p = (ROOT / recorded).resolve()
        if not p.is_relative_to(ROOT.resolve() / "resumes") or not p.is_file():
            return False
    return True


def preflight() -> tuple[str, Path]:
    """Run before creating an API client; no paid request unless all inputs exist."""
    for path, name in ((PROFILE_FILE, "profile.txt"),
                       (TEMPLATE_FILE, "resume-template.docx"),
                       (ROOT / "resume_writer.py", "resume_writer.py"),
                       (ROOT / "resume_docx.py", "resume_docx.py"),
                       (KEY_FILE, "APIkey.env")):
        if not path.is_file():
            raise ValueError(f"缺少文件：{name}（位于 agent project 根目录）")
    profile = PROFILE_FILE.read_text(encoding="utf-8-sig").strip()
    if not profile:
        raise ValueError("profile.txt 为空，不能生成真实简历")
    try:
        from resume_docx import template_context
        template_context(TEMPLATE_FILE)
    except ImportError as exc:
        raise ValueError("请先安装：python -m pip install python-docx") from exc
    except Exception as exc:
        raise ValueError(f"Word 模板检查失败：{exc}") from exc
    from dotenv import dotenv_values
    api_key = dotenv_values(KEY_FILE).get("OPENAI_API_KEY")
    if not isinstance(api_key, str) or not api_key.strip():
        raise ValueError("APIkey.env 中没有有效的 OPENAI_API_KEY")
    return profile, api_key.strip()


def list_rows(rows: list[dict], state: dict) -> None:
    print(f"\n筛选报告包含 {len(rows)} 个职位。以下仅是草稿优先级，不代表有工作许可。\n")
    for row in rows:
        jid = str(row["job_id"])
        jd_file = find_jd(row)
        blocked = restrictions(row)
        level = "待核实/默认暂缓" if blocked else "可选择生成审核稿"
        if not jd_file:
            level = "缺少已验证的 JD 文件"
        elif all(path.exists() for path in (PROFILE_FILE, TEMPLATE_FILE)):
            try:
                stamp = input_fingerprint(jd_file)
                if completed_before(row, state, stamp):
                    level = "已生成（相同输入）"
            except OSError:
                pass
        score = row.get("match_score")
        print(f"[{jid}] {row.get('company','')} — {row.get('title','')}")
        print(f"      技术分：{score if score is not None else '—'} | {row.get('priority','')} | {level}")
        for note in eligibility_notes(row)[:2]:
            print("      ⚠ " + note)
        if blocked:
            print("      暂缓原因：" + "；".join(blocked))
    print("\n生成指定岗位审核稿：python run_screened_resumes.py --job-id 11651900")
    print("默认只预览，不调用 OpenAI，也不申请任何职位。\n")


def write_draft(row: dict, state: dict, *, force: bool, allow_risk: bool, yes: bool) -> str:
    jid = str(row["job_id"])
    jd_file = find_jd(row)
    if not jd_file:
        return f"SKIP {jid}: 缺少对应 JD 或路径不安全"
    job = jd_file.read_text(encoding="utf-8-sig", errors="replace").strip()
    if len(job) < 220 or "Job description" not in job:
        return f"SKIP {jid}: JD 内容不完整，请重新抓取"

    blocked = restrictions(row)
    if blocked and not allow_risk:
        return f"SKIP {jid}: {'；'.join(blocked)}。如仅想制作供审核草稿，须显式加 --allow-risk"

    notes = eligibility_notes(row)
    print(f"\n目标职位：{row.get('company','')} — {row.get('title','')}")
    print(f"评分 {row.get('match_score')} | {row.get('priority')} | 截止：{row.get('deadline') or '待查'}")
    if notes:
        print("以下资格、地点或工作授权事项仍需人工核实：")
        for note in notes:
            print("  ! " + note)
    print("注意：此操作只生成待审核简历，不表示符合申请资格，不会自动投递。")

    # Check presence and shape of Word template before any API spend.
    profile, api_key = preflight()
    fingerprint = input_fingerprint(jd_file)
    if completed_before(row, state, fingerprint) and not force:
        return f"SKIP {jid}: 相同 JD、profile 和模板已经有 Word 审核稿。需要重做加 --force"

    if not yes:
        reply = input("确认调用 GPT API 为此岗位生成一份 Word 审核稿？输入 y 确认：").strip().lower()
        if reply not in {"y", "yes"}:
            return f"SKIP {jid}: 用户未确认"

    # Lazy imports: --list never needs OpenAI or reads its key.
    from openai import OpenAI
    from resume_writer import generate_resume_draft
    client = OpenAI(api_key=api_key)
    result = generate_resume_draft(client, profile, job, jd_file, ROOT)
    if not result:
        return f"FAILED {jid}: 生成模块未返回有效草稿"
    md_file = Path(result).resolve()
    docx_file = md_file.with_suffix(".docx")
    resume_root = (ROOT / "resumes").resolve()
    if not md_file.is_relative_to(resume_root) or not (md_file.is_file() and docx_file.is_file()):
        return f"PARTIAL {jid}: 已返回草稿，但未确认 Word 文件；本次不标记完成"

    state[jid] = {
        "fingerprint": fingerprint,
        "markdown": str(md_file.relative_to(ROOT)),
        "docx": str(docx_file.relative_to(ROOT)),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "screen_priority": row.get("priority", ""),
        "eligibility_review_required": True,
    }
    save_state(state)
    return f"SUCCESS {jid}: Word 审核稿 {docx_file.name}；仍需核对资格和正文真实性"


def main() -> int:
    parser = argparse.ArgumentParser(description="将已筛选 Handshake JD 转为逐岗审核简历")
    parser.add_argument("--list", action="store_true", help="只列出职位（默认行为）")
    parser.add_argument("--job-id", action="append", default=[], help="指定一个职位编号；可重复以选择多个")
    parser.add_argument("--yes", action="store_true", help="对已明确选择的职位跳过交互确认")
    parser.add_argument("--allow-risk", action="store_true", help="明确允许为低优先级/有硬限制的职位制作草稿，不代表符合资格")
    parser.add_argument("--force", action="store_true", help="重生成相同输入的简历草稿")
    parser.add_argument("--max-drafts", type=int, default=1, help="单次最多尝试生成多少份（默认 1）")
    args = parser.parse_args()
    if args.max_drafts < 1:
        parser.error("--max-drafts 必须 >= 1")
    rows = load_report()
    state = read_state()
    if not args.job_id or args.list:
        list_rows(rows, state)
        if not args.job_id:
            return 0
    wanted = list(dict.fromkeys(args.job_id))
    if len(wanted) > args.max_drafts:
        parser.error(f"选了 {len(wanted)} 个岗位，但 --max-drafts={args.max_drafts}。请提高上限或分批运行")
    lookup = {str(row["job_id"]): row for row in rows}
    errors = 0
    for jid in wanted:
        if jid not in lookup:
            print(f"ERROR {jid}: 不在当前筛选报告中。先重新运行 job_screen.py")
            errors += 1
            continue
        try:
            result = write_draft(lookup[jid], state, force=args.force,
                                 allow_risk=args.allow_risk, yes=args.yes)
            print(result)
            if result.startswith(("FAILED", "PARTIAL")):
                errors += 1
        except (OSError, ValueError, ImportError) as exc:
            print(f"FAILED {jid}: {type(exc).__name__}: {exc}")
            errors += 1
    return 1 if errors else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        raise SystemExit(1)
