"""Release handler - Close enumeration context and free resources"""
import html

from src.enumeration.enumeration import get_enumeration_registry

from classes.handlers.base import BaseHandler
from classes.parsing.context import RequestContext


# Handles WS-Enumeration Release: drops the cached results of an enumeration
# context, or faults when the request names none.
class ReleaseHandler(BaseHandler):
    """Handles WS-Enumeration Release requests

    Closes enumeration context and removes cached results.
    """

    # Releases the named context and answers with an empty body, or with the
    # same invalid-context fault its siblings return when no context is named.
    # A context the registry no longer holds is already released, so that stays
    # a success: the client asked for a state that is the state it is in.
    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        enum_context_id = context.enumeration_context
        if not enum_context_id:
            return str(
                self.faults.invalid_enumeration_context(context.message_id, "(missing)")
            )
        self.logger.info(f"[RELEASE] Context ID: {enum_context_id}")
        get_enumeration_registry(self.logger).release_context(enum_context_id)
        self.logger.info("[RELEASE] Context deleted successfully")
        return self._build_release_response(context)

    # Renders the bodyless ReleaseResponse, related to the request it answers.
    def _build_release_response(self, context: RequestContext) -> str:
        response_xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
            'xmlns:a="http://www.w3.org/2005/08/addressing">'
            '<s:Header>'
            '<a:Action s:mustUnderstand="1">'
            'http://schemas.xmlsoap.org/ws/2004/09/enumeration/ReleaseResponse'
            '</a:Action>'
            f'<a:RelatesTo>{html.escape(context.message_id)}</a:RelatesTo>'
            '</s:Header>'
            '<s:Body />'
            '</s:Envelope>'
        )

        return response_xml
