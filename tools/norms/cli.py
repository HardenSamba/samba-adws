import argparse
from pathlib import Path
from typing import Dict, List

from .report import check_file


# Expands the given paths into the list of .py files to check, dropping any
# whose path contains an excluded fragment (e.g. vendored dirs).
def iter_files(paths: List[str], exclude: List[str]) -> List[Path]:
    found: List[Path] = []
    for raw in paths:
        target = Path(raw)
        if target.is_dir():
            found.extend(sorted(target.rglob("*.py")))
        elif target.suffix == ".py":
            found.append(target)
    return [p for p in found if not any(x in p.as_posix() for x in exclude)]


# Parses the command-line flags into a namespace.
def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ADWS norms checker")
    parser.add_argument("paths", nargs="*")
    parser.add_argument("--max-line", type=int, default=100)
    parser.add_argument("--max-functions", type=int, default=5)
    parser.add_argument("--max-classes", type=int, default=1)
    parser.add_argument("--max-func-lines", type=int, default=20)
    parser.add_argument("--max-nesting", type=int, default=2)
    parser.add_argument("--require-headers", action="store_true")
    parser.add_argument("--exclude", action="append", default=[])
    return parser.parse_args()


# Builds the numeric limits dict from the parsed args.
def _limits_from(args: argparse.Namespace) -> Dict[str, int]:
    return {
        "max_line": args.max_line,
        "max_functions": args.max_functions,
        "max_classes": args.max_classes,
        "max_func_lines": args.max_func_lines,
        "max_nesting": args.max_nesting,
    }


# Runs the checker over every file and prints the violation summary.
def main() -> int:
    args = _parse_args()
    limits = _limits_from(args)
    excluded = ["src/nettcp/", "src/wcf/", *args.exclude]
    files = iter_files(args.paths or ["src", "classes"], excluded)
    violations: List[str] = []
    for path in files:
        violations.extend(check_file(path, limits, args.require_headers))
    print("\n".join(violations))
    print(f"\n{len(violations)} violation(s) across "
          f"{len(files)} file(s).")
    return 1 if violations else 0
