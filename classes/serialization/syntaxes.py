from typing import Dict, Tuple

from src.serialization.syntax_constants import (
    BINARY_ATTRIBUTES,
    BOOLEAN_ATTRIBUTES,
    DN_ATTRIBUTES,
    GENERALIZED_TIME_ATTRIBUTES,
    INTEGER_ATTRIBUTES,
    LARGE_INTEGER_ATTRIBUTES,
    NAME_OVERRIDES,
    SYNTAX_BOOLEAN,
    SYNTAX_DIRECTORY_STRING,
    SYNTAX_DN,
    SYNTAX_GENERALIZED_TIME,
    SYNTAX_INTEGER,
    SYNTAX_LARGE_INTEGER,
    SYNTAX_NAME_BY_OID,
    SYNTAX_NAME_UNICODE,
    SYNTAX_OCTET_STRING,
    XSD_STRING,
    XSI_TYPE_BY_OID,
)


class SyntaxRegistry:

    def __init__(self) -> None:
        self._cache: Dict[str, str] = {}
        self._seed(INTEGER_ATTRIBUTES, SYNTAX_INTEGER)
        self._seed(LARGE_INTEGER_ATTRIBUTES, SYNTAX_LARGE_INTEGER)
        self._seed(BINARY_ATTRIBUTES, SYNTAX_OCTET_STRING)
        self._seed(GENERALIZED_TIME_ATTRIBUTES, SYNTAX_GENERALIZED_TIME)
        self._seed(BOOLEAN_ATTRIBUTES, SYNTAX_BOOLEAN)
        self._seed(DN_ATTRIBUTES, SYNTAX_DN)

    def _seed(self, names: Tuple[str, ...], oid: str) -> None:
        for name in names:
            self._cache[name.lower()] = oid

    def syntax_for(self, attr_name: str) -> str:
        return self._cache.get(attr_name.lower(), SYNTAX_DIRECTORY_STRING)

    def xsi_type_for(self, attr_name: str) -> str:
        return XSI_TYPE_BY_OID.get(self.syntax_for(attr_name), XSD_STRING)

    def ldap_syntax_name_for(self, attr_name: str) -> str:
        override = NAME_OVERRIDES.get(attr_name.lower())
        if override is not None:
            return override
        return SYNTAX_NAME_BY_OID.get(self.syntax_for(attr_name), SYNTAX_NAME_UNICODE)

    def register(self, attr_name: str, oid: str) -> None:
        self._cache[attr_name.lower()] = oid
