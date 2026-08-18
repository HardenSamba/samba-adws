from typing import Any, Dict, Sequence, Tuple, cast

from classes.serialization.ca_elements import CaElement
from classes.parsing.context import RequestContext
from classes.serialization.ldb_value import LdbValue
from src.soap.namespaces import CUSTOM_ACTIONS
from classes.handlers.base import BaseHandler

_NIL_FIELDS: Tuple[str, ...] = ("app_partitions", "xforest", "spn", "upn", "sites")

_FOREST_PLAN: Sequence[Tuple[str, str, str]] = (
    ("array", "ApplicationPartitions", "app_partitions"),
    ("array", "CrossForestReferences", "xforest"),
    ("text", "DomainNamingMaster", "dns_host"),
    ("array", "Domains", "domains"),
    ("text", "ForestMode", "forest_mode"),
    ("array", "GlobalCatalogs", "gcs"),
    ("text", "Name", "name"),
    ("text", "RootDomain", "root_domain"),
    ("array", "SPNSuffixes", "spn"),
    ("text", "SchemaMaster", "dns_host"),
    ("array", "Sites", "sites"),
    ("array", "UPNSuffixes", "upn"),
)


class GetADForestHandler(BaseHandler):

    REPLY_ACTION = f"{CUSTOM_ACTIONS}/TopologyManagement/GetADForestResponse"

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        try:
            body = self._serialize(self._collect())
            return self.envelope.wrap(self.REPLY_ACTION, context.message_id, body)
        except Exception as e:
            self.logger.exception("[GetADForest] failure")
            return cast(str, self.faults.custom_action_fault(
                context.message_id, "GetADForestFault", str(e)
            ))

    def _collect(self) -> Dict[str, Any]:
        root = self.db.naming_context("rootDomainNamingContext")
        dns = LdbValue.dn_to_dns(root)
        host = self.db.naming_context("dnsHostName")
        data: Dict[str, Any] = dict.fromkeys(_NIL_FIELDS)
        data.update(
            name=dns, root_domain=dns, dns_host=host,
            forest_mode=self.db.naming_context("forestFunctionality") or "0",
            domains=[dns] if dns else None, gcs=[host] if host else None,
        )
        return data

    @staticmethod
    def _serialize(data: Dict[str, Any]) -> str:
        inner = CaElement.fields(_FOREST_PLAN, data)
        return CaElement.response("GetADForestResponse", "Forest", inner)
