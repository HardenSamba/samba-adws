import html
from typing import Any

from src.faults.fault_codes import (
    DA_FAULT_NS,
    WSADDR_FAULT_NS,
    WSEN_FAULT_NS,
    WSMAN_FAULT_NS,
    WST_FAULT_NS,
)
from classes.soap.soap_envelope import SoapEnvelope


class TypedFaults:

    @classmethod
    def wsman(cls, relates_to: str, name: str, message: str) -> Any:
        detail = (
            f'<wsman:FaultDetail xmlns:wsman="{WSMAN_FAULT_NS}">'
            f'<wsman:Code>{html.escape(name)}</wsman:Code>'
            f'<wsman:Message>{html.escape(message)}</wsman:Message>'
            f'</wsman:FaultDetail>'
        )
        return SoapEnvelope.fault(relates_to, "s:Sender", message, detail)

    @classmethod
    def wsaddressing(cls, relates_to: str, name: str, message: str) -> Any:
        detail = (
            f'<wsa:FaultDetail xmlns:wsa="{WSADDR_FAULT_NS}">'
            f'<wsa:Code>{html.escape(name)}</wsa:Code>'
            f'<wsa:Message>{html.escape(message)}</wsa:Message>'
            f'</wsa:FaultDetail>'
        )
        return SoapEnvelope.fault(relates_to, "s:Sender", message, detail)

    @classmethod
    def directory(cls, relates_to: str, name: str, message: str) -> Any:
        detail = (
            f'<da:Fault xmlns:da="{DA_FAULT_NS}">'
            f'<da:Code>{html.escape(name)}</da:Code>'
            f'<da:Message>{html.escape(message)}</da:Message>'
            f'</da:Fault>'
        )
        return SoapEnvelope.fault(relates_to, "s:Receiver", message, detail)

    @classmethod
    def transfer(cls, relates_to: str, name: str, message: str) -> Any:
        detail = (
            f'<wst:Fault xmlns:wst="{WST_FAULT_NS}">'
            f'<wst:Code>{html.escape(name)}</wst:Code>'
            f'<wst:Message>{html.escape(message)}</wst:Message>'
            f'</wst:Fault>'
        )
        return SoapEnvelope.fault(relates_to, "s:Sender", message, detail)

    @classmethod
    def enumeration(cls, relates_to: str, name: str, message: str) -> Any:
        detail = (
            f'<wsen:Fault xmlns:wsen="{WSEN_FAULT_NS}">'
            f'<wsen:Code>{html.escape(name)}</wsen:Code>'
            f'<wsen:Message>{html.escape(message)}</wsen:Message>'
            f'</wsen:Fault>'
        )
        return SoapEnvelope.fault(relates_to, "s:Sender", message, detail)
