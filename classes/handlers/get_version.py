from classes.parsing.context import RequestContext
from src.soap.namespaces import CUSTOM_ACTIONS
from classes.handlers.base import BaseHandler


class GetVersionHandler(BaseHandler):

    REPLY_ACTION = f"{CUSTOM_ACTIONS}/TopologyManagement/GetVersionResponse"
    SERVER_VERSION = "1.0.0"
    PROTOCOL_VERSION = "1.1"

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        body = (
            f'<ca:Version xmlns:ca="{CUSTOM_ACTIONS}">'
            f"<ca:Server>{self.SERVER_VERSION}</ca:Server>"
            f"<ca:Protocol>{self.PROTOCOL_VERSION}</ca:Protocol>"
            "</ca:Version>"
        )
        return self.envelope.wrap(self.REPLY_ACTION, context.message_id, body)
