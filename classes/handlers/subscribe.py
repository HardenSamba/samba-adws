import html
from datetime import datetime
from typing import cast

from src.enumeration.subscription_id import parse_expires
from src.enumeration.subscription_registry import get_subscription_cache
from src.soap.namespaces import WSEV

from classes.handlers.base import BaseHandler
from classes.parsing.context import RequestContext


class SubscribeHandler(BaseHandler):

    REPLY_ACTION = f"{WSEV}/SubscribeResponse"
    SUB_MANAGER_ADDRESS = (
        "net.tcp://localhost:9389/ActiveDirectoryWebServices/Windows/AccountManagement"
    )

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        try:
            ttl = parse_expires(context.raw_xml)
            cache = get_subscription_cache()
            sub_id, expires_at = cache.create(ttl)
            self.logger.info(f"[SUBSCRIBE] Created subscription {sub_id} (TTL {ttl}s)")
            body = self._build_body(sub_id, expires_at)
            return self.envelope.wrap(self.REPLY_ACTION, context.message_id, body)
        except Exception as e:
            self.logger.exception("[SUBSCRIBE] failure")
            return cast(str, self.faults.directory_error(
                context.message_id, str(e), "SubscribeFault"
            ))

    def _build_body(self, sub_id: str, expires_at: datetime) -> str:
        expires_iso = expires_at.strftime("%Y-%m-%dT%H:%M:%S.000Z")
        return (
            f'<wse:SubscribeResponse xmlns:wse="{WSEV}">'
            f'<wse:SubscriptionManager>'
            f'<a:Address>{html.escape(self.SUB_MANAGER_ADDRESS)}</a:Address>'
            f'<a:ReferenceParameters>'
            f'<wse:Identifier>uuid:{sub_id}</wse:Identifier>'
            f'</a:ReferenceParameters>'
            f'</wse:SubscriptionManager>'
            f'<wse:Expires>{expires_iso}</wse:Expires>'
            f'</wse:SubscribeResponse>'
        )
