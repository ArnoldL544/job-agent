"""Job Agent Dashboard v2 — local-only Streamlit UI.

Launch from the same folder as existing backend scripts:
    python -m streamlit run web_app.py --server.address 127.0.0.1

No model request without the explicit per-job paid-action checkbox and button.
The page never submits a job application or exposes private credentials.
"""

from __future__ import annotations

import html
import json
import os
import re
import subprocess
import sys
from collections import Counter
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlsplit

import streamlit as st

ROOT = Path(__file__).resolve().parent
JOBS = ROOT / "jobs"
RESUMES = ROOT / "resumes"
INDEX = JOBS / "handshake_email_jobs.json"
SCREEN = JOBS / "job_screen_results.json"
RESUME_STATE = JOBS / "resume_draft_state.json"
ACCEPTED = {"高匹配·优先核实", "中匹配·待核实"}
PAGES = ["总览", "岗位列表", "职位详情", "简历中心", "运行任务"]
MIME_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"

st.set_page_config(page_title="Job Agent · Career Workspace", page_icon="◈", layout="wide", initial_sidebar_state="expanded")

CSS = r"""
<style>
:root { --ja-ink: #e8effa; --ja-muted: #98abc2; --ja-line: rgba(154,180,208,.14); --ja-green: #3fdec0; --ja-blue: #7ca9ff; }
html, body, [data-testid="stAppViewContainer"] { color: var(--ja-ink); }
[data-testid="stAppViewContainer"] {
    background: radial-gradient(ellipse 80% 36% at 84% 0%, rgba(36,78,127,.15), transparent 76%), #0b111d;
}
[data-testid="stHeader"] { background: transparent; }
[data-testid="stSidebar"] { background: #0f1928; border-right: 1px solid var(--ja-line); }
[data-testid="stSidebar"] > div:first-child { padding-top: 1.8rem; }
[data-testid="stSidebar"] [data-testid="stMarkdownContainer"] p { color: #c0cedf; }
.block-container { max-width: 1470px; padding-top: 1.35rem; padding-bottom: 5rem; }
[data-testid="stAppViewContainer"], [data-testid="stSidebar"], button, input, textarea { font-family: 'Segoe UI', 'Microsoft YaHei', 'PingFang SC', sans-serif; }
h1, h2, h3 { letter-spacing: -.035em !important; }
h1 { font-weight: 800 !important; }
h3 { font-weight: 700 !important; }
div[data-testid="stVerticalBlockBorderWrapper"] { border-color: var(--ja-line) !important; border-radius: 17px !important; }
[data-testid="stButton"] > button, [data-testid="stDownloadButton"] > button, [data-testid="stLinkButton"] > a {
 border-radius: 10px; font-weight: 650; transition: .15s ease; border-color: rgba(143,166,191,.22);
}
[data-testid="stButton"] > button[kind="primary"] { background: #42d6bd; color: #07151a; border: none; }
[data-testid="stButton"] > button[kind="primary"]:hover { background: #64e7d2; color: #04191a; }
[data-testid="stTextInput"] input, [data-testid="stSelectbox"] > div, [data-testid="stMultiSelect"] > div { border-radius: 10px; }
[data-testid="stRadio"] label, [data-testid="stCheckbox"] label { font-size: .92rem; }
[data-testid="stMetric"] { border-radius: 14px; }
[data-testid="stDataFrame"] { border-radius: 12px; overflow:hidden; }
[data-testid="stTabs"] button { font-weight: 650; }
hr { border-color: rgba(151,174,206,.15); }
.ja-brand { font-weight: 800; font-size: 1.48rem; letter-spacing: -.035em; color:#f5faff; margin-bottom:.1rem; }
.ja-mark { display:inline-grid; place-items:center; background: linear-gradient(145deg,#36d6b8,#488bff); width:33px; height:33px; border-radius:10px; color:#0c1b2b; margin-right:9px; font-weight:900; }
.ja-brand-sub { color:#748da9; font-size:.75rem; letter-spacing:.14em; font-weight:700; margin-top:2px; }
.ja-sep { border-top:1px solid var(--ja-line); margin:20px 0; }
.ja-privacy { background:rgba(45,183,154,.075); border:1px solid rgba(67,215,185,.16); border-radius:12px; padding:12px 13px; font-size:.78rem; line-height:1.65; color:#9fc2c7; }
.ja-hero { border:1px solid rgba(123,185,215,.2); border-radius:22px; padding:31px 34px 29px; margin-bottom:24px;
 background:radial-gradient(ellipse 57% 123% at 96% -29%,rgba(57,196,171,.17),transparent 81%),linear-gradient(106deg,#14243a,#102135 58%,#132c39); overflow:hidden; position:relative; }
.ja-overline { font-size:.68rem; letter-spacing:.2em; font-weight:800; color:#58e5d3; text-transform:uppercase; margin-bottom:12px; }
.ja-hero-title { color:#f3f8ff; font-size:2.2rem; letter-spacing:-.055em; line-height:1.25; font-weight:800; margin:0 0 11px; }
.ja-hero-desc { max-width:770px; color:#aabed3; font-size:.95rem; line-height:1.8; }
.ja-chips { display:flex; gap:8px; flex-wrap:wrap; margin-top:21px; }
.ja-chip { font-size:.73rem; padding:7px 11px; color:#b6d2e5; background:rgba(255,255,255,.055);border:1px solid rgba(172,207,225,.12);border-radius:30px; }
.ja-section-kicker {font-size:.72rem; letter-spacing:.15em; font-weight:750; color:#56d7c2; margin-bottom:5px; }
.ja-section-title { color:#ebf3ff; font-weight:750; font-size:1.24rem; letter-spacing:-.03em; margin-bottom:16px; }
.ja-kpi { border:1px solid var(--ja-line);border-radius:16px;min-height:116px;padding:18px 20px;
 background:linear-gradient(135deg,rgba(30,48,69,.87),rgba(17,30,48,.88)); }
.ja-kpi-label {color:#9aacbf;font-size:.8rem;font-weight:570;}
.ja-kpi-num {color:#f1f7ff;font-size:2.02rem;font-weight:800;line-height:1.25;margin-top:7px;letter-spacing:-.05em;}
.ja-kpi-note {color:#6f90ac;font-size:.72rem; margin-top:6px;}
.ja-panel-title { font-weight:750; color:#eef6ff; font-size:1.05rem; letter-spacing:-.025em; margin-bottom:4px; }
.ja-panel-sub {font-size:.81rem;color:#8da4bd;margin-bottom:16px;}
.ja-scorebar {background:#1c2b3c; height:6px; border-radius:10px; overflow:hidden;margin-top:10px;}
.ja-scorefill {height:100%;background:linear-gradient(90deg,#34ccb2,#83a8ff);border-radius:10px;}
.ja-job-name { font-size:.92rem; color:#f1f7ff; font-weight:690; line-height:1.52; }
.ja-job-company { font-size:.77rem; color:#9db1c9; margin:1px 0 8px; }
.ja-score {color:#61e5cd; font-weight:800; font-size:1.2rem; letter-spacing:-.04em; text-align:right; }
.ja-small {color:#8da2bc;font-size:.78rem;line-height:1.65;}
.ja-label {display:inline-block; font-size:.68rem; font-weight:750; border:1px solid rgba(96,228,202,.2); border-radius:99px; padding:3px 9px; color:#6de2d0; background:rgba(60,211,181,.085);}
.ja-label-warn {color:#f5c680; border-color:rgba(226,181,113,.2);background:rgba(193,137,59,.1);}
.ja-muted {color:#91a8bf; font-size:.84rem;line-height:1.7;}
.ja-divider { border-top:1px solid var(--ja-line); margin:18px 0; }
.ja-mini-step {padding:10px 12px;border:1px solid var(--ja-line);border-radius:12px;background:#111e2e;margin-bottom:8px;display:flex;align-items:center;gap:10px;color:#adbed2;font-size:.82rem;}
.ja-dot {width:8px;height:8px;border-radius:50%;background:#46d6b9;box-shadow:0 0 0 4px rgba(70,214,185,.10);flex:none;}
.ja-detail-head {padding:20px 22px;border:1px solid rgba(135,169,202,.17);border-radius:16px;background:linear-gradient(110deg,#14263b,#142231);margin-bottom:12px;}
.ja-detail-role {font-weight:800;color:#f1f7ff;letter-spacing:-.035em;font-size:1.49rem;margin-bottom:6px;}
.ja-detail-company {font-size:.87rem;color:#9dbee0;}
.ja-jd {white-space:pre-wrap;word-break:break-word;max-height:650px;overflow-y:auto;border:1px solid var(--ja-line);border-radius:13px;padding:20px 22px;background:#101b2a;color:#d0dceb;font-size:.88rem;line-height:1.75;}
.ja-footnote {color:#7590a9;font-size:.72rem;line-height:1.7;margin-top:13px;}
.ja-progress {color:#99a9bd;font-size:.77rem;}
/* Better separation for the Streamlit sidebar navigation. */
[data-testid="stSidebar"] [data-testid="stRadio"] > div {gap:.26rem;}
[data-testid="stSidebar"] [data-testid="stRadio"] label {background:rgba(255,255,255,.012);border:1px solid transparent;border-radius:10px;padding:8px 10px;}
[data-testid="stSidebar"] [data-testid="stRadio"] label:hover {background:rgba(110,148,179,.12);}
@media (max-width:760px) { .ja-hero{padding:24px 22px;} .ja-hero-title{font-size:1.6rem;} .ja-kpi{min-height:100px;padding:13px;} }
</style>
"""
st.markdown(CSS, unsafe_allow_html=True)


def esc(value: object) -> str:
    return html.escape(str(value) if value is not None else "", quote=True)


def read_json(path: Path, default):
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, UnicodeError):
        return default


def valid_id(value: object) -> str | None:
    val = str(value).strip()
    return val if re.fullmatch(r"\d+", val) else None


def load_jobs() -> list[dict]:
    merged: dict[str, dict] = {}
    for path in (INDEX, SCREEN):
        records = read_json(path, [])
        if not isinstance(records, list):
            continue
        for rec in records:
            if not isinstance(rec, dict):
                continue
            jid = valid_id(rec.get("job_id", ""))
            if jid:
                merged[jid] = {**merged.get(jid, {}), **rec, "job_id": jid}
    def rank(row):
        score = row.get("match_score")
        return (not isinstance(score, (float, int)), -(score if isinstance(score, (float, int)) else 0), str(row.get("company", "")).lower())
    return sorted(merged.values(), key=rank)


def jd_file(row: dict) -> Path | None:
    jid = valid_id(row.get("job_id", ""))
    if not jid:
        return None
    saved = row.get("jd_file")
    if isinstance(saved, str) and saved.strip():
        candidate = (ROOT / saved).resolve()
        if (candidate.is_relative_to(JOBS.resolve()) and candidate.name.startswith(jid + "_")
                and candidate.name.endswith("_description.txt") and candidate.is_file()):
            return candidate
    if not JOBS.is_dir():
        return None
    paths = sorted(JOBS.glob(f"{jid}_*_description.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    return paths[0] if paths else None


def resumes_for(jid: str, ext: str) -> list[Path]:
    if not valid_id(jid) or ext not in {".md", ".docx"}:
        return []
    found = list(RESUMES.glob(f"{jid}_*_resume_draft{ext}")) if RESUMES.is_dir() else []
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    state = read_json(RESUME_STATE, {})
    row = state.get(jid) if isinstance(state, dict) else None
    if isinstance(row, dict):
        stored = row.get("docx" if ext == ".docx" else "markdown")
        if isinstance(stored, str) and stored:
            path = (ROOT / stored).resolve()
            if path.is_relative_to(RESUMES.resolve()) and path.is_file() and path.suffix == ext and path not in found:
                found.insert(0, path)
    return found


def flags_for(row: dict) -> list[str]:
    val = row.get("flags", [])
    return [str(f) for f in val if str(f).strip()] if isinstance(val, list) else []


def eligibility_hold(row: dict) -> list[str]:
    notes = []
    priority = str(row.get("priority", ""))
    if priority not in ACCEPTED:
        notes.append(f"筛选级别为「{priority or '未筛选'}」")
    if not isinstance(row.get("match_score"), (int, float)):
        notes.append("缺少技术评分")
    raw_deadline = row.get("deadline", "")
    if isinstance(raw_deadline, str) and raw_deadline:
        try:
            if date.fromisoformat(raw_deadline) < date.today():
                notes.append("申请截止日期已过，需再次核实岗位状态")
        except ValueError:
            notes.append("截止日期格式异常，需核实")
    return notes


def safe_handshake_url(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    split = urlsplit(value)
    name = split.hostname or ""
    if split.scheme == "https" and (name == "joinhandshake.com" or name.endswith(".joinhandshake.com")):
        return value
    return None


def job_label(row: dict) -> str:
    return f"{row.get('company','未知公司')} · {row.get('title','未知职位')}  [{row['job_id']}]"


def job_score(row: dict) -> str:
    score = row.get("match_score")
    return str(round(score)) if isinstance(score, (int, float)) else "—"


def score_bar(score: object) -> str:
    num = min(100, max(0, float(score))) if isinstance(score, (int, float)) else 0
    return f'<div class="ja-scorebar"><div class="ja-scorefill" style="width:{num:.1f}%"></div></div>'


def risk_badge(row: dict) -> str:
    priority = str(row.get("priority", "未筛选"))
    if eligibility_hold(row):
        return f'<span class="ja-label ja-label-warn">{esc(priority)}</span>'
    return f'<span class="ja-label">{esc(priority)}</span>'


def section(title: str, kicker: str = ""):
    st.markdown(f'<div class="ja-section-kicker">{esc(kicker)}</div><div class="ja-section-title">{esc(title)}</div>', unsafe_allow_html=True)


def kpi(label: str, value: object, note: str = ""):
    st.markdown(f'<div class="ja-kpi"><div class="ja-kpi-label">{esc(label)}</div><div class="ja-kpi-num">{esc(value)}</div><div class="ja-kpi-note">{esc(note)}</div></div>', unsafe_allow_html=True)


def go_to(page: str, jid: str | None = None):
    if jid:
        st.session_state["chosen_job_id"] = jid
        # Streamlit keeps selectbox selections across reruns; update the specific
        # page selector before navigation so the opened record is the clicked one.
        if page == "职位详情":
            st.session_state["detail_selected"] = jid
        elif page == "简历中心":
            st.session_state["resume_selected"] = jid
    st.session_state["nav_pending"] = page
    st.rerun()


def latest_stamp(path: Path | None) -> str:
    if not path or not path.is_file():
        return "—"
    return datetime.fromtimestamp(path.stat().st_mtime).strftime("%m-%d %H:%M")


def download_file(label: str, path: Path, key: str, mime: str, width: str = "stretch"):
    if not path.is_file():
        return
    try:
        content = path.read_bytes()
    except OSError:
        st.error("无法读取文件。")
        return
    st.download_button(label, data=content, file_name=path.name, mime=mime, key=key, width=width)


def execute_backend(filename: str, args: list[str]) -> tuple[int, str]:
    """Run only named local scripts without shell expansion; decode Chinese reliably."""
    allowed = {"run_full_agent.py", "run_email_jobs.py", "run_screened_resumes.py"}
    if filename not in allowed:
        return 1, "未允许调用此脚本。"
    script = ROOT / filename
    if not script.is_file():
        return 1, f"未找到 {filename}。"
    environment = os.environ.copy()
    environment.update(PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    command = [sys.executable, "-u", str(script), *args]
    text_lines = []
    placeholder = st.empty()
    try:
        proc = subprocess.Popen(command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                encoding="utf-8", errors="replace", bufsize=1)
        assert proc.stdout
        for line in proc.stdout:
            text_lines.append(line.rstrip("\r\n"))
            if len(text_lines) > 1700:
                text_lines = text_lines[-1700:]
            if len(text_lines) % 5 == 0 or any(t in line for t in ("SUCCESS", "FAILED", "Traceback", "Saved:")):
                placeholder.code("\n".join(text_lines[-18:])[-7500:], language="text")
        code = proc.wait()
    except (OSError, ValueError) as exc:
        return 1, f"子进程启动失败：{type(exc).__name__}: {exc}"
    full_log = "\n".join(text_lines)
    # Keep a compact preview: raw Markdown with model output should not be the primary UI.
    placeholder.code("\n".join(text_lines[-20:])[-8500:], language="text")
    return code, full_log


def execution_result(code: int, log: str, task: str):
    st.session_state["last_exec"] = {"code": code, "log": log, "task": task}
    if code != 0 or "FAILED " in log or "PARTIAL " in log:
        st.error("运行未完全成功。请检查日志，不要把它当作已完成的简历。")
    elif "SKIP " in log and "SUCCESS " not in log:
        st.info("执行结束，但本次跳过了生成。可能已有相同审核稿，或当前岗位尚待核实。")
    else:
        st.success("任务执行结束。结果已从本地文件更新。")


def sidebar() -> str:
    if "nav_pending" in st.session_state:
        st.session_state["page_nav"] = st.session_state.pop("nav_pending")
    with st.sidebar:
        st.markdown('<div class="ja-brand"><span class="ja-mark">◈</span>Job Agent</div><div class="ja-brand-sub">CAREER WORKSPACE · V2</div>', unsafe_allow_html=True)
        st.markdown('<div class="ja-sep"></div>', unsafe_allow_html=True)
        page = st.radio("功能导航", PAGES, key="page_nav", label_visibility="collapsed")
        st.markdown('<div class="ja-sep"></div>', unsafe_allow_html=True)
        st.markdown('<div class="ja-privacy">● LOCAL WORKSPACE<br>数据与凭据保留在本机。生成简历需要你单独确认；不会自动投递。</div>', unsafe_allow_html=True)
        st.write("")
        if st.button("↻  刷新数据", width="stretch"):
            st.rerun()
        st.caption("运行服务：127.0.0.1 · 建议仅在本机使用")
    return page


def dashboard(jobs: list[dict]):
    count_jd = sum(bool(jd_file(j)) for j in jobs)
    count_resume = sum(bool(resumes_for(j["job_id"], ".docx")) for j in jobs)
    count_high = sum(j.get("priority") in ACCEPTED for j in jobs)
    st.markdown('''<div class="ja-hero"><div class="ja-overline">PERSONAL CAREER INTELLIGENCE</div>
        <div class="ja-hero-title">你的机会，都在一个工作台。</div>
        <div class="ja-hero-desc">从 Gmail 自动发现职位，进入 Handshake 获取完整 JD，进行技能与资格筛选，最后生成需要你审核的 Word 简历。</div>
        <div class="ja-chips"><span class="ja-chip">✦ Gmail 采集</span><span class="ja-chip">↗ JD 自动提取</span><span class="ja-chip">◎ 智能匹配</span><span class="ja-chip">▤ Word 审核稿</span></div>
        </div>''', unsafe_allow_html=True)
    cols = st.columns(4)
    for col, label, val, note in zip(cols,
                                     ["已发现岗位", "JD 已完成", "高/中技术匹配", "已有 Word 草稿"],
                                     [len(jobs), count_jd, count_high, count_resume],
                                     ["邮箱同步的机会", "可以用于分析", "尚需资格核实", "等待本人审核"]):
        with col:
            kpi(label, val, note)
    st.write("")
    left, right = st.columns([1.7, 1], gap="large")
    with left:
        section("优先处理的岗位", "YOUR SHORTLIST")
        if not jobs:
            st.info("还没有职位。到「运行任务」导入 Gmail 推荐职位即可。")
        for row in jobs[:5]:
            jid = row["job_id"]
            with st.container(border=True):
                a, b = st.columns([6, 1.1], gap="medium")
                with a:
                    st.markdown(f'<div class="ja-job-name">{esc(row.get("title","未知职位"))}</div><div class="ja-job-company">{esc(row.get("company",""))} · #{esc(jid)}</div>{risk_badge(row)}', unsafe_allow_html=True)
                    st.markdown(score_bar(row.get("match_score")), unsafe_allow_html=True)
                with b:
                    st.markdown(f'<div class="ja-score">{esc(job_score(row))}</div>', unsafe_allow_html=True)
                    if st.button("查看 →", key="dash_" + jid, width="stretch"):
                        go_to("职位详情", jid)
        if jobs:
            if st.button("查看全部职位  →", key="dash_all", width="stretch"):
                go_to("岗位列表")
    with right:
        section("处理进度", "PIPELINE HEALTH")
        with st.container(border=True):
            steps = [("邮件与链接导入", INDEX.is_file()), ("JD 读取", bool(count_jd)),
                     ("岗位评分", SCREEN.is_file()), ("Word 草稿", bool(count_resume))]
            for label, available in steps:
                st.markdown(f'<div class="ja-mini-step"><span class="ja-dot" style="background:{"#46d6b9" if available else "#667991"}"></span><span>{esc(label)}</span><span style="margin-left:auto;color:{"#67dbcb" if available else "#8398b0"};">{"已就绪" if available else "未完成"}</span></div>', unsafe_allow_html=True)
            st.markdown('<div class="ja-footnote">此处显示本地数据和文件状态，不代表岗位资格或申请已通过。</div>', unsafe_allow_html=True)
        st.write("")
        section("下一步操作", "QUICK ACTIONS")
        if st.button("运行最新邮箱 →", key="quick_run", width="stretch"):
            go_to("运行任务")
        if st.button("创建定制简历 →", key="quick_resume", width="stretch"):
            go_to("简历中心")
        st.write("")
        st.caption("隐私：当前页面只在本地读取工作目录，不对外展示 Google 凭据或 API Key。")


def listings(jobs: list[dict]):
    section("所有机会", "JOB EXPLORER")
    a, b, c = st.columns([2.5, 1.3, 1.2])
    with a:
        search = st.text_input("搜索", placeholder="搜索公司、职位或 Job ID", label_visibility="collapsed")
    levels = sorted({str(row.get("priority", "未筛选")) for row in jobs})
    with b:
        chosen = st.selectbox("类型", ["全部状态"] + levels, label_visibility="collapsed")
    with c:
        sorting = st.selectbox("排序", ["匹配度最高", "匹配度最低", "公司名称"], label_visibility="collapsed")
    matching = [row for row in jobs if
                search.casefold() in (str(row.get("title", "")) + " " + str(row.get("company", "")) + " " + row["job_id"]).casefold()
                and (chosen == "全部状态" or str(row.get("priority", "未筛选")) == chosen)]
    if sorting == "匹配度最低":
        matching.sort(key=lambda r: (r.get("match_score") is None, r.get("match_score") or 0))
    elif sorting == "公司名称":
        matching.sort(key=lambda r: str(r.get("company", "")).casefold())
    st.markdown(f'<div class="ja-muted">找到 {len(matching)} 个结果 · 匹配分为规则评分，不等于录取概率或工作许可</div>', unsafe_allow_html=True)
    st.write("")
    if not matching:
        st.info("没有符合筛选条件的职位。")
    for row in matching:
        jid = row["job_id"]
        with st.container(border=True):
            left, mid, right = st.columns([6, 1.2, 1.4], gap="medium", vertical_alignment="center")
            with left:
                st.markdown(f'<div class="ja-job-name">{esc(row.get("title", ""))}</div><div class="ja-job-company">{esc(row.get("company", ""))} · #{esc(jid)} · 截止 {esc(row.get("deadline") or "待确认")}</div>{risk_badge(row)}', unsafe_allow_html=True)
                if flags_for(row):
                    st.markdown(f'<div class="ja-small" style="margin-top:9px;">⚠ {esc(flags_for(row)[0])}</div>', unsafe_allow_html=True)
            with mid:
                st.markdown(f'<div class="ja-score">{esc(job_score(row))}</div>', unsafe_allow_html=True)
                st.markdown(score_bar(row.get("match_score")), unsafe_allow_html=True)
            with right:
                st.caption(("JD ✓" if jd_file(row) else "JD 待提取") + " · " + ("Word ✓" if resumes_for(jid, ".docx") else "Word —"))
                if st.button("查看岗位 →", key="list_" + jid, width="stretch"):
                    go_to("职位详情", jid)


def choose_job(jobs: list[dict], *, key: str) -> dict:
    job_by_id = {row["job_id"]: row for row in jobs}
    ids = list(job_by_id)
    current = st.session_state.get("chosen_job_id")
    if current not in ids:
        current = ids[0]
    jid = st.selectbox("选择一个职位", ids, index=ids.index(current), format_func=lambda x: job_label(job_by_id[x]), key=key)
    st.session_state["chosen_job_id"] = jid
    return job_by_id[jid]


def detail(jobs: list[dict]):
    section("职位档案", "JOB INTELLIGENCE")
    if not jobs:
        st.info("还没有职位。")
        return
    row = choose_job(jobs, key="detail_selected")
    jid = row["job_id"]
    st.markdown(f'<div class="ja-detail-head"><div class="ja-overline">JOB ID · {esc(jid)}</div><div class="ja-detail-role">{esc(row.get("title",""))}</div><div class="ja-detail-company">{esc(row.get("company",""))}</div></div>', unsafe_allow_html=True)
    a, b, c, d = st.columns(4)
    with a: kpi("技术匹配", job_score(row) + " / 100")
    with b: kpi("申请截止", row.get("deadline") or "待核实")
    with c: kpi("JD 文件", "已保存" if jd_file(row) else "缺失")
    with d: kpi("简历审核稿", "已有" if resumes_for(jid, ".docx") else "未生成")
    st.write("")
    left, right = st.columns([2.1, 1], gap="large")
    with left:
        t1, t2 = st.tabs(["完整 JD", "技能与匹配"])
        with t1:
            path = jd_file(row)
            if path:
                content = path.read_text(encoding="utf-8-sig", errors="replace")
                st.markdown(f'<div class="ja-jd">{esc(content)}</div>', unsafe_allow_html=True)
                download_file("↓ 下载 JD 原文", path, key="download_jd_"+jid, mime="text/plain")
            else:
                st.warning("还没有可用的职位正文。先去「运行任务」补充 JD。")
        with t2:
            items = row.get("matched_skills", [])
            st.markdown("**简历中已确认的相关技能关键词**")
            st.write(" · ".join(items) if isinstance(items, list) and items else "筛选报告没有识别到可证实的匹配技能。")
            keywords = row.get("jd_keywords", [])
            st.markdown("**JD 涉及的技术**")
            st.write(" · ".join(keywords) if isinstance(keywords, list) and keywords else "暂无提取结果。")
            st.caption("JD 技术要求不自动等于你本人具备的技能。")
    with right:
        with st.container(border=True):
            st.markdown('<div class="ja-panel-title">资格与申请限制</div><div class="ja-panel-sub">在生成简历前需要关注</div>', unsafe_allow_html=True)
            st.markdown(risk_badge(row), unsafe_allow_html=True)
            notes = flags_for(row)
            if notes:
                for note in notes:
                    st.warning(note)
            else:
                st.info("未自动识别到限制，不代表申请资格已确认。")
            if eligibility_hold(row):
                st.caption("此岗位被默认暂缓；如仍想制作审核稿，可在简历中心显式确认。")
            url = safe_handshake_url(row.get("url"))
            if url:
                st.link_button("↗ 打开 Handshake 原网页", url, width="stretch")
        with st.container(border=True):
            st.markdown('<div class="ja-panel-title">相关文档</div>', unsafe_allow_html=True)
            docs = resumes_for(jid, ".docx")
            st.write("Word 审核稿：" + (f"{len(docs)} 份" if docs else "暂无"))
            if docs:
                download_file("↓ 下载最新 Word", docs[0], key="detail_doc_"+jid, mime=MIME_DOCX)
            if st.button("去简历中心 →", key="detail_resume_"+jid, width="stretch"):
                go_to("简历中心", jid)


def cleanup_word(path: Path) -> Path:
    from docx import Document
    doc = Document(path)
    # Remove pagination markings; do not change the original file.
    for paragraph in doc.paragraphs:
        paragraph.paragraph_format.keep_together = False
        paragraph.paragraph_format.keep_with_next = False
        paragraph.paragraph_format.page_break_before = False
    new = path.with_name(path.stem + "_format_clean.docx")
    doc.save(new)
    return new


def resume_center(jobs: list[dict]):
    section("简历工作室", "RESUME STUDIO")
    st.markdown('<div class="ja-muted">从已抓取的 JD 构建定制简历，Word 和中文审核稿分开保存。不会代替你申请任何职位。</div>', unsafe_allow_html=True)
    if not jobs:
        st.info("暂无岗位数据。")
        return
    row = choose_job(jobs, key="resume_selected")
    jid = row["job_id"]
    existing = resumes_for(jid, ".docx")
    left, right = st.columns([1.4, 1], gap="large")
    with left:
        with st.container(border=True):
            st.markdown('<div class="ja-panel-title">已有简历版本</div><div class="ja-panel-sub">历史版本不会被新生成覆盖</div>', unsafe_allow_html=True)
            if existing:
                version = st.selectbox("选择一个 Word 版本", existing, format_func=lambda p: datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M") + " · " + p.name[-38:], key="version_"+jid)
                st.caption("文件最后更新：" + latest_stamp(version))
                d1, d2 = st.columns(2)
                with d1:
                    download_file("↓ 下载 Word", version, key="word_"+jid, mime=MIME_DOCX)
                with d2:
                    review = version.with_suffix(".md")
                    if review.is_file():
                        download_file("↓ 下载审核说明", review, key="md_"+jid, mime="text/markdown")
                review = version.with_suffix(".md")
                if review.is_file():
                    with st.expander("查看完整英文草稿与中文核对说明"):
                        st.markdown(review.read_text(encoding="utf-8-sig", errors="replace"))
                with st.expander("修复 Word 左侧方块（不调用模型）"):
                    st.caption("从现有 Word 制作一个去除段落分页控制的副本，不消耗 GPT Token，也不会修改原文件。")
                    if st.button("生成修复副本", key="fixword_"+jid):
                        try:
                            clean = cleanup_word(version)
                            st.success("已创建格式修复副本。")
                            st.session_state["clean_file_"+jid] = str(clean)
                        except (ImportError, OSError, ValueError) as exc:
                            st.error(f"Word 修复失败：{type(exc).__name__}: {exc}")
                    fixed_file = version.with_name(version.stem + "_format_clean.docx")
                    if fixed_file.is_file():
                        download_file("↓ 下载修复版 Word", fixed_file, key="clean_doc_"+jid, mime=MIME_DOCX)
            else:
                st.info("这个职位还没有保存过 Word 简历。")
    with right:
        with st.container(border=True):
            st.markdown('<div class="ja-panel-title">生成新审核稿</div><div class="ja-panel-sub">复用当前 GPT-5.4-mini 与原 Word 模板</div>', unsafe_allow_html=True)
            st.markdown(risk_badge(row), unsafe_allow_html=True)
            st.markdown(f'<div class="ja-small" style="margin-top:9px;">技术匹配 {esc(job_score(row))} 分 · Job ID {esc(jid)}</div>', unsafe_allow_html=True)
            if not jd_file(row):
                st.error("缺少已验证的 JD，本次不可生成。")
                return
            holds = eligibility_hold(row)
            for msg in holds:
                st.warning(msg)
            for f in flags_for(row)[:3]:
                st.caption("⚠ " + f)
            allow_risk = st.checkbox("我理解岗位存在资格/截止风险，仍希望创建审核稿", key="allow_risk_"+jid) if holds else False
            force = st.checkbox("重新生成已处理过的内容（可能再次付费）", key="force_"+jid)
            approve = st.checkbox("我确认这次将调用 OpenAI API 并产生费用，仅生成待审核文件", key="approve_"+jid)
            if st.button("✦ 生成定制 Word", type="primary", width="stretch", key="generate_"+jid,
                         disabled=not approve or (bool(holds) and not allow_risk)):
                previous_docs = {p.resolve() for p in resumes_for(jid, ".docx")}
                arguments = ["--job-id", jid, "--yes"]
                if allow_risk:
                    arguments.append("--allow-risk")
                if force:
                    arguments.append("--force")
                with st.spinner("正在运行现有简历模型与 Word 导出模块…"):
                    code, log = execute_backend("run_screened_resumes.py", arguments)
                execution_result(code, log, "简历生成")
                updated = resumes_for(jid, ".docx")
                created = [p for p in updated if p.resolve() not in previous_docs]
                if created:
                    st.success("检测到本次新生成的 Word 文件。")
                    download_file("↓ 下载刚生成的 Word", created[0], key="just_word_"+jid, mime=MIME_DOCX)
                elif updated:
                    st.info("未检测到新的 Word 文件；可以下载上面的已有版本。若需重新生成，请查看日志与去重状态。")
                else:
                    st.warning("尚未发现 Word 文件。请检查运行日志。")
            st.markdown('<div class="ja-footnote">提醒：F-1/CPT、到岗地点等要求必须向学校或雇主核实。评分不是合法工作许可证明。</div>', unsafe_allow_html=True)


def tasks():
    section("任务控制台", "AUTOMATION CONSOLE")
    st.markdown('<div class="ja-muted">运行你已经写好的后端脚本。每次启动都需明确点击；不会自动投递，也不会在这里自动触发付费简历生成。</div>', unsafe_allow_html=True)
    with st.container(border=True):
        options = {
            "仅重新进行岗位评分": ("run_email_jobs.py", ["--screen-only"]),
            "补充尚未提取的 JD": ("run_email_jobs.py", ["--skip-email"]),
            "完整同步 Gmail → Handshake → JD → 筛选": ("run_full_agent.py", []),
        }
        selected = st.radio("选择任务", list(options), horizontal=False)
        filename, args = options[selected]
        if selected.startswith("完整同步"):
            max_emails = st.number_input("最多扫描多少封邮件", min_value=1, max_value=100, value=20)
            args = ["--max-emails", str(int(max_emails))]
        st.caption("全部流程有可能弹出 Google 授权或浏览器。请保持同一登录会话，避免两个 Playwright 程序同时占用 browser_session。")
        if st.button("▶ 开始执行", type="primary", width="stretch"):
            with st.spinner("正在运行本地任务…"):
                code, log = execute_backend(filename, args)
            execution_result(code, log, selected)
    last = st.session_state.get("last_exec")
    if last:
        st.write("")
        section("最近一次执行", "ACTIVITY LOG")
        st.caption(last["task"] + " · " + ("退出码 0" if last["code"] == 0 else f"退出码 {last['code']}"))
        with st.expander("展开完整日志"):
            st.code(last["log"][-65000:], language="text")
        st.download_button("↓ 下载日志", last["log"], file_name="job_agent_log.txt", mime="text/plain", key="task_log_dl")
    st.write("")
    section("分析报告", "EXPORTS")
    c1, c2 = st.columns(2)
    report = JOBS / "job_screen_report.md"
    csv = JOBS / "job_screen_results.csv"
    with c1:
        if report.is_file():
            download_file("↓ 下载岗位筛选报告", report, "report_md", "text/markdown")
        else:
            st.caption("尚未生成 Markdown 筛选报告")
    with c2:
        if csv.is_file():
            download_file("↓ 下载评分 CSV", csv, "report_csv", "text/csv")
        else:
            st.caption("尚未生成 CSV 报告")


def main():
    page = sidebar()
    jobs = load_jobs()
    st.markdown('<div class="ja-overline" style="margin:0 0 13px;letter-spacing:.17em;color:#7c91ad;">JOB AGENT / ' + esc(page) + '</div>', unsafe_allow_html=True)
    if page == "总览":
        dashboard(jobs)
    elif page == "岗位列表":
        listings(jobs)
    elif page == "职位详情":
        detail(jobs)
    elif page == "简历中心":
        resume_center(jobs)
    else:
        tasks()


if __name__ == "__main__":
    main()
