from datetime import datetime, timedelta

from classes.parsing.context import RequestContext
from src.soap.namespaces import WSEV
from src.enumeration.subscription_id import extract_identifier, parse_expires
from src.enumeration.subscription_registry import get_subscription_cache
from classes.handlers.base import BaseHandler


class SubscriptionRenewHandler(BaseHandler):

    REPLY_ACTION = f"{WSEV}/RenewResponse"

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        sub_id = extract_identifier(context.raw_xml)
        ttl = parse_expires(context.raw_xml)
        cache = get_subscription_cache()
        expires_at = cache.renew(sub_id, ttl) if sub_id else None
        if expires_at is None:
            expires_at = datetime.utcnow() + timedelta(seconds=ttl)
        expires_iso = expires_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        body = (
            f'<wse:RenewResponse xmlns:wse="{WSEV}">'
            f'<wse:Expires>{expires_iso}</wse:Expires>'
            f'</wse:RenewResponse>'
        )
        return self.envelope.wrap(self.REPLY_ACTION, context.message_id, body)
