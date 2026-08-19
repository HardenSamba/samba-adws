"""Typed failures raised by the public ADWS client."""

from typing import Optional


# Maps a stable error code and message to a PowerShell-friendly category.
def _error_category(code: str, message: str) -> str:
    if "not found" in message.lower():
        return "ObjectNotFound"
    categories = {
        "InvalidArgument": "InvalidArgument",
        "TransportError": "ResourceUnavailable",
        "CorrelationError": "ProtocolError",
        "MalformedResponse": "ProtocolError",
        "EncodingError": "ProtocolError",
    }
    return categories.get(code, "NotSpecified")


# Carries a stable code, category, and optional operation target.
class ADWSClientError(RuntimeError):
    message: str
    code: str
    category: str
    target: Optional[str]

    # Stores structured failure metadata while preserving a useful string.
    def __init__(
        self, message: str, code: str = "ClientError", target: Optional[str] = None
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.category = _error_category(code, message)
        self.target = target
