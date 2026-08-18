"""Enumerate handler - List/Enumerate AD objects"""
import html
from datetime import datetime, timedelta
from typing import Any, List

import ldb

from classes.serialization.constructed_attrs import ConstructedAttrs
from classes.parsing.context import RequestContext
from src.enumeration.enumeration import get_enumeration_registry
from classes.faults.exceptions import ADWSException
from classes.parsing.filter_parser import FilterParser
from classes.handlers.base import BaseHandler


class EnumerateHandler(BaseHandler):
    """Handles WS-Enumeration Enumerate requests"""

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)

        try:
            base_dn: str = context.base_dn or ''
            search_filter: str = self._normalize(context.ldap_filter or '(objectClass=*)')
            ldap_scope: str = context.ldap_scope or 'Subtree'
            selection_attrs: List[str] = self._with_object_class(
                ConstructedAttrs.expand(context.selection_attributes)
            )

            if not base_dn:
                base_dn = self.db.naming_context() or ''
                if base_dn:
                    self.logger.info(f"[ENUMERATE] Empty base, defaulted to {base_dn}")

            scope_map = {
                'Base': ldb.SCOPE_BASE,
                'OneLevel': ldb.SCOPE_ONELEVEL,
                'Subtree': ldb.SCOPE_SUBTREE,
            }
            ldb_scope = scope_map.get(ldap_scope, ldb.SCOPE_SUBTREE)

            self.logger.info(f"[ENUMERATE] Base DN: '{base_dn}'")
            self.logger.info(f"[ENUMERATE] Filter: {search_filter}")
            self.logger.info(f"[ENUMERATE] Scope: {ldap_scope} (ldb:{ldb_scope})")
            self.logger.info(f"[ENUMERATE] Attributes: {selection_attrs}")

            try:
                results = self.db.db.search(
                    base=base_dn,
                    scope=ldb_scope,
                    expression=search_filter,
                    attrs=selection_attrs,
                    controls=context.ldap_controls or None,
                )

                self.logger.info(f"[ENUMERATE] Found {len(results)} objects")
            except Exception as e:
                self.logger.error(f"[ENUMERATE] Search failed: {str(e)}")
                raise ADWSException(f"Search failed: {str(e)}") from e

            enum_registry = get_enumeration_registry(self.logger)
            context_id: str = enum_registry.create_context(
                base_dn=base_dn,
                search_filter=search_filter,
                attributes=selection_attrs,
                session_id=context.message_id,
                ttl_seconds=3600
            )

            enum_context = enum_registry.get_context(context_id)
            if enum_context:
                limit = enum_registry.MAX_RESULTS_PER_CONTEXT
                materialized: List[Any] = list(results)
                if len(materialized) > limit:
                    self.logger.warning(
                        f"[ENUMERATE] Truncating {len(materialized)} → {limit}"
                    )
                    materialized = materialized[:limit]
                enum_context.cached_results = materialized

            expires = (datetime.utcnow() + timedelta(hours=1)).isoformat() + "Z"
            response_xml = self._build_enumerate_response(context, context_id, expires)

            return response_xml

        except ADWSException:
            raise
        except Exception as e:
            self.logger.error(f"[ENUMERATE] Error: {str(e)}")
            raise ADWSException(f"Enumeration failed: {str(e)}") from e

    # Normalises the client filter (e.g. wraps bare NOT operands); raw on failure.
    @staticmethod
    def _normalize(raw: str) -> str:
        try:
            return FilterParser().parse(raw)
        except ValueError:
            return raw

    @staticmethod
    def _with_object_class(attrs: List[str]) -> List[str]:
        if attrs and not any(a.lower() == "objectclass" for a in attrs):
            return attrs + ["objectClass"]
        return attrs

    def _build_enumerate_response(
        self, context: RequestContext, enum_context_id: str, expires: str
    ) -> str:
        response_xml = (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
            'xmlns:a="http://www.w3.org/2005/08/addressing" '
            'xmlns:wsen="http://schemas.xmlsoap.org/ws/2004/09/enumeration">'
            '<s:Header>'
            '<a:Action s:mustUnderstand="1">'
            'http://schemas.xmlsoap.org/ws/2004/09/enumeration/EnumerateResponse'
            '</a:Action>'
            f'<a:RelatesTo>{html.escape(context.message_id)}</a:RelatesTo>'
            '</s:Header>'
            '<s:Body>'
            '<wsen:EnumerateResponse>'
            f'<wsen:Expires>{expires}</wsen:Expires>'
            f'<wsen:EnumerationContext>{enum_context_id}</wsen:EnumerationContext>'
            '</wsen:EnumerateResponse>'
            '</s:Body>'
            '</s:Envelope>'
        )

        return response_xml
