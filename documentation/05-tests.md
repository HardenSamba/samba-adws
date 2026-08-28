# Tests

Four levels, in the order to run them.

| Level | Suite | Where | What | When |
|---|---|---|---|---|
| 0 | `pytest tests/unit` | Anywhere | The layers that need no directory: WCF, NMF, SOAP envelope, value encoding, request parsing, the scope-dependent attribute projection, handler coverage | Every commit |
| 1 | `pytest tests/dc` | Linux DC | Every registered handler, in isolation, against a real directory | Before deployment |
| 2 | `tools/test/test_adws.py` | Linux DC | Operator diagnostic: port, imports, parser | First start, and when something is wrong |
| 3 | `Test-ADWS-Sovereign.ps1` | Windows | End to end, real PowerShell cmdlets | Final validation |

## 0. `pytest` (run this first)

```bash
python3 -m pytest -q
```

Levels 0 and 1 are one pytest run. Level 1 carries the `dc` marker and
`tests/conftest.py` **skips** it when `python3-samba` cannot be imported, so the
command above passes on a plain Debian box with no directory:

```console
$ python3 -m pytest -q
ssssssssssssssssssssssssssssssss........................................
48 passed, 32 skipped
```

Skipped, never failed. A red run on a workstation is a real defect, not a
missing DC.

`python3 -m pytest tests/unit -q` runs only the part that needs nothing.

### What level 0 covers, and the one string it uses

Every write path is fed `créé & <société> "x" 'y'` and the result is **reparsed
with `xml.etree` and compared to the input**, rather than merely asserted not to
raise. Non-ASCII has broken this codebase once already: the WCF escaper had to
stop turning accents into HTML entities that `ElementTree` cannot resolve, and
that fix is now held by a test that fails if it is reverted.

The same suite pins that a value containing byte `0x01` leaves as
`xsd:base64Binary` rather than being inserted into XML that cannot carry it.

### Handler coverage

`tests/unit/test_handler_coverage.py` reads the registration keys straight out
of `src/handlers/handler_routing.py` with `ast` — importing it would pull in the
directory bindings — and fails when a key has no entry in
`tests/dc/handler_actions.py`. **Adding a handler without a test fails the
suite, on any machine.**

### Handlers that touch the directory

Decision: `tests/dc/` uses a **real directory**, not a stub. A fake `SambaDB`
would have to imitate LDB's `MessageElement` semantics, which is where this
codebase's bugs actually live (see troubleshooting sections 4 and 9) — a stub
faithful enough to catch them would be a second implementation to maintain, and
one that is not would give green tests and broken cmdlets. The cost is that
level 1 is skipped off a DC, which is why level 0 carries everything testable
without one.

The registry is built per test through the `registry` fixture, never at module
level: `python3-samba` is not thread-safe and `CLAUDE.md` section 5 forbids
opening `SamDB` at import time. That applies to fixtures too.

---

## 1. `Test-ADWS-Sovereign.ps1` (main validation)

Pester-like suite in pure PowerShell. **This is the reference test**: if everything passes here, the server is usable in production.

### Running

```powershell
.\tools\test\Test-ADWS-Sovereign.ps1 -Server samba.local
```

Parameters:

| Parameter | Default | Description |
|---|---|---|
| `-Server` | (required) | FQDN or IP address of the Samba DC |
| `-Credential` | (interactive) | Domain admin `pscredential`. Prompted interactively otherwise |
| `-OutputDirectory` | `.\adws-test-results` | Output directory |
| `-TestUserPrefix` | `adwsTest` | Prefix for the temporary test accounts |
| `-SkipMutations` | `$false` | Reads only (Create/Modify/Delete skipped) |
| `-SkipStress` | `$false` | Skips the load test (50 parallel requests) |

### Categories covered

| Category | Tests | Notes |
|---|---|---|
| `Connectivity` | `Get-ADRootDSE`, `Get-ADDomain`, `Get-ADForest`, `Get-ADDomainController` | Must always pass |
| `Read` | `Get-ADUser`, `Get-ADGroup`, `Get-ADComputer -Filter *` | Checks the IMDA and WS-Transfer rendering |
| `Enumerate` | `Get-ADUser -Filter *`, AND/OR/NOT filters, `Get-ADObject` pagination | Covers `Enumerate`/`Pull`/`Release` |
| `Create` / `Modify` / `Delete` | Full cycle on a `${TestUserPrefix}-{ts}` user | Skipped with `-SkipMutations` |
| `SetPassword` / `ChangePassword` | Reset, then change using the old password | Checks GSSAPI seal and password policies |
| `GroupRead` / `GroupModify` | Creates a group with 2 members, adds, lists, recursive, removes | |
| `Schema` | Lists 10 `classSchema` and 10 `attributeSchema` | Reads the Schema partition |
| `Stress` | 50 parallel `Get-ADUser -Filter *` (throttle 10) | Skipped with `-SkipStress` |

### Outputs

Two timestamped files are created in `-OutputDirectory`:

- `adws-test-{timestamp}.log`: readable text, one section per test
- `adws-test-{timestamp}.json`: structured result for CI and automation

JSON format:

```json
[
  {
    "Name": "Get-ADUser Administrator -Properties *",
    "Category": "Read",
    "StartTime": "2026-04-26T10:23:45.123+02:00",
    "Status": "Pass",
    "DurationMs": 142,
    "Output": "...",
    "Error": null
  },
  …
]
```

`Status` is either `Pass` or `Fail`. With `$ErrorActionPreference = "Stop"` (set at the top of the script), any PowerShell exception aborts the test, so a false Pass is impossible.

### Reading a run quickly

```powershell
$results = Get-Content .\adws-test-results\adws-test-*.json | ConvertFrom-Json
$results | Group-Object Status | Format-Table Count, Name
$results | Where-Object Status -eq Fail | Select-Object Name, Error
```

---

## 2. `tests/dc/` (handlers in isolation)

To be run on **the Samba DC**:

```bash
cd /root/SambaAD_ADWS
python3 -m pytest tests/dc -q
```

Loads the Python handlers directly and passes them hand-built `RequestContext` objects (no NMF, no WCF, no network). Useful to:

- isolate an application bug from a protocol bug,
- add a regression case without having to deploy everything,
- iterate quickly while writing a new handler.

Every registered handler is driven here, and each one is asserted to answer
with XML that parses and whose `<a:RelatesTo>` echoes the request's
`MessageID` — the invariant of `CLAUDE.md` section 5, and the assertion that
holds for every registered key without guessing at the shape of each body. A
handler that needs a richer request than a bare envelope answers with a fault,
and a fault has to relate to its request too. The case list is derived from
`tests/dc/handler_actions.py`, so registering or removing a handler moves it
without anyone having to recount the cases here.

One file in `tests/dc/` drives no handler: `test_member_write_flags.py` pins the
LDB flags a group-membership `Put` ends up applying. It needs `ldb`, so it
carries the `dc` marker like the rest of level 1 even though it never builds a
`RequestContext`.

This replaces `tools/test/test_handlers.py`, whose three checks moved here. That
script took a `reg` argument that pytest read as a fixture, so its three checks
had never run under `pytest`, only through its own `main()`.

---

## 3. `test_adws.py` (diagnostics)

```bash
python3 tools/test/test_adws.py
```

Checks, in sequence:

1. That port `9389/tcp` is open.
2. Critical imports (`samba`, `ldb`, `gssapi`, `lxml`).
3. The `SamDB` connection (reading the default DN).
4. The XML/WCF parser (encode/decode round trip).
5. Instantiation of every handler.
6. Routing through `HandlerRegistry`.

This is the first thing to run after installation to confirm that the environment is healthy, well before trying a PowerShell cmdlet.

---

## 4. Validation against a real Windows client

Reference validation is done from a **domain-joined Windows workstation**,
with the real `ActiveDirectory` module, by running
`.\tools\test\Test-ADWS-Sovereign.ps1 -Server <DC>` (see §1).

### Status: validated against a real Windows 11 client (8 June 2026)

Tested from a **domain-joined Windows 11 workstation** (`samba.local`), with the
real `ActiveDirectory` module, against the server on the Samba DC.
`Test-ADWS-Sovereign.ps1` suite: **26/28**.

- ✅ Connection and authentication (NMF + GSSAPI/Negotiate + binary WCF).
- ✅ Read: RootDSE, Domain/Forest/DomainController,
  Get-ADUser/Group/Computer/Object, filtered (AND/OR/bitwise-NOT) and paged
  enumerations, schema discovery.
- ✅ Write: New-AD*, Set-AD*, Remove-AD*, `Set-ADAccountPassword -Reset`,
  group operations (direct and recursive members).
- ✅ Advanced administration, **parity battery 18/18**: OU (New/Get/Remove),
  `Enable`/`Disable-ADAccount`, `Rename-ADObject`, `Move-ADObject`, recursive
  deletion (`-Recursive`), `Search-ADAccount` (-AccountDisabled/-Inactive/
  -LockedOut), `Get-AD*|Set-AD*` pipeline, `Get-ADUser -Properties *`.
- ⚠️ `Set-ADAccountPassword` **self-service change** (old→new):
  fails on the Samba side (`Failed to obtain remote address for the LDAP client`).
  The administrator reset works. See [known limitations](01-architecture.md#known-limitations).
- ⚠️ `Stress` test (50 parallel requests): a limitation of the harness
  (`ForEach-Object -Parallel` is missing from Windows PowerShell 5.1), not of the server.

**Root cause of the historical RootDSE blocker (resolved).** On the wire the
client accepts only two `xsi:type` values: `xsd:string` and `xsd:base64Binary`
(observed client behaviour). The server was emitting `xsd:integer` / `long`
/ `boolean` / `dateTime`, which raised a `KeyNotFoundException` during
client-side value deserialization. The real LDAP type is carried by `LdapSyntax`,
never by `xsi:type`. Fixed in `value_codec.py`, `value_special.py`,
`syntax_constants.py`. `New-ADUser` additionally required DN resolution through
`relativeDistinguishedName` + `container-hierarchy-parent`, and a
`ResourceCreated` response whose `Address`/`ReferenceParameters` are in the
WS-Addressing namespace (`wsa`, not `wst`), fixed in `handlers/create.py`.

**Other parity fixes.** `Rename-ADObject`/`Move-ADObject` arrive as a
Put modifying `relativeDistinguishedName`/`container-hierarchy-parent`, handled
as an LDB modrdn (`db.rename`) in `handlers/modify.py`. Recursive deletion
(`Remove-AD* -Recursive`) honours the tree-delete control in
`handlers/delete.py`. Filters with a bare NOT operand (`(!attr=val)`, sent
by `Search-ADAccount`, tolerated by AD but rejected by ldb) are normalised to
`(!(attr=val))` by `filter_parser.py`.

---

## Recommended workflow

```
                ┌────────────────────────────┐
                │ 1. Code change             │
                └─────────────┬──────────────┘
                              ▼
                ┌────────────────────────────┐
                │ 2. test_adws.py            │  ← imports + sanity
                │    on DC                   │
                └─────────────┬──────────────┘
                              ▼
                ┌────────────────────────────┐
                │ 3. pytest tests/dc         │  ← isolated logic
                │    on DC                   │
                └─────────────┬──────────────┘
                              ▼
                ┌────────────────────────────┐
                │ 4. python3 -m src.main     │  ← live server
                │    on DC                   │
                └─────────────┬──────────────┘
                              ▼
                ┌────────────────────────────┐
                │ 5. Test-ADWS-Sovereign.ps1 │  ← real E2E
                │    -SkipMutations          │     (reads first)
                └─────────────┬──────────────┘
                              ▼
                ┌────────────────────────────┐
                │ 6. Test-ADWS-Sovereign.ps1 │  ← E2E + writes
                │    (without -SkipMutations)│
                └────────────────────────────┘
```

At each failing step, go back no further than necessary:

- Any red `Connectivity` → go back to step 4 and read the server logs.
- Any red `Read` with a green `Connectivity` → bug in `Get`/`Enumerate`/`Pull` (step 3).
- Any red `Mutation` with a green `Read` → bug in `Create`/`Modify`/`Delete` (step 3).

The typical server-side errors are decoded in [06-depannage.md](06-depannage.md).
