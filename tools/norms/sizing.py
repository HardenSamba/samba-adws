import ast
import tokenize
from pathlib import Path
from typing import List, Tuple

from .kinds import DEF_TYPES


# Counts the classes and functions in a parsed module.
def count_nodes(tree: ast.AST) -> Tuple[int, int]:
    classes = sum(isinstance(n, ast.ClassDef) for n in ast.walk(tree))
    funcs = sum(isinstance(n, DEF_TYPES) for n in ast.walk(tree))
    return classes, funcs


# Tells whether a def/class node opens with a string docstring.
def _has_docstring(node: ast.AST) -> bool:
    body = getattr(node, "body", [])
    if not body:
        return False
    first = body[0]
    return (isinstance(first, ast.Expr)
            and isinstance(first.value, ast.Constant)
            and isinstance(first.value.value, str))


# Counts a function's body lines, excluding blanks, comments and docstring.
def func_length(node: ast.AST, lines: List[str]) -> int:
    body = node.body
    start = body[0].lineno
    end = node.end_lineno or start
    if _has_docstring(node):
        start = (body[0].end_lineno or body[0].lineno) + 1
    count = 0
    for idx in range(start, end + 1):
        text = lines[idx - 1].strip()
        if text and not text.startswith("#"):
            count += 1
    return count


# Lists 1-based line numbers exceeding the length limit.
def long_lines(lines: List[str], limit: int) -> List[int]:
    if limit <= 0:
        return []
    return [i + 1 for i, ln in enumerate(lines)
            if len(ln.rstrip()) > limit]


# Lists 1-based line numbers of `#` comments past the first line.
def comment_lines(path: Path) -> List[int]:
    with tokenize.open(str(path)) as handle:
        toks = list(tokenize.generate_tokens(handle.readline))
    return [t.start[0] for t in toks
            if t.type == tokenize.COMMENT and t.start[0] > 1]
