from typing import Any, Optional, Tuple, cast

import ldb
from src.soap.namespaces import CUSTOM_ACTIONS

from classes.handlers.base import BaseHandler
from classes.parsing.body_parser import BodyParser
from classes.parsing.context import RequestContext


class ChangePasswordHandler(BaseHandler):

    REPLY_ACTION = f"{CUSTOM_ACTIONS}/AccountManagement/ChangePasswordResponse"

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        try:
            dn, old_pwd, new_pwd = self._extract(context)
            if not dn or old_pwd is None or new_pwd is None:
                raise ValueError("Missing AccountDN, OldPassword or NewPassword")
            self._change(dn, old_pwd, new_pwd)
            self.logger.info(f"[ChangePassword] Password changed on {dn}")
            body = f'<ChangePasswordResponse xmlns="{CUSTOM_ACTIONS}"></ChangePasswordResponse>'
            return self.envelope.wrap(self.REPLY_ACTION, context.message_id, body)
        except Exception as e:
            self.logger.exception("[ChangePassword] failure")
            return cast(str, self.faults.custom_action_fault(
                context.message_id, "ChangePasswordFault", str(e)
            ))

    @staticmethod
    def _extract(
        context: RequestContext,
    ) -> Tuple[Optional[str], Optional[str], Optional[str]]:
        parser = BodyParser(context.raw_xml or "")
        body: Any = parser.find_custom_body("ChangePasswordRequest")
        if body is None:
            return None, None, None
        return (
            parser.text_of(body, "AccountDN"),
            parser.text_of(body, "OldPassword"),
            parser.text_of(body, "NewPassword"),
        )

    def _change(self, dn: str, old_pwd: str, new_pwd: str) -> None:
        old_encoded = ('"' + old_pwd + '"').encode("utf-16-le")
        new_encoded = ('"' + new_pwd + '"').encode("utf-16-le")
        msg = ldb.Message(ldb.Dn(self.db.db, dn))
        msg.add(ldb.MessageElement([old_encoded], ldb.FLAG_MOD_DELETE, "unicodePwd"))
        msg.add(ldb.MessageElement([new_encoded], ldb.FLAG_MOD_ADD, "unicodePwd"))
        self.db.db.modify(msg)
