#!/usr/bin/env python3
"""Require cloud/core checks and compare the full suite with the actual base.

main already has unrelated failing MR fixture/render expectations. Do not hide
or hard-code those test IDs, or let a new failure pass as an old failure.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

CORE = ["tests/cloud", "tests/test_pdf_batch_run.py", "tests/test_building_registry.py", "tests/test_building_summaries.py", "tests/test_schema_migration.py", "tests/test_schema_reproducibility_pipeline.py", "tests/test_schema_guard.py", "tests/test_build_smoke.py"]


def failures(path: Path) -> set[str]:
    return {case.attrib.get("classname", "") + "::" + case.attrib["name"] for case in ET.parse(path).iter("testcase") if case.find("failure") is not None or case.find("error") is not None}


def run_tests(root: Path, args: list[str], output: Path, name: str):
    report = output / f"{name}.xml"
    test_env = dict(os.environ)
    # Each tree's pytest.ini supplies its own src path. Existing subprocess
    # tests set PYTHONPATH themselves; an inherited value breaks one on main.
    test_env.pop("PYTHONPATH", None)
    result = subprocess.run([sys.executable, "-m", "pytest", "-q", *args, f"--junitxml={report}"], cwd=root, text=True, capture_output=True, env=test_env)
    (output / f"{name}.log").write_text(result.stdout + result.stderr, encoding="utf-8")
    if result.returncode not in (0, 1) or not report.is_file():
        print((result.stdout + result.stderr)[-20000:])
        raise RuntimeError(f"{name}_test_execution_failed")
    return result.returncode, failures(report)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, help="PR base SHA or previous main commit, never the candidate itself")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    output = root / "work/test-comparison"
    output.mkdir(parents=True, exist_ok=True)
    base_sha = subprocess.check_output(["git", "rev-parse", args.base], text=True).strip()
    candidate_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    if base_sha == candidate_sha:
        raise SystemExit("base must be the pre-change commit")
    code, required = run_tests(root, CORE, output, "required")
    if code or required:
        print((output / "required.log").read_text(encoding="utf-8")[-20000:])
        raise SystemExit("required cloud/core tests failed; see private work/test-comparison/required.log")
    baseline = output / "baseline"
    subprocess.run(["git", "worktree", "add", "--detach", str(baseline), base_sha], check=True, capture_output=True)
    try:
        _, old = run_tests(baseline, [], output, "baseline")
        _, new = run_tests(root, [], output, "candidate")
    finally:
        subprocess.run(["git", "worktree", "remove", "--force", str(baseline)], check=True, capture_output=True)
    added, fixed = new - old, old - new
    result = {"base_sha": base_sha, "candidate_sha": candidate_sha, "required_tests": "passed", "baseline_failures": len(old), "candidate_failures": len(new), "new_failures": sorted(added), "fixed_failures": sorted(fixed), "remaining_existing_failures": sorted(new & old)}
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    (output / "comparison.json").write_text(rendered, encoding="utf-8")
    print(rendered)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a") as stream:
            stream.write("Cloud/core tests must all pass. Full-suite comparison (existing failures remain visible):\n\n```json\n" + rendered + "\n```\n")
    if added:
        raise SystemExit("new full-suite failures detected")


if __name__ == "__main__":
    main()
