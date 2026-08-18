from typing import Any, Optional

from classes.parsing.context import RequestContext
from classes.handlers.base import BaseHandler
from classes.handlers.delete import DeleteHandler
from classes.handlers.modify import ModifyHandler


class TransferHandler(BaseHandler):

    def __init__(self, logger: Any, session_info: Optional[Any] = None) -> None:
        super().__init__(logger, session_info)
        self._modify = ModifyHandler(logger, session_info)
        self._delete = DeleteHandler(logger, session_info)

    def handle(self, context: RequestContext) -> str:
        action = (context.action or "").lower()
        if action.endswith("/put"):
            return self._modify.handle(context)
        if action.endswith("/delete"):
            return self._delete.handle(context)
        return str(self.faults.directory_error(
            context.message_id,
            f"Unsupported transfer action: {context.action}",
            "ActionNotSupported",
        ))
