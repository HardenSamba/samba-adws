import logging
from typing import Any, Optional

from src.wcf.records import dump_records
from src.wcf.xml2records import XMLParser

from classes.faults.exceptions import ADWSException, ADWSUnrelatableRequestException
from classes.handlers.handler_registry import HandlerRegistry
from classes.parsing import message_id
from classes.parsing.context import RequestContext
from classes.soap.soap_envelope import SoapEnvelope


# Routes one decoded message to the handler that owns its action, and turns
# anything that goes wrong into a SOAP fault the client can relate to the
# request it sent.
class ADWSDispatcher:

    # Holds the logger, the caller's authenticated session and the registry of
    # handlers for the length of one connection.
    def __init__(self, logger: logging.Logger, session_info: Any = None,
                 peer: str = "") -> None:
        self.logger = logger
        self.session_info = session_info
        self.peer = peer
        self.registry = HandlerRegistry(logger, session_info)

    # Decodes one message, invokes the handler for its action and returns the
    # encoded response, or a fault. The decoded text is kept so that a request
    # which never parsed can still be answered with its own MessageID.
    def dispatch(self, record: Any, index: int) -> bytes:
        self.logger.info(f"[DISPATCH] message #{index}")
        context: Optional[RequestContext] = None
        request: Optional[str] = None
        try:
            request = record.payload_to_xml()
            context = RequestContext.from_xml(request or "")
            self.logger.info(
                f"[DISPATCH] action={context.action} message_id={context.message_id}"
            )
            response_xml = self._invoke(context)
            return self._encode_response(response_xml)
        except ADWSException as e:
            return self._encode_response(self._fault(context, e.message, request))
        except Exception as e:
            self.logger.exception("[DISPATCH] unexpected failure")
            return self._encode_response(self._fault(context, str(e), request))

    # Resolves the action to its handler and returns what that handler
    # rendered, or raises when no handler claims the action.
    def _invoke(self, context: RequestContext) -> str:
        handler = self.registry.resolve(context.action)
        if handler is None:
            keys = ", ".join(self.registry.keys())
            raise ADWSException(f"Unknown action: {context.action}. Known: {keys}")
        self.logger.info(f"[DISPATCH] handler={handler.__class__.__name__}")
        return handler.handle(context)

    # Encodes one response as WCF binary XML behind the leading record byte
    # the framing expects.
    @staticmethod
    def _encode_response(response_xml: str) -> bytes:
        records: Any = XMLParser.parse(response_xml)
        encoded: Any = dump_records(records)
        result: bytes = b"\x00" + encoded
        return result

    # Builds the fault, relating it to the request it answers. A request that
    # never parsed still yields its MessageID; one that yields nothing cannot
    # be answered at all, so the caller is told to close instead.
    def _fault(self, context: Optional[RequestContext], message: str,
               request: Optional[str] = None) -> str:
        if context is not None:
            return SoapEnvelope.fault(context.message_id, "s:Receiver", message)
        relates_to = message_id.extract(request)
        if not relates_to:
            self.logger.warning(
                f"[DISPATCH] {self.peer} sent a request with no recoverable MessageID; "
                f"closing rather than sending a fault the client would discard")
            raise ADWSUnrelatableRequestException(message)
        self.logger.warning(
            f"[DISPATCH] {self.peer} sent a request that did not parse; "
            f"faulting with the MessageID recovered from its text")
        return SoapEnvelope.fault(relates_to, "s:Receiver", message)
