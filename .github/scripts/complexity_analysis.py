#!/usr/bin/env python3
"""
Complexity gate: post per-function metric cards as a PR comment.
Each function gets a 2-column table (metric | branch value) + delta vs main.
Never blocks merge — informational only.
"""
import argparse
import ast
import re
import subprocess
import sys
from pathlib import Path

import lizard


def _cc_badge(cc: int) -> str:
    if cc <= 5:  return f"{cc} ✅"
    if cc <= 10: return f"{cc} ⚠️"
    if cc <= 15: return f"{cc} 🟠"
    return f"{cc} 🔴"


def _delta(before: int | None, after: int) -> str:
    if before is None: return "new"
    d = after - before
    if d > 0:  return f"+{d} ⚠️"
    if d < 0:  return f"{d} ✅"
    return "—"


def _is_recursive(source: str, name: str) -> bool:
    try:
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        fn = child.func
                        if (isinstance(fn, ast.Name) and fn.id == name) or \
                           (isinstance(fn, ast.Attribute) and fn.attr == name):
                            return True
    except SyntaxError:
        pass
    return False


def _is_orphan(filepath: str, name: str) -> bool:
    r = subprocess.run(
        ["grep", "-r", "--include=*.py", "-l", rf"\b{re.escape(name)}\b", "backend/"],
        capture_output=True, text=True,
    )
    return not any(f for f in r.stdout.strip().splitlines() if f != filepath)


def _baseline_cc(filepath: str, func_name: str, baseline_dir: str) -> int | None:
    baseline = Path(baseline_dir) / filepath
    if not baseline.exists():
        return None
    info = lizard.analyze_file(str(baseline))
    if not info:
        return None
    for fn in info.function_list:
        if fn.name == func_name:
            return fn.cyclomatic_complexity
    return None


def _shorten(filepath: str) -> str:
    for prefix in ("backend/archimedes/", "backend/", "ui/src/"):
        if filepath.startswith(prefix):
            return filepath[len(prefix):]
    return filepath


def analyze(changed_files: list[str], baseline_dir: str) -> str:
    blocks = []

    for filepath in changed_files:
        p = Path(filepath)
        if not p.exists():
            continue
        info = lizard.analyze_file(filepath)
        if not info:
            continue

        is_py = p.suffix == ".py"
        source = p.read_text(errors="replace") if is_py else ""

        for fn in info.function_list:
            nesting = getattr(fn, "max_nesting_depth", 0)
            recursive = is_py and _is_recursive(source, fn.name)
            orphan = is_py and _is_orphan(filepath, fn.name)
            base_cc = _baseline_cc(filepath, fn.name, baseline_dir)

            rows = [
                ("CC",        _cc_badge(fn.cyclomatic_complexity)),
                ("Δ CC",      _delta(base_cc, fn.cyclomatic_complexity)),
                ("Nesting",   f"{nesting}{'⚠️' if nesting >= 3 else ''}"),
                ("Recursive", "✅" if recursive else "—"),
                ("Orphan",    "⚠️" if orphan else "—"),
            ]

            header = f"### `{fn.name}` · `{_shorten(filepath)}:{fn.start_line}`"
            table = ["| Metric | Branch |", "|---|---|"]
            table += [f"| {k} | {v} |" for k, v in rows]
            blocks.append(header + "\n" + "\n".join(table))

    if not blocks:
        return "## 🔬 Complexity\n\nNo functions found in changed files.\n"

    return "## 🔬 Complexity\n\n" + "\n\n".join(blocks) + \
           "\n\n*CC: ✅ 1–5 · ⚠️ 6–10 · 🟠 11–15 · 🔴 16+*\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--changed-files", nargs="+", required=True)
    parser.add_argument("--baseline-dir", required=True)
    parser.add_argument("--output-md", required=True)
    args = parser.parse_args()

    targets = [f for f in args.changed_files
               if Path(f).suffix in {".py", ".js", ".ts", ".jsx", ".tsx"}]
    try:
        md = analyze(targets, args.baseline_dir) if targets \
            else "## 🔬 Complexity\n\nNo Python or JS/TS files changed.\n"
    except Exception as exc:
        import traceback
        md = (
            "## 🔬 Complexity\n\n"
            f"> ⚠️ `{exc}`\n\n"
            f"<details><summary>Traceback</summary>\n\n```\n{traceback.format_exc()}\n```\n\n</details>\n"
        )

    Path(args.output_md).write_text(md)


if __name__ == "__main__":
    main()
