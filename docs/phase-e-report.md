# Phase E Completion Report

Date: 2026-09-04

Project: Invoice / Purchase Order Reconciliation

Scope: Command-line orchestration only

## Outcome

Phase E is complete. The installed `reconcile` command and `python -m reconcile` now run the same
thin CLI over the existing loaders, reconciliation engine, and Phase D renderers.

No database, HTTP API, web interface, OCR, LLM, ERP integration, configuration system, business
policy option, or Phase F CI work was added.

## Repository starting point

Work started from the clean, pushed Phase D head on `main`:

```text
71196b8 docs: record phase D completion
```

## Architecture

The command pipeline is:

```text
argparse
  -> Phase B loaders
  -> Phase C reconcile()
  -> Phase D renderers
  -> stdout or explicit UTF-8 output paths
```

`src/reconcile/cli.py` owns argument parsing, orchestration, expected error mapping, destination
preflight, and file writing. `src/reconcile/__main__.py` delegates directly to `main()`. The
`pyproject.toml` console script points to the same function. No source validation, reconciliation,
or report schema is duplicated in the CLI.

## CLI contract

```text
usage: reconcile [-h] --purchase-orders PATH --receipts PATH --invoices PATH
                 [--format {terminal,json,csv}] [--output PATH] [--force]
```

Required inputs:

- `--purchase-orders PATH`
- `--receipts PATH`
- `--invoices PATH`

`--format` accepts only `terminal`, `json`, or `csv` and defaults to `terminal`. The CLI does not
infer format from a filename. `--force` requires `--output`.

## Output behavior

### Terminal

Without `--output`, the exact `render_terminal_report()` string is written to stdout. With
`--output`, that same string is written to the named file.

### JSON

Without `--output`, the exact `render_json_report()` document is written to stdout. With
`--output`, that same document is written to the named file.

### CSV

CSV requires `--output DIRECTORY` and never emits two concatenated tables to stdout. It writes:

```text
reconciliation-results.csv
reconciliation-summary.csv
```

using the exact Phase D renderers. Missing destination parents are created. Output files use
UTF-8 with the renderers' existing `\n` line endings.

## Overwrite policy

Existing report files are refused by default with exit code 4 and an actionable stderr message.
`--force` permits replacement.

CSV mode preflights both final filenames before writing either. If one exists without `--force`,
neither output is changed or created. It also rejects a directory occupying either expected CSV
filename before writing the other file. Both CSV strings are rendered in memory before writes
begin.

V0.1 does not claim a transactional two-file commit after preflight; a new low-level filesystem
failure during the second write could still leave the first file written. Atomic temporary-file
replacement can be evaluated as release hardening without changing the CLI contract.

## Process streams and exit codes

Successful stdout mode writes only report content. Successful file mode writes a concise path
confirmation. Expected failures keep stdout empty and write diagnostics to stderr.

| Code | Meaning |
| ---: | --- |
| `0` | Success |
| `1` | Unexpected unhandled application failure |
| `2` | Argparse usage or argument error |
| `3` | Input/source validation error (`CsvValidationError`) |
| `4` | Expected output or filesystem error |

Normal malformed or missing input does not show a traceback. For example:

```text
CSV validation failed with 1 issue:

invalid-purchase-orders.csv:2
column: ordered_quantity
value: '-3'
reason: ordered_quantity must be a finite decimal greater than zero
```

## Packaging

`pyproject.toml` defines:

```toml
[project.scripts]
reconcile = "reconcile.cli:main"
```

The installed distribution metadata and `python -m reconcile --help` are covered by tests. Manual
verification also invoked the executable created in `.venv/Scripts`.

## Verification

Verification used Python 3.12.7 from the project `.venv`:

| Command | Result |
| --- | --- |
| `python -m pip install -e ".[dev]"` | Passed; console script installed |
| `python -m pytest -vv` | Passed: 176 passed, 0 failed |
| `python -m ruff check .` | Passed |
| `python -m ruff format --check .` | Passed: 29 files already formatted |
| `python -m pip check` | Passed: no broken requirements |
| `git diff --check` | Passed |
| `git diff --cached --check` | Passed |

## Manual CLI verification

The installed executable was exercised against `examples/sample_data` in every required mode:

- terminal stdout: exit 0 and readable report;
- JSON stdout: exit 0 and parseable 17-result document;
- nested JSON file: exit 0 and parent directory created;
- CSV directory: exit 0 and exactly two parseable files with 17 detail rows;
- repeated JSON write without `--force`: exit 4 and original file preserved;
- repeated JSON write with `--force`: exit 0 and file replaced;
- malformed purchase-order CSV: exit 3, structured stderr, no traceback.

Both public invocations display the same help contract:

```text
reconcile --help
python -m reconcile --help
```

The accepted business output remains:

```text
results: 17
invoices: 15
matched: 6
review required: 11
disputed: EUR=2450.00, MAD=10199.00, USD=75.00
```

Issue counts also remain unchanged from Phase D.

## Limitations

V0.1 intentionally has no stdin support, input-directory discovery, interactive overwrite prompt,
format inference, `--version`, configuration file, environment configuration, or business-policy
flags. Unexpected internal programming failures are left visible and exit through the Python
runtime rather than being mislabeled as normal validation or output errors.

## Scope check

Phase E added only CLI and packaging orchestration. There is no database, API, web UI, OCR, new
integration, new report schema, or modification to reconciliation business rules. No Phase F CI
or portfolio-polish work was started.

## Exact next step

Begin Phase F by adding a GitHub Actions workflow that installs the package and runs pytest, Ruff,
format checking, and pip integrity on supported Python versions. Then improve the README's
portfolio overview with architecture, control decisions, and reproducible CLI demonstrations.
Keep all accepted Phase B-E contracts unchanged unless a failing compatibility check identifies a
specific defect.
