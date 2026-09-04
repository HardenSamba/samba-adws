import html
from typing import Any

from src.soap.namespaces import CUSTOM_ACTIONS, FAULT_NS, XSI

from classes.soap.soap_envelope import SoapEnvelope


class FaultBuilder:

    SENDER = "s:Sender"
    RECEIVER = "s:Receiver"

    @classmethod
    def directory_error(cls, relates_to: str, message: str, short_error: str = "") -> Any:
        da_ns = "http://schemas.microsoft.com/2006/11/IdentityManagement/DirectoryAccess"
        detail = (
            f'<da:Fault xmlns:da="{da_ns}">'
            f'<da:ShortError>{html.escape(short_error or message)}</da:ShortError>'
            f'<da:LongError>{html.escape(message)}</da:LongError>'
            f'</da:Fault>'
        )
        return SoapEnvelope.fault(relates_to, cls.RECEIVER, message, detail)

    @classmethod
    def access_denied(cls, relates_to: str, message: str = "Access denied") -> Any:
        return SoapEnvelope.fault(relates_to, cls.SENDER, message)

    @classmethod
    def custom_action_fault(cls, relates_to: str, fault_name: str, message: str) -> Any:
        detail = (
            f'<{fault_name} xmlns="{CUSTOM_ACTIONS}" xmlns:xsi="{XSI}">'
            f'<ArgumentError xsi:nil="true"></ArgumentError>'
            f'<DirectoryError xsi:nil="true"></DirectoryError>'
            f'<Error>{html.escape(message)}</Error>'
            f'<ShortError>{html.escape(message)}</ShortError>'
            f'</{fault_name}>'
        )
        return SoapEnvelope.fault(
            relates_to, cls.RECEIVER, message, detail,
            subcode=f"ca:{fault_name}", action=FAULT_NS,
        )

    @classmethod
    def invalid_enumeration_context(cls, relates_to: str, context_id: str) -> Any:
        return SoapEnvelope.fault(
            relates_to, cls.SENDER,
            f"Invalid or expired enumeration context: {context_id}",
        )
