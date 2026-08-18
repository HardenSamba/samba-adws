import html
import re

from src.soap.namespaces import (
    AD,
    ADDATA,
    ADLQ,
    CUSTOM_ACTIONS,
    DA,
    SOAP_ENV,
    WSA,
    WSEN,
    WST,
    XSD,
    XSI,
)

_DEFAULT_FAULT_ACTION = "http://www.w3.org/2005/08/addressing/soap/fault"


class SoapEnvelope:

    NS_DECL = (
        f'xmlns:s="{SOAP_ENV}" xmlns:a="{WSA}" '
        f'xmlns:wsen="{WSEN}" xmlns:wst="{WST}" '
        f'xmlns:ad="{AD}" xmlns:addata="{ADDATA}" '
        f'xmlns:da="{DA}" xmlns:adlq="{ADLQ}" '
        f'xmlns:ca="{CUSTOM_ACTIONS}" '
        f'xmlns:xsi="{XSI}" xmlns:xsd="{XSD}"'
    )

    @classmethod
    def wrap(cls, action: str, relates_to: str, body_xml: str) -> str:
        envelope = (
            '<?xml version="1.0" encoding="utf-8"?>'
            f'<s:Envelope {cls.NS_DECL}>'
            '<s:Header>'
            f'<a:Action s:mustUnderstand="1">{html.escape(action)}</a:Action>'
            f'<a:RelatesTo>{html.escape(relates_to or "")}</a:RelatesTo>'
            '</s:Header>'
            f'<s:Body>{body_xml}</s:Body>'
            '</s:Envelope>'
        )
        return cls._minify(envelope)

    @classmethod
    def fault(
        cls, relates_to: str, code_value: str, reason: str,
        detail_xml: str = "", subcode: str = "", action: str = _DEFAULT_FAULT_ACTION,
    ) -> str:
        body = (
            '<s:Fault>'
            f'{cls._code(code_value, subcode)}'
            f'<s:Reason><s:Text xml:lang="en-US">{html.escape(reason)}</s:Text></s:Reason>'
        )
        if detail_xml:
            body += f'<s:Detail>{detail_xml}</s:Detail>'
        body += '</s:Fault>'
        return cls.wrap(action, relates_to, body)

    @staticmethod
    def _code(code_value: str, subcode: str) -> str:
        inner = f'<s:Value>{html.escape(code_value)}</s:Value>'
        if subcode:
            inner += f'<s:Subcode><s:Value>{html.escape(subcode)}</s:Value></s:Subcode>'
        return f'<s:Code>{inner}</s:Code>'

    @staticmethod
    def _minify(xml_string: str) -> str:
        return re.sub(r">\s+<", "><", xml_string)
