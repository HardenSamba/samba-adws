"""Offline failure contract tests for the public ADWS client."""

import functools
import subprocess
import sys

import pytest

from samba_adws import ADWSClient, ADWSClientError
from tests.client_helpers import (
    failing_response,
    install_transport,
    malformed_response,
    response_for,
)

FAULT_BODY = (
    '<s:Fault><s:Code><s:Value>s:Receiver</s:Value></s:Code><s:Reason>'
    '<s:Text xml:lang="en-US">Object not found: CN=Missing</s:Text></s:Reason></s:Fault>'
)
SUCCESS_BODY = (
    '<addata:user><addata:cn><ad:value xsi:type="xsd:string">Demo</ad:value>'
    '</addata:cn></addata:user>'
)


# Verifies SOAP faults become structured public client exceptions.
def test_get_by_dn_decodes_fault(monkeypatch: pytest.MonkeyPatch) -> None:
    script = functools.partial(response_for, body=FAULT_BODY)
    install_transport(monkeypatch, script)
    with pytest.raises(ADWSClientError) as raised:
        ADWSClient("dc.example.test").get_by_dn("CN=Missing,DC=example,DC=test")
    assert raised.value.code == "ObjectNotFound"
    assert raised.value.category == "ObjectNotFound"
    assert raised.value.target == "CN=Missing,DC=example,DC=test"


# Verifies mismatched correlation and malformed SOAP are rejected.
@pytest.mark.parametrize("malformed", [False, True])
def test_get_by_dn_rejects_invalid_response(
    monkeypatch: pytest.MonkeyPatch, malformed: bool
) -> None:
    script = functools.partial(response_for, body=SUCCESS_BODY, relates_to="urn:uuid:wrong")
    install_transport(monkeypatch, malformed_response if malformed else script)
    with pytest.raises(ADWSClientError) as raised:
        ADWSClient("dc.example.test").get_by_dn("CN=Demo,DC=example,DC=test")
    assert raised.value.code in {"CorrelationError", "MalformedResponse"}


# Verifies network failures are normalized and the session is still closed.
def test_get_by_dn_normalizes_transport_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    transport = install_transport(monkeypatch, failing_response)
    with pytest.raises(ADWSClientError) as raised:
        ADWSClient("dc.example.test").get_by_dn("CN=Demo,DC=example,DC=test")
    assert raised.value.code == "TransportError"
    assert raised.value.category == "ResourceUnavailable"
    assert transport.closed


# Verifies invalid public arguments fail before transport construction.
def test_client_rejects_invalid_arguments() -> None:
    with pytest.raises(ADWSClientError) as invalid_timeout:
        ADWSClient("dc.example.test", timeout=float("nan"))
    with pytest.raises(ADWSClientError) as invalid_properties:
        ADWSClient("dc.example.test").get_by_dn("CN=Demo", "cn")
    assert invalid_timeout.value.code == "InvalidArgument"
    assert invalid_properties.value.code == "InvalidArgument"
    assert invalid_properties.value.target == "CN=Demo"


# Verifies importing the public client never loads Samba server modules.
def test_client_import_is_workstation_safe() -> None:
    statement = (
        "import sys,types; from types import SimpleNamespace; "
        "fake=types.ModuleType('gssapi'); "
        "fake.RequirementFlag=SimpleNamespace("
        "mutual_authentication=1,confidentiality=2,integrity=4,"
        "replay_detection=8,out_of_sequence_detection=16); "
        "sys.modules['gssapi']=fake; import samba_adws.client; import samba_adws._nettcp; "
        "bad=[n for n in sys.modules if n in ('samba','ldb') or n.startswith('classes.server')]; "
        "assert not bad, bad"
    )
    result = subprocess.run(
        [sys.executable, "-c", statement], check=True, capture_output=True, text=True,
    )
    assert result.stderr == ""
