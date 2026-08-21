"""Request builders for the directory-changing ADWS operations."""

import html
from typing import Dict, Mapping, Sequence, Tuple

from src.soap.namespaces import CUSTOM_ACTIONS, WST

from samba_adws._write_body import request_body, split_dn
from samba_adws._write_wire import build_envelope, endpoint

CREATE_ACTION = f"{WST}/Create"
PUT_ACTION = f"{WST}/Put"
DELETE_ACTION = f"{WST}/Delete"
SET_PASSWORD_ACTION = f"{CUSTOM_ACTIONS}/AccountManagement/SetPassword"


# Builds a WS-Transfer Create request placing the object under its parent.
def build_create_request(server: str, port: int, identity: str,
                         attributes: Mapping[str, Sequence[str]]) -> Tuple[str, str]:
    rdn, parent = split_dn(identity)
    entries: Dict[str, Sequence[str]] = {
        "relativeDistinguishedName": (rdn,), "container-hierarchy-parent": (parent,),
    }
    entries.update(attributes)
    body = request_body(entries, change=False)
    target = endpoint(server, port, factory=True)
    return build_envelope(CREATE_ACTION, target, parent, body, imda=True)


# Builds a WS-Transfer Put request replacing the named attributes.
def build_modify_request(server: str, port: int, identity: str,
                         changes: Mapping[str, Sequence[str]]) -> Tuple[str, str]:
    body = request_body(changes, change=True)
    target = endpoint(server, port)
    return build_envelope(PUT_ACTION, target, identity, body, imda=True)


# Builds a WS-Transfer Delete request for one object by distinguished name.
def build_delete_request(server: str, port: int, identity: str) -> Tuple[str, str]:
    target = endpoint(server, port)
    return build_envelope(DELETE_ACTION, target, identity, "", imda=False)


# Builds a WS-Transfer Put request that renames or moves the object (modrdn).
def build_rename_request(server: str, port: int, identity: str,
                         new_dn: str) -> Tuple[str, str]:
    rdn, parent = split_dn(new_dn)
    entries: Dict[str, Sequence[str]] = {
        "relativeDistinguishedName": (rdn,), "container-hierarchy-parent": (parent,),
    }
    body = request_body(entries, change=True)
    target = endpoint(server, port)
    return build_envelope(PUT_ACTION, target, identity, body, imda=True)


# Builds a custom-action SetPassword request; the secret rides the sealed body.
def build_set_password_request(server: str, port: int, identity: str,
                               password: str) -> Tuple[str, str]:
    body = (
        f'<SetPasswordRequest xmlns="{CUSTOM_ACTIONS}">'
        f'<AccountDN>{html.escape(identity)}</AccountDN>'
        f'<NewPassword>{html.escape(password)}</NewPassword>'
        f'</SetPasswordRequest>'
    )
    target = endpoint(server, port)
    return build_envelope(SET_PASSWORD_ACTION, target, identity, body, imda=False)
