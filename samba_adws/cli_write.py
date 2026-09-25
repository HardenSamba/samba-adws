"""The write verbs: `new-user` and `set-password`.

**Two verbs, and no delete.** These are what `hardensamba-powershell` needs for
`New-ADUser` and `Set-ADAccountPassword`, which it reached until now through a
copy of this module's client carried in another repository
(HardenSamba/hardensamba#29). Neither destroys anything a person cannot put
back. A delete, a move or a rename reached from a shell is still not exposed:
it needs a confirmation story of its own, and nobody has asked for one.

**The password never touches argv.** `argv` is world-readable on Linux and
lands in shell history, so the password arrives on stdin: one line from a pipe,
or typed without echo when stdin is a terminal. It goes to `ADWSWriteClient`
and nowhere else, as the client promises.

**`new-user` makes a usable account, through `create_usable_account`.** Created
disabled, given its password, then enabled, in that order. A failure after the
create is refused like any other, with the account named and the step it
reached in the reason: the object exists, disabled, and the next attempt must
not create a second one beside it.
"""

import argparse
import getpass
import sys
from typing import Dict, List

from samba_adws import cli_format, cli_output
from samba_adws._write_request import Placement
from samba_adws.accounts import create_usable_account
from samba_adws.errors import ADWSClientError
from samba_adws.write_client import ADWSWriteClient

# The attributes `new-user` sets from its flags, beside the RDN and the parent.
OPTIONAL = (("upn", "userPrincipalName"), ("given", "givenName"),
            ("surname", "sn"), ("display", "displayName"))


# Declares both verbs. The port default is passed in because `cli` owns it.
def add_parsers(verbs: "argparse._SubParsersAction[argparse.ArgumentParser]",
                common: argparse.ArgumentParser, default_port: int) -> None:
    new_user = verbs.add_parser("new-user", parents=[common],
                                help="create an enabled user; the password on stdin")
    set_password = verbs.add_parser("set-password", parents=[common],
                                    help="reset a password; the password on stdin")
    for parser in (new_user, set_password):
        parser.add_argument("--server", required=True, help="the controller to ask")
        parser.add_argument("--port", type=int, default=default_port)
    new_user.add_argument("--parent", required=True, help="the container, as a DN")
    new_user.add_argument("--rdn", required=True, help="the relative name, e.g. CN=Marie Dupont")
    new_user.add_argument("--sam", required=True, help="sAMAccountName")
    for flag, attribute in OPTIONAL:
        new_user.add_argument(f"--{flag}", default="", help=attribute)
    set_password.add_argument("--identity", required=True, help="the account's DN")


# The password: one line from a pipe, or typed without echo on a terminal.
def read_password() -> str:
    if sys.stdin.isatty():
        return getpass.getpass("Password: ")
    return sys.stdin.readline().rstrip("\r\n")


# The attributes of the new account, from the flags that were given.
def attributes(options: argparse.Namespace) -> Dict[str, List[str]]:
    chosen = {"objectClass": ["user"], "sAMAccountName": [options.sam]}
    for flag, attribute in OPTIONAL:
        if getattr(options, flag):
            chosen[attribute] = [getattr(options, flag)]
    return chosen


# Creates one enabled account and prints where it is and what it was given.
def new_user(options: argparse.Namespace) -> int:
    try:
        password = read_password()
        client = ADWSWriteClient(options.server, options.port)
        account = create_usable_account(
            client, Placement(options.rdn, options.parent), attributes(options), password)
    except ADWSClientError as error:
        return cli_output.refuse(f"{error.code}: {error}")
    answer = {"dn": account.dn, "objectGUID": account.guid, "reached": account.reached}
    return cli_output.emit(answer, cli_format.wanted(options))


# Resets one account's password and says which account.
def set_password(options: argparse.Namespace) -> int:
    try:
        password = read_password()
        ADWSWriteClient(options.server, options.port).set_password(options.identity, password)
    except ADWSClientError as error:
        return cli_output.refuse(f"{error.code}: {error}")
    return cli_output.emit({"dn": options.identity, "passwordSet": True},
                           cli_format.wanted(options))
