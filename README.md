# 🛡️ CIS Unified Multi-Cloud Compliance & Audit CLI

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

A high-performance, professional terminal CLI security auditing tool for **AWS**, **Microsoft Azure**, **Google Cloud Platform (GCP)**, and **Google Workspace**.

---

## ⚡ Features & Capabilities

- 🚀 **Fast Parallel Execution**: Evaluates 18 multi-cloud security checks in sub-second execution (< 1 second, network/API latency aside).
- 🎨 **Rich Terminal Interface**: Professional ASCII header banner, live progress bars, status badges, and executive score cards.
- ☁️ **Multi-Cloud Support**: AWS, Microsoft Azure, Google Cloud Platform (GCP), and Google Workspace.
- 📥 **Benchmark PDF Import**: `cis import <pdf> --cloud <aws|azure|gcp|workspace>` parses an official CIS Benchmark PDF into a structured JSON rule catalog.
- 📊 **Multi-Format Export**: Generates **Interactive HTML Dashboard**, **Excel Workbook (.xlsx)**, and **Markdown (.md)** reports.

---

## 🎯 Scope & Coverage — read this before you trust a score

This tool does **not** implement the full official CIS Benchmarks. It implements a small, hand-picked set of **18 checks total**, chosen because they're common, high-impact, and checkable via each provider's CLI:

| Cloud | Checks implemented | Real official benchmark size (for comparison) |
| :--- | :--- | :--- |
| 🟠 AWS | 4 (root MFA, S3 public access block, SG unrestricted SSH, CloudTrail) | CIS AWS Foundations Benchmark **v1.2.0** has 49 recommendations (verified via `cis import`) |
| 🔵 Azure | 3 (privileged MFA — manual, storage public blob, NSG unrestricted SSH) | CIS Azure Foundations Benchmark has 100+ recommendations |
| 🟢 GCP | 6 (SA key age, primitive roles, firewall SSH/RDP, public buckets, Cloud SQL public IP) | CIS GCP Foundations Benchmark has 90+ recommendations |
| 🔴 Google Workspace | 5 (4 are honest `MANUAL_CHECK` placeholders — see below; only SPF/DMARC is automated) | CIS Google Workspace Foundations Benchmark **v1.4** has 86 recommendations (verified via `cis import`) |

**Two things this means in practice:**

1. **The rule IDs are this project's own, not CIS's.** `AWS-1.1`, `GCP-3.2`, etc. are numbered by this codebase for its own bookkeeping — they do not correspond to the official CIS Benchmark's own section/control numbers. Don't cite them as if they were.
2. **A "100% compliance score" from this tool is not the same as "CIS Benchmark compliant."** It means these 18 specific checks passed — nothing more. For a full, official assessment, use the actual CIS Benchmark PDFs (free, requires a CIS account) from **https://www.cisecurity.org/cis-benchmarks**, or a CIS-certified scanning tool.

As of this version, `cis import` can parse official CIS Benchmark PDFs (AWS, Azure, GCP, Google Workspace) into a complete, structured JSON catalog of all their recommendations (see "Importing an official benchmark PDF" below) — but this produces a *reference catalog* for coverage tracking, not new automated checks. A PDF describes what to check in prose; it can't generate the CLI-calling verification logic a real check needs.

---

## 🔑 Required Credentials & Cloud Access

Before scanning, ensure your environment or CLI is authenticated with read-only access for each target provider:

| Cloud Provider | Authentication / Command | Minimum Required Role / Policy |
| :--- | :--- | :--- |
| 🟢 **Google Cloud (GCP)** | `gcloud auth login` or `GOOGLE_APPLICATION_CREDENTIALS` | `Security Reviewer` (`roles/iam.securityReviewer`) or `Viewer` |
| 🟠 **AWS** | `aws configure` or `AWS_ACCESS_KEY_ID` / `AWS_SECRET_ACCESS_KEY` | `SecurityAudit` or `ReadOnlyAccess` managed policy |
| 🔵 **Microsoft Azure** | `az login` or `AZURE_CLIENT_ID` / `AZURE_TENANT_ID` / `AZURE_CLIENT_SECRET` | `Reader` role on Target Subscription |
| 🔴 **Google Workspace** | Just `--domain company.com` — no Google auth needed today | None. Only the SPF/DMARC check is automated (public DNS lookups); the other 4 checks are `MANUAL_CHECK` placeholders that call no API at all. Admin SDK + Workspace Admin permissions will be required once those are implemented for real. |

---

## 📦 Installation

This is a CLI-only tool — there is no GUI, and none is planned. Install it as a regular Python package into a virtualenv:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"     # editable install + pytest for running tests
```

That gives you a real `cis` command on your `PATH` (via `pyproject.toml`'s `console_scripts` entry point) — it works from any directory, not just the repo root. To build a distributable wheel instead: `pip install build && python -m build`.

---

## 💻 CLI Usage

> Run `cis scan --help` or `cis import --help` to see each subcommand's full flag list — `cis --help` alone only lists the subcommand names.

### Run All Clouds
```bash
cis --cloud all --domain yourdomain.com
```

### Audit Specific Cloud Provider
```bash
# Audit AWS only
cis --cloud aws

# Audit Azure only
cis --cloud azure

# Audit GCP only
cis --cloud gcp

# Audit Google Workspace only
cis --cloud workspace --domain example.com
```

### Custom Threads & Output Directory
```bash
cis --cloud all --workers 20 --output ./custom_reports
```

### Plain output (cron / CI / log capture)
```bash
cis --cloud all --plain
```
Drops the Rich banner/progress bar/live table in favor of simple line-per-rule output — same engine, same reports, just script-friendly stdout. There is one CLI entrypoint (`cis_benchmark/cli.py`); `--plain` selects the output mode, so there's no separate binary to keep in sync.

### Version
```bash
cis --version
```

---

## 📥 Importing an Official Benchmark PDF

`cis import` turns an official CIS Benchmark PDF into a structured JSON
catalog of every recommendation in it — useful for seeing exactly how much
of the real benchmark this tool's 18 automated checks actually cover. It
does **not** create new automated checks (see Scope & Coverage above).

**Prerequisite:** `pdftotext`, from `poppler-utils` — only needed for
`cis import`, not for `cis scan`.

```bash
# macOS
brew install poppler

# Debian/Ubuntu
sudo apt-get install poppler-utils
```

**Getting a PDF:** Download the official benchmark from
[cisecurity.org/cis-benchmarks](https://www.cisecurity.org/cis-benchmarks)
(free CIS account required). AWS, Azure, GCP, and Google Workspace are
supported today.

```bash
cis import /path/to/CIS_Amazon_Web_Services_Foundations_Benchmark_v7.0.0.pdf --cloud aws
cis import /path/to/CIS_Microsoft_Azure_Foundations_Benchmark_v6.0.0.pdf --cloud azure
cis import /path/to/CIS_Google_Cloud_Platform_Foundation_Benchmark_v5.0.0.pdf --cloud gcp
cis import /path/to/CIS_Google_Workspace_Foundations_Benchmark_v1.4.pdf --cloud workspace
```

Older, already-verified versions work too — `cis import` doesn't care about
the filename, only `--cloud` and the PDF's actual content:

```bash
cis import /path/to/CIS_Amazon_Web_Services_Foundations_Benchmark_v1.2.0.pdf --cloud aws
cis import /path/to/CIS_Microsoft_Azure_Foundations_Benchmark_v1.4.0.pdf --cloud azure
cis import /path/to/CIS_Google_Cloud_Platform_Foundation_Benchmark_v1.2.0.pdf --cloud gcp
```

Writes to `imports/aws_<version>.json` by default (override with
`--output`). That directory is gitignored: the generated JSON reproduces
CIS's own copyrighted rule text (descriptions, rationale, remediation
steps), so it isn't committed automatically — check CIS's terms of use
before committing it yourself.

The command reports how many rules it found and how many it couldn't fully
parse, e.g. `Parsed 49 rule(s) (0 incomplete) -> imports/aws_1.2.0.json`.
An `incomplete: true` rule in the output JSON means the parser found that
recommendation but one of its expected sections (Description/Rationale/
Remediation) was missing — check `missing_sections` on that rule and treat
its data as partial.

Each cloud's parser is only verified against the specific benchmark
version(s) actually tested against real data (see the table below). If a
PDF's detected version isn't in that list, the import still proceeds
(never blocked), but the catalog is stamped `"version_verified": false`
and the CLI prints a warning — treat results from an unverified version
with extra scrutiny; the document's structure may differ from what the
parser expects, and it's already the case (found by testing against real
Azure/GCP data) that even the same rough CIS template era can differ in
heading text and classification vocabulary between benchmark generations.

| Cloud | Verified version(s) |
| :--- | :--- |
| AWS | 1.2.0, 7.0.0 |
| Azure | 1.4.0, 6.0.0 |
| GCP | 1.2.0, 5.0.0 |
| Workspace | 1.4 |

---

## 📁 Project Architecture

```
CIS_Benchmark/
├── pyproject.toml               # Build config, dependencies, `cis` entry point
├── cis_benchmark/                # The installable package
│   ├── __init__.py              # __version__ (read from installed package metadata)
│   ├── cli.py                   # CLI entrypoint (Rich UI + --plain mode)
│   ├── core/
│   │   ├── engine.py            # Concurrent multi-threaded execution engine
│   │   ├── base_check.py        # Abstract Check interface
│   │   ├── models.py            # Dataclasses & Status Enums
│   │   ├── config.py            # Settings resolution (CWD override -> bundled defaults)
│   │   └── default_settings.json # Defaults bundled inside the installed package
│   ├── modules/                  # Cloud Provider Audit Modules
│   │   ├── aws_checks.py        # AWS IAM, S3, EC2, CloudTrail
│   │   ├── azure_checks.py      # Azure AD, Storage, NSGs
│   │   ├── gcp_checks.py        # GCP IAM, Storage, VPC, Cloud SQL
│   │   └── workspace_checks.py  # Workspace 2SV, SPF/DMARC, OAuth
│   └── reporters/                # Report Generators
│       ├── html_reporter.py     # Dark-mode HTML Dashboard
│       ├── excel_reporter.py    # Formatted XLSX Workbook
│       └── doc_reporter.py      # Markdown Report
├── config/settings.json         # OPTIONAL project-local override (see below)
├── benchmarks/                   # Reference-only JSON Benchmark Specifications
├── tests/                        # pytest suite
└── output/                       # Generated Reports (default)
```

> **Settings resolution order:** `core/config.py::load_settings()` checks, in
> order: (1) an explicit path (tests only), (2) a `config/settings.json` in
> your **current working directory** if present — this repo ships one as a
> ready-to-edit example, (3) the defaults bundled inside the installed
> package (`cis_benchmark/core/default_settings.json`), (4) a hardcoded
> fallback dict as an absolute last resort. This is what makes a real,
> non-editable `pip install` work correctly even after the source checkout
> is gone — the earlier design (a single `config/settings.json` living
> outside the package) would have silently broken in that case.
>
> **`benchmarks/*.json`** is reference documentation mirroring the rules
> actually implemented in `cis_benchmark/modules/*_checks.py` — it is **not**
> loaded at runtime, so the check logic in code is always the source of
> truth.

---

## 📋 Result Statuses

| Status | Meaning |
| :--- | :--- |
| ✅ `PASS` | The control was verified against the live environment and is compliant. |
| ❌ `FAIL` | The control was verified and is **not** compliant. |
| ⚠️ `WARNING` | The check ran but found a soft issue (e.g. a weak-but-present DMARC policy). |
| 🔍 `MANUAL_CHECK` | This rule is not yet automated (e.g. it needs Admin SDK / Microsoft Graph API access this tool doesn't call) — verify it manually. It never reports PASS or FAIL. |
| 💥 `ERROR` | The underlying CLI call itself failed (auth, network, bad flag) — the control's real state is unknown, and this must not be read as compliant. |

---

## 📄 License

Licensed under the [GNU General Public License v3.0](LICENSE).
