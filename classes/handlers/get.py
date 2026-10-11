"""Get handler - Get/Retrieve AD objects and Root DSE with proper XML structure"""
import re
import uuid
from typing import Any, Dict, List, Optional

import ldb

from classes.handlers.base import BaseHandler
from classes.parsing.context import RequestContext
from classes.parsing.controls_parser import ControlsParser

# RootDSE attributes Samba returns that real AD does NOT expose. The Windows
# AD client looks attribute names up in its hardcoded RootDSE syntax table
# without TryGetValue, so an unknown key (e.g. vendorName) raises
# KeyNotFoundException on the client and breaks every cmdlet at connect time.
_ROOTDSE_DROP = frozenset((
    "vendorname", "vendorversion",
))


class GetHandler(BaseHandler):
    """Handles Get/Retrieve requests including Root DSE

    Key Design:
    - Attributes rendered with addata: prefix (e.g., <addata:name>)
    - NO ObjectClass wrapper - attributes go DIRECTLY in <ad:PartialAttribute>
    - ldb.MessageElement properly decoded to UTF-8 or Base64
    - 100% minified XML (zero whitespace)
    """

    def __init__(self, logger: Any, session_info: Optional[Any] = None) -> None:
        super().__init__(logger, session_info)

    def handle(self, context: RequestContext) -> str:
        """Route request to Root DSE or object handler"""
        self.log_request(context)

        obj_ref = context.object_reference

        if (not obj_ref or
                obj_ref.lower() == 'root dse' or
                obj_ref == '' or
                obj_ref.lower() == '11111111-1111-1111-1111-111111111111'):
            return self._get_root_dse(context)

        return self._get_object(context)

    def _prepare_attributes(
        self,
        attributes: Dict[str, Any],
        context: RequestContext,
        is_root_dse: bool = False,
    ) -> Dict[str, Any]:
        """Prepare attributes: add synthetics, filter if requested

        Returns filtered/enriched attributes dict
        """
        attrs = dict(attributes)

        if is_root_dse:
            for key in [k for k in attrs if k.lower() in _ROOTDSE_DROP]:
                del attrs[key]
            if 'msDS-PortLDAP' not in attrs:
                attrs['msDS-PortLDAP'] = '389'
            if 'msDS-PortSSL' not in attrs:
                attrs['msDS-PortSSL'] = '636'

        if context.requested_attributes:
            filtered: Dict[str, Any] = {}
            requested_lower = {name.lower(): name for name in context.requested_attributes}

            for key, value in attrs.items():
                if key.lower() in requested_lower:
                    filtered[key] = value

            return filtered

        return attrs

    def _get_object_class(self, obj_dict: Dict[str, Any]) -> str:
        """Extract the most specific objectClass from object

        Returns the last (most specific) objectClass value, or 'top' as default.
        Handles ldb.MessageElement and regular lists.
        """
        if 'objectClass' in obj_dict:
            obj_classes = obj_dict['objectClass']

            if hasattr(obj_classes, '__iter__') and not isinstance(obj_classes, (str, bytes)):
                obj_class_list: List[Any] = list(obj_classes)
            else:
                obj_class_list = [obj_classes] if obj_classes else []

            if obj_class_list:
                last_class = obj_class_list[-1]

                if isinstance(last_class, bytes):
                    return last_class.decode('utf-8')
                return str(last_class)

        return 'top'

    @staticmethod
    def _wrap_imda_object(obj_xml: str) -> str:
        """IMDA form (b): whole object inside a single <da:PartialAttribute>."""
        return (
            '<da:BaseObjectSearchResponse><da:PartialAttribute>'
            f'{obj_xml}</da:PartialAttribute></da:BaseObjectSearchResponse>'
        )

    def _get_root_dse(self, context: RequestContext) -> str:
        """Retrieve Root DSE with format-aware GetResponse

        For WS-Transfer requests: <addata:top> with objectReferenceProperty + attributes
        For IMDA requests: <da:BaseObjectSearchResponse> with PartialAttribute elements

        All namespaces declared at <s:Envelope> root level (SOAP 1.2 compliant)
        """
        try:
            search_expr = "(objectClass=*)"
            controls = ["sd_flags:1:0"]

            objs = self.db.db.search(
                base="",
                scope=ldb.SCOPE_BASE,
                expression=search_expr,
                attrs=["*"],
                controls=controls
            )

            if not objs or len(objs) == 0:
                return self.build_soap_fault(context, "Root DSE not found")

            root_dse = dict(objs[0])

            attributes: Dict[str, Any] = {}
            for key, value in root_dse.items():
                if key.lower() not in ('dn', 'dn_parsed', 'objectclass'):
                    attributes[key] = value

            attributes = self._prepare_attributes(attributes, context, is_root_dse=True)

            attributes_xml = self.renderer.render_attributes(
                attributes, wrap_partial=context.is_imda
            )

            if context.is_imda:
                body_xml = (
                    f'<da:BaseObjectSearchResponse>'
                    f'{attributes_xml}'
                    f'</da:BaseObjectSearchResponse>'
                )
            else:
                ref_prop_xml = (
                    '<ad:objectReferenceProperty>'
                    '<ad:value xsi:type="xsd:string">'
                    '11111111-1111-1111-1111-111111111111'
                    '</ad:value>'
                    '</ad:objectReferenceProperty>'
                )
                body_xml = (
                    f'<addata:top>'
                    f'{ref_prop_xml}'
                    f'{attributes_xml}'
                    f'</addata:top>'
                )

            response = (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<s:Envelope '
                'xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
                'xmlns:a="http://www.w3.org/2005/08/addressing" '
                'xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory" '
                'xmlns:addata="http://schemas.microsoft.com/2008/1/ActiveDirectory/Data" '
                'xmlns:da="http://schemas.microsoft.com/2006/11/'
                'IdentityManagement/DirectoryAccess" '
                'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                'xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
                '<s:Header>'
                '<a:Action s:mustUnderstand="1">'
                'http://schemas.xmlsoap.org/ws/2004/09/transfer/GetResponse'
                '</a:Action>'
                f'<a:RelatesTo>{context.message_id}</a:RelatesTo>'
                '</s:Header>'
                '<s:Body>'
                f'{body_xml}'
                '</s:Body>'
                '</s:Envelope>'
            )

            response = re.sub(r'>\s+<', '><', response)

            return response

        except Exception as e:
            self.logger.error(f"Error getting Root DSE: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return self.build_soap_fault(context, str(e))

    def _get_object(self, context: RequestContext) -> str:
        """Retrieve a regular AD object with format-aware GetResponse

        For WS-Transfer requests: <addata:{objectClass}> with objectReferenceProperty + attributes
        For IMDA requests: <da:BaseObjectSearchResponse> with PartialAttribute elements

        All namespaces declared at <s:Envelope> root level (SOAP 1.2 compliant)
        """
        try:
            obj_ref = context.object_reference

            dns_to_try: List[str] = [obj_ref] if obj_ref else []

            if hasattr(self, 'naming_context') and self.naming_context:
                dns_to_try.append(f"{obj_ref},{self.naming_context}")

            obj: Optional[Dict[str, Any]] = None
            for dn in dns_to_try:
                try:
                    search_expr = "(objectClass=*)"
                    controls = ControlsParser.for_object_read(context.ldap_controls)

                    from classes.serialization.constructed_attrs import ConstructedAttrs
                    base_attrs: List[str] = ['*']
                    if context.requested_attributes:
                        base_attrs = base_attrs + context.requested_attributes
                    attrs_to_fetch = ConstructedAttrs.expand(base_attrs)

                    objs = self.db.db.search(
                        base=dn,
                        scope=ldb.SCOPE_BASE,
                        expression=search_expr,
                        attrs=attrs_to_fetch,
                        controls=controls
                    )

                    if objs and len(objs) > 0:
                        obj = dict(objs[0])
                        break
                except Exception as e_dn:
                    self.logger.debug(f"Failed to search DN {dn}: {e_dn}")
                    continue

            if obj is None:
                return self.build_soap_fault(context, f"Object not found: {obj_ref}")

            attributes2: Dict[str, Any] = {}
            for key, value in obj.items():
                if key.lower() not in ('dn', 'dn_parsed'):
                    attributes2[key] = value

            attributes2 = self._prepare_attributes(attributes2, context, is_root_dse=False)

            obj_class = self._get_object_class(obj)

            dn = obj_ref or ''
            dn_raw: Any = obj.get('dn')
            if dn_raw is not None:
                if dn_raw.__class__.__name__ == 'MessageElement':
                    dn_raw = dn_raw[0] if len(dn_raw) > 0 else None
                if isinstance(dn_raw, bytes):
                    dn_raw = dn_raw.decode('utf-8')
                if dn_raw:
                    dn = str(dn_raw)

            guid = obj_ref or ''
            guid_raw: Any = obj.get('objectGUID')
            if guid_raw is not None:
                if hasattr(guid_raw, '__iter__') and not isinstance(guid_raw, (str, bytes)):
                    guid_raw = guid_raw[0] if len(guid_raw) > 0 else None
                if isinstance(guid_raw, bytes) and len(guid_raw) == 16:
                    guid = str(uuid.UUID(bytes_le=guid_raw))

            if context.is_imda and context.requested_attributes:
                body_xml = self.serializer.imda_projection(attributes2, dn)
            else:
                obj_xml = self.serializer.whole_object(attributes2, obj_class, guid, dn)
                body_xml = self._wrap_imda_object(obj_xml) if context.is_imda else obj_xml

            response = (
                '<?xml version="1.0" encoding="utf-8"?>'
                '<s:Envelope '
                'xmlns:s="http://www.w3.org/2003/05/soap-envelope" '
                'xmlns:a="http://www.w3.org/2005/08/addressing" '
                'xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory" '
                'xmlns:addata="http://schemas.microsoft.com/2008/1/ActiveDirectory/Data" '
                'xmlns:da="http://schemas.microsoft.com/2006/11/'
                'IdentityManagement/DirectoryAccess" '
                'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" '
                'xmlns:xsd="http://www.w3.org/2001/XMLSchema">'
                '<s:Header>'
                '<a:Action s:mustUnderstand="1">'
                'http://schemas.xmlsoap.org/ws/2004/09/transfer/GetResponse'
                '</a:Action>'
                f'<a:RelatesTo>{context.message_id}</a:RelatesTo>'
                '</s:Header>'
                '<s:Body>'
                f'{body_xml}'
                '</s:Body>'
                '</s:Envelope>'
            )

            response = re.sub(r'>\s+<', '><', response)

            return response

        except Exception as e:
            self.logger.error(f"Error getting object {context.object_reference}: {e}")
            import traceback
            self.logger.error(traceback.format_exc())
            return self.build_soap_fault(context, str(e))
