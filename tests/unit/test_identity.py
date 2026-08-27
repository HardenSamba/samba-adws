"""Offline tests for reading the caller off the context that authenticated it.

`identity.py` imports nothing from samba on purpose: it asks the negotiated
context a question and decides what to do with silence. That decision is the
whole of `#8` on this side of the handshake, so it is tested directly rather
than inferred from a server that happened to work.

The doubles below stand in for `samba.gensec.Security`, which is what
`GENSECStream.client_ctx` holds after a successful negotiation.
"""

import logging
from typing import Any, Optional

import pytest

from classes.server import identity

PEER = "10.0.0.7:51322"


# A principal as Samba describes one, with the two fields a log line uses.
class Principal:
    def __init__(self, account: str, domain: str) -> None:
        self.account_name = account
        self.domain_name = domain


# A session as Samba builds one for an authenticated caller.
class Session:
    def __init__(self, account: str = "m.dupont", domain: str = "EXAMPLE") -> None:
        self.info = Principal(account, domain)


# A negotiated security context that answers with one session, or refuses to.
class Context:
    def __init__(self, session: Optional[Session] = None, error: str = "") -> None:
        self._session = session
        self._error = error

    def session_info(self) -> Any:
        if self._error:
            raise RuntimeError(self._error)
        return self._session


# A stream at whatever stage of negotiation the test needs.
class Stream:
    def __init__(self, context: Any = None) -> None:
        if context is not None:
            self.client_ctx = context


# The session the context built is the session that comes back.
def test_the_authenticated_session_is_the_one_returned() -> None:
    session = Session()
    assert identity.session_for(Stream(Context(session))) is session


# A stream that never negotiated has no identity to give.
def test_a_stream_that_never_negotiated_yields_nothing() -> None:
    assert identity.session_for(Stream()) is None


# A context that cannot answer the question yields nothing.
def test_a_context_with_no_session_reader_yields_nothing() -> None:
    assert identity.session_for(Stream(object())) is None


# A context that answers with nothing yields nothing, not something falsy.
def test_a_context_answering_with_nothing_yields_nothing() -> None:
    assert identity.session_for(Stream(Context(None))) is None


# A principal is named by domain and account.
def test_a_principal_is_named_by_domain_and_account() -> None:
    assert identity.described(Session("m.dupont", "EXAMPLE")) == "EXAMPLE\\m.dupont"


# A session of an unexpected shape is still recorded as having connected.
@pytest.mark.parametrize("session", [object(), None, Session("", "")])
def test_an_unexpected_session_is_still_named(session: Any) -> None:
    assert identity.described(session)


# An authenticated connection gets its session, and the log says whose.
def test_an_authenticated_connection_is_named_in_the_log(
        caplog: pytest.LogCaptureFixture) -> None:
    session = Session("m.dupont", "EXAMPLE")
    log = logging.getLogger("identity-test")
    with caplog.at_level(logging.INFO, logger="identity-test"):
        assert identity.required(Stream(Context(session)), log, PEER) is session
    assert "EXAMPLE\\m.dupont" in caplog.text
    assert PEER in caplog.text


# A negotiation that produced no session is refused, and the log says why.
#
# The refusal is the fix. What used to happen here was a SYSTEM session, so the
# connection carried on with every right in the domain and the log above it
# recorded a successful negotiation - which it had been.
def test_a_negotiation_with_no_session_is_refused(
        caplog: pytest.LogCaptureFixture) -> None:
    log = logging.getLogger("identity-test")
    with caplog.at_level(logging.ERROR, logger="identity-test"):
        assert identity.required(Stream(Context(None)), log, PEER) is None
    assert "SYSTEM" in caplog.text
    assert PEER in caplog.text


# A context that fails to answer is refused, with the reason and no traceback.
def test_a_session_that_cannot_be_read_is_refused_with_its_reason(
        caplog: pytest.LogCaptureFixture) -> None:
    log = logging.getLogger("identity-test")
    with caplog.at_level(logging.ERROR, logger="identity-test"):
        assert identity.required(Stream(Context(error="gensec is not finished")), log, PEER) is None
    assert "gensec is not finished" in caplog.text
    assert not any(record.exc_info for record in caplog.records), (
        "a caller that cannot be identified is a refusal, not a crash"
    )
