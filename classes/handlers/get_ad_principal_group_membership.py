from typing import Any, List, Optional, cast

import ldb
from src.soap.namespaces import CUSTOM_ACTIONS

from classes.directory.principal_loader import PrincipalLoader
from classes.handlers.base import BaseHandler
from classes.parsing.body_parser import BodyParser
from classes.parsing.context import RequestContext
from classes.serialization.group_serializer import PrincipalSerializer


class GetADPrincipalGroupMembershipHandler(BaseHandler):

    REPLY_ACTION = f"{CUSTOM_ACTIONS}/AccountManagement/GetADPrincipalGroupMembershipResponse"

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        try:
            principal_dn = self._extract_dn(context)
            groups = self._find_groups(principal_dn)
            principals: Any = PrincipalLoader(self.db.db).load_many(groups)
            body: Any = PrincipalSerializer.memberof_response(
                "GetADPrincipalGroupMembershipResponse", principals)
            return self.envelope.wrap(self.REPLY_ACTION, context.message_id, body)
        except Exception as e:
            self.logger.exception("[GetADPrincipalGroupMembership] failure")
            return cast(str, self.faults.custom_action_fault(
                context.message_id, "GetADPrincipalGroupMembershipFault", str(e)
            ))

    def _extract_dn(self, context: RequestContext) -> Optional[str]:
        parser = BodyParser(context.raw_xml or "")
        body: Any = parser.find_custom_body("GetADPrincipalGroupMembershipRequest")
        if body is not None:
            value: Any = parser.text_of(body, "PrincipalDN")
            if value:
                return str(value)
        return context.object_reference

    def _find_groups(self, principal_dn: Optional[str]) -> List[str]:
        if not principal_dn:
            return []
        base: Any = self.db.naming_context()
        if not base:
            return []
        results: Any = self.db.db.search(
            base=base, scope=ldb.SCOPE_SUBTREE,
            expression=f"(&(objectClass=group)(member={principal_dn}))",
            attrs=["distinguishedName"],
        )
        return [str(msg.dn) for msg in results]
