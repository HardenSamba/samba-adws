from typing import Any, Dict, List, Optional, Tuple

import ldb

from classes.parsing.body_parser import BodyParser
from classes.parsing.context import RequestContext
from classes.directory.ldap_attr_builder import LdapAttrBuilder
from src.soap.namespaces import WST
from classes.handlers.base import BaseHandler

# A Put changing these expresses a rename/move (modrdn), not an attribute edit.
_RENAME_KEYS = ("relativedistinguishedname", "container-hierarchy-parent")


# Handles WS-Transfer Put: object renames/moves plus ordinary attribute modifies.
class ModifyHandler(BaseHandler):

    REPLY_ACTION = f"{WST}/PutResponse"

    # Applies any rename/move first, then the remaining attribute changes.
    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        dn = context.object_reference
        if not dn:
            return str(self.faults.directory_error(
                context.message_id, "Missing target DN", "InvalidRequest"
            ))
        try:
            dn, attrs = self._apply_rename(dn, self._read_entries(context))
            self._modify_attrs(dn, attrs)
            return self._success(context)
        except Exception as e:
            self.logger.exception("[MODIFY] failure")
            return str(
                self.faults.directory_error(context.message_id, str(e), "ModifyFailed")
            )

    # Parses the ModifyRequest (or AddRequest) into attribute change entries.
    @staticmethod
    def _read_entries(context: RequestContext) -> List[Dict[str, Any]]:
        parser = BodyParser(context.raw_xml or "")
        entries: Optional[List[Dict[str, Any]]] = parser.find_modify_request()
        if entries is None:
            entries = parser.find_add_request() or []
        return entries

    # Renames/moves the object when RDN/parent change; returns (dn, other attrs).
    def _apply_rename(self, dn: str,
                      entries: List[Dict[str, Any]]) -> Tuple[str, List[Dict[str, Any]]]:
        moves = {e["name"].lower(): str(e["values"][0]) for e in entries
                 if e["values"] and e["name"].lower() in _RENAME_KEYS}
        attrs = [e for e in entries if e["name"].lower() not in _RENAME_KEYS]
        if not moves:
            return dn, attrs
        parsed = ldb.Dn(self.db.db, dn)
        rdn = moves.get(_RENAME_KEYS[0]) or f"{parsed.get_rdn_name()}={parsed.get_rdn_value()}"
        parent = moves.get(_RENAME_KEYS[1]) or str(parsed.parent())
        new_dn = ldb.Dn(self.db.db, f"{rdn},{parent}")
        self.db.db.rename(parsed, new_dn)
        self.logger.info(f"[MODIFY] Renamed {dn} -> {new_dn}")
        return str(new_dn), attrs

    # Applies the remaining attribute changes as an LDB replace, if any.
    def _modify_attrs(self, dn: str, attrs: List[Dict[str, Any]]) -> None:
        if not attrs:
            return
        msg = LdapAttrBuilder.build_message(
            self.db.db, dn, attrs, default_flag=ldb.FLAG_MOD_REPLACE
        )
        self.db.db.modify(msg)
        self.logger.info(f"[MODIFY] Modified {dn} ({len(attrs)} attrs)")

    # Wraps the empty PutResponse body in a SOAP envelope.
    def _success(self, context: RequestContext) -> str:
        return str(self.envelope.wrap(self.REPLY_ACTION, context.message_id, ""))
