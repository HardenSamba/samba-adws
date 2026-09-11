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

Everything in this section is done by one command,
[`tools/installation/patch-samba.sh`](../../tools/installation/patch-samba.sh)
(`samba-adws patch-samba` once the package is installed): it fetches the source
of the installed version, adds the patch to `debian/patches/series`, rebuilds
at a local version, proves the artefacts with `nm` and `strings`, installs the
set through `apt` and reads the reply back.
[`documentation/08-adac.md`](../../documentation/08-adac.md) is its page. What
follows is the recipe it automates, for the reader who does it by hand, on
another distribution, or on a Samba the anchor has moved under.

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

`fill_netlogon_samlogon_response()` is defined in one shared library and
called from several others (`rootdse.so`, `nbtd.so`, `libdcerpc-server`),
which resolve it at load time. Only the library that *defines* it carries the
patch; the callers list the same symbol as undefined (`U` in `nm`) and are
unchanged by it. **Do not copy the name from a previous release.** On 4.17 the
defining library is `libdsdb-module-samba4.so.0`; on 4.22.10 it is
`libdsdb-module-private-samba.so.0`.

Derive it from the build. `debian/tmp` is what the package installs, already at
the right path and with the soname the installed tree expects, so there is no
mapping to get wrong. Filter on the symbol type, or every caller shows up too:

```console
# cd samba-4.22.10+dfsg
# find debian/tmp -type f \( -name '*.so' -o -name '*.so.*' \) |
    while read -r f; do
        n=$(nm -a "$f" 2>/dev/null | grep -cE ' [TtWw] fill_netlogon_samlogon_response$')
        [ "$n" -gt 0 ] && echo "${f#debian/tmp}"
    done
/usr/lib/x86_64-linux-gnu/samba/libdsdb-module-private-samba.so.0
```

Count the matches rather than testing with `grep -q`: under `set -o pipefail`,
`grep -q` closes the pipe on its first match, `nm` takes a `SIGPIPE`, and the
pipeline reports failure precisely when the symbol *is* there. And filter on
`[TtWw]`: the first version of this check counted every mention of the symbol,
and on a build that was entirely correct it reported three libraries as
unpatched, because they call the function without containing it.

Copy it to the same path on the controller, keep the original — that copy is
the whole rollback — and `systemctl restart samba-ad-dc`. (The first version
of this recipe copied the two callers as well, `rootdse.so` and `nbtd.so`,
because the unfiltered `nm` listed them. It did no harm, since they were
built from the same tree, and it was not needed.)

On Debian 13 the defining library belongs to `samba-libs`, read out of the
release's own `Contents-amd64` index rather than guessed
(`usr/lib/x86_64-linux-gnu/samba/libdsdb-module-private-samba.so.0`); on
Debian 12, `libdsdb-module-samba4.so.0`, in the same package.

### Installing it as packages, and why that means all of them

Copying the file works and is what the recipe above does. It is also what
makes the announcement fragile: the file belongs to `dpkg`, `dpkg -V samba-libs`
reports it as modified from then on, and the next `apt upgrade` puts the stock
one back.

The durable route is to rebuild the source package and install the result, so
the patch lives inside a package `apt` understands. That route has a
constraint which is not obvious and is not a matter of taste: **you cannot ship
only `samba-libs`.** Debian's Samba binaries pin each other to an exact
version, checked in trixie's `Packages` index:

```
samba              Depends: samba-libs (= 2:4.22.10+dfsg-0+deb13u1),
                            samba-common-bin (= 2:4.22.10+dfsg-0+deb13u1)
samba-dsdb-modules Depends: samba-libs (= 2:4.22.10+dfsg-0+deb13u1)
samba-ad-dc        Depends: samba, python3-samba, samba-dsdb-modules,
                            winbind, samba-libs — all (= <that version>)
winbind            Depends: samba-libs, samba-common-bin, libwbclient0 — all (=)
python3-samba      Depends: samba-libs (=)
smbclient          Depends: samba-libs (=)
libsmbclient0      Depends: samba-libs (=)
```

Bump three of them to a local version and leave the rest at the archive's, and
`apt` is handed a dependency it cannot satisfy. So the source package is
rebuilt whole and every binary it produces is offered at one version.

`dpkg` decides which wins, and it is worth being precise about what that buys:

```console
$ dpkg --compare-versions '2:4.22.10+dfsg-0+deb13u2+hs1' gt '2:4.22.10+dfsg-0+deb13u2'; echo $?
0
$ dpkg --compare-versions '2:4.22.10+dfsg-0+deb13u3' gt '2:4.22.10+dfsg-0+deb13u2+hs1'; echo $?
0
```

A local suffix outranks the archive version it was built from, so `apt`
installs the patched build. It is outranked in turn by the next Debian
revision, so a security update replaces it and the announcement stops. That is
the right way round — a controller that refuses security updates to keep a
feature is worse than one that loses the feature — but it means the pin has to
move and the packages have to be rebuilt on every Samba update, and an operator
who upgraded should re-run the check below.

The HardenSamba appliance does all of this in its image build: `make samba`
applies this patch through `debian/patches`, rebuilds the source, and refuses
to finish if the built artefacts do not carry the parameter. See `src/build/samba.sh`
and `docs/image.md` in `HardenSamba/hardensamba`.

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

The same `0x000033fd` was read on 4 September 2026 from a second controller,
`samba.local`, running Debian 12 with Samba **4.17.12** and the library
replaced by hand, and again on 11 September 2026 from the same controller
once `patch-samba.sh` had replaced that copy with rebuilt packages
(`2:4.17.12+dfsg-0+deb12u4+adws1`, `dpkg -V` clean). Two Samba releases five
apart, the same answer: the patch is
not anchored to a version, and the value in that table is what to compare
against rather than a number from one machine.

Read it in Python, from the reply and never from the request:

```python
from samba.credentials import Credentials
from samba.dcerpc import nbt
from samba.net import Net
from samba.param import LoadParm

lp = LoadParm(); lp.load_default()
creds = Credentials(); creds.guess(lp)
reply = Net(creds=creds, lp=lp).finddc(address="127.0.0.1",
                                       flags=nbt.NBT_SERVER_LDAP | nbt.NBT_SERVER_DS)
print("0x%08x" % reply.server_type,
      bool(reply.server_type & nbt.NBT_SERVER_ADS_WEB_SERVICE))
```

`Net(...)` needs `creds`; called without them it raises `TypeError: function
missing required argument 'creds'`, which reads as a problem with the
controller and is a problem with the call.

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

Applied as loose files, this patch is applied outside the Debian package, so an
update of `samba` overwrites the libraries and the announcement silently stops
while the `smb.conf` line stays exactly where it was. Applied as a rebuilt
package it survives longer, but not forever: the next Debian revision outranks
the local suffix and `apt` takes it. **In neither case is the presence of the
line evidence that the announcement works.** Three things follow:

- pin or hold `samba`, or rebuild after every upgrade. Holding a domain
  controller's Samba back from a security update is a real cost; rebuilding is
  the answer that does not trade one away;
- re-derive the file list on every Samba release, not just the patch. The
  anchor has held so far, but the set of installed artefacts carrying the code
  has already changed once between 4.17 and 4.22, silently: copying the older
  list gives two files that exist and one that does not, and a controller that
  still does not advertise;
- check the controller, not the configuration. The one measurement that cannot
  be fooled is `server_type` from its own netlogon reply, and the one that
  proves the client half is `nltest /dsgetdc:<realm> /ws /force` from a joined
  Windows machine. Both are above. An appliance built from
  `HardenSamba/hardensamba` runs the first of them in `tests/appliance-check.sh`
  on every run; on any other controller, `samba-adws patch-samba --check` runs
  it, and says whether the installed samba is still the rebuilt one.

`samdb_server_type()`, named in most write-ups on this subject, does not exist
in Samba at all. Neither does the `0x00100000` those write-ups give as the
server-side bit; that value is `DS_WEB_SERVICE_REQUIRED`, which is what the
client sends.
