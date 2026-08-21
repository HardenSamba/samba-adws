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

Authorization for writes is enforced by the server once
[issue #8](https://github.com/HardenSamba/samba-adws/issues/8) is in place: the
request runs under the caller's GSSAPI session and Samba's local `acl` module
denies a write the principal has no right for. This client exposes the write
verbs through `ADWSWriteClient` (see [Write operations](#write-operations)); the
read-only `ADWSClient` remains available for callers that must not write. Until
#8 is merged, the server still opens `SamDB` as SYSTEM, so restrict writes to a
trusted lab. Read requests are not attribute-filtered by the local `SamDB`
([#17](https://github.com/HardenSamba/samba-adws/issues/17)); a successful read
does not prove the caller's read rights.

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

## Write operations

`ADWSWriteClient` extends `ADWSClient` with the directory-changing verbs, so one
instance both reads and writes. Reads use the same `get_by_dn`; writes map onto
the server's WS-Transfer and custom-action handlers.

```python
from samba_adws import ADWSWriteClient

client = ADWSWriteClient("dc1.samdom.example.com")
parent = "CN=Users,DC=samdom,DC=example,DC=com"
client.create(f"CN=demo,{parent}", {"objectClass": ["user"], "sAMAccountName": ["demo"]})
client.set_password(f"CN=demo,{parent}", secret)     # secret rides the sealed body
client.modify(f"CN=demo,{parent}", {"description": ["set over ADWS"]})
client.rename(f"CN=demo,{parent}", f"CN=demo2,{parent}")
client.delete(f"CN=demo2,{parent}")
```

The stable signatures are:

```python
create(identity: str, attributes: Mapping[str, Sequence[str]]) -> None
modify(identity: str, changes: Mapping[str, Sequence[str]]) -> None
delete(identity: str) -> None
set_password(identity: str, password: str) -> None
rename(identity: str, new_dn: str) -> None
```

`create` splits `identity` into its RDN and parent and posts an `AddRequest` to
the ResourceFactory endpoint. `modify` replaces each named attribute (an empty
value sequence clears it). `rename` is an LDAP modrdn carried as a WS-Transfer
`Put`. `set_password` places the secret inside the request body only — never on
a command line or in a header — and the transport seals it under GSSAPI. Every
method returns `None` on success and raises `ADWSClientError` on a SOAP fault or
a validation error, with the target distinguished name attached.

## Supported surface

| Surface | Linux client status |
|---|---|
| Resource endpoint, WS-Transfer Get by DN | Supported |
| Optional IMDA attribute projection | Supported |
| SOAP fault decoding | Supported |
| WS-Enumeration (`Enumerate`, `Pull`, `Release`) | Server-only |
| Create, Put, Delete, rename, SetPassword (`ADWSWriteClient`) | Supported |
| Group-membership and other custom actions | Server-only |
| Schema and enumeration-based search | Server-only |

The client currently accepts the static WCF dictionary emitted by this server.
It rejects a non-empty dynamic dictionary; the server does not negotiate or
emit one. Live acceptance still requires a Debian workstation with `kinit` and
a reachable Samba ADWS endpoint. Offline tests cover request encoding, response
decoding, faults, malformed responses, correlation, transport errors, and
import isolation:

```bash
python3 -m pytest -q tests
```
