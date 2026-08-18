from typing import Dict

FSMO_ROLE_DN_TEMPLATES: Dict[str, str] = {
    "PDCEmulator": "{domain_dn}",
    "RIDMaster": "CN=RID Manager$,CN=System,{domain_dn}",
    "InfrastructureMaster": "CN=Infrastructure,{domain_dn}",
    "SchemaMaster": "{schema_dn}",
    "DomainNamingMaster": "CN=Partitions,{config_dn}",
}

FSMO_ROLE_ATTR: str = "fSMORoleOwner"
