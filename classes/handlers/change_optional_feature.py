"""ChangeOptionalFeature custom action (Enable-ADOptionalFeature)."""
from typing import Any, Tuple, cast

import ldb
from src.soap.namespaces import CUSTOM_ACTIONS

from classes.faults.exceptions import ADWSDataException
from classes.handlers.base import BaseHandler
from classes.parsing.body_parser import BodyParser
from classes.parsing.context import RequestContext

ENABLE_ATTR = "enableOptionalFeature"


# Enables an optional feature (the AD Recycle Bin) through the rootDSE, as AD does.
class ChangeOptionalFeatureHandler(BaseHandler):

    REPLY_ACTION = f"{CUSTOM_ACTIONS}/TopologyManagement/ChangeOptionalFeatureResponse"

    # Enables the feature on the scope the request names; disabling is refused.
    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        try:
            feature_id, target_dn, enable = self._extract(context)
            if not enable:
                raise ADWSDataException("An optional feature cannot be disabled once enabled")
            self._enable(target_dn, feature_id)
            self.logger.info(f"[ChangeOptionalFeature] {feature_id} enabled on {target_dn}")
            return self.envelope.wrap(self.REPLY_ACTION, context.message_id, "")
        except Exception as e:
            self.logger.exception("[ChangeOptionalFeature] failure")
            return cast(str, self.faults.custom_action_fault(
                context.message_id, "ChangeOptionalFeatureFault", str(e),
            ))

    # Reads the feature GUID, the scope DN and the Enable flag of the request.
    @staticmethod
    def _extract(context: RequestContext) -> Tuple[str, str, bool]:
        parser = BodyParser(context.raw_xml or "")
        body: Any = parser.find_custom_body("ChangeOptionalFeatureRequest")
        if body is None:
            raise ADWSDataException("Missing ChangeOptionalFeatureRequest body")
        feature: Any = parser.text_of(body, "FeatureId")
        target: Any = parser.text_of(body, "DistinguishedName")
        enable = (parser.text_of(body, "Enable") or "false").lower() == "true"
        if not feature or not target:
            raise ADWSDataException("FeatureId and DistinguishedName are required")
        return str(feature).strip().strip("{}"), str(target), enable

    # Writes enableOptionalFeature "<scope DN>:<feature GUID>" on the rootDSE
    # ([MS-ADTS] 3.1.1.3.4.1.27): the directory checks the right and the level.
    def _enable(self, target_dn: str, feature_id: str) -> None:
        msg = ldb.Message(ldb.Dn(self.db.db, ""))
        value = f"{target_dn}:{feature_id}"
        msg[ENABLE_ATTR] = ldb.MessageElement(
            [value.encode("utf-8")], ldb.FLAG_MOD_ADD, ENABLE_ATTR,
        )
        self.db.db.modify(msg)
