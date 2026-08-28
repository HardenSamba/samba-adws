"""Addressing and envelope shape for the supported search operations.

**The endpoint is `Windows/Enumeration`, not `Windows/Resource`.** That is what
the published WCF endpoint table gives for the `IEnumeration` contract, and what
a Microsoft server requires. This repository's server does no demultiplexing by
endpoint — it routes on the SOAP action and answers whatever URI it is addressed
with — so the distinction costs nothing here and is the difference between
working and not working against a real one.
"""

import html

from samba_adws._request import RESOURCE_PATH, endpoint_for
from src.soap.namespaces import AD, ADDATA, ADLQ, SOAP_ENV, WSA, WSEN, XSD, XSI

ENUMERATION_PATH = "/ActiveDirectoryWebServices/Windows/Enumeration"

NAMESPACES = (
    f'xmlns:s="{SOAP_ENV}" xmlns:a="{WSA}" xmlns:wsen="{WSEN}" xmlns:ad="{AD}" '
    f'xmlns:adlq="{ADLQ}" xmlns:addata="{ADDATA}" xmlns:xsi="{XSI}" xmlns:xsd="{XSD}"'
)


# Returns the Enumeration endpoint URI for one server.
def enumeration_endpoint(server: str, port: int) -> str:
    return endpoint_for(server, port).replace(RESOURCE_PATH, ENUMERATION_PATH)


# Wraps one body in an addressed SOAP 1.2 envelope.
def envelope(action: str, message_id: str, endpoint: str, body: str) -> str:
    headers = (
        f'<a:Action s:mustUnderstand="1">{action}</a:Action>'
        f'<a:MessageID>{message_id}</a:MessageID><a:ReplyTo>'
        f'<a:Address>{WSA}/anonymous</a:Address></a:ReplyTo>'
        f'<a:To s:mustUnderstand="1">{html.escape(endpoint)}</a:To>'
        f'<ad:instance>ldap:389</ad:instance>'
    )
    return (
        f'<s:Envelope {NAMESPACES}><s:Header>{headers}</s:Header>'
        f'<s:Body>{body}</s:Body></s:Envelope>'
    )
