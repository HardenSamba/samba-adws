import html
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

import ldb

from classes.parsing.body_parser import BodyParser
from classes.parsing.context import RequestContext
from classes.directory.ldap_attr_builder import LdapAttrBuilder
from src.soap.namespaces import WST
from classes.handlers.base import BaseHandler


# Handles the WS-Transfer Create action: adds the object, returns its EPR reply.
class CreateHandler(BaseHandler):

    REPLY_ACTION = f"{WST}/CreateResponse"

    # ADWS routing attributes that locate the object but are not LDAP attributes:
    # the client sends the target as relativeDistinguishedName + the parent DN
    # (container-hierarchy-parent), never a full distinguishedName.
    DN_ROUTING = frozenset((
        "distinguishedname", "relativedistinguishedname", "container-hierarchy-parent",
    ))

    # Parses the request, adds the object to the directory, returns the EPR reply.
    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        try:
            dn, entries = self._extract(context)
            msg = LdapAttrBuilder.build_message(
                self.db.db, dn, entries, default_flag=ldb.FLAG_MOD_ADD
            )
            self.db.db.add(msg)
            self.logger.info(f"[CREATE] Created object {dn}")
            return self._success(context, dn, self._object_guid(dn))
        except Exception as e:
            self.logger.exception("[CREATE] failure")
            return str(self.faults.directory_error(context.message_id, str(e), "CreateFailed"))

    # Resolves the target DN and returns it with the cleaned LDAP attribute entries.
    def _extract(self, context: RequestContext) -> Tuple[str, List[Dict[str, Any]]]:
        parser = BodyParser(context.raw_xml or "")
        raw_entries: Optional[List[Dict[str, Any]]] = parser.find_add_request()
        entries: List[Dict[str, Any]] = raw_entries or []
        dn = self._resolve_dn(entries, context.object_reference)
        if not dn:
            raise ValueError("Cannot determine target DN for Create")
        cleaned = [e for e in entries if e["name"].lower() not in self.DN_ROUTING]
        return dn, cleaned

    # Builds the DN from relativeDistinguishedName + container-hierarchy-parent.
    @staticmethod
    def _resolve_dn(entries: List[Dict[str, Any]], fallback: Optional[str]) -> Optional[str]:
        by_name: Dict[str, str] = {}
        for entry in entries:
            if entry["values"]:
                by_name[entry["name"].lower()] = str(entry["values"][0])
        if by_name.get("distinguishedname"):
            return by_name["distinguishedname"]
        rdn = by_name.get("relativedistinguishedname")
        parent = by_name.get("container-hierarchy-parent") or fallback
        return f"{rdn},{parent}" if rdn and parent else fallback

    # Reads the freshly created object's GUID for the response EPR.
    def _object_guid(self, dn: str) -> str:
        res = self.db.db.search(base=dn, scope=ldb.SCOPE_BASE, attrs=["objectGUID"])
        if not res or "objectGUID" not in res[0]:
            return str(uuid.UUID(int=0))
        return str(uuid.UUID(bytes_le=bytes(res[0]["objectGUID"][0])))

    # Builds the WS-Addressing ResourceCreated EPR reply (wsa Address + refparams).
    def _success(self, context: RequestContext, dn: str, guid: str) -> str:
        match = re.search(r"<a:To[^>]*>([^<]+)</a:To>", context.raw_xml or "")
        address = (match.group(1).replace("ResourceFactory", "Resource")
                   if match else "http://www.w3.org/2005/08/addressing/anonymous")
        body = (
            '<wst:ResourceCreated '
            'xmlns:wst="http://schemas.xmlsoap.org/ws/2004/09/transfer" '
            'xmlns:wsa="http://www.w3.org/2005/08/addressing" '
            'xmlns:ad="http://schemas.microsoft.com/2008/1/ActiveDirectory">'
            f'<wsa:Address>{html.escape(address)}</wsa:Address>'
            '<wsa:ReferenceParameters>'
            f'<ad:objectReferenceProperty>{guid}</ad:objectReferenceProperty>'
            '<ad:instance>ldap:389</ad:instance>'
            '</wsa:ReferenceParameters>'
            '</wst:ResourceCreated>'
        )
        return str(self.envelope.wrap(self.REPLY_ACTION, context.message_id, body))
