# The Samba patch this module needs

This module answers on 9389, but nothing tells a Windows client that the
controller has an ADWS server. That announcement is made by Samba, in a code
path this module cannot reach, so it is carried here as a patch to Samba
rather than as code of our own.

Without it, the module is reachable only by a caller that names the server
explicitly. The Active Directory Administrative Center has no such option, and
the ActiveDirectory PowerShell module used without `-Server` has none either:
both go through the domain controller locator, which filters on the flag.

## What the client actually asks for

A client looking for an ADWS controller calls `DsGetDcName` with
`DS_WEB_SERVICE_REQUIRED`. That flag is `0x00100000`, and it belongs to
`netr_DsRGetDCName_flags` — it is what the *client sends*, not what the server
answers.

The controller answers over CLDAP on UDP 389 with a netlogon response whose
`server_type` field is a `netr_DsR_DcFlags` bitmap. The bit that means "this
controller speaks ADWS" is `DS_SERVER_WEBSERV`, and it is `0x00002000`.

The two live in the same file and are easy to confuse:

```
librpc/idl/netlogon.idl:1184   DS_WEB_SERVICE_REQUIRED = 0x00100000
librpc/idl/netlogon.idl:1210   DS_SERVER_WEBSERV       = 0x00002000
```

Both constants already exist, as does `NBT_SERVER_ADS_WEB_SERVICE = 0x00002000`
in `librpc/idl/nbt.idl`. **No IDL change and no `pidl` regeneration is needed.**

Verifiable on any Samba DC without fetching the source:

```console
# python3 -c "from samba.dcerpc import nbt; print(hex(nbt.NBT_SERVER_ADS_WEB_SERVICE))"
0x2000
```

## Enabling it

The patch does nothing until `smb.conf` says so:

```ini
[global]
    adws:advertise = yes
```

It is off by default on purpose. A controller that advertises ADWS with nothing
listening on 9389 is worse than one that stays quiet: the client locates it,
connects, and fails, rather than moving on. Turn it on only where this module
runs.

`smb.conf` belongs to `samba-dc-role` under contract 3.1, so placing that line
is tracked there rather than done from here.

## Building a patched Samba

Verified against `samba_4.17.12+dfsg-0+deb12u4` on Debian 12.

```console
# apt-get build-dep -y samba
# apt-get source samba
# cd samba-4.17.12+dfsg
# patch -p1 < .../0001-advertise-adws-in-the-cldap-netlogon-response.patch
# DEB_BUILD_OPTIONS=parallel=4 debian/rules build
```

`fill_netlogon_samlogon_response()` is compiled into the `DSDB_MODULE_HELPERS`
subsystem, which is static. There is no single module to swap: it is linked
into three installed artefacts, and all three have to be replaced.

| Built | Installed |
|---|---|
| `bin/default/source4/nbt_server/libservice_module_nbtd.inst.so` | `/usr/lib/$(DEB_HOST_MULTIARCH)/samba/service/nbtd.so` |
| `bin/default/source4/dsdb/samdb/ldb_modules/libldb_module_rootdse.inst.so` | `/usr/lib/$(DEB_HOST_MULTIARCH)/samba/ldb/rootdse.so` |
| `bin/default/source4/dsdb/samdb/ldb_modules/libdsdb-module-samba4.inst.so.0` | `/usr/lib/$(DEB_HOST_MULTIARCH)/samba/libdsdb-module-samba4.so.0` |

Use the `.inst` variants: they carry the runtime path and soname the installed
tree expects. Keep the originals — a copy of each is the whole rollback.

Then `systemctl restart samba-ad-dc`.

## Checking that it worked

From a joined Windows machine:

```console
> nltest /dsgetdc:example.local /ws
```

Before, the locator finds nothing:

```
Status = 1355 0x54b ERROR_NO_SUCH_DOMAIN
```

After, it returns the controller and `WS` appears at the end of the flags:

```
Indicateurs : PDC GC DS LDAP KDC TIMESERV GTIMESERV WRITABLE DNS_DC
              DNS_DOMAIN DNS_FOREST CLOSE_SITE FULL_SECRET WS
```

The PowerShell module confirms it by the way its failure changes. Before, it
cannot find a server at all:

> Unable to find a default server with Active Directory Web Services running.

After, it locates the controller and gets as far as authenticating.

## What this does not do

Advertising the capability is not the same as serving it. With the flag set,
`Get-ADDomain` without `-Server` now reaches this module and fails in its
GSSAPI negotiation, because the server accepts NTLM and refuses Kerberos while
the locator always returns a name. That defect is tracked in #14 and is what
still stands between this module and a working Administrative Center.

## Keeping it alive

This patch is applied outside the Debian package, so an update of `samba`
overwrites the three libraries and the announcement silently stops. Two things
follow:

- pin or hold `samba`, or rebuild after every upgrade;
- revalidate on the target Debian release. This was verified on bookworm with
  Samba 4.17, which is oldstable, while `MODULE.yaml` declares a minimum of
  4.19. The anchor the patch attaches to has moved between Samba releases
  before, and `samdb_server_type()` — named in most write-ups on the subject —
  does not exist here at all.
