"""No request path can reach a SYSTEM directory session any more.

This is the test that would have caught #8 on the commit that introduced it.
`classes/server/connection.py` built `system_session()` immediately after GSSAPI
succeeded, under a comment saying auth was done - which it was. Authentication
was done and authorization was never asked for, and nothing about a running
server looked wrong: the negotiation logged success and every request worked,
because SYSTEM can do everything.

So the invariant is checked structurally rather than behaviourally. A test that
needed a denied write to prove it would need a domain, a second principal and an
ACL, and would therefore not run anywhere the mistake actually gets made. The
directory tests in `tests/dc/` prove the behaviour; this proves it cannot come
back on a laptop.

The files are parsed rather than searched as text, so the prose in `samba_db.py`
explaining what it used to do does not count as doing it.
"""

import ast
from pathlib import Path
from typing import Any, List, Optional, Set

import pytest

ROOT = Path(__file__).resolve().parents[2]
SEARCHED = ("classes", "src")
# Vendored protocol libraries, excluded for the reason `.pre-commit-config.yaml`
# excludes them: they are not this project's code.
VENDORED = ("nettcp", "wcf")

# The files allowed to name `system_session`, and why each one may.
#
# Neither is a request path, which is the whole of the rule. Adding to this set
# is a decision somebody has to make on purpose, which is why it is a set in a
# test rather than a convention in somebody's head.
DOORS = {
    # The only place that produces one. Callers ask for it by name.
    "classes/directory/maintenance.py",
    # A start-up check that samba loads at all. It calls `system_session()`,
    # discards the result and opens no directory; it runs once, before the
    # listener accepts anything. Left naming it directly because bringing this
    # file into the project norms is a refactor of its own - it holds two
    # classes against a limit of one - and that does not belong in a security
    # fix.
    "classes/server/server.py",
}

# Local maintenance callers under `classes/` and `src/`. There are none: the
# only caller is the DC diagnostic in `tools/`, which this does not scan. A
# request path reaching for `local_session` would fail this.
LOCAL_PATHS: Set[str] = set()

# The two places the caller's identity is taken and immediately guarded, with
# the expression each reads it from. Both must refuse rather than carry on.
GUARDS = [
    ("classes/server/protocol.py", "self.stream.session_info()", "return False"),
    ("classes/server/connection.py", "phase_handler.session_info", "return"),
]


# Every file naming one identifier, by import, call or attribute.
def naming(wanted: str) -> Set[str]:
    files: List[Path] = sorted(path for top in SEARCHED
                               for path in (ROOT / top).rglob("*.py")
                               if not any(part in VENDORED for part in path.parts))
    trees = [(path, ast.parse(path.read_text(encoding="utf-8"))) for path in files]
    return {path.relative_to(ROOT).as_posix()
            for path, tree in trees for node in ast.walk(tree)
            if (isinstance(node, ast.Name) and node.id == wanted)
            or (isinstance(node, ast.Attribute) and node.attr == wanted)
            or (isinstance(node, ast.alias) and node.name == wanted)}


# The statement following the one that reads `source`, in whatever block holds
# it. None if nothing in the file reads it, so the caller can say so.
def guard_after(path: str, source: str) -> Optional[Any]:
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    blocks = [body for node in ast.walk(tree)
              if isinstance(body := getattr(node, "body", None), list)]
    pairs = [(block[index], block[index + 1])
             for block in blocks for index in range(len(block) - 1)]
    return next((after for before, after in pairs
                 if isinstance(before, ast.Assign)
                 and ast.unparse(before.value) == source), None)


# No file names a SYSTEM session except the two that are allowed to.
def test_only_the_maintenance_door_names_system_session() -> None:
    assert naming("system_session") == DOORS, (
        "a SYSTEM session must be reachable only from a file listed in DOORS; "
        "a request path that can build one runs with every right in the domain"
    )


# Only local maintenance goes through that door.
def test_only_local_maintenance_asks_for_a_system_session() -> None:
    callers = naming("local_session") - DOORS
    assert callers == LOCAL_PATHS, (
        f"unexpected callers of local_session: {sorted(callers - LOCAL_PATHS)}. "
        "If one is genuinely local maintenance rather than a remote request, "
        "add it to LOCAL_PATHS with the reason it is not a request."
    )


# Each place that takes the caller's identity refuses when there is none.
#
# Checked by shape rather than by running it, because importing the server
# pulls in every handler and therefore `ldb`. What matters is that the identity
# is read and the very next statement is a guard that stops.
@pytest.mark.parametrize("path, source, stops", GUARDS)
def test_a_path_with_no_session_refuses_rather_than_carrying_on(
        path: str, source: str, stops: str) -> None:
    guard = guard_after(path, source)
    assert guard is not None, (
        f"{path} no longer reads the caller's session from {source}; without "
        "that read there is no identity to serve the caller as"
    )
    assert isinstance(guard, ast.If) and "is None" in ast.unparse(guard.test)
    assert stops in ast.unparse(guard), (
        f"{path} must stop when the negotiation produced no session, not carry "
        "on with whatever rights it happens to have"
    )
