"""SOAP request construction for the supported Enumerate and Pull operations.

Two messages, because WS-Enumeration is two messages. `Enumerate` states the
query and gets back an opaque context; `Pull` exchanges that context for a batch
and, unless the sequence ended, a context to use next. A caller that wants one
screenful sends one of each; a caller that wants a domain sends one Enumerate
and as many Pulls as it needs.

**The filter travels as an LDAP filter, escaped once.** The server unescapes it
and hands it to `ldb` after normalising it, so `(&(objectClass=user)(cn=a*))`
means what it says. It is the caller's filter and nothing here rewrites it: a
client that quietly widened `(objectClass=user)` would be answering a question
nobody asked.
"""

import html
import uuid
from typing import Tuple

from src.soap.namespaces import ADLQ, WSEN

from samba_adws._search_validation import SearchQuery
from samba_adws._search_wire import enumeration_endpoint, envelope

ENUMERATE_ACTION = f"{WSEN}/Enumerate"
ENUMERATE_RESPONSE_ACTION = f"{ENUMERATE_ACTION}Response"
PULL_ACTION = f"{WSEN}/Pull"
PULL_RESPONSE_ACTION = f"{PULL_ACTION}Response"
LDAP_DIALECT = ADLQ


# Builds one correlated Enumerate request and its MessageID.
def build_enumerate_request(server: str, port: int, query: SearchQuery) -> Tuple[str, str]:
    message_id = f"urn:uuid:{uuid.uuid4()}"
    endpoint = enumeration_endpoint(server, port)
    body = (
        f'<wsen:Enumerate><wsen:Filter Dialect="{LDAP_DIALECT}">'
        f'{_ldap_query(query)}</wsen:Filter>{_selection(query)}</wsen:Enumerate>'
    )
    return envelope(ENUMERATE_ACTION, message_id, endpoint, body), message_id


# Builds one correlated Pull request and its MessageID.
def build_pull_request(server: str, port: int, context: str, count: int) -> Tuple[str, str]:
    message_id = f"urn:uuid:{uuid.uuid4()}"
    endpoint = enumeration_endpoint(server, port)
    body = (
        f'<wsen:Pull><wsen:EnumerationContext>{html.escape(context)}'
        f'</wsen:EnumerationContext><wsen:MaxElements>{int(count)}'
        f'</wsen:MaxElements></wsen:Pull>'
    )
    return envelope(PULL_ACTION, message_id, endpoint, body), message_id


# Renders the LdapQuery the Enumerate filter carries.
def _ldap_query(query: SearchQuery) -> str:
    return (
        f'<adlq:LdapQuery><adlq:BaseObject>{html.escape(query.base)}</adlq:BaseObject>'
        f'<adlq:Scope>{html.escape(query.scope)}</adlq:Scope>'
        f'<adlq:Filter>{html.escape(query.ldap_filter)}</adlq:Filter></adlq:LdapQuery>'
    )


# Renders the attribute projection, which is absent when nothing was asked for.
#
# Absent rather than empty: the server reads an empty selection as "every
# attribute", and an element saying nothing is a slower way of saying that.
def _selection(query: SearchQuery) -> str:
    return "".join(
        f"<ad:SelectionProperty>{html.escape(name)}</ad:SelectionProperty>"
        for name in query.properties
    )
