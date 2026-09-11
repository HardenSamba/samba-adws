#!/bin/sh
# Manual installation of samba-adws on a Debian controller with no access to
# the package archive: the same files at the same paths as the package,
# printed one per line on standard output as they are put in place, so the
# list can be diffed against `dpkg -L samba-adws` - CI does exactly that. Run
# from a checkout, as root. Nothing is enabled or started (contract 4.2).
#
#   sudo tools/installation/install.sh              install
#   sudo tools/installation/install.sh --uninstall  take the installed files away,
#                                                   the configuration file included;
#                                                   the logs and the host SPN stay
#
# Both refuse to touch a system where dpkg knows the package at all - installed,
# removed but not purged, half-configured - because the files, and the conffile
# a removal leaves behind, are dpkg's to manage there: `apt purge` first.
#
# What the package's maintainer scripts do is done here too: the payload is
# byte-compiled with py3compile, and the runtime.d hook dh_python3 writes is
# written, so a change of interpreter recompiles it. Documentation is
# compressed the way dh_compress does it: files over 4 KiB under
# /usr/share/doc, and the manual page. The one thing the package does not do
# and this script does, as it always has, is register the host service
# principal, because a checkout installation has no packaging step left to
# leave it to.
set -eu

HERE=$(cd "$(dirname "$0")/../.." && pwd)
NAME=samba-adws
PYTHON=/usr/bin/python3
PAYLOAD=/usr/share/$NAME
BIN=/usr/bin/$NAME
UNIT=/usr/lib/systemd/system/$NAME.service
SHIM_DIR=/usr/lib/python3/dist-packages/samba_adws
SHIM=$SHIM_DIR/__init__.py
CONF_DIR=/etc/hardensamba/$NAME
CONF=$CONF_DIR/$NAME.conf
DOC=/usr/share/doc/$NAME
MAN=/usr/share/man/man1/$NAME.1.gz
RTUPDATE=/usr/share/python3/runtime.d/$NAME.rtupdate
# Where the installer of earlier versions rendered its own unit; it shadows
# the package's, so it is taken away when found.
OLD_UNIT=/etc/systemd/system/$NAME.service
COMPRESS_OVER=4096
SCRATCH=$(mktemp -d)
trap 'rm -rf "$SCRATCH"' EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

say() { printf '%s: %s\n' "$NAME" "$*" >&2; }

# Refuses to run as anyone but root, or where dpkg knows the package. A purged
# package stays in dpkg's database as "not-installed", which is not knowing it.
guard() {
    if [ "$(id -u)" -ne 0 ]; then
        say "run as root"
        exit 64
    fi
    state=$(dpkg-query -W -f='${Status}' "$NAME" 2>/dev/null || true)
    case "$state" in
        ""|*not-installed) ;;
        *)
            say "dpkg knows the package ($state); apt purge $NAME before this"
            exit 64 ;;
    esac
}

# Installs the system packages the package depends on, through apt and
# nothing else - no pip, no virtualenv - then refuses to go on without the
# checkout and the interpreter the installed command runs under.
require() {
    if [ ! -d "$HERE/classes" ] || [ ! -d "$HERE/src" ] || [ ! -d "$HERE/samba_adws" ]; then
        say "$HERE is not a checkout of $NAME"
        exit 64
    fi
    command -v apt-get >/dev/null 2>&1 || { say "apt-get missing; this targets Debian"; exit 64; }
    say "installing the missing system packages"
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
        python3 python3-samba python3-gssapi samba-common-bin krb5-user >/dev/null
    [ -x "$PYTHON" ] || { say "$PYTHON missing"; exit 64; }
}

# Installs one file at a path with a mode, making the directory, and says so.
put() {
    install -D -m "$1" "$2" "$3"
    echo "$3"
}

# Installs a documentation file as the package does: gzipped past the size
# dh_compress compresses at, plain below it.
put_doc() {
    if [ "$(wc -c < "$1")" -gt "$COMPRESS_OVER" ]; then
        gzip -9 -n -c "$1" > "$SCRATCH/doc.gz"
        put 0644 "$SCRATCH/doc.gz" "$2/$(basename "$1").gz"
    else
        put 0644 "$1" "$2/$(basename "$1")"
    fi
}

# The service and the client, as a payload under /usr/share, normalised the
# way debian/rules and debhelper normalise it: no byte-code from the
# checkout, everything owned by root with the modes dh_fixperms gives (the
# checkout belongs to whoever cloned it, and root runs this code), library
# modules not executable, the vendored python2 shebangs rewritten.
payload() {
    rm -rf "$PAYLOAD"
    install -d "$PAYLOAD/tools/test"
    cp -R "$HERE/src" "$HERE/classes" "$HERE/samba_adws" "$HERE/MODULE.yaml" "$PAYLOAD/"
    install -m 0644 "$HERE/tools/test/test_adws.py" "$PAYLOAD/tools/test/test_adws.py"
    # The Samba patch and the script that rebuilds Samba with it, at the
    # paths a checkout has, as debian/rules installs them: the script finds
    # patches/samba/ relative to itself from either place.
    install -d "$PAYLOAD/patches/samba" "$PAYLOAD/tools/installation"
    install -m 0644 "$HERE"/patches/samba/*.patch "$HERE/patches/samba/README.md" \
        "$PAYLOAD/patches/samba/"
    install -m 0755 "$HERE/tools/installation/patch-samba.sh" \
        "$PAYLOAD/tools/installation/patch-samba.sh"
    find "$PAYLOAD" -name __pycache__ -prune -exec rm -rf {} +
    find "$PAYLOAD" -name '*.pyc' -delete
    chown -R root:root "$PAYLOAD"
    find "$PAYLOAD" -type d -exec chmod 0755 {} +
    find "$PAYLOAD" -type f -exec chmod 0644 {} +
    chmod 0755 "$PAYLOAD/tools/installation/patch-samba.sh"
    find "$PAYLOAD" -type f -name '*.py' \
        -exec sed -i '1s|^#!.*python2.*$|#!/usr/bin/python3|' {} +
    find "$PAYLOAD" -type f | sort
}

# What dh_python3 does for a private directory: the hook that recompiles it
# when the interpreter changes, and the byte-code itself.
compiled() {
    printf '%s\n' '#! /bin/sh' 'set -e' '' 'if [ "$1" = rtupdate ]; then' \
        "	py3clean $PAYLOAD" "	py3compile $PAYLOAD" 'fi' > "$SCRATCH/rtupdate"
    put 0755 "$SCRATCH/rtupdate" "$RTUPDATE"
    if command -v py3compile >/dev/null 2>&1; then
        py3compile "$PAYLOAD"
    fi
}

# The host service principal on this machine's account, when samba-tool can
# see the directory and it is missing; a checkout installation has no other
# step to leave it to. Best effort: a controller not yet provisioned says so.
register_spn() {
    command -v samba-tool >/dev/null 2>&1 || { say "samba-tool missing; the SPN is not registered"; return; }
    fqdn=$(hostname -f 2>/dev/null || hostname); short=${fqdn%%.*}
    acct="${short}\$"; spn="host/${fqdn}"
    if samba-tool spn list "$acct" 2>/dev/null | grep -qiF "$spn"; then
        say "SPN $spn already registered on $acct"
    elif samba-tool spn add "$spn" "$acct" 2>/dev/null; then
        say "SPN $spn registered on $acct"
    else
        say "could not register SPN $spn on $acct: not provisioned yet, or no rights; add it after"
    fi
}

# Tells systemd about unit files that appeared or disappeared, when it runs.
reload() {
    if [ -d /run/systemd/system ]; then
        systemctl daemon-reload
    fi
}

# Everything the package installs, at the same paths; then the one step it
# leaves to the administrator, and the reminder of the other.
install_all() {
    guard
    require
    payload
    put 0755 "$HERE/debian/$NAME.wrapper" "$BIN"
    put 0644 "$HERE/debian/$NAME.shim.py" "$SHIM"
    put 0644 "$HERE/debian/$NAME.service" "$UNIT"
    if [ -e "$CONF" ]; then
        echo "$CONF"
        say "$CONF kept as it is"
    else
        put 0644 "$HERE/debian/$NAME.conf" "$CONF"
    fi
    put_doc "$HERE/README.md" "$DOC"
    for doc in "$HERE"/documentation/*.md; do
        put_doc "$doc" "$DOC/documentation"
    done
    gzip -9 -n -c "$HERE/debian/changelog" > "$SCRATCH/changelog.gz"
    put 0644 "$SCRATCH/changelog.gz" "$DOC/changelog.gz"
    put 0644 "$HERE/debian/copyright" "$DOC/copyright"
    gzip -9 -n -c "$HERE/debian/$NAME.1" > "$SCRATCH/man.gz"
    put 0644 "$SCRATCH/man.gz" "$MAN"
    compiled
    if [ -e "$OLD_UNIT" ]; then
        rm -f "$OLD_UNIT"
        say "$OLD_UNIT from an earlier installer removed; it shadowed $UNIT"
    fi
    reload
    register_spn
    say "installed and left disabled (contract 4.2); when the directory is provisioned:"
    say "    systemctl enable --now $NAME"
}

# Stops what may be running, then removes what install_all put in place, the
# configuration file included - the way a purge does. The logs and the SPN
# stay: they belong to the record and to the domain.
remove_all() {
    guard
    if [ -d /run/systemd/system ]; then
        systemctl stop "$NAME.service" 2>/dev/null || true
        systemctl disable "$NAME.service" 2>/dev/null || true
    fi
    if command -v py3clean >/dev/null 2>&1 && [ -d "$PAYLOAD" ]; then
        py3clean "$PAYLOAD"
    fi
    rm -rf "$PAYLOAD" "$DOC" "$SHIM_DIR"
    rm -f "$BIN" "$UNIT" "$OLD_UNIT" "$MAN" "$RTUPDATE" "$CONF"
    rmdir --ignore-fail-on-non-empty "$CONF_DIR" /etc/hardensamba 2>/dev/null || true
    reload
    say "uninstalled; the logs under /var/log/$NAME and the host SPN are left in place"
}

case "${1:-}" in
    "") install_all ;;
    --uninstall|--remove) remove_all ;;
    -h|--help) sed -n '2,24p' "$0" | sed 's/^# \{0,1\}//' ;;
    *) echo "usage: $0 [--uninstall]" >&2; exit 64 ;;
esac
