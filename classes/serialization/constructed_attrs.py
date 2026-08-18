from typing import List, Optional

CONSTRUCTED_ATTRIBUTES = (
    "tokenGroups",
    "tokenGroupsGlobalAndUniversal",
    "tokenGroupsNoGCAcceptable",
    "canonicalName",
    "primaryGroupToken",
    "msDS-PrincipalName",
    "msDS-User-Account-Control-Computed",
    "msDS-UserPasswordExpiryTimeComputed",
    "structuralObjectClass",
    "subSchemaSubentry",
    "allowedAttributes",
    "allowedAttributesEffective",
    "allowedChildClasses",
    "allowedChildClassesEffective",
    "createTimeStamp",
    "modifyTimeStamp",
    "parentGUID",
)


class ConstructedAttrs:

    @staticmethod
    def is_constructed(name: Optional[str]) -> bool:
        if not name:
            return False
        lowered = name.lower()
        return any(lowered == attr.lower() for attr in CONSTRUCTED_ATTRIBUTES)

    @staticmethod
    def expand(requested: Optional[List[str]]) -> List[str]:
        if not requested:
            return ["*"] + list(CONSTRUCTED_ATTRIBUTES)
        normalized = [a for a in requested if a]
        if "*" in normalized:
            existing = {a.lower() for a in normalized}
            for attr in CONSTRUCTED_ATTRIBUTES:
                if attr.lower() not in existing:
                    normalized.append(attr)
        return normalized
