"""Making an account usable, which is three exchanges in an order that matters.

WS-Transfer `Create` adds the object; the account-management `SetPassword`
gives it a password; a `Put` on `userAccountControl` clears the disabled bit.
A directory refuses to enable an account that has no password, so the order is
forced in one direction — and the reason it is worth a module is the other
direction. **A failure at any step leaves a disabled object**, which is inert.
Enabling first would leave, on a failure at step two, an enabled account with
no password: the kind of half-made thing nobody finds until it is used. That
ordering is a security property, and until now it was enforced by prose in
`documentation/07-linux-client.md`. This is `#43`.

**The create is disabled whatever the caller asked for.** `userAccountControl`
is this sequence's to set, at both ends: `NORMAL_ACCOUNT | PASSWD_NOTREQD |
ACCOUNTDISABLE` going in, `NORMAL_ACCOUNT` coming out. A caller that supplies
it is refused before anything is sent, rather than overridden in silence.

**The password is checked before the create, not after.** `set_password`
checks it too, but by then the object exists; a refusal there would leave an
account behind for an input that could have been refused up front.

**The relative name is the caller's, verbatim.** `Placement` is the same pair
`create` takes. The one place this package puts two halves of a name back
together is below, and it is a caller re-joining the two strings it just
passed — not this package deciding how a directory spells a name, which is the
work an RFC 4514 parser exists for and which the server owns.

**The password is in the exchange that sets it and in no other.** Not the
create, not the result, not any error raised on the way.
"""

import functools
from typing import Callable, Dict, Mapping, Sequence

from samba_adws._account import Account
from samba_adws._write_request import Placement
from samba_adws._write_validation import validate_password
from samba_adws.account_errors import AccountLeftDisabled
from samba_adws.errors import ADWSClientError
from samba_adws.write_client import ADWSWriteClient

# From [MS-ADTS] 2.2.16, userAccountControl bits.
ACCOUNT_DISABLED = 0x0002       # ADS_UF_ACCOUNTDISABLE
PASSWORD_NOT_REQUIRED = 0x0020  # ADS_UF_PASSWD_NOTREQD
NORMAL_ACCOUNT = 0x0200         # ADS_UF_NORMAL_ACCOUNT
# What the object is created with: a normal account, disabled, and allowed to
# exist without a password for the instant before it is given one.
DISABLED_AT_CREATION = NORMAL_ACCOUNT | PASSWORD_NOT_REQUIRED | ACCOUNT_DISABLED
# What it ends up as: a normal account, enabled, password required.
ENABLED = NORMAL_ACCOUNT

# The three steps, as `Account.reached` names them.
CREATED = "created"
PASSWORD_SET = "password-set"
USABLE = "usable"


# The attributes the create sends: the caller's, with the control this owns.
def disabled_at_creation(attributes: Mapping[str, Sequence[str]],
                         target: str) -> Dict[str, Sequence[str]]:
    if any(name.lower() == "useraccountcontrol" for name in attributes):
        raise ADWSClientError(
            "userAccountControl is set by this sequence, disabled at creation and "
            "enabled last; do not supply it", "InvalidArgument", target)
    entries: Dict[str, Sequence[str]] = dict(attributes)
    entries["userAccountControl"] = (str(DISABLED_AT_CREATION),)
    return entries


# Runs one exchange after the create, naming the account it would leave behind.
def _after_create(reached: str, account: Account, exchange: Callable[[], None]) -> None:
    try:
        exchange()
    except ADWSClientError as refusal:
        raise AccountLeftDisabled(refusal, account._replace(reached=reached)) from refusal


# Creates an account, gives it a password, and enables it, in that order.
#
# Returns the account with `reached` set to `USABLE`. A refusal at the create
# is the write client's own error and leaves nothing behind. A refusal after it
# is `AccountLeftDisabled`, carrying the account as it was left.
def create_usable_account(client: ADWSWriteClient, placement: Placement,
                          attributes: Mapping[str, Sequence[str]],
                          password: str) -> Account:
    dn = f"{placement.rdn},{placement.parent}"
    validate_password(password, dn)
    guid = client.create(placement.rdn, placement.parent,
                         disabled_at_creation(attributes, dn))
    account = Account(dn, guid, CREATED)
    _after_create(CREATED, account,
                  functools.partial(client.set_password, dn, password))
    _after_create(PASSWORD_SET, account, functools.partial(
        client.modify, dn, {"userAccountControl": (str(ENABLED),)}))
    return account._replace(reached=USABLE)
