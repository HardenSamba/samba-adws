"""Public read-write ADWS client, extending the read-only ADWSClient."""

from typing import Mapping, Sequence

from src.soap.namespaces import CUSTOM_ACTIONS, WST

from samba_adws._codec import decode_xml, encode_xml
from samba_adws._validation import validate_identity
from samba_adws._write_request import (
    build_create_request,
    build_delete_request,
    build_modify_request,
    build_rename_request,
    build_set_password_request,
)
from samba_adws._write_response import parse_write_response
from samba_adws._write_validation import (
    validate_named_values,
    validate_new_dn,
    validate_password,
)
from samba_adws.client import ADWSClient

_CREATE_RESPONSE = f"{WST}/CreateResponse"
_PUT_RESPONSE = f"{WST}/PutResponse"
_DELETE_RESPONSE = f"{WST}/DeleteResponse"
_SET_PASSWORD_RESPONSE = f"{CUSTOM_ACTIONS}/AccountManagement/SetPasswordResponse"


# Adds the directory-changing verbs to the supported client surface.
class ADWSWriteClient(ADWSClient):

    # Creates one object at a distinguished name with the given attributes.
    def create(self, identity: str, attributes: Mapping[str, Sequence[str]]) -> None:
        validate_identity(identity)
        clean = validate_named_values(attributes, False, identity)
        request, message_id = build_create_request(self.server, self.port, identity, clean)
        response = self._exchange(encode_xml(request), identity)
        parse_write_response(decode_xml(response), message_id, identity, _CREATE_RESPONSE)

    # Replaces or clears the named attributes of one existing object.
    def modify(self, identity: str, changes: Mapping[str, Sequence[str]]) -> None:
        validate_identity(identity)
        clean = validate_named_values(changes, True, identity)
        request, message_id = build_modify_request(self.server, self.port, identity, clean)
        response = self._exchange(encode_xml(request), identity)
        parse_write_response(decode_xml(response), message_id, identity, _PUT_RESPONSE)

    # Deletes one object by distinguished name.
    def delete(self, identity: str) -> None:
        validate_identity(identity)
        request, message_id = build_delete_request(self.server, self.port, identity)
        response = self._exchange(encode_xml(request), identity)
        parse_write_response(decode_xml(response), message_id, identity, _DELETE_RESPONSE)

    # Sets an account's password, carried in the sealed request body.
    def set_password(self, identity: str, password: str) -> None:
        validate_identity(identity)
        validate_password(password, identity)
        request, message_id = build_set_password_request(
            self.server, self.port, identity, password)
        response = self._exchange(encode_xml(request), identity)
        parse_write_response(
            decode_xml(response), message_id, identity, _SET_PASSWORD_RESPONSE)

    # Moves or renames one object to a new distinguished name (an LDAP modrdn).
    def rename(self, identity: str, new_dn: str) -> None:
        validate_identity(identity)
        validate_new_dn(new_dn, identity)
        request, message_id = build_rename_request(self.server, self.port, identity, new_dn)
        response = self._exchange(encode_xml(request), identity)
        parse_write_response(decode_xml(response), message_id, identity, _PUT_RESPONSE)
