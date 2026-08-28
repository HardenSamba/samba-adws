"""Addressing and envelope shape for the directory-changing operations.

**Three endpoints, not one.** WS-Transfer Create is addressed to
`Windows/ResourceFactory` and SetPassword to `Windows/AccountManagement`; the
rest go to `Windows/Resource`. That is what the published WCF endpoint table
gives for those contracts and what a Microsoft server requires.

This repository's server routes on `<a:Action>` alone — `HandlerRegistry.resolve`
never reads `<a:To>` — so the distinction costs nothing here and is the
difference between working and not working against a real one. `ResourceFactory`
is the one address this server does read: `CreateHandler._success` replaces
`ResourceFactory` with `Resource` in the `<a:To>` it echoes back to build the
ResourceCreated EPR, so addressing a create anywhere else makes that a no-op.

The endpoint is composed from `_request.endpoint_for` rather than rebuilt, which
is where the IPv6 host bracketing already lives; `_search_wire` set that
precedent.

**`WriteVerb` holds the three facts that vary together.** Which action, which of
those three endpoints, and whether the IMDA header rides along are one decision
per operation, not three arguments per call: a create is always the factory
endpoint and always IMDA, a SetPassword is always account management and never
IMDA. Passing them as one value is also what keeps every builder within the four
parameters `.flake8` allows, without pushing the pair back into the caller.
"""

import html
import uuid
from typing import NamedTuple, Tuple

from src.soap.namespaces import AD, ADDATA, DA, SOAP_ENV, WSA, XSD, XSI

from samba_adws._request import RESOURCE_PATH, endpoint_for

FACTORY_PATH = "/ActiveDirectoryWebServices/Windows/ResourceFactory"
ACCOUNT_PATH = "/ActiveDirectoryWebServices/Windows/AccountManagement"
_NS = (
    f'xmlns:s="{SOAP_ENV}" xmlns:a="{WSA}" xmlns:ad="{AD}" '
    f'xmlns:addata="{ADDATA}" xmlns:da="{DA}" xmlns:xsi="{XSI}" xmlns:xsd="{XSD}"'
)


# The wire signature of one write operation: what it is, where it is published,
# and whether it speaks the IMDA dialect.
class WriteVerb(NamedTuple):
    action: str
    path: str
    imda: bool


# Returns the net.tcp endpoint URI for one server's write service.
def endpoint(server: str, port: int, path: str = RESOURCE_PATH) -> str:
    return endpoint_for(server, port).replace(RESOURCE_PATH, path)


# Renders the WS-Addressing and ADWS routing headers for one write request.
#
# `IdentityManagementOperation` marks the IMDA dialect the way `_request` does
# for a Get. It is inert against this server and required by a real one.
def _headers(verb: WriteVerb, target: str, reference: str, message_id: str) -> str:
    imda = '<da:IdentityManagementOperation s:mustUnderstand="1"/>' if verb.imda else ""
    return (
        f'<a:Action s:mustUnderstand="1">{verb.action}</a:Action>'
        f'<a:MessageID>{message_id}</a:MessageID>'
        f'<a:ReplyTo><a:Address>{WSA}/anonymous</a:Address></a:ReplyTo>'
        f'<a:To s:mustUnderstand="1">{html.escape(target)}</a:To>{imda}'
        f'<ad:instance>ldap:389</ad:instance>'
        f'<ad:objectReferenceProperty>{html.escape(reference)}</ad:objectReferenceProperty>'
    )


# Builds one correlated SOAP 1.2 write request and returns it with its MessageID.
def build_envelope(verb: WriteVerb, target: str, reference: str,
                   body: str) -> Tuple[str, str]:
    message_id = f"urn:uuid:{uuid.uuid4()}"
    headers = _headers(verb, target, reference, message_id)
    envelope = (
        f'<s:Envelope {_NS}><s:Header>{headers}</s:Header>'
        f'<s:Body>{body}</s:Body></s:Envelope>'
    )
    return envelope, message_id
