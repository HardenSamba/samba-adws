from typing import Any, Dict, Sequence, Tuple

from classes.serialization.ca_elements import CaElement

_DOMAIN_PLAN: Sequence[Tuple[str, str, str]] = (
    ("text", "DistinguishedName", "dn"),
    ("text", "Name", "name"),
    ("text", "ObjectClass", "object_class"),
    ("text", "ObjectGuid", "object_guid"),
    ("array", "ObjectTypes", "object_types"),
    ("text", "ReferenceServer", "dns_root"),
    ("text", "DNSRoot", "dns_root"),
    ("text", "DeletedObjectsContainer", "deleted"),
    ("text", "LostAndFoundContainer", "lostfound"),
    ("text", "QuotasContainer", "quotas"),
    ("array", "ReadOnlyReplicaDirectoryServer", "ro_replica"),
    ("array", "ReplicaDirectoryServer", "replica"),
    ("array", "SubordinateReferences", "subrefs"),
    ("array", "AllowedDNSSuffixes", "dns_suffixes"),
    ("array", "AppliedGroupPolicies", "gpos"),
    ("array", "ChildDomains", "children"),
    ("text", "ComputersContainer", "computers"),
    ("text", "DomainControllersContainer", "dcs"),
    ("text", "DomainMode", "domain_mode"),
    ("text", "DomainSID", "sid"),
    ("text", "ForeignSecurityPrincipalsContainer", "fsp"),
    ("text", "Forest", "forest_dns"),
    ("text", "InfrastructureMaster", "dns_host"),
    ("text", "LastLogonReplicationInterval", "llri"),
    ("text", "ManagedBy", "managed_by"),
    ("text", "NetBIOSName", "netbios"),
    ("text", "PDCEmulator", "dns_host"),
    ("text", "ParentDomain", "parent"),
    ("text", "RIDMaster", "dns_host"),
    ("text", "SystemsContainer", "system"),
    ("text", "UsersContainer", "users"),
)


class DomainSerializer:

    @classmethod
    def domain_response(cls, raw: Dict[str, Any]) -> str:
        data = cls._data(raw)
        inner = CaElement.fields(_DOMAIN_PLAN, data)
        return CaElement.response("GetADDomainResponse", "Domain", inner)

    @classmethod
    def _data(cls, raw: Dict[str, Any]) -> Dict[str, Any]:
        data: Dict[str, Any] = dict(raw)
        data.update(cls._containers(raw.get("base", "")))
        data["object_class"] = "domainDNS"
        data["object_types"] = ["top", "domain", "domainDNS"]
        data["replica"] = [raw["dns_host"]] if raw.get("dns_host") else None
        return data

    @staticmethod
    def _containers(base: str) -> Dict[str, str]:
        return {
            "users": f"CN=Users,{base}",
            "computers": f"CN=Computers,{base}",
            "dcs": f"OU=Domain Controllers,{base}",
            "system": f"CN=System,{base}",
            "fsp": f"CN=ForeignSecurityPrincipals,{base}",
            "deleted": f"CN=Deleted Objects,{base}",
            "lostfound": f"CN=LostAndFound,{base}",
            "quotas": f"CN=NTDS Quotas,{base}",
        }
