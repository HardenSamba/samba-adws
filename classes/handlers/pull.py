"""Pull handler - Retrieve enumerated AD objects in batches"""
import html
import uuid
from typing import Any, Dict, List, Optional

from classes.parsing.context import RequestContext
from src.enumeration.enumeration import get_enumeration_registry
from classes.faults.exceptions import ADWSException
from classes.handlers.base import BaseHandler


class PullHandler(BaseHandler):
    """Handles WS-Enumeration Pull requests"""

    def handle(self, context: RequestContext) -> str:
        self.log_request(context)

        try:
            enum_context_id: Optional[str] = context.enumeration_context
            max_elements: int = context.max_elements or 100

            if not enum_context_id:
                raise ADWSException("EnumerationContext not provided in Pull request")

            enum_registry = get_enumeration_registry(self.logger)
            enum_context = enum_registry.get_context(enum_context_id)

            if not enum_context:
                raise ADWSException(
                    f"Invalid or expired enumeration context: {enum_context_id}"
                )

            results_batch: List[Any] = enum_context.get_next_batch(max_elements)
            is_end: bool = enum_context.is_end_of_sequence
            self.logger.info(
                f"[PULL] Returning {len(results_batch)} objects (end: {is_end})"
            )

            return self._build_pull_response(
                context, enum_context_id, results_batch, is_end
            )

        except ADWSException:
            raise
        except Exception as e:
            self.logger.error(f"[PULL] Error: {str(e)}")
            raise ADWSException(f"Pull failed: {str(e)}") from e

    def _render_object_xml(self, ldap_obj: Any) -> str:
        obj_class = self._object_class(ldap_obj)
        attrs: Dict[str, Any] = {
            k: v for k, v in dict(ldap_obj).items()
            if k.lower() not in ('dn', 'dn_parsed')
        }
        dn = str(ldap_obj.dn) if getattr(ldap_obj, 'dn', None) is not None else ''
        return self.serializer.whole_object(attrs, obj_class, self._guid_of(ldap_obj), dn)

    def _object_class(self, ldap_obj: Any) -> str:
        val: Any = ldap_obj.get('objectClass') if hasattr(ldap_obj, 'get') else None
        if not val:
            return 'top'
        last: Any = val[-1] if hasattr(val, '__getitem__') and len(val) > 0 else val
        if isinstance(last, bytes):
            return last.decode('utf-8', errors='replace')
        return str(last) if last is not None else 'top'

    def _guid_of(self, ldap_obj: Any) -> str:
        raw: Any = ldap_obj.get('objectGUID') if hasattr(ldap_obj, 'get') else None
        if raw is not None and not isinstance(raw, (str, bytes)):
            raw = raw[0] if hasattr(raw, '__getitem__') and len(raw) > 0 else raw
        if isinstance(raw, bytes) and len(raw) == 16:
            return str(uuid.UUID(bytes_le=raw))
        return ''

    def _build_pull_response(
        self,
        context: RequestContext,
        enum_context_id: str,
        results_batch: List[Any],
        is_end_of_sequence: bool,
    ) -> str:
        items_xml = ''.join(self._render_object_xml(o) for o in results_batch)
        items_element = f'<wsen:Items>{items_xml}</wsen:Items>' if items_xml \
            else '<wsen:Items/>'
        if is_end_of_sequence:
            continuation = '<wsen:EndOfSequence/>'
        else:
            continuation = (
                '<wsen:EnumerationContext>'
                f'{html.escape(enum_context_id)}</wsen:EnumerationContext>'
            )

        return (
            '<?xml version="1.0" encoding="utf-8"?>'
            '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
            'xmlns:a="http://www.w3.org/2005/08/addressing" '
            'xmlns:wsen="http://schemas.xmlsoap.org/ws/2004/09/enumeration" '
            'xmlns:addata="http://schemas.microsoft.com/2008/1/ActiveDirectory/Data" '
            'xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
            'xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
            '<s:Header>'
            '<a:Action s:mustUnderstand="1">'
            'http://schemas.xmlsoap.org/ws/2004/09/enumeration/PullResponse'
            '</a:Action>'
            f'<a:RelatesTo>{html.escape(context.message_id)}</a:RelatesTo>'
            '</s:Header>'
            '<s:Body>'
            '<wsen:PullResponse>'
            f'{items_element}{continuation}'
            '</wsen:PullResponse>'
            '</s:Body>'
            '</s:Envelope>'
        )
