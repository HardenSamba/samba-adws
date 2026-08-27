"""The request bodies for the three ways an object changes.

Lifted from `hardensamba`, where 482 lines of client for this module had been
written inside the image repository — which its own `CLAUDE.md` forbids, and
which is HardenSamba/hardensamba#29. Only the part that existed nowhere else
came across: the Enumerate and Pull building beside it duplicated
`_search_request.py`, and importing a second copy of something already here
would have been the same mistake pointing the other way.

**Three exchanges, and the order is the point.** WS-Transfer Create adds the
object, the account management action sets the password, and only then can the
account be enabled: a directory refuses to enable one that has no password.
Doing it in one step produces an account that exists and cannot be used, which
is the kind of half-made thing an administrator finds a week later.

**The client never sends a full distinguished name on a create.** It sends the
relative name and the parent, and the server assembles them, which is what a
Windows client does. Sending an assembled name would be this client deciding how
a directory composes one.

**Every value is escaped where it enters the document.** These are attribute
values an administrator typed, and a name carrying `&` or `<` would otherwise
produce a request the server cannot parse — or, with less luck, one it parses
differently than intended.
"""

from __future__ import annotations

import html
import uuid
from dataclasses import dataclass
from typing import Iterable, Mapping, Tuple

from samba_adws._request import RESOURCE_PATH, endpoint_for

# The endpoint each action is spoken to. Setting a password is an account
# management action and is refused on the resource endpoint.
ACCOUNT_PATH = "/ActiveDirectoryWebServices/Windows/AccountManagement"

# WS-Transfer, and the two Active Directory dialects layered on it. The server
# names the same three: `classes/handlers/delete.py` calls its own the
# "WS-Transfer Delete action".
WST = "http://schemas.xmlsoap.org/ws/2004/09/transfer"
CREATE = f"{WST}/Create"
PUT = f"{WST}/Put"
DELETE = f"{WST}/Delete"
SET_PASSWORD = ("http://schemas.microsoft.com/2008/1/ActiveDirectory"
                "/CustomActions/AccountManagement/SetPassword")
LDAP_DIALECT = ("http://schemas.microsoft.com/2008/1/ActiveDirectory"
                "/Dialect/LdapDialect")
DA = ("http://schemas.microsoft.com/2006/11/IdentityManagement"
      "/DirectoryAccess")
SOAP_ENV = "http://www.w3.org/2003/05/soap-envelope"
WSA = "http://www.w3.org/2005/08/addressing"
AD = "http://schemas.microsoft.com/2008/1/ActiveDirectory"
ADDATA = "http://schemas.microsoft.com/2008/1/ActiveDirectory/Data"
XSI = "http://www.w3.org/2001/XMLSchema-instance"
XSD = "http://www.w3.org/2001/XMLSchema"


# One attribute and its values, in the form the directory access dialect takes.
def attribute(name: str, values: Iterable[object]) -> str:
    items = "".join(f'<ad:value xsi:type="xsd:string">{html.escape(str(value))}</ad:value>'
                    for value in values)
    return ("<da:AttributeTypeAndValue>"
            f"<da:AttributeType>{html.escape(name)}</da:AttributeType>"
            f"<da:AttributeValue>{items}</da:AttributeValue>"
            "</da:AttributeTypeAndValue>")


# The body that adds one object under a parent.
def add_body(rdn: str, parent: str, attributes: Mapping[str, object]) -> str:
    parts = [attribute("ad:relativeDistinguishedName", [rdn]),
             attribute("ad:container-hierarchy-parent", [parent])]
    for name, values in attributes.items():
        given = values if isinstance(values, list | tuple) else [values]
        parts.append(attribute(f"addata:{name}", given))
    joined = "".join(parts)
    return f'<da:AddRequest Dialect="{LDAP_DIALECT}" xmlns:da="{DA}">{joined}</da:AddRequest>'


# The body that replaces one attribute's value.
def modify_body(name: str, value: object) -> str:
    return (f'<da:ModifyRequest Dialect="{LDAP_DIALECT}" xmlns:da="{DA}">'
            '<da:Change Operation="replace">'
            f"<da:AttributeType>addata:{html.escape(name)}</da:AttributeType>"
            "<da:AttributeValue>"
            f'<ad:value xsi:type="xsd:string">{html.escape(str(value))}</ad:value>'
            "</da:AttributeValue></da:Change></da:ModifyRequest>")


# The body that sets one account's password.
#
# The password reaches this function and goes straight into the document. It is
# never logged, never returned and never held: the caller is expected to have it
# for exactly as long as this call takes.
def password_body(account_dn: str, password: str) -> str:
    return ('<SetPasswordRequest xmlns="http://schemas.microsoft.com/2008/1'
            '/ActiveDirectory/CustomActions">'
            f"<AccountDN>{html.escape(account_dn)}</AccountDN>"
            f"<NewPassword>{html.escape(password)}</NewPassword>"
            "</SetPasswordRequest>")


# Where one action is sent: a controller, and the endpoint on it that takes it.
#
# The path is part of the address rather than an argument of its own, because
# setting a password is an account management action and is refused on the
# resource endpoint - so an action and its endpoint are not free to disagree.
@dataclass(frozen=True)
class Endpoint:
    server: str
    port: int
    path: str = RESOURCE_PATH


# One correlated SOAP 1.2 request and its MessageID.
#
# `identity` names the object the action applies to and is empty on a create,
# where there is no object yet.
def build(where: Endpoint, action: str, body: str, identity: str = "") -> Tuple[str, str]:
    message_id = f"urn:uuid:{uuid.uuid4()}"
    endpoint = endpoint_for(where.server, where.port).replace(RESOURCE_PATH, where.path)
    reference = (f"<ad:objectReferenceProperty>{html.escape(identity)}"
                 "</ad:objectReferenceProperty>") if identity else ""
    return (
        f'<s:Envelope xmlns:s="{SOAP_ENV}" xmlns:a="{WSA}" xmlns:ad="{AD}" '
        f'xmlns:addata="{ADDATA}" xmlns:da="{DA}" xmlns:xsi="{XSI}" '
        f'xmlns:xsd="{XSD}"><s:Header>'
        f'<a:Action s:mustUnderstand="1">{action}</a:Action>'
        f"<a:MessageID>{message_id}</a:MessageID>"
        f"<a:ReplyTo><a:Address>{WSA}/anonymous</a:Address></a:ReplyTo>"
        f'<a:To s:mustUnderstand="1">{html.escape(endpoint)}</a:To>'
        f"<ad:instance>ldap:389</ad:instance>{reference}"
        f"</s:Header><s:Body>{body}</s:Body></s:Envelope>",
        message_id,
    )
