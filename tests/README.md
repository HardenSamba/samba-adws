The pytest suite.

`tests/unit/` runs anywhere, including a workstation with no Samba installed.
`tests/dc/` needs a provisioned Samba AD DC and is skipped, not failed, when
`python3-samba` is absent — `tests/conftest.py` does that on the `dc` marker.

    python3 -m pytest -q            # both, skipping what cannot run here
    python3 -m pytest tests/unit -q # only what runs without a directory

`tools/test/` still holds `test_adws.py`, the operator diagnostic run by hand on
a first start, and the suites written before this layout existed.
`tools/test/Test-ADWS-Sovereign.ps1` is the end-to-end suite and needs Windows.

See [documentation/05-tests.md](../documentation/05-tests.md) for the ladder and
what each level is for.
