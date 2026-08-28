"""Runs the command as `python3 -m samba_adws`, for a checkout with no install."""

import sys

from samba_adws.cli import main

if __name__ == "__main__":
    sys.exit(main())
