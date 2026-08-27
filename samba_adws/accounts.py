"""Making an account usable, which is three exchanges rather than one.

WS-Transfer Create adds the object, the account management action sets the
password, and only then can the account be enabled: a directory refuses to
enable one that has no password. A caller doing it in one step gets an account
that exists and cannot be used, and finds out a week later.

**It reports which of the three it reached.** An account created and left
disabled is a different outcome from one that failed, and telling them apart is
the difference between an administrator finishing the job and starting it again.

Separate from `write_client.py` because that holds one exchange per method and
this holds the order they go in, which is the part somebody has to read.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Mapping

from samba_adws.write_client import ADWSWriteClient

# What a directory sets on an ordinary, enabled account. 512 is
# ADS_UF_NORMAL_ACCOUNT with the disabled bit clear, from the published schema.
ENABLED = 512


# One account as the caller wants it to end up, password and all.
#
# `password` and `enable` travel together because the second is not reachable
# without the first, and a signature that took them as two more arguments would
# let a caller ask for a state the directory refuses.
@dataclass(frozen=True)
class NewUser:
    name: str
    parent: str
    attributes: Mapping[str, object]
    password: str = ""
    enable: bool = False


# One account, created and made usable, or created and honestly reported.
def create_user(client: ADWSWriteClient, wanted: NewUser) -> Dict[str, Any]:
    made: Dict[str, Any] = dict(
        client.create(f"CN={wanted.name}", wanted.parent, wanted.attributes)
    )
    made["passwordSet"] = False
    made["enabled"] = False
    if not wanted.password:
        return made
    client.set_password(made["distinguishedName"], wanted.password)
    made["passwordSet"] = True
    if wanted.enable:
        client.modify(made["distinguishedName"], "userAccountControl", ENABLED)
        made["enabled"] = True
    return made
