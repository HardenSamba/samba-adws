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
