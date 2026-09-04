from typing import Any, Optional, Set, cast

import ldb
from src.soap.namespaces import CUSTOM_ACTIONS

from classes.directory.principal_loader import PrincipalLoader
from classes.handlers.base import BaseHandler
from classes.parsing.body_parser import BodyParser
from classes.parsing.context import RequestContext
from classes.serialization.group_serializer import PrincipalSerializer


class GetADPrincipalAuthorizationGroupHandler(BaseHandler):

    REPLY_ACTION = f"{CUSTOM_ACTIONS}/AccountManagement/GetADPrincipalAuthorizationGroupResponse"

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        try:
            principal_dn = self._extract(context)
            transitive = self._collect_transitive(principal_dn)
            principals: Any = PrincipalLoader(self.db.db).load_many(sorted(transitive))
            body: Any = PrincipalSerializer.memberof_response(
                "GetADPrincipalAuthorizationGroupResponse", principals)
            return self.envelope.wrap(self.REPLY_ACTION, context.message_id, body)
        except Exception as e:
            self.logger.exception("[GetADPrincipalAuthorizationGroup] failure")
            return cast(str, self.faults.custom_action_fault(
                context.message_id, "GetADPrincipalAuthorizationGroupFault", str(e),
            ))

    def _extract(self, context: RequestContext) -> Optional[str]:
        parser = BodyParser(context.raw_xml or "")
        body: Any = parser.find_custom_body("GetADPrincipalAuthorizationGroupRequest")
        if body is not None:
            value: Any = parser.text_of(body, "PrincipalDN")
            if value:
                return str(value)
        return context.object_reference

    def _collect_transitive(self, principal_dn: Optional[str]) -> Set[str]:
        if not principal_dn:
            return set()
        base: Any = self.db.naming_context()
        seen: Set[str] = set()
        self._walk_groups(principal_dn, base, seen)
        return seen

    def _walk_groups(self, member_dn: str, base: Any, seen: Set[str]) -> None:
        try:
            results: Any = self.db.db.search(
                base=base, scope=ldb.SCOPE_SUBTREE,
                expression=f"(&(objectClass=group)(member={member_dn}))",
                attrs=["distinguishedName"],
            )
        except ldb.LdbError:
            return
        for msg in results:
            dn = str(msg.dn)
            if dn in seen:
                continue
            seen.add(dn)
            self._walk_groups(dn, base, seen)
