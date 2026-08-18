from classes.parsing.context import RequestContext
from src.soap.namespaces import CUSTOM_ACTIONS
from classes.handlers.base import BaseHandler


class NotifyHandler(BaseHandler):

    REPLY_ACTION = f"{CUSTOM_ACTIONS}/AccountManagement/NotifyResponse"

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        body = (
            f'<ca:NotifyResponse xmlns:ca="{CUSTOM_ACTIONS}">'
            f'<ca:Events/>'
            f'</ca:NotifyResponse>'
        )
        return self.envelope.wrap(self.REPLY_ACTION, context.message_id, body)
