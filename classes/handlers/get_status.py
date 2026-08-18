from classes.parsing.context import RequestContext
from src.enumeration.enumeration import get_enumeration_registry
from src.soap.namespaces import WSEN
from classes.handlers.base import BaseHandler


class GetStatusHandler(BaseHandler):

    REPLY_ACTION = f"{WSEN}/GetStatusResponse"

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        ctx_id = context.enumeration_context
        if not ctx_id:
            return str(
                self.faults.invalid_enumeration_context(context.message_id, "(missing)")
            )
        cache = get_enumeration_registry(self.logger)
        ctx = cache.get_context(ctx_id)
        if ctx is None:
            return str(
                self.faults.invalid_enumeration_context(context.message_id, ctx_id)
            )
        expires = ctx.expires_at.isoformat() + "Z"
        body = (
            f"<wsen:GetStatusResponse>"
            f"<wsen:Expires>{expires}</wsen:Expires>"
            f"</wsen:GetStatusResponse>"
        )
        return str(self.envelope.wrap(self.REPLY_ACTION, context.message_id, body))
