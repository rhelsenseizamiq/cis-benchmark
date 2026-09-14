# CIS Benchmark PDF Importer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `cis import <pdf-path> --cloud aws` subcommand that parses an official CIS AWS Foundations Benchmark PDF into a structured JSON rule catalog, without touching what `cis scan` does today.

**Architecture:** A new `cis_benchmark/importer/` package with four small, single-purpose modules (`errors.py`, `schema.py`, `pdf_extract.py`, `aws_parser.py`), wired into `cli.py` via argparse subparsers (`scan` / `import`). Text extraction (shelling out to `pdftotext -layout`) is fully separated from structural parsing (regex-based, operating on already-clean text) so each is independently testable. The parser uses a two-pass strategy: first parse the PDF's own "Appendix: Summary Table" into an authoritative ordered list of rule IDs, then use that list as anchors to carve the document body — never scanning the body for "any numbered line," which would misidentify numbered cross-references inside `CIS Controls:` sections as new rules.

**Tech Stack:** Python 3.10+, `pdftotext` (poppler-utils, external system binary — required only for `cis import`, not for `cis scan`), stdlib `re`/`subprocess`/`shutil`/`dataclasses`/`json`, pytest.

**Spec:** `docs/superpowers/specs/2026-09-14-cis-benchmark-pdf-importer-design.md`

## Global Constraints

- CLI-only. No GUI, ever — this is a hard product constraint from the project owner.
- `cis scan` (all its flags, defaults, and output) must be byte-for-byte unchanged after this work. Every existing test in `tests/` must still pass without modification.
- Bare `cis --cloud aws ...` (no explicit `scan` subcommand) must keep working exactly as it does today — this is existing, documented, tested behavior.
- No real CIS Benchmark PDF content or extracted text may be committed to the repo (licensing — see spec). Tests use synthetic fixtures only. `.gitignore` already has both `*.pdf` and `imports/` (the default `cis import` output directory) — this was done ahead of this plan; no task needs to repeat it, just don't remove either line.
- Follow the project's existing conventions: relative imports within `cis_benchmark/` (`from .models import ...`, `from ..core.x import ...`), flat test files directly under `tests/` (no subdirectories — the existing suite has none), dataclasses for structured data (matching `core/models.py`'s `CheckResult` pattern), commit messages as plain descriptive imperative titles (no `feat:`/`fix:` prefixes — none of this repo's existing commits use them).
- Every expected failure mode (missing `pdftotext`, unparseable structure, unimplemented `--cloud` choice) raises `ImporterError` and is caught at the CLI boundary to print a clean message — never a raw traceback, matching the project's established "fail loud with a clear, actionable message" pattern from the cloud checks (`Status.ERROR` with a real explanation, not a silent wrong answer).

---

### Task 1: Importer data model (`errors.py` + `schema.py`)

**Files:**
- Create: `cis_benchmark/importer/__init__.py` (empty)
- Create: `cis_benchmark/importer/errors.py`
- Create: `cis_benchmark/importer/schema.py`
- Test: `tests/test_importer_schema.py`

**Interfaces:**
- Produces: `ImporterError(Exception)`; `ImportedRule` dataclass (fields: `id: str`, `title: str`, `scored: bool`, `profile_level: str`, `section: str`, `description: str = ""`, `rationale: str = ""`, `impact: Optional[str] = None`, `audit: str = ""`, `remediation: str = ""`, `references: List[str] = field(default_factory=list)`, `cis_controls: str = ""`, `incomplete: bool = False`, `missing_sections: List[str] = field(default_factory=list)`); `BenchmarkCatalog` dataclass (fields: `benchmark_name: str`, `benchmark_version: str`, `source_filename: str`, `extracted_at: str`, `rules: List[ImportedRule] = field(default_factory=list)`) with `.to_dict()`, `.to_json(indent=2)`, `.write(path) -> str` methods; `now_iso() -> str` helper.

- [ ] **Step 1: Write the failing test**

Create `tests/test_importer_schema.py`:

```python
import json
import os

from cis_benchmark.importer.schema import ImportedRule, BenchmarkCatalog, now_iso


def test_imported_rule_defaults():
    rule = ImportedRule(id="1.1", title="Example", scored=True, profile_level="Level 1", section="1. Example")
    assert rule.description == ""
    assert rule.references == []
    assert rule.incomplete is False
    assert rule.missing_sections == []


def test_catalog_to_dict_includes_counts():
    rules = [
        ImportedRule(id="1.1", title="A", scored=True, profile_level="Level 1", section="1. X"),
        ImportedRule(id="1.2", title="B", scored=False, profile_level="Level 2", section="1. X", incomplete=True, missing_sections=["Remediation:"]),
    ]
    catalog = BenchmarkCatalog(
        benchmark_name="CIS Test Benchmark",
        benchmark_version="9.9.9",
        source_filename="test.pdf",
        extracted_at=now_iso(),
        rules=rules,
    )
    d = catalog.to_dict()
    assert d["total_rules"] == 2
    assert d["incomplete_rules"] == 1
    assert len(d["rules"]) == 2
    assert d["rules"][0]["id"] == "1.1"


def test_catalog_to_json_is_valid_json():
    catalog = BenchmarkCatalog(
        benchmark_name="CIS Test Benchmark", benchmark_version="9.9.9",
        source_filename="test.pdf", extracted_at=now_iso(), rules=[],
    )
    parsed = json.loads(catalog.to_json())
    assert parsed["benchmark_name"] == "CIS Test Benchmark"
    assert parsed["total_rules"] == 0


def test_catalog_write_creates_parent_dirs_and_file(tmp_path):
    catalog = BenchmarkCatalog(
        benchmark_name="CIS Test Benchmark", benchmark_version="9.9.9",
        source_filename="test.pdf", extracted_at=now_iso(),
        rules=[ImportedRule(id="1.1", title="A", scored=True, profile_level="Level 1", section="1. X")],
    )
    out_path = tmp_path / "nested" / "dir" / "catalog.json"
    result_path = catalog.write(str(out_path))

    assert result_path == str(out_path)
    assert out_path.exists()
    with open(out_path) as f:
        data = json.load(f)
    assert data["total_rules"] == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_importer_schema.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cis_benchmark.importer'`

- [ ] **Step 3: Write minimal implementation**

Create `cis_benchmark/importer/__init__.py` (empty file).

Create `cis_benchmark/importer/errors.py`:

```python
class ImporterError(Exception):
    """Raised for any expected `cis import` failure: missing pdftotext,
    a benchmark document whose structure doesn't match what the parser
    expects, or a --cloud choice with no parser implemented yet. Callers
    (cli.py) catch this and print a clean message — never a raw traceback.
    """
```

Create `cis_benchmark/importer/schema.py`:

```python
import json
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ImportedRule:
    id: str
    title: str
    scored: bool
    profile_level: str
    section: str
    description: str = ""
    rationale: str = ""
    impact: Optional[str] = None
    audit: str = ""
    remediation: str = ""
    references: List[str] = field(default_factory=list)
    cis_controls: str = ""
    incomplete: bool = False
    missing_sections: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class BenchmarkCatalog:
    benchmark_name: str
    benchmark_version: str
    source_filename: str
    extracted_at: str
    rules: List[ImportedRule] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "benchmark_name": self.benchmark_name,
            "benchmark_version": self.benchmark_version,
            "source_filename": self.source_filename,
            "extracted_at": self.extracted_at,
            "total_rules": len(self.rules),
            "incomplete_rules": sum(1 for r in self.rules if r.incomplete),
            "rules": [r.to_dict() for r in self.rules],
        }

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    def write(self, path: str) -> str:
        parent = os.path.dirname(os.path.abspath(path))
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write(self.to_json())
        return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_importer_schema.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add cis_benchmark/importer/__init__.py cis_benchmark/importer/errors.py cis_benchmark/importer/schema.py tests/test_importer_schema.py
git commit -m "Add importer data model (ImportedRule, BenchmarkCatalog, ImporterError)"
```

---

### Task 2: PDF text extraction (`pdf_extract.py`)

**Files:**
- Create: `cis_benchmark/importer/pdf_extract.py`
- Test: `tests/test_importer_pdf_extract.py`

**Interfaces:**
- Consumes: `ImporterError` from Task 1 (`cis_benchmark.importer.errors`).
- Produces: `extract_text(pdf_path: str) -> str`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_importer_pdf_extract.py`:

```python
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from cis_benchmark.importer.errors import ImporterError
from cis_benchmark.importer.pdf_extract import extract_text


def test_raises_clear_error_when_pdftotext_missing():
    with patch("cis_benchmark.importer.pdf_extract.shutil.which", return_value=None):
        with pytest.raises(ImporterError, match="poppler"):
            extract_text("whatever.pdf")


def test_raises_on_nonzero_exit():
    fake_result = MagicMock(returncode=1, stdout="", stderr="Syntax Error: bad PDF")
    with patch("cis_benchmark.importer.pdf_extract.shutil.which", return_value="/usr/bin/pdftotext"), \
         patch("cis_benchmark.importer.pdf_extract.subprocess.run", return_value=fake_result):
        with pytest.raises(ImporterError, match="Syntax Error"):
            extract_text("broken.pdf")


def test_raises_on_timeout():
    with patch("cis_benchmark.importer.pdf_extract.shutil.which", return_value="/usr/bin/pdftotext"), \
         patch("cis_benchmark.importer.pdf_extract.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pdftotext", timeout=60)):
        with pytest.raises(ImporterError, match="timed out"):
            extract_text("huge.pdf")


def test_strips_form_feed_characters():
    fake_result = MagicMock(returncode=0, stdout="1.1 Rule\n\x0cProfile Applicability:\n", stderr="")
    with patch("cis_benchmark.importer.pdf_extract.shutil.which", return_value="/usr/bin/pdftotext"), \
         patch("cis_benchmark.importer.pdf_extract.subprocess.run", return_value=fake_result) as mock_run:
        text = extract_text("clean.pdf")
    assert "\x0c" not in text
    assert "1.1 Rule\nProfile Applicability:\n" == text
    called_args = mock_run.call_args[0][0]
    assert called_args == ["pdftotext", "-layout", "clean.pdf", "-"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_importer_pdf_extract.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cis_benchmark.importer.pdf_extract'`

- [ ] **Step 3: Write minimal implementation**

Create `cis_benchmark/importer/pdf_extract.py`:

```python
import shutil
import subprocess

from .errors import ImporterError

_INSTALL_HINT = (
    "pdftotext (from poppler-utils) is required for `cis import` but was not "
    "found on PATH.\nInstall it with:\n"
    "  macOS:         brew install poppler\n"
    "  Debian/Ubuntu: sudo apt-get install poppler-utils\n"
)


def extract_text(pdf_path: str) -> str:
    """Extracts layout-preserving text from a PDF via `pdftotext -layout`,
    stripping the page-break form-feed characters pdftotext inserts (they
    can land mid-line and break line-start parsing downstream in
    aws_parser.py).
    """
    if shutil.which("pdftotext") is None:
        raise ImporterError(_INSTALL_HINT)

    try:
        result = subprocess.run(
            ["pdftotext", "-layout", pdf_path, "-"],
            capture_output=True,
            text=True,
            timeout=60,
        )
    except subprocess.TimeoutExpired:
        raise ImporterError(f"pdftotext timed out extracting text from {pdf_path}")

    if result.returncode != 0:
        raise ImporterError(f"pdftotext failed on {pdf_path}: {result.stderr.strip()}")

    return result.stdout.replace("\x0c", "")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_importer_pdf_extract.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add cis_benchmark/importer/pdf_extract.py tests/test_importer_pdf_extract.py
git commit -m "Add PDF text extraction wrapper for the benchmark importer"
```

---

### Task 3: AWS benchmark parser (`aws_parser.py`)

This is the core parsing logic — a two-pass strategy validated by hand against a real CIS AWS Foundations Benchmark v1.2.0 PDF during design (see spec's Investigation Findings). Pass 1 parses the PDF's own "Appendix: Summary Table" into an authoritative ordered rule list (title/scored, handling titles that wrap across lines). Pass 2 uses that list as anchors to carve the "Recommendations" body into per-rule blocks — critically, this never scans the body for "any line starting with a number," which would misidentify numbered cross-references inside `CIS Controls:` sections (e.g. `9.9 Require A Second Authentication Factor...`) as new rule boundaries.

**Files:**
- Create: `cis_benchmark/importer/aws_parser.py`
- Test: `tests/test_importer_aws_parser.py`

**Interfaces:**
- Consumes: `ImportedRule`, `BenchmarkCatalog`, `now_iso` (Task 1, `cis_benchmark.importer.schema`); `ImporterError` (Task 1, `cis_benchmark.importer.errors`).
- Produces: `parse(text: str, source_filename: str = "") -> BenchmarkCatalog`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_importer_aws_parser.py`:

```python
import pytest

from cis_benchmark.importer.errors import ImporterError
from cis_benchmark.importer.aws_parser import parse

# A synthetic "mini benchmark" built to exercise the exact structural
# wrinkles found by inspecting a real CIS AWS Foundations Benchmark PDF
# during design: a title that wraps across two lines before its
# (Scored)/(Not Scored) marker, a CIS Controls cross-reference number
# ("9.9 Require A Second...") that must NOT be mistaken for a new rule,
# and one deliberately-incomplete rule (missing Remediation:) to exercise
# the incomplete-flagging path. No real CIS content — see spec Licensing.
FIXTURE_HAPPY_PATH = '''CIS Amazon Web Services Foundations
Benchmark
v9.9.9 - 01-01-2099
Terms of Use
Please see the below link for our current terms of use:
https://example.invalid/terms

Table of Contents

Recommendations
1 Identity and Access Management
1.1 Avoid the use of the "root" account (Scored)
Profile Applicability:

 Level 1

Description:

Do not use the root account for daily tasks.

Rationale:

The root account has unrestricted access to everything.

Audit:

Run the following command:

  aws iam get-account-summary

Remediation:

Stop using the root account for daily tasks.

References:

   1. CCE-00000-0

CIS Controls:

9.9 Require A Second Authentication Factor For Privileged Accounts
Require a second authentication factor for all privileged account access.

1.2 Ensure multi-factor authentication (MFA) is enabled for all IAM users that have a
console password (Scored)
Profile Applicability:

 Level 1

Description:

MFA adds an extra layer of protection on top of a password.

Rationale:

Enabling MFA provides increased security for console access.

Audit:

Run the following command:

  aws iam list-mfa-devices

Remediation:

Enable MFA for all IAM users with a console password.

References:

   1. CCE-00000-1

CIS Controls:

9.9 Require A Second Authentication Factor For Privileged Accounts
Require a second authentication factor for all privileged account access.

1.3 Ensure this rule is intentionally left incomplete (Not Scored)
Profile Applicability:

 Level 2

Description:

This rule intentionally omits a Remediation section so the importer's
incomplete-flagging path can be tested.

Rationale:

Testing matters.

Audit:

Run the following command:

  aws iam get-account-summary

References:

   1. CCE-00000-2

Appendix: Summary Table
                         Control                                             Set
                                                                          Correctly
                                                                          Yes No
1      Identity and Access Management
1.1    Avoid the use of the "root" account (Scored)
1.2    Ensure multi-factor authentication (MFA) is enabled for all
       IAM users that have a console password (Scored)
1.3    Ensure this rule is intentionally left incomplete (Not Scored)

Appendix: Change History
Nothing to see here.
'''

# Summary Table lists rule 1.2 but the body never actually contains it —
# exercises the hard-error path (a rule the parser can't locate at all,
# as opposed to one it locates but finds incomplete).
FIXTURE_MISSING_RULE = '''CIS Amazon Web Services Foundations
Benchmark
v9.9.9 - 01-01-2099

Table of Contents

Recommendations
1 Identity and Access Management
1.1 Avoid the use of the "root" account (Scored)
Profile Applicability:

 Level 1

Description:

Do not use the root account for daily tasks.

Rationale:

The root account has unrestricted access to everything.

Audit:

Run the following command:

  aws iam get-account-summary

Remediation:

Stop using the root account for daily tasks.

References:

   1. CCE-00000-0

Appendix: Summary Table
1      Identity and Access Management
1.1    Avoid the use of the "root" account (Scored)
1.2    This rule is listed in the summary table but never appears in the body (Scored)

Appendix: Change History
Nothing to see here.
'''


def test_parses_all_rules_with_correct_ids_and_order():
    catalog = parse(FIXTURE_HAPPY_PATH, source_filename="fixture.pdf")
    assert [r.id for r in catalog.rules] == ["1.1", "1.2", "1.3"]


def test_extracts_benchmark_version_from_title_page():
    catalog = parse(FIXTURE_HAPPY_PATH)
    assert catalog.benchmark_version == "9.9.9"
    assert catalog.benchmark_name == "CIS Amazon Web Services Foundations Benchmark"


def test_wrapped_title_is_joined_correctly():
    catalog = parse(FIXTURE_HAPPY_PATH)
    rule_1_2 = next(r for r in catalog.rules if r.id == "1.2")
    assert rule_1_2.title == (
        "Ensure multi-factor authentication (MFA) is enabled for all "
        "IAM users that have a console password"
    )
    assert rule_1_2.scored is True


def test_cis_controls_cross_reference_is_not_mistaken_for_a_new_rule():
    catalog = parse(FIXTURE_HAPPY_PATH)
    # There must be exactly 3 rules — a broken parser would produce a
    # phantom "4.5" rule from the CIS Controls cross-reference text.
    assert len(catalog.rules) == 3
    assert "4.5" not in [r.id for r in catalog.rules]
    rule_1_1 = next(r for r in catalog.rules if r.id == "1.1")
    assert "9.9 Require A Second Authentication Factor" in rule_1_1.cis_controls


def test_fields_extracted_correctly_for_a_complete_rule():
    catalog = parse(FIXTURE_HAPPY_PATH)
    rule = next(r for r in catalog.rules if r.id == "1.1")
    assert rule.description == "Do not use the root account for daily tasks."
    assert rule.rationale == "The root account has unrestricted access to everything."
    assert rule.audit.startswith("Run the following command:")
    assert rule.remediation == "Stop using the root account for daily tasks."
    assert rule.references == ["CCE-00000-0"]
    assert rule.profile_level == "Level 1"
    assert rule.section == "1. Identity and Access Management"
    assert rule.incomplete is False
    assert rule.missing_sections == []


def test_incomplete_rule_is_flagged_not_dropped():
    catalog = parse(FIXTURE_HAPPY_PATH)
    rule = next(r for r in catalog.rules if r.id == "1.3")
    assert rule.incomplete is True
    assert "Remediation:" in rule.missing_sections
    assert rule.description  # still captured, just missing one section
    assert rule.profile_level == "Level 2"
    assert rule.scored is False


def test_missing_rule_in_body_raises_importer_error():
    with pytest.raises(ImporterError, match="1.2"):
        parse(FIXTURE_MISSING_RULE)


def test_empty_summary_table_raises_importer_error():
    with pytest.raises(ImporterError):
        parse("Recommendations\n\nAppendix: Summary Table\n\nAppendix: Change History\n")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_importer_aws_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cis_benchmark.importer.aws_parser'`

- [ ] **Step 3: Write minimal implementation**

Create `cis_benchmark/importer/aws_parser.py`:

```python
import re

from .errors import ImporterError
from .schema import BenchmarkCatalog, ImportedRule, now_iso

_RULE_ID_RE = re.compile(r"^(\d+(?:\.\d+){1,2})\s")
_SECTION_ID_RE = re.compile(r"^(\d+)\s+(.+)$")
_SCORED_SUFFIX_RE = re.compile(r"\((Scored|Not Scored)\)\s*$")
_VERSION_RE = re.compile(r"v(\d+\.\d+\.\d+)\s*-\s*[\d-]+")

_LABELS = [
    "Profile Applicability:",
    "Description:",
    "Rationale:",
    "Impact:",
    "Audit:",
    "Remediation:",
    "References:",
    "CIS Controls:",
    "Default Value:",
    "Additional Information:",
]
_REQUIRED_LABELS = ["Description:", "Rationale:", "Remediation:"]


def _find_index(text: str, marker: str) -> int:
    idx = text.find(marker)
    if idx == -1:
        raise ImporterError(
            f"Could not locate {marker!r} in the extracted text — this "
            "document's structure doesn't match what this parser expects."
        )
    return idx


def _parse_summary_table(text: str):
    """Returns an ordered list of (rule_id, section_name, title, scored)
    parsed from the PDF's own "Appendix: Summary Table" — the authoritative
    anchor list used to carve the body. Never derived by scanning the body
    itself, which would misidentify numbered cross-references inside
    "CIS Controls:" sections as new rules.
    """
    start = _find_index(text, "Appendix: Summary Table")
    end = text.find("Appendix: Change History", start)
    if end == -1:
        end = len(text)
    table_text = text[start:end]

    anchors = []
    current_section = ""
    pending_id = None
    pending_lines = []

    def flush():
        nonlocal pending_id, pending_lines
        if pending_id is not None:
            joined = " ".join(l.strip() for l in pending_lines if l.strip())
            m = _SCORED_SUFFIX_RE.search(joined)
            scored = (m.group(1) == "Scored") if m else None
            title = _SCORED_SUFFIX_RE.sub("", joined).strip()
            anchors.append((pending_id, current_section, title, scored))
        pending_id = None
        pending_lines = []

    for line in table_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        rule_m = _RULE_ID_RE.match(line)
        if rule_m:
            flush()
            pending_id = rule_m.group(1)
            pending_lines = [line[len(pending_id):]]
            continue
        section_m = _SECTION_ID_RE.match(line) if pending_id is None else None
        if section_m and "." not in section_m.group(1):
            flush()
            current_section = f"{section_m.group(1)}. {section_m.group(2).strip()}"
            continue
        if pending_id is not None:
            pending_lines.append(line)
    flush()

    if not anchors:
        raise ImporterError(
            "Parsed the Summary Table but found zero recommendations in it "
            "— refusing to produce an empty catalog."
        )
    return anchors


def _split_block_into_sections(block: str) -> dict:
    """Splits one rule's raw text block on the fixed CIS section labels,
    keeping only the labels actually present in this block.
    """
    positions = []
    for label in _LABELS:
        idx = block.find(f"\n{label}")
        if idx != -1:
            positions.append((idx, label))
    positions.sort()

    sections = {}
    for i, (idx, label) in enumerate(positions):
        content_start = idx + 1 + len(label)
        content_end = positions[i + 1][0] if i + 1 < len(positions) else len(block)
        sections[label] = block[content_start:content_end].strip()
    return sections


def parse(text: str, source_filename: str = "") -> BenchmarkCatalog:
    """Parses CIS AWS Foundations Benchmark text (already extracted and
    form-feed-stripped by pdf_extract.extract_text) into a BenchmarkCatalog.
    """
    version_m = _VERSION_RE.search(text)
    benchmark_version = version_m.group(1) if version_m else "unknown"

    anchors = _parse_summary_table(text)

    body_start = _find_index(text, "\nRecommendations\n")
    body_end = text.find("Appendix: Summary Table", body_start)
    if body_end == -1:
        body_end = len(text)
    body = text[body_start:body_end]

    rules = []
    missing_ids = []
    cursor = 0
    for i, (rule_id, section, title, scored) in enumerate(anchors):
        pattern = re.compile(rf"^{re.escape(rule_id)}\s", re.MULTILINE)
        m = pattern.search(body, cursor)
        if not m:
            missing_ids.append(rule_id)
            continue

        next_start = len(body)
        for next_id, *_rest in anchors[i + 1:]:
            next_pattern = re.compile(rf"^{re.escape(next_id)}\s", re.MULTILINE)
            next_m = next_pattern.search(body, m.end())
            if next_m:
                next_start = next_m.start()
                break

        block = body[m.start():next_start]
        cursor = next_start

        fields = _split_block_into_sections(block)
        missing = [lbl for lbl in _REQUIRED_LABELS if lbl not in fields]

        profile_raw = fields.get("Profile Applicability:", "")
        if "Level 2" in profile_raw:
            profile_level = "Level 2"
        elif "Level 1" in profile_raw:
            profile_level = "Level 1"
        else:
            profile_level = ""

        references_raw = fields.get("References:", "")
        references = [
            re.sub(r"^\s*\d+\.\s*", "", l).strip()
            for l in references_raw.splitlines()
            if l.strip()
        ]

        rules.append(ImportedRule(
            id=rule_id,
            title=title,
            scored=bool(scored),
            profile_level=profile_level,
            section=section,
            description=fields.get("Description:", ""),
            rationale=fields.get("Rationale:", ""),
            impact=fields.get("Impact:") or None,
            audit=fields.get("Audit:", ""),
            remediation=fields.get("Remediation:", ""),
            references=references,
            cis_controls=fields.get("CIS Controls:", ""),
            incomplete=bool(missing),
            missing_sections=missing,
        ))

    if missing_ids:
        raise ImporterError(
            f"Could not locate {len(missing_ids)} rule(s) from the Summary "
            f"Table in the document body: {', '.join(missing_ids)}. "
            f"Expected {len(anchors)} rules, found {len(rules)}."
        )

    return BenchmarkCatalog(
        benchmark_name="CIS Amazon Web Services Foundations Benchmark",
        benchmark_version=benchmark_version,
        source_filename=source_filename,
        extracted_at=now_iso(),
        rules=rules,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_importer_aws_parser.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add cis_benchmark/importer/aws_parser.py tests/test_importer_aws_parser.py
git commit -m "Add CIS AWS Foundations Benchmark PDF parser"
```

---

### Task 4: CLI subcommand wiring (`cis scan` / `cis import`)

**Files:**
- Modify: `cis_benchmark/cli.py`
- Test: `tests/test_cli_subcommands.py`

**Interfaces:**
- Consumes: `extract_text` (Task 2, `cis_benchmark.importer.pdf_extract`); `parse` as `parse_aws` (Task 3, `cis_benchmark.importer.aws_parser`); `ImporterError` (Task 1, `cis_benchmark.importer.errors`).
- Produces: `_normalize_argv(argv: list) -> list`; `_build_parser(settings: dict) -> argparse.ArgumentParser`; `_run_import(args: argparse.Namespace) -> None`; module-level `_IMPORT_PARSERS: dict` (patchable by tests).

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli_subcommands.py`:

```python
import argparse

import pytest

from cis_benchmark import cli
from cis_benchmark.core.config import load_settings
from cis_benchmark.importer.errors import ImporterError
from cis_benchmark.importer.schema import BenchmarkCatalog, ImportedRule


def test_bare_scan_flags_still_work():
    assert cli._normalize_argv(["--cloud", "aws"]) == ["scan", "--cloud", "aws"]


def test_empty_argv_defaults_to_scan():
    assert cli._normalize_argv([]) == ["scan"]


def test_explicit_scan_command_passes_through():
    assert cli._normalize_argv(["scan", "--cloud", "aws"]) == ["scan", "--cloud", "aws"]


def test_import_command_passes_through():
    assert cli._normalize_argv(["import", "file.pdf", "--cloud", "aws"]) == ["import", "file.pdf", "--cloud", "aws"]


def test_help_and_version_pass_through_unmodified():
    assert cli._normalize_argv(["--help"]) == ["--help"]
    assert cli._normalize_argv(["-h"]) == ["-h"]
    assert cli._normalize_argv(["--version"]) == ["--version"]


def test_parser_produces_scan_namespace_with_settings_defaults():
    settings = load_settings()
    parser = cli._build_parser(settings)
    args = parser.parse_args(cli._normalize_argv(["--cloud", "aws"]))
    assert args.command == "scan"
    assert args.cloud == "aws"
    assert args.workers == settings["max_worker_threads"]
    assert args.output == settings["output_directory"]
    assert args.plain is False


def test_parser_produces_import_namespace():
    settings = load_settings()
    parser = cli._build_parser(settings)
    args = parser.parse_args(["import", "/tmp/fake.pdf", "--cloud", "aws"])
    assert args.command == "import"
    assert args.pdf_path == "/tmp/fake.pdf"
    assert args.cloud == "aws"
    assert args.output is None


def test_import_requires_cloud_argument():
    settings = load_settings()
    parser = cli._build_parser(settings)
    with pytest.raises(SystemExit):
        parser.parse_args(["import", "/tmp/fake.pdf"])


def test_run_import_writes_catalog_and_prints_summary(tmp_path, monkeypatch, capsys):
    fake_catalog = BenchmarkCatalog(
        benchmark_name="Fake Benchmark", benchmark_version="9.9.9",
        source_filename="fake.pdf", extracted_at="now",
        rules=[ImportedRule(id="1.1", title="t", scored=True, profile_level="Level 1", section="1. X")],
    )
    monkeypatch.setattr(cli, "extract_text", lambda path: "irrelevant")
    monkeypatch.setattr(cli, "_IMPORT_PARSERS", {"aws": lambda text, source_filename="": fake_catalog})

    output_path = tmp_path / "out.json"
    args = argparse.Namespace(cloud="aws", pdf_path="fake.pdf", output=str(output_path))
    cli._run_import(args)

    assert output_path.exists()
    captured = capsys.readouterr()
    assert "Parsed 1 rule(s) (0 incomplete)" in captured.out


def test_run_import_rejects_unimplemented_cloud():
    args = argparse.Namespace(cloud="azure", pdf_path="fake.pdf", output=None)
    with pytest.raises(ImporterError, match="not implemented yet"):
        cli._run_import(args)


def test_run_import_default_output_path(tmp_path, monkeypatch):
    fake_catalog = BenchmarkCatalog(
        benchmark_name="Fake", benchmark_version="1.2.3",
        source_filename="fake.pdf", extracted_at="now", rules=[],
    )
    monkeypatch.setattr(cli, "extract_text", lambda path: "irrelevant")
    monkeypatch.setattr(cli, "_IMPORT_PARSERS", {"aws": lambda text, source_filename="": fake_catalog})
    monkeypatch.chdir(tmp_path)

    args = argparse.Namespace(cloud="aws", pdf_path="fake.pdf", output=None)
    cli._run_import(args)

    assert (tmp_path / "imports" / "aws_1.2.3.json").exists()


def test_main_prints_clean_error_and_exits_1_on_importer_error(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "argv", ["cis", "import", "fake.pdf", "--cloud", "azure"])
    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "not implemented yet" in captured.err
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli_subcommands.py -v`
Expected: FAIL — `cli._normalize_argv` / `cli._build_parser` / `cli._run_import` / `cli._IMPORT_PARSERS` don't exist yet (`AttributeError`).

- [ ] **Step 3: Write minimal implementation**

Modify `cis_benchmark/cli.py`. Replace the imports block at the top (lines 1-17 in the current file) with:

```python
import argparse
import os
import sys
from datetime import datetime, timezone

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table
from rich.text import Text

from . import __version__
from .core.config import load_settings
from .core.engine import ComplianceEngine
from .importer.aws_parser import parse as parse_aws
from .importer.errors import ImporterError
from .importer.pdf_extract import extract_text
from .reporters.doc_reporter import DocReporter
from .reporters.excel_reporter import ExcelReporter
from .reporters.html_reporter import HTMLReporter

_IMPORT_PARSERS = {"aws": parse_aws}
_KNOWN_COMMANDS = {"scan", "import"}
```

Everything from `BANNER = """` through the end of `_run_rich(...)` (today's lines 19-165) stays exactly as-is — do not modify `_generate_reports`, `_run_plain`, or `_run_rich` at all.

Replace the `def main():` function (today's lines 168-188) with:

```python
def _normalize_argv(argv):
    """Bare `cis --cloud aws` (no explicit subcommand) keeps working by
    defaulting to `scan` — every command documented before the `cis import`
    subcommand was added continues to work completely unchanged.
    """
    if not argv:
        return ["scan"]
    if argv[0] in _KNOWN_COMMANDS or argv[0] in ("-h", "--help", "--version"):
        return list(argv)
    return ["scan"] + list(argv)


def _build_parser(settings):
    parser = argparse.ArgumentParser(prog="cis", description="CIS Unified Multi-Cloud Compliance & Audit CLI")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    scan_parser = subparsers.add_parser("scan", help="Run compliance checks against your cloud accounts (default)")
    scan_parser.add_argument("--cloud", type=str, default="all", choices=["all", "gcp", "workspace", "aws", "azure"], help="Cloud provider target filter")
    scan_parser.add_argument("--domain", type=str, default=settings["google_workspace_domain"], help="Target domain for Workspace checks")
    scan_parser.add_argument("--workers", type=int, default=settings["max_worker_threads"], help="Number of concurrent worker threads")
    scan_parser.add_argument("--output", type=str, default=settings["output_directory"], help="Output directory for generated reports")
    scan_parser.add_argument("--plain", action="store_true", help="Plain, non-interactive output with no colors/progress bar (for cron, CI, or log capture)")

    import_parser = subparsers.add_parser("import", help="Convert an official CIS Benchmark PDF into a structured JSON rule catalog")
    import_parser.add_argument("pdf_path", type=str, help="Path to a downloaded CIS Benchmark PDF")
    import_parser.add_argument("--cloud", type=str, required=True, choices=["aws", "azure", "gcp", "workspace"], help="Which benchmark this PDF is")
    import_parser.add_argument("--output", type=str, default=None, help="Output JSON path (default: imports/<cloud>_<version>.json)")

    return parser


def _run_import(args):
    if args.cloud not in _IMPORT_PARSERS:
        raise ImporterError(
            f"`cis import --cloud {args.cloud}` is not implemented yet. "
            "Only --cloud aws is supported today."
        )

    text = extract_text(args.pdf_path)
    catalog = _IMPORT_PARSERS[args.cloud](text, source_filename=os.path.basename(args.pdf_path))

    output_path = args.output or os.path.join("imports", f"{args.cloud}_{catalog.benchmark_version}.json")
    catalog.write(output_path)

    total = len(catalog.rules)
    incomplete = sum(1 for r in catalog.rules if r.incomplete)
    print(f"Parsed {total} rule(s) ({incomplete} incomplete) -> {output_path}")


def main():
    settings = load_settings()
    parser = _build_parser(settings)
    args = parser.parse_args(_normalize_argv(sys.argv[1:]))

    if args.command == "import":
        try:
            _run_import(args)
        except ImporterError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        return

    engine = ComplianceEngine(max_workers=args.workers, target_domain=args.domain, cloud_filter=args.cloud)
    if args.plain:
        _run_plain(engine, args.output)
    else:
        _run_rich(engine, args.output)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli_subcommands.py -v`
Expected: PASS (11 tests)

Then run the **full existing suite** to confirm nothing broke:

Run: `python -m pytest -v`
Expected: PASS (all tests, previous 17 plus the new ones from Tasks 1-4)

Then manually verify the installed command still behaves correctly:

Run: `pip install -e ".[dev]" && cis --cloud workspace --plain --output /tmp/cli_check`
Expected: Runs exactly as before (bare `--cloud` flag still works, no `scan`/`import` needed).

Run: `cis scan --cloud workspace --plain --output /tmp/cli_check`
Expected: Identical output to the command above.

Run: `cis import --help`
Expected: Shows `pdf_path`, `--cloud`, `--output` usage.

- [ ] **Step 5: Commit**

```bash
git add cis_benchmark/cli.py tests/test_cli_subcommands.py
git commit -m "Add cis import subcommand, keep bare cis --cloud X working via scan default"
```

---

### Task 5: README documentation + real-file acceptance check

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing new (documentation only).

- [ ] **Step 1: Manually verify against the real PDF (not an automated test — a one-time acceptance check)**

The project owner has a real CIS AWS Foundations Benchmark v1.2.0 PDF (used during design, not committed to the repo per licensing). Run:

```bash
pip install -e ".[dev]"
cis import /path/to/AWS_CIS_Foundations_Benchmark.pdf --cloud aws --output /tmp/aws_catalog.json
python3 -c "
import json
d = json.load(open('/tmp/aws_catalog.json'))
print('total_rules:', d['total_rules'])
print('incomplete_rules:', d['incomplete_rules'])
print('benchmark_version:', d['benchmark_version'])
print('sample rule 1.13:', json.dumps([r for r in d['rules'] if r['id']=='1.13'][0], indent=2)[:500])
"
```

Expected: `total_rules: 49`, `incomplete_rules: 0`, `benchmark_version: 1.2.0`, and rule `1.13`'s fields (title "Ensure MFA is enabled for the "root" account", description/rationale/audit/remediation all populated) match what was manually inspected during design. If this doesn't match, stop and fix `aws_parser.py` before writing docs that claim this works — do not document a feature that doesn't actually work against a real file.

- [ ] **Step 2: Update README**

In `README.md`, in the `## 🎯 Scope & Coverage` section, find this paragraph:

```
There is currently no automated pipeline that downloads or parses those official PDFs into this tool's check set — every check here was written by hand against the provider's CLI. If you want that pipeline built (download → parse → drive checks from the real benchmark), that's a real feature to design, not a quick fix — ask and we'll scope it properly.
```

Replace it with:

```
As of this version, `cis import` can parse an official CIS AWS Foundations Benchmark PDF into a complete, structured JSON catalog of all its recommendations (see "Importing an official benchmark PDF" below) — but this produces a *reference catalog* for coverage tracking, not new automated checks. A PDF describes what to check in prose; it can't generate the AWS-CLI-calling verification logic a real check needs. Azure/GCP/Workspace PDF import is not yet implemented.
```

In the `## ⚡ Features & Capabilities` bullet list, find:

```
- ☁️ **Multi-Cloud Support**: AWS, Microsoft Azure, Google Cloud Platform (GCP), and Google Workspace.
```

Add a bullet immediately after it:

```
- 📥 **Benchmark PDF Import**: `cis import <pdf> --cloud aws` parses an official CIS Benchmark PDF into a structured JSON rule catalog (AWS only today).
```

Add a new section right before `## 📁 Project Architecture`:

````
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
(free CIS account required). Only the AWS Foundations Benchmark is
supported today.

```bash
cis import /path/to/CIS_AWS_Foundations_Benchmark.pdf --cloud aws
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
````

- [ ] **Step 3: Fix the incorrect AWS benchmark version claim**

In `README.md`'s `## 🎯 Scope & Coverage` table, find:

```
| 🟠 AWS | 4 (root MFA, S3 public access block, SG unrestricted SSH, CloudTrail) | CIS AWS Foundations Benchmark has 50+ recommendations |
```

Replace with (using the real, verified number from Step 1's acceptance check — adjust `49` if the real run produced a different count):

```
| 🟠 AWS | 4 (root MFA, S3 public access block, SG unrestricted SSH, CloudTrail) | CIS AWS Foundations Benchmark **v1.2.0** has 49 recommendations (verified via `cis import`) |
```

- [ ] **Step 4: Verify the README's example commands actually work**

Run every command block added/changed in Steps 2-3 by hand (the `brew install poppler` one can be skipped if poppler is already installed) to confirm none of them have typos or wrong flag names.

- [ ] **Step 5: Commit**

```bash
git add README.md
git commit -m "Document cis import, correct AWS benchmark version claim to v1.2.0"
git push
```
