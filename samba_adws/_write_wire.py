"""SOAP 1.2 envelope and addressing for the directory-changing operations."""

import html
import uuid
from typing import Tuple

from src.soap.namespaces import AD, ADDATA, DA, SOAP_ENV, WSA, XSD, XSI

RESOURCE_PATH = "/ActiveDirectoryWebServices/Windows/Resource"
FACTORY_PATH = "/ActiveDirectoryWebServices/Windows/ResourceFactory"
_NS = (
    f'xmlns:s="{SOAP_ENV}" xmlns:a="{WSA}" xmlns:ad="{AD}" '
    f'xmlns:addata="{ADDATA}" xmlns:da="{DA}" xmlns:xsi="{XSI}" xmlns:xsd="{XSD}"'
)


# Returns the net.tcp endpoint URI for the Resource or ResourceFactory service.
def endpoint(server: str, port: int, factory: bool = False) -> str:
    host = f"[{server}]" if ":" in server and not server.startswith("[") else server
    path = FACTORY_PATH if factory else RESOURCE_PATH
    return f"net.tcp://{host}:{port}{path}"


# Renders the WS-Addressing and ADWS routing headers for one write request.
def _headers(action: str, target: str, reference: str,
             message_id: str, imda: bool) -> str:
    imda_header = '<da:IdentityManagementOperation s:mustUnderstand="1"/>' if imda else ""
    return (
        f'<a:Action s:mustUnderstand="1">{action}</a:Action>'
        f'<a:MessageID>{message_id}</a:MessageID>'
        f'<a:ReplyTo><a:Address>{WSA}/anonymous</a:Address></a:ReplyTo>'
        f'<a:To s:mustUnderstand="1">{html.escape(target)}</a:To>{imda_header}'
        f'<ad:instance>ldap:389</ad:instance>'
        f'<ad:objectReferenceProperty>{html.escape(reference)}</ad:objectReferenceProperty>'
    )


# Builds one correlated SOAP 1.2 write request and returns it with its MessageID.
def build_envelope(action: str, target: str, reference: str,
                   body: str, imda: bool) -> Tuple[str, str]:
    message_id = f"urn:uuid:{uuid.uuid4()}"
    headers = _headers(action, target, reference, message_id, imda)
    envelope = (
        f'<s:Envelope {_NS}><s:Header>{headers}</s:Header>'
        f'<s:Body>{body}</s:Body></s:Envelope>'
    )
    return envelope, message_id
