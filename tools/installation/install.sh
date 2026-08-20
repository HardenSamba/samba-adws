#!/usr/bin/env bash
#
# SambaAD ADWS - one-command installer for a Samba AD Domain Controller.
#
#   Usage (run AS ROOT, from the cloned repo directory):
#       sudo tools/installation/install.sh              # install + enable + start the service
#       sudo tools/installation/install.sh --uninstall  # remove the service (keeps logs, SPN)
#       sudo tools/installation/install.sh --no-ufw     # skip opening 9389/tcp in ufw
#
# It is idempotent: safe to re-run. It does NOT use pip, a virtualenv, or
# --break-system-packages -- every runtime dependency is a Debian/Ubuntu
# system package (python3-samba provides samba+ldb, python3-gssapi provides
# gssapi). The service runs in place from this directory.
#
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
SERVICE=samba-adws.service
UNIT_PATH="/etc/systemd/system/${SERVICE}"
ENV_PATH="/etc/default/samba-adws"
LOG_DIR="/var/log/samba-adws"
DO_UFW=1
DO_UNINSTALL=0

info() { printf '[*] %s\n' "$*"; }
ok()   { printf '[+] %s\n' "$*"; }
warn() { printf '[-] %s\n' "$*" >&2; }
die()  { printf '[x] %s\n' "$*" >&2; exit 1; }

parse_args() {
    for arg in "$@"; do
        case "$arg" in
            --uninstall) DO_UNINSTALL=1 ;;
            --no-ufw)    DO_UFW=0 ;;
            -h|--help)   grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
            *)           die "unknown argument: $arg" ;;
        esac
    done
}

require_root() {
    [ "$(id -u)" -eq 0 ] || die "must run as root (use: sudo tools/installation/install.sh)"
}

check_dc() {
    [ -f /var/lib/samba/private/sam.ldb ] \
        || warn "no /var/lib/samba/private/sam.ldb - is this a provisioned Samba AD DC?"
    [ -f /etc/krb5.conf ] \
        || warn "no /etc/krb5.conf - ADWS needs Kerberos (see documentation/02-installation.md)"
}

install_packages() {
    command -v apt-get >/dev/null || die "this installer targets Debian/Ubuntu (apt-get not found)"
    info "installing only MISSING system packages (no pip, no venv, no upgrades) ..."
    apt-get update -qq
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-upgrade \
        python3 python3-samba python3-gssapi samba-common-bin krb5-user
    ok "required system packages present (already-installed packages left untouched)"
}

register_spn() {
    command -v samba-tool >/dev/null || { warn "samba-tool not found; skipping SPN"; return; }
    local fqdn short acct spn
    fqdn="$(hostname -f)"; short="$(hostname -s)"; acct="${short}$"; spn="host/${fqdn}"
    if samba-tool spn list "$acct" 2>/dev/null | grep -qiF "$spn"; then
        ok "SPN ${spn} already registered on ${acct}"
    elif samba-tool spn add "$spn" "$acct" 2>/dev/null; then
        ok "SPN ${spn} registered on ${acct}"
    else
        warn "could not register SPN ${spn} (not a DC, or insufficient rights) - add it manually"
    fi
}

write_env() {
    mkdir -p "$LOG_DIR"
    if [ -f "$ENV_PATH" ]; then
        ok "${ENV_PATH} already exists (left unchanged)"
        return
    fi
    cat > "$ENV_PATH" <<EOF
# SambaAD ADWS service configuration (read by ${SERVICE}).
ADWS_HOST=0.0.0.0
ADWS_PORT=9389
ADWS_LOG_FILE=${LOG_DIR}/adws.log
ADWS_LOG_LEVEL=INFO
# Ceiling on any length a client announces, in bytes. 1 MB matches the
# MaxReceivedMessageSize default of the Windows ADWS service. A connection
# announcing more is closed. Takes effect on: systemctl restart samba-adws
ADWS_MAX_MESSAGE_SIZE=1048576
EOF
    ok "wrote ${ENV_PATH}"
}

install_unit() {
    local tmpl="${SCRIPT_DIR}/${SERVICE}"
    [ -f "$tmpl" ] || die "missing unit template: ${tmpl}"
    sed "s#__INSTALL_DIR__#${INSTALL_DIR}#g" "$tmpl" > "$UNIT_PATH"
    systemctl daemon-reload
    systemctl enable --now "$SERVICE"
    ok "service installed and started (WorkingDirectory=${INSTALL_DIR})"
}

open_firewall() {
    [ "$DO_UFW" -eq 1 ] || return 0
    if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -qi active; then
        ufw allow 9389/tcp >/dev/null 2>&1 && ok "ufw: allowed 9389/tcp" || warn "ufw rule add failed"
    fi
}

uninstall() {
    info "uninstalling ${SERVICE} ..."
    systemctl disable --now "$SERVICE" 2>/dev/null || true
    rm -f "$UNIT_PATH"
    systemctl daemon-reload
    rm -f "$ENV_PATH"
    command -v ufw >/dev/null && ufw delete allow 9389/tcp >/dev/null 2>&1 || true
    ok "uninstalled (logs in ${LOG_DIR} kept; the host/ SPN was left in AD)"
}

summary() {
    cat <<EOF

[+] DONE. ADWS is installed and running.

    Check it:        systemctl status ${SERVICE}
    Live logs:        journalctl -u ${SERVICE} -f
    Listening on:     ss -tlnp | grep 9389
    From Windows:     Get-ADRootDSE -Server $(hostname -f)

    Config:           ${ENV_PATH}   (edit + 'systemctl restart ${SERVICE}')
    Uninstall:        sudo tools/installation/install.sh --uninstall
EOF
}

main() {
    parse_args "$@"
    require_root
    if [ "$DO_UNINSTALL" -eq 1 ]; then
        uninstall
        exit 0
    fi
    info "installing SambaAD ADWS from ${INSTALL_DIR}"
    check_dc
    install_packages
    register_spn
    write_env
    install_unit
    open_firewall
    summary
}

main "$@"
