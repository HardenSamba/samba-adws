import socket
from typing import Any, Dict, List, cast

import ldb
from src.soap.namespaces import CUSTOM_ACTIONS

from classes.handlers.base import BaseHandler
from classes.parsing.context import RequestContext
from classes.serialization.dc_serializer import DomainControllerSerializer
from classes.serialization.ldb_value import LdbValue

_EMPTY_GUID = "00000000-0000-0000-0000-000000000000"
_DC_ATTRS = ["distinguishedName", "objectGUID", "invocationId"]


class GetADDomainControllerHandler(BaseHandler):

    REPLY_ACTION = f"{CUSTOM_ACTIONS}/TopologyManagement/GetADDomainControllerResponse"

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        try:
            body = DomainControllerSerializer.response(self._load())
            return self.envelope.wrap(self.REPLY_ACTION, context.message_id, body)
        except Exception as e:
            self.logger.exception("[GetADDomainController] failure")
            return cast(str, self.faults.custom_action_fault(
                context.message_id, "GetADDomainControllerFault", str(e),
            ))

    def _load(self) -> List[Dict[str, Any]]:
        cfg: Any = self.db.naming_context("configurationNamingContext")
        if not cfg:
            return []
        results: Any = self.db.db.search(
            base=cfg, scope=ldb.SCOPE_SUBTREE,
            expression="(objectClass=nTDSDSA)", attrs=_DC_ATTRS,
        )
        return [self._format(msg) for msg in results]

    def _format(self, msg: Any) -> Dict[str, Any]:
        ntds_dn = str(msg.dn)
        base = self.db.naming_context("defaultNamingContext")
        dns = LdbValue.dn_to_dns(base)
        host = self.db.naming_context("dnsHostName") or socket.gethostname()
        return {
            "base": base, "host": host, "name": host.split(".")[0],
            "ntds_dn": ntds_dn, "server_dn": ntds_dn.split(",", 1)[-1],
            "site": self._site(ntds_dn), "domain": dns, "forest": dns,
            "invocation_id": LdbValue.guid(msg, "invocationId") or _EMPTY_GUID,
            "server_guid": LdbValue.guid(msg) or _EMPTY_GUID,
            "ldap_port": "389", "ssl_port": "636",
            "is_gc": "true", "is_ro": "false", "enabled": "true",
            "roles": None, "partitions": None, "computer_dn": None,
            "os_name": None, "os_version": None, "os_sp": None, "os_hotfix": None,
        }

    @staticmethod
    def _site(ntds_dn: str) -> str:
        parts = [p.strip() for p in ntds_dn.split(",")]
        sites = [parts[i - 1][3:] for i in range(1, len(parts))
                 if parts[i].upper() == "CN=SITES"]
        return sites[0] if sites else "Default-First-Site-Name"
