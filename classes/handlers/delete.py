from typing import List

import ldb
from src.soap.namespaces import WST

from classes.handlers.base import BaseHandler
from classes.parsing.context import RequestContext

# LDAP_SERVER_TREE_DELETE_OID — sent by Remove-AD* -Recursive to drop subtrees.
_TREE_DELETE_OID = "1.2.840.113556.1.4.805"


# Handles the WS-Transfer Delete action, including recursive subtree deletes.
class DeleteHandler(BaseHandler):

    REPLY_ACTION = f"{WST}/DeleteResponse"

    # Deletes the target object, honouring the tree-delete control when present.
    def handle(self, context: RequestContext) -> str:
        self.log_request(context)
        dn = context.object_reference
        if not dn:
            return str(
                self.faults.directory_error(
                    context.message_id, "Missing target DN", "InvalidRequest"
                )
            )
        try:
            controls = self._controls(context)
            self.db.db.delete(ldb.Dn(self.db.db, dn), controls)
            self.logger.info(f"[DELETE] Deleted {dn} (recursive={bool(controls)})")
            return str(self.envelope.wrap(self.REPLY_ACTION, context.message_id, ""))
        except Exception as e:
            self.logger.exception("[DELETE] failure")
            return str(
                self.faults.directory_error(context.message_id, str(e), "DeleteFailed")
            )

    # Returns the ldb tree-delete control when the request asked for recursion.
    @staticmethod
    def _controls(context: RequestContext) -> List[str]:
        if context.raw_xml and _TREE_DELETE_OID in context.raw_xml:
            return ["tree_delete:1"]
        return []
