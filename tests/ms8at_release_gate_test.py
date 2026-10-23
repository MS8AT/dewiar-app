"""MS8AT fork must not create full-tree Dewiar releases.

Static offline guard: no GitHub API, credentials, Actions, or model calls.
"""
from pathlib import Path
import re
import sys


ROOT = Path(__file__).resolve().parents[1]
workflow = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
header, jobs = workflow.split("jobs:", 1)

checks = {
    "top-level token is read-only": re.search(r"(?m)^permissions:\s*\n\s+contents:\s+read\s*$", header) is not None,
    "top-level token cannot write": "contents: write" not in header,
    "tag job is official-repository-only": "if: github.repository == 'dwr-git/dewiar-app'" in jobs,
    "both publishing jobs are gated": jobs.count("if: github.repository == 'dwr-git/dewiar-app'") >= 2,
    "write permission stays job-scoped": jobs.count("contents: write") >= 2,
}

failed = [name for name, passed in checks.items() if not passed]
for name, passed in checks.items():
    print(("PASS" if passed else "FAIL") + ": " + name)
if failed:
    raise SystemExit("release gate failures: " + ", ".join(failed))
print("ALL OK")
sys.exit(0)
