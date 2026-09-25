"""`new-user` and `set-password`: the password on stdin, one document or none.

The protocol under these verbs is tested with the write client. What is tested
here is the command's side of it: the password comes from stdin and never from
an argument, a success is one JSON document, and a refusal leaves stdout empty
with the reason, and the account it left behind, on stderr.
"""

import io
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import pytest

from samba_adws import cli_write
from samba_adws._account import Account
from samba_adws._write_request import Placement
from samba_adws.account_errors import AccountLeftDisabled
from samba_adws.cli import main
from samba_adws.errors import ADWSClientError

SERVER = ["--server", "dc.example.test"]
PARENT = "OU=Staff,DC=example,DC=test"
DN = f"CN=Marie Dupont,{PARENT}"
GUID = "6c8dd5f1-6b3c-4f1a-9d33-6b1f0a2e77aa"
NEW_USER = ["new-user", *SERVER, "--parent", PARENT, "--rdn", "CN=Marie Dupont",
            "--sam", "m.dupont"]


# What the fake client and account sequence were asked to do.
class Recorder:
    # Starts with nothing asked.
    def __init__(self) -> None:
        self.calls: List[Tuple[Any, ...]] = []

    # Stands in for create_usable_account.
    def create(self, client: Any, placement: Placement,
               attributes: Mapping[str, Sequence[str]], password: str) -> Account:
        self.calls.append(("create", placement, dict(attributes), password))
        return Account(DN, GUID, "usable")

    # Stands in for ADWSWriteClient.set_password.
    def set_password(self, identity: str, password: str) -> None:
        self.calls.append(("set_password", identity, password))


# Replaces the client and the account sequence, and feeds stdin.
def install(monkeypatch: pytest.MonkeyPatch, stdin: str) -> Recorder:
    recorder = Recorder()
    monkeypatch.setattr(cli_write, "create_usable_account", recorder.create)
    monkeypatch.setattr(cli_write, "ADWSWriteClient", lambda server, port: recorder)
    monkeypatch.setattr("sys.stdin", io.StringIO(stdin))
    return recorder


# Runs the command and returns its status, its stdout and its stderr.
def run(capsys: Any, argv: List[str]) -> Tuple[int, str, str]:
    status = main(argv)
    captured = capsys.readouterr()
    return status, captured.out, captured.err


# A created account is one document: where it is, its GUID, how far it got.
def test_new_user_answers_the_account(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    recorder = install(monkeypatch, "S3cret-pass\n")

    status, out, err = run(capsys, NEW_USER + ["--upn", "m.dupont@example.test"])

    assert (status, err) == (0, "")
    assert out == f'{{"dn":"{DN}","objectGUID":"{GUID}","reached":"usable"}}\n'
    verb, placement, attributes, password = recorder.calls[0]
    assert placement == Placement("CN=Marie Dupont", PARENT)
    assert password == "S3cret-pass"
    assert attributes == {"objectClass": ["user"], "sAMAccountName": ["m.dupont"],
                          "userPrincipalName": ["m.dupont@example.test"]}


# The line ending a pipe adds is not part of the password; anything else is.
def test_set_password_takes_one_line_from_stdin(
        monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    recorder = install(monkeypatch, " spaced pass \r\nsecond line\n")

    status, out, _ = run(capsys, ["set-password", *SERVER, "--identity", DN])

    assert status == 0
    assert out == f'{{"dn":"{DN}","passwordSet":true}}\n'
    assert recorder.calls == [("set_password", DN, " spaced pass ")]


# There is no flag a password could be passed in.
def test_no_verb_accepts_a_password_argument(monkeypatch: pytest.MonkeyPatch) -> None:
    install(monkeypatch, "")
    for argv in (NEW_USER + ["--password", "x"],
                 ["set-password", *SERVER, "--identity", DN, "--password", "x"]):
        with pytest.raises(SystemExit) as exited:
            main(argv)
        assert exited.value.code == 2


# On a terminal the password is typed without echo, not read as a line.
def test_a_terminal_is_asked_without_echo(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    recorder = install(monkeypatch, "")
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr(cli_write.getpass, "getpass", lambda prompt: "typed")

    assert run(capsys, ["set-password", *SERVER, "--identity", DN])[0] == 0
    assert recorder.calls == [("set_password", DN, "typed")]


# A refusal before the create leaves nothing, and stdout empty.
def test_a_refused_create_leaves_stdout_empty(
        monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    install(monkeypatch, "pass\n")

    # Refuses the way the write client does.
    def refuse(*_: Any) -> Account:
        raise ADWSClientError("Access denied", "AccessDenied", PARENT)

    monkeypatch.setattr(cli_write, "create_usable_account", refuse)
    status, out, err = run(capsys, NEW_USER)

    assert (status, out) == (1, "")
    assert err.startswith("AccessDenied: Access denied")


# A refusal after the create says the account exists, and how far it got.
def test_an_account_left_disabled_is_named(monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    install(monkeypatch, "pass\n")
    left = Account(DN, GUID, "created")

    # Refuses at the password, after the object exists.
    def half(*_: Any) -> Account:
        raise AccountLeftDisabled(ADWSClientError("policy", "PasswordPolicy"), left)

    monkeypatch.setattr(cli_write, "create_usable_account", half)
    status, out, err = run(capsys, NEW_USER)

    assert (status, out) == (1, "")
    assert "the account exists, disabled; reached: created" in err


# `status` names both verbs, since a consumer reads it to decide what it may call.
def test_status_names_the_write_verbs(capsys: Any) -> None:
    status, out, _ = run(capsys, ["status"])

    assert status == 0
    assert '"new-user"' in out and '"set-password"' in out


# An empty stdin is refused by the client's own check, before any exchange.
def test_an_empty_password_is_refused_before_anything_is_sent(
        monkeypatch: pytest.MonkeyPatch, capsys: Any) -> None:
    import samba_adws.client as client_module

    # Fails the test if the command ever opens a connection.
    def no_socket(*_: Any) -> Dict[str, Any]:
        raise AssertionError("a connection was opened for an empty password")

    monkeypatch.setattr(client_module, "open_transport", no_socket)
    monkeypatch.setattr("sys.stdin", io.StringIO("\n"))
    status, out, err = run(capsys, ["set-password", *SERVER, "--identity", DN])

    assert (status, out) == (1, "")
    assert "InvalidArgument" in err
