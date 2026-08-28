"""Public read-write ADWS client, extending the read-only ADWSClient.

The supported client could read and not write, so a consumer wanting to create,
change, move or delete an object had to reimplement the wire protocol or do
nothing. That is `samba-adws#16`, and it is why `hardensamba-webui`'s create,
rename, move and delete dialogs are all built against routes that refuse.

**The handlers have been able to do this all along.** `classes/handlers/` has
carried create, modify, delete and password reset since before this file
existed. What was missing was never the capability, only a way for a Linux
caller to reach it.

**Creating a usable account is three exchanges, in an order that matters:**
`create`, then `set_password`, then `modify` to clear the disabled bit. A
directory refuses to enable an account that has no password, and enabling before
setting one would leave an enabled account without a password if the second call
failed. Doing it in that order means a failure anywhere leaves a disabled
object, which is the safe half-made thing. See `documentation/07-linux-client.md`
for the recipe; the orchestration itself belongs above this boundary.

**Nothing here holds a password.** It reaches `set_password`, goes into one
document, and is not stored, logged or returned. Faults are re-raised with the
account as the target and the reason the server gave, never the secret.
"""

from typing import Mapping, Sequence

from src.soap.namespaces import CUSTOM_ACTIONS, WST

from samba_adws._codec import decode_xml, encode_xml
from samba_adws._validation import validate_identity
from samba_adws._write_request import (
    Placement,
    build_create_request,
    build_delete_request,
    build_modify_request,
    build_rename_request,
    build_set_password_request,
)
from samba_adws._write_response import created_guid, parse_write_response
from samba_adws._write_validation import (
    validate_named_values,
    validate_password,
    validate_rename,
)
from samba_adws.client import ADWSClient

# Each is byte-identical to the REPLY_ACTION its handler declares. A response
# that names a different verb is refused: an acknowledgement of some other
# operation is not an acknowledgement of this one.
_CREATE_RESPONSE = f"{WST}/CreateResponse"
_PUT_RESPONSE = f"{WST}/PutResponse"
_DELETE_RESPONSE = f"{WST}/DeleteResponse"
_SET_PASSWORD_RESPONSE = f"{CUSTOM_ACTIONS}/AccountManagement/SetPasswordResponse"


# Adds the directory-changing verbs to the supported client surface.
class ADWSWriteClient(ADWSClient):

    # Creates one object under a parent and returns the objectGUID it was given.
    #
    # The relative name and the parent stay separate all the way to the wire, so
    # no distinguished name is composed on this side. The returned GUID is what
    # the directory reported; `CreateHandler._object_guid` answers the all-zero
    # UUID when it cannot read the attribute back, so
    # `00000000-0000-0000-0000-000000000000` means created but not read back.
    def create(self, rdn: str, parent: str,
               attributes: Mapping[str, Sequence[str]]) -> str:
        validate_identity(rdn)
        validate_identity(parent)
        clean = validate_named_values(attributes, False, parent)
        request, message_id = build_create_request(
            self.server, self.port, Placement(rdn, parent), clean)
        response = self._exchange(encode_xml(request), parent)
        body = parse_write_response(
            decode_xml(response), message_id, parent, _CREATE_RESPONSE)
        return created_guid(body, parent)

    # Replaces or clears the named attributes of one existing object.
    #
    # A mapping rather than one attribute per call: three edits are one LDAP
    # modify in one transaction, not three round trips that can half-apply.
    def modify(self, identity: str, changes: Mapping[str, Sequence[str]]) -> None:
        validate_identity(identity)
        clean = validate_named_values(changes, True, identity)
        request, message_id = build_modify_request(
            self.server, self.port, identity, clean)
        response = self._exchange(encode_xml(request), identity)
        parse_write_response(decode_xml(response), message_id, identity, _PUT_RESPONSE)

    # Deletes one object by distinguished name.
    def delete(self, identity: str) -> None:
        validate_identity(identity)
        request, message_id = build_delete_request(self.server, self.port, identity)
        response = self._exchange(encode_xml(request), identity)
        parse_write_response(decode_xml(response), message_id, identity, _DELETE_RESPONSE)

    # Renames one object, moves it, or both (an LDAP modrdn).
    #
    # Give `new_rdn` to rename in place, `new_parent` to move, or both. The half
    # that is not given is not sent, and the server keeps what the object has.
    # They are keyword-only because a bare second string is not self-evidently
    # a name rather than a container, and passing one for the other silently
    # moves an object instead of renaming it.
    def rename(self, identity: str, *,
               new_rdn: str = "", new_parent: str = "") -> None:
        validate_identity(identity)
        validate_rename(new_rdn, new_parent, identity)
        request, message_id = build_rename_request(
            self.server, self.port, identity, Placement(new_rdn, new_parent))
        response = self._exchange(encode_xml(request), identity)
        parse_write_response(decode_xml(response), message_id, identity, _PUT_RESPONSE)

    # Sets an account's password, carried in the sealed request body.
    def set_password(self, identity: str, password: str) -> None:
        validate_identity(identity)
        validate_password(password, identity)
        request, message_id = build_set_password_request(
            self.server, self.port, identity, password)
        response = self._exchange(encode_xml(request), identity)
        parse_write_response(
            decode_xml(response), message_id, identity, _SET_PASSWORD_RESPONSE)
