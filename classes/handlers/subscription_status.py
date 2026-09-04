from datetime import datetime, timedelta

from src.enumeration.subscription_id import extract_identifier
from src.enumeration.subscription_registry import get_subscription_cache
from src.soap.namespaces import WSEV

from classes.handlers.base import BaseHandler
from classes.parsing.context import RequestContext


class SubscriptionStatusHandler(BaseHandler):

    REPLY_ACTION = f"{WSEV}/GetStatusResponse"

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        sub_id = extract_identifier(context.raw_xml)
        cache = get_subscription_cache()
        expires_at = cache.get_expires(sub_id) if sub_id else None
        if expires_at is None:
            expires_at = datetime.utcnow() + timedelta(seconds=3600)
        expires_iso = expires_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        body = (
            f'<wse:GetStatusResponse xmlns:wse="{WSEV}">'
            f'<wse:Expires>{expires_iso}</wse:Expires>'
            f'</wse:GetStatusResponse>'
        )
        return self.envelope.wrap(self.REPLY_ACTION, context.message_id, body)
