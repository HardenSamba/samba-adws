# Architecture

## Why this project exists

Samba AD provides a domain controller compatible with Active Directory at the **LDAP, Kerberos, SMB and DNS** level, but **does not expose** ADWS (port 9389/tcp). Without ADWS, the Microsoft PowerShell tools fail on the very first cmdlet:

```
Get-ADUser : Unable to find a default server with Active Directory Web Services running
```

This project implements **the same protocol** on the Linux side as `Microsoft.ActiveDirectory.WebServices.exe`, so that the `ActiveDirectory` PowerShell module, ADAC, and any tool built on the `Microsoft.ActiveDirectory.Management` namespace work **without modification**.

## The 10 km view

```
PowerShell / ADAC (Windows)                                Samba DC (Linux)
─────────────────────────────                              ────────────────
Get-ADUser administrator                                   python3 -m src.main
        │                                                          │
        │  net.tcp://samba.local:9389                              │
        │  ┌──────────────────────────────────┐                    │
        └──┤  1. Préambule (NMF)              ├──── src/nettcp/ ────►  │
           │  2. Négociation GSSAPI/Kerberos  │                    │
           │  3. Trame SOAP binaire (WCF)     │                    │
           └──────────────────────────────────┘                    │
                          │                                        │
                          ▼                                        ▼
                   src/wcf/xml2records.py ◄──── XML lisible ──  classes/handlers/
                          │                                   dispatcher
                          ▼                                        │
                  classes/handlers/                               │
                  (Get, Pull, CRUD, …)                             │
                          │                                        │
                          └─────► samba.samdb (python3-samba)──────┘
                                          │
                                          ▼
                                    sam.ldb (Samba)
```

## Server layers

The code is organised **by responsibility**, not by business feature. Each layer only knows the one directly below it.

### 1. `src/nettcp/` — Net.tcp framing

Implements [MS-NMF] (.NET Message Framing Protocol).

| File | Role |
|---|---|
| `nmf.py` | Preamble records (Version, Mode, Via, Encoding, UpgradeRequest, EndRecord, …) |
| `protocol2xml.py` | Binary record to XML fragment conversion |
| `tools/work/proxy.py` | Capture / replay tool for debugging (outside the runtime, moved to `tools/work/`) |
| `stream/socket.py` | Buffered wrapper around the TCP socket |
| `stream/gssapi.py` | GSSAPI initiator plus the server GENSEC acceptor; Samba imports stay lazy and server-only |

This is the layer that speaks "the wire". Above it, payloads are XML.

### 2. `src/wcf/` — WCF binary encoding

Implements [MS-NBFX] (.NET Binary Format: XML Data Structure).

| File | Role |
|---|---|
| `xml2records.py` | XML text → sequence of binary records (outbound) |
| `records/` | Binary records → XML text (inbound) |
| `dictionary.py` | Static Microsoft dictionary (prefixes known strings on 1 byte) |
| `datatypes.py` | WCF primitive types (Int32TextRecord, DatetimeTextRecord, GuidTextRecord, …) |
| `html_parser.py` / `html_parse_error.py` | SAX-like parser used to build the records from the application XML |

Everything that leaves the dispatcher is **plain SOAP XML**; this layer compresses it into WCF binary before sending.

### 3. ADWS logic — `classes/<phase>/` + `src/<phase>/`

The in-house application core, organised **by protocol phase** (see
[03-protocole.md](03-protocole.md)). Each phase has a folder of the same name in
**two mirror trees**: `classes/<phase>/` holds the **classes** (one file = one
class), `src/<phase>/` holds the **class-free code** of the same phase
(constants, functions, routing tables, singletons). `src/nettcp/`
(NMF framing + GSSAPI) and `src/wcf/` (WCF binary encoding) are vendored
third-party code, integrated under `src/` but excluded from the §6.1 norms (see `pyproject.toml`).

| Phase (folder) | `classes/<phase>/` (one class per file) | `src/<phase>/` (non-classes) |
|---|---|---|
| `server` | `config`, `server`, `connection`, `protocol`, `service_context` | — |
| `soap` | `soap_envelope` | `namespaces` |
| `parsing` | `context`, `body_parser`, `attribute_parser`, `controls_parser`, `filter_parser` | — |
| `serialization` | `object_projector`, `xml_renderer`, `value_codec`, `ldb_value`, `ca_elements`, `constructed_attrs`, `dc/domain/group_serializer`, `name_formats`, `syntaxes`, `syntax_cache` | `value_special`, `name_filters`, `name_renderers`, `syntax_constants` |
| `handlers` | `dispatcher`, `handler_registry`, `base` + one file per action | `handler_routing` |
| `enumeration` | `enumeration_registry`, `enumeration_context`, `subscription_cache` | `enumeration`, `subscription_id`, `subscription_registry` |
| `directory` | `samba_db`, `ldap_attr_builder`, `ldap_session_pool`, `schema_cache`, `domain_loader`, `principal_loader`, `instance_index`, `quota_ledger`, `reservation_lease` | `fsmo_roles` |
| `faults` | `exceptions`, `faults`, `typed_faults` | `fault_codes` |

`dispatcher` receives a `Record`, parses it into a `RequestContext`, routes it to
the right handler and encodes the response; `parsing/` splits the XML fragments;
`serialization/` renders AD objects according to their LDAP syntax. SDDL
scrubbing (`nTSecurityDescriptor`) is not wired up yet.

### 4. `classes/handlers/` — One action = one file

One file per SOAP action. They all inherit from `BaseHandler` and expose `handle(context: RequestContext) → str` (the response XML).

See [04-handlers.md](04-handlers.md) for the complete list.

### 5. `classes/server/server.py` + `classes/server/connection.py` + `classes/server/protocol.py`

| File | Role |
|---|---|
| `server.py` | `socketserver.ForkingTCPServer` listening on 9389/tcp |
| `connection.py` | For each connection: preamble → GSSAPI upgrade → message loop |
| `protocol.py` | State machine for the NMF protocol phases |

> **Important:** `ForkingTCPServer` means that **each connection is a separate process**. Any resource (the `SamDB` cache, the WCF dictionaries) must be opened **inside the handler**, not at module level, otherwise it is shared between forks and the locks break.

## Flow of a request

Example: `Get-ADUser Administrator`.

1. **On the Windows side** — The `ActiveDirectory` module opens a `net.tcp` connection to `samba.local:9389`.
2. **Preamble (Phase 1)** — `VersionRecord`, `ModeRecord`, `ViaRecord`, `KnownEncodingRecord`, `UpgradeRequestRecord` are sent in sequence. The server validates each record in `classes/server/protocol.py`.
3. **Security (Phase 2)** — The client switches to a TLS-like mode through GSSAPI. Several `update()` round trips take place until a Kerberos context is obtained. From that point on, every message is sealed (`wrap` / `unwrap`).
4. **SOAP message** — The client sends a WCF binary payload.
5. **Decoding** — `nettcp` reads the record and extracts the encrypted payload, GSSAPI decrypts it, and `src/wcf/xml2records.py` turns it into XML text.
6. **Routing** — `RequestContext.from_xml(xml)` extracts the action (`http://schemas.xmlsoap.org/ws/2004/09/transfer/Get`), the message ID and the target DN. `HandlerRegistry.resolve()` returns `GetHandler`.
7. **Execution** — `GetHandler.handle()` calls `samba.samdb.search()` and formats the result depending on whether the request is in **WS-Transfer** mode (a single `<addata:user>...</addata:user>`) or **IMDA** mode (each attribute in its own `<da:PartialAttribute>`).
8. **Response encoding** — SOAP XML → WCF records → GSSAPI-sealed bytes → Net.tcp frame.
9. **On the Windows side** — `Get-ADUser` receives the object, deserialises it and displays it.

Every server-side error is converted into a **SOAP fault** by the dispatcher (with `<a:Action>` and `<a:RelatesTo>` referring back to the original `MessageID`; without them, PowerShell ignores the response).

## Design decisions

### Why `ForkingTCPServer`?

Samba's `python3-samba` is **not thread-safe** (its internal C structures do not support concurrent access). Forking gives complete isolation per request. The cost is one fork per connection, which is acceptable because PowerShell clients reuse the connection across several cmdlets.

### Why parse SOAP XML rather than generate and parse WCF records directly?

Textual SOAP stays **readable and debuggable**. The `src/wcf/` layer is a reversible encoder/decoder: everything can be logged as XML. The CPU cost of the round trip is negligible compared to network and LDB time.

### Why one file = one handler?

Readability, isolation, and a project rule: **5 functions max per file, one class max per file**. Adding a new SOAP action then becomes mechanical (see [04-handlers.md](04-handlers.md)).

### Why separate IMDA and WS-Transfer modes?

The `ActiveDirectory` PowerShell module sends Get requests in **two forms depending on the version**:

- **WS-Transfer**: the envelope is `<addata:user>` containing all the attributes (compact response).
- **IMDA** (Identity Management Directory Access): the envelope is `<da:BaseObjectSearchResponse>` with one `<da:PartialAttribute>` per attribute.

The detection lives in `classes/parsing/context.py` (`is_imda`), and each handler picks the matching rendering.

## Known limitations

- **Self-service password change** (`Set-ADAccountPassword` with old + new) is not supported: on this path the Samba `password_hash` module requires the client network address (`remoteAddress`), which cannot be supplied over a local `SamDB` connection (a `tsocket_address` cannot be built from Python). The **administrative reset** (`-Reset`) works. Possible approach: an authenticated `ldapi://` connection, or delegation of the GSSAPI client identity.
- **Inter-domain and inter-forest trusts** are not supported (the code assumes a single local domain).
- **Binary attributes** are partially supported (the most common ones, `objectGUID`, `objectSid` and `nTSecurityDescriptor`, work; custom binary attributes from schema extensions are rendered as raw base64).
- **Extended LDAP pagination**: client-side `PagedResults` controls are accepted, but the server performs a single full `search()` and paginates in the handler.
- **Exotic LDAP filters**: extended operators such as `1.2.840.113556.1.4.804` (LDAP_MATCHING_RULE_BIT_OR) are supported; undocumented ones may not be (see `classes/parsing/filter_parser.py`).

## Further reading

- [02-installation.md](02-installation.md) — how to deploy
- [03-protocole.md](03-protocole.md) — NMF / WCF / SOAP details
- [04-handlers.md](04-handlers.md) — how to add an action
