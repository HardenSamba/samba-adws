"""Creating, changing and deleting an object, over the protocol the reads use.

The supported client could read and not write, so a caller wanting to create an
account had to reimplement the protocol layer or do nothing. `samba-adws#16` is
that gap; `hardensamba-webui`'s create, rename, move and delete dialogs are all
built and all pointed at routes that refuse, because there was no verb to call.

**The handlers have been able to do this all along.** `classes/handlers/`
carries create, modify, delete, group membership and password reset. What was
missing was never the capability, only a way for a Linux caller to reach it.

**Creating an account is three exchanges, in an order that matters**, and that
sequence lives in `accounts.py` beside this — one exchange per method here, the
ordering that composes them there, because the ordering is the piece of
knowledge and it deserves to be read on its own.

**Nothing here holds a password.** It reaches `set_password`, goes into one
document, and is not stored, logged or returned.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping

from samba_adws import _write_request as write
from samba_adws._codec import decode_xml, encode_xml
from samba_adws._envelope import parse_root, read_body
from samba_adws._validation import validate_identity
from samba_adws.client import ADWSClient
from samba_adws.errors import ADWSClientError


# Creating, changing and deleting, on the same connection settings as a read.
class ADWSWriteClient(ADWSClient):
    # Sends one built request and returns the body the server answered with.
    def _exchange_body(self, built: tuple[str, str], target: str) -> Any:
        envelope, message_id = built
        answer = self._exchange(encode_xml(envelope), target)
        return read_body(parse_root(decode_xml(answer), target), message_id, target)

    # Adds one object under a parent and answers with what it became.
    #
    # The relative name and the parent are sent separately: the server composes
    # the distinguished name, which is what a Windows client does and what keeps
    # this client out of the business of deciding how a directory spells one.
    def create(self, rdn: str, parent: str, attributes: Mapping[str, object]) -> Dict[str, str]:
        validate_identity(parent)
        validate_identity(rdn)
        body = self._exchange_body(
            write.build(write.Endpoint(self.server, self.port), write.CREATE,
                        write.add_body(rdn, parent, attributes)),
            parent,
        )
        found = body.findtext(f".//{{{write.AD}}}objectReferenceProperty")
        if not found:
            raise ADWSClientError("The directory did not report the new object.",
                                  "ProtocolError", parent)
        return {"distinguishedName": f"{rdn},{parent}", "objectGUID": found}

    # Replaces one attribute on one object.
    def modify(self, identity: str, name: str, value: object) -> None:
        validate_identity(identity)
        self._exchange_body(
            write.build(write.Endpoint(self.server, self.port), write.PUT,
                        write.modify_body(name, value), identity),
            identity,
        )

    # Sets one account's password, on the endpoint that accepts the action.
    def set_password(self, identity: str, password: str) -> None:
        validate_identity(identity)
        if not password:
            raise ADWSClientError("A password is required", "InvalidArgument", identity)
        self._exchange_body(
            write.build(write.Endpoint(self.server, self.port, write.ACCOUNT_PATH),
                        write.SET_PASSWORD, write.password_body(identity, password)),
            identity,
        )

    # Removes one object.
    def delete(self, identity: str) -> None:
        validate_identity(identity)
        self._exchange_body(
            write.build(write.Endpoint(self.server, self.port), write.DELETE, "", identity),
            identity,
        )
