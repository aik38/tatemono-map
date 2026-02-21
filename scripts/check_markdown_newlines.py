#!/usr/bin/env python3
"""Fail when key markdown docs are likely minified into a few lines."""

from pathlib import Path
import sys

TARGETS = {
    Path("README.md"): 20,
    Path("PLAN.md"): 20,
    Path("docs/spec.md"): 20,
    Path("docs/wbs.md"): 20,
}

errors = []
for path, min_newlines in TARGETS.items():
    if not path.exists():
        errors.append(f"missing file: {path}")
        continue
    text = path.read_text(encoding="utf-8")
    newline_count = text.count("\n")
    if newline_count < min_newlines:
        errors.append(
            f"{path}: newline count {newline_count} < required {min_newlines} (document may be minified)"
        )

if errors:
    print("Markdown newline check failed:")
    for err in errors:
        print(f"- {err}")
    sys.exit(1)

print("Markdown newline check passed.")
