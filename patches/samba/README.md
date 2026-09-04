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

Verified on Debian 13 (trixie) against `samba_4.22.10+dfsg-0+deb13u2`, which is
what the appliance runs. It was first verified on Debian 12 with Samba 4.17.12;
the differences between the two are recorded below, because the older recipe
does not work here.

```console
# apt-get build-dep -y samba
# apt-get source samba=2:4.22.10+dfsg-0+deb13u2
# cd samba-4.22.10+dfsg
# patch -p1 < .../0001-advertise-adws-in-the-cldap-netlogon-response.patch
patching file source4/dsdb/samdb/ldb_modules/netlogon.c
Hunk #1 succeeded at 303 (offset 9 lines).
# DEB_BUILD_OPTIONS=parallel=6 debian/rules build
```

Six minutes on twenty cores. The anchor held across five Samba releases, and
`lp_ctx` is still a parameter of `fill_netlogon_samlogon_response`, which is
what the call needs.

### Which files to replace, and how to know

`fill_netlogon_samlogon_response()` is compiled into a static subsystem. There
is no single module to swap: it is linked into several installed artefacts and
all of them have to move together. **Do not copy the list from a previous
release.** On 4.22.10 one of the three from 4.17 does not exist at all —
`libdsdb-module-samba4.so.0` is now `libdsdb-module-private-samba.so.0`.

Derive it from the build instead. `debian/tmp` is what the package installs,
already at the right path and with the soname the installed tree expects, so
there is no mapping to get wrong:

```console
# cd samba-4.22.10+dfsg
# find debian/tmp -type f \( -name '*.so' -o -name '*.so.*' \) |
    while read -r f; do
        n=$(nm -a "$f" 2>/dev/null | grep -c fill_netlogon_samlogon_response)
        [ "$n" -gt 0 ] && echo "${f#debian/tmp}"
    done
/usr/lib/x86_64-linux-gnu/samba/ldb/rootdse.so
/usr/lib/x86_64-linux-gnu/samba/libdsdb-module-private-samba.so.0
/usr/lib/x86_64-linux-gnu/samba/service/nbtd.so
```

Count the matches rather than testing with `grep -q`: under `set -o pipefail`,
`grep -q` closes the pipe on its first match, `nm` takes a `SIGPIPE`, and the
pipeline reports failure precisely when the symbol *is* there.

Copy each to the same path on the controller, keep the originals — a copy of
each is the whole rollback — and `systemctl restart samba-ad-dc`.

## Checking that it worked

Two measurements, one on each side. Both were taken on the appliance,
`HARDENSAMBA.LAB`, Samba `4.22.10-Debian-4.22.10+dfsg-0+deb13u2`, by taking the
setting away and putting it back.

**On the controller**, the CLDAP netlogon response read through Samba's own
locator, which is the field the patch changes:

| `adws:advertise` | `server_type` | `NBT_SERVER_ADS_WEB_SERVICE` (0x2000) |
|---|---|---|
| absent | `0x000013fd` | not set |
| `yes` | `0x000033fd` | set |

**On a joined Windows client**, which is the only thing that proves the locator
filter, because that filter runs there and not on the controller:

```console
> nltest /dsgetdc:HARDENSAMBA.LAB /ws /force
```

| `adws:advertise` | Result |
|---|---|
| absent | `Status = 1355 0x54b ERROR_NO_SUCH_DOMAIN`, exit 1 |
| `yes` | the controller, `WS` last in `Flags`, exit 0 |

`/force` matters: without it the client answers from its cached locator result
and says nothing about what the controller advertises now.

Two ways to fool yourself, both hit while taking these:

- **Asking `finddc` by address proves nothing.** Given an address it sends a
  CLDAP ping straight at that host and returns whatever answers; the flags are
  a request, not a filter. It returned this controller with the bit clear. Read
  `server_type` from the reply instead.
- **`-match 'WS'` in PowerShell is case-insensitive**, so it matched the `/ws`
  in the echoed command line and reported the flag present on a run that had
  just failed with `ERROR_NO_SUCH_DOMAIN`. Read it off the `Flags:` line, with
  `-cmatch`.

## What it gives, verified

Advertising the capability is not the same as serving it, and for a while the
two did not meet: with the flag set, `Get-ADDomain` without `-Server` reached
this module and failed in its GSSAPI negotiation (#14). That was not reproduced
on 4 September 2026: from a Windows 11 client signed in as a member of Domain
Admins, against Samba 4.17.12 on Debian 12 with this patch and #8 in place, the
negotiation completed with Kerberos, the server logged every request as
`SAMBA\<user>`, and the Administrative Center opened the domain, listed its
containers and accounts, showed full property pages, answered a global search,
and wrote an edit back to the directory.

Two conditions remain on the client, neither of them this patch's business.
The Windows session must be a domain logon: ADAC refuses a local account before
any network call, and `runas /netonly` does not change the token it looks at.
And `dsac.exe` asks for `highestAvailable`, so an administrator gets a UAC
prompt unless the launcher sets `__COMPAT_LAYER=RunAsInvoker` first.

## Keeping it alive

This patch is applied outside the Debian package, so an update of `samba`
overwrites the libraries and the announcement silently stops, while the
`smb.conf` line stays exactly where it was. **The presence of the line is not
evidence that the announcement works.** Two things follow:

- pin or hold `samba`, or rebuild after every upgrade;
- re-derive the file list on every Samba release, not just the patch. The
  anchor has held so far, but the set of installed artefacts carrying the code
  has already changed once between 4.17 and 4.22, silently: copying the older
  list gives two files that exist and one that does not, and a controller that
  still does not advertise.

`samdb_server_type()`, named in most write-ups on this subject, does not exist
in Samba at all. Neither does the `0x00100000` those write-ups give as the
server-side bit; that value is `DS_WEB_SERVICE_REQUIRED`, which is what the
client sends.
