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

BASE_ONLY_ATTRIBUTES = (
    "tokenGroups",
    "tokenGroupsGlobalAndUniversal",
    "tokenGroupsNoGCAcceptable",
)

BASE_ONLY_LOWERED = frozenset(name.lower() for name in BASE_ONLY_ATTRIBUTES)


# Decides which attribute names a directory search may ask for, knowing that
# some attributes are computed per entry and that a few of those are served
# only by a BASE-scoped search.
class ConstructedAttrs:

    # Tells whether a name is one of the attributes the directory computes
    # instead of storing.
    @staticmethod
    def is_constructed(name: Optional[str]) -> bool:
        if not name:
            return False
        lowered = name.lower()
        return any(lowered == attr.lower() for attr in CONSTRUCTED_ATTRIBUTES)

    # Adds every constructed attribute to a selection that asks for all of
    # them, either by being empty or by naming the '*' wildcard.
    @staticmethod
    def expand(requested: Optional[List[str]]) -> List[str]:
        if not requested:
            return ["*"] + list(CONSTRUCTED_ATTRIBUTES)
        normalized = [a for a in requested if a]
        if "*" not in normalized:
            return normalized
        existing = {a.lower() for a in normalized}
        extra = [a for a in CONSTRUCTED_ATTRIBUTES if a.lower() not in existing]
        return normalized + extra

    # Projects a selection onto one search scope: a BASE search still gets the
    # constructed attributes expanded, while any wider search keeps only what
    # such a scope can serve, so the directory answers instead of failing.
    @staticmethod
    def for_scope(requested: Optional[List[str]], is_base: bool) -> List[str]:
        if is_base:
            expanded = ConstructedAttrs.expand(requested)
            return ConstructedAttrs._with_object_class(expanded or ["objectClass"])
        named = [a for a in (requested or ["*"]) if a]
        kept = [a for a in named if a.lower() not in BASE_ONLY_LOWERED]
        return ConstructedAttrs._with_object_class(kept or ["objectClass"])

    # Guarantees objectClass is part of a non-empty projection, because every
    # rendered object reports its structural class from that attribute.
    @staticmethod
    def _with_object_class(attrs: List[str]) -> List[str]:
        if attrs and not any(a.lower() == "objectclass" for a in attrs):
            return attrs + ["objectClass"]
        return attrs
