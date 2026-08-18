from datetime import datetime, timedelta

from classes.parsing.context import RequestContext
from src.enumeration.enumeration import get_enumeration_registry
from src.soap.namespaces import WSEN
from classes.handlers.base import BaseHandler


class RenewHandler(BaseHandler):

    REPLY_ACTION = f"{WSEN}/RenewResponse"

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        ctx_id = context.enumeration_context
        if not ctx_id:
            return str(self.faults.invalid_enumeration_context(context.message_id, "(missing)"))
        cache = get_enumeration_registry(self.logger)
        if not cache.renew_context(ctx_id, ttl_seconds=3600):
            return str(self.faults.invalid_enumeration_context(context.message_id, ctx_id))
        expires = (datetime.utcnow() + timedelta(seconds=3600)).isoformat() + "Z"
        body = (
            "<wsen:RenewResponse>"
            f"<wsen:Expires>{expires}</wsen:Expires>"
            f"<wsen:EnumerationContext>{ctx_id}</wsen:EnumerationContext>"
            "</wsen:RenewResponse>"
        )
        return str(self.envelope.wrap(self.REPLY_ACTION, context.message_id, body))
