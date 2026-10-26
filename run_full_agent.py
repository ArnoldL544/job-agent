"""One entry point for Gmail -> JD -> screening -> review queue (optional resume draft)."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run(filename: str, args: list[str]) -> None:
    script = ROOT / filename
    if not script.is_file():
        raise FileNotFoundError(f"找不到 {script}")
    command = [sys.executable, str(script), *args]
    print("\n>>> " + " ".join(command), flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Gmail→Handshake→JD→岗位筛选→人工选定后生成审核简历")
    parser.add_argument("--skip-email", action="store_true", help="使用已导入的职位 URL")
    parser.add_argument("--screen-only", action="store_true", help="不读取邮箱和 JD，仅重新筛选现有 JD")
    parser.add_argument("--draft-job", help="本次同时为指定 Job ID 生成一份审核稿（需确认）")
    parser.add_argument("--allow-risk", action="store_true", help="明确允许为地点/资格待核实等低优先级职位制作草稿")
    parser.add_argument("--force-draft", action="store_true", help="为相同输入重生成简历草稿")
    parser.add_argument("--max-emails", type=int, default=20, help="邮件导入上限（默认 20）")
    args = parser.parse_args()

    first_args = []
    if args.screen_only:
        first_args = ["--screen-only"]
    else:
        if args.skip_email:
            first_args.append("--skip-email")
        first_args += ["--max-emails", str(args.max_emails)]
    run("run_email_jobs.py", first_args)
    run("run_screened_resumes.py", ["--list"])
    if args.draft_job:
        next_args = ["--job-id", args.draft_job]
        if args.allow_risk:
            next_args.append("--allow-risk")
        if args.force_draft:
            next_args.append("--force")
        run("run_screened_resumes.py", next_args)
    else:
        print("\n已完成筛选。没有指定 --draft-job，因此未调用简历生成模型。")


if __name__ == "__main__":
    try:
        main()
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(f"Pipeline stopped: {exc}", file=sys.stderr)
        raise SystemExit(1)
