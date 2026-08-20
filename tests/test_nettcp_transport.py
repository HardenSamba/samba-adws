"""Offline protocol-boundary tests for the production Net.TCP transport."""

import importlib
import sys
from enum import IntFlag
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, PropertyMock, call

import pytest

SPNEGO_OID = "1.3.6.1.5.5.2"
ALL_SECURITY_FLAGS = 0x1F
RESOURCE_URL = (
    "net.tcp://dc.example.test:9389/ActiveDirectoryWebServices/Windows/Resource"
)


# Models the subset of python-gssapi flags required by the stream.
class FakeRequirementFlag(IntFlag):
    mutual_authentication = 0x01
    confidentiality = 0x02
    integrity = 0x04
    replay_detection = 0x08
    out_of_sequence_detection = 0x10


# Loads the vendored GSSAPI stream against a controllable workstation-safe module.
def _load_gssapi_stream(
    monkeypatch: pytest.MonkeyPatch, actual_flags: int
) -> tuple[ModuleType, Any, MagicMock, MagicMock, object]:
    fake_gssapi: Any = ModuleType("gssapi")
    fake_gssapi.RequirementFlag = FakeRequirementFlag
    fake_gssapi.NameType = SimpleNamespace(hostbased_service=object())
    fake_gssapi.Name = MagicMock(return_value=object())
    spnego = object()
    fake_gssapi.OID = SimpleNamespace(from_int_seq=MagicMock(return_value=spnego))
    negotiated = {flag for flag in FakeRequirementFlag if flag & actual_flags}
    context = MagicMock(actual_flags=negotiated)
    type(context).complete = PropertyMock(side_effect=[False, True, True])
    context.step.return_value = b"client-token"
    fake_gssapi.SecurityContext = MagicMock(return_value=context)
    monkeypatch.setitem(sys.modules, "gssapi", fake_gssapi)
    module_name = "src.nettcp.stream.gssapi"
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    module = importlib.import_module(module_name)
    return module, fake_gssapi, context, fake_gssapi.SecurityContext, spnego


# Verifies SPNEGO, the required security flags, and negotiated flag enforcement.
@pytest.mark.parametrize(
    ("actual_flags", "must_fail"),
    [(ALL_SECURITY_FLAGS, False), (ALL_SECURITY_FLAGS ^ 0x10, True)],
    ids=["all-flags", "missing-out-of-sequence"],
)
def test_gssapi_negotiate_requires_spnego_and_security_flags(
    monkeypatch: pytest.MonkeyPatch, actual_flags: int, must_fail: bool
) -> None:
    module, fake_gssapi, context, security_context, spnego = _load_gssapi_stream(
        monkeypatch, actual_flags
    )
    framed_stream = MagicMock()
    monkeypatch.setattr(module, "NegotiateStream", MagicMock(return_value=framed_stream))
    stream = module.GSSAPIStream(MagicMock(), "host@dc.example.test")
    if must_fail:
        with pytest.raises(IOError, match="flags"):
            stream.negotiate()
    else:
        stream.negotiate()
    fake_gssapi.OID.from_int_seq.assert_called_once_with(SPNEGO_OID)
    expected = dict(name=fake_gssapi.Name.return_value, usage="initiate")
    security_context.assert_called_once_with(**expected, flags=ALL_SECURITY_FLAGS, mech=spnego)
    context.step.assert_called_once_with(b"")
    framed_stream.write.assert_called_once_with(b"client-token")


# Verifies fixed-length reads tolerate one- and two-byte socket fragments.
def test_socket_stream_reassembles_fragmented_reads() -> None:
    from src.nettcp.stream.socket import SocketStream

    raw_socket = MagicMock()
    raw_socket.recv.side_effect = [b"A", b"BC", b"D"]
    assert SocketStream(raw_socket).read(4) == b"ABCD"
    assert raw_socket.recv.call_args_list == [call(4), call(3), call(1)]


# Builds the exact NMF records expected before the authenticated session starts.
def _expected_nmf_writes(module: ModuleType) -> list[Any]:
    records: list[Any] = [
        module.VersionRecord(MajorVersion=1, MinorVersion=0),
        module.ModeRecord(Mode=2),
        module.ViaRecord(ViaLength=len(RESOURCE_URL), Via=RESOURCE_URL),
        module.KnownEncodingRecord(Encoding=8),
    ]
    preamble = b"".join(record.to_bytes() for record in records)
    upgrade = module.UpgradeRequestRecord(
        UpgradeProtocolLength=21, UpgradeProtocol="application/negotiate"
    ).to_bytes()
    return [
        call(preamble),
        call(upgrade),
        call(module.PreambleEndRecord().to_bytes()),
    ]


# Verifies the NMF preamble carries the Resource URI and negotiate upgrade.
def test_nmf_preamble_serializes_uri_and_negotiate_upgrade(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _load_gssapi_stream(monkeypatch, ALL_SECURITY_FLAGS)
    module_name = "src.nettcp.stream.nmf"
    monkeypatch.delitem(sys.modules, module_name, raising=False)
    module = importlib.import_module(module_name)
    inner = MagicMock()
    inner.read.side_effect = [b"\x0a", b"\x0b"]
    gssapi_stream = MagicMock(return_value=inner)
    monkeypatch.setattr(module, "GSSAPIStream", gssapi_stream)
    module.NMFStream(inner, RESOURCE_URL, "host@dc.example.test").preamble()
    assert inner.write.call_args_list == _expected_nmf_writes(module)
    assert inner.read.call_args_list == [call(1), call(1)]
    gssapi_stream.assert_called_once_with(inner, "host@dc.example.test")
