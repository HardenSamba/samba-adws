"""Restore of a deleted object (AD Recycle Bin) asked for by a WS-Transfer Put."""
from typing import Any, Dict, List, Optional

import ldb

from classes.directory.ldap_attr_builder import LdapAttrBuilder
from classes.faults.exceptions import ADWSDataException, ADWSObjectNotFoundException
from classes.parsing.controls_parser import VISIBILITY_CONTROLS

RENAME_KEYS = ("relativedistinguishedname", "container-hierarchy-parent")
UNDELETE_KEYS = frozenset(RENAME_KEYS + ("isdeleted", "distinguishedname"))
KNOWN_ATTRS = ["msDS-LastKnownRDN", "lastKnownParent", "isDeleted"]
SHOW_DELETED = "show_deleted:1"


# Turns a Put removing isDeleted into the single LDAP modify of an undelete.
class UndeleteRequest:

    # Keeps the directory and the visibility controls the modify needs.
    def __init__(self, samdb: Any, client_controls: Optional[List[str]]) -> None:
        self.samdb = samdb
        self.controls: List[str] = [
            c for c in client_controls or [] if c.split(":", 1)[0] in VISIBILITY_CONTROLS
        ]
        if not any(c.startswith("show_deleted:") for c in self.controls):
            self.controls.append(SHOW_DELETED)

    # Tells whether the changes of a Put ask to restore a deleted object.
    @staticmethod
    def is_undelete(entries: List[Dict[str, Any]]) -> bool:
        return any(
            e["name"].lower() == "isdeleted" and e.get("operation") in ("delete", "remove")
            for e in entries
        )

    # Restores the deleted object and returns the DN it was restored under.
    def restore(self, dn: str, entries: List[Dict[str, Any]]) -> str:
        found: Any = self.samdb.search(
            base=dn, scope=ldb.SCOPE_BASE, attrs=KNOWN_ATTRS, controls=self.controls
        )
        if len(found) != 1:
            raise ADWSObjectNotFoundException(f"Deleted object not found: {dn}")
        if "isDeleted" not in found[0]:
            raise ADWSDataException(f"Not a deleted object: {dn}")
        target = self._target_dn(found[0], entries)
        self.samdb.modify(self._message(found[0].dn, target, entries), self.controls)
        return target

    # The DN asked for (distinguishedName, new RDN or parent), else the last known one.
    def _target_dn(self, found: Any, entries: List[Dict[str, Any]]) -> str:
        asked: Dict[str, str] = {
            e["name"].lower(): str(e["values"][0]) for e in entries if e.get("values")
        }
        known: Dict[str, str] = {a: str(found[a]) for a in KNOWN_ATTRS if a in found}
        if "distinguishedname" in asked:
            return asked["distinguishedname"]
        parent = asked.get(RENAME_KEYS[1]) or known.get("lastKnownParent")
        if not parent:
            raise ADWSDataException(f"No parent to restore {found.dn} under")
        if RENAME_KEYS[0] in asked:
            return f"{asked[RENAME_KEYS[0]]},{parent}"
        rdn_name: str = found.dn.get_rdn_name()
        rdn_value = known.get("msDS-LastKnownRDN") or found.dn.get_rdn_value().split("\n")[0]
        target = ldb.Dn(self.samdb, f"{rdn_name}=x,{parent}")
        target.set_component(0, rdn_name, rdn_value)
        return str(target)

    # Builds the modify: isDeleted removed, the new DN set, the other changes kept.
    def _message(self, dn: Any, target: str, entries: List[Dict[str, Any]]) -> Any:
        others = [e for e in entries if e["name"].lower() not in UNDELETE_KEYS]
        msg = LdapAttrBuilder.build_message(self.samdb, str(dn), others)
        msg["isDeleted"] = ldb.MessageElement([], ldb.FLAG_MOD_DELETE, "isDeleted")
        msg["distinguishedName"] = ldb.MessageElement(
            [target.encode("utf-8")], ldb.FLAG_MOD_REPLACE, "distinguishedName"
        )
        return msg
