import ast
from typing import List

from .kinds import SCOPE_TYPES


# Returns the first source line of a def/class, counting any decorators.
def _header_anchor(node: ast.AST) -> int:
    decorators = getattr(node, "decorator_list", [])
    if decorators:
        return min(dec.lineno for dec in decorators)
    return node.lineno


# Tells whether the given 1-based source line is a `#` comment line.
def _is_comment(lines: List[str], lineno: int) -> bool:
    if lineno < 1 or lineno > len(lines):
        return False
    return lines[lineno - 1].lstrip().startswith("#")


# Lists line numbers of classes/functions with no `#` header block above them.
def missing_headers(tree: ast.AST, lines: List[str]) -> List[int]:
    out: List[int] = []
    for node in ast.walk(tree):
        if not isinstance(node, SCOPE_TYPES):
            continue
        if not _is_comment(lines, _header_anchor(node) - 1):
            out.append(node.lineno)
    return sorted(out)
