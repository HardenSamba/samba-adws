"""Request builders for the directory-changing ADWS operations.

**No distinguished name is ever assembled or parsed here.** A create takes the
relative name and the parent separately and sends them as the two fields
`CreateHandler._resolve_dn` composes a name from; a rename takes a new relative
name and a new parent the same way. Assembling one would be this client deciding
how a directory spells a name, and parsing one would be it deciding how a
directory reads one — RFC 4514 escaping, quoted RDNs and multi-valued RDNs
included. The server already owns both answers.

**A rename sends only the half that changed.** `ModifyHandler._apply_rename`
falls back to the object's current relative name or its current parent for
whichever key is absent, so omitting one expresses rename-in-place and omitting
the other expresses a move, through one signature and with no name arithmetic.

**`Placement` is the pair a create and a rename both work in**: a relative name
and a container. Naming it says out loud that the two builders take the same
shape — a rename target is a placement with a half left out — and it keeps both
of them inside the four parameters `.flake8` allows without demoting the pair to
two loose strings the caller has to keep in order.
"""

import html
from typing import Dict, Mapping, NamedTuple, Sequence, Tuple

from src.soap.namespaces import CUSTOM_ACTIONS, WST

from samba_adws._request import RESOURCE_PATH
from samba_adws._write_body import request_body
from samba_adws._write_wire import (
    ACCOUNT_PATH,
    FACTORY_PATH,
    WriteVerb,
    build_envelope,
    endpoint,
)

CREATE_ACTION = f"{WST}/Create"
PUT_ACTION = f"{WST}/Put"
DELETE_ACTION = f"{WST}/Delete"
SET_PASSWORD_ACTION = f"{CUSTOM_ACTIONS}/AccountManagement/SetPassword"
_CREATE = WriteVerb(CREATE_ACTION, FACTORY_PATH, imda=True)
_MODIFY = WriteVerb(PUT_ACTION, RESOURCE_PATH, imda=True)
_DELETE = WriteVerb(DELETE_ACTION, RESOURCE_PATH, imda=False)
_SET_PASSWORD = WriteVerb(SET_PASSWORD_ACTION, ACCOUNT_PATH, imda=False)


# Where an object sits: its relative name and the container that holds it.
#
# A create gives both. A rename gives whichever half changes and leaves the
# other empty, which is how the server is told to keep the value it has.
class Placement(NamedTuple):
    rdn: str
    parent: str


# Builds a WS-Transfer Create request placing the object under its parent.
#
# The parent also rides the objectReferenceProperty header, which is the
# fallback `CreateHandler._resolve_dn` uses when the body names no parent.
def build_create_request(server: str, port: int, placement: Placement,
                         attributes: Mapping[str, Sequence[str]]) -> Tuple[str, str]:
    entries: Dict[str, Sequence[str]] = {
        "relativeDistinguishedName": (placement.rdn,),
        "container-hierarchy-parent": (placement.parent,),
    }
    entries.update(attributes)
    body = request_body(entries, change=False)
    target = endpoint(server, port, _CREATE.path)
    return build_envelope(_CREATE, target, placement.parent, body)


# Builds a WS-Transfer Put request replacing the named attributes.
def build_modify_request(server: str, port: int, identity: str,
                         changes: Mapping[str, Sequence[str]]) -> Tuple[str, str]:
    body = request_body(changes, change=True)
    target = endpoint(server, port, _MODIFY.path)
    return build_envelope(_MODIFY, target, identity, body)


# Builds a WS-Transfer Delete request for one object by distinguished name.
def build_delete_request(server: str, port: int, identity: str) -> Tuple[str, str]:
    target = endpoint(server, port, _DELETE.path)
    return build_envelope(_DELETE, target, identity, "")


# Builds the Put request that renames or moves one object (an LDAP modrdn).
#
# It must be a ModifyRequest: `ModifyHandler._read_entries` falls back to
# `find_add_request`, so an AddRequest here would still rename and the mistake
# would never surface. An absent half is omitted rather than sent empty; a half
# that is present is sent as given, which is why `_write_validation` refuses a
# blank one before it can reach the wire as a name made of spaces.
def build_rename_request(server: str, port: int, identity: str,
                         placement: Placement) -> Tuple[str, str]:
    entries: Dict[str, Sequence[str]] = {}
    if placement.rdn:
        entries["relativeDistinguishedName"] = (placement.rdn,)
    if placement.parent:
        entries["container-hierarchy-parent"] = (placement.parent,)
    body = request_body(entries, change=True)
    return build_envelope(_MODIFY, endpoint(server, port, _MODIFY.path), identity, body)


# Builds a custom-action SetPassword request; the secret rides the sealed body.
#
# It goes into one document and is never logged, returned or held. The body is
# the shape `SetPasswordHandler._extract` reads.
def build_set_password_request(server: str, port: int, identity: str,
                               password: str) -> Tuple[str, str]:
    body = (
        f'<SetPasswordRequest xmlns="{CUSTOM_ACTIONS}">'
        f'<AccountDN>{html.escape(identity)}</AccountDN>'
        f'<NewPassword>{html.escape(password)}</NewPassword>'
        f'</SetPasswordRequest>'
    )
    target = endpoint(server, port, _SET_PASSWORD.path)
    return build_envelope(_SET_PASSWORD, target, identity, body)
