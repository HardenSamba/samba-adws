"""Pull handler - Retrieve enumerated AD objects in batches"""
import html
import uuid
from typing import Any, Dict, List

from src.enumeration.enumeration import get_enumeration_registry

from classes.enumeration.enumeration_context import EnumerationContext
from classes.handlers.base import BaseHandler
from classes.parsing.context import RequestContext

PULL_RESPONSE_TEMPLATE = (
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
    '<a:RelatesTo>{relates_to}</a:RelatesTo>'
    '</s:Header>'
    '<s:Body>'
    '<wsen:PullResponse>{payload}</wsen:PullResponse>'
    '</s:Body>'
    '</s:Envelope>'
)


# Handles WS-Enumeration Pull: hands back one batch of the objects an earlier
# Enumerate cached, or a fault when the context it names is not ours.
class PullHandler(BaseHandler):

    # Answers with the next batch and the way to continue, or with the same
    # invalid-context fault its WS-Enumeration siblings return.
    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        enum_context_id = context.enumeration_context
        if not enum_context_id:
            return str(
                self.faults.invalid_enumeration_context(context.message_id, "(missing)")
            )
        registry = get_enumeration_registry(self.logger)
        enum_context = registry.get_context(enum_context_id)
        if enum_context is None:
            return str(
                self.faults.invalid_enumeration_context(context.message_id, enum_context_id)
            )
        batch: List[Any] = enum_context.get_next_batch(context.max_elements or 100)
        return self._build_pull_response(context, enum_context, batch)

    # Renders one cached directory entry as the object element a client reads.
    def _render_object_xml(self, ldap_obj: Any) -> str:
        obj_class = self._object_class(ldap_obj)
        attrs: Dict[str, Any] = {
            k: v for k, v in dict(ldap_obj).items()
            if k.lower() not in ('dn', 'dn_parsed')
        }
        dn = str(ldap_obj.dn) if getattr(ldap_obj, 'dn', None) is not None else ''
        return self.serializer.whole_object(attrs, obj_class, self._guid_of(ldap_obj), dn)

    # Reads the structural class off the last objectClass value, falling back
    # to top for an entry whose projection carries none.
    def _object_class(self, ldap_obj: Any) -> str:
        val: Any = ldap_obj.get('objectClass') if hasattr(ldap_obj, 'get') else None
        if not val:
            return 'top'
        last: Any = val[-1] if hasattr(val, '__getitem__') and len(val) > 0 else val
        if isinstance(last, bytes):
            return last.decode('utf-8', errors='replace')
        return str(last) if last is not None else 'top'

    # Decodes the entry's objectGUID into its string form, empty when absent.
    def _guid_of(self, ldap_obj: Any) -> str:
        raw: Any = ldap_obj.get('objectGUID') if hasattr(ldap_obj, 'get') else None
        if raw is not None and not isinstance(raw, (str, bytes)):
            raw = raw[0] if hasattr(raw, '__getitem__') and len(raw) > 0 else raw
        if isinstance(raw, bytes) and len(raw) == 16:
            return str(uuid.UUID(bytes_le=raw))
        return ''

    # Renders the PullResponse: the batch, then either the context to continue
    # from or the end-of-sequence marker that says there is no more. The batch
    # is drawn by the caller, so this reads the context only for what it says
    # about the batch that was just taken out of it.
    def _build_pull_response(
        self,
        context: RequestContext,
        enum_context: EnumerationContext,
        results_batch: List[Any],
    ) -> str:
        is_end: bool = enum_context.is_end_of_sequence
        self.logger.info(f"[PULL] Returning {len(results_batch)} objects (end: {is_end})")
        items_xml = ''.join(self._render_object_xml(o) for o in results_batch)
        items = f'<wsen:Items>{items_xml}</wsen:Items>' if items_xml else '<wsen:Items/>'
        continuation = '<wsen:EndOfSequence/>' if is_end else (
            '<wsen:EnumerationContext>'
            f'{html.escape(enum_context.context_id)}</wsen:EnumerationContext>'
        )
        return PULL_RESPONSE_TEMPLATE.format(
            relates_to=html.escape(context.message_id),
            payload=f'{items}{continuation}',
        )
