"""No request path can reach a SYSTEM directory session any more.

This is the test that would have caught `#8` on the commit that introduced it.
`classes/server/connection.py` built `system_session()` immediately after GSSAPI
succeeded, with a comment saying auth was done - which it was. Authentication
was done and authorization was never asked for, and nothing about a running
server looked wrong: the negotiation logged success and every request worked,
because SYSTEM can do everything.

So the invariant is checked structurally rather than behaviourally. A test that
needed a denied write to prove this would need a domain, a second principal and
an ACL, and would therefore not run anywhere the mistake gets made.

The files are parsed rather than searched as text, so that the prose in
`samba_db.py` and `connection.py` explaining what they used to do does not
count as doing it.
"""

import ast
from pathlib import Path
from typing import List, Set

ROOT = Path(__file__).resolve().parents[2]
SEARCHED = ("classes", "src")
# Vendored protocol libraries, excluded here for the reason `pyproject.toml`
# and `.pre-commit-config.yaml` exclude them: they are not this project's code.
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
    # discards the result, and opens no directory; it runs once, before the
    # listener accepts anything. Left naming it directly because bringing this
    # file into the project norms is a refactor of its own - it holds two
    # classes against a limit of one - and that does not belong in a security
    # fix. Tracked separately.
    "classes/server/server.py",
}

# Local maintenance callers under `classes/` and `src/`. There are none: the
# only caller is the DC diagnostic in `tools/`, which this does not scan. A
# request path that reached for `local_session` would fail this.
LOCAL_PATHS: Set[str] = set()


# Every file this project is answerable for.
def sources() -> List[Path]:
    found: List[Path] = []
    for top in SEARCHED:
        found += [path for path in (ROOT / top).rglob("*.py")
                  if not any(part in VENDORED for part in path.parts)]
    return sorted(found)


# The repository-relative name of one file, in the form the lists above use.
def named(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


# Every file naming one identifier, by import, call or attribute.
def naming(wanted: str) -> Set[str]:
    found: Set[str] = set()
    for path in sources():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            hit = (isinstance(node, ast.Name) and node.id == wanted) or \
                  (isinstance(node, ast.Attribute) and node.attr == wanted) or \
                  (isinstance(node, ast.alias) and node.name == wanted)
            if hit:
                found.add(named(path))
    return found


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
        "If one of these is genuinely local maintenance rather than a remote "
        "request, add it to LOCAL_PATHS with the reason it is not a request."
    )


# The connection path asks for the caller's session and stops without one.
#
# Checked here rather than by running it, because importing `connection.py`
# pulls in every handler and therefore `ldb`. What matters is the shape: the
# session is fetched, and the very next thing is a guard that returns.
def test_the_connection_refuses_a_negotiation_that_produced_no_session() -> None:
    tree = ast.parse((ROOT / "classes/server/connection.py").read_text(encoding="utf-8"))
    body = [node for node in ast.walk(tree)
            if isinstance(node, ast.FunctionDef) and node.name == "_serve"]
    assert body, "connection.py no longer has the _serve it is checked through"
    statements = body[0].body
    asks = [i for i, node in enumerate(statements)
            if isinstance(node, ast.Assign)
            and ast.unparse(node.value).startswith("identity.required(")]
    assert asks, "the connection no longer asks identity.required for a session"
    guard = statements[asks[0] + 1]
    assert isinstance(guard, ast.If) and "is None" in ast.unparse(guard.test)
    assert any(isinstance(node, ast.Return) for node in guard.body), (
        "a connection whose negotiation produced no session must stop, "
        "not carry on with whatever rights it happens to have"
    )
