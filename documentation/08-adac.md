# Making the Administrative Center find a Samba controller

The Active Directory Administrative Center (`dsac.exe`, "ADAC") is the one RSAT console that speaks
nothing but ADWS. Against a Samba controller running this module it works: the domain tree, every
container, fully populated property pages, global search, and edits that reach the directory
(verified 4 September 2026 from a Windows 11 client, Samba 4.17.12 on Debian 12). But it does not
work by installing the module alone, and this page is the shortest path from a stock Samba
controller to an ADAC that opens.

Two things stand between them, one on each side.

| Side | Condition | Section |
|---|---|---|
| Controller | It must **announce** ADWS in its CLDAP netlogon reply, and stock Samba cannot | [§ 1](#1-the-controller-must-announce-adws), [§ 2](#2-the-one-command-fix) |
| Windows client | The console must run under a **domain logon**, with UAC handled | [§ 4](#4-opening-the-console-on-the-client) |

## 1. The controller must announce ADWS

ADAC does not connect to the controller you point it at; it asks Windows for one. That call is
`DsGetDcName` with the flag `DS_WEB_SERVICE_REQUIRED`, and the locator keeps a controller only if
the netlogon reply it gets over CLDAP (udp/389) carries `DS_SERVER_WEBSERV` (`0x2000`). Stock Samba
never sets that bit, because Samba has no ADWS of its own. So a Samba controller with this module
answers on tcp/9389 and stays invisible: the client reports that no server running Active
Directory Web Services could be found, and never opens a connection.

The bit is set by eight lines of C in Samba's netlogon module, shipped in
[`patches/samba/`](../patches/samba/README.md) and switched on by `adws:advertise = yes` in
`smb.conf`. There is no way to set it from outside Samba: no `smb.conf` option of stock Samba, no
LDAP attribute, no registry key. The controller's Samba has to be rebuilt with the patch, and that
is what the command in § 2 does.

Two situations need nothing from this page:

- a controller installed from the **HardenSamba appliance image** already runs the patched Samba
  (`make samba` builds it into the image, and `tests/appliance-check.sh` verifies the bit on every
  run);
- **ADUC** (`dsa.msc`) and cmdlets run with **`-Server`** talk to the controller directly and never
  ask the locator. They are the fallback on a controller that cannot be rebuilt.

## 2. The one-command fix

On the controller, as root. From the Debian package:

```console
# samba-adws patch-samba
```

From a checkout of this repository:

```console
# tools/installation/patch-samba.sh
```

It rebuilds Debian's own `samba` source package with the patch added and installs the result, so
that afterwards `dpkg` still owns every file and `apt` still knows what is installed. Nothing is
copied over a library by hand. Step by step, it:

1. adds a `deb-src` line if the system has none, derived from the existing `deb` lines
   (`/etc/apt/sources.list.d/samba-adws-src.list`, safe to delete afterwards);
2. installs Samba's build dependencies. There are several hundred; `apt-get build-dep` marks them
   automatically installed, so `apt-get autoremove` takes them away once the build is done;
3. fetches the source of the **installed** Samba version, so that the rebuild is what runs today
   plus the patch and nothing else. If the archive has moved past it, the current version is taken
   and said so: the rebuilt set replaces the installed one wholesale, so a newer base is an upgrade,
   not a mix;
4. adds the patch to `debian/patches/series` and checks that it applies **before** spending the
   build time;
5. gives the package a local version, `<installed version>+adws1`;
6. builds, with as many parallel jobs as the memory allows (about 1.2 GB per job);
7. proves with `nm` and `strings` that every built library carrying the netlogon function also
   carries the patch's parameter string, and stops if one does not;
8. installs every rebuilt package whose name is already installed, in one `apt-get` call, because
   Debian's samba packages pin each other to an exact version and cannot move one at a time;
9. adds `adws:advertise = yes` under `[global]` if it is not there (backup in
   `smb.conf.samba-adws.bak`), restarts `samba-ad-dc` and, if it is running, `samba-adws`;
10. reads the controller's own netlogon reply and prints whether the bit is set.

What it needs: Debian or Ubuntu, root, about 4 GB free under `/var/tmp`, the Debian archive
reachable, and time. The build is the long part: six minutes on twenty cores, and on the lab
controller (a VM with 8 cores and 3.8 GB, which the script turned into 2 jobs) the same build ran
for 64 hours wall-clock, most of it waiting for a starved host. The service keeps answering
throughout; only the final `apt-get install` and the restart of `samba-ad-dc` interrupt the
directory, for the seconds they take. A run that stops after the build, for whatever reason, does
not cost it again: the next run finds the packages under `/var/tmp/samba-adws-patch/<version>/`
and goes on from the verification. Delete that directory to force a rebuild.

Three switches:

| Switch | Effect |
|---|---|
| `--check` | Reports the state (§ 3) and changes nothing |
| `--no-install` | Builds and verifies, installs nothing; the packages stay in `/var/tmp/samba-adws-patch/<version>/` |
| `--revert` | Puts Debian's stock packages back (§ 6) |

## 3. Checking that it worked

On the controller:

```console
# samba-adws patch-samba --check
[*] samba package version: 2:4.17.12+dfsg-0+deb12u4+adws1
[+] this is a build of this script (carries +adws)
[*] last rebuild by this script: samba=2:4.17.12+dfsg-0+deb12u4+adws1 built=2026-09-11T10:55:57Z
[+] smb.conf carries adws:advertise = yes
[+] the controller announces ADWS: server_type 0x000033fd
[*] from a joined Windows client, the proof is:  nltest /dsgetdc:<realm> /ws /force
```

The line that matters is the one about the netlogon reply. It is read through Samba's own locator
from the controller itself, and it is the field a Windows client reads; the configuration line is
not evidence of anything, since stock Samba reads it and does nothing. `0x33fd` is a `server_type`
with `0x2000` set.

From a **joined** Windows client, as any domain user:

```powershell
nltest /dsgetdc:samba.local /ws /force
```

It must succeed and list `WS` among the flags. `/force` matters: without it the client answers
from its locator cache and says nothing about what the controller announces now. Error `1355`
(`ERROR_NO_SUCH_DOMAIN`) with `/ws`, while the same command without `/ws` succeeds, means the
controller is not announcing.

The rebuilt packages are what `dpkg` now owns: `dpkg -V samba-libs samba-dsdb-modules` reports
nothing, where a library copied by hand shows as modified.

## 4. Opening the console on the client

With the controller announcing, ADAC still has two client-side conditions, both of which produce
their own error before any network call.

**The Windows session must be a domain logon.** `dsac.exe` checks the process token first, and a
token that belongs to a local account makes it stop with *"Your account or computer is not joined
to any domain"*, even on a joined machine and even with `runas /netonly`, whose token stays local.
Sign in as a domain user, or start the console inside a real domain logon from a local session:
`CreateProcessWithLogonW` with `LOGON_WITH_PROFILE`, which is what a PowerShell launcher can do
with `Get-Credential` and a P/Invoke.

**UAC.** The console's manifest asks for `highestAvailable`, so an administrator gets an elevation
prompt at every start. A launcher that must not prompt sets the environment variable
`__COMPAT_LAYER=RunAsInvoker` before starting `dsac.exe`; the console then runs with the token it
was given.

`runas /trustlevel` does not help with either. Once both conditions hold, ADAC opens on the
domain node without being told which controller to use, and the server logs every request under
the principal that signed in.

### What was verified from the console

On 11 September 2026, from a Windows 11 client, signed in as a member of Domain Admins, driving
`dsac.exe` itself (its dialogs, not the cmdlets it generates), against samba-adws 1.0.1 on Samba
4.17.12 rebuilt as above. Every operation was checked afterwards in the directory and in the
server log, which showed no fault:

| In the console | What the server received | Result |
|---|---|---|
| *New > Organizational unit*, protected from accidental deletion (the default) | `Create`, then `Put` of `nTSecurityDescriptor` | OU present, `ProtectedFromAccidentalDeletion` true |
| *New > Computer* | `Create`, `SetPassword` (random 120-character password), `Put` enabling it | `userAccountControl` 4096, password set |
| *New > User* with a password | `Create` (514), `SetPassword`, `Put` enabling it, `Put` of the security descriptor, `Put` of `pwdLastSet = 0` | enabled, must change password at next logon |
| *New > User* with the password boxes left empty | `Create` (514), the two `Put` | disabled, no password: ADAC's own behaviour, the same as on Windows |
| *New > Group*, universal, security | `Create` | `Universal/Security` |
| *Properties* of a user, office and description changed | `Put` | both attributes written |
| *Disable*, then *Enable* | two `Put` of `userAccountControl` | 514, then 512 |
| *Add to group…*, through the Windows object picker | `Put` of `member` | member present |
| *Delete* | `Delete` | object gone |

Two things the same session established that are not the server's doing. A user or computer
that is protected from accidental deletion cannot be moved either, on Windows as here: clear the
protection first. And adding an account to its own primary group (`Domain Users` for a user)
is refused with *already set via primaryGroupID*, as Windows refuses it.

Rights are the directory's, not the console's. From the same client, a plain domain user was
refused the creation of a user and of a computer and the modification of another user
(`insufficient access rights`); once granted *create/delete user objects* and *write user
properties* on one OU with `samba-tool dsacl set`, the same account could create and modify users
there and was still refused computers. ADWS runs every request as the principal that
authenticated it, so the console shows exactly the rights the account has.

Mandatory attributes follow Windows: a user or a group created without `sAMAccountName` gets a
generated one (`$96F0A53C-885AEFE01311E1D2`), a computer whose `sAMAccountName` lacks the trailing
`$` gets it added, a duplicate `sAMAccountName` and an attribute the schema does not know are
refused with the server's message, and an empty password is refused.

Replication was not exercised: the lab has one controller (`samba-tool drs showrepl` lists no
partner). What the console writes goes through Samba's own LDB modules, the same path
`samba-tool` and LDAP take, so a second controller receives it the way it receives any other write;
that claim is Samba's, not this module's, and it was not measured here.

## 5. After a Samba update

The rebuilt package is versioned `<Debian version>+adws1`, which sorts **below** the next Debian
revision on purpose. When Debian publishes a security update of samba, `apt upgrade` takes it, the
patched libraries are replaced, and the announcement stops while the `smb.conf` line stays exactly
where it was. That is the intended trade: a controller that refuses security updates to keep a
locator flag is worse than one that loses the flag.

After such an upgrade, `samba-adws patch-samba --check` says `this is a stock build` and the
netlogon line turns to `does NOT announce`; run `samba-adws patch-samba` again and it rebuilds the
new version. The script does not hold the packages, and this page does not recommend doing so.

## 6. Going back

```console
# samba-adws patch-samba --revert
```

Reinstalls, at their stock version, every package that carries `+adws`, and restarts
`samba-ad-dc`. It needs the archive to still offer that version; when the archive has moved on,
the way back is the way forward: `apt-get upgrade` installs the newer stock samba. The
`adws:advertise` line stays in `smb.conf`, read by nothing, and the module keeps answering on
tcp/9389 for `-Server` clients.

## 7. When it does not go through

- `the patch does not apply to samba <version>`: the source has moved under the patch. It has held
  from 4.17 to 4.22 so far; [`patches/samba/README.md`](../patches/samba/README.md) describes the
  anchor and how to re-derive it.
- `the build failed; see /var/tmp/samba-adws-patch/<version>/build.log`: the last lines of that
  log name the failing step. A build killed without a message is usually memory; run it again with
  nothing else on the machine, since the job count is derived from the memory available at start.
- `no built artefact carries the netlogon function`: the function was found in none of the built
  libraries, which means the set of artefacts carrying it changed in this Samba release. The same
  README covers it; the script refuses to install rather than install something it could not prove.
- The controller announces, `nltest ... /ws /force` succeeds, and ADAC still says no server was
  found: the client's DNS does not resolve the domain's SRV records to this controller, or a
  firewall drops tcp/9389. [06-depannage § 7](06-depannage.md#7-unable-to-find-a-default-server)
  walks the ladder from the bottom.
