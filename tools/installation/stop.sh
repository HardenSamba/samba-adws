#!/usr/bin/env bash
#
# Stop the SambaAD ADWS service cleanly (WITHOUT uninstalling it).
#   sudo tools/installation/stop.sh
#
# Re-start later with:  sudo systemctl start samba-adws
# Remove entirely with: sudo tools/installation/install.sh --uninstall
#
set -euo pipefail
SERVICE=samba-adws.service

[ "$(id -u)" -eq 0 ] || { echo "[x] must run as root (sudo tools/installation/stop.sh)" >&2; exit 1; }

if systemctl list-unit-files 2>/dev/null | grep -q "^${SERVICE}"; then
    systemctl stop "$SERVICE"
    echo "[+] ${SERVICE} stopped (service still installed)."
else
    if pkill -f 'python3 -m src.main'; then
        echo "[+] stopped the manual ADWS process (python3 -m src.main)."
    else
        echo "[*] no running ADWS found (neither service nor manual launch)."
    fi
fi
