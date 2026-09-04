"""Group membership on the supported client: one member per call, as a delta.

`ADWSMembershipClient` extends `ADWSWriteClient` with the two verbs `#21` asked
for, so a consumer holds one object that creates, changes, moves and deletes
objects and edits the groups they belong to. It is its own class because the
project's norms allow five functions per file and `write_client.py` already has
them; that is a fact about the file, not a suggestion that membership is a
different kind of write.

**These are not `modify`.** `modify(group, {"member": [...]})` replaces the
whole list from what the caller read a moment ago, and loses whatever another
administrator added in between. `_member_request` says why at length. These
send a delta the directory applies to one value.

**A redundant call is a refusal, not a no-op.** Measured against a Samba 4.17
directory rather than assumed, and there are three sentences, not two:

- adding a member the group already has: `LDB_ERR_ENTRY_ALREADY_EXISTS`,
  *Attribute member already exists for target GUID …*
- removing a member the group never had: `LDB_ERR_NO_SUCH_ATTRIBUTE`,
  *No such attribute during LDB_MODIFY*
- removing a former member a second time: `LDB_ERR_UNWILLING_TO_PERFORM`,
  *Attribute member already deleted for target GUID …* — the first removal
  leaves a linked-attribute tombstone rather than nothing.

`ModifyHandler` turns all three into a fault whose `da:ShortError` is
`ModifyFailed`, so they arrive here as an `ADWSClientError` with that code, the
group as `.target`, and the directory's sentence as the message. The code alone
cannot tell them from any other refused modify; the sentence can. A caller that
wants a no-op reads the list first; the console's members dialog already does,
and asks here only for the change.
"""

from src.soap.namespaces import WST

from samba_adws._codec import decode_xml, encode_xml
from samba_adws._member_request import ADD, REMOVE, Membership, build_member_request
from samba_adws._validation import validate_identity
from samba_adws._write_response import parse_write_response
from samba_adws.write_client import ADWSWriteClient

# Byte-identical to the REPLY_ACTION `ModifyHandler` declares: a membership
# change is a Put, and only a PutResponse acknowledges one.
_PUT_RESPONSE = f"{WST}/PutResponse"


# Adds the membership verbs to the supported write client.
class ADWSMembershipClient(ADWSWriteClient):

    # Adds one member to one group. Both are distinguished names.
    def add_member(self, group: str, member: str) -> None:
        self._change_member(group, member, ADD)

    # Removes one member from one group. Both are distinguished names.
    def remove_member(self, group: str, member: str) -> None:
        self._change_member(group, member, REMOVE)

    # Sends the one Put both verbs are, and reads its acknowledgement.
    #
    # Faults are re-raised with the group as the target: a refusal names the
    # object whose membership did not change, which is what a caller renders.
    def _change_member(self, group: str, member: str, operation: str) -> None:
        validate_identity(group)
        validate_identity(member)
        request, message_id = build_member_request(
            self.server, self.port, Membership(group, member), operation)
        response = self._exchange(encode_xml(request), group)
        parse_write_response(decode_xml(response), message_id, group, _PUT_RESPONSE)
