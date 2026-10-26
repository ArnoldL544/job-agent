"""One command: import Handshake links, read JDs, then screen job fit/eligibility.

Usage:
    python run_email_jobs.py --skip-email --dry-run
    python run_email_jobs.py --skip-email --match "Clark Associates" --limit 1
    python run_email_jobs.py

Gmail import and JD extraction launch separate browsers sequentially, so the
same persistent browser_session/ is never used by two processes at once.
"""

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def run_module(filename, args):
    script = ROOT / filename
    if not script.is_file():
        raise FileNotFoundError(f"Missing required script: {script}")
    command = [sys.executable, str(script), *args]
    print("\n>>> " + " ".join(command), flush=True)
    subprocess.run(command, cwd=str(ROOT), check=True)


def main():
    parser = argparse.ArgumentParser(description="Handshake Gmail -> verified URLs -> saved JDs")
    parser.add_argument("--skip-email", action="store_true", help="Use already imported jobs JSON")
    parser.add_argument("--match", default="", help="Only process a company or job title")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N pending job descriptions")
    parser.add_argument("--max-emails", type=int, default=20, help="Gmail messages to check in importer")
    parser.add_argument("--dry-run", action="store_true", help="Only preview pending JDs (implies --skip-email)")
    parser.add_argument("--force", action="store_true", help="Re-extract even already saved JDs")
    parser.add_argument("--skip-screen", action="store_true", help="Skip job screening after JD extraction")
    parser.add_argument("--screen-only", action="store_true", help="Screen existing JDs without Gmail or browser")
    args = parser.parse_args()
    if args.limit < 0 or args.max_emails < 1:
        parser.error("--limit must be >= 0 and --max-emails must be >= 1")

    if args.screen_only:
        screen_args = ["--match", args.match] if args.match else []
        run_module("job_screen.py", screen_args)
        return

    if not (args.skip_email or args.dry_run):
        importer_args = ["--max-emails", str(args.max_emails)]
        if args.match:
            importer_args += ["--match", args.match]
        run_module("handshake_email_import.py", importer_args)

    reader_args = ["--from-email"]
    if args.match:
        reader_args += ["--match", args.match]
    if args.limit:
        reader_args += ["--limit", str(args.limit)]
    if args.dry_run:
        reader_args += ["--dry-run"]
    if args.force:
        reader_args += ["--force"]
    reader_failure = None
    try:
        run_module("job_reader.py", reader_args)
    except subprocess.CalledProcessError as exc:
        reader_failure = exc
        print("JD extraction encountered errors; completed JDs remain available.", flush=True)
    if args.dry_run:
        if reader_failure is not None:
            raise reader_failure
        print("\nPreview completed. No browser opened, no files modified.")
    else:
        if not args.skip_screen:
            # Also screen already-saved JDs if one new extraction failed.
            # Preserve the nonzero exit status so failures aren't hidden.
            run_module("job_screen.py", [])
        if reader_failure is not None:
            raise reader_failure
        print("\nPipeline finished: Gmail job URLs -> saved job descriptions"
              + ("." if args.skip_screen else " -> screening report."))


if __name__ == "__main__":
    try:
        main()
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        print(f"Pipeline stopped: {exc}", file=sys.stderr)
        sys.exit(1)
