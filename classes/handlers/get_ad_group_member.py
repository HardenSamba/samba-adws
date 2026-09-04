from typing import Any, List, Optional, Set, cast

import ldb
from src.soap.namespaces import CUSTOM_ACTIONS

from classes.directory.principal_loader import PrincipalLoader
from classes.handlers.base import BaseHandler
from classes.parsing.body_parser import BodyParser
from classes.parsing.context import RequestContext
from classes.serialization.group_serializer import PrincipalSerializer


class GetADGroupMemberHandler(BaseHandler):

    REPLY_ACTION = f"{CUSTOM_ACTIONS}/AccountManagement/GetADGroupMemberResponse"

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        try:
            group_dn, recursive = self._extract(context)
            members = self._load_members(group_dn, recursive)
            principals: Any = PrincipalLoader(self.db.db).load_many(members)
            body = self._build_body(principals)
            return self.envelope.wrap(self.REPLY_ACTION, context.message_id, body)
        except Exception as e:
            self.logger.exception("[GetADGroupMember] failure")
            return cast(str, self.faults.custom_action_fault(
                context.message_id, "GetADGroupMemberFault", str(e)
            ))

    def _extract(self, context: RequestContext) -> Any:
        parser = BodyParser(context.raw_xml or "")
        body: Any = parser.find_custom_body("GetADGroupMemberRequest") if context.raw_xml else None
        group_dn: Any = parser.text_of(body, "GroupDN") if body is not None else None
        recursive_text: Any = parser.text_of(body, "Recursive") if body is not None else None
        return group_dn or context.object_reference, (recursive_text == "true")

    def _load_members(self, group_dn: Optional[str], recursive: bool) -> List[str]:
        if not group_dn:
            return []
        seen: Set[str] = set()
        return self._walk(group_dn, recursive, seen)

    def _walk(self, dn: str, recursive: bool, seen: Set[str]) -> List[str]:
        if dn in seen:
            return []
        seen.add(dn)
        try:
            results: Any = self.db.db.search(base=dn, scope=ldb.SCOPE_BASE,
                                              expression="(objectClass=*)", attrs=["member"])
        except ldb.LdbError:
            return []
        members: List[str] = []
        for msg in results:
            for raw in msg.get("member", []):
                value = raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)
                members.append(value)
                if recursive:
                    members.extend(self._walk(value, True, seen))
        return members

    def _build_body(self, principals: Any) -> Any:
        return PrincipalSerializer.members_response(principals)
