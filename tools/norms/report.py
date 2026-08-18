import ast
from pathlib import Path
from typing import Dict, List

from .headers import missing_headers
from .kinds import DEF_TYPES
from .nesting import depth_of
from .sizing import count_nodes, func_length, long_lines


# Flags files exceeding the per-file class or function counts.
def _struct_violations(path: Path, tree: ast.AST,
                       limits: Dict[str, int]) -> List[str]:
    classes, funcs = count_nodes(tree)
    out: List[str] = []
    if classes > limits["max_classes"]:
        out.append(f"{path}:1: {classes} classes "
                   f"(max {limits['max_classes']})")
    if funcs > limits["max_functions"]:
        out.append(f"{path}:1: {funcs} functions "
                   f"(max {limits['max_functions']})")
    return out


# Flags functions over the line-count or nesting-depth limits.
def _func_violations(path: Path, tree: ast.AST, lines: List[str],
                     limits: Dict[str, int]) -> List[str]:
    out: List[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, DEF_TYPES):
            continue
        length = func_length(node, lines)
        if length > limits["max_func_lines"]:
            out.append(f"{path}:{node.lineno}: {node.name}() {length} "
                       f"lines (max {limits['max_func_lines']})")
        depth = depth_of(node.body, 0)
        if depth > limits["max_nesting"]:
            out.append(f"{path}:{node.lineno}: {node.name}() nesting "
                       f"{depth} (max {limits['max_nesting']})")
    return out


# Runs every norm check on one file and returns its violation strings.
def check_file(path: Path, limits: Dict[str, int],
               require_headers: bool) -> List[str]:
    source = path.read_text(encoding="utf-8")
    lines = source.splitlines()
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [f"{path}:{exc.lineno}: syntax error: {exc.msg}"]
    out = _struct_violations(path, tree, limits)
    out += _func_violations(path, tree, lines, limits)
    out += [f"{path}:{n}: line > {limits['max_line']} chars"
            for n in long_lines(lines, limits["max_line"])]
    if require_headers:
        out += [f"{path}:{n}: missing '#' header block before def/class"
                for n in missing_headers(tree, lines)]
    return out
