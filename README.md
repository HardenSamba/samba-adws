# Samba AD — ADWS (sovereign edition)

A **100% Python implementation, with no Microsoft component whatsoever**, of the **Active Directory
Web Services** (ADWS, `9389/tcp`) for a **Samba AD** domain controller.

It bridges the WS-\* requests of Windows clients and the Samba directory (LDB).
The result: a Windows workstation drives the Samba domain with its usual tools,
`Get-ADUser`, `Set-ADUser`, the `ActiveDirectory` PowerShell module and the **ADUC** console,
as if it were facing a Microsoft AD (ADAC needs the DC to advertise ADWS, see
[Graphical consoles](#graphical-consoles-adac-dsacexe-and-aduc-dsamsc)).

> **Strategic goal:** a sovereign alternative to Microsoft AD, open and auditable,
> without giving up the existing PowerShell tooling.

**Validated status** (8 June 2026, real Windows 11 client -> Samba DC): official suite **26/28**,
admin parity battery **18/18**. The 2 remaining gaps are not server bugs
(see [Known limitations](#known-limitations)).

> **Authorization status:**
> [#8](https://github.com/HardenSamba/samba-adws/issues/8) removed the SYSTEM
> session: each request opens `SamDB` under the caller's authenticated GSSAPI
> session, and a connection with no negotiated session is refused rather than run
> as SYSTEM. **Writes are enforced** as that principal — Samba's local `acl`
> module denies a create/modify/delete/rename/password reset the caller lacks the
> right for; the allow/deny pair is asserted against a real directory by
> `tests/dc/test_session_authorization.py`, which needs a provisioned DC and is
> skipped without one. **Reads are not attribute-filtered:** Samba's `acl_read`
> filtering runs only in its LDAP frontend, so a directly opened `SamDB` returns
> attributes a caller's ACLs would hide over LDAP. Reads run as the caller, never
> SYSTEM, but do not enforce per-attribute read rights —
> [#17](https://github.com/HardenSamba/samba-adws/issues/17) tracks that gap.

---

## Contents

- [How it works](#how-it-works)
- [Installing on the Samba DC](#installing-on-the-samba-dc)
- [Checking that it runs](#checking-that-it-runs)
- [From Linux: using the Python client](#from-linux-using-the-python-client)
- [From Windows: querying the directory](#from-windows-querying-the-directory)
- [From Windows: administering](#from-windows-administering)
- [Known limitations](#known-limitations)
- [Documentation](#documentation)

---

## How it works

Protocol stack (bottom → top), entirely on the Linux side, with no .NET binary:

| Layer | Role | Code |
|---|---|---|
| [MS-NMF] | .NET Message Framing | `src/nettcp/nmf.py` |
| GSSAPI / SPNEGO | Kerberos AES via client GSSAPI or server `samba.gensec` | `src/nettcp/stream/gssapi.py` |
| [MS-NBFX/NBFS] | WCF binary XML + dictionary | `src/wcf/` |
| SOAP 1.2 + WS-Addressing | Application envelope | `classes/soap/`, `src/soap/` |
| WS-Transfer / WS-Enumeration / IMDA | CRUD, enumeration, AD data model | `classes/handlers/` |

**Authentication: Kerberos only** (no clear-text password). Directory access goes through the
local `SamDB`, opened **lazily and per process** (the server is a `ForkingTCPServer` because
`python3-samba` is not thread-safe).

---

## Installing on the Samba DC

Since the repository is **already cloned on the Samba domain controller** (Debian/Ubuntu),
everything installs and starts with **a single command**, as `root`:

```bash
cd SambaAD_ADWS        # the cloned directory
sudo tools/installation/install.sh
```

That is all. `install.sh` is idempotent and sovereign (readable bash, no binary): it
installs the system packages through **apt** (**no `pip`, no virtualenv,
no `--break-system-packages`**), registers the `host/<fqdn>` SPN if it is missing, writes the
`/etc/default/samba-adws` configuration, installs and starts the systemd service (rendered from
[`tools/installation/samba-adws.service`](tools/installation/samba-adws.service)) and opens `9389/tcp`.

| Action | Command |
|---|---|
| **Install + start** | `sudo tools/installation/install.sh` |
| **Stop cleanly** | `sudo tools/installation/stop.sh` |
| Restart | `sudo systemctl restart samba-adws` |
| Reconfigure (host/port/log) | edit `/etc/default/samba-adws` then restart |
| Uninstall | `sudo tools/installation/install.sh --uninstall` |
| Follow the logs | `journalctl -u samba-adws -f` |

> **Prerequisite:** a Samba AD DC that is **already provisioned**: `samba-tool domain info "$(hostname -d)"`
> answers and `systemctl is-active samba-ad-dc` returns `active`. Manual startup (debug),
> Kerberos/SPN and variants: [documentation/02-installation.md](documentation/02-installation.md).

---

## Checking that it runs

On the DC:

```bash
ss -tlnp | grep 9389                 # LISTEN 0.0.0.0:9389 (python3)
journalctl -u samba-adws -f          # follow the logs live
```

From a domain-joined Windows workstation:

```powershell
Test-NetConnection samba.local -Port 9389     # raw TCP reachability
Get-ADRootDSE -Server samba.local             # if defaultNamingContext is shown, it works
```

---

## From Linux: using the Python client

After `kinit`, Linux callers can retrieve an object without a command-line
password or a local `SamDB` handle:

```python
from samba_adws.client import ADWSClient

client = ADWSClient("dc1.samdom.example.com")
user = client.get_by_dn(
    "CN=demo,CN=Users,DC=samdom,DC=example,DC=com",
    ("sAMAccountName", "objectGUID"),
)
```

The current public client surface is WS-Transfer Get by distinguished name,
with optional IMDA property projection. Installation, return-value semantics,
typed errors, and server-only actions are documented in
[the Linux client guide](documentation/07-linux-client.md).

> **Authorization:** the server executes directory operations under the caller's
> authenticated session, not SYSTEM
> ([#8](https://github.com/HardenSamba/samba-adws/issues/8)). Writes are
> ACL-enforced as that principal; reads run as the caller but are not
> attribute-filtered by Samba's `acl_read`
> ([#17](https://github.com/HardenSamba/samba-adws/issues/17)), so do not infer
> read rights from a successful read.

---

## From Windows: querying the directory

> **Client prerequisite:** the `ActiveDirectory` RSAT module.
> `Add-WindowsCapability -Online -Name "Rsat.ActiveDirectory.DS-LDS.Tools~~~~0.0.1.0"`
> (Windows 10/11) or `Install-WindowsFeature RSAT-AD-PowerShell` (Server).

### Preparing the session (once)

`-Server` accepts the FQDN (`samba.local`) **or the IP address** of the DC. If the workstation has
no Kerberos ticket for the domain, supply `-Credential`.

```powershell
Import-Module ActiveDirectory

$Server = 'samba.local'                         # or the DC IP, e.g. 192.168.141.10
$cred   = Get-Credential                        # e.g. SAMBA\Administrator

# Make -Server / -Credential / -AuthType implicit for every AD cmdlet.
# (Required in particular for Get-ADRootDSE, which otherwise sends no credential.)
$PSDefaultParameterValues = @{
    '*-AD*:Server'     = $Server
    '*-AD*:Credential' = $cred
    '*-AD*:AuthType'   = 'Negotiate'
}
```

### Reading / information

```powershell
# --- Topology ---
Get-ADRootDSE | Format-List defaultNamingContext, schemaNamingContext, configurationNamingContext
Get-ADDomain  | Format-List Name, DNSRoot, NetBIOSName, DomainSID, DomainMode, PDCEmulator
Get-ADForest  | Format-List Name, ForestMode, GlobalCatalogs
Get-ADDomainController | Format-List Name, HostName, IPv4Address, IsGlobalCatalog

# --- Objects (WS-Transfer Get) ---
Get-ADUser Administrator -Properties *                       # full object
Get-ADUser Administrator -Properties memberOf, lastLogonDate, userAccountControl
Get-ADGroup 'Domain Admins' -Properties *
Get-ADComputer -Filter * | Select-Object Name, DNSHostName, DistinguishedName

# --- Filtered enumerations (Enumerate / Pull / Release) ---
Get-ADUser -Filter *                                         # all users
Get-ADUser -Filter "Enabled -eq 'True'"                      # AND filter
Get-ADUser -LDAPFilter "(|(samAccountName=admin*)(!(userAccountControl:1.2.840.113556.1.4.803:=2)))"
Get-ADObject -Filter * -ResultPageSize 50                    # paged enumeration

# --- Groups ---
Get-ADGroupMember 'Domain Admins'                            # direct members
Get-ADGroupMember <group> -Recursive                         # nested members
Get-ADPrincipalGroupMembership <user>                        # reverse memberships

# --- Accounts / schema ---
Search-ADAccount -AccountDisabled                            # also -Inactive, -LockedOut
$schema = (Get-ADRootDSE).schemaNamingContext
Get-ADObject -SearchBase $schema -LDAPFilter '(objectClass=classSchema)' `
    -ResultPageSize 50 | Select-Object Name -First 10
```

### Graphical consoles: ADAC (`dsac.exe`) and ADUC (`dsa.msc`)

**ADAC (Active Directory Administrative Center) works** against a Samba DC running this module,
on two conditions. Verified 4 September 2026 from a Windows 11 client signed in with a member of
Domain Admins: the domain node lists its containers, `Users` lists every account, a user's
property pages are fully populated, global search answers, and an edit made in a property page
reaches the directory. The server logs every request as the signed-in principal.

1. **The DC must advertise ADWS.** ADAC locates a controller with `DsGetDcName` and the
   `DS_WEB_SERVICE_REQUIRED` flag, and stock Samba never sets the matching `DS_WS` bit in its
   CLDAP answer. The patch in [`patches/samba/`](patches/samba/README.md) adds it, behind
   `adws:advertise = yes` in `smb.conf`. Check from a joined client:

   ```powershell
   nltest /dsgetdc:samba.local /ws /force     # must succeed, with WS among the Flags
   ```

2. **The Windows session must be a domain logon.** `dsac.exe` refuses to start when the process
   token belongs to a local account ("Your account or computer is not joined to any domain"), and
   `runas /netonly` does not help, because that token stays local. Sign in as a domain user, or
   open a real domain logon for the tool from a local session (`CreateProcessWithLogonW` with
   `LOGON_WITH_PROFILE`). Its manifest asks for `highestAvailable`, so an administrator gets a UAC
   prompt; an unattended launcher sets `__COMPAT_LAYER=RunAsInvoker` before starting it.

**ADUC** (`dsa.msc`) speaks **LDAP** directly to Samba, needs neither of the above, and remains
the fallback on a DC without the patch (if needed: right-click the root node →
*Change Domain Controller* → your DC).

---

## From Windows: administering

All these operations are validated (parity battery 18/18). **Domain Admins** rights are required.

```powershell
# --- Users ---
New-ADUser -Name demo -SamAccountName demo -Enabled $true `
    -AccountPassword (ConvertTo-SecureString 'P@ssw0rd!Test123' -AsPlainText -Force)
Set-ADUser demo -Description 'created via sovereign ADWS' -Replace @{title='Engineer'}
Set-ADAccountPassword demo -Reset -NewPassword (ConvertTo-SecureString 'Reset@1234' -AsPlainText -Force)
Enable-ADAccount demo ; Disable-ADAccount demo
Rename-ADObject (Get-ADUser demo).DistinguishedName -NewName demo-renamed
Move-ADObject (Get-ADUser demo-renamed).DistinguishedName -TargetPath '<target_OU_DN>'
Remove-ADUser demo-renamed -Confirm:$false

# --- Groups ---
New-ADGroup -Name appgrp -GroupScope Global
Add-ADGroupMember appgrp -Members userA, userB
Remove-ADGroupMember appgrp -Members userA -Confirm:$false

# --- OU & recursive deletion ---
New-ADOrganizationalUnit -Name Test
Remove-ADObject '<OU_DN>' -Recursive -Confirm:$false        # honors the tree-delete control

# --- Pipeline ---
Get-ADUser -Filter "Department -eq 'QA'" | Set-ADUser -Description 'updated'
```

---

## Known limitations

**None of these points is a server bug:**

1. **Automatic discovery needs the Samba patch.** ADAC (`dsac.exe`), and cmdlets run **without
   `-Server`**, locate a controller with `DS_WEB_SERVICE_REQUIRED`, and stock Samba does not set the
   `DS_WS` flag in its CLDAP answer. Without [`patches/samba/`](patches/samba/README.md) applied and
   `adws:advertise = yes`, `nltest /dsgetdc:samba.local /ws` returns `1355` and ADAC cannot connect.
   With them, both work (verified 4 September 2026, Samba 4.17.12 on Debian 12). Fallbacks without
   the patch: ADUC (`dsa.msc`, LDAP) for the GUI, PowerShell `-Server` on the CLI. Details:
   [06-depannage § 7](documentation/06-depannage.md#7-unable-to-find-a-default-server).
2. **Self-service password change** (`Set-ADAccountPassword`, old → new):
   fails on the Samba side (`Failed to obtain remote address for the LDAP client`). Samba's
   `password_hash` module requires a `remoteAddress` that a local `SamDB` connection cannot
   provide. **The administrative reset (`-Reset`) works.**
3. **`Stress` phase** of the test suite: `ForEach-Object -Parallel` does not exist in Windows
   PowerShell 5.1 (a limitation of the harness, not of the server). Run it under PowerShell 7+, or
   use `-SkipStress`.

Server scope: a single local domain (no inter-forest trusts); the SDDL/`nTSecurityDescriptor`
and binary attributes are returned as raw base64. Details: [01-architecture.md](documentation/01-architecture.md#known-limitations).

---

## Documentation

| File | Topic |
|---|---|
| [01-architecture.md](documentation/01-architecture.md) | Overview, protocol layers, code organization |
| [02-installation.md](documentation/02-installation.md) | Prerequisites, deployment, Kerberos / SPN, uninstallation |
| [03-protocole.md](documentation/03-protocole.md) | Net.tcp, NMF, WCF binary XML, SOAP, IMDA vs WS-Transfer |
| [04-handlers.md](documentation/04-handlers.md) | Supported SOAP actions and how to add new ones |
| [05-tests.md](documentation/05-tests.md) | Windows + server test suite, reading the results |
| [06-depannage.md](documentation/06-depannage.md) | Common errors (Kerberos, empty base DN, SOAP faults) |

For end-to-end validation: [`Test-ADWS-Sovereign.ps1`](tools/test/Test-ADWS-Sovereign.ps1) from the
Windows workstation (see [05-tests.md](documentation/05-tests.md)).

---

## Status

Phases 1 → 4 (CRUD, LDAP search, group operations, PowerShell/ADAC compatibility)
**complete**. Phase 5 (performance + security hardening) **in progress**.

## License

synetis
