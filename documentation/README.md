# Samba AD ADWS Documentation

Complete index of the project documentation.

## By profile

### I just want to install it

→ [02-installation.md](02-installation.md), then [05-tests.md § Test-ADWS-Sovereign.ps1](05-tests.md#3-test-adws-sovereignps1-main-validation).

### I want to call ADWS from Linux

→ [07-linux-client.md](07-linux-client.md) for the supported Python API,
Kerberos requirements, and current action surface.

### I want to understand how it is built

→ [01-architecture.md](01-architecture.md), then [03-protocole.md](03-protocole.md).

### I have an error in production

→ [06-depannage.md](06-depannage.md). The index at the top of the file maps symptom → section.

### I want to add a feature

→ [04-handlers.md § Adding a new handler](04-handlers.md#ajouter-un-nouveau-handler).

### I want to write a regression test

→ [05-tests.md § pytest](05-tests.md#0-pytest-run-this-first) if it needs no directory, [05-tests.md § tests/dc](05-tests.md#1-testsdc-handlers-in-isolation) if it does.

---

## Detailed contents

### [01-architecture.md](01-architecture.md)
- Why the project exists
- High-level view: client → server flow
- Server layers: `src/nettcp/`, `src/wcf/`, `classes/` + `src/` (by phase), `classes/server/server.py`
- Flow of a `Get-ADUser` request, step by step
- Design decisions (forking, IMDA vs WS-Transfer, …)
- Known limitations

### [02-installation.md](02-installation.md)
- Linux and Windows prerequisites
- Kerberos configuration (`/etc/krb5.conf`, SPN)
- One-command installation (`git clone` + `sudo tools/installation/install.sh`)
- Manual startup and systemd service
- Verification (`Test-NetConnection`, `Get-ADRootDSE`)
- No virtualenv and no pip (everything through apt)
- Uninstallation

### [03-protocole.md](03-protocole.md)
- Protocol stack (NMF, WCF binary XML, GSSAPI, SOAP)
- Phase 1 — NMF preamble
- Phase 2 — GSSAPI negotiation
- Phase 3 — Application messages (binary WCF, dictionary)
- SOAP envelope + WS-Addressing
- Get modes: WS-Transfer vs IMDA
- Paged enumeration (Enumerate / Pull / Release / Renew)
- SOAP fault format
- Capture tools (`tcpdump`, debug proxy)

### [04-handlers.md](04-handlers.md)
- Full catalogue of handlers (WS-Transfer, WS-Enumeration, ADWS actions)
- `SOAP action → handler` routing
- The `BaseHandler.handle()` contract
- Procedure for adding a new handler
- Frequently used helpers
- Best practices

### [05-tests.md](05-tests.md)
- Overview of the four levels
- `pytest -m "not dc"` (level 0, runs anywhere, blocking pre-commit hook)
- `pytest tests/dc` (handlers in isolation)
- `test_adws.py` (environment diagnostics)
- `Test-ADWS-Sovereign.ps1` (end-to-end PowerShell validation)
- Recommended workflow

### [06-depannage.md](06-depannage.md)
- Kerberos / SPN (`STATUS_NO_SUCH_USER`)
- Connection closed by the server
- Malformed XML (expected element)
- `MessageElement` unwrapped incorrectly
- Empty base DN
- Cmdlet that hangs (missing RelatesTo)
- ADWS not found on the Windows side
- Insufficient rights
- Enabling DEBUG logs
- Capturing a full exchange

### [07-linux-client.md](07-linux-client.md)
- Workstation dependencies and Kerberos credential-cache authentication
- Public `ADWSClient` and `ADWSClientError` contracts
- Supported Get-by-DN surface and server-only operations
- Offline tests and the remaining live validation criterion

---

## Conventions used in the examples

- **`samba.local`**: placeholder FQDN of the DC in every example. Replace it with your own.
- **`SAMBA.LOCAL`**: the matching Kerberos realm (always uppercase).
- **`Administrator`**: the default Samba admin account. Depending on your domain it may have another name.
- **`/root/SambaAD_ADWS`**: the default installation path (the cloned folder, started by `install.sh`). Adapt it to your own convention.

## Documentation contribution rules

- **French** on the documentation side, **English** on the code side (see `CLAUDE.md`).
- No decorative emoji: an icon must carry information (✅/❌ are acceptable in status tables).
- File paths mentioned in the text are **clickable links** to the source file.
- Shell code blocks are **copy-pasteable as is** on a standard Debian/Ubuntu, with no variable to substitute (otherwise use an explicit `<placeholder>`).
- Any fix to a documented behaviour must also update the documentation in the same PR.
