# Phase F Completion Report

Date: 2026-09-05

Project: Invoice / Purchase Order Reconciliation

Scope: CI, release and security hardening, reproducibility, and portfolio presentation

## Outcome

Phase F completes the V0.1 core local tool. The repository now has cross-version GitHub Actions
verification, weekly dependency maintenance, safer forced file replacement, release artifact
checks, a focused security policy, a reproducible quick start, and a portfolio-oriented README.

The accepted CSV schemas, reconciliation rules, result/report schemas, CLI arguments, and exit
codes remain unchanged. No web application, API, database, authentication, OCR, ML, or new
business rule was added.

## Starting point

Work started on `main` from the clean, pushed Phase E head:

```text
0b24b37 docs: record phase E completion
```

## CI

The workflow is `.github/workflows/ci.yml`. It runs for pushes to `main` and pull requests with a
matrix of Python 3.11 and 3.12. Each matrix run:

1. checks out the repository with persisted credentials disabled;
2. installs Python and enables a pip cache keyed from `pyproject.toml`;
3. installs the project with `python -m pip install -e ".[dev]"`;
4. runs `python -m pytest -vv`;
5. runs `python -m ruff check .`;
6. runs `python -m ruff format --check .`;
7. runs `python -m pip check`;
8. invokes both `python -m reconcile --help` and `reconcile --help`;
9. runs the sample data through the installed console script;
10. builds the source and wheel distributions.

The Python 3.12 matrix run additionally installs the wheel into a clean virtual environment and
runs its console entry point and sample reconciliation. The workflow does not set `PYTHONPATH` or
execute the package directly from `src`.

Only official `actions/checkout@v7` and `actions/setup-python@v7` actions are used. Stable major
tags allow compatible maintenance updates while Dependabot reviews action-version changes weekly.
The job has read-only repository-content permission.

The Phase F commits were pushed to `main`. GitHub Actions run
[`33930885216`](https://github.com/boudani-ayoub/Invoice-Purchase-Order-Reconciliation/actions/runs/33930885216)
completed successfully, including both `Python 3.11` and `Python 3.12` matrix jobs.

## Security review

| Concern | Finding | Risk | Decision | Change |
| --- | --- | --- | --- | --- |
| Path and shell handling | Application code uses `pathlib` and Python file APIs. It has no subprocess, `shell=True`, expression evaluation, or execution of CSV content. | A caller can access paths already permitted to that operating-system user; the tool is not a filesystem sandbox. | Keep the local-user trust boundary and advise ordinary user privileges. | Documentation only. |
| Malformed input | Strict UTF-8 CSV parsing, exact schemas, scalar validation, and structured `CsvValidationError` handling already cover expected failures. | Invalid input could otherwise expose an internal traceback. | Preserve strict validation. | Added a regression proving an over-limit CSV field becomes a controlled validation error. |
| Oversized input | Python's CSV parser enforces its runtime field-size limit, but all valid rows and domain objects are held in memory. | A huge local file can consume substantial memory or processing time. | Do not invent an arbitrary low cap for a non-networked V0.1 batch tool. | Documented limitation; future web uploads need explicit limits. |
| CSV formula injection | Supplier, invoice, PO, and item identifiers are source-controlled and may begin with spreadsheet formula characters. Currency cannot because its schema requires three uppercase letters. | Spreadsheet software may interpret exported identifiers as formulas. | Preserve the detailed CSV's exact machine-readable values and warn consumers to import identifiers as text. | Documentation only; no silent prefixing or schema change. |
| Overwrite behavior | Without `--force`, preflight is followed by exclusive `"x"` creation, so a path appearing during the race is still refused. | Interrupted creation can leave a partial new file, but an existing file is never silently replaced. | Keep exclusive creation. | Behavior unchanged and limitation documented. |
| Forced single-file output | Phase E wrote directly to a final path. | A low-level interruption could truncate the previous report. | Stage complete UTF-8 content beside the destination, flush and `fsync`, then replace it. | Fixed in `src/reconcile/cli.py`; failure-path regression added. |
| Forced two-file CSV output | Preflight existed, but the first final file could be changed before the second write succeeded. | The output pair could be inconsistent after a write failure. | Write both temporary files before either replacement. Do not claim a transactional pair. | Fixed staging risk; a second replacement failure can still leave one new and one old final file. |
| Unexpected filesystem errors | Input `OSError` becomes source validation; expected output `OSError` becomes exit code 4. Diagnostics include the path supplied by the caller. | Permission, disk, or device failures remain possible. | Keep actionable errors without masking programming defects. | No contract change. |
| Dependencies | Runtime uses only the Python standard library. pytest, Ruff, and build are development-only. | A runtime dependency scanner would have no third-party application package to audit. | Keep the zero third-party runtime surface; do not add `pip-audit` for badge value. | Added weekly Dependabot checks for Python development dependencies and GitHub Actions. |
| Secrets and sample data | Filename and content-pattern scans found no credentials, private keys, tokens, certificates, passwords, or local absolute paths. Sample identifiers and scenarios are synthetic fixtures. | Accidental real data would undermine a public portfolio repository. | Keep fixtures deterministic and explicitly label them synthetic. | Documentation and a portability regression test added. |

## Output hardening

Forced terminal/JSON output now uses a `NamedTemporaryFile` in the destination directory. Content
is completely rendered before writing, then written as UTF-8, flushed, synchronized with
`os.fsync`, closed, and replaced into the final path. Temporary files are removed after failures
where possible.

Forced CSV output performs both temporary writes before replacing either report. Tests simulate a
single-file staging failure and a failure during the second CSV staging write; prior final files
remain byte-for-byte unchanged and temporary files are cleaned up in both cases.

Two filesystem replacements cannot be made ACID with this simple standard-library design. Complex
rollback or journaling was intentionally not introduced.

## Packaging and reproducibility

`build` is included in the development dependency group. Current setuptools license metadata now
uses the SPDX expression `MIT`, explicitly includes `LICENSE`, and removes the deprecated license
classifier. Project name, version `0.1.0`, author, README, Python requirement, and Python 3.11/3.12
classifiers are consistent.

`python -m build` successfully produced:

```text
dist/invoice_purchase_order_reconciliation-0.1.0.tar.gz
dist/invoice_purchase_order_reconciliation-0.1.0-py3-none-any.whl
```

The wheel contains the `reconcile` package, console-script metadata, distribution metadata, and
license, with no sample-data runtime dependency. `MANIFEST.in` makes the source archive
self-contained by including the security policy, phase reports, test suite, and synthetic sample
CSVs. Generated build artifacts remain ignored by Git.

The wheel was installed with `--no-deps` into a newly created temporary virtual environment. Both
entry points displayed the accepted help contract, and the installed console script reproduced the
15-invoice sample with 17 result rows and the accepted summary. The temporary environment was
removed after verification.

## README and repository polish

The README now opens with the business value and V0.1 status, illustrates cumulative invoice
exposure, shows the data-to-CLI architecture, and provides a clean-clone quick start. It documents
all output modes, the exact sample result, the input contract, engineering choices, technology,
CI/build commands, security boundary, honest limitations, and a clearly separate future web layer.

A single CI badge links to the actual workflow. No coverage, download, production, or security
score badges were added. `SECURITY.md` records the current local-tool threat boundary and private
reporting guidance. No Docker or small-project process bureaucracy was added.

## Verification

Verification used Python 3.12.7 from the project virtual environment:

| Command | Result |
| --- | --- |
| `python -m pip install -e ".[dev]"` | Passed; editable package and build tooling installed |
| `python -m pytest -vv` | Passed: 180 passed, 0 failed |
| `python -m ruff check .` | Passed |
| `python -m ruff format --check .` | Passed: 33 files already formatted |
| `python -m pip check` | Passed: no broken requirements |
| `python -m build` | Passed: sdist and universal wheel built |
| clean wheel install with `--no-deps` | Passed |
| clean-wheel `python -m reconcile --help` | Passed |
| clean-wheel `reconcile --help` | Passed |
| clean-wheel sample JSON workflow | Passed with accepted summary |
| installed editable `reconcile --help` | Passed |
| installed editable `python -m reconcile --help` | Passed |
| installed editable sample terminal workflow | Passed |
| installed editable sample JSON-file workflow | Passed and parsed successfully |
| local absolute-path regression | Passed |
| credential/private-key filename and content-pattern scan | No findings |
| GitHub Actions CI | Passed: Python 3.11 and Python 3.12 |
| `git diff --check` | Passed |
| `git diff --cached --check` | Passed |

Python 3.11 was not installed on the local Windows host, so its verification came from the clean
GitHub-hosted matrix job. Both supported Python versions passed the same installed-package test,
lint, format, dependency, CLI, sample, and build workflow.

The first sandboxed package-build attempt could not download isolated build requirements, and the
build frontend exposed a localized output-decoding error while reporting that network denial. The
same command succeeded with dependency-download access, and the final clean build had no warning or
error. This was an execution-environment restriction, not a repository build failure.

## Sample acceptance

All accepted business behavior is unchanged:

```text
invoices: 15
invoice lines: 17
matched: 6
review required: 11

UNKNOWN_PO=1
UNKNOWN_ITEM=1
DUPLICATE_INVOICE=2
SUPPLIER_MISMATCH=1
CURRENCY_MISMATCH=1
MISSING_RECEIPT=1
QUANTITY_EXCEEDS_PO=2
QUANTITY_EXCEEDS_RECEIPT=2
PRICE_MISMATCH=1

EUR=2450.00
MAD=10199.00
USD=75.00
```

## Remaining limits

- V0.1 is a local in-memory batch tool, without explicit total-file or row-count limits.
- It has no returns, credit notes, taxes, freight, or as-of-date mode.
- It has no receipt-level findings model.
- Whole-document duplicate proof requires a source occurrence identifier not present in V0.1.
- Machine-readable CSV does not escape spreadsheet formula characters.
- Non-forced interrupted creation may leave a partial new file.
- A forced two-file CSV replacement is staged but not transactional across both final paths.
- Web UI, HTTP API, uploads, database, users, authentication, and saved history are separate work.

## Final core-tool status

V0.1 is ready to present as a portfolio project and to use as a deterministic local CLI within its
documented scope. Its package boundaries, typed financial logic, stable output contracts, tests,
release artifacts, security decisions, and CI definition also make it a suitable engine for a
future application layer.

## Future work

A future web application should wrap the existing package rather than replace it, and should be
planned as a separate project layer with its own upload limits, threat model, persistence model,
and deployment design. It is not Phase G of the completed core roadmap unless deliberately defined
later.
