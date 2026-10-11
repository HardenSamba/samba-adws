"""Enumerate handler - List/Enumerate AD objects"""
import html
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

import ldb
from src.enumeration.enumeration import get_enumeration_registry

from classes.enumeration.enumerate_query import EnumerateQuery, build_query
from classes.faults.exceptions import ADWSException
from classes.handlers.base import BaseHandler
from classes.parsing.context import RequestContext

LDB_SCOPES: Dict[str, int] = {
    "Base": ldb.SCOPE_BASE,
    "OneLevel": ldb.SCOPE_ONELEVEL,
    "Subtree": ldb.SCOPE_SUBTREE,
}

ENUMERATE_RESPONSE_TEMPLATE = (
    '<?xml version="1.0" encoding="utf-8"?>'
    '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
    'xmlns:a="http://www.w3.org/2005/08/addressing" '
    'xmlns:wsen="http://schemas.xmlsoap.org/ws/2004/09/enumeration">'
    '<s:Header>'
    '<a:Action s:mustUnderstand="1">'
    'http://schemas.xmlsoap.org/ws/2004/09/enumeration/EnumerateResponse'
    '</a:Action>'
    '<a:RelatesTo>{relates_to}</a:RelatesTo>'
    '</s:Header>'
    '<s:Body>'
    '<wsen:EnumerateResponse>'
    '<wsen:Expires>{expires}</wsen:Expires>'
    '<wsen:EnumerationContext>{enum_context_id}</wsen:EnumerationContext>'
    '</wsen:EnumerateResponse>'
    '</s:Body>'
    '</s:Envelope>'
)


# Handles WS-Enumeration Enumerate: runs the search the request describes,
# caches its results and answers with the context Pull reads them from.
class EnumerateHandler(BaseHandler):

    # Resolves the request into one search, caches what it returned and
    # answers with the enumeration context identifier and its expiry.
    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        query = build_query(context, self._base_dn(context))
        results = self._search(query, context.ldap_controls or None)
        context_id = self._cache(query, results, context.message_id)
        expires = (datetime.utcnow() + timedelta(hours=1)).isoformat() + "Z"
        return self._build_enumerate_response(context, context_id, expires)

    # Resolves the base the search starts from, falling back to the directory's
    # default naming context; a directory that refuses that lookup has to leave
    # this handler as the typed fault the dispatcher answers a client with.
    def _base_dn(self, context: RequestContext) -> str:
        if context.base_dn:
            return context.base_dn
        try:
            base_dn: str = self.db.naming_context() or ''
        except Exception as e:
            self.logger.error(f"[ENUMERATE] Naming context lookup failed: {str(e)}")
            raise ADWSException(f"Naming context lookup failed: {str(e)}") from e
        self.logger.info(f"[ENUMERATE] Empty base, defaulted to '{base_dn}'")
        return base_dn

    # Runs the query against the directory, re-raising any refusal as the
    # typed fault the dispatcher knows how to answer a client with.
    def _search(self, query: EnumerateQuery, controls: Optional[List[str]]) -> Any:
        scope = LDB_SCOPES.get(query.scope_name, ldb.SCOPE_SUBTREE)
        self.logger.info(
            f"[ENUMERATE] base='{query.base_dn}' filter={query.search_filter} "
            f"scope={query.scope_name}(ldb:{scope}) attrs={query.attributes} "
            f"controls={controls}"
        )
        try:
            results = self.db.db.search(
                base=query.base_dn,
                scope=scope,
                expression=query.search_filter,
                attrs=query.attributes,
                controls=controls,
            )
        except Exception as e:
            self.logger.error(f"[ENUMERATE] Search failed: {str(e)}")
            raise ADWSException(f"Search failed: {str(e)}") from e
        self.logger.info(f"[ENUMERATE] Found {len(results)} objects")
        return results

    # Stores the results under a fresh enumeration context, truncated to the
    # registry ceiling, and returns that context's identifier.
    def _cache(self, query: EnumerateQuery, results: Any, session_id: str) -> str:
        registry = get_enumeration_registry(self.logger)
        context_id: str = registry.create_context(
            base_dn=query.base_dn, search_filter=query.search_filter,
            attributes=query.attributes, session_id=session_id, ttl_seconds=3600,
        )
        enum_context = registry.get_context(context_id)
        if enum_context is None:
            return context_id
        materialized: List[Any] = list(results)
        limit = registry.MAX_RESULTS_PER_CONTEXT
        if len(materialized) > limit:
            self.logger.warning(f"[ENUMERATE] Truncating {len(materialized)} -> {limit}")
            materialized = materialized[:limit]
        enum_context.cached_results = materialized
        return context_id

    # Renders the EnumerateResponse carrying the context identifier and the
    # moment the server will stop honouring it.
    def _build_enumerate_response(
        self, context: RequestContext, enum_context_id: str, expires: str
    ) -> str:
        return ENUMERATE_RESPONSE_TEMPLATE.format(
            relates_to=html.escape(context.message_id),
            expires=expires,
            enum_context_id=enum_context_id,
        )
