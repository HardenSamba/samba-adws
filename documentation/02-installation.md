# Installation and deployment

## 1. Prerequisites

### Server side (Linux)

- **Distribution**: Debian 11/12 or Ubuntu 22.04+ recommended.
- **Samba AD**: a **working** domain with functional level ≥ 2008R2. Check with:
  ```bash
  sudo samba-tool domain info $(hostname -d)
  ```
- **Python**: 3.9 or newer.
- **System packages** (all runtime dependencies; **no `pip`**):
  ```bash
  sudo apt-get update
  sudo apt-get install -y \
      python3 python3-samba python3-gssapi \
      samba-common-bin krb5-user
  ```
  `python3-samba` provides `samba`+`ldb`, `python3-gssapi` provides `gssapi`,
  `samba-common-bin` provides `samba-tool`. The server has **no** pip
  dependency: never run `pip install samba`/`ldb`, and never use `--break-system-packages`.
  The package (§3) or the `install.sh` script (§4) installs these packages for you.

### Client side (Windows)

- Windows 10/11 or Windows Server 2019/2022, joined to the domain (or with a DNS mapping to `samba.local`).
- **ActiveDirectory** PowerShell module:
  ```powershell
  Add-WindowsCapability -Online -Name "Rsat.ActiveDirectory.DS-LDS.Tools~~~~0.0.1.0"
  ```

### Network

- The client must be able to resolve **the FQDN of the DC** (for example `samba.local`) to an IP address, either through DNS or through `C:\Windows\System32\drivers\etc\hosts`.
- Ports open from the client to the DC:
  | Port | Service |
  |---|---|
  | 88/tcp+udp | Kerberos |
  | 389/tcp | LDAP |
  | 636/tcp | LDAPS (optional) |
  | **9389/tcp** | **ADWS (this project)** |

  ```bash
  sudo ufw allow 9389/tcp
  ```

## 2. Kerberos configuration

ADWS requires GSSAPI/Kerberos authentication, **not** a plaintext password.

### Minimal `/etc/krb5.conf` on the DC

```ini
[libdefaults]
    default_realm = SAMBA.LOCAL
    dns_lookup_realm = false
    dns_lookup_kdc = true

[realms]
    SAMBA.LOCAL = {
        kdc = samba.local
        admin_server = samba.local
    }

[domain_realm]
    .samba.local = SAMBA.LOCAL
    samba.local = SAMBA.LOCAL
```

### Check that the DC is its own KDC

```bash
kinit Administrator@SAMBA.LOCAL
klist
```

If `klist` shows a ticket for `krbtgt/SAMBA.LOCAL@SAMBA.LOCAL`, Kerberos is working.

### Register the required SPNs

PowerShell requests a ticket for `host/<dc-fqdn>`. **If that SPN is not registered on the machine account of the DC, authentication fails with `STATUS_NO_SUCH_USER`** (see [06-depannage.md](06-depannage.md)).

List the current SPNs:
```bash
sudo samba-tool spn list "$(hostname -s)$"
```

Add the missing ones:
```bash
sudo samba-tool spn add "host/$(hostname -f)" "$(hostname -s)$"
sudo samba-tool spn add "HOST/$(hostname -f)" "$(hostname -s)$"
```

## 3. The Debian package (recommended)

The repository carries its own `debian/`, so the service installs the way
anything else on a Debian controller does, and `apt` resolves the dependencies.

```bash
git clone https://github.com/HardenSamba/samba-adws.git
cd samba-adws
dpkg-buildpackage -us -uc -b          # needs debhelper and dh-python
sudo apt install ../samba-adws_*.deb
```

What the package installs, and where — checked against `MODULE.yaml` field by
field by `tests/test_packaging.py`, because the two files drift and the drift
is invisible until a machine installs the package:

| What | Where |
|---|---|
| the service and the client | `/usr/share/samba-adws/` (a payload, not the Python path: the tree is two sibling top-level packages, `src` and `classes`, and neither name may be claimed in a shared `site-packages`) |
| the unit | `/lib/systemd/system/samba-adws.service` |
| the command | `/usr/bin/samba-adws` — `run`, `check`, `patch-samba`, `--version`, and every client verb (`naming-context`, `search`, `status`) |
| the Samba patch and the script that applies it | `/usr/share/samba-adws/patches/samba/` and `/usr/share/samba-adws/tools/installation/patch-samba.sh` (§7) |
| the configuration | `/etc/hardensamba/samba-adws/samba-adws.conf`, a conffile (§3.1) |
| the log | `/var/log/samba-adws/adws.log`, in a directory systemd creates |

**The unit is installed and left disabled**, on every controller. Contract 4.2
makes enabling a unit the administrator's explicit action, and the service
needs two things the package cannot provide: a provisioned directory and the
host service principal (§2). The installation says so on standard error; once
both exist, enable it:

```bash
sudo systemctl enable --now samba-adws
```

An upgrade restarts a running service onto the new code and leaves a stopped
one stopped. (An earlier `postinst` enabled and started the service where
`/var/lib/samba/private/sam.ldb` existed; measured on a provisioned Debian 13
controller, it never did: debhelper's own snippet records the unit's state
first, `deb-systemd-helper enable` defers to that record, and
`deb-systemd-invoke` does not start a unit that is not enabled.)

**The SPN is the one manual step.** A maintainer script cannot assume the
directory is up, or that it may write to it, so the package does not register
`host/<fqdn>` on the machine account. Do it once (§2, *Register the required
SPNs*); the from-checkout installer below does it for you.

**Upgrading from the installer.** An installation made with an earlier
`install.sh` wrote `/etc/default/samba-adws` and rendered a unit under
`/etc/systemd/system/`. The package's unit reads that file first and the
conffile second, and the conffile wins where both name a variable — as
shipped it names all five, so a setting changed in the old file does not
take effect until it is carried into `/etc/hardensamba/samba-adws/samba-adws.conf`
by hand. A unit in `/etc/systemd/system/` shadows the package's; today's
`install.sh` removes that unit when it finds it, and its `--uninstall` does
too. Before installing the package over a script installation of any version,
take the script's files away first:

```bash
sudo tools/installation/install.sh --uninstall     # the package's paths and the old unit
sudo apt install ../samba-adws_*.deb
```

Removing the package (`apt remove`) stops and removes the service and the
command; purging it (`apt purge`) also removes the conffile. The logs are kept
either way, and the SPN is left in the directory: it belongs to the domain.

### 3.1 The configuration file

`/etc/hardensamba/samba-adws/samba-adws.conf` — the package's conffile, the
path `MODULE.yaml` declares — holds every setting the service reads. The
installer script installs the same file at the same path (and keeps one that
is already there). An installer of an earlier version wrote the same variables
to `/etc/default/samba-adws` instead; the unit still reads that file first if
it exists, but the conffile is read second and wins where both name a
variable, and as shipped it names all five - so a setting from that file only
takes effect once it is carried into the conffile. A change takes effect on
`systemctl restart samba-adws`, not before.

| Variable | Default | Meaning |
|---|---|---|
| `ADWS_HOST` | `0.0.0.0` | Address the listener binds. |
| `ADWS_PORT` | `9389` | Port. 9389 is the port Microsoft assigns to ADWS; a client will not look elsewhere. |
| `ADWS_LOG_FILE` | `/var/log/samba-adws/adws.log` | Rotating log file. |
| `ADWS_LOG_LEVEL` | `INFO` | `DEBUG` adds the record-by-record protocol trace. |
| `ADWS_MAX_MESSAGE_SIZE` | `1048576` (1 MB) | Ceiling on any length a client announces, in bytes. |

`ADWS_MAX_MESSAGE_SIZE` bounds what an unauthenticated peer can make the server
allocate. Two of the lengths read on a connection — the `Via` address and the
upgrade protocol name — arrive before any credential has been presented, and
without a ceiling each is read in full at the announced size. A connection that
announces more than the ceiling is closed, with one line in the log naming the
client and the size; the client sees the connection drop rather than a SOAP
fault, because at that layer there is no message to relate a fault to.

The default matches the `MaxReceivedMessageSize` of the Windows ADWS service,
documented by Microsoft as 1 MB, so a client that works against a Windows
domain controller works against this one. Raise it only if a legitimate request
is refused, and read
[Troubleshooting § 10](06-depannage.md#10-a-connection-is-closed-on-the-announced-size)
first.

## 4. From a checkout: the installer script

```bash
git clone https://github.com/HardenSamba/samba-adws.git
cd samba-adws
sudo tools/installation/install.sh
```

`install.sh` is **idempotent** and **sovereign** (readable bash, no binaries),
for a controller with no access to a package archive. It puts the package's
files at the package's paths - the table in §3, byte-compiled the way
`dh_python3` does it - and prints each path on standard output, which is how
CI holds it to the package: the list is diffed against `dpkg -L samba-adws`.
In order, it:

1. refuses to run where `dpkg` knows the package (installed, or removed but
   not purged): those files are `dpkg`'s to manage, `apt purge` first;
2. installs the system packages (§1), with no `pip` and no virtualenv;
3. copies the service and the client under `/usr/share/samba-adws`, installs
   the command, the import shim, the unit, the configuration file (kept if one
   is there), the manual page and the documentation;
4. removes a unit an earlier installer rendered under `/etc/systemd/system/`,
   which would shadow the package's;
5. registers the `host/<fqdn>` SPN on the machine account of the DC if it is
   missing - the one step a checkout installation has no packaging to leave to;
6. enables nothing (contract 4.2), and says so.

Then, as after the package: `sudo systemctl enable --now samba-adws`, and open
`9389/tcp` in the firewall yourself. To uninstall:
`sudo tools/installation/install.sh --uninstall` (takes every installed file
away, the configuration file included; keeps the logs, leaves the SPN in AD).
To reconfigure: edit `/etc/hardensamba/samba-adws/samba-adws.conf`, then run
`sudo systemctl restart samba-adws`.

## 5. Manual start (debug): under the hood

`install.sh` is nothing more than the automation of the following; to start the
server by hand during development:

```bash
sudo python3 -m src.main
```

Expected output:
```
============================================================
SambaAD ADWS Server Starting
============================================================
NMF protocol registered
[LDB] Backend verification passed
ADWS server started on 0.0.0.0:9389
```

The unit `install.sh` installs is the package's own,
[`debian/samba-adws.service`](../debian/samba-adws.service)
(`EnvironmentFile=-/etc/hardensamba/samba-adws/samba-adws.conf`,
`Requires=samba-ad-dc.service`).
Status and manual activation:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now samba-adws
sudo systemctl status samba-adws
```

Live logs:
```bash
sudo journalctl -u samba-adws -f
```

## 6. Verification

### From the DC

```bash
ss -tlnp | grep 9389
# Should display: LISTEN ... 0.0.0.0:9389 ... python3
```

### From Windows

```powershell
# Raw TCP test
Test-NetConnection samba.local -Port 9389

# Functional ADWS test
Get-ADRootDSE -Server samba.local
```

If `Get-ADRootDSE` returns an object containing `defaultNamingContext`, the deployment is validated.

### Full test suite

See [05-tests.md](05-tests.md) for `Test-ADWS-Sovereign.ps1`, which covers reads, mutations, groups, schema and stress.

## 7. Making the Administrative Center find the controller

Installing the service is not enough for ADAC (`dsac.exe`): the controller must also announce
ADWS in its CLDAP netlogon reply, and stock Samba cannot. One command on the controller rebuilds
Debian's samba with the patch this repository carries, installs it, and reads the reply back:

```bash
sudo samba-adws patch-samba                 # from the package
sudo tools/installation/patch-samba.sh      # from a checkout
```

It takes tens of minutes and about 4 GB under `/var/tmp`. [08-adac.md](08-adac.md) is the page
for it: what it does, `--check`, what a Samba security update does to it, and the two conditions
on the Windows side.

## No virtualenv, no pip

The server has **no pip dependency**: all runtime dependencies are system
packages (`python3-samba`, `python3-gssapi`) installed by the package (§3) or by `install.sh` (§4). There is no need to
create a virtualenv or to use `pip --break-system-packages`.

## Uninstallation

Installed from the package:

```bash
sudo apt purge samba-adws             # stops and removes the service, the command and the conffile; keeps the logs
```

Installed from a checkout with the script:

```bash
sudo tools/installation/install.sh --uninstall        # stops and removes the service, the command, the code under /usr/share/samba-adws and the configuration file; keeps the logs, leaves the SPN
sudo rm -rf samba-adws                # the clone, if desired
sudo ufw delete allow 9389/tcp        # if you opened it
```

No change is made to the AD schema or to the Samba objects; uninstalling the ADWS server does not break the domain.
