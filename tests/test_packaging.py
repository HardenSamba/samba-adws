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


# The patch the Administrative Center needs, and the command that applies it,
# ship with the package at the paths a checkout has, so "samba-adws
# patch-samba" finds patches/samba/ the way the script does from a checkout.
def test_the_samba_patch_and_its_script_ship_together() -> None:
    rules = (DEBIAN / "rules").read_text(encoding="utf-8")
    wrapper = (DEBIAN / "samba-adws.wrapper").read_text(encoding="utf-8")
    patches = sorted(p.name for p in (ROOT / "patches" / "samba").glob("*.patch"))
    assert patches, "patches/samba/ carries no patch"
    for name in patches:
        assert f"patches/samba/{name}" in rules, f"rules does not ship {name}"
    assert "tools/installation/patch-samba.sh" in rules, "rules does not ship the script"
    assert "patch-samba)" in wrapper and "tools/installation/patch-samba.sh" in wrapper
    installer = (ROOT / "tools" / "installation" / "install.sh").read_text(encoding="utf-8")
    assert "patches/samba/*.patch" in installer and "patch-samba.sh" in installer, (
        "the checkout installer does not put the patch and the script where the package does")


# The maintainer scripts never fail an installation on a controller without a
# domain: every command that could is guarded, and the script exits zero.
@pytest.mark.parametrize("script", ["samba-adws.postinst", "samba-adws.prerm",
                                    "samba-adws.postrm"])
def test_the_maintainer_scripts_end_by_exiting_zero(script: str) -> None:
    lines = [ln.strip() for ln in (DEBIAN / script).read_text(encoding="utf-8").splitlines()
             if ln.strip()]
    assert lines[-1] == "exit 0", f"{script} does not end with exit 0"
    assert "#DEBHELPER#" in lines, f"{script} drops debhelper's own snippets"


# The unit is never enabled or started by the package (contract 4.2): the
# maintainer script has no such call, and debhelper is told the same.
def test_the_package_never_enables_or_starts_the_unit() -> None:
    postinst = (DEBIAN / "samba-adws.postinst").read_text(encoding="utf-8")
    commands = [ln for ln in postinst.splitlines()
                if not ln.lstrip().startswith(("#", "echo"))]
    assert not [ln for ln in commands if re.search(r"\b(enable|start)\b", ln)], commands
    assert "try-restart" in postinst, "an upgrade must restart a running service"
    rules = (DEBIAN / "rules").read_text(encoding="utf-8")
    assert "dh_installsystemd --no-enable --no-start" in rules


# The checkout installer puts the package's files at the package's paths: every
# path rules installs by hand, and every artefact debhelper adds, is named in
# the installer, from the same source files, and no template of its own is left.
def test_the_installer_mirrors_the_package() -> None:
    installer = (ROOT / "tools" / "installation" / "install.sh").read_text(encoding="utf-8")
    for path in ("/usr/share/samba-adws", "/usr/bin/samba-adws",
                 "/usr/lib/systemd/system/samba-adws.service",
                 "/usr/lib/python3/dist-packages/samba_adws",
                 "/etc/hardensamba/samba-adws", "/usr/share/doc/samba-adws",
                 "/usr/share/man/man1/samba-adws.1.gz",
                 "/usr/share/python3/runtime.d/samba-adws.rtupdate"):
        assert path.replace("samba-adws", "$NAME") in installer, f"{path} is not installed"
    for source in ("debian/$NAME.wrapper", "debian/$NAME.shim.py", "debian/$NAME.service",
                   "debian/$NAME.conf", "debian/$NAME.1", "debian/copyright"):
        assert source in installer, f"the installer does not install from {source}"
    assert "enable --now" not in installer.replace("systemctl enable --now $NAME\"", "")
    assert not (ROOT / "tools" / "installation" / "samba-adws.service").exists(), (
        "the installer's own unit template is back; the package's unit is the one unit")


# CI builds the package, checks it with lintian, installs it, and diffs the
# installer's list against dpkg -L: the parity is held by a machine.
def test_ci_holds_the_installer_to_the_package() -> None:
    workflow = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    for step in ("dpkg-buildpackage -us -uc -b", "lintian --fail-on error,warning",
                 "dpkg -L samba-adws", "tools/installation/install.sh | sort",
                 "diff packaged.txt manual.txt", "install.sh --uninstall"):
        assert step in workflow, f"ci.yml lacks: {step}"
