---
name: check-norms
description: >
  Audit Python files against this project's strict, non-standard coding norms
  (max 1 class and 5 functions per file, functions <=20 lines, nesting <=2,
  line length, a '#' header block before each def/class) using the bundled AST
  checker. Use before
  committing, after writing/changing a handler, or when asked to "check the
  norms / conventions / standards", "lint", or "verify the coding rules".
allowed-tools: Bash, Read
argument-hint: "[paths, default src/] [--max-line N] [--require-headers]"
---

# Check coding norms

Runs a self-contained AST checker bundled with this skill. No third-party
dependencies (standard library only).

## Run

From the **repo root** (the checker is the project tool `tools/norms`):

```bash
python3 -m tools.norms $ARGUMENTS
```

If `$ARGUMENTS` is empty it defaults to checking `src/`. Examples:

```bash
python3 -m tools.norms classes/handlers/get.py
python3 -m tools.norms src --require-headers
python3 -m tools.norms src --max-line 0     # §6.1 structure only
python3 -m tools.norms src --max-line 88     # add a line-length signal
```

Exit code is non-zero if any violation is found (suitable for a pre-commit
gate).

## What it enforces (defaults, all overridable by flag)

| Rule | Flag | Default |
|---|---|---|
| classes per file | `--max-classes` | 1 |
| functions per file (methods included) | `--max-functions` | 5 |
| lines per function (blanks + docstring excluded) | `--max-func-lines` | 20 |
| block nesting depth | `--max-nesting` | 2 |
| line length | `--max-line` | 60 |
| `#` header block before each def/class | `--require-headers` | off |

## Interpreting results
- Line length is a still-unsettled §6.2 decision (the code has ~840 lines
  over 60 chars). Use `--max-line 0` to audit §6.1 structure only (~36
  findings), or `--max-line 88` for a softer line signal.
- `elif` chains are treated as same-level (not extra nesting).
- The checker lives in `tools/norms/` (modular, itself §6.1-compliant) and
  is wired into `.pre-commit-config.yaml`: the `adws-norms` hook runs it
  with `--max-line 100 --require-headers` and BLOCKS commits that break §6.1
  on `src/` files (including a missing `#` header block before a def/class).
