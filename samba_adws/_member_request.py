"""The Put that adds or removes one group member, as a delta and never a replace.

**`modify` cannot do this, and the reason is a lost update.** `modify` sends a
`Change` with no operation, which `ModifyHandler` applies as a replace of the
whole attribute. On `member` that is a read-modify-write: two administrators
open the same group, each reads the list, each appends one name, each writes the
list back — and the second write silently undoes the first. Not an error, not a
conflict; the name is simply gone. `member` is the attribute most likely to be
edited by two people at once, on a domain where group membership is how
permission is granted. That is `#21`.

**A delta has no such failure.** `Operation="add"` and `Operation="delete"` are
what the ActiveDirectory module's own `Add-ADGroupMember` and
`Remove-ADGroupMember` send, and `LdapAttrBuilder` maps them to `FLAG_MOD_ADD`
and `FLAG_MOD_DELETE`: the directory applies the change to the one value named,
and two concurrent adds both land. `tests/test_member_request.py` asserts that
what this builds parses to exactly what the cmdlet's recorded request parses to.

**One member per call, on purpose.** It is how the directory models the edit,
and it is what lets a console mark one row busy while the others stay live.
"""

from typing import NamedTuple, Tuple

from samba_adws._request import RESOURCE_PATH
from samba_adws._write_body import request_body
from samba_adws._write_request import PUT_ACTION
from samba_adws._write_wire import WriteVerb, build_envelope, endpoint

# The two operations on the wire. `delete`, not `remove`: it is the name the
# cmdlet sends and the name `LdapAttrBuilder` reads.
ADD = "add"
REMOVE = "delete"
_MEMBER = WriteVerb(PUT_ACTION, RESOURCE_PATH, imda=True)


# One membership edit: the group, and the member added to it or removed from it.
class Membership(NamedTuple):
    group: str
    member: str


# Builds the WS-Transfer Put that applies one membership delta to one group.
#
# The group rides the objectReferenceProperty header, which is where
# `ModifyHandler` reads the target from; the member is the single value of the
# one Change in the body.
def build_member_request(server: str, port: int, membership: Membership,
                         operation: str) -> Tuple[str, str]:
    body = request_body({"member": (membership.member,)}, change=True,
                        operation=operation)
    target = endpoint(server, port, _MEMBER.path)
    return build_envelope(_MEMBER, target, membership.group, body)
