from src.enumeration.subscription_id import extract_identifier
from src.enumeration.subscription_registry import get_subscription_cache
from src.soap.namespaces import WSEV

from classes.handlers.base import BaseHandler
from classes.parsing.context import RequestContext


class UnsubscribeHandler(BaseHandler):

    REPLY_ACTION = f"{WSEV}/UnsubscribeResponse"

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        sub_id = extract_identifier(context.raw_xml)
        if sub_id:
            cache = get_subscription_cache()
            removed = cache.remove(sub_id)
            self.logger.info(f"[UNSUBSCRIBE] {sub_id} removed={removed}")
        body = f'<wse:UnsubscribeResponse xmlns:wse="{WSEV}"/>'
        return self.envelope.wrap(self.REPLY_ACTION, context.message_id, body)
