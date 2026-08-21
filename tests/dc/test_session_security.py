#!/usr/bin/env python3
"""The authenticated-session contract (samba-adws#8): no request runs as SYSTEM.

Every SambaDB is scoped to the caller's negotiated session; the SYSTEM fallback
that the server used to open the directory with is gone. These tests pin that
contract at the point it is enforced, the directory open, and are skipped off a
provisioned directory because they need python3-samba.
"""
from __future__ import annotations

import logging
from typing import Any

import pytest

pytestmark = pytest.mark.dc


# Refusing to open without a session is what closes the escalation hole: the
# old code substituted system_session() here, granting every caller SYSTEM. A
# session-less handle may exist (a fault path builds one) but must never open.
def test_samba_db_refuses_to_open_without_a_session(logger: logging.Logger) -> None:
    from classes.directory import SambaDB
    from classes.faults.exceptions import ADWSAuthenticationException

    directory = SambaDB(logger, session_info=None)

    with pytest.raises(ADWSAuthenticationException):
        directory.naming_context("defaultNamingContext")


# A genuine session is accepted and kept verbatim, never swapped for another:
# the directory must act as exactly the principal the handshake authenticated.
def test_samba_db_keeps_the_supplied_session(logger: logging.Logger) -> None:
    from samba.auth import system_session

    from classes.directory import SambaDB

    session = system_session()
    directory = SambaDB(logger, session_info=session)

    assert directory.session_info is session


# The accepted session is the one the directory opens under, proved by a read
# that only succeeds once SamDB is bound to it.
def test_samba_db_opens_under_the_session(logger: logging.Logger) -> None:
    from samba.auth import system_session

    from classes.directory import SambaDB

    directory: Any = SambaDB(logger, session_info=system_session())

    assert directory.naming_context("defaultNamingContext").startswith("DC=")
