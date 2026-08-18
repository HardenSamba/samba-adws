import ast
from typing import List

from .kinds import BLOCK_TYPES, SCOPE_TYPES


# Returns the deepest block-nesting level reached in a list of statements.
def depth_of(stmts: List[ast.stmt], level: int) -> int:
    best = level
    for stmt in stmts:
        best = max(best, _node_depth(stmt, level))
    return best


# Returns the nesting depth contributed by a single statement node.
def _node_depth(node: ast.stmt, level: int) -> int:
    if isinstance(node, SCOPE_TYPES):
        return level
    if not isinstance(node, BLOCK_TYPES):
        return level
    inner = level + 1
    best = depth_of(node.body, inner)
    best = max(best, _orelse_depth(node, inner, level))
    best = max(best, depth_of(getattr(node, "finalbody", []), inner))
    for handler in getattr(node, "handlers", []):
        best = max(best, depth_of(handler.body, inner))
    return best


# Returns the depth of an else/elif branch, treating elif as same-level.
def _orelse_depth(node: ast.stmt, inner: int, level: int) -> int:
    orelse = getattr(node, "orelse", [])
    if (isinstance(node, ast.If) and len(orelse) == 1
            and isinstance(orelse[0], ast.If)):
        return _node_depth(orelse[0], level)
    return depth_of(orelse, inner)
