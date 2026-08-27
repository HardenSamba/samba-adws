"""Offline tests for the directory refusing to open without an authenticated session.

`samba_db.py` imports `ldb`, `samba.param` and `samba.samdb` at module level, so
these stand in for them. The stubs replace samba and never the code under test:
what is asserted is this repository's own decision about when a directory may be
opened and as whom, which is the half `#8` got wrong.

That decision used to be `session_info or system_session()`. A request that
arrived carrying no identity opened the directory with every right in it, and
the only visible difference from a request that had those rights was none.
"""

import importlib
import logging
import sys
import types
from typing import Any, List, Tuple

import pytest

from classes.faults.exceptions import ADWSAccessDeniedException, ADWSException


# The directory module, imported against samba stubs, and what it opened.
@pytest.fixture
def directory(monkeypatch: pytest.MonkeyPatch) -> Tuple[Any, List[Any]]:
    opened: List[Any] = []

    class LoadParm:
        def load_default(self) -> None:
            return None

    class SamDB:
        def __init__(self, lp: Any = None, session_info: Any = None) -> None:
            opened.append(session_info)

    ldb_module = types.ModuleType("ldb")
    setattr(ldb_module, "SCOPE_BASE", 0)
    param = types.ModuleType("samba.param")
    setattr(param, "LoadParm", LoadParm)
    samdb = types.ModuleType("samba.samdb")
    setattr(samdb, "SamDB", SamDB)
    samba = types.ModuleType("samba")

    for name, module in (("ldb", ldb_module), ("samba", samba),
                         ("samba.param", param), ("samba.samdb", samdb)):
        monkeypatch.setitem(sys.modules, name, module)
    for cached in ("classes.directory", "classes.directory.samba_db"):
        monkeypatch.delitem(sys.modules, cached, raising=False)
    return importlib.import_module("classes.directory.samba_db").SambaDB, opened


# A request that arrived with no identity opens nothing at all.
def test_a_directory_with_no_session_refuses_to_open(
        directory: Tuple[Any, List[Any]], logger: logging.Logger) -> None:
    SambaDB, opened = directory
    with pytest.raises(ADWSAccessDeniedException):
        _ = SambaDB(logger).db
    assert opened == [], "nothing may be opened for a caller who was never identified"


# The session it was handed is the session it opens as, unchanged.
def test_it_opens_as_the_session_it_was_given(
        directory: Tuple[Any, List[Any]], logger: logging.Logger) -> None:
    SambaDB, opened = directory
    caller = object()
    _ = SambaDB(logger, session_info=caller).db
    assert opened == [caller]


# The refusal says what was missing rather than failing as something else.
def test_the_refusal_names_what_was_missing(
        directory: Tuple[Any, List[Any]], logger: logging.Logger) -> None:
    SambaDB, _ = directory
    with pytest.raises(ADWSAccessDeniedException) as raised:
        _ = SambaDB(logger).db
    assert "authenticated session" in str(raised.value)


# The refusal is the kind the dispatcher already turns into a SOAP fault.
#
# CLAUDE.md 5: every error is a typed `ADWSException`, because the dispatcher
# translates those and lets anything else through as an unexpected failure.
def test_the_refusal_is_a_typed_adws_error(
        directory: Tuple[Any, List[Any]], logger: logging.Logger) -> None:
    SambaDB, _ = directory
    with pytest.raises(ADWSException):
        _ = SambaDB(logger).db


# The connection is opened once and reused, not opened per question.
def test_the_directory_is_opened_once(
        directory: Tuple[Any, List[Any]], logger: logging.Logger) -> None:
    SambaDB, opened = directory
    db = SambaDB(logger, session_info=object())
    first, second = db.db, db.db
    assert first is second
    assert len(opened) == 1
