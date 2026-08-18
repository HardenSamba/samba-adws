import logging
from abc import ABC, abstractmethod
from typing import Any, Optional

from classes.parsing.context import RequestContext
from classes.directory import SambaDB
from classes.faults.faults import FaultBuilder
from classes.serialization.object_projector import ObjectProjector
from classes.server.service_context import ServiceContext
from classes.soap.soap_envelope import SoapEnvelope
from classes.serialization.syntaxes import SyntaxRegistry
from classes.faults.typed_faults import TypedFaults
from classes.serialization.value_codec import ValueCodec
from classes.serialization.xml_renderer import AttributeRenderer


class BaseHandler(ABC):

    def __init__(self, logger: logging.Logger, session_info: Optional[Any] = None) -> None:
        self.logger = logger
        self.db = SambaDB(logger, session_info=session_info)
        self.syntaxes = SyntaxRegistry()
        self.codec = ValueCodec(self.syntaxes)
        self.renderer = AttributeRenderer(self.syntaxes, self.codec)
        self.serializer = ObjectProjector(self.renderer)
        self.envelope = SoapEnvelope
        self.faults = FaultBuilder
        self.typed_faults = TypedFaults
        self.service = ServiceContext.get(logger)

    @abstractmethod
    def handle(self, context: RequestContext) -> str:
        ...

    def log_request(self, context: RequestContext) -> None:
        ref = context.object_reference or "Root DSE"
        self.logger.info(f"[{self.__class__.__name__}] Processing: {ref}")

    def build_soap_fault(self, context: RequestContext, message: str) -> str:
        return str(SoapEnvelope.fault(context.message_id, "s:Receiver", message))
