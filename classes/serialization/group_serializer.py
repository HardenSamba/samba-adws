from typing import Any, Dict, List, Sequence, Tuple

from classes.serialization.ca_elements import CaElement

_PRINCIPAL_PLAN: Sequence[Tuple[str, str, str]] = (
    ("text", "DistinguishedName", "dn"),
    ("text", "Name", "name"),
    ("text", "ObjectClass", "object_class"),
    ("text", "ObjectGuid", "object_guid"),
    ("array", "ObjectTypes", "object_types"),
    ("text", "ReferenceServer", "server"),
    ("text", "SID", "sid"),
    ("text", "SamAccountName", "sam"),
)
_GROUP_EXTRA: Sequence[Tuple[str, str, str]] = (
    ("text", "GroupScope", "group_scope"),
    ("text", "GroupType", "group_type"),
)


class PrincipalSerializer:

    @classmethod
    def members_response(cls, principals: List[Dict[str, Any]]) -> str:
        items = "".join(cls._principal(p) for p in principals)
        return CaElement.response("GetADGroupMemberResponse", "Members", items)

    @classmethod
    def memberof_response(cls, operation: str, groups: List[Dict[str, Any]]) -> str:
        items = "".join(cls._group(g) for g in groups)
        return CaElement.response(operation, "MemberOf", items)

    @staticmethod
    def _principal(principal: Dict[str, Any]) -> str:
        inner = CaElement.fields(_PRINCIPAL_PLAN, principal)
        return f"<ActiveDirectoryPrincipal>{inner}</ActiveDirectoryPrincipal>"

    @staticmethod
    def _group(group: Dict[str, Any]) -> str:
        base = CaElement.fields(_PRINCIPAL_PLAN, group)
        extra = CaElement.fields(_GROUP_EXTRA, group)
        return f"<ActiveDirectoryGroup>{base}{extra}</ActiveDirectoryGroup>"
