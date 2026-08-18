import logging
from typing import Any, Optional

from src.wcf.records import dump_records
from src.wcf.xml2records import XMLParser

from classes.parsing.context import RequestContext
from classes.faults.exceptions import ADWSException
from classes.handlers.handler_registry import HandlerRegistry
from classes.soap.soap_envelope import SoapEnvelope


class ADWSDispatcher:

    def __init__(self, logger: logging.Logger, session_info: Any = None) -> None:
        self.logger = logger
        self.session_info = session_info
        self.registry = HandlerRegistry(logger, session_info)

    def dispatch(self, record: Any, index: int) -> bytes:
        self.logger.info(f"[DISPATCH] message #{index}")
        context: Optional[RequestContext] = None
        try:
            xml_request = record.payload_to_xml()
            context = RequestContext.from_xml(xml_request)
            self.logger.info(
                f"[DISPATCH] action={context.action} message_id={context.message_id}"
            )
            response_xml = self._invoke(context)
            return self._encode_response(response_xml)
        except ADWSException as e:
            return self._encode_response(self._fault(context, e.message))
        except Exception as e:
            self.logger.exception("[DISPATCH] unexpected failure")
            return self._encode_response(self._fault(context, str(e)))

    def _invoke(self, context: RequestContext) -> str:
        handler = self.registry.resolve(context.action)
        if handler is None:
            keys = ", ".join(self.registry.keys())
            raise ADWSException(f"Unknown action: {context.action}. Known: {keys}")
        self.logger.info(f"[DISPATCH] handler={handler.__class__.__name__}")
        return handler.handle(context)

    @staticmethod
    def _encode_response(response_xml: str) -> bytes:
        records: Any = XMLParser.parse(response_xml)
        encoded: Any = dump_records(records)
        result: bytes = b"\x00" + encoded
        return result

    @staticmethod
    def _fault(context: Optional[RequestContext], message: str) -> str:
        relates_to = context.message_id if context else ""
        return SoapEnvelope.fault(relates_to, "s:Receiver", message)
