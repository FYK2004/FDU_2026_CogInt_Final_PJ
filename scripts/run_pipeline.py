"""One-command offline reproduction from any working directory."""
import argparse
import datetime as dt
import os
from pathlib import Path
import subprocess
import sys


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--as-of", type=dt.date.fromisoformat, default=dt.date(2026, 10, 14))
    ap.add_argument("--skip-figures", action="store_true")
    args = ap.parse_args()
    root = Path(__file__).resolve().parents[1]
    env = dict(os.environ, PJ_AS_OF=args.as_of.isoformat(), PYTHONUTF8="1")
    scripts = ["build_evidence_index.py", "analyze_term_structure.py", "milestone_model.py", "calibrate_model.py"]
    if not args.skip_figures:
        scripts += ["make_figures.py", "make_pipeline_figure.py"]
    scripts += ["build_report_markdown.py"]
    for name in scripts:
        subprocess.run([sys.executable, "-X", "utf8", str(root/"scripts"/name)], cwd=root, env=env, check=True)


if __name__ == "__main__":
    main()
