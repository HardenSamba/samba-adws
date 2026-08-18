from typing import Any, Optional

from classes.parsing.context import RequestContext
from classes.parsing.filter_parser import FilterParser
from classes.handlers.base import BaseHandler
from classes.handlers.enumerate import EnumerateHandler


class SearchHandler(BaseHandler):

    def __init__(self, logger: Any, session_info: Optional[Any] = None) -> None:
        super().__init__(logger, session_info)
        self._enumerate = EnumerateHandler(logger, session_info)
        self._filters = FilterParser()

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        if context.ldap_filter:
            try:
                context.ldap_filter = self._filters.parse(context.ldap_filter)
            except ValueError as e:
                return str(self.faults.directory_error(
                    context.message_id, str(e), "CannotProcessFilter"
                ))
        return self._enumerate.handle(context)
