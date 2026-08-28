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

Authentication and authorization are separate. The current server authenticates
the Kerberos principal but still opens its request-time `SamDB` with a SYSTEM
session. [Issue #8](https://github.com/HardenSamba/samba-adws/issues/8) tracks
binding the accepted GSSAPI identity to Samba's ACL evaluation. Until it is
fixed and proven live, this source client is a read-only integration preview:
an unprivileged-user test proves authentication, not enforcement of that user's
directory rights. Do not expose the service to untrusted domain principals or
build write clients on this boundary.

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
```

`identity` is a distinguished name. An empty property sequence requests the
whole WS-Transfer object; a non-empty sequence requests an IMDA projection.
Single text values are returned as `str`, `xsd:base64Binary` values as `bytes`,
and multi-valued attributes as tuples. Every failure crosses the API as
`ADWSClientError`, whose `code`, `category`, and `target` fields are suitable
for command-line or PowerShell error translation.

Each operation creates a unique WS-Addressing `MessageID`. The response must
contain the same `RelatesTo`; missing or mismatched correlation, malformed WCF
or SOAP, and SOAP faults are rejected as typed errors. The configured timeout
applies to connection, authentication, reads, and writes.

## Supported surface

| Surface | Linux client status |
|---|---|
| Resource endpoint, WS-Transfer Get by DN | Supported |
| Optional IMDA attribute projection | Supported |
| SOAP fault decoding | Supported |
| WS-Enumeration `Enumerate` and `Pull` | Supported |
| WS-Enumeration `Release` | Server-only |
| Create, Put, Delete, password and group actions | Server-only |
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

## The `samba-adws` command

`MODULE.yaml` has declared a command of that name since it was written, and
there was none. There is now, and it exists so that another module can reach
this one **without importing it**.

That is the ecosystem's rule rather than a preference: a module owns its
behaviour and its consumers render it, and a consumer that imported this
package would be holding this module's code in its own process — with
`python3-samba` underneath, which is not thread-safe and is why the server
forks rather than threads.

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
verbs exist on `ADWSWriteClient` and are not exposed here yet: a command that
can delete an account needs a decision about which identity it acts as, and
that is `#8`.
