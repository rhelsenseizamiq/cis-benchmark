# Workspace Benchmark PDF Importer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `cis import` to support `--cloud workspace`, by generalizing three shared-engine patterns (rule-ID depth, version-string segments, Summary Table end-boundary) that were built AWS/Azure/GCP-shaped and silently fail on the real Google Workspace Foundations Benchmark v1.4 PDF's deeper structure, plus adding two new artifact-stripping regexes at the extraction layer and a new `workspace_parser.py`.

**Architecture:** `cis_benchmark/importer/_pdf_benchmark_parser.py` (the shared engine already used by `aws_parser.py`/`azure_parser.py`/`gcp_parser.py`) gets four small, behavior-preserving generalizations verified against the real Workspace PDF during design: an unbounded-depth rule-ID regex, an unbounded-segment version regex, a Summary Table end-boundary based on "next literal `Appendix:`" instead of a hardcoded marker string, and a one-line title cleanup that strips a leading `(L1)`/`(L2)` profile-level tag (cosmetic only — `profile_level` itself is already populated correctly today from the unrelated `Profile Applicability:` body field, unmodified). `cis_benchmark/importer/pdf_extract.py` gets two new whole-line-anchored stripping regexes for Workspace's page-footer and watermark formats. `workspace_parser.py` is a new ~10-line config + wrapper, following the exact shape of `azure_parser.py`/`gcp_parser.py`.

**Tech Stack:** Python 3.10+, `pdftotext -layout` (poppler-utils), `re`, `dataclasses`, `pytest`.

**Spec:** `docs/superpowers/specs/2026-09-15-workspace-benchmark-importer-design.md`

## Global Constraints

- No real CIS PDF content or extracted text is ever committed to git — test fixtures are synthetic/fictional from the start, never verbatim real CIS Benchmark wording.
- Every change to `_pdf_benchmark_parser.py` and `pdf_extract.py` must keep the full existing test suite green — these files are already depended on by AWS/Azure/GCP's shipped, verified parsers, and this plan's changes must be provably safe supersets of current behavior, not new branches.
- Commit messages: plain imperative title (e.g. `Generalize shared engine for Workspace's deeper rule-ID nesting`), no `feat:`/`fix:` prefix. Apply whatever trailer convention is currently active for your session when you run `git commit` — this plan does not hardcode one.
- The real Workspace PDF is at `/Users/administrator/Desktop/CIS_Benchmark/CIS_Google_Workspace_Foundations_Benchmark_v1.4.pdf` (gitignored, not to be committed) — used only for the manual acceptance check in Task 4, never referenced by an automated test.
- Verified ground truth from the design spec's investigation (use as given facts): 86/86 real rules recovered, 0 missing, 0 incomplete; sections `{'1. Directory': 3, '3. Apps': 55, '4. Security': 18, '5. Reporting': 2, '6. Rules': 8}`.

---

### Task 1: Generalize the shared parsing engine for Workspace's deeper structure

**Files:**
- Modify: `cis_benchmark/importer/_pdf_benchmark_parser.py`
- Test: `tests/test_importer_pdf_benchmark_parser.py`

**Interfaces:**
- Consumes: nothing new — this task only changes internals of `_pdf_benchmark_parser.py` (`_RULE_ID_RE`, `_VERSION_RE`, `_parse_summary_table`, `BenchmarkParserConfig`), all already defined in the existing file.
- Produces: `BenchmarkParserConfig` no longer has an `appendix_end_marker` field (removed — no config in the codebase sets it explicitly, confirmed by `grep -rn "appendix_end_marker" cis_benchmark tests` returning only the two lines inside `_pdf_benchmark_parser.py` itself before this task's edit). `parse_benchmark(text, config, source_filename="")`'s signature and return type (`BenchmarkCatalog`) are unchanged — later tasks call it exactly as `aws_parser.py`/`azure_parser.py`/`gcp_parser.py` already do.

This task changes code that AWS's, Azure's, and GCP's shipped parsers already depend on. Every existing test in `tests/test_importer_pdf_benchmark_parser.py`, `tests/test_importer_aws_parser.py`, `tests/test_importer_azure_parser.py`, and `tests/test_importer_gcp_parser.py` must still pass after this task — that is the regression check for those three clouds (per the design spec's Non-goals section, no real old-version AWS/Azure/GCP PDF re-verification is needed; the synthetic fixtures already exercise the shapes that must keep working).

- [ ] **Step 1: Write the four failing tests**

Open `tests/test_importer_pdf_benchmark_parser.py` and add the following at the end of the file (after the existing `test_grouping_header_with_no_marker_and_no_body_content_is_excluded` function):

```python
# Regression fixtures for the Workspace finding: rule IDs go up to 6
# segments deep (e.g. real "3.1.2.1.1.6"), far beyond AWS/Azure/GCP's max
# of 3 — the old _RULE_ID_RE (capped at {1,2} extra segments) silently
# failed to match anything deeper, which was the root cause of an initial
# broken run recovering only 32 of 86 real rules. Also exercises multiple
# levels of intermediate grouping headers (2, 3, and 4 segments), each
# with no classification marker and no body content, which must all be
# dropped the same way the existing single-level grouping-header test
# above already proves for a 2-segment header.
FIXTURE_DEEP_NESTING = '''CIS Test Benchmark 2
v9.9.9 - 01-01-2099

Table of Contents

Recommendations
1 Sharing Controls
1.1 Sharing Options
1.1.1 File Sharing
1.1.1.1 External Sharing
1.1.1.1.1 Ensure external file sharing defaults to view-only access (Manual)
Description:

Files shared externally should default to view-only permissions.

Rationale:

View-only defaults reduce accidental data modification by external parties.

Remediation:

Set the external sharing default to view-only.

Appendix: Recommendation Summary
Table
1          Sharing Controls
1.1        Sharing Options
1.1.1      File Sharing
1.1.1.1    External Sharing
1.1.1.1.1  Ensure external file sharing defaults to view-only access (Manual)

Appendix: Change History
Nothing to see here.
'''


def test_rule_id_regex_matches_ids_deeper_than_three_segments():
    catalog = parse_benchmark(FIXTURE_DEEP_NESTING, _GENERIC_CONFIG)
    assert [r.id for r in catalog.rules] == ["1.1.1.1.1"]
    assert catalog.rules[0].classification == "Manual"


def test_intermediate_multi_segment_grouping_headers_are_all_dropped():
    catalog = parse_benchmark(FIXTURE_DEEP_NESTING, _GENERIC_CONFIG)
    ids = [r.id for r in catalog.rules]
    assert "1.1" not in ids
    assert "1.1.1" not in ids
    assert "1.1.1.1" not in ids
    assert len(catalog.rules) == 1


def test_version_regex_accepts_two_segment_version_string():
    text = FIXTURE_HAPPY_PATH.replace("v9.9.9 - 01-01-2099", "v9.9 - 01-01-2099")
    config = BenchmarkParserConfig(
        benchmark_name="CIS Test Benchmark",
        appendix_marker="Appendix: Summary Table",
        classification_words=["Scored", "Not Scored"],
        known_versions=["9.9"],
    )
    catalog = parse_benchmark(text, config)
    assert catalog.benchmark_version == "9.9"
    assert catalog.version_verified is True


# Regression fixture for the Workspace finding: the Summary Table is
# directly followed by an appendix type AWS/Azure/GCP don't have, sitting
# between the Summary Table and Appendix: Change History. The old
# end-boundary logic searched specifically for the literal string
# "Appendix: Change History", which would sweep this extra appendix's
# content into the table slice too (observed as duplicate/corrupted
# anchors on the real document). The row inside the extra appendix below
# deliberately reuses "1.1" as its leading token to prove it would corrupt
# the anchor list if swept in.
FIXTURE_EXTRA_APPENDIX_BEFORE_CHANGE_HISTORY = '''CIS Test Benchmark
v9.9.9 - 01-01-2099

Table of Contents

Recommendations
1 Identity and Access Management
1.1 Ensure account root access keys are removed (Scored)
Description:

Root access keys should not exist.

Rationale:

Root has unrestricted access.

Remediation:

Remove root access keys.

Appendix: Summary Table
1      Identity and Access Management
1.1    Ensure account root access keys are removed (Scored)

Appendix: CIS Controls Mapped Recommendations
1.1    9.9 Require A Second Authentication Factor For Privileged Accounts

Appendix: Change History
Nothing to see here.
'''


def test_summary_table_boundary_stops_at_next_appendix_not_just_change_history():
    catalog = parse_benchmark(FIXTURE_EXTRA_APPENDIX_BEFORE_CHANGE_HISTORY, _AWS_CONFIG)
    assert [r.id for r in catalog.rules] == ["1.1"]


# Regression fixture for the Workspace finding: the Summary Table (and
# body rule-header lines) embed a profile-level tag directly before the
# title, e.g. real "1.1.1 (L1) Ensure that between two and four global
# admins are designated". This is cosmetic only — profile_level is
# already correctly populated from the unrelated Profile Applicability:
# body field below (unchanged logic) — the tag just needs stripping so
# the title reads cleanly.
FIXTURE_WITH_PROFILE_LEVEL_TAG = '''CIS Test Benchmark
v9.9.9 - 01-01-2099

Table of Contents

Recommendations
1 Identity and Access Management
1.1 (L1) Ensure account root access keys are removed (Scored)
Profile Applicability:

 Enterprise Level 1

Description:

Root access keys should not exist.

Rationale:

Root has unrestricted access.

Remediation:

Remove root access keys.

Appendix: Summary Table
1      Identity and Access Management
1.1    (L1) Ensure account root access keys are removed (Scored)

Appendix: Change History
Nothing to see here.
'''


def test_leading_profile_level_tag_is_stripped_from_title():
    catalog = parse_benchmark(FIXTURE_WITH_PROFILE_LEVEL_TAG, _AWS_CONFIG)
    rule = catalog.rules[0]
    assert rule.title == "Ensure account root access keys are removed"
    assert "(L1)" not in rule.title
    assert rule.classification == "Scored"
    assert rule.profile_level == "Level 1"
```

- [ ] **Step 2: Run the new tests to verify they fail**

Run: `pytest tests/test_importer_pdf_benchmark_parser.py -k "deep_nesting or grouping_headers_are_all_dropped or two_segment_version or stops_at_next_appendix or profile_level_tag" -v`

Expected: all 5 new tests FAIL — `test_rule_id_regex_matches_ids_deeper_than_three_segments` and `test_intermediate_multi_segment_grouping_headers_are_all_dropped` fail because the current `_RULE_ID_RE` never matches `1.1.1.1.1` (4 dot-segments beyond the first) at all, so the fixture's real rule is silently absent from `catalog.rules` (the two assertions on `catalog.rules[0]` or the exact-ids list fail); `test_version_regex_accepts_two_segment_version_string` fails because `_VERSION_RE` requires 3 segments and `benchmark_version` falls back to `"unknown"`; `test_summary_table_boundary_stops_at_next_appendix_not_just_change_history` fails because the old code searches specifically for `"Appendix: Change History"`, sweeping in the extra appendix's `"1.1    9.9 Require..."` row and corrupting the anchor list (duplicate `"1.1"` entries, order broken); `test_leading_profile_level_tag_is_stripped_from_title` fails because the title still contains the literal `"(L1) "` prefix.

- [ ] **Step 3: Implement the four generalizations**

In `cis_benchmark/importer/_pdf_benchmark_parser.py`, make these exact changes:

Change the two module-level regexes near the top of the file:

```python
_RULE_ID_RE = re.compile(r"^(\d+(?:\.\d+)+)\s")
_SECTION_ID_RE = re.compile(r"^(\d+)\s+(.+)$")
_VERSION_RE = re.compile(r"v(\d+(?:\.\d+)+)\s*-\s*[\d-]+")
```

(Only `_RULE_ID_RE` and `_VERSION_RE` change; `_SECTION_ID_RE` is shown unchanged for context — leave it exactly as-is.)

Add the L-tag regex directly below the existing `_VERSION_RE` line:

```python
_L_TAG_RE = re.compile(r"^\(L\d\)\s*")
```

Remove `appendix_end_marker` from `BenchmarkParserConfig`:

```python
@dataclass
class BenchmarkParserConfig:
    benchmark_name: str
    appendix_marker: str
    classification_words: List[str] = field(default_factory=lambda: ["Scored", "Not Scored"])
    known_versions: List[str] = field(default_factory=list)
```

In `_parse_summary_table`, change the end-boundary line from:

```python
    start = _find_last_index(text, config.appendix_marker)
    end = text.find(config.appendix_end_marker, start)
    if end == -1:
        end = len(text)
```

to:

```python
    start = _find_last_index(text, config.appendix_marker)
    end = text.find("Appendix:", start + len(config.appendix_marker))
    if end == -1:
        end = len(text)
```

In `_parse_summary_table`'s nested `flush()` function, add the L-tag strip as the first line of the `if pending_id is not None:` block, before the existing `joined = " ".join(...)` line's result is used for classification matching:

```python
    def flush():
        nonlocal pending_id, pending_lines
        if pending_id is not None:
            joined = " ".join(l.strip() for l in pending_lines if l.strip())
            joined = _L_TAG_RE.sub("", joined.strip())
            m = class_re.search(joined)
            classification = m.group(1) if m else None
            title = joined[:m.start()].strip() if m else joined.strip()
            anchors.append((pending_id, current_section, title, classification))
        pending_id = None
        pending_lines = []
```

(Only the new `joined = _L_TAG_RE.sub(...)` line is added; everything else in `flush()` is unchanged.)

- [ ] **Step 4: Run the new tests to verify they pass**

Run: `pytest tests/test_importer_pdf_benchmark_parser.py -k "deep_nesting or grouping_headers_are_all_dropped or two_segment_version or stops_at_next_appendix or profile_level_tag" -v`

Expected: all 5 PASS.

- [ ] **Step 5: Run the full existing suite to confirm the AWS/Azure/GCP regression check**

Run: `pytest tests/test_importer_pdf_benchmark_parser.py tests/test_importer_aws_parser.py tests/test_importer_azure_parser.py tests/test_importer_gcp_parser.py -v`

Expected: every test in all four files PASSES, including every test that existed before this task (the ones not touched in Step 1) — this is the concrete evidence that the four generalizations are safe supersets of AWS/Azure/GCP's current behavior, not just a reasoned assumption. If anything in this run fails, do not proceed — investigate and fix before continuing (a failure here means one of the four changes was not actually behavior-preserving for an existing cloud).

- [ ] **Step 6: Commit**

```bash
git add cis_benchmark/importer/_pdf_benchmark_parser.py tests/test_importer_pdf_benchmark_parser.py
git commit -m "Generalize shared engine for Workspace's deeper rule-ID nesting and extra appendices"
```

---

### Task 2: Strip Workspace's page-footer and watermark artifacts at the extraction layer

**Files:**
- Modify: `cis_benchmark/importer/pdf_extract.py`
- Test: `tests/test_importer_pdf_extract.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: `extract_text(pdf_path: str) -> str` — signature unchanged, only its internal stripping behavior gains two new cases. Task 3 and Task 4 don't call anything new from this file.

- [ ] **Step 1: Write the three failing tests**

Open `tests/test_importer_pdf_extract.py` and add these at the end of the file:

```python
def test_strips_bare_page_number_footer_lines():
    fake_result = MagicMock(
        returncode=0,
        stdout="Some content\n                    Page 1\nMore content\n              Page 42\nEnd\n",
        stderr="",
    )
    with patch("cis_benchmark.importer.pdf_extract.shutil.which", return_value="/usr/bin/pdftotext"), \
         patch("cis_benchmark.importer.pdf_extract.subprocess.run", return_value=fake_result):
        text = extract_text("doc.pdf")
    assert "Page 1" not in text
    assert "Page 42" not in text
    assert "Some content" in text
    assert "More content" in text
    assert "End" in text


def test_page_number_footer_regex_does_not_strip_lines_with_extra_content():
    fake_result = MagicMock(
        returncode=0,
        stdout="See Page 1 for details\n",
        stderr="",
    )
    with patch("cis_benchmark.importer.pdf_extract.shutil.which", return_value="/usr/bin/pdftotext"), \
         patch("cis_benchmark.importer.pdf_extract.subprocess.run", return_value=fake_result):
        text = extract_text("doc.pdf")
    assert "See Page 1 for details" in text


def test_strips_confidentiality_watermark_lines():
    fake_result = MagicMock(
        returncode=0,
        stdout="Audit:\n\nCheck the setting.\n\nInternal Only - General\n\nRemediation:\n\nFix it.\n",
        stderr="",
    )
    with patch("cis_benchmark.importer.pdf_extract.shutil.which", return_value="/usr/bin/pdftotext"), \
         patch("cis_benchmark.importer.pdf_extract.subprocess.run", return_value=fake_result):
        text = extract_text("doc.pdf")
    assert "Internal Only - General" not in text
    assert "Check the setting." in text
    assert "Remediation:" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_importer_pdf_extract.py -k "page_number_footer or confidentiality_watermark" -v`

Expected: `test_strips_bare_page_number_footer_lines` and `test_strips_confidentiality_watermark_lines` FAIL (the footer/watermark text is still present in the output); `test_page_number_footer_regex_does_not_strip_lines_with_extra_content` PASSES already (nothing strips it yet) — that's fine, it's written now so it stays a live regression guard once the new regex exists in Step 3.

- [ ] **Step 3: Implement the two new stripping regexes**

In `cis_benchmark/importer/pdf_extract.py`, add two new module-level regexes directly below the existing `_PAGE_FOOTER_RE` definition:

```python
# Page-footer lines like "35 | P a g e" or "4|Page" (pdftotext -layout
# sometimes letter-spaces the footer text; spacing varies by page).
_PAGE_FOOTER_RE = re.compile(r"^\s*\d+\s*\|\s*P\s*a\s*g\s*e\s*$", re.MULTILINE)
# A second page-footer format some benchmarks use instead: a bare
# "Page N" line with no pipe separator.
_PAGE_NUMBER_FOOTER_RE = re.compile(r"^\s*Page\s+\d+\s*$", re.MULTILINE)
# A repeating confidentiality watermark line some benchmarks print on
# every page, which otherwise leaks into extracted rule body text near
# page breaks.
_WATERMARK_RE = re.compile(r"^\s*Internal Only - General\s*$", re.MULTILINE)
```

Then update `extract_text()`'s stripping sequence from:

```python
    text = result.stdout.replace("\x0c", "")
    text = _PAGE_FOOTER_RE.sub("", text)
    text = _PUA_GLYPH_RE.sub("", text)
    return text
```

to:

```python
    text = result.stdout.replace("\x0c", "")
    text = _PAGE_FOOTER_RE.sub("", text)
    text = _PAGE_NUMBER_FOOTER_RE.sub("", text)
    text = _WATERMARK_RE.sub("", text)
    text = _PUA_GLYPH_RE.sub("", text)
    return text
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_importer_pdf_extract.py -v`

Expected: all tests in the file PASS, including the 3 new ones and every pre-existing test (`test_strips_page_footer_lines`, `test_strips_private_use_area_glyphs`, etc.) unchanged.

- [ ] **Step 5: Commit**

```bash
git add cis_benchmark/importer/pdf_extract.py tests/test_importer_pdf_extract.py
git commit -m "Strip Workspace's page-number footer and confidentiality watermark lines"
```

---

### Task 3: Workspace parser module

**Files:**
- Create: `cis_benchmark/importer/workspace_parser.py`
- Test: `tests/test_importer_workspace_parser.py`

**Interfaces:**
- Consumes: `BenchmarkParserConfig`, `parse_benchmark` from `cis_benchmark/importer/_pdf_benchmark_parser.py` (Task 1's generalized versions); `BenchmarkCatalog` from `cis_benchmark/importer/schema.py`.
- Produces: `parse(text: str, source_filename: str = "") -> BenchmarkCatalog` — the exact same signature `aws_parser.parse`/`azure_parser.parse`/`gcp_parser.parse` already expose. Task 4 imports this as `from .importer.workspace_parser import parse as parse_workspace`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_importer_workspace_parser.py`:

```python
from cis_benchmark.importer.workspace_parser import parse

# Synthetic fixture exercising every Workspace-specific wrinkle verified
# during design: a single-line (unwrapped) appendix marker, a 3-segment
# rule ID under a 2-segment grouping header, an embedded (L1) profile-level
# tag stripped from the title, a 2-segment version string, and an extra
# appendix (CIS Controls mapping) between the Summary Table and Change
# History that must not corrupt the parsed rule list. No real CIS content.
FIXTURE = '''CIS Google Workspace
Foundations Benchmark
v1.4 - 01-01-2099

Table of Contents

Recommendations
1 Directory
1.1 Users
1.1.1 (L1) Ensure that between two and four global admins are designated (Manual)
Profile Applicability:

 Enterprise Level 1

Description:

Example description text.

Rationale:

Example rationale text.

Remediation:

Example remediation text.

Appendix: Summary Table
1        Directory
1.1      Users
1.1.1    (L1) Ensure that between two and four global admins are designated (Manual)

Appendix: CIS Controls v7 IG 1 Mapped Recommendations
1.1.1    9.9 Require A Second Authentication Factor For Privileged Accounts

Appendix: Change History
Nothing to see here.
'''


def test_workspace_parser_uses_correct_benchmark_name():
    catalog = parse(FIXTURE, source_filename="fixture.pdf")
    assert catalog.benchmark_name == "CIS Google Workspace Foundations Benchmark"


def test_workspace_parser_uses_manual_automated_vocabulary():
    catalog = parse(FIXTURE)
    assert catalog.rules[0].classification == "Manual"


def test_workspace_parser_strips_profile_level_tag_from_title():
    catalog = parse(FIXTURE)
    assert catalog.rules[0].title == "Ensure that between two and four global admins are designated"
    assert catalog.rules[0].profile_level == "Level 1"


def test_workspace_parser_drops_grouping_header_and_ignores_extra_appendix():
    catalog = parse(FIXTURE)
    ids = [r.id for r in catalog.rules]
    assert ids == ["1.1.1"]
    assert "1.1" not in ids


def test_workspace_parser_known_two_segment_version_is_verified():
    catalog = parse(FIXTURE)
    assert catalog.benchmark_version == "1.4"
    assert catalog.version_verified is True


def test_workspace_parser_unknown_version_is_not_verified():
    unknown_version_text = FIXTURE.replace("v1.4 - 01-01-2099", "v9.9 - 01-01-2099")
    catalog = parse(unknown_version_text)
    assert catalog.version_verified is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_importer_workspace_parser.py -v`

Expected: FAIL with `ModuleNotFoundError: No module named 'cis_benchmark.importer.workspace_parser'` (the module doesn't exist yet).

- [ ] **Step 3: Create the Workspace parser module**

Create `cis_benchmark/importer/workspace_parser.py`:

```python
from ._pdf_benchmark_parser import BenchmarkParserConfig, parse_benchmark
from .schema import BenchmarkCatalog

_CONFIG = BenchmarkParserConfig(
    benchmark_name="CIS Google Workspace Foundations Benchmark",
    appendix_marker="Appendix: Summary Table",
    classification_words=["Manual", "Automated"],
    known_versions=["1.4"],
)


def parse(text: str, source_filename: str = "") -> BenchmarkCatalog:
    return parse_benchmark(text, _CONFIG, source_filename)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_importer_workspace_parser.py -v`

Expected: all 6 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add cis_benchmark/importer/workspace_parser.py tests/test_importer_workspace_parser.py
git commit -m "Add Workspace benchmark parser"
```

---

### Task 4: CLI wiring, fix the two tests that used workspace as the unimplemented-cloud example, manual acceptance check

**Files:**
- Modify: `cis_benchmark/cli.py`
- Modify: `tests/test_cli_subcommands.py`

**Interfaces:**
- Consumes: `parse` from `cis_benchmark/importer/workspace_parser.py` (Task 3), imported as `parse_workspace` matching the existing `parse_aws`/`parse_azure`/`parse_gcp` naming convention already in `cli.py`.
- Produces: `_IMPORT_PARSERS` dict now maps all four cloud names; no other public interface changes.

- [ ] **Step 1: Write the failing test for CLI wiring**

Open `tests/test_cli_subcommands.py` and add this test after `test_run_import_writes_catalog_and_prints_summary` (before the existing `test_run_import_rejects_unimplemented_cloud`):

```python
def test_run_import_accepts_workspace_cloud():
    assert "workspace" in cli._IMPORT_PARSERS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli_subcommands.py::test_run_import_accepts_workspace_cloud -v`

Expected: FAIL — `"workspace" not in cli._IMPORT_PARSERS` (only `aws`, `azure`, `gcp` are registered today).

- [ ] **Step 3: Wire the Workspace parser into the CLI**

In `cis_benchmark/cli.py`, change the import block from:

```python
from .importer.aws_parser import parse as parse_aws
from .importer.azure_parser import parse as parse_azure
from .importer.gcp_parser import parse as parse_gcp
from .importer.errors import ImporterError
from .importer.pdf_extract import extract_text
```

to:

```python
from .importer.aws_parser import parse as parse_aws
from .importer.azure_parser import parse as parse_azure
from .importer.gcp_parser import parse as parse_gcp
from .importer.workspace_parser import parse as parse_workspace
from .importer.errors import ImporterError
from .importer.pdf_extract import extract_text
```

And change:

```python
_IMPORT_PARSERS = {"aws": parse_aws, "azure": parse_azure, "gcp": parse_gcp}
```

to:

```python
_IMPORT_PARSERS = {"aws": parse_aws, "azure": parse_azure, "gcp": parse_gcp, "workspace": parse_workspace}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli_subcommands.py::test_run_import_accepts_workspace_cloud -v`

Expected: PASS.

- [ ] **Step 5: Fix the two tests that relied on `workspace` being unimplemented**

`workspace` is now implemented, so `test_run_import_rejects_unimplemented_cloud` and `test_main_prints_clean_error_and_exits_1_on_importer_error` (both currently use `cloud="workspace"` as their "not implemented" example) would otherwise start exercising the real Workspace parser against fake/empty text instead of the error path they're meant to test. Run: `pytest tests/test_cli_subcommands.py::test_run_import_rejects_unimplemented_cloud tests/test_cli_subcommands.py::test_main_prints_clean_error_and_exits_1_on_importer_error -v` now to confirm they currently FAIL (this proves the wiring in Step 3 actually changed their behavior, not just that the new test passes).

Change `test_run_import_rejects_unimplemented_cloud` from:

```python
def test_run_import_rejects_unimplemented_cloud():
    args = argparse.Namespace(cloud="workspace", pdf_path="fake.pdf", output=None)
    with pytest.raises(ImporterError, match="not implemented yet"):
        cli._run_import(args)
```

to:

```python
def test_run_import_rejects_unimplemented_cloud():
    args = argparse.Namespace(cloud="digitalocean", pdf_path="fake.pdf", output=None)
    with pytest.raises(ImporterError, match="not implemented yet"):
        cli._run_import(args)
```

(This test constructs an `argparse.Namespace` directly, bypassing the real argparse `choices` validation entirely, so a synthetic cloud name not in `_IMPORT_PARSERS` works fine here and doesn't need monkeypatching.)

Change `test_main_prints_clean_error_and_exits_1_on_importer_error` from:

```python
def test_main_prints_clean_error_and_exits_1_on_importer_error(monkeypatch, capsys):
    monkeypatch.setattr(cli.sys, "argv", ["cis", "import", "fake.pdf", "--cloud", "workspace"])
    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "not implemented yet" in captured.err
```

to:

```python
def test_main_prints_clean_error_and_exits_1_on_importer_error(monkeypatch, capsys):
    # "workspace" must stay a real --cloud choice so this test still goes
    # through real argparse validation; the unimplemented-cloud path is
    # simulated instead by removing it from _IMPORT_PARSERS for this test.
    monkeypatch.setattr(cli, "_IMPORT_PARSERS", {"aws": cli._IMPORT_PARSERS["aws"]})
    monkeypatch.setattr(cli.sys, "argv", ["cis", "import", "fake.pdf", "--cloud", "workspace"])
    with pytest.raises(SystemExit) as exc_info:
        cli.main()
    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "not implemented yet" in captured.err
```

- [ ] **Step 6: Run the full CLI test file to verify everything passes**

Run: `pytest tests/test_cli_subcommands.py -v`

Expected: every test in the file PASSES.

- [ ] **Step 7: Run the entire test suite**

Run: `pytest -v`

Expected: all tests across the whole project PASS — this is the final confirmation that Tasks 1-4 together haven't broken anything anywhere else in the codebase.

- [ ] **Step 8: Commit**

```bash
git add cis_benchmark/cli.py tests/test_cli_subcommands.py
git commit -m "Wire the Workspace parser into cis import --cloud workspace"
```

- [ ] **Step 9: Manual acceptance check against the real Workspace PDF**

This step is not automated and produces no commit — it's the same real-data check that caught real bugs during the AWS and Azure/GCP builds, run here against the actual installed CLI end-to-end (not just the raw parsing algorithm in isolation).

Run:

```bash
cd /Users/administrator/Desktop/CIS_Benchmark
cis import "CIS_Google_Workspace_Foundations_Benchmark_v1.4.pdf" --cloud workspace --output /tmp/workspace_import_check.json
```

Expected console output: `Parsed 86 rule(s) (0 incomplete) -> /tmp/workspace_import_check.json`.

If the count or incomplete number differs from `86` and `0`, do not consider this task done — the synthetic-fixture tests passing is not sufficient evidence on its own (this exact gap — synthetic tests green, real document behaving differently — is what caught two real bugs during the AWS build and one during Azure/GCP). Investigate the discrepancy: re-run the diagnostic approach from this plan's design spec (compare `grep -c "^Profile Applicability:"` et al. against the real extracted text to the actual `total_rules`/`incomplete_rules` in the output JSON) before considering Task 4 complete.

Additionally spot-check the output JSON directly:

```bash
python3 -c "
import json
data = json.load(open('/tmp/workspace_import_check.json'))
print('version:', data['benchmark_version'], 'verified:', data['version_verified'])
print('total_rules:', data['total_rules'], 'incomplete_rules:', data['incomplete_rules'])
r = next(r for r in data['rules'] if r['id'] == '1.1.1')
print('1.1.1 title:', r['title'])
print('1.1.1 profile_level:', r['profile_level'])
print('1.1.1 classification:', r['classification'])
"
```

Expected: `version: 1.4 verified: True`, `total_rules: 86 incomplete_rules: 0`, `1.1.1 title:` a clean title with no `(L1)` prefix and no trailing PDF artifacts, `1.1.1 profile_level: Level 1`, `1.1.1 classification: Manual`.

Delete the scratch output file afterward (it's outside the gitignored `imports/` directory and contains real CIS content, so it must not be left lying around or committed):

```bash
rm /tmp/workspace_import_check.json
```

---

### Task 5: README documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing — documentation only.
- Produces: nothing consumed by later tasks (this is the final task).

- [ ] **Step 1: Update the feature bullet list**

In `README.md`, change (around line 14):

```markdown
- 📥 **Benchmark PDF Import**: `cis import <pdf> --cloud <aws|azure|gcp>` parses an official CIS Benchmark PDF into a structured JSON rule catalog.
```

to:

```markdown
- 📥 **Benchmark PDF Import**: `cis import <pdf> --cloud <aws|azure|gcp|workspace>` parses an official CIS Benchmark PDF into a structured JSON rule catalog.
```

- [ ] **Step 2: Update the Scope & Coverage comparison table and its trailing paragraph**

Change (around line 28):

```markdown
| 🔴 Google Workspace | 5 (4 are honest `MANUAL_CHECK` placeholders — see below; only SPF/DMARC is automated) | CIS Google Workspace Benchmark has 60+ recommendations |
```

to:

```markdown
| 🔴 Google Workspace | 5 (4 are honest `MANUAL_CHECK` placeholders — see below; only SPF/DMARC is automated) | CIS Google Workspace Foundations Benchmark **v1.4** has 86 recommendations (verified via `cis import`) |
```

Change (around line 35):

```markdown
As of this version, `cis import` can parse official CIS Benchmark PDFs (AWS, Azure, GCP) into a complete, structured JSON catalog of all their recommendations (see "Importing an official benchmark PDF" below) — but this produces a *reference catalog* for coverage tracking, not new automated checks. A PDF describes what to check in prose; it can't generate the CLI-calling verification logic a real check needs. Google Workspace PDF import is not yet implemented.
```

to:

```markdown
As of this version, `cis import` can parse official CIS Benchmark PDFs (AWS, Azure, GCP, Google Workspace) into a complete, structured JSON catalog of all their recommendations (see "Importing an official benchmark PDF" below) — but this produces a *reference catalog* for coverage tracking, not new automated checks. A PDF describes what to check in prose; it can't generate the CLI-calling verification logic a real check needs.
```

- [ ] **Step 3: Update the "Importing an official benchmark PDF" section**

Change (around line 126-129):

```markdown
**Getting a PDF:** Download the official benchmark from
[cisecurity.org/cis-benchmarks](https://www.cisecurity.org/cis-benchmarks)
(free CIS account required). AWS, Azure, and GCP are supported today;
Google Workspace is not yet implemented.
```

to:

```markdown
**Getting a PDF:** Download the official benchmark from
[cisecurity.org/cis-benchmarks](https://www.cisecurity.org/cis-benchmarks)
(free CIS account required). AWS, Azure, GCP, and Google Workspace are
supported today.
```

Change (around line 131-135):

```markdown
```bash
cis import /path/to/CIS_AWS_Foundations_Benchmark.pdf --cloud aws
cis import /path/to/CIS_Microsoft_Azure_Foundations_Benchmark.pdf --cloud azure
cis import /path/to/GCP_CIS_Foundation_Benchmark.pdf --cloud gcp
```
```

to:

```markdown
```bash
cis import /path/to/CIS_AWS_Foundations_Benchmark.pdf --cloud aws
cis import /path/to/CIS_Microsoft_Azure_Foundations_Benchmark.pdf --cloud azure
cis import /path/to/GCP_CIS_Foundation_Benchmark.pdf --cloud gcp
cis import /path/to/CIS_Google_Workspace_Foundations_Benchmark.pdf --cloud workspace
```
```

- [ ] **Step 4: Update the verified-versions table**

Change (around line 160-164):

```markdown
| Cloud | Verified version(s) |
| :--- | :--- |
| AWS | 1.2.0 |
| Azure | 1.4.0 |
| GCP | 1.2.0 |
```

to:

```markdown
| Cloud | Verified version(s) |
| :--- | :--- |
| AWS | 1.2.0 |
| Azure | 1.4.0 |
| GCP | 1.2.0 |
| Workspace | 1.4 |
```

- [ ] **Step 5: Proofread the whole "Importing an official benchmark PDF" section**

Read the full section top to bottom (`grep -n "Importing an official benchmark PDF" README.md` to find the start) to confirm no other sentence still says Workspace is unsupported or lists only 3 clouds — fix any you find.

- [ ] **Step 6: Commit**

```bash
git add README.md
git commit -m "Document --cloud workspace support in the README"
```
