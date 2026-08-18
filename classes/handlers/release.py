"""Release handler - Close enumeration context and free resources"""
import html

from classes.parsing.context import RequestContext
from src.enumeration.enumeration import get_enumeration_registry
from classes.faults.exceptions import ADWSException
from classes.handlers.base import BaseHandler


class ReleaseHandler(BaseHandler):
    """Handles WS-Enumeration Release requests

    Closes enumeration context and removes cached results.
    """

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)

        try:
            enum_context_id = context.enumeration_context

            if not enum_context_id:
                raise ADWSException("EnumerationContext not provided in Release request")

            self.logger.info(f"[RELEASE] Context ID: {enum_context_id}")

            enum_registry = get_enumeration_registry(self.logger)
            enum_registry.release_context(enum_context_id)

            self.logger.info("[RELEASE] Context deleted successfully")

            response_xml = self._build_release_response(context)

            return response_xml

        except ADWSException:
            raise
        except Exception as e:
            self.logger.error(f"[RELEASE] Error: {str(e)}")
            raise ADWSException(f"Release failed: {str(e)}") from e

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
