#!/bin/bash
#
# Make this Samba domain controller announce Active Directory Web Services,
# so that a Windows client's Administrative Center (ADAC) can find it.
#
#   sudo tools/installation/patch-samba.sh               # rebuild, install, enable, verify
#   sudo tools/installation/patch-samba.sh --check       # only report the current state
#   sudo tools/installation/patch-samba.sh --no-install  # build and verify, install nothing
#   sudo tools/installation/patch-samba.sh --revert      # put Debian's stock packages back
#
# Installed from the Debian package, the same thing is "samba-adws patch-samba".
#
# Why this exists. ADAC, and the ActiveDirectory PowerShell module used
# without -Server, locate a controller with DsGetDcName and the flag
# DS_WEB_SERVICE_REQUIRED, and keep only the controllers whose CLDAP netlogon
# reply carries DS_SERVER_WEBSERV (0x2000). Stock Samba never sets that bit,
# because Samba itself has no ADWS. So a controller running this module
# answers on tcp/9389 and is invisible to ADAC all the same: the client gives
# up before it connects. The only remedy is eight lines of C in Samba itself
# (patches/samba/), and that means rebuilding Samba. This script does that
# rebuild the Debian way -- the patch goes into the source package, the whole
# set of samba binaries is rebuilt at a local version, apt installs them --
# so that the result is packages dpkg knows about, not files copied over
# ones it owns.
#
# It is idempotent: run it again and it rebuilds and reinstalls the same
# thing. It needs a Debian or Ubuntu controller with deb-src lines (it adds
# them if they are missing), about 4 GB of free space under /var/tmp, and
# patience: the build is measured in tens of minutes on a small machine.
#
# What it does NOT survive: a Samba security update from Debian. The local
# version sorts below the next Debian revision on purpose -- a controller that
# refuses security updates to keep a locator flag is worse than one that
# loses the flag -- so after "apt upgrade" replaces samba, run this again.
# --check tells you whether that has happened.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PATCH_DIR="$REPO_DIR/patches/samba"
WORK_BASE=/var/tmp/samba-adws-patch
STATE_DIR=/var/lib/samba-adws
STATE_FILE="$STATE_DIR/samba-patched"
LOCAL_SUFFIX="+adws"
SMB_CONF=/etc/samba/smb.conf
MODE=build
DO_INSTALL=1

info() { printf '[*] %s\n' "$*"; }
ok()   { printf '[+] %s\n' "$*"; }
warn() { printf '[-] %s\n' "$*" >&2; }
die()  { printf '[x] %s\n' "$*" >&2; exit 1; }

usage() {
    # The comment block above, up to the first line of code.
    sed -n '2,/^set -euo pipefail/p' "$0" | sed '$d; s/^# \{0,1\}//'
}

parse_args() {
    for arg in "$@"; do
        case "$arg" in
            --check)      MODE=check ;;
            --revert)     MODE=revert ;;
            --no-install) DO_INSTALL=0 ;;
            -h|--help)    usage; exit 0 ;;
            *)            die "unknown argument: $arg (try --help)" ;;
        esac
    done
}

require_root() {
    [ "$(id -u)" -eq 0 ] || die "must run as root (sudo tools/installation/patch-samba.sh)"
}

require_debian_dc() {
    command -v apt-get >/dev/null || die "this script targets Debian/Ubuntu (apt-get not found)"
    dpkg-query -W samba >/dev/null 2>&1 || die "samba is not installed"
    [ -f /var/lib/samba/private/sam.ldb ] \
        || warn "no /var/lib/samba/private/sam.ldb: not a provisioned DC yet; rebuilding anyway"
}

# The netlogon reply's server_type, read through Samba's own locator, and
# whether the ADWS bit is in it. This is the measurement that cannot be fooled:
# it is the field a Windows client reads. Asked of the reply, never of the
# request -- finddc's flags are what the caller wants, not a filter the answer
# had to pass.
announces() {
    python3 - <<'PY' 2>/dev/null
import sys
try:
    from samba.credentials import Credentials
    from samba.dcerpc import nbt
    from samba.net import Net
    from samba.param import LoadParm
    lp = LoadParm(); lp.load_default()
    creds = Credentials(); creds.guess(lp)
    reply = Net(creds=creds, lp=lp).finddc(address="127.0.0.1",
                                           flags=nbt.NBT_SERVER_LDAP | nbt.NBT_SERVER_DS)
    bit = bool(reply.server_type & nbt.NBT_SERVER_ADS_WEB_SERVICE)
    print("%s 0x%08x" % ("yes" if bit else "no", reply.server_type))
    sys.exit(0 if bit else 1)
except Exception as error:
    print("unknown (%s)" % error)
    sys.exit(2)
PY
}

report_state() {
    local version answer
    version=$(dpkg-query -W -f='${Version}' samba 2>/dev/null || echo "not installed")
    info "samba package version: $version"
    case $version in
        *"$LOCAL_SUFFIX"*) ok "this is a build of this script (carries $LOCAL_SUFFIX)" ;;
        *) info "this is a stock build (no $LOCAL_SUFFIX suffix)" ;;
    esac
    if [ -f "$STATE_FILE" ]; then
        info "last rebuild by this script: $(tr '\n' ' ' < "$STATE_FILE")"
    fi
    if grep -qE '^\s*adws:advertise\s*=\s*yes' "$SMB_CONF" 2>/dev/null; then
        ok "smb.conf carries adws:advertise = yes"
    else
        info "smb.conf does not carry adws:advertise = yes"
    fi
    if [ -f /var/lib/samba/private/sam.ldb ] \
        && systemctl is-active samba-ad-dc >/dev/null 2>&1; then
        answer=$(announces || true)
        case $answer in
            yes*) ok "the controller announces ADWS: server_type ${answer#yes }" ;;
            no*)  warn "the controller does NOT announce ADWS: server_type ${answer#no }" ;;
            *)    warn "could not read the netlogon reply: $answer" ;;
        esac
    else
        info "no running provisioned DC to ask; the CLDAP check needs one"
    fi
    info "from a joined Windows client, the proof is:  nltest /dsgetdc:<realm> /ws /force"
}

ensure_deb_src() {
    if apt-cache showsrc samba >/dev/null 2>&1; then
        return 0
    fi
    info "no deb-src entry for samba; deriving one from the deb lines"
    local list=/etc/apt/sources.list.d/samba-adws-src.list
    {
        echo "# Written by samba-adws/tools/installation/patch-samba.sh: source lines for"
        echo "# rebuilding samba with the ADWS advertisement patch. Safe to remove."
        grep -hE '^\s*deb\s' /etc/apt/sources.list /etc/apt/sources.list.d/*.list 2>/dev/null \
            | sed -E 's/^\s*deb\s/deb-src /' | sort -u
    } > "$list"
    apt-get update -qq
    apt-cache showsrc samba >/dev/null 2>&1 || die "still no samba source after adding $list"
}

# The source version to rebuild: the installed one, so that what is built is
# what is running plus the patch and nothing else. If the archive has moved on
# and no longer offers it, the current one is taken and said so: the rebuilt
# set is installed wholesale anyway, so a newer base is an upgrade, not a mix.
choose_version() {
    local installed
    installed=$(dpkg-query -W -f='${source:Version}' samba)
    installed=${installed%%"$LOCAL_SUFFIX"*}
    # Not grep -q: it stops at the first match, apt-cache gets SIGPIPE, and
    # pipefail then reports failure exactly when the version is there.
    if apt-cache showsrc samba 2>/dev/null | grep -Fx "Version: $installed" >/dev/null; then
        SRC_VERSION=$installed
    else
        SRC_VERSION=$(apt-cache showsrc samba | sed -n 's/^Version: //p' | sort -V | tail -1)
        warn "the archive no longer offers $installed; rebuilding $SRC_VERSION instead"
    fi
    ok "source version to rebuild: $SRC_VERSION"
    BUILT_VERSION="${SRC_VERSION}${LOCAL_SUFFIX}1"
    WORK="$WORK_BASE/${SRC_VERSION//:/_}"
}

# A build of exactly this version that this script already finished is
# reused rather than redone: the build is the expensive step, and a run that
# stopped after it (a failed install, a verification this script got wrong,
# a lost terminal) should not cost it again. Delete the directory to force one.
built_already() {
    local changes="$WORK/samba_${BUILT_VERSION#*:}_$(dpkg --print-architecture).changes"
    [ -f "$changes" ] || return 1
    TREE=$(find "$WORK" -maxdepth 1 -mindepth 1 -type d -name 'samba-*' | head -1)
    [ -n "$TREE" ] || return 1
    ok "reusing the packages already built in $WORK (delete it to rebuild)"
}

install_build_deps() {
    info "installing Samba's build dependencies (several hundred packages) ..."
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q dpkg-dev fakeroot binutils >/dev/null
    DEBIAN_FRONTEND=noninteractive apt-get build-dep -y -q samba >/dev/null
    ok "build dependencies present"
}

fetch_source() {
    rm -rf "$WORK"
    mkdir -p "$WORK"
    info "fetching the samba source into $WORK ..."
    # dpkg-source's warnings about Debian's own patches go to the log too;
    # they are not this script's to show, and they drown its own lines.
    ( cd "$WORK" && apt-get source -q "samba=$SRC_VERSION" ) >"$WORK/source.log" 2>&1 \
        || die "fetching the source failed; see $WORK/source.log"
    TREE=$(find "$WORK" -maxdepth 1 -mindepth 1 -type d -name 'samba-*' | head -1)
    [ -n "$TREE" ] || die "apt-get source left no samba-* directory in $WORK"
    ok "source unpacked: $(basename "$TREE")"
}

apply_patch() {
    local patch base series
    patch=$(ls -1 "$PATCH_DIR"/*.patch 2>/dev/null | head -1)
    [ -n "$patch" ] || die "no .patch file under $PATCH_DIR"
    base=$(basename "$patch")
    series="$TREE/debian/patches/series"
    [ -f "$series" ] || die "$TREE has no debian/patches/series"
    sed 's/\r$//' "$patch" > "$TREE/debian/patches/$base"
    grep -qxF "$base" "$series" || printf '%s\n' "$base" >> "$series"
    # Applied now rather than left to the build, so a source it no longer fits
    # fails here with the hunk that failed, not thirty minutes later.
    ( cd "$TREE" && patch -p1 --dry-run -s -i "debian/patches/$base" >/dev/null ) \
        || die "the patch does not apply to samba $SRC_VERSION; see $PATCH_DIR/README.md"
    ok "patch added to debian/patches/series: $base"
}

bump_version() {
    local stamp changelog
    stamp=$(date -u -R)
    changelog="$TREE/debian/changelog"
    {
        printf 'samba (%s) %s; urgency=medium\n\n' "$BUILT_VERSION" \
            "$(sed -n '1s/^samba ([^)]*) \([^;]*\);.*/\1/p' "$changelog")"
        printf '  * Advertise Active Directory Web Services in the CLDAP netlogon reply\n'
        printf '    when smb.conf carries "adws:advertise = yes" (samba-adws).\n\n'
        printf ' -- samba-adws patch-samba.sh <noreply@hardensamba.invalid>  %s\n\n' "$stamp"
        cat "$changelog"
    } > "$changelog.new"
    mv "$changelog.new" "$changelog"
    ok "version: $BUILT_VERSION"
}

build() {
    local mem_mb jobs cores started minutes
    cores=$(nproc 2>/dev/null || echo 2)
    # About 1.2 GB per job is what a Samba build has needed to finish rather
    # than be killed; the memory sets the count, the cores only cap it.
    mem_mb=$(awk '/MemAvailable/{print int($2/1024)}' /proc/meminfo)
    jobs=$(( mem_mb / 1200 ))
    [ "$jobs" -lt 1 ] && jobs=1
    [ "$jobs" -gt "$cores" ] && jobs=$cores
    info "building samba $BUILT_VERSION with $jobs job(s); the long part (log: $WORK/build.log)"
    started=$(date +%s)
    ( cd "$TREE" && DEB_BUILD_OPTIONS="nocheck parallel=$jobs" \
        dpkg-buildpackage -us -uc -b ) >"$WORK/build.log" 2>&1 \
        || die "the build failed; see $WORK/build.log"
    minutes=$(( ($(date +%s) - started) / 60 ))
    ok "built $(ls -1 "$WORK"/*.deb | wc -l) packages in $minutes minutes"
}

# Proves the build did the one thing it is for, before anything installs it.
# Only the artefacts that DEFINE the function (nm type T, t or W) can carry
# the patch; the ones that merely call it list the same symbol as U, and
# counting those flagged three unpatched libraries on a build that was fine.
# Counted rather than grep -q, which under pipefail reports failure exactly
# when the symbol is there.
verify_build() {
    local found=0 missing=0 f n
    while IFS= read -r f; do
        n=$(nm -a "$f" 2>/dev/null | grep -cE ' [TtWw] fill_netlogon_samlogon_response$' || true)
        [ "${n:-0}" -gt 0 ] || continue
        found=$((found + 1))
        if [ "$(strings "$f" 2>/dev/null | grep -c adws || true)" -gt 0 ]; then
            ok "patched: ${f#"$TREE/debian/"}"
        else
            warn "NOT patched: ${f#"$TREE/debian/"}"; missing=$((missing + 1))
        fi
    done < <(find "$TREE/debian" -type f \( -name '*.so' -o -name '*.so.*' \) 2>/dev/null)
    [ "$found" -gt 0 ] \
        || die "no built artefact carries the netlogon function; see $PATCH_DIR/README.md"
    [ "$missing" -eq 0 ] || die "$missing artefact(s) carry the function without the patch"
}

# Every rebuilt package whose name is installed, installed together. Debian's
# samba binaries pin each other to an exact version, so a partial install is a
# dependency apt cannot satisfy; all of the installed set has to move at once.
install_packages() {
    local debs=() f name
    for f in "$WORK"/*.deb; do
        name=$(dpkg-deb -f "$f" Package)
        if [ "$(dpkg-query -W -f='${db:Status-Status}' "$name" 2>/dev/null)" = "installed" ]; then
            debs+=("$f")
        fi
    done
    [ "${#debs[@]}" -gt 0 ] || die "none of the rebuilt packages is installed here"
    info "installing ${#debs[@]} rebuilt package(s) over the installed set ..."
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q --allow-downgrades "${debs[@]}" \
        >"$WORK/install.log" 2>&1 \
        || die "installing the rebuilt packages failed; see $WORK/install.log"
    ok "samba is now $(dpkg-query -W -f='${Version}' samba)"
}

enable_setting() {
    if grep -qE '^\s*adws:advertise\s*=\s*yes' "$SMB_CONF"; then
        ok "smb.conf already carries adws:advertise = yes"
        return 0
    fi
    cp -a "$SMB_CONF" "$SMB_CONF.samba-adws.bak"
    # Right under [global]; Samba reads the parameter from the global section.
    local lines='[global]\n\t# ADWS announcement (samba-adws)\n\tadws:advertise = yes'
    sed -i "0,/^\[global\]/s//$lines/" "$SMB_CONF"
    ok "added adws:advertise = yes under [global] (backup: $SMB_CONF.samba-adws.bak)"
}

restart_and_verify() {
    systemctl restart samba-ad-dc
    if systemctl is-active samba-adws >/dev/null 2>&1; then
        systemctl restart samba-adws
    fi
    sleep 3
    mkdir -p "$STATE_DIR"
    printf 'samba=%s\nbuilt=%s\n' "$BUILT_VERSION" "$(date -u +%FT%TZ)" > "$STATE_FILE"
    report_state
}

# Debian's own packages back, at the version this script started from. It
# needs the archive to still offer that version; when it has moved on, the
# way back is the way forward: apt-get upgrade takes the newer stock samba.
revert() {
    local pkgs=() name version
    while read -r name version; do
        case $version in
            *"$LOCAL_SUFFIX"*) pkgs+=("$name=${version%%"$LOCAL_SUFFIX"*}") ;;
        esac
    done < <(dpkg-query -W -f='${Package} ${Version}\n')
    if [ "${#pkgs[@]}" -eq 0 ]; then
        ok "no installed package carries $LOCAL_SUFFIX; nothing to revert"
        return 0
    fi
    info "reinstalling ${#pkgs[@]} package(s) at their stock version ..."
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q --allow-downgrades "${pkgs[@]}" \
        || die "apt could not reinstall the stock versions; is the archive still offering them?"
    rm -f "$STATE_FILE"
    systemctl restart samba-ad-dc
    sleep 3
    ok "stock samba is back; the smb.conf line stays and is now read by nothing"
    report_state || true
}

main() {
    parse_args "$@"
    require_root
    require_debian_dc
    case $MODE in
        check)  report_state; exit 0 ;;
        revert) revert; exit 0 ;;
    esac
    ensure_deb_src
    choose_version
    if ! built_already; then
        install_build_deps
        fetch_source
        apply_patch
        bump_version
        build
    fi
    verify_build
    if [ "$DO_INSTALL" -eq 0 ]; then
        ok "built and verified; not installed (--no-install). Packages are in $WORK"
        exit 0
    fi
    install_packages
    enable_setting
    restart_and_verify
    echo
    ok "DONE. A Debian security update of samba replaces this build; run this again afterwards."
}

main "$@"
