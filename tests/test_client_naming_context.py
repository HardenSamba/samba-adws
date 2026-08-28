"""Offline contract tests for the RootDSE naming context: the call itself.

The **request** direction is checked against the server's own parser:
`classes/parsing/context` imports nothing but ElementTree, so these tests feed
it the bytes the client actually builds and assert on what the server would
have understood — which branch of `GetHandler` it would have routed to, and
which attribute it would have filtered its RootDSE search down to.

The **response** direction is scripted, because `classes/handlers/get.py`
imports `ldb` and cannot be loaded on a machine without Samba. One test reads
that file as text and checks the identity this client sends is still the one
the handler routes on. The answers it refuses are in
`test_naming_context_refusals`.
"""

import functools
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from classes.parsing.context import RequestContext
from samba_adws import ADWSClient
from samba_adws._codec import decode_xml
from samba_adws._root_dse import ROOT_DSE_IDENTITY
from src.soap.namespaces import AD, DA, SOAP_ENV

from tests.client_helpers import NAMING_CONTEXT, ROOT_DSE_BODY, install_transport, response_for
from tests.scripted_transport import ScriptedTransport

PUBLISHED = ROOT_DSE_BODY.format(context=NAMING_CONTEXT)


# Answers one scripted body and hands back the transport that recorded the ask.
def scripted(monkeypatch: pytest.MonkeyPatch, body: str) -> ScriptedTransport:
    return install_transport(monkeypatch, functools.partial(response_for, body=body))


# The request names the RootDSE and projects the single attribute it wants.
def test_the_request_asks_the_root_dse_for_one_attribute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = scripted(monkeypatch, PUBLISHED)
    ADWSClient("dc.example.test").naming_context()

    root = ET.fromstring(decode_xml(transport.requests[0]))
    header = root.find(f"./{{{SOAP_ENV}}}Header")
    assert header is not None
    assert header.findtext(f"{{{AD}}}objectReferenceProperty") == ROOT_DSE_IDENTITY
    assert header.find(f"{{{DA}}}IdentityManagementOperation") is not None
    attributes = root.findall(f".//{{{DA}}}AttributeType")
    assert [element.text for element in attributes] == ["addata:defaultNamingContext"]


# The server's own parser reads those bytes as a RootDSE attribute projection.
#
# This is the check that matters: an object reference the handler did not
# recognise would be looked up as a distinguished name and never found, and a
# projection it did not understand would return the whole RootDSE.
def test_the_server_parser_reads_it_as_a_root_dse_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    transport = scripted(monkeypatch, PUBLISHED)
    ADWSClient("dc.example.test").naming_context()

    context = RequestContext.from_xml(decode_xml(transport.requests[0]))
    assert context.object_reference == ROOT_DSE_IDENTITY
    assert context.requested_attributes == ["defaultNamingContext"]
    assert context.is_imda


# The value crosses the boundary spelled the way the directory spelled it.
def test_the_published_naming_context_is_returned_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scripted(monkeypatch, PUBLISHED)

    assert ADWSClient("dc.example.test").naming_context() == NAMING_CONTEXT


# The handler still routes on the identity this client sends.
#
# Coarse on purpose: `classes/handlers/get.py` imports `ldb` and cannot be
# loaded off a domain controller, so the file is read as text. It catches the
# rename that would otherwise be found by an operator looking at empty output.
def test_the_handler_still_routes_on_the_identity_this_client_sends() -> None:
    handler = Path(__file__).resolve().parent.parent / "classes" / "handlers" / "get.py"

    assert ROOT_DSE_IDENTITY in handler.read_text(encoding="utf-8")
