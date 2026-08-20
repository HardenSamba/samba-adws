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
  The `install.sh` script (§3) installs these packages for you.

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

## 3. One-command installation (recommended)

```bash
cd /root
git clone <url-du-depot> SambaAD_ADWS
cd SambaAD_ADWS
sudo tools/installation/install.sh
```

`install.sh` is **idempotent** and **sovereign** (readable bash, no binaries).
It chains together everything this document used to describe doing by hand:

1. installs the system packages (§1), with no `pip` and no virtualenv;
2. registers the `host/<fqdn>` SPN on the machine account of the DC if it is missing;
3. writes `/etc/default/samba-adws` (host/port/log, read by the service);
4. renders and installs the systemd unit from `tools/installation/samba-adws.service`
   (`WorkingDirectory` = the cloned directory);
5. starts the service (`enable --now`) and opens `9389/tcp` in ufw.

To uninstall: `sudo tools/installation/install.sh --uninstall` (keeps the logs, leaves the SPN
in AD). To reconfigure: edit `/etc/default/samba-adws`, then run
`sudo systemctl restart samba-adws`.

### 3.1 The environment file

`/etc/default/samba-adws` holds every setting the service reads. A change takes
effect on `systemctl restart samba-adws`, not before.

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

## 4. Manual start (debug): under the hood

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

The unit installed by `install.sh` is rendered from the versioned template
[`tools/installation/samba-adws.service`](../tools/installation/samba-adws.service)
(`EnvironmentFile=-/etc/default/samba-adws`, `Requires=samba-ad-dc.service`).
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

## 5. Verification

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

## No virtualenv, no pip

The server has **no pip dependency**: all runtime dependencies are system
packages (`python3-samba`, `python3-gssapi`) installed by `install.sh` (§3). There is no need to
create a virtualenv or to use `pip --break-system-packages`.

## Uninstallation

```bash
sudo tools/installation/install.sh --uninstall        # stops and removes the service (keeps the logs, leaves the SPN)
sudo rm -rf /root/SambaAD_ADWS        # removes the code if desired
sudo ufw delete allow 9389/tcp        # if not already removed by --uninstall
```

No change is made to the AD schema or to the Samba objects; uninstalling the ADWS server does not break the domain.
