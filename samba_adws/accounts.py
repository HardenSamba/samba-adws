"""Making an account usable, which is three exchanges rather than one.

WS-Transfer `Create` adds the object, the account-management action sets the
password, and only then can the account be enabled: a directory refuses to
enable one that has no password. A caller doing it in one step gets an account
that exists, reports success and cannot sign in, and finds out a week later.

Separate from `write_client.py` because that holds one exchange per method and
this holds the order they go in, which is the part somebody has to read.
"""

from dataclasses import dataclass
from typing import Dict, Mapping, Sequence

from samba_adws.errors import ADWSClientError
from samba_adws.write_client import ADWSWriteClient

# What a directory sets on an ordinary, enabled account: ADS_UF_NORMAL_ACCOUNT
# with the disabled bit clear.
ENABLED = "512"


# One account as the caller wants it to end up, password and all.
#
# `password` and `enable` travel together because the second is not reachable
# without the first, and separate arguments would let a caller ask for a state
# the directory refuses.
@dataclass(frozen=True)
class NewUser:
    identity: str
    attributes: Mapping[str, Sequence[str]]
    password: str = ""
    enable: bool = False


# Refuses a combination the directory would reject, before anything is sent.
def _refuse_unreachable(wanted: NewUser) -> None:
    if wanted.enable and not wanted.password:
        raise ADWSClientError(
            "An account cannot be enabled without a password; set one or "
            "create the account disabled.",
            "InvalidArgument", wanted.identity)


# The exchanges that follow a create, in the order a directory accepts them.
def _finish(client: ADWSWriteClient, wanted: NewUser, reached: Dict[str, object]) -> None:
    if not wanted.password:
        return
    client.set_password(wanted.identity, wanted.password)
    reached["passwordSet"] = True
    if not wanted.enable:
        return
    client.modify(wanted.identity, {"userAccountControl": [ENABLED]})
    reached["enabled"] = True


# Reports a failure that left an object behind, so a retry does not create twice.
def _left_behind(error: ADWSClientError, reached: Dict[str, object]) -> ADWSClientError:
    state = "with a password, disabled" if reached["passwordSet"] else "without a password"
    return ADWSClientError(
        f"{error.message} The account was created and left {state}; it exists, "
        "so a retry must not create it again.",
        error.code, error.target)


# One account, created and made usable, or created and honestly reported.
#
# The returned mapping says which of the three exchanges were reached. An
# account created and left disabled is a different outcome from one that
# failed, and telling them apart is the difference between an administrator
# finishing the job and starting it again.
def create_user(client: ADWSWriteClient, wanted: NewUser) -> Dict[str, object]:
    _refuse_unreachable(wanted)
    reached: Dict[str, object] = {
        "distinguishedName": wanted.identity,
        "created": False, "passwordSet": False, "enabled": False,
    }
    client.create(wanted.identity, wanted.attributes)
    reached["created"] = True
    try:
        _finish(client, wanted, reached)
    except ADWSClientError as error:
        raise _left_behind(error, reached) from error
    return reached
