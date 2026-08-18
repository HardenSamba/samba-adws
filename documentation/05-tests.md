# Tests

Three test suites, at different levels.

| Suite | Where | What | When |
|---|---|---|---|
| `Test-ADWS-Sovereign.ps1` | Windows | End to end, real PowerShell cmdlets | Final validation |
| `test_handlers.py` | Linux DC | Handlers in isolation (no network) | Before deployment |
| `test_adws.py` | Linux DC | Diagnostics (port, imports, parser, …) | First start |

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

## 2. `test_handlers.py` (handlers in isolation)

To be run on **the Samba DC**:

```bash
cd /root/SambaAD_ADWS
python3 tools/test/test_handlers.py
```

Loads the Python handlers directly and passes them hand-built `RequestContext` objects (no NMF, no WCF, no network). Useful to:

- isolate an application bug from a protocol bug,
- add a regression case without having to deploy everything,
- iterate quickly while writing a new handler.

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
                │ 3. test_handlers.py        │  ← isolated logic
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
