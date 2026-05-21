"""Check mypy regressions against a checked-in baseline.

Compares the current ``mypy src`` output against ``scripts/mypy-baseline.txt``.

Exit codes:
    0  No new errors introduced (existing errors may have disappeared).
    1  At least one new error is present that is not in the baseline.
    2  Internal error running mypy or reading the baseline.

Usage:
    uv run --extra dev python scripts/check_mypy_regressions.py
    uv run --extra dev python scripts/check_mypy_regressions.py --update

Line numbers are deliberately excluded from the comparison key because any edit
shifts every line below it, which would produce false-positive regressions.
The key is ``path: message [code]`` aggregated as a multiset so repeated
identical errors at different lines still count.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
BASELINE_PATH = REPO_ROOT / "scripts" / "mypy-baseline.txt"
MYPY_TARGET = "src"

ERROR_LINE_RE = re.compile(
    r"^(?P<path>[^:]+):(?P<line>\d+):\s*error:\s*"
    r"(?P<message>.*?)\s*\[(?P<code>[a-z0-9_-]+)\]\s*$"
)


def _normalize_path(raw_path: str) -> str:
    abs_prefix = f"{REPO_ROOT}/"
    if raw_path.startswith(abs_prefix):
        return raw_path[len(abs_prefix) :]
    return raw_path


def _normalize_error(match: re.Match[str]) -> str:
    return f"{_normalize_path(match['path'])}: {match['message']} [{match['code']}]"


class MypyInvocationError(RuntimeError):
    """Raised when mypy cannot run (config error, internal crash, missing install)."""


def run_mypy() -> str:
    proc = subprocess.run(
        [sys.executable, "-m", "mypy", MYPY_TARGET],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    # mypy exits 0 when no errors, 1 when type errors are found. Any other code
    # means mypy itself failed (bad config, missing import root, internal crash).
    # Treat anything else as a hard failure so the gate cannot silently pass.
    if proc.returncode not in (0, 1):
        raise MypyInvocationError(
            f"mypy exited with code {proc.returncode}\n"
            f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        )
    return proc.stdout


def collect_errors(mypy_output: str) -> Counter[str]:
    counter: Counter[str] = Counter()
    for line in mypy_output.splitlines():
        match = ERROR_LINE_RE.match(line)
        if match is not None:
            counter[_normalize_error(match)] += 1
    return counter


def write_baseline(errors: Counter[str]) -> None:
    lines: list[str] = []
    for key in sorted(errors):
        lines.extend([key] * errors[key])
    BASELINE_PATH.write_text("\n".join(lines) + ("\n" if lines else ""))


def read_baseline() -> Counter[str]:
    if not BASELINE_PATH.exists():
        return Counter()
    counter: Counter[str] = Counter()
    for raw in BASELINE_PATH.read_text().splitlines():
        line = raw.strip()
        if line:
            counter[line] += 1
    return counter


def diff_new_errors(current: Counter[str], baseline: Counter[str]) -> list[str]:
    new: list[str] = []
    for key, count in current.items():
        delta = count - baseline.get(key, 0)
        if delta > 0:
            new.extend([key] * delta)
    return sorted(new)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--update",
        action="store_true",
        help="Regenerate the baseline from the current mypy output.",
    )
    args = parser.parse_args(argv)

    try:
        mypy_output = run_mypy()
    except MypyInvocationError as exc:
        print(f"error: failed to run mypy: {exc}", file=sys.stderr)
        return 2
    current = collect_errors(mypy_output)

    if args.update:
        try:
            write_baseline(current)
        except OSError as exc:
            print(f"error: failed to write baseline: {exc}", file=sys.stderr)
            return 2
        rel = BASELINE_PATH.relative_to(REPO_ROOT)
        print(f"Updated baseline at {rel} with {sum(current.values())} errors")
        return 0

    try:
        baseline = read_baseline()
    except OSError as exc:
        print(f"error: failed to read baseline: {exc}", file=sys.stderr)
        return 2
    baseline_count = sum(baseline.values())
    current_count = sum(current.values())
    new_errors = diff_new_errors(current, baseline)

    print(f"mypy baseline:  {baseline_count} errors")
    print(f"mypy current:   {current_count} errors")
    print(f"mypy delta:     {current_count - baseline_count:+d}")

    if new_errors:
        print()
        print(f"New errors not in baseline ({len(new_errors)}):")
        for err in new_errors:
            print(f"  {err}")
        print()
        print("Reproduce locally:")
        print("  uv run --extra dev python -m mypy src")
        print()
        print("If these regressions are intentional (e.g. backlog shrank and")
        print("the message text changed), refresh the baseline:")
        print("  uv run --extra dev python scripts/check_mypy_regressions.py --update")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
