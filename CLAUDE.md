# SambaAD ADWS: project instructions

## 1. Context
Python implementation of the Active Directory Web Services (TCP 9389) for
a Samba AD DC. Single entry point: `python3 -m src.main`.

"Sovereign" = open, auditable, with no Microsoft binary or code in
production. The service bridges the WS-* requests of Windows clients and
the Samba directory (LDB).

Current state: phases 1 to 4 COMPLETE (CRUD, LDAP search and enumeration,
group operations, ActiveDirectory PowerShell module + ADAC compatibility).
Phase 5 IN PROGRESS: performance + security hardening.
→ The work is to MAINTAIN and EXTEND, not to rewrite.

## 2. First things first: read what already exists
1. `documentation/` is the source of truth. Read in this order:
   01-architecture → 03-protocole → 04-handlers, then 05-tests / 06-depannage.
2. Protocol reference:
   - Microsoft Open Specifications = THE SPEC, authoritative ([MS-NMF], [MS-NNS],
     [MS-NBFX], [MS-NBFS], [MS-ADDM], [MS-WSTIM], [MS-WSDS], [MS-WSPELD],
     [MS-ADTS]), together with the RFCs (4120, 4121, 4178, 2743) and the
     W3C recommendations (SOAP 1.2, WS-Addressing).
   - Observed Windows client behaviour (network captures, cmdlet error
     messages) completes the spec on the points it leaves open. Any deduction
     drawn from an observation must be flagged as such in the documentation.

## 3. Expected behaviour (already achieved, must not regress)
From a domain member machine, against the Samba directory:
- Read: Get-ADUser/Computer/Group/Object/Domain/DomainController/Forest,
  Get-ADRootDSE, filtered and paginated searches and enumerations.
- Write: New-AD*, Set-AD*, Remove-AD*, Set-ADAccountPassword.
- Groups: Get-ADGroupMember, Get-ADPrincipalGroupMembership (plus recursive).
- Integrated Kerberos authentication through GSSAPI, AD rights enforced.

## 4. Protocol: technical grounding
TCP 9389. Stack (bottom → top):
- [MS-NMF] .NET Message Framing                → src/nettcp/nmf.py
- GSSAPI/SPNEGO (Kerberos AES, seal/unseal)    → src/nettcp/stream/gssapi.py
  (on the Windows side this is NegotiateStream [MS-NNS]; on the Linux server
   side we go through samba.gensec, no .NET NegotiateStream)
- [MS-NBFX]/[MS-NBFS] WCF binary XML + dict.   → src/wcf/
- SOAP 1.2 + WS-Addressing
- [MS-ADDM] AD data model, [MS-WSTIM] IMDA Get/Put,
  [MS-WSDS] enumeration, [MS-WSPELD] LDAP v3 controls

## 5. NON-NEGOTIABLE invariants (the project's pitfalls)
- Server running as `ForkingTCPServer`: `python3-samba` is NOT thread-safe.
  → NEVER open `SamDB` at module level. Go through the
    `classes/directory/SambaDB` helper (lazy per-process opening).
- Every rendered object: check `context.is_imda` and pick the right rendering
  (IMDA = one `<da:PartialAttribute>` per attribute; WS-Transfer = objectClass
  wrapper). The wrong wrapper → the Windows cmdlet breaks.
- In IMDA, always emit `distinguishedName` as an explicit attribute.
- Every error = a typed `ADWSException` (never a bare `Exception`); the
  dispatcher translates it into a SOAP fault.
- Every fault MUST carry `<a:RelatesTo>{message_id}`, otherwise PowerShell
  ignores the response and the cmdlet blocks until the timeout.
- One file = one SOAP action, inheriting from `BaseHandler.handle()`.

## 6. Coding standards
Language: English throughout, without exception. Prose, documentation, code,
identifiers, comments, commit messages and issues.

Verbatim quotations of client error messages keep their original language:
they are what an administrator actually sees on screen.

### 6.1 Mandatory (blocking)
- 1 class max and 5 functions max per file.
- Function ≤ 20 lines (blank lines excluded).
- Nesting ≤ 2 levels.
- Line ≤ 100 characters.
- Complete typing: every parameter, return value and non-trivial variable is
  annotated. `mypy --strict` (platform=linux, ignore_missing_imports because
  samba/ldb ship no stubs).
- No mutable global state; UPPER_CASE constants.
- snake_case / PascalCase / UPPER_CASE.
- No `import *`, no bare `except:`, no mutable default.
- Mandatory header: every `class` and every function is preceded by a
  `#` comment block (1 to 3 lines) describing what it does, immediately
  above the `def`/`class` (and above its decorators). Format:
  `# Resolves the target DN, adds the object, returns the ResourceCreated EPR.`
  Describe the WHAT (the role), not the HOW. No other inline comment
  inside the body: the name plus the types document the detail. Module
  docstring: one line max, optional.

### 6.2 Targets (aim for them, measure them; not retroactively blocking)
- McCabe ≤ 5, ≤ 4 parameters per function.

### 6.3 Enforcement
- In-house AST checker `tools/norms` (1 class / 5 functions, ≤20
  lines, nesting ≤2, line ≤100), itself compliant with the standards.
- ruff + flake8 + flake8-functions (style, naming, imports, length).
- mypy --strict (platform=linux) for complete typing.
- pylint in addition (max-nested-blocks=2, max-args=4).
- pre-commit: `tools/norms` + ruff + flake8 + mypy --strict are BLOCKING on
  `src/` (fully typed). pylint in the `manual` stage.

## 7. Tests (see 05-tests.md): workflow
Note: `test_adws.py` (diagnostic, runs anywhere) and `test_handlers.py`
(isolated handlers, DC-only) live in `tools/test/`.
1. `test_adws.py` (environment diagnostic) on the DC.
2. `test_handlers.py` (isolated handlers, no network) on the DC.
3. `python3 -m src.main`, then `Test-ADWS-Sovereign.ps1 -SkipMutations`,
   then without `-SkipMutations`.
Any fix to a documented behaviour updates the documentation in the
same commit.

## 8. To be specified (outside the repository)
- Targeted Samba AD version, Windows version of the clients, domain
  functional level.

## 9. Deliverables
- Code compliant with §6.1 (and §6.2 depending on decisions).
- Linter configs + pre-commit hook + in-house AST checker.
- The two missing Python test suites (§7).
- `documentation/` kept up to date with every behaviour change.

## 10. Agent tooling (project skills and agents)
Available in `.claude/` (created for this project):
- Skill `add-handler`: scaffolds a SOAP handler plus its routing wiring.
- Skill `check-norms`: runs `python -m tools.norms` (the §6.1 checker).
- Skill `decode-wcf`: decodes a WCF binary payload into XML (debugging).
- Agent `adws-protocol-expert`: protocol research (Open Specifications,
  RFCs, W3C).
- Agent `norms-auditor`: audits the §6.1 standards and the §5 invariants
  on a diff.
- Agent `interop-parity-auditor`: static check of our `classes/`/`src/`
  serialization against the format specifications (xsi:type, LdapSyntax,
  EPR namespaces, RootDSE table). Preventive.
- Agent `wire-triage`: reactive forensics, from a captured WCF payload or a
  .NET stack trace to the root cause and the `file:line` to fix.
- Agent `doc-sync-auditor`: checks that a behaviour change updates
  `documentation/` (§7/§9).
- Agent `regression-tester`: runs the test ladder (§7) and reports the
  regressions against the last run (`tools/test/adws-test-results/*.json`).
- Agent `adws-coverage-auditor`: authority on the complete ADWS functional
  surface; spots the missing or untested functions and writes the tests
  (loop: coverage → tests → regression-tester → fixes).

Enforcement: `tools/norms/` (AST checker, itself compliant with §6.1),
wired into `.pre-commit-config.yaml` (blocking §6.1 on `src/` and `classes/`; mypy /
pylint / line length in the `manual` stage). Configs: `pyproject.toml`,
`.flake8`, `.pylintrc`. Dev tools: `tools/installation/requirements-dev.txt`.
