import xml.etree.ElementTree as ET
from typing import Any, Optional, Tuple

import ldb

from classes.parsing.body_parser import BodyParser
from classes.parsing.context import RequestContext
from src.soap.namespaces import CUSTOM_ACTIONS
from classes.handlers.base import BaseHandler
from classes.handlers.get_ad_group_member import GetADGroupMemberHandler


class GroupHandler(BaseHandler):

    def __init__(self, logger: Any, session_info: Optional[Any] = None) -> None:
        super().__init__(logger, session_info)
        self._members = GetADGroupMemberHandler(logger, session_info)

    def handle(self, context: RequestContext) -> str:
        action = (context.action or "").lower()
        if "add" in action:
            return self._modify_member(context, ldb.FLAG_MOD_ADD, "AddedMember")
        if "remove" in action:
            return self._modify_member(context, ldb.FLAG_MOD_DELETE, "RemovedMember")
        return self._members.handle(context)

    def _modify_member(self, context: RequestContext, flag: int, label: str) -> str:
        try:
            group_dn, member_dn = self._extract(context)
            if not group_dn or not member_dn:
                raise ValueError("Missing GroupDN or MemberDN")
            msg = ldb.Message(ldb.Dn(self.db.db, group_dn))
            msg["member"] = ldb.MessageElement([member_dn.encode("utf-8")], flag, "member")
            self.db.db.modify(msg)
            self.logger.info(f"[GROUPS] {label} {member_dn} on {group_dn}")
            body = f'<ca:{label}>{member_dn}</ca:{label}>'
            action_uri = f"{CUSTOM_ACTIONS}/AccountManagement/{label}Response"
            return str(self.envelope.wrap(action_uri, context.message_id, body))
        except Exception as e:
            self.logger.exception(f"[GROUPS] {label} failure")
            return str(self.faults.custom_action_fault(context.message_id, f"{label}Fault", str(e)))

    @staticmethod
    def _extract(context: RequestContext) -> Tuple[Optional[str], Optional[str]]:
        parser = BodyParser(context.raw_xml or "")
        body: Optional[ET.Element] = parser.find_custom_body("GroupModificationRequest")
        if body is None:
            return context.object_reference, None
        return (
            parser.text_of(body, "GroupDN") or context.object_reference,
            parser.text_of(body, "MemberDN"),
        )
