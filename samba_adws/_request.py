"""SOAP request construction for the supported Get-by-DN operation."""

import html
import uuid
from types import MappingProxyType
from typing import Mapping, Sequence, Tuple

from src.soap.namespaces import AD, ADDATA, DA, SOAP_ENV, WSA, XSD, XSI

GET_ACTION = "http://schemas.xmlsoap.org/ws/2004/09/transfer/Get"
GET_RESPONSE_ACTION = f"{GET_ACTION}Response"
RESOURCE_PATH = "/ActiveDirectoryWebServices/Windows/Resource"
XPATH_DIALECT = "http://schemas.microsoft.com/2008/1/ActiveDirectory/Dialect/XPath-Level-1"
_AD_PROPERTIES: Mapping[str, str] = MappingProxyType({
    "container-hierarchy-parent": "container-hierarchy-parent",
    "distinguishedname": "distinguishedName",
    "objectreferenceproperty": "objectReferenceProperty",
    "relativedistinguishedname": "relativeDistinguishedName",
})


# Returns the canonical Resource endpoint URI for one server.
def endpoint_for(server: str, port: int) -> str:
    host = f"[{server}]" if ":" in server and not server.startswith("[") else server
    return f"net.tcp://{host}:{port}{RESOURCE_PATH}"


# Builds one correlated SOAP 1.2 Get request and its MessageID.
def build_get_request(
    server: str, port: int, identity: str, properties: Sequence[str]
) -> Tuple[str, str]:
    message_id = f"urn:uuid:{uuid.uuid4()}"
    endpoint = endpoint_for(server, port)
    namespace_xml = (
        f'xmlns:s="{SOAP_ENV}" xmlns:a="{WSA}" xmlns:ad="{AD}" '
        f'xmlns:addata="{ADDATA}" xmlns:da="{DA}" xmlns:xsi="{XSI}" xmlns:xsd="{XSD}"'
    )
    envelope = (
        f'<s:Envelope {namespace_xml}><s:Header>'
        f'{_headers(message_id, endpoint, identity, bool(properties))}'
        f'</s:Header><s:Body>{_request_body(properties)}</s:Body></s:Envelope>'
    )
    return envelope, message_id


# Renders WS-Addressing, endpoint, and IMDA request headers.
def _headers(message_id: str, endpoint: str, identity: str, is_imda: bool) -> str:
    imda = '<da:IdentityManagementOperation s:mustUnderstand="1"/>' if is_imda else ""
    return (
        f'<a:Action s:mustUnderstand="1">{GET_ACTION}</a:Action>'
        f'<a:MessageID>{message_id}</a:MessageID><a:ReplyTo>'
        f'<a:Address>{WSA}/anonymous</a:Address></a:ReplyTo>'
        f'<a:To s:mustUnderstand="1">{html.escape(endpoint)}</a:To>{imda}'
        f'<ad:instance>ldap:389</ad:instance><ad:objectReferenceProperty>'
        f'{html.escape(identity)}</ad:objectReferenceProperty>'
    )


# Renders an optional IMDA property projection for the Get body.
def _request_body(properties: Sequence[str]) -> str:
    if not properties:
        return ""
    attributes = "".join(
        f"<da:AttributeType>{_qualified_property(name)}</da:AttributeType>"
        for name in properties
    )
    return (
        f'<da:BaseObjectSearchRequest Dialect="{XPATH_DIALECT}">'
        f'{attributes}</da:BaseObjectSearchRequest>'
    )


# Selects the AD or AD data QName used by an AttributeType.
def _qualified_property(name: str) -> str:
    synthetic = _AD_PROPERTIES.get(name.lower())
    if synthetic is not None:
        return f"ad:{synthetic}"
    return f"addata:{html.escape(name)}"
