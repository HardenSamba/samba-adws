from typing import Any, Dict, List, Sequence, Tuple

from classes.serialization.ca_elements import CaElement

_DC_PLAN: Sequence[Tuple[str, str, str]] = (
    ("text", "DefaultPartition", "base"),
    ("text", "HostName", "host"),
    ("text", "InvocationId", "invocation_id"),
    ("text", "LdapPort", "ldap_port"),
    ("text", "NTDSSettingsObjectDN", "ntds_dn"),
    ("text", "Name", "name"),
    ("array", "OperationMasterRole", "roles"),
    ("array", "Partitions", "partitions"),
    ("text", "ServerObjectDN", "server_dn"),
    ("text", "ServerObjectGuid", "server_guid"),
    ("text", "Site", "site"),
    ("text", "SslPort", "ssl_port"),
    ("text", "ComputerDN", "computer_dn"),
    ("text", "Domain", "domain"),
    ("text", "Enabled", "enabled"),
    ("text", "Forest", "forest"),
    ("text", "IsGlobalCatalog", "is_gc"),
    ("text", "IsReadOnly", "is_ro"),
    ("text", "OSHotFix", "os_hotfix"),
    ("text", "OSName", "os_name"),
    ("text", "OSServicepack", "os_sp"),
    ("text", "OSVersion", "os_version"),
)


class DomainControllerSerializer:

    @classmethod
    def response(cls, controllers: List[Dict[str, Any]]) -> str:
        items = "".join(cls._item(c) for c in controllers)
        return CaElement.response(
            "GetADDomainControllerResponse", "DomainControllers", items
        )

    @staticmethod
    def _item(controller: Dict[str, Any]) -> str:
        inner = CaElement.fields(_DC_PLAN, controller)
        return f"<ActiveDirectoryDomainController>{inner}</ActiveDirectoryDomainController>"
