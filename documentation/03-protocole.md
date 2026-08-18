# Protocol details

This document describes what actually travels over port `9389/tcp`. Useful for debugging a failed connection, writing a new handler, or making sense of a `tcpdump` trace.

## Protocol stack

```
┌─────────────────────────────────────────────────┐
│  Application: ADWS / WS-* / Active Directory    │  ← MS-ADDM
├─────────────────────────────────────────────────┤
│  SOAP 1.2 + WS-Addressing                       │
├─────────────────────────────────────────────────┤
│  WCF binary XML (dictionary compression)        │  ← MS-NBFX, MS-NBFS
├─────────────────────────────────────────────────┤
│  GSSAPI (Kerberos AES256, msg sealing)          │  ← RFC 4121
├─────────────────────────────────────────────────┤
│  Net.tcp framing (MS-NMF)                       │  ← MS-NMF
├─────────────────────────────────────────────────┤
│  TCP / 9389                                     │
└─────────────────────────────────────────────────┘
```

Reference Microsoft specifications:

- **MS-NMF**: .NET Message Framing Protocol
- **MS-NBFX**: .NET Binary Format: XML Data Structure
- **MS-NBFS**: .NET Binary Format: SOAP Extension
- **MS-ADDM**: Active Directory Web Services: Data Model and Common Elements

## Phase 1: NMF preamble

The client sends a **fixed sequence of records** with no prior negotiation:

| Byte | Record | Content |
|---|---|---|
| `0x00 0x01 0x00 0x01` | `VersionRecord` | major=1, minor=0 |
| `0x02 0x02` | `ModeRecord` | mode=DUPLEX (2) |
| `0x03 …` | `ViaRecord` | Target URL: `net.tcp://samba.local:9389/ActiveDirectoryWebServices/Windows/Resource` |
| `0x04 0x03` | `KnownEncodingRecord` | encoding=BINARY_WITH_DICT (3) |
| `0x09 …` | `UpgradeRequestRecord` | type = `application/negotiate` (triggers GSSAPI) |

The server answers nothing until it has received `UpgradeRequestRecord`: it just accumulates. If the sequence is invalid, it closes the connection without a reply.

In the code: `src/nettcp/nmf.py` (parsing) + `classes/server/protocol.py` (state machine).

## Phase 2: GSSAPI negotiation

Once `UpgradeRequestRecord` has been received, the server replies with `UpgradeResponseRecord`, then both sides exchange **raw GSSAPI tokens** (each prefixed with a little-endian `int32` length).

```
client ──── token #1 (AP-REQ Kerberos) ──── ► server
client ◄─── token #2 (AP-REP)         ──── server
[possibly several round trips]
client ◄─── PreambleEndRecord (0x0c) ───── server   (= security OK)
```

The server uses `samba.gensec` (through `src/nettcp/stream/gssapi.py`), so the keytab is **automatically** the Samba one (`/var/lib/samba/private/secrets.tdb`). No separate keytab is needed.

From that point on, **every message is sealed**: `gss.wrap(payload)` when sending, `gss.unwrap(...)` when receiving. This is invisible to the layers above.

> **Common error:** `STATUS_NO_SUCH_USER` (NTSTATUS `0xC0000064`) on the server side means that the SPN requested by the client is not in AD. See [06-depannage.md](06-depannage.md).

## Phase 3: application messages

Message format:

```
┌──────────────┬──────────────┬───────────────────────────────┐
│ 0x06 (Sized) │ varint length│  GSSAPI-wrapped( WCF binary ) │
└──────────────┴──────────────┴───────────────────────────────┘
```

The `varint` follows the MS-NMF encoding (continuation bit). Once unsealed, the payload is **WCF binary XML**.

### WCF binary XML (MS-NBFX)

Instead of `<a>b</a>`, there is a sequence of typed **records**. Simplified example:

| Record (byte) | Meaning |
|---|---|
| `0x40 0x01 'a'` | `<a` (element with a short name) |
| `0x06 'b'` | short text "b" |
| `0x01` | `>` then an implicit `</a>` (EndElement) |

Each primitive type has its own record:

| XSD type | Record |
|---|---|
| `xsd:int` | `Int32TextRecord` (0x88) |
| `xsd:long` | `Int64TextRecord` (0x8a) |
| `xsd:dateTime` | `DatetimeTextRecord` (0x96) |
| `xsd:string` | `Chars8TextRecord` / `Chars16TextRecord` (0x98 / 0x9a) |
| `xsd:base64Binary` | `Bytes8TextRecord` (0x9e) |
| `xsd:guid` | `GuidTextRecord` (0xb0) |

The **dictionary** shortens things further: the well-known Microsoft strings (`MessageID`, `Action`, `s:Body`, …) are encoded on 1 byte through the static table (`src/wcf/dictionary.py`). The per-session negotiated dynamic dictionary (MS-NBFSE) is not implemented: only the static table is used.

In the code:

- **Encode** (XML → records): `src/wcf/xml2records.py` + `src/wcf/html_parser.py` (SAX parser feeding the records).
- **Decode** (records → XML): `src/wcf/records/` (one module per record category) + `src/wcf/datatypes.py`.

## SOAP envelope

Once the XML has been reconstructed, it is standard SOAP 1.2 with WS-Addressing headers:

```xml
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
            xmlns:a="http://www.w3.org/2005/08/addressing">
  <s:Header>
    <a:Action s:mustUnderstand="1">
      http://schemas.xmlsoap.org/ws/2004/09/transfer/Get
    </a:Action>
    <a:MessageID>urn:uuid:ece4c158-…</a:MessageID>
    <a:ReplyTo><a:Address>http://www.w3.org/2005/08/addressing/anonymous</a:Address></a:ReplyTo>
    <a:To s:mustUnderstand="1">net.tcp://samba.local:9389/.../Resource</a:To>
    <wsa:ResourceReference xmlns:wsa="…">
      <wsa:InstanceId>11111111-1111-1111-1111-111111111111</wsa:InstanceId>
      <wsa:ObjectReferenceProperty>CN=Administrator,CN=Users,DC=samba,DC=local</wsa:ObjectReferenceProperty>
    </wsa:ResourceReference>
  </s:Header>
  <s:Body>…</s:Body>
</s:Envelope>
```

`Action` determines the handler (see [04-handlers.md](04-handlers.md)). `MessageID` must be echoed back **verbatim** in the `<a:RelatesTo>` of the response; without it PowerShell ignores the reply.

## Get modes: WS-Transfer vs IMDA

The PowerShell `ActiveDirectory` module uses **two distinct layouts** to retrieve an object, depending on the context (cmdlet, version, requested attributes).

### WS-Transfer (whole object)

```xml
<s:Body>
  <addata:user xmlns:addata="…ActiveDirectory/Data"
               xmlns:ad="…ActiveDirectory">
    <ad:objectReferenceProperty><ad:value xsi:type="xsd:string">f6aac55f-…</ad:value></ad:objectReferenceProperty>
    <addata:cn LdapSyntax="UnicodeString"><ad:value xsi:type="xsd:string">Administrator</ad:value></addata:cn>
    <addata:objectGUID LdapSyntax="OctetString"><ad:value xsi:type="xsd:base64Binary">…</ad:value></addata:objectGUID>
    <addata:objectSid LdapSyntax="SidString"><ad:value xsi:type="xsd:base64Binary">…</ad:value></addata:objectSid>
    …
    <ad:relativeDistinguishedName><ad:value xsi:type="xsd:string">CN=Administrator</ad:value></ad:relativeDistinguishedName>
    <ad:distinguishedName><ad:value xsi:type="xsd:string">CN=…</ad:value></ad:distinguishedName>
  </addata:user>
</s:Body>
```

A single wrapper named after the structural objectClass. `objectReferenceProperty`
(the EPR **GUID**, not the CN) comes first; the synthetic `distinguishedName` /
`relativeDistinguishedName`, in the `ad:` namespace, come last. The value of
`LdapSyntax` is a directory syntax enumeration name defined by the specification.
The items of `Pull` (WS-Enumeration) use exactly this form.

### IMDA: Identity Management Directory Access

Two sub-forms, depending on whether the `<da:BaseObjectSearchRequest>` request lists
any `<da:AttributeType>` (the discriminator defined by [MS-WSTIM]).

**Form a, at least one attribute requested**: one `<da:PartialAttribute>` per
attribute, with `distinguishedName` always emitted (synthetic `ad:`):

```xml
<s:Body>
  <da:BaseObjectSearchResponse xmlns:da="…DirectoryAccess">
    <da:PartialAttribute>
      <addata:cn LdapSyntax="UnicodeString"><ad:value xsi:type="xsd:string">Administrator</ad:value></addata:cn>
    </da:PartialAttribute>
    <da:PartialAttribute>
      <addata:objectSid LdapSyntax="SidString"><ad:value xsi:type="xsd:base64Binary">…</ad:value></addata:objectSid>
    </da:PartialAttribute>
    <da:PartialAttribute>
      <ad:distinguishedName><ad:value xsi:type="xsd:string">CN=…</ad:value></ad:distinguishedName>
    </da:PartialAttribute>
  </da:BaseObjectSearchResponse>
</s:Body>
```

**Form b, no attribute requested**: the whole object (the WS-Transfer form
above) inside **a single** `<da:PartialAttribute>`.

> `distinguishedName` is a **synthetic** attribute: `<ad:distinguishedName>` in the
> `ad:` namespace, **without** `LdapSyntax`, never `<addata:distinguishedName>`.

### Detection

`classes/parsing/context.py`: `is_imda` is true if the request contains
`<da:IdentityManagementOperation>` **or** `<da:BaseObjectSearchRequest>`;
false for a bare `<wxf:Get>` (WS-Transfer). Form a versus form b is then decided
from `context.requested_attributes`.

The handlers that render objects (`get.py`, `pull.py`) delegate to
`object_projector.ObjectProjector` (`whole_object` / `imda_projection`).

> **Typical bug**: sending the WS-Transfer form in response to an IMDA request gives, on the Windows side:
> `Élément de fin '…' attendu, trouvé 'ad:distinguishedName'` (verbatim message from a French-locale client;
> in English: "expected end element '…', found 'ad:distinguishedName'"). See [06-depannage.md](06-depannage.md).

## Paged enumeration (WS-Enumeration)

A cmdlet such as `Get-ADUser -Filter *` does not fit in a single response. The flow is:

```
client → Enumerate {Filter, BaseDN, Scope}            ─► server
server ◄ EnumerateResponse {EnumerationContext=UUID, Expires=...}

client → Pull {EnumerationContext=UUID, MaxElements=N} ─► server
server ◄ PullResponse {Items=[...], EnumerationContext OR EndOfSequence}

[repeat Pull as many times as needed]

client → Release {EnumerationContext=UUID}             ─► server
server ◄ ReleaseResponse
```

The enumeration context is stored in `src/enumeration/enumeration.py` (in memory, keyed by UUID). Since the server runs in forking mode, **each process keeps its own cache**: session stickiness on the Windows side means that every Pull for the same Enumerate lands on the same process (the TCP connection is reused).

`Renew` lets the client extend the expiry; `GetStatus` lets it check the state.

## SOAP Faults

Every server-side exception is translated into:

```xml
<s:Envelope …>
  <s:Header>
    <a:Action>http://schemas.xmlsoap.org/ws/2004/08/addressing/fault</a:Action>
    <a:RelatesTo>{message_id_of_the_request}</a:RelatesTo>
  </s:Header>
  <s:Body>
    <s:Fault>
      <s:Code><s:Value>s:Receiver</s:Value></s:Code>
      <s:Reason><s:Text xml:lang="en">message</s:Text></s:Reason>
    </s:Fault>
  </s:Body>
</s:Envelope>
```

**Without the `<a:RelatesTo>`**, PowerShell assumes the message is an unsolicited response and drops it → the cmdlet blocks until the timeout. That is why `_fault()` in `classes/handlers/dispatcher.py` captures `context.message_id` even when the error occurs before the handler is called.

Typed fault codes (`src/faults/fault_codes.py`):

| Code | Meaning |
|---|---|
| `DirectoryError` | Generic LDB error |
| `InsufficientAccessRights` | Missing rights |
| `ConstraintViolation` | Constraint violation (password too short, required attribute missing, …) |
| `ObjectClassViolation` | Invalid object class |
| `EntryAlreadyExists` | DN already in use |
| `NoSuchObject` | Target DN not found |

## Capture tools

To observe a real exchange:

```bash
# On the DC, on the loopback interface:
sudo tcpdump -i any -w /tmp/adws.pcap port 9389
```

The content will be **encrypted** after the GSSAPI negotiation. To see it in the clear, log through `proxy.py`:

```python
# In tools/work/proxy.py (debugging only):
RECORD_LOG = "/tmp/adws-records.log"
```

To decode a binary payload by hand:
```bash
python3 -c "from src.wcf.records import dump_records; \
            data=open('/tmp/payload.bin','rb').read(); \
            print(dump_records(data))"
```
