from typing import Any, Tuple, cast

import ldb
from src.soap.namespaces import CUSTOM_ACTIONS

from classes.handlers.base import BaseHandler
from classes.parsing.body_parser import BodyParser
from classes.parsing.context import RequestContext

ENABLED_FEATURE_ATTR = "msDS-EnabledFeature"


class ChangeOptionalFeatureHandler(BaseHandler):

    REPLY_ACTION = f"{CUSTOM_ACTIONS}/TopologyManagement/ChangeOptionalFeatureResponse"

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        try:
            feature_id, target_dn, enable = self._extract(context)
            feature_dn = self._resolve_feature_dn(feature_id)
            self._toggle(target_dn, feature_dn, enable)
            self.logger.info(f"[ChangeOptionalFeature] {feature_id} enable={enable} on {target_dn}")
            return self.envelope.wrap(self.REPLY_ACTION, context.message_id, "")
        except Exception as e:
            self.logger.exception("[ChangeOptionalFeature] failure")
            return cast(str, self.faults.custom_action_fault(
                context.message_id, "ChangeOptionalFeatureFault", str(e),
            ))

    @staticmethod
    def _extract(context: RequestContext) -> Tuple[str, str, bool]:
        parser = BodyParser(context.raw_xml or "")
        body: Any = parser.find_custom_body("ChangeOptionalFeatureRequest")
        if body is None:
            raise ValueError("Missing ChangeOptionalFeatureRequest body")
        feature: Any = parser.text_of(body, "FeatureId")
        target: Any = parser.text_of(body, "DistinguishedName")
        enable = (parser.text_of(body, "Enable") or "false").lower() == "true"
        if not feature or not target:
            raise ValueError("FeatureId and DistinguishedName are required")
        return feature, target, enable

    def _resolve_feature_dn(self, feature_id: str) -> str:
        config_dn: Any = self.db.naming_context("configurationNamingContext")
        results: Any = self.db.db.search(
            base=config_dn, scope=ldb.SCOPE_SUBTREE,
            expression=(
                f"(&(objectClass=msDS-OptionalFeature)(msDS-OptionalFeatureGUID={feature_id}))"
            ),
            attrs=["distinguishedName"],
        )
        if not results:
            raise RuntimeError(f"Optional feature {feature_id} not found")
        return str(results[0].dn)

    def _toggle(self, target_dn: str, feature_dn: str, enable: bool) -> None:
        flag = ldb.FLAG_MOD_ADD if enable else ldb.FLAG_MOD_DELETE
        msg = ldb.Message(ldb.Dn(self.db.db, target_dn))
        msg[ENABLED_FEATURE_ATTR] = ldb.MessageElement(
            [feature_dn.encode("utf-8")], flag, ENABLED_FEATURE_ATTR,
        )
        self.db.db.modify(msg)
