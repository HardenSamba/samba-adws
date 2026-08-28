"""The `samba-adws` command, which another module runs as a subprocess.

The consumer is `hardensamba-webui`. It starts this, waits with a deadline, and
does exactly two things: check the exit status, and parse stdout as JSON. So the
contract worth testing is not the wording of anything — it is that a success is
a zero status and one parseable document, and a failure is a non-zero status
with stdout left empty.

The transport is scripted, as it is for the client tests: nothing here opens a
socket or needs a directory.
"""

import functools
import json
from typing import Any, Callable, List, Optional

import pytest

import samba_adws.client as client_module
from samba_adws._codec import decode_xml, encode_xml
from samba_adws._search_request import ENUMERATE_RESPONSE_ACTION, PULL_RESPONSE_ACTION
from samba_adws.cli import main
from src.soap.namespaces import AD, ADDATA, SOAP_ENV, WSA, WSEN, XSD, XSI
from tests.client_helpers import NAMING_CONTEXT, ROOT_DSE_BODY, failing_response, response_for
from tests.scripted_transport import ScriptedTransport

BASE = "OU=Staff,DC=example,DC=test"
NAMING_ARGV = ["naming-context", "--server", "dc.example.test"]
# Longer than `cli_text.WIDTH`, which four labels of ordinary length reach.
LONG_CONTEXT = "DC=directory,DC=engineering,DC=northamerica,DC=corporate,DC=example,DC=test"
NAMESPACES = (
    f'xmlns:s="{SOAP_ENV}" xmlns:a="{WSA}" xmlns:wsen="{WSEN}" xmlns:ad="{AD}" '
    f'xmlns:addata="{ADDATA}" xmlns:xsi="{XSI}" xmlns:xsd="{XSD}"'
)


# One correlated response envelope.
def envelope(action: str, payload: bytes, body: str) -> bytes:
    import xml.etree.ElementTree as ET

    request = ET.fromstring(decode_xml(payload))
    relates = request.findtext(f"./{{{SOAP_ENV}}}Header/{{{WSA}}}MessageID") or ""
    return encode_xml(
        f'<s:Envelope {NAMESPACES}><s:Header><a:Action>{action}</a:Action>'
        f'<a:RelatesTo>{relates}</a:RelatesTo></s:Header><s:Body>{body}</s:Body></s:Envelope>'
    )


# A server that opens one context and answers one final page with one object.
def one_page(payload: bytes) -> bytes:
    if "Enumerate</a:Action>" in decode_xml(payload):
        opened = ('<wsen:EnumerateResponse><wsen:EnumerationContext>ctx-1'
                  '</wsen:EnumerationContext></wsen:EnumerateResponse>')
        return envelope(ENUMERATE_RESPONSE_ACTION, payload, opened)
    item = ('<addata:user><addata:sAMAccountName><ad:value xsi:type="xsd:string">m.dupont'
            '</ad:value></addata:sAMAccountName></addata:user>')
    body = f'<wsen:PullResponse><wsen:Items>{item}</wsen:Items><wsen:EndOfSequence/>' \
           f'</wsen:PullResponse>'
    return envelope(PULL_RESPONSE_ACTION, payload, body)


# Replaces the transport factory for the length of one test.
def install(monkeypatch: pytest.MonkeyPatch, script: Callable[[bytes], bytes]) -> ScriptedTransport:
    transport = ScriptedTransport(script)

    # Returns the scripted transport for every session the command opens.
    def factory(server: str, port: int, timeout: float) -> ScriptedTransport:
        return transport

    monkeypatch.setattr(client_module, "open_transport", factory)
    return transport


# Runs the command and returns its status, its stdout and its stderr.
def run(monkeypatch: pytest.MonkeyPatch, capsys: Any, argv: Optional[List[str]] = None) -> Any:
    status = main(argv or ["search", "--server", "dc.example.test", "--base", BASE])
    captured = capsys.readouterr()
    return status, captured.out, captured.err


# A page arrives as one JSON document on stdout, with a zero status.
def test_a_page_is_one_document_and_a_zero_status(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    install(monkeypatch, one_page)
    status, out, err = run(monkeypatch, capsys)

    assert status == 0
    assert err == ""
    page = json.loads(out)
    assert page["objects"][0]["sAMAccountName"] == "m.dupont"


# The end of a sequence is an empty cursor, which is how a caller stops.
def test_the_end_of_a_sequence_is_an_empty_cursor(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    install(monkeypatch, one_page)
    _, out, _ = run(monkeypatch, capsys)

    assert json.loads(out)["cursor"] == ""


# A cursor the caller already holds skips the Enumerate entirely.
#
# That is the whole point of paging across invocations: a second page must not
# re-run the search, or every page after the first is the first.
def test_a_cursor_continues_rather_than_starting_again(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    transport = install(monkeypatch, one_page)
    argv = ["search", "--server", "dc.example.test", "--base", BASE, "--cursor", "ctx-1"]
    status, out, _ = run(monkeypatch, capsys, argv)

    assert status == 0
    assert json.loads(out)["objects"]
    sent = [decode_xml(request) for request in transport.requests]
    assert not any("Enumerate</a:Action>" in request for request in sent)


# A failure is a non-zero status with stdout left empty.
#
# Empty rather than an error document: a consumer that parsed stdout on a
# non-zero status would be reading a shape this command does not promise.
def test_a_failure_leaves_stdout_empty(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    # Refusing the whole exchange, the way an unreachable controller does.
    def broken(_: bytes) -> bytes:
        raise OSError("connection refused")

    install(monkeypatch, broken)
    status, out, err = run(monkeypatch, capsys)

    assert status == 1
    assert out == ""
    assert "connection refused" in err


# A bad argument is refused before anything is opened.
def test_an_unknown_scope_never_reaches_the_network(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    transport = install(monkeypatch, one_page)
    argv = ["search", "--server", "dc.example.test", "--base", BASE, "--scope", "One"]

    with pytest.raises(SystemExit):
        main(argv)

    assert transport.requests == []


# The attributes are the directory's own, not renamed on the way out.
def test_the_attributes_keep_the_names_the_directory_gave_them(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    install(monkeypatch, one_page)
    _, out, _ = run(monkeypatch, capsys)

    assert "sAMAccountName" in json.loads(out)["objects"][0]


# THE TOP OF THE DOMAIN IS ONE JSON DOCUMENT AND A ZERO STATUS.
#
# `search` requires a `--base` and nothing published one, so `hardensamba-webui`
# could not start a listing at all: it had no distinguished name to begin from
# and no way to ask for one. samba-adws#28.
def test_the_naming_context_is_one_document_and_a_zero_status(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    body = ROOT_DSE_BODY.format(context=NAMING_CONTEXT)
    install(monkeypatch, functools.partial(response_for, body=body))
    status, out, err = run(monkeypatch, capsys, NAMING_ARGV)

    assert status == 0
    assert err == ""
    assert json.loads(out) == {"defaultNamingContext": NAMING_CONTEXT}


# A NAMING CONTEXT IS PRINTED WHOLE, WHATEVER ITS LENGTH.
#
# `--format text` trims a value at `cli_text.WIDTH` because a page of objects
# is a spot check. This answer is not: it is the one value the operator pastes
# into `--base`, and a real domain passes 60 characters with four ordinary
# labels. An ellipsised distinguished name is worse than none, because it looks
# like something that can be used.
def test_a_long_naming_context_is_not_trimmed(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    body = ROOT_DSE_BODY.format(context=LONG_CONTEXT)
    install(monkeypatch, functools.partial(response_for, body=body))
    _, out, _ = run(monkeypatch, capsys, NAMING_ARGV + ["--format", "text"])

    assert out == f"defaultNamingContext: {LONG_CONTEXT}\n"


# It fails the way every other verb fails: non-zero, with stdout left empty.
def test_an_unreachable_controller_leaves_stdout_empty(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    install(monkeypatch, failing_response)
    status, out, err = run(monkeypatch, capsys, NAMING_ARGV)

    assert status == 1
    assert out == ""
    assert "connection refused" in err


# STATUS ANSWERS ONE JSON DOCUMENT, WHICH IS THE WHOLE POINT OF IT.
#
# `hardensamba-webui` probed this module with `search --help`, chosen for the
# right reason and unable to work: argparse prints help as text and that console
# parses stdout as JSON, so a module that was working perfectly read as
# installed and not answering. samba-adws#25.
def test_status_is_one_json_document_and_a_zero_status(capsys: Any) -> None:
    status, out, err = run(None, capsys, ["status"])

    assert status == 0
    assert err == ""
    said = json.loads(out)
    assert said["module"] == "samba-adws"
    assert "search" in said["verbs"]
    assert "naming-context" in said["verbs"]


# It opens nothing: a probe must not need a base, a query or a credential.
def test_status_never_touches_the_network(
    monkeypatch: pytest.MonkeyPatch, capsys: Any
) -> None:
    transport = install(monkeypatch, one_page)
    run(None, capsys, ["status"])

    assert transport.requests == []


# BOTH ORDERINGS OF --format PARSE.
#
# argparse gives a subparser's default priority over whatever the root already
# parsed, so a real default would silently produce json for
# `samba-adws --format text status` — and that is the position a person writes
# first. The flag is declared with SUPPRESS on a parent both levels inherit.
@pytest.mark.parametrize("argv", [["--format", "text", "status"],
                                  ["status", "--format", "text"]])
def test_the_format_flag_works_on_either_side_of_the_verb(
    capsys: Any, argv: List[str]
) -> None:
    status, out, _ = run(None, capsys, argv)

    assert status == 0
    assert out.startswith("module: samba-adws")


# json remains the default, because every caller written before the flag
# receives what it always received.
def test_json_is_still_what_a_caller_gets_without_asking(capsys: Any) -> None:
    _, out, _ = run(None, capsys, ["status"])
    assert json.loads(out)


# The version it reports is the version the manifest declares.
#
# A probe cannot read `MODULE.yaml`, so the number is held in the package as
# well — and two copies of a fact drift unless something holds them together.
def test_the_reported_version_is_the_one_the_manifest_declares() -> None:
    import re
    from pathlib import Path

    from samba_adws import __version__

    manifest = (Path(__file__).resolve().parent.parent / "MODULE.yaml").read_text(encoding="utf-8")
    declared = re.search(r"^version:\s*(\S+)\s*$", manifest, re.MULTILINE)

    assert declared is not None, "MODULE.yaml declares no version"
    assert declared.group(1).strip("'\"") == __version__
