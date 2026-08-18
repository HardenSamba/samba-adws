from typing import Any, Optional, Tuple, cast

import ldb

from classes.parsing.body_parser import BodyParser
from classes.parsing.context import RequestContext
from src.soap.namespaces import CUSTOM_ACTIONS
from classes.handlers.base import BaseHandler


class SetPasswordHandler(BaseHandler):

    REPLY_ACTION = f"{CUSTOM_ACTIONS}/AccountManagement/SetPasswordResponse"

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        try:
            account_dn, new_password = self._extract(context)
            if not account_dn or new_password is None:
                raise ValueError("Missing AccountDN or NewPassword")
            self._reset_password(account_dn, new_password)
            self.logger.info(f"[SetPassword] Password reset on {account_dn}")
            body = f'<SetPasswordResponse xmlns="{CUSTOM_ACTIONS}"></SetPasswordResponse>'
            return self.envelope.wrap(self.REPLY_ACTION, context.message_id, body)
        except Exception as e:
            self.logger.exception("[SetPassword] failure")
            return cast(str, self.faults.custom_action_fault(
                context.message_id, "SetPasswordFault", str(e)
            ))

    @staticmethod
    def _extract(context: RequestContext) -> Tuple[Optional[str], Optional[str]]:
        parser = BodyParser(context.raw_xml or "")
        body: Any = parser.find_custom_body("SetPasswordRequest")
        if body is None:
            return None, None
        return parser.text_of(body, "AccountDN"), parser.text_of(body, "NewPassword")

    def _reset_password(self, dn: str, new_password: str) -> None:
        encoded = ('"' + new_password + '"').encode("utf-16-le")
        msg = ldb.Message(ldb.Dn(self.db.db, dn))
        msg["unicodePwd"] = ldb.MessageElement([encoded], ldb.FLAG_MOD_REPLACE, "unicodePwd")
        self.db.db.modify(msg)
