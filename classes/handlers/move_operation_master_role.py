from typing import Any, Tuple, cast

import ldb
from src.directory.fsmo_roles import FSMO_ROLE_ATTR, FSMO_ROLE_DN_TEMPLATES
from src.soap.namespaces import CUSTOM_ACTIONS

from classes.handlers.base import BaseHandler
from classes.parsing.body_parser import BodyParser
from classes.parsing.context import RequestContext


class MoveOperationMasterRoleHandler(BaseHandler):

    REPLY_ACTION = f"{CUSTOM_ACTIONS}/TopologyManagement/MoveADOperationMasterRoleResponse"

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        try:
            role, seize = self._extract(context)
            target_dn, owner_dn = self._resolve_role(role)
            self._transfer(target_dn, owner_dn)
            _ = seize
            self.logger.info(f"[MoveFSMO] {role} -> {owner_dn} (seize={seize})")
            return self.envelope.wrap(self.REPLY_ACTION, context.message_id, "")
        except Exception as e:
            self.logger.exception("[MoveFSMO] failure")
            return cast(str, self.faults.custom_action_fault(
                context.message_id, "MoveADOperationMasterRoleFault", str(e),
            ))

    @staticmethod
    def _extract(context: RequestContext) -> Tuple[str, bool]:
        parser = BodyParser(context.raw_xml or "")
        body: Any = parser.find_custom_body("MoveADOperationMasterRoleRequest")
        if body is None:
            raise ValueError("Missing MoveADOperationMasterRoleRequest body")
        role: Any = parser.text_of(body, "OperationMasterRole")
        seize = (parser.text_of(body, "Seize") or "false").lower() == "true"
        if not role or role not in FSMO_ROLE_DN_TEMPLATES:
            raise ValueError(f"Unsupported FSMO role: {role}")
        return role, seize

    def _resolve_role(self, role: str) -> Tuple[str, str]:
        domain_dn: Any = self.db.naming_context("defaultNamingContext")
        config_dn: Any = self.db.naming_context("configurationNamingContext")
        schema_dn: Any = self.db.naming_context("schemaNamingContext")
        target = FSMO_ROLE_DN_TEMPLATES[role].format(
            domain_dn=domain_dn, config_dn=config_dn, schema_dn=schema_dn,
        )
        owner = self._self_ntds_settings_dn(config_dn)
        return target, owner

    def _self_ntds_settings_dn(self, config_dn: Any) -> str:
        results: Any = self.db.db.search(
            base=config_dn, scope=ldb.SCOPE_SUBTREE,
            expression="(&(objectClass=nTDSDSA)(options=*))",
            attrs=["distinguishedName"],
        )
        if not results:
            raise RuntimeError("Cannot locate local nTDSDSA settings")
        return str(results[0].dn)

    def _transfer(self, target_dn: str, owner_dn: str) -> None:
        msg = ldb.Message(ldb.Dn(self.db.db, target_dn))
        flag = ldb.FLAG_MOD_REPLACE
        msg[FSMO_ROLE_ATTR] = ldb.MessageElement([owner_dn.encode("utf-8")], flag, FSMO_ROLE_ATTR)
        self.db.db.modify(msg)
