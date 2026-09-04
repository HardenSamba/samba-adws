# Supported Linux client API

The `samba_adws` package is the supported Python boundary for Linux callers that
need ADWS. It reuses this repository's NMF, WCF binary XML, and initiating GSSAPI
implementation; callers do not need to copy any wire-protocol code.

## Requirements

- Python 3.11 or newer.
- MIT Kerberos configured for the target domain.
- `python3-gssapi` on Debian/Ubuntu, or the equivalent `gssapi` Python package.
- A valid ticket in the caller's credential cache (`kinit <user>`).
- TCP access to the domain controller's port 9389.

The client does **not** import or require `python3-samba`, `ldb`, `SamDB`, a
machine keytab, or a password argument. Use the domain controller's FQDN so
GSSAPI can request its `host/<fqdn>` service principal.

Authentication and authorization are now bound.
[Issue #8](https://github.com/HardenSamba/samba-adws/issues/8) removed the SYSTEM
session: the server opens each request-time `SamDB` under the session the GSSAPI
handshake authenticated, and refuses the connection if no session was negotiated
rather than falling back to SYSTEM. **Writes are enforced as that principal** —
Samba's local `acl` module denies a create, modify, delete, rename or password
reset the caller has no directory right to.
`tests/dc/test_session_authorization.py` asserts that against a real directory:
the same modification of the same object is denied as an unprivileged principal
and allowed as SYSTEM. It asserts that the write is refused, not which error text
Samba returns, and it is skipped wherever no DC is provisioned.

One authorization gap remains, tracked by
[issue #17](https://github.com/HardenSamba/samba-adws/issues/17): **reads are not
attribute-filtered**. Samba applies read-side ACL filtering (`acl_read`) in its
LDAP frontend, not on a directly opened local `SamDB`, so a caller can read
attributes their ACLs would hide over LDAP. Reads run as the caller (never
SYSTEM), but do not yet enforce per-attribute read rights; treat read output as
if the caller could read anything the directory returns to a local process.

Until Debian packaging is delivered by issue #6, run the client from a source
checkout. The workstation dependency still comes only from Debian:

```bash
sudo apt install python3-gssapi
cd /path/to/samba-adws
PYTHONPATH="$PWD" python3 your-client.py
```

Do not install this source tree with pip: its legacy top-level `src` and
`classes` packages need the layout decision and Debian work tracked by issue
#6. The supported API namespace is stable, but system installation is not yet
claimed by this ticket. The existing DC source-install workflow and its
apt-managed dependencies remain unchanged. `MODULE.yaml` therefore continues
to describe the server/DC installation; issue #6 owns the client package and
workstation manifest decision.

## Public API

```python
from samba_adws.client import ADWSClient, ADWSClientError

client = ADWSClient("dc1.samdom.example.com", port=9389, timeout=30.0)

try:
    user = client.get_by_dn(
        "CN=demo,CN=Users,DC=samdom,DC=example,DC=com",
        ("sAMAccountName", "objectGUID", "memberOf"),
    )
except ADWSClientError as error:
    print(error.code, error.category, error.target, str(error))
else:
    print(user["sAMAccountName"])
```

The stable signatures are:

```python
ADWSClient(server: str, port: int = 9389, timeout: float = 30.0)
get_by_dn(identity: str, properties: Sequence[str] = ()) -> Mapping[str, object]
naming_context(kind: str = "defaultNamingContext") -> str
```

`identity` is a distinguished name. An empty property sequence requests the
whole WS-Transfer object; a non-empty sequence requests an IMDA projection.
Single text values are returned as `str`, `xsd:base64Binary` values as `bytes`,
and multi-valued attributes as tuples. Every failure crosses the API as
`ADWSClientError`, whose `code`, `category`, and `target` fields are suitable
for command-line or PowerShell error translation.

`naming_context` is the one call that needs no distinguished name: it fetches
the RootDSE — the object the server answers for the reserved reference
`11111111-1111-1111-1111-111111111111` — and returns the attribute named by
`kind`, `defaultNamingContext` by default. That value is what every other call
needs and no other call can supply: `get_by_dn` wants a DN, a search wants a
base, and a caller that has just been told a controller's name has neither. A
RootDSE that publishes no such attribute raises `ADWSClientError` with code
`MalformedResponse` rather than returning an empty base that would silently
search the whole forest root or nothing at all.

It returns **one** context, so `kind` must name an attribute that holds a
single distinguished name. The multi-valued `namingContexts` decodes to a tuple
and is refused with the same code and a message that says so — not reduced to
whichever value came first, which would hand a caller one context out of
several with no way to tell which, and not reported as unpublished, which would
blame a server that published it. Use `get_by_dn` on the RootDSE reference to
read every context at once.

Each operation creates a unique WS-Addressing `MessageID`. The response must
contain the same `RelatesTo`; missing or mismatched correlation, malformed WCF
or SOAP, and SOAP faults are rejected as typed errors. The configured timeout
applies to connection, authentication, reads, and writes.

## Supported surface

| Surface | Linux client status |
|---|---|
| Resource endpoint, WS-Transfer Get by DN | Supported |
| WS-Transfer Get of the RootDSE (one naming context) | Supported |
| Optional IMDA attribute projection | Supported |
| SOAP fault decoding | Supported |
| WS-Enumeration `Enumerate` and `Pull` | Supported |
| WS-Enumeration `Release` | Server-only |
| Create, Put, Delete, rename, SetPassword (`ADWSWriteClient`) | Supported |
| Schema and custom actions | Server-only |

The client currently accepts the static WCF dictionary emitted by this server.
It rejects a non-empty dynamic dictionary; the server does not negotiate or
emit one. Live acceptance still requires a Debian workstation with `kinit` and
a reachable Samba ADWS endpoint. Offline tests cover request encoding, response
decoding, faults, malformed responses, correlation, transport errors, and
import isolation:

```bash
python3 -m pytest -q tests
```

## Searching

`ADWSClient.get_by_dn` fetches one object whose distinguished name the caller
already knows. That is the wrong half for anything that draws a list: a console
never knows a distinguished name until it has listed something. `ADWSSearchClient`
extends it with the two WS-Enumeration messages the server has answered since
enumeration landed.

```python
from samba_adws import ADWSSearchClient, search_query

client = ADWSSearchClient("dc.example.test")
query = search_query(
    base="OU=Staff,OU=Paris,DC=example,DC=test",
    scope="OneLevel",
    ldap_filter="(objectClass=user)",
    properties=("sAMAccountName", "displayName", "whenChanged"),
)

for entry in client.search(query):
    print(entry["sAMAccountName"])
```

`search` is a generator: a container holding forty thousand accounts is the case
paging exists for, and gathering them all would undo it. A caller that wants one
screenful holds the cursor itself:

```python
context = client.open_search(query)
objects, context = client.pull(context, count=50)
# `context` is None when the server said the sequence ended.
```

**The cursor is opaque.** This client never parses one and never builds one. It
is the server's own position in a cached result set, which is what makes paging
a directory somebody else is writing to safe — an offset would skip a row every
time another administrator deletes one.

**The end of a sequence is `EndOfSequence`, never an empty batch.** A short page
is ordinary and an empty page in the middle is legal, so a client that inferred
the end from either would truncate a listing without saying so. A response
carrying neither `EndOfSequence` nor a context is refused rather than guessed
at: the two possible guesses fail in opposite directions and neither is
detectable afterwards.

### The scope is checked here, not widened there

`Base`, `OneLevel` and `Subtree` are what `EnumerateHandler` maps onto
`ldb.SCOPE_*`. Anything it does not recognise falls through to `Subtree`, the
widest of the three, so a caller who mistyped one level would silently search a
whole domain and get an answer that does not look wrong. `search_query` refuses
a scope outside the three before a socket is opened.

### A base may be a GUID as well as a distinguished name

A distinguished name is a **position**, not an identity.
`OU=Staff,OU=Paris,DC=example,DC=test` stops existing the moment somebody
renames `OU=Paris` or moves `OU=Staff` under another container, and every saved
view a console stored that way breaks silently. An `objectGUID` never changes,
which is why `hardensamba-webui` holds GUIDs and needs to hand one back as a
search base.

`search_query` therefore accepts three spellings of `base`, and so does
`samba-adws search --base`:

| Typed | Sent |
|---|---|
| `OU=Staff,DC=example,DC=test` | unchanged |
| `<GUID=6c8dd5f1-6b3c-4f1a-9d33-6b1f0a2e77aa>` | unchanged |
| `6c8dd5f1-…` or `{6c8dd5f1-…}` | `<GUID=6c8dd5f1-…>` |

Surrounding whitespace is trimmed from all three, because `search_query` is
what decides the text that goes on the wire and a pasted DN should not carry
spaces that a pasted GUID would have lost.

```python
query = search_query(base="<GUID=6c8dd5f1-6b3c-4f1a-9d33-6b1f0a2e77aa>",
                     scope="OneLevel")
```

`<GUID=…>` is LDAP's own extended-DN form, not something invented here.
Normalising a bare GUID guesses nothing: a bare GUID contains no `=` and can
therefore never have been a distinguished name. Anything that is neither is
passed through untouched — this boundary recognises a GUID, it does not judge a
DN. Active Directory's three-part extended DN,
`<GUID=…>;<SID=…>;OU=Staff,DC=example,DC=test`, is one of those: it already
carries a distinguished name, so it is passed on rather than rewritten.

A base that opens with `<GUID=` and does not carry a GUID is refused as
`InvalidArgument` before a socket is opened, for the same reason an unknown
scope is: a `Search failed` fault that travelled to a domain controller first
names neither the value nor the reason. A half-copied `{6c8dd5f1-…` — an
opening brace with no closing one — is not repaired into a GUID either; it is
not the shape a directory prints, so it is not read as one.

`ADWSClient.get_by_dn` is **not** covered by this. Its `identity` is still a
distinguished name; `classes/handlers/get.py` converts only the RootDSE
sentinel GUID and answers `Object not found` for any other, which
`tools/docgen/chapters/06-operations.md` records as a deliberate divergence
from the Microsoft server.

**What is proven, and what is not.** The client escapes the base once
(`samba_adws/_search_request.py`, inside `<adlq:BaseObject>`), the WCF text
record escapes it again (`src/wcf/records/text.py`), and the server's own
parser reads back the exact string `<GUID=…>`
(`classes/parsing/context_enumeration.py`). `tests/test_client_search.py` and
`tests/test_cli.py` assert that round trip on the bytes the client really
builds, so **transport of a GUID base is verified offline**. `EnumerateHandler`
then hands `base_dn` to `SamDB.search(base=…)` with no DN parsing of its own
(`classes/handlers/enumerate.py`).

**Resolution of the extended base is Samba's `ldb`, and this repository has not
observed it.** No test here can: `classes/handlers/enumerate.py` imports `ldb`,
which is absent from a workstation, and no capture in `tools/test/` exercises a
GUID identity. That `<GUID=…>` is LDB syntax is corroborated in-repo by
`tools/docgen/chapters/06-operations.md`, which says the Get handler declines to
use it — evidence the form exists, not evidence it resolves as a search base.
Treat "the DC accepts a GUID base" as a **deduction pending a live check**
against a domain controller, not as an observed fact. That the client accepts,
normalises and transmits one is observed.

**The fallback needs no extended-DN support at all**, and it is also how a
console turns a GUID into a DN the first time it sees one:

```bash
samba-adws search --server dc1.samdom.example.com \
  --base "DC=samdom,DC=example,DC=com" --scope Subtree \
  --filter "(objectGUID=6c8dd5f1-6b3c-4f1a-9d33-6b1f0a2e77aa)" \
  --properties distinguishedName
```

`FilterParser` passes that assertion through unchanged, and
`src/serialization/name_filters.py` already builds the identical filter for
`TranslateName`, so it is exercised by an existing server path. The client does
**not** fall back to it automatically, for the same reason it refuses an unknown
scope rather than widening it to `Subtree`: turning one caller's failed lookup
into a subtree search of the domain is a decision the caller has to make.
`samba_adws.is_guid_base` is exported so a consumer can tell which case it is
holding before it decides. It answers `True` exactly when `search_query` would
rewrite the base into `<GUID=…>`, malformed values included in the sense that
they answer `False`, so the branch it selects cannot raise the `InvalidArgument`
the predicate had just ruled out.

### The endpoint is `Windows/Enumeration`

The published WCF endpoint table gives that path for the `IEnumeration`
contract. This server does no demultiplexing by endpoint — it routes on the SOAP
action and answers whatever URI it is addressed with — so the distinction costs
nothing here and is the difference between working and not working against a
Microsoft server.

### What the tests can and cannot check offline

The **request** direction is checked against the server's own parser:
`classes/parsing/context_enumeration` imports nothing but ElementTree, so
`tests/test_client_search.py` feeds it the bytes the client actually builds and
asserts on what the server would have understood. A test that read the request
back with a parser written for the test would agree with itself.

The **response** direction is scripted, because `classes/handlers/pull.py`
imports `ldb` and cannot be loaded on a machine without Samba. One test reads
that file and checks the elements this client looks for are the elements it
writes. It is coarse, and it catches the rename that would otherwise be found by
an administrator looking at an empty screen.

## Write operations

`ADWSWriteClient` extends `ADWSClient` — it inherits `get_by_dn` and
`naming_context` and the same connection settings, and adds the five verbs that
change the directory. It is a sibling of `ADWSSearchClient`, not a subclass of
it, so it does not have `search`. The handlers behind these verbs have existed
since long before this client did; what was missing was a way for a Linux caller
to reach them without reimplementing the wire protocol. That is `#16`.

```python
from samba_adws import ADWSWriteClient, ADWSClientError

client = ADWSWriteClient("dc1.samdom.example.com")
guid = client.create("CN=demo", "CN=Users,DC=samdom,DC=example,DC=com",
                     {"objectClass": ["user"], "sAMAccountName": ["demo"]})
```

The stable signatures are:

```python
create(rdn: str, parent: str, attributes: Mapping[str, Sequence[str]]) -> str
modify(identity: str, changes: Mapping[str, Sequence[str]]) -> None
rename(identity: str, *, new_rdn: str = "", new_parent: str = "") -> None
delete(identity: str) -> None
set_password(identity: str, password: str) -> None
```

`ADWSMembershipClient` extends `ADWSWriteClient` with the two membership verbs,
so one object carries every write:

```python
add_member(group: str, member: str) -> None
remove_member(group: str, member: str) -> None
```

Both take distinguished names. See
[Group membership is a delta, never a replace](#group-membership-is-a-delta-never-a-replace)
for why they exist and what a redundant call answers.

**No distinguished name is ever composed or parsed on this side.** `create`
takes the relative name and the parent separately and sends them as the two
fields the server composes a name from; `rename` takes a new relative name and a
new parent the same way. Assembling a name here would be this client deciding
how a directory spells one — RFC 4514 escaping, quoted and multi-valued RDNs
included — and the server already owns that answer. A user named `Doe, Jane` is
the case that punishes the alternative.

`create` returns the `objectGUID` the directory reported, so a caller does not
have to issue a second read to learn the identifier it was just handed. Note
that the server answers the all-zero UUID
`00000000-0000-0000-0000-000000000000` when it created the object but could not
read the attribute back; that value means *created but not read back*, not
*failed*. A `CreateResponse` that names no object at all is refused as a
`ProtocolError` rather than returned as a success with an empty identifier.

`modify` takes a mapping because three attribute edits are **one** LDAP modify
in one transaction, where three calls would be three transactions that can
half-apply. An empty value sequence clears an attribute on `modify`, and is
refused on `create`, where an attribute named with nothing to put in it is a
mistake rather than an instruction.

`rename` sends only the half that changed: give `new_rdn` to rename in place,
`new_parent` to move, or both. The server keeps the object's current value for
whichever key is absent, so one signature covers rename, move, and both. They
are keyword-only because a bare second string is not self-evidently a name
rather than a container, and passing one for the other would silently move an
object instead of renaming it. Passing neither is refused, and so is a half that
is present but blank: absence is what tells the server to keep the value it has,
so `new_rdn="   "` is not an absence — it is an instruction to call the object
three spaces, and it is refused here rather than by the directory.

### Creating a usable account is three exchanges, in an order that matters

```python
guid = client.create("CN=demo", parent, {
    "objectClass": ["user"], "sAMAccountName": ["demo"],
    "userAccountControl": ["546"],          # NORMAL_ACCOUNT | ACCOUNTDISABLE
})
dn = f"CN=demo,{parent}"     # the caller's own two halves, put back together
client.set_password(dn, secret)
client.modify(dn, {"userAccountControl": ["512"]})   # NORMAL_ACCOUNT, enabled
```

That `dn` is composed here, a few lines after this document said no name is
composed on this side, so it is worth saying which claim holds. The claim is
about the **client**: nothing in `samba_adws` builds a name out of parts or takes
one apart, which is the work that would need an RFC 4514 parser. A caller putting
back together the two strings it has just passed to `create` is not parsing
anything. It does have to do that, because the other four verbs address an object
by distinguished name — `ModifyHandler` and `DeleteHandler` hand `identity`
straight to `ldb.Dn` — so the `objectGUID` that `create` returns is not accepted
where they expect a DN. The GUID is still worth returning: it is the identifier
that survives the rename described above, where the DN does not. It is something
to record, not something to pass back in here.

Create the account **disabled**, set the password, and only then clear the
disabled bit. A directory refuses to enable an account that has no password, so
the order is forced in one direction; the reason it is worth writing down is the
other direction. A failure at any step then leaves a *disabled* object, which is
inert. Enabling first and setting the password second leaves, on a failure at
step two, an enabled account with no password — which is the kind of half-made
thing nobody finds until it is used.

The orchestration of those three calls is `accounts.create_usable_account`,
which holds the order so the knowledge is enforced rather than remembered:

```python
from samba_adws import ADWSWriteClient, AccountLeftDisabled, Placement, create_usable_account

client = ADWSWriteClient("dc1.samdom.example.com")
try:
    account = create_usable_account(
        client, Placement("CN=demo", parent),
        {"objectClass": ["user"], "sAMAccountName": ["demo"]}, secret)
except AccountLeftDisabled as left:
    # The object exists, disabled. left.account.reached says how far it got:
    # "created" (no password yet) or "password-set" (the enable was refused).
    ...
# account.dn, account.guid, account.reached == "usable"
```

`userAccountControl` is the sequence's to set at both ends — `546` going in,
`512` coming out — and a caller that supplies it is refused before anything is
sent, rather than overridden in silence. The password is checked before the
create for the same reason: a refusal after it would leave an account behind
for an input that could have been refused up front. A refusal *by the
directory* after the create — a password its policy rejects, an enable it will
not perform — raises `AccountLeftDisabled`, which carries the server's code and
reason unchanged, names the object as `.target`, and says in `.account.reached`
which step succeeded last. That is what lets a retry start from the password
rather than create a second object beside the first.

The relative name stays the caller's, verbatim, which is why `Placement` is the
same pair `create` takes. The `dn` above is composed in `accounts.py` — the one
place this package puts two halves back together — and the claim that survives
is the one that matters: it is a caller re-joining the two strings it passed,
not this package deciding how a directory spells a name.

`tests/test_accounts.py` reads the order off the recorded traffic with the
server's own parsers and checks both control values bit by bit against
constants written in the test. `tests/dc/test_accounts.py` asks a real
directory the two questions no script can answer: that a good password ends
with an enabled account, and that a refused one leaves a disabled one.

### An empty response body is a success

A WS-Transfer `PutResponse` and `DeleteResponse` each carry an **empty** SOAP
body, and each is an acknowledgement that the work was done — `ModifyHandler`
and `DeleteHandler` both answer with an empty body on success. A client that
required a non-empty body, as the read path rightly does, would report failure
for a rename or a delete the directory had already performed. `_write_response`
exists to hold that distinction, which is why the write path does not go through
`_envelope.read_body`.

Each response is also checked against the reply action its verb expects, so an
acknowledgement of some other operation cannot satisfy a delete.

### Group membership is a delta, never a replace

`modify(group, {"member": [...]})` is the wrong tool for a group, and the
difference is a lost update. `modify` sends a `Change` with no operation, which
the server applies as a replace of the whole attribute. Two administrators open
the same group; the first reads the list, appends Marie and writes it back; the
second, from the list read before Marie was added, appends Luc and writes it
back. Marie is gone, and nothing anywhere reports it — the second write simply
won. `member` is the attribute most likely to be edited by two people at once,
on a domain where group membership is how permission is granted.

`add_member` and `remove_member` send `Operation="add"` and
`Operation="delete"` instead, which is what `Add-ADGroupMember` and
`Remove-ADGroupMember` send and what `LdapAttrBuilder` maps to `FLAG_MOD_ADD`
and `FLAG_MOD_DELETE`. The directory applies the change to the one value named,
and two concurrent adds both land. `tests/test_member_request.py` asserts that
the server reads from this client, entry for entry, what it reads from the
cmdlet's recorded request.

One member per call, on purpose: it is how the directory models the edit, and it
is what lets a console mark one row busy while the others stay live.

**A redundant call is a refusal, not a no-op.** Measured against a Samba 4.17
directory, and there are three answers, not two:

| Call | The directory answers | Reason text |
|---|---|---|
| add a member the group already has | `LDB_ERR_ENTRY_ALREADY_EXISTS` | *Attribute member already exists for target GUID …* |
| remove a member the group never had | `LDB_ERR_NO_SUCH_ATTRIBUTE` | *No such attribute during LDB_MODIFY* |
| remove a former member a second time | `LDB_ERR_UNWILLING_TO_PERFORM` | *Attribute member already deleted for target GUID …* |

The third exists because a removal leaves a linked-attribute tombstone rather
than nothing, so the directory remembers the member it no longer has. A console
keying on one sentence for "not a member" would miss the other.

`ModifyHandler` carries all three as `ModifyFailed`, so they arrive as an
`ADWSClientError` with that code, the group as `.target`, and the directory's
sentence as the message. The code alone cannot tell them from any other refused
modify; the reason can. A caller that wants a no-op reads the membership first
and asks only for the change, which is what the console's members dialog does.
`tests/dc/test_membership_client.py` pins all three answers against a real
directory.

### What a refusal is called

`ADWSClientError.code` is the fault's SOAP subcode where there is one. On the
write path there usually is not: `FaultBuilder.directory_error` — which is what
`CreateHandler`, `ModifyHandler` and `DeleteHandler` all answer a failure with —
sets no subcode and puts its discriminator in the fault Detail instead, as
`da:ShortError`. That is read as the code, so a refused create arrives as
`CreateFailed`, a refused modify or rename as `ModifyFailed`, a delete as
`DeleteFailed`, and a request the handler could not even read as
`InvalidRequest`. Without it all four collapse to `SOAPFault` and the caller is
left parsing the reason text.

`set_password` is the exception that proves the rule: it faults through
`custom_action_fault`, which *does* set a subcode, and arrives as
`SetPasswordFault`. A subcode always wins over the Detail. A reason mentioning
"not found" is normalised to `ObjectNotFound` whichever of the two carried it,
and `.target` is the object the call named — including when the refusal happened
before the wire, as it does for an empty identity.

### Endpoints and what this server actually reads

`Create` is addressed to `Windows/ResourceFactory` and `SetPassword` to
`Windows/AccountManagement`; the rest go to `Windows/Resource`. That is what the
published WCF endpoint table gives for those contracts and what a Microsoft
server requires. This server routes on `<a:Action>` alone and never reads
`<a:To>`, so the distinction costs nothing here — with one exception:
`ResourceFactory` is the address this server *does* read, because `CreateHandler`
rewrites it into the `ResourceCreated` EPR it replies with.

Offline tests cover the request direction against the server's own parsers, and
the response direction over a scripted transport. `tests/dc/test_write_verbs.py`
drives all five verbs through the real handlers against a provisioned directory
and is skipped without one.

## The `samba-adws` command

`MODULE.yaml` has declared a command of that name since it was written, and
there was none. There is now, and it exists so that another module can reach
this one **without importing it**.

That is the ecosystem's rule rather than a preference: a module owns its
behaviour and its consumers render it, and a consumer that imported this
package would be holding this module's code in its own process — with
`python3-samba` underneath, which is not thread-safe and is why the server
forks rather than threads.

### Where a consumer starts: the top of the domain

`search` requires a `--base`, and until now nothing published one. A console
knows a controller's name and nothing else; it never holds a distinguished name
until it has listed something, and it cannot list anything until it knows which
container to list. So the first call is:

```bash
samba-adws naming-context --server dc.example.test
```

```json
{"defaultNamingContext":"DC=example,DC=test"}
```

That value is exactly what `search --base` wants. The server has answered this
since the RootDSE branch of `GetHandler` was written — it is the object
`Get-ADRootDSE` reads — and no verb named it, which is why a working module
looked like one a console could not use. samba-adws#28.

**It is a verb of its own, not a field of `status`.** `status` promises a probe
that opens nothing: no base, no query, no credential, no socket. Reading a
naming context opens one, against a named controller, and fails for every
reason a directory read fails for. Folding it into `status` would make the one
call that must always answer depend on a domain being reachable — which is the
question `status` exists to answer without asking a domain.

**The key is the directory's own**, as the attributes of `search` are: the
RootDSE calls it `defaultNamingContext` and it leaves unchanged. `--format
text` renders it as `defaultNamingContext: DC=example,DC=test`, whole: a
listing trims a value that is longer than a line, because a page of objects is
a spot check, but this answer is the value the operator pastes into `--base`
and an ellipsised distinguished name only looks like one that can be used.

### Listing what is under it

```bash
samba-adws search --server dc.example.test     --base "OU=Staff,DC=example,DC=test"     --scope OneLevel     --filter "(objectClass=user)"     --properties sAMAccountName,displayName,whenChanged     --count 50
```

```json
{"objects":[{"sAMAccountName":"m.dupont","displayName":"Marie Dupont"}],"cursor":"ctx-2"}
```

**One page per invocation.** A command that ran a subtree search to completion
would hold a controller for as long as the domain is large and hand its caller
forty thousand objects at once. The caller pages by asking again with the
cursor it was given:

```bash
samba-adws search --server dc.example.test --base "..." --cursor ctx-2
```

An empty `cursor` is the end of the sequence. An empty `objects` is **not**: a
server may answer a short page, or an empty one, before its last.

**The attributes are the directory's own.** They arrive as the server named them
and leave unchanged. A consumer wanting different names would be asking this
command to hold its vocabulary, and there is more than one consumer.

### What a consumer can rely on

| | |
|---|---|
| Success | exit `0`, one JSON document on stdout, stderr empty |
| Failure | non-zero exit, the reason on stderr, **stdout empty** |
| Bad arguments | exit `2` from the parser, before anything is opened |

stdout is left empty on failure deliberately. A consumer that parsed it on a
non-zero status would be reading a shape this command does not promise, and one
that did not would find half a page.

### Read only, for now

`search` is the verb `hardensamba-webui#9` and `#20` were blocked on. The write
verbs exist on `ADWSWriteClient` and are not exposed here yet. The identity
question that held them up is answered: `#8` binds every request to the Kerberos
principal in the caller's credential cache, and the server enforces that
principal's write rights. What is left is the command surface itself, tracked by
`#16`.
