# CIS_Benchmark — Fix Report

**Date:** 2026-09-12
**Scope:** Full review of the project followed by fixes for every issue found. Verified with a new `tests/` pytest suite (16 tests, all passing) and an end-to-end smoke run of both CLIs.

This document explains **what was broken, why it mattered, and what changed.** Issues are grouped the same way they were found: false-positive/false-pass correctness bugs first (the most dangerous class for a security-audit tool), then spec/config inconsistencies, then smaller robustness and display issues.

---

## 1. Critical correctness bugs (false "compliant" results)

### 1.1 Azure MFA check could never fail
**File:** `modules/azure_checks.py` — `AzureCheckMFAAdmins`
**Before:** Both the `if account:` and `else` branches set `status = Status.PASS`. The check queried `az account show` (which only proves an authenticated session, nothing about MFA policy) and reported "Privilege MFA policy enforced" unconditionally.
**Why it mattered:** A CRITICAL-severity control — MFA for privileged Entra ID accounts — would show green on every single run, regardless of the real tenant configuration. This is worse than not having the check at all, because it gives false assurance.
**Fix:** The check now returns `Status.MANUAL_CHECK` with an explicit note that verifying Conditional Access / MFA policy requires Microsoft Graph API access this tool doesn't have yet, and points to where to verify manually. It can no longer report PASS without actually checking anything.

### 1.2 AWS Security Group SSH check was silently broken
**File:** `modules/aws_checks.py` — `AWSCheckSecurityGroupIngressSSH`
**Before:** Used `aws ec2 describe-security-groups --format=json`. `--format` is **gcloud** syntax, not a valid AWS CLI flag — it looks like a copy-paste from the GCP module. The AWS CLI would reject the command, the helper swallowed the error and returned `None`, and the check fell through to a false **PASS** ("No Security Groups permit unrestricted SSH ingress") even on a wide-open account.
**Fix:** Changed to the correct `--output json` flag, applied consistently across all AWS CLI calls.

### 1.3 Four Google Workspace checks were hardcoded stubs with zero verification
**File:** `modules/workspace_checks.py` — `WorkspaceCheck2SV`, `WorkspaceCheckFIDO2Admins`, `WorkspaceCheckOAuthRestricted`, `WorkspaceCheckAdminAuditLogs`
**Before:** Each of these returned `Status.PASS` with a canned "Verified: ..." message and made **no API call whatsoever**, despite docstrings claiming to check "via Admin SDK API." Only `WorkspaceCheckSPF_DKIM_DMARC` (WS-3.1) did real work.
**Why it mattered:** These are exactly the controls attackers go after first — 2-Step Verification enforcement, FIDO2-for-admins, OAuth app restrictions, audit logging. Reporting all four as compliant unconditionally is the most dangerous defect in the project.
**Fix:** All four now return `Status.MANUAL_CHECK` with a clear explanation of what real API integration would require (Admin SDK Directory/Reports API with domain-wide delegation), instead of fabricating a PASS.

### 1.4 Fail-open pattern in every cloud CLI helper
**Files:** `modules/aws_checks.py`, `modules/azure_checks.py`, `modules/gcp_checks.py`
**Before:** `run_aws_json` / `run_az_json` / `run_gcloud_json` caught every exception and returned `None` on any failure (bad auth, expired token, network error, invalid command). Each check then had to guess what "no data" meant, and several defaulted toward PASS.
**Why it mattered:** An audit run against an environment with broken/expired CLI credentials could report a clean bill of health instead of surfacing that nothing was actually verified.
**Fix:** All three helpers now return `(ok, data)`. `ok=False` (non-zero exit, timeout, or unparsable JSON) makes every check return `Status.ERROR` with the underlying CLI error message, instead of silently falling back to PASS or FAIL. This was verified live in this sandbox (no AWS/Azure CLI installed, gcloud installed but unauthenticated): a real run now correctly shows 12/18 checks as `ERROR` — where the old code would have shown a misleading mix of false PASS/FAIL results.

---

## 2. Spec and config files that conflicted with the actual code

### 2.1 `benchmarks/*.json` didn't match, and weren't even loaded by, the implementation
**Files:** `benchmarks/gcp_foundations_v2.0.json`, `benchmarks/google_workspace_v1.4.json`
**Before:** The GCP spec listed 10 rules; only 6 were implemented (missing GCP-2.1, 2.2, 4.2, 5.2). The Workspace spec listed 10 rules; only 5 were implemented (missing WS-1.3, 1.4, 2.1, 2.2, 3.2). Neither file was referenced anywhere in the Python code (confirmed by grep) — they were pure dead documentation overstating real coverage.
**Fix:** Trimmed both files to exactly the rules that have a corresponding check class, added a `_note` field stating they are reference-only and not loaded at runtime, and added a `planned_not_yet_implemented` list for the rules that were dropped, so the gap is explicit instead of silently misleading.

### 2.2 `config/settings.json` was completely dead
**File:** `config/settings.json`
**Before:** No code anywhere read this file. `key_expiration_threshold_days: 90` had no connection to the hardcoded `90` in `gcp_checks.py`; `max_worker_threads`, `output_directory`, and `google_workspace_domain` were ignored in favor of hardcoded CLI argparse defaults.
**Fix:** Added `core/config.py::load_settings()` — a safe loader that reads `config/settings.json` and falls back to built-in defaults on any missing/invalid key (never raises, so a broken settings file can't break the CLI). Wired it into:
- `core/engine.py` — `GCPCheckServiceAccountKeys` now takes `max_key_age_days` from settings instead of a hardcoded `90`.
- `cis_cli.py` and `run_audit.py` — `--workers`, `--output`, and `--domain` argparse defaults now come from settings.
- `gcp_project_id` and `severity_weights` remain **intentionally unused** — see "Not fixed / left as follow-ups" below.

### 2.3 `requirements.txt` was wrong in both directions
**File:** `requirements.txt`
**Before:** `rich` (used throughout `cis_cli.py`) was **missing** — a clean `pip install -r requirements.txt` followed by `./cis` would crash with `ModuleNotFoundError`. Meanwhile `google-api-python-client`, `google-auth`, `google-auth-httplib2`, `google-auth-oauthlib`, `jinja2`, and `python-docx` were listed but never imported anywhere (confirmed by grep across all `.py` files).
**Fix:** Trimmed to exactly what's imported: `rich` and `openpyxl`.

### 2.4 `run_audit.py` couldn't scope to a single cloud provider
**File:** `run_audit.py`
**Before:** Unlike `cis_cli.py`, it never exposed `--cloud`, even though `ComplianceEngine` supports filtering. It always ran all 18 checks.
**Fix:** Added the `--cloud` argument, matching `cis_cli.py`'s behavior, and wired settings-based defaults the same way. (Kept as a separate entrypoint rather than deleting it — it looks like the intentional non-interactive/no-TTY variant of `cis_cli.py` for cron/log use, since Rich's progress bars need a terminal. Flagging this design decision in case you'd rather consolidate the two.)

---

## 3. Robustness, security, and display issues

### 3.1 No HTML escaping in the HTML report (stored-XSS-shaped bug)
**File:** `reporters/html_reporter.py`
**Before:** `details`, `section`, `title`, and every item in `affected_resources` were interpolated directly into HTML with no escaping. These fields include live cloud resource names (bucket names, security group names, NSG rule names) — an attacker who can name a cloud resource (e.g. an S3 bucket called `<script>...</script>`) could inject markup/script into a report a human later opens in a browser.
**Fix:** All dynamic fields are now passed through `html.escape()`. Verified with a test that plants `<script>alert(1)</script>` in `affected_resources` and confirms it's rendered as literal text, not markup.

### 3.2 No Excel/CSV formula-injection protection (same bug class as #3.1)
**File:** `reporters/excel_reporter.py`
**Before:** Cell values built from live resource names/details were written to the workbook unsanitized. A string cell starting with `=`, `+`, `-`, or `@` is interpreted as a formula by Excel/LibreOffice when the file is opened, regardless of how openpyxl wrote it — the same class of formula-injection bug you'd previously fixed in the IPAM project's CSV export.
**Fix:** Added `_sanitize_cell()`, which prefixes any string starting with a formula-trigger character with a leading `'` (the standard neutralization), applied to every dynamic cell in the Detailed Findings sheet.

### 3.3 `Status.ERROR` and `Status.MANUAL_CHECK` were indistinguishable from a soft warning
**Files:** `cis_cli.py`, `reporters/html_reporter.py`, `reporters/doc_reporter.py`, `reporters/excel_reporter.py`
**Before:** Each reporter's status branching only special-cased `PASS`/`FAIL`; everything else (`WARNING`, `ERROR`, `MANUAL_CHECK`) fell into one generic "⚠ WARN" bucket. A check that crashed due to a CLI auth failure looked identical to a soft warning. Separately, in `cis_cli.py`, any severity other than `CRITICAL`/`HIGH` was hardcoded to display the literal text `"MEDIUM"` — a `LOW`/`INFO` finding would have been mislabeled.
**Fix:** Replaced the if/elif chains with explicit per-status (and per-severity) style maps in all four files, giving `MANUAL_CHECK` (🔍 cyan/blue) and `ERROR` (💥 magenta/purple) their own distinct rendering everywhere, and making severity text always reflect the real value.

### 3.4 `core/engine.py` merged "couldn't verify" and "needs manual review" into one bucket
**File:** `core/engine.py`
**Before:** `error_count` summed both `Status.ERROR` and `Status.MANUAL_CHECK` — two semantically different outcomes ("the tool broke" vs. "this isn't automated yet") reported as one number, and `Status.MANUAL_CHECK` was never actually produced by any check before this fix, so the bug was latent.
**Fix:** Split into separate `manual` and `errors` fields in the summary dict; all three reporters and the CLI banner now show both.

### 3.5 Dead code
- `socket` import in `modules/workspace_checks.py` — never used. Removed.
- `Optional` import in `core/models.py` — never used. Removed.
- `results_json = json.dumps(...)` in `reporters/html_reporter.py` — computed but never referenced anywhere in the template. Removed, along with the now-unused `json` import in that file.

### 3.6 Deprecation warning surfaced by the new test suite
**File:** `core/models.py`
`datetime.utcnow()` is deprecated on the Python version installed in this project's venv (3.14). Replaced with `datetime.now(timezone.utc)`.

---

## 4. Not fixed / left as follow-ups (deliberately)

- **`gcp_project_id` in `config/settings.json` is still unused.** Wiring it in would mean adding `--project=<id>` to every `gcloud` command across `gcp_checks.py` instead of relying on the ambient `gcloud config` context — a behavior change (explicit targeting vs. current-context targeting) worth a deliberate decision rather than a silent side-effect of a "fix bugs" pass.
- **`severity_weights` in `config/settings.json` is still unused.** The compliance score is a flat `passed / total` ratio; there's no existing weighted-scoring formula to plug these into. Introducing one would change what the headline score means, which felt like a product decision for you to make, not something to decide unilaterally while fixing bugs.
- **Azure MFA and the four Workspace checks are `MANUAL_CHECK`, not real API integrations.** Building real Microsoft Graph / Google Admin SDK calls needs live credentials and a real tenant to test against, which aren't available here — shipping unverified "real" checks I can't test against a live environment would risk trading a known-bad bug (always PASS) for an unknown-bad one (a broken check that *looks* legitimate). `MANUAL_CHECK` is the honest, testable middle ground; happy to build the real integrations in a follow-up session against your actual tenant/subscription.
- **`run_audit.py` vs. `cis_cli.py` duplication** — kept both (see §2.4) rather than deleting one, since I wasn't certain the plain-print variant isn't in use somewhere (cron, CI). Let me know if you'd like them consolidated.

---

## 5. Verification

- Added `tests/` (5 files, 16 tests) covering: the AWS `--output json` fix and fail-open→`ERROR` behavior, the Azure/Workspace `MANUAL_CHECK` fixes, the engine's manual/error count separation, the configurable GCP key-rotation threshold, the settings loader's fallback behavior, HTML escaping, and Excel formula-injection sanitization. All 16 pass (`pytest.ini` added; run with `venv/bin/python -m pytest`).
- Ran `python -m py_compile` on every source file — no syntax errors.
- Ran both CLIs end-to-end (`cis_cli.py --cloud all` and `run_audit.py --cloud workspace`) in this sandbox (no AWS/Azure CLI installed, gcloud installed but unauthenticated). Confirmed: no crashes, 12/18 checks correctly report `ERROR` instead of the old code's false PASS/FAIL results, the 5 previously-fake checks correctly report `MANUAL_CHECK`, and all three report formats (HTML/XLSX/MD) generated successfully. Regenerated the example reports in `output/` so they reflect this corrected behavior instead of the pre-fix demo data.
- Added `rich` and `pytest` to the project's `venv` (pytest is a dev-only addition for running `tests/`, not added to `requirements.txt`).

---

*Generated as part of a fix pass requested after a full project review. See conversation history for the original review that identified these issues.*

---

# Part 2 — Packaging & Distribution Migration

**Date:** 2026-09-12
**Scope:** Turned the project into a real, installable Python package (the first of four "make it more professional" priorities you picked — packaging, extensibility/config, CI-friendly output, real API integrations, in that build order). CLI-only throughout, as requested — no GUI was added or considered anywhere in this change.

## What changed

### Package restructuring
`core/`, `modules/`, `reporters/` moved under a single top-level package, `cis_benchmark/`. Before this, a `pip install` would have dropped generically-named top-level modules (`core`, `modules`, `reporters`) directly into site-packages — a real collision risk with any other installed package doing the same. Every internal import was converted to a relative import (`from .models import ...`, `from ..modules.gcp_checks import ...`) instead of hardcoding the package name, so the package can be renamed again later without touching internal files. Added explicit `__init__.py` to `cis_benchmark/core`, `cis_benchmark/modules`, `cis_benchmark/reporters` — Python's implicit namespace packages would have worked without them, but explicit is the professional convention and avoids tooling gotchas (mypy, older setuptools) down the line.

### Two CLI entrypoints merged into one
`cis_cli.py` (Rich UI) and `run_audit.py` (plain print, and previously missing `--cloud`) merged into `cis_benchmark/cli.py`. A new `--plain` flag switches to simple line-per-rule output with no banners/progress bar/colors — covers the cron/CI/log-capture case the second script existed for, without a second argument parser to keep in sync. Also added `--version`.

### `pyproject.toml` — the project is now a real package
Build backend `hatchling`. One console-script entry point: `cis = "cis_benchmark.cli:main"`. Runtime deps `rich` + `openpyxl`; `dev` optional-dependency group adds `pytest`. `requirements.txt` deleted — superseded by this file. Version (`1.4.0`) now lives in exactly one place; `cis_benchmark/__init__.py` reads it back via `importlib.metadata.version("cis-benchmark")` (falling back to `"0.0.0-dev"` if run unin­stalled), and the HTML report's badge — previously a hardcoded `v1.4.0` string — now reads this instead.

### `config/settings.json` now actually survives a real install — and a real bug this exposed
The design as originally presented ("`config/settings.json` stays put, path resolved relative to install location") was wrong: a file living outside the package directory does not ship with a non-editable `pip install` once the source checkout is gone. Fixed by bundling a default copy inside the package (`cis_benchmark/core/default_settings.json`, loaded via `importlib.resources`), with resolution order: (1) explicit path (tests), (2) a `./config/settings.json` in the current working directory if present — preserving the original override UX, and this repo still ships one as an example, (3) the bundled package default, (4) a hardcoded dict as an absolute last resort.

**Building and testing this surfaced a real, previously-latent bug:** the repo's example `config/settings.json` has `"google_workspace_domain": null`. The settings merge logic copied that `null` straight over the `"example.com"` default, so running `cis --cloud workspace` from the repo root **without** `--domain` silently queried DNS for the literal domain `"None"` instead of falling back sensibly — reported as a false `WARNING` ("Missing SPF record for domain 'None'"), not a crash, so it would have been easy to miss. Root cause: `if key in data: settings[key] = data[key]` treated a JSON `null` as "explicitly override to `None`" rather than "not set." Fixed in `cis_benchmark/core/config.py` to skip `None` values during the merge, added a regression test (`test_null_value_in_settings_file_does_not_clobber_default`), and reproduced the exact failing command before and after the fix to confirm it.

### Cleanup
Deleted the `./cis` bash wrapper and the checked-in `venv/` directory (per your answer to keep only the installed console script). Removed the `version` field from `config/settings.json` (dead now that `pyproject.toml` is the single source of truth — it was never actually read by `load_settings()` either, since it's not a recognized settings key). Trimmed the standalone `pytest.ini` in favor of `[tool.pytest.ini_options]` inside `pyproject.toml` (one config source instead of two). Removed stray `.DS_Store`/`.mypy_cache`/`__pycache__` clutter and added a `.gitignore` (this project has no git repo yet — worth doing before you initialize one).

## Verification

- Full pytest suite (17 tests now, up from 16 — added the null-settings regression test) passes against the editable install.
- Built an actual wheel (`python -m build --wheel`) and inspected its contents — confirmed `cis_benchmark/core/default_settings.json` is bundled automatically by hatchling.
- Installed that wheel into a **fresh, isolated venv with zero connection to the source checkout** and ran `cis --version` / `cis --cloud workspace --plain` from `/tmp` — the real test of "this is now a proper installable package," not just an editable-install-in-place.
- Ran `cis` from arbitrary working directories in both `--plain` and Rich modes, confirmed the HTML report's version badge reads `v1.4.0` from installed package metadata, confirmed `pip check` reports no broken requirements, and reran `py_compile` across every source and test file.
- Regenerated the example reports in `output/` one final time with the finished, installed CLI.

## Not done (next up per the agreed build order)

Extensibility/config (plugin-style rule loading, baseline/suppressions, severity-gating flags), CI-friendly output (JSON/SARIF, exit codes), and the four real cloud API integrations (AWS/boto3, Azure/Graph, GCP/google-cloud-*, Workspace/Admin SDK) are still ahead, in that order, each as its own design-then-implement cycle.

---

*Part 2 generated as part of the packaging & distribution work you approved after the brainstorming/design conversation. See conversation history for that design discussion.*
