"""Offline tests for the supported search client.

Two directions, checked differently, because only one of them can be checked
against the server itself on a machine with no `ldb`.

**The request direction is checked against the server's real parser.**
`classes/parsing/context_enumeration` imports nothing but ElementTree, so the
tests below feed it the bytes the client actually builds and assert on what the
server would have understood. A test that read the request back with a parser
written here would agree with itself and prove nothing.

**The response direction is scripted**, from the shape `[MS-WSDS]` and
WS-Enumeration fix, with one test reading `classes/handlers/pull.py` to check
that the elements this client looks for are the elements that file writes. It
is a coarse check and it is the only one available offline; it catches the
rename that would otherwise be found by an administrator.
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional

import pytest

from classes.parsing.context_enumeration import read_enumerate, read_pull_release
from samba_adws._codec import decode_xml, encode_xml
from samba_adws._search_request import (
    ENUMERATE_RESPONSE_ACTION,
    PULL_RESPONSE_ACTION,
    build_enumerate_request,
    build_pull_request,
)
from samba_adws._search_validation import MAX_PAGE_SIZE, search_query
from samba_adws.errors import ADWSClientError
from samba_adws.search_client import ADWSSearchClient
from src.soap.namespaces import AD, ADDATA, ADLQ, SOAP_ENV, WSA, WSEN, XSD, XSI
from tests.client_helpers import install_transport

SERVER = "dc.example.test"
BASE = "OU=Staff,OU=Paris,DC=example,DC=test"
NAMESPACES = (
    f'xmlns:s="{SOAP_ENV}" xmlns:a="{WSA}" xmlns:wsen="{WSEN}" '
    f'xmlns:ad="{AD}" xmlns:addata="{ADDATA}" xmlns:adlq="{ADLQ}" '
    f'xmlns:xsi="{XSI}" xmlns:xsd="{XSD}"'
)


# The MessageID of a scripted request, which a response has to correlate to.
def message_id_of(payload: bytes) -> str:
    request = ET.fromstring(decode_xml(payload))
    return request.findtext(f"./{{{SOAP_ENV}}}Header/{{{WSA}}}MessageID") or ""


# One SOAP response envelope carrying an action and a body.
def envelope(action: str, relates_to: str, body: str) -> bytes:
    return encode_xml(
        f'<s:Envelope {NAMESPACES}><s:Header><a:Action>{action}</a:Action>'
        f'<a:RelatesTo>{relates_to}</a:RelatesTo></s:Header>'
        f'<s:Body>{body}</s:Body></s:Envelope>'
    )


# One object, in the shape PullHandler renders through the projector.
def obj(name: str, dn: str) -> str:
    return (
        f'<addata:user><addata:sAMAccountName><ad:value xsi:type="xsd:string">{name}'
        f'</ad:value></addata:sAMAccountName><ad:distinguishedName>'
        f'<ad:value xsi:type="xsd:string">{dn}</ad:value></ad:distinguishedName>'
        f'</addata:user>'
    )


# One PullResponse body, ending the sequence or handing back a context.
def pull_body(items: str, more: Optional[str]) -> str:
    tail = (
        f'<wsen:EnumerationContext>{more}</wsen:EnumerationContext>'
        if more
        else '<wsen:EndOfSequence/>'
    )
    return f'<wsen:PullResponse><wsen:Items>{items}</wsen:Items>{tail}</wsen:PullResponse>'


# A server that opens one context and answers two batches, the second final.
def two_pages(payload: bytes) -> bytes:
    correlation = message_id_of(payload)
    request = decode_xml(payload)
    if "wsen:Enumerate>" in request or "Enumerate</a:Action>" in request:
        body = '<wsen:EnumerateResponse><wsen:EnumerationContext>ctx-1' \
               '</wsen:EnumerationContext></wsen:EnumerateResponse>'
        return envelope(ENUMERATE_RESPONSE_ACTION, correlation, body)
    if "ctx-1" in request:
        items = obj("m.dupont", f"CN=Marie,{BASE}") + obj("l.bernard", f"CN=Luc,{BASE}")
        return envelope(PULL_RESPONSE_ACTION, correlation, pull_body(items, "ctx-2"))
    return envelope(PULL_RESPONSE_ACTION, correlation, pull_body(obj("c.arnaud", BASE), None))


# A client whose transport is the given script.
def client(monkeypatch: pytest.MonkeyPatch, script: object) -> ADWSSearchClient:
    install_transport(monkeypatch, script)  # type: ignore[arg-type]
    return ADWSSearchClient(SERVER)


# The server's own parser reads the base, scope and filter this client sends.
def test_the_server_understands_the_enumerate_request() -> None:
    query = search_query(BASE, "OneLevel", "(objectClass=user)", ("sAMAccountName", "cn"))
    request, _ = build_enumerate_request(SERVER, 9389, query)
    values = read_enumerate(ET.fromstring(request))
    assert values["base_dn"] == BASE
    assert values["ldap_scope"] == "OneLevel"
    assert values["ldap_filter"] == "(objectClass=user)"
    assert values["selection_attributes"] == ["sAMAccountName", "cn"]


# A filter carrying the characters XML reserves survives the round trip.
def test_a_filter_with_reserved_characters_arrives_intact() -> None:
    query = search_query(BASE, "Subtree", "(&(objectClass=user)(cn=A*))")
    request, _ = build_enumerate_request(SERVER, 9389, query)
    values = read_enumerate(ET.fromstring(request))
    assert values["ldap_filter"] == "(&(objectClass=user)(cn=A*))"


# The server's own parser reads the context and batch size this client sends.
def test_the_server_understands_the_pull_request() -> None:
    request, _ = build_pull_request(SERVER, 9389, "ctx-1", 25)
    values = read_pull_release(ET.fromstring(request))
    assert values["enumeration_context"] == "ctx-1"
    assert values["max_elements"] == 25


# Enumerate and Pull address the endpoint the published table gives them.
def test_the_requests_address_the_enumeration_endpoint() -> None:
    request, _ = build_pull_request(SERVER, 9389, "ctx-1", 10)
    to = ET.fromstring(request).findtext(f"./{{{SOAP_ENV}}}Header/{{{WSA}}}To")
    assert to == f"net.tcp://{SERVER}:9389/ActiveDirectoryWebServices/Windows/Enumeration"


# A search pages until the server says the sequence ended.
def test_a_search_pages_until_the_sequence_ends(monkeypatch: pytest.MonkeyPatch) -> None:
    found = list(client(monkeypatch, two_pages).search(search_query(BASE)))
    assert [entry["sAMAccountName"] for entry in found] == ["m.dupont", "l.bernard", "c.arnaud"]


# The end is EndOfSequence, never an empty batch.
#
# A client that stopped on an empty page would truncate against a server that
# answers one in the middle, and one that stopped on a short page would
# truncate against every server: a batch smaller than the maximum is ordinary.
def test_an_empty_batch_is_not_the_end(monkeypatch: pytest.MonkeyPatch) -> None:
    # Enumerate, then an empty page with a context, then one object and the end.
    def script(payload: bytes) -> bytes:
        correlation = message_id_of(payload)
        request = decode_xml(payload)
        if "Enumerate</a:Action>" in request:
            body = ('<wsen:EnumerateResponse><wsen:EnumerationContext>ctx-1'
                    '</wsen:EnumerationContext></wsen:EnumerateResponse>')
            return envelope(ENUMERATE_RESPONSE_ACTION, correlation, body)
        if "ctx-1" in request:
            return envelope(PULL_RESPONSE_ACTION, correlation, pull_body("", "ctx-2"))
        return envelope(PULL_RESPONSE_ACTION, correlation, pull_body(obj("late", BASE), None))

    found = list(client(monkeypatch, script).search(search_query(BASE)))
    assert [entry["sAMAccountName"] for entry in found] == ["late"]


# A response saying neither is refused rather than guessed at.
def test_a_response_with_no_continuation_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    def script(payload: bytes) -> bytes:
        correlation = message_id_of(payload)
        body = '<wsen:PullResponse><wsen:Items/></wsen:PullResponse>'
        return envelope(PULL_RESPONSE_ACTION, correlation, body)

    with pytest.raises(ADWSClientError) as raised:
        client(monkeypatch, script).pull("ctx-1")
    assert raised.value.code == "MalformedResponse"


# A response to somebody else's request is not an answer to this one.
def test_an_uncorrelated_response_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    def script(_: bytes) -> bytes:
        body = '<wsen:PullResponse><wsen:Items/><wsen:EndOfSequence/></wsen:PullResponse>'
        return envelope(PULL_RESPONSE_ACTION, "urn:uuid:somebody-else", body)

    with pytest.raises(ADWSClientError) as raised:
        client(monkeypatch, script).pull("ctx-1")
    assert raised.value.code == "CorrelationError"


# An expired context comes back as the server's own reason.
def test_a_fault_carries_the_reason_the_server_gave(monkeypatch: pytest.MonkeyPatch) -> None:
    def script(payload: bytes) -> bytes:
        correlation = message_id_of(payload)
        body = (
            '<s:Fault><s:Code><s:Value>s:Receiver</s:Value></s:Code><s:Reason>'
            '<s:Text>Invalid or expired enumeration context: ctx-1</s:Text>'
            '</s:Reason></s:Fault>'
        )
        return envelope(PULL_RESPONSE_ACTION, correlation, body)

    with pytest.raises(ADWSClientError) as raised:
        client(monkeypatch, script).pull("ctx-1")
    assert "expired enumeration context" in str(raised.value)


# An object carrying none of the projected attributes does not lose the page.
def test_an_object_with_no_attributes_keeps_its_place(monkeypatch: pytest.MonkeyPatch) -> None:
    def script(payload: bytes) -> bytes:
        correlation = message_id_of(payload)
        items = '<addata:user/>' + obj("present", BASE)
        return envelope(PULL_RESPONSE_ACTION, correlation, pull_body(items, None))

    objects, more = client(monkeypatch, script).pull("ctx-1")
    assert more is None
    assert len(objects) == 2
    assert objects[0] == {}


# A scope the server does not map is refused here, not widened there.
#
# EnumerateHandler falls through to Subtree for anything it does not recognise.
# A caller who asked for one level and searched a whole domain gets an answer
# that is not wrong-looking, which is the worst kind.
def test_an_unknown_scope_is_refused_before_the_network() -> None:
    with pytest.raises(ADWSClientError) as raised:
        search_query(BASE, "One")
    assert raised.value.code == "InvalidArgument"


# A batch size that means nothing is refused rather than sent.
@pytest.mark.parametrize("count", [0, -1, MAX_PAGE_SIZE + 1, True])
def test_a_meaningless_page_size_is_refused(count: object) -> None:
    with pytest.raises(ADWSClientError) as raised:
        ADWSSearchClient(SERVER).pull("ctx-1", count)  # type: ignore[arg-type]
    assert raised.value.code == "InvalidArgument"


# An empty base is refused: it is the one thing the server defaults for you.
def test_an_empty_base_is_refused() -> None:
    with pytest.raises(ADWSClientError):
        search_query("")


# The elements this client reads are the elements the server writes.
#
# The response side cannot be exercised against the real handler without `ldb`,
# so this reads its source instead. Coarse, and it catches the rename that
# would otherwise be found by an administrator with an empty screen.
def test_the_client_reads_what_the_pull_handler_writes() -> None:
    source = (Path(__file__).resolve().parents[1] / "classes/handlers/pull.py").read_text(
        encoding="utf-8"
    )
    for element in ("wsen:PullResponse", "wsen:Items", "wsen:EndOfSequence",
                    "wsen:EnumerationContext"):
        assert element in source, f"{element} is not what the Pull handler writes any more"
