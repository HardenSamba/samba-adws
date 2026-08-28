The pytest suite.

`tests/unit/` runs anywhere, including a workstation with no Samba installed.
`tests/dc/` needs a provisioned Samba AD DC and is skipped, not failed, when
`python3-samba` is absent — `tests/conftest.py` does that on the `dc` marker.

    python3 -m pytest -q              # both, skipping what cannot run here
    python3 -m pytest -q -m "not dc"  # level 0 only, same set on a DC
    python3 -m pytest tests/unit -q   # only the layer tests

The second form is the blocking hook in `.pre-commit-config.yaml`, which adds
`--ignore=tests/dc` to it. It deselects the `dc` marker instead of relying on
the skip, and excludes the directory by path as well, so committing on the DC
itself does not fire the directory tests — not even for a file added here later
that forgets `pytestmark = pytest.mark.dc`.

`tools/test/` still holds `test_adws.py`, the operator diagnostic run by hand on
a first start, and the suites written before this layout existed.
`tools/test/Test-ADWS-Sovereign.ps1` is the end-to-end suite and needs Windows.

See [documentation/05-tests.md](../documentation/05-tests.md) for the ladder and
what each level is for.
