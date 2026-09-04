"""The Debian packaging says what MODULE.yaml says, checked field by field.

`#6`'s acceptance criterion, in its own words: the command name, unit name and
config_dir installed by the package must match what `MODULE.yaml` declares,
checked field by field. The two files are edited by different people for
different reasons, and the drift between them is invisible until a machine
installs the package and a consumer probes for a command that is not there.

No YAML library: the manifest is read with a line parser that understands the
four shapes it uses, so this runs on a workstation with nothing installed.
`debian/` is read as text, since that is what dpkg reads.
"""

import re
from pathlib import Path
from typing import Dict, List

import pytest

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "MODULE.yaml"
DEBIAN = ROOT / "debian"


# The scalars and lists of MODULE.yaml this file reasons about.
def manifest() -> Dict[str, List[str]]:
    found: Dict[str, List[str]] = {}
    key = ""
    for raw in MANIFEST.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip()
        item = re.match(r"^\s*-\s+(.+)$", line)
        scalar = re.match(r"^(\s*)([A-Za-z_]+):\s*(.*)$", line)
        if item and key:
            found.setdefault(key, []).append(item.group(1).strip())
        elif scalar:
            key = scalar.group(2)
            if scalar.group(3):
                found[key] = [scalar.group(3).strip()]
    return found


# One field of debian/control, continuation lines joined.
def control_field(name: str) -> str:
    text = (DEBIAN / "control").read_text(encoding="utf-8")
    match = re.search(rf"^{name}:(.*(?:\n[ \t].*)*)", text, re.MULTILINE)
    assert match, f"debian/control has no {name} field"
    return " ".join(match.group(1).split())


# The package names a Depends field lists, without versions or alternatives.
def depends() -> List[str]:
    return [re.split(r"[ (|]", part.strip())[0]
            for part in control_field("Depends").split(",") if part.strip()]


# The package is the module, by name.
def test_the_package_is_named_after_the_module() -> None:
    assert control_field("Package") == manifest()["name"][0]


# The package version is the module version, and the source is native.
def test_the_version_is_the_manifests() -> None:
    first = (DEBIAN / "changelog").read_text(encoding="utf-8").splitlines()[0]
    assert first.startswith(f"samba-adws ({manifest()['version'][0]})"), first
    assert (DEBIAN / "source" / "format").read_text().strip() == "3.0 (native)"


# Every unit the manifest declares is a unit the package ships, by that name.
def test_the_units_are_shipped_by_name() -> None:
    for unit in manifest()["systemd_units"]:
        assert (DEBIAN / unit).is_file(), f"debian/{unit} is not shipped"


# Every command the manifest declares is installed to /usr/bin by that name.
def test_the_commands_are_installed_by_name() -> None:
    rules = (DEBIAN / "rules").read_text(encoding="utf-8")
    for command in manifest()["commands"]:
        assert f"usr/bin/{command}" in rules, f"rules does not install usr/bin/{command}"


# The configuration lives under the directory the manifest says it writes.
def test_the_configuration_is_under_the_declared_config_dir() -> None:
    config_dir = manifest()["config_dir"][0].strip("/")
    rules = (DEBIAN / "rules").read_text(encoding="utf-8")
    unit = (DEBIAN / "samba-adws.service").read_text(encoding="utf-8")
    assert f"debian/samba-adws/{config_dir}/" in rules, "rules installs no conffile there"
    assert f"EnvironmentFile=-/{config_dir}/" in unit, "the unit does not read it"


# Every Debian package the manifest requires is a hard dependency.
def test_the_required_packages_are_dependencies() -> None:
    missing = set(manifest()["debian_packages"]) - set(depends())
    assert not missing, f"MODULE.yaml requires {sorted(missing)}; Depends lacks them"


# The command's "run" and the unit start the same thing, the same way.
def test_run_and_the_unit_start_the_same_entry_point() -> None:
    wrapper = (DEBIAN / "samba-adws.wrapper").read_text(encoding="utf-8")
    unit = (DEBIAN / "samba-adws.service").read_text(encoding="utf-8")
    assert "python3 -m src.main" in wrapper
    assert "ExecStart=/usr/bin/python3 -m src.main" in unit


# The import shim runs the package's real __init__ rather than copying its
# exports, so a name added to samba_adws/__init__.py is exported from
# dist-packages without anyone remembering to update debian/.
def test_the_import_shim_runs_the_real_init_rather_than_copying_it() -> None:
    shim = (DEBIAN / "samba-adws.shim.py").read_text(encoding="utf-8")
    rules = (DEBIAN / "rules").read_text(encoding="utf-8")
    assert '"/samba_adws/__init__.py"' in shim, "the shim does not point at the real __init__"
    assert "__all__ = [" not in shim and "__all__ = (" not in shim, (
        "the shim carries its own export list, which is the drift it exists to avoid")
    assert "usr/lib/python3/dist-packages/samba_adws/__init__.py" in rules


# The maintainer scripts never fail an installation on a controller without a
# domain: every command that could is guarded, and the script exits zero.
@pytest.mark.parametrize("script", ["samba-adws.postinst", "samba-adws.prerm",
                                    "samba-adws.postrm"])
def test_the_maintainer_scripts_end_by_exiting_zero(script: str) -> None:
    lines = [ln.strip() for ln in (DEBIAN / script).read_text(encoding="utf-8").splitlines()
             if ln.strip()]
    assert lines[-1] == "exit 0", f"{script} does not end with exit 0"
    assert "#DEBHELPER#" in lines, f"{script} drops debhelper's own snippets"
