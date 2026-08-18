from typing import Any, Dict, List, Optional

import ldb

from classes.parsing.context import RequestContext
from classes.directory.schema_cache import SchemaCache
from classes.handlers.base import BaseHandler


class SchemaHandler(BaseHandler):

    SCHEMA_ATTRS: List[str] = [
        "lDAPDisplayName", "attributeID", "attributeSyntax", "isSingleValued",
        "objectClass", "name", "subClassOf", "mustContain", "mayContain",
        "systemMustContain", "systemMayContain",
    ]

    _CACHE: SchemaCache = SchemaCache()

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        try:
            schema_dn = self._schema_dn()
            cache_key = f"{schema_dn}::{context.object_reference or ''}"
            attrs_by_obj: Optional[Dict[str, Dict[str, Any]]] = self._CACHE.get(cache_key)
            if attrs_by_obj is None:
                objects = self._search_schema(schema_dn, context)
                attrs_by_obj = {str(o.dn): dict(o) for o in objects}
                self._CACHE.set(cache_key, attrs_by_obj)
            for _dn, attrs in attrs_by_obj.items():
                self._register_syntax_for(attrs)
            return self._build_response(context, attrs_by_obj)
        except Exception as e:
            self.logger.exception("[SCHEMA] failure")
            return str(
                self.faults.directory_error(context.message_id, str(e), "SchemaError")
            )

    def _schema_dn(self) -> str:
        result = self.db.db.search(
            base="", scope=ldb.SCOPE_BASE, attrs=["schemaNamingContext"]
        )
        if not result or "schemaNamingContext" not in result[0]:
            raise RuntimeError("Schema naming context not found")
        raw: Any = result[0]["schemaNamingContext"][0]
        return raw.decode("utf-8") if isinstance(raw, bytes) else str(raw)

    def _search_schema(self, schema_dn: str, context: RequestContext) -> Any:
        scope = ldb.SCOPE_BASE if context.object_reference else ldb.SCOPE_ONELEVEL
        base = context.object_reference or schema_dn
        return self.db.db.search(
            base=base, scope=scope,
            expression="(|(objectClass=attributeSchema)(objectClass=classSchema))",
            attrs=self.SCHEMA_ATTRS,
        )

    def _register_syntax_for(self, attrs: Dict[str, Any]) -> None:
        name: Any = attrs.get("lDAPDisplayName")
        oid: Any = attrs.get("attributeID")
        if name and oid:
            decoded_name = name[0].decode("utf-8") if isinstance(name[0], bytes) else str(name[0])
            decoded_oid = oid[0].decode("utf-8") if isinstance(oid[0], bytes) else str(oid[0])
            self.syntaxes.register(decoded_name, decoded_oid)

    def _build_response(
        self, context: RequestContext, attrs_by_obj: Dict[str, Dict[str, Any]]
    ) -> str:
        items: List[str] = []
        for dn, attrs in attrs_by_obj.items():
            rendered = self.renderer.render_attributes(attrs)
            items.append(
                f'<addata:schemaObject DistinguishedName="{dn}">{rendered}</addata:schemaObject>'
            )
        body = f'<addata:SchemaResponse>{"".join(items)}</addata:SchemaResponse>'
        schema_action = "http://schemas.microsoft.com/2008/1/ActiveDirectory/SchemaResponse"
        return str(self.envelope.wrap(schema_action, context.message_id, body))
