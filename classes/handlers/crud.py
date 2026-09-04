from typing import Any, Optional

from classes.handlers.base import BaseHandler
from classes.handlers.create import CreateHandler
from classes.handlers.delete import DeleteHandler
from classes.handlers.modify import ModifyHandler
from classes.parsing.context import RequestContext


class CRUDHandler(BaseHandler):

    def __init__(self, logger: Any, session_info: Optional[Any] = None) -> None:
        super().__init__(logger, session_info)
        self._create = CreateHandler(logger, session_info)
        self._modify = ModifyHandler(logger, session_info)
        self._delete = DeleteHandler(logger, session_info)

    def handle(self, context: RequestContext) -> str:
        action = (context.action or "").lower()
        if action.endswith("/create"):
            return self._create.handle(context)
        if action.endswith("/put"):
            return self._modify.handle(context)
        if action.endswith("/delete"):
            return self._delete.handle(context)
        return str(self.faults.directory_error(
            context.message_id,
            f"Unsupported CRUD action: {context.action}",
            "ActionNotSupported",
        ))
