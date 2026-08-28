"""The Samba patch this module carries has to be a patch.

`patches/samba/0001-advertise-adws-in-the-cldap-netlogon-response.patch` was
committed with a hunk header claiming fifteen lines on the new side while the
body produced fourteen. GNU patch answered `malformed patch at line 40` and
`git apply` answered `corrupt patch at line 41`, so the file could not be
applied by any standard tool — on any Samba version, including the one it was
written against.

Nothing caught it, because applying it needs a Samba source tree and CI has
none. It does not need one to be checked for this: a hunk header states how
many lines it covers on each side, and the body either agrees or does not.
That is arithmetic on the file itself, and it runs anywhere.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PATCH_DIR = Path(__file__).resolve().parents[2] / "patches" / "samba"
HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def patches() -> list[Path]:
    return sorted(PATCH_DIR.glob("*.patch"))


def test_there_is_at_least_one_patch() -> None:
    """Guards the guard: a glob that matches nothing passes every test below."""
    assert patches(), f"no *.patch under {PATCH_DIR}"


@pytest.mark.parametrize("patch", patches(), ids=lambda p: p.name)
def test_every_hunk_header_matches_its_body(patch: Path) -> None:
    lines = patch.read_text(encoding="utf-8").split("\n")
    if lines and lines[-1] == "":
        lines.pop()

    hunks = 0
    index = 0
    while index < len(lines):
        found = HUNK.match(lines[index])
        if found is None:
            index += 1
            continue
        hunks += 1
        header = lines[index]
        declared_old = int(found.group(2) or 1)
        declared_new = int(found.group(4) or 1)

        old = new = 0
        index += 1
        while index < len(lines):
            line = lines[index]
            if line.startswith("@@") or line.startswith("--- "):
                break
            if line.startswith("+"):
                new += 1
            elif line.startswith("-"):
                old += 1
            elif line.startswith(" ") or line == "":
                # A context line. Some tools write the blank one bare rather
                # than as a single space; both count.
                old += 1
                new += 1
            elif line.startswith(r"\ No newline"):
                pass
            else:
                break
            index += 1

        assert (old, new) == (declared_old, declared_new), (
            f"{patch.name}: {header} covers {declared_old} old and "
            f"{declared_new} new lines, the body has {old} and {new}")

    assert hunks, f"{patch.name} has no hunk"


@pytest.mark.parametrize("patch", patches(), ids=lambda p: p.name)
def test_every_patch_names_the_file_it_changes(patch: Path) -> None:
    text = patch.read_text(encoding="utf-8")
    assert re.search(r"^--- a/\S+", text, re.MULTILINE), "no --- a/ line"
    assert re.search(r"^\+\+\+ b/\S+", text, re.MULTILINE), "no +++ b/ line"


# A patch with CRLF endings is refused by `patch` on the Debian host it is
# meant for, and this repository is edited from Windows as well.
@pytest.mark.parametrize("patch", patches(), ids=lambda p: p.name)
def test_no_carriage_returns(patch: Path) -> None:
    assert b"\r" not in patch.read_bytes()


# The C the patch inserts, with the leading '+' removed and runs of whitespace
# flattened, so an assertion can speak about what the patch does.
def added_c(patch: Path) -> str:
    added = [line[1:] for line in patch.read_text(encoding="utf-8").split("\n")
             if line.startswith("+") and not line.startswith("+++")]
    return " ".join(" ".join(added).split())


# Everything above checks the patch is a patch; this checks it is the RIGHT
# patch. Each assertion kills a mutation that the shape checks let through: a
# default of true, clearing the bit rather than setting it, writing the
# request-side constant the server must never answer with, and a parameter name
# that drifts from the one the description promises an administrator.
@pytest.mark.parametrize("patch", patches(), ids=lambda p: p.name)
def test_the_advertise_patch_sets_the_answer_side_bit_and_stays_off(patch: Path) -> None:
    if "advertise-adws" not in patch.name:
        pytest.skip("not the ADWS advertisement patch")
    body = added_c(patch)
    assert 'lpcfg_parm_bool(lp_ctx, NULL, "adws", "advertise", false)' in body, (
        "the bit must be gated on adws:advertise and default to false: announcing "
        "ADWS with nothing on 9389 makes a client connect and fail")
    assert "server_type |= DS_SERVER_WEBSERV;" in body, (
        "the patch must SET DS_SERVER_WEBSERV, the flag a server answers with")
    assert "DS_WEB_SERVICE_REQUIRED" not in body, (
        "DS_WEB_SERVICE_REQUIRED is what the client sends; writing it into "
        "server_type sets a bit with no meaning in that field")
    assert "&=" not in body and "&= ~" not in body
    description = patch.read_text(encoding="utf-8").split("--- a/")[0]
    assert "adws:advertise" in description, (
        "the description must name the parameter the code actually reads")
