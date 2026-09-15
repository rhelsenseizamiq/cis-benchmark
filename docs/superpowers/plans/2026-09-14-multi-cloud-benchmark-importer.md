# Multi-Cloud Benchmark Importer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend `cis import` from AWS-only to also support `--cloud azure` and `--cloud gcp`, by extracting the existing AWS parsing algorithm into a shared, config-parameterized engine, and changing `ImportedRule.scored: bool` to `ImportedRule.classification: str` to honestly represent that AWS's Scored/Not-Scored and Azure/GCP's Manual/Automated are different concepts, not the same boolean.

**Architecture:** A new `cis_benchmark/importer/_pdf_benchmark_parser.py` holds the two-pass parsing algorithm (Appendix-table anchoring, body-carving, section-splitting), parameterized by a `BenchmarkParserConfig` dataclass (benchmark name, appendix marker text, classification vocabulary, known-verified versions). `aws_parser.py` is refactored onto it; `azure_parser.py` and `gcp_parser.py` are new, each a ~15-line config + wrapper. A newly-verified rule in the shared engine (found by testing against real Azure/GCP data, absent from the original AWS-only algorithm) distinguishes a genuine rule whose classification marker is corrupted (AWS's existing edge case — keep it, flag incomplete) from a structural grouping/subsection heading with no marker and no body content at all (Azure/GCP's `4.1 SQL Server - Auditing`-style headers — drop it, it isn't a rule).

**Tech Stack:** Python 3.10+, stdlib `re`/`dataclasses`, pytest. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-09-14-multi-cloud-benchmark-importer-design.md`

## Global Constraints

- `cis scan` and every existing non-importer test must remain unaffected — nothing in this plan touches `core/`, `modules/`, `reporters/`.
- No real CIS Benchmark PDF content or extracted text may be committed to the repo. Tests use synthetic, clearly-fictional fixtures only — the AWS build's fixture-licensing mistake (real CIS Controls wording accidentally reused) must not repeat here.
- Follow the project's existing conventions: relative imports within `cis_benchmark/`, flat test files directly under `tests/` (no subdirectories), commit messages as plain descriptive imperative titles — no `feat:`/`fix:` prefix, and no `Co-Authored-By`/`Claude-Session` trailer (this repo-specific convention, confirmed via `git log --oneline` before every commit in this plan).
- Every expected failure mode raises `ImporterError`, caught at the CLI boundary — never a raw traceback.
- The `_pdf_benchmark_parser` module's grouping-header-vs-corrupted-marker distinction (`classification is None and not fields` → drop; `classification is None and fields` → keep, flag incomplete) was independently verified against all three real PDFs (AWS 49/49 rules 0 dropped, Azure 115/115 6 dropped, GCP 83/83 3 dropped) before this plan was written — implement it exactly as given in Task 2, do not redesign it.
- `ImportedRule.classification` and `BenchmarkCatalog.version_verified` are the only schema changes. `known_versions` comparison is exact string match (e.g. `"1.2.0"`), never a prefix or semver-range match.

---

### Task 1: Schema change — `scored: bool` → `classification: str`, add `version_verified`

**Files:**
- Modify: `cis_benchmark/importer/schema.py`
- Test: `tests/test_importer_schema.py`

**Interfaces:**
- Produces: `ImportedRule` with `classification: str` (was `scored: bool`) at the same field position; `BenchmarkCatalog` with new `version_verified: bool = True` field, positioned after `extracted_at` and before `rules` (must come before `rules`, which has a default, per dataclass field-ordering rules).

- [ ] **Step 1: Write the failing test**

Replace the full contents of `tests/test_importer_schema.py`:

```python
import json

from cis_benchmark.importer.schema import ImportedRule, BenchmarkCatalog, now_iso


def test_imported_rule_defaults():
    rule = ImportedRule(id="1.1", title="Example", classification="Scored", profile_level="Level 1", section="1. Example")
    assert rule.description == ""
    assert rule.references == []
    assert rule.incomplete is False
    assert rule.missing_sections == []


def test_catalog_to_dict_includes_counts():
    rules = [
        ImportedRule(id="1.1", title="A", classification="Scored", profile_level="Level 1", section="1. X"),
        ImportedRule(id="1.2", title="B", classification="Not Scored", profile_level="Level 2", section="1. X", incomplete=True, missing_sections=["Remediation:"]),
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
    assert d["rules"][0]["classification"] == "Scored"


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
        rules=[ImportedRule(id="1.1", title="A", classification="Scored", profile_level="Level 1", section="1. X")],
    )
    out_path = tmp_path / "nested" / "dir" / "catalog.json"
    result_path = catalog.write(str(out_path))

    assert result_path == str(out_path)
    assert out_path.exists()
    with open(out_path) as f:
        data = json.load(f)
    assert data["total_rules"] == 1


def test_catalog_version_verified_defaults_true_and_is_serialized():
    catalog = BenchmarkCatalog(
        benchmark_name="CIS Test Benchmark", benchmark_version="9.9.9",
        source_filename="test.pdf", extracted_at=now_iso(), rules=[],
    )
    assert catalog.version_verified is True
    assert catalog.to_dict()["version_verified"] is True


def test_catalog_version_verified_false_is_serialized():
    catalog = BenchmarkCatalog(
        benchmark_name="CIS Test Benchmark", benchmark_version="0.0.1",
        source_filename="test.pdf", extracted_at=now_iso(), rules=[],
        version_verified=False,
    )
    assert catalog.to_dict()["version_verified"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_importer_schema.py -v`
Expected: FAIL — `ImportedRule.__init__() got an unexpected keyword argument 'classification'` (the dataclass still has `scored`, not `classification`), and `version_verified` tests fail with `TypeError: __init__() got an unexpected keyword argument 'version_verified'`.

- [ ] **Step 3: Write minimal implementation**

In `cis_benchmark/importer/schema.py`, change the `ImportedRule` dataclass's third field from:
```python
    scored: bool
```
to:
```python
    classification: str
```
(Every other field in `ImportedRule` stays exactly as-is, same order.)

Change the `BenchmarkCatalog` dataclass to add `version_verified` before `rules`:
```python
@dataclass
class BenchmarkCatalog:
    benchmark_name: str
    benchmark_version: str
    source_filename: str
    extracted_at: str
    version_verified: bool = True
    rules: List[ImportedRule] = field(default_factory=list)
```

`to_dict()` on both classes needs no changes — `ImportedRule.to_dict()` uses `asdict(self)` (automatically picks up the renamed field), and `BenchmarkCatalog.to_dict()`'s explicit dict needs `version_verified` added:
```python
    def to_dict(self) -> Dict[str, Any]:
        return {
            "benchmark_name": self.benchmark_name,
            "benchmark_version": self.benchmark_version,
            "source_filename": self.source_filename,
            "extracted_at": self.extracted_at,
            "version_verified": self.version_verified,
            "total_rules": len(self.rules),
            "incomplete_rules": sum(1 for r in self.rules if r.incomplete),
            "rules": [r.to_dict() for r in self.rules],
        }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_importer_schema.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add cis_benchmark/importer/schema.py tests/test_importer_schema.py
git commit -m "Replace ImportedRule.scored:bool with classification:str, add BenchmarkCatalog.version_verified"
```

---

### Task 2: Extract shared parsing engine, refactor AWS onto it

This is the highest-risk task: it moves already-shipped, already-tested logic. The exact algorithm below (including the grouping-header-vs-corrupted-marker distinction) was independently verified against all three real PDFs before this plan was written — implement it verbatim, don't redesign it.

**Files:**
- Create: `cis_benchmark/importer/_pdf_benchmark_parser.py`
- Modify: `cis_benchmark/importer/aws_parser.py` (full rewrite, ~220 lines → ~15 lines)
- Create: `tests/test_importer_pdf_benchmark_parser.py`
- Modify: `tests/test_importer_aws_parser.py` (trimmed to AWS-config-specific tests only; the shared-behavior tests move to the new file above)

**Interfaces:**
- Consumes: `ImportedRule`, `BenchmarkCatalog`, `now_iso` (Task 1, `cis_benchmark.importer.schema`); `ImporterError` (`cis_benchmark.importer.errors`).
- Produces: `BenchmarkParserConfig` dataclass (fields: `benchmark_name: str`, `appendix_marker: str`, `appendix_end_marker: str = "Appendix: Change History"`, `classification_words: List[str] = field(default_factory=lambda: ["Scored", "Not Scored"])`, `known_versions: List[str] = field(default_factory=list)`); `parse_benchmark(text: str, config: BenchmarkParserConfig, source_filename: str = "") -> BenchmarkCatalog`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_importer_pdf_benchmark_parser.py`:

```python
import pytest

from cis_benchmark.importer.errors import ImporterError
from cis_benchmark.importer._pdf_benchmark_parser import BenchmarkParserConfig, parse_benchmark

_AWS_CONFIG = BenchmarkParserConfig(
    benchmark_name="CIS Test Benchmark",
    appendix_marker="Appendix: Summary Table",
    classification_words=["Scored", "Not Scored"],
    known_versions=["9.9.9"],
)

# A synthetic "mini benchmark" exercising every structural wrinkle found
# across the three real CIS PDFs inspected during design: a title that
# wraps across two lines before its classification marker, a CIS Controls
# cross-reference number that must NOT be mistaken for a new rule, and one
# deliberately-incomplete rule (missing Remediation:). No real CIS content.
FIXTURE_HAPPY_PATH = '''CIS Test Benchmark
v9.9.9 - 01-01-2099
Terms of Use
Please see the below link for our current terms of use:
https://example.invalid/terms

Table of Contents

Recommendations
1 Identity and Access Management
1.1 Avoid using the primary administrative account for routine operations (Scored)
Profile Applicability:

 Level 1

Description:

Do not use the root account for daily tasks.

Rationale:

The root account has unrestricted access to everything.

Audit:

Run the following command:

  example iam get-account-summary

Remediation:

Stop using the root account for daily tasks.

References:

   1. CCE-00000-0

CIS Controls:

9.9 Require A Second Authentication Factor For Privileged Accounts
Use multi-factor authentication for all administrative account access.

1.2 Ensure a secondary verification factor is required for every user account that can
sign in through the web console (Scored)
Profile Applicability:

 Level 1

Description:

MFA adds an extra layer of protection on top of a password.

Rationale:

Enabling MFA provides increased security for console access.

Audit:

Run the following command:

  example iam list-mfa-devices

Remediation:

Enable MFA for all IAM users with a console password.

References:

   1. CCE-00000-1

CIS Controls:

9.9 Require A Second Authentication Factor For Privileged Accounts
Use multi-factor authentication for all administrative account access.

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

  example iam get-account-summary

References:

   1. CCE-00000-2

Appendix: Summary Table
                         Control                                             Set
                                                                          Correctly
                                                                          Yes No
1      Identity and Access Management
1.1    Avoid using the primary administrative account for routine operations (Scored)
1.2    Ensure a secondary verification factor is required for every user
       account that can sign in through the web console (Scored)
1.3    Ensure this rule is intentionally left incomplete (Not Scored)

Appendix: Change History
Nothing to see here.
'''


def test_parses_all_rules_with_correct_ids_and_order():
    catalog = parse_benchmark(FIXTURE_HAPPY_PATH, _AWS_CONFIG, source_filename="fixture.pdf")
    assert [r.id for r in catalog.rules] == ["1.1", "1.2", "1.3"]


def test_extracts_benchmark_version_and_uses_config_name():
    catalog = parse_benchmark(FIXTURE_HAPPY_PATH, _AWS_CONFIG)
    assert catalog.benchmark_version == "9.9.9"
    assert catalog.benchmark_name == "CIS Test Benchmark"


def test_version_verified_true_when_version_in_known_versions():
    catalog = parse_benchmark(FIXTURE_HAPPY_PATH, _AWS_CONFIG)
    assert catalog.version_verified is True


def test_version_verified_false_when_version_not_in_known_versions():
    config = BenchmarkParserConfig(
        benchmark_name="CIS Test Benchmark",
        appendix_marker="Appendix: Summary Table",
        classification_words=["Scored", "Not Scored"],
        known_versions=["1.0.0"],  # deliberately does not match "9.9.9"
    )
    catalog = parse_benchmark(FIXTURE_HAPPY_PATH, config)
    assert catalog.version_verified is False


def test_wrapped_title_is_joined_correctly():
    catalog = parse_benchmark(FIXTURE_HAPPY_PATH, _AWS_CONFIG)
    rule_1_2 = next(r for r in catalog.rules if r.id == "1.2")
    assert rule_1_2.title == (
        "Ensure a secondary verification factor is required for every "
        "user account that can sign in through the web console"
    )
    assert rule_1_2.classification == "Scored"


def test_cis_controls_cross_reference_is_not_mistaken_for_a_new_rule():
    catalog = parse_benchmark(FIXTURE_HAPPY_PATH, _AWS_CONFIG)
    assert len(catalog.rules) == 3
    assert "9.9" not in [r.id for r in catalog.rules]
    rule_1_1 = next(r for r in catalog.rules if r.id == "1.1")
    assert "9.9 Require A Second Authentication Factor" in rule_1_1.cis_controls


def test_fields_extracted_correctly_for_a_complete_rule():
    catalog = parse_benchmark(FIXTURE_HAPPY_PATH, _AWS_CONFIG)
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
    catalog = parse_benchmark(FIXTURE_HAPPY_PATH, _AWS_CONFIG)
    rule = next(r for r in catalog.rules if r.id == "1.3")
    assert rule.incomplete is True
    assert "Remediation:" in rule.missing_sections
    assert rule.description
    assert rule.profile_level == "Level 2"
    assert rule.classification == "Not Scored"


FIXTURE_MISSING_RULE = '''CIS Test Benchmark
v9.9.9 - 01-01-2099

Table of Contents

Recommendations
1 Identity and Access Management
1.1 Avoid using the primary administrative account for routine operations (Scored)
Profile Applicability:

 Level 1

Description:

Do not use the root account for daily tasks.

Rationale:

The root account has unrestricted access to everything.

Audit:

Run the following command:

  example iam get-account-summary

Remediation:

Stop using the root account for daily tasks.

References:

   1. CCE-00000-0

Appendix: Summary Table
1      Identity and Access Management
1.1    Avoid using the primary administrative account for routine operations (Scored)
1.2    This rule is listed in the summary table but never appears in the body (Scored)

Appendix: Change History
Nothing to see here.
'''


def test_missing_rule_in_body_raises_importer_error():
    with pytest.raises(ImporterError, match="1.2"):
        parse_benchmark(FIXTURE_MISSING_RULE, _AWS_CONFIG)


def test_empty_summary_table_raises_importer_error():
    with pytest.raises(ImporterError):
        parse_benchmark("Recommendations\n\nAppendix: Summary Table\n\nAppendix: Change History\n", _AWS_CONFIG)


FIXTURE_WITH_TOC_COLLISION = (
    "CIS Test Benchmark\nv9.9.9 - 01-01-2099\n\n"
    "Table of Contents\n\n"
    "Recommendations .......................................................... 9\n"
    "Appendix: Summary Table .......................................................... 152\n"
    "Appendix: Change History .......................................................... 155\n\n"
) + FIXTURE_HAPPY_PATH


def test_toc_dot_leader_mention_of_appendix_marker_is_not_mistaken_for_the_real_section():
    """When the appendix marker appears both in the TOC (early, dot-leader
    entry) and as the real section (late), the parser must use the LAST
    occurrence. If it used .find() instead of .rfind(), it would match the
    TOC entry and extract a slice with zero rows.
    """
    catalog = parse_benchmark(FIXTURE_WITH_TOC_COLLISION, _AWS_CONFIG)
    assert [r.id for r in catalog.rules] == ["1.1", "1.2", "1.3"]


def test_trailing_glyph_after_classification_marker_does_not_break_detection():
    glyph = chr(0xF06F)
    text = f'''CIS Test Benchmark
v9.9.9 - 01-01-2099

Table of Contents

Recommendations
1 Identity and Access Management
1.1 Ensure a control has trailing PDF artifacts after its marker (Scored)
Profile Applicability:

 Level 1

Description:

Testing trailing artifact handling.

Rationale:

Testing matters.

Audit:

Run the following command:

  example iam get-account-summary

Remediation:

Fix it.

Appendix: Summary Table
1      Identity and Access Management
1.1    Ensure a control has trailing PDF artifacts after its marker (Scored){glyph}

Appendix: Change History
Nothing to see here.
'''
    catalog = parse_benchmark(text, _AWS_CONFIG)
    rule = catalog.rules[0]
    assert rule.title == "Ensure a control has trailing PDF artifacts after its marker"
    assert rule.classification == "Scored"
    assert "(Scored)" not in rule.title


FIXTURE_MULTI_SECTION = '''CIS Test Benchmark
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

1.2 Ensure access policies are attached only to teams or roles (Scored)
Description:

Policies should not be attached directly to users.

Rationale:

Grouping eases permission management.

Remediation:

Detach direct user policies.

2 Logging and Monitoring
2.1 Ensure activity logging is enabled in all regions (Scored)
Description:

Activity logging should be enabled across all regions.

Rationale:

Centralized logging aids incident response.

Remediation:

Enable activity logging in all regions.

3 Networking
3.1 Ensure no network security rule permits unrestricted inbound access to port 22 (Scored)
Description:

Security groups should restrict SSH ingress.

Rationale:

Open SSH exposes hosts to brute force attacks.

Remediation:

Restrict port 22 ingress to known ranges.

3.2 Ensure network flow logging is enabled in all virtual networks (Scored)
Description:

Flow logs capture network traffic metadata.

Rationale:

Flow logs aid network forensics.

Remediation:

Enable flow logging for every VPC.

Appendix: Summary Table
                         Control                                             Set
                                                                          Correctly
                                                                          Yes No
1      Identity and Access Management
1.1    Ensure account root access keys are removed (Scored)
1.2    Ensure access policies are attached only to teams or roles (Scored)
2      Logging and Monitoring
2.1    Ensure activity logging is enabled in all regions (Scored)
3      Networking
3.1    Ensure no network security rule permits unrestricted inbound access to port 22 (Scored)
3.2    Ensure network flow logging is enabled in all virtual networks (Scored)

Appendix: Change History
Nothing to see here.
'''


def test_section_updates_correctly_between_rule_blocks_in_summary_table():
    catalog = parse_benchmark(FIXTURE_MULTI_SECTION, _AWS_CONFIG, source_filename="fixture.pdf")
    sections_by_id = {r.id: r.section for r in catalog.rules}
    assert sections_by_id["1.1"] == "1. Identity and Access Management"
    assert sections_by_id["1.2"] == "1. Identity and Access Management"
    assert sections_by_id["2.1"] == "2. Logging and Monitoring"
    assert sections_by_id["3.1"] == "3. Networking"
    assert sections_by_id["3.2"] == "3. Networking"
    assert len(set(sections_by_id.values())) == 3


def test_corrupted_marker_on_a_real_rule_is_kept_and_flagged_incomplete():
    """A rule with real body content (Description/Rationale/Remediation all
    present) but an unparseable classification marker must still be
    emitted, flagged incomplete — NOT silently dropped. This is distinct
    from a structural grouping header (next test), which has no body
    content at all.
    """
    text = '''CIS Test Benchmark
v9.9.9 - 01-01-2099

Table of Contents

Recommendations
1 Identity and Access Management
1.1 Ensure a control has a marker with an injected character
Profile Applicability:

 Level 1

Description:

Testing unparseable marker handling.

Rationale:

Testing matters.

Audit:

Run the following command:

  example iam get-account-summary

Remediation:

Fix it.

Appendix: Summary Table
1      Identity and Access Management
1.1    Ensure a control has a marker with an injected character (Not\N{REGISTERED SIGN}Scored)

Appendix: Change History
Nothing to see here.
'''
    catalog = parse_benchmark(text, _AWS_CONFIG)
    assert len(catalog.rules) == 1
    rule = catalog.rules[0]
    assert rule.incomplete is True
    assert any("classification" in m for m in rule.missing_sections)


# Regression fixture for the Azure/GCP grouping-header finding: a Summary
# Table row with a 2-level id, no classification marker anywhere, and NO
# body content at all (just a bare heading line, like Azure's real
# "4.1 SQL Server - Auditing" grouping several 3-level leaf rules) must be
# excluded from the catalog entirely — it isn't a rule. Uses a different
# classification vocabulary (Manual/Automated) than the AWS-flavored
# fixtures above, both to prove config parameterization actually works and
# because this pattern was found in benchmarks that use that vocabulary.
_GENERIC_CONFIG = BenchmarkParserConfig(
    benchmark_name="CIS Test Benchmark 2",
    appendix_marker="Appendix: Recommendation Summary",
    classification_words=["Manual", "Automated"],
    known_versions=["9.9.9"],
)

FIXTURE_GROUPING_HEADER = '''CIS Test Benchmark 2
v9.9.9 - 01-01-2099

Table of Contents

Recommendations
1 Database Services
1.1 Example Database Grouping
1.1.1 Ensure that 'Change Tracking' is set to 'On' (Automated)
Profile Applicability:

 Level 1

Description:

Auditing should be enabled.

Rationale:

Auditing aids incident investigation.

Remediation:

Enable auditing.

1.1.2 Ensure that 'History Window' is 'greater than 90 days' (Manual)
Profile Applicability:

 Level 1

Description:

Longer retention aids investigation.

Rationale:

Short retention loses historical data.

Remediation:

Increase retention to over 90 days.

Appendix: Recommendation Summary
Table
1        Database Services
1.1      Example Database Grouping
1.1.1    Ensure that 'Change Tracking' is set to 'On' (Automated)
1.1.2    Ensure that 'History Window' is 'greater than 90 days' (Manual)

Appendix: Change History
Nothing to see here.
'''


def test_grouping_header_with_no_marker_and_no_body_content_is_excluded():
    catalog = parse_benchmark(FIXTURE_GROUPING_HEADER, _GENERIC_CONFIG)
    ids = [r.id for r in catalog.rules]
    assert ids == ["1.1.1", "1.1.2"]
    assert "1.1" not in ids
    assert len(catalog.rules) == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_importer_pdf_benchmark_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cis_benchmark.importer._pdf_benchmark_parser'`

- [ ] **Step 3: Write minimal implementation**

Create `cis_benchmark/importer/_pdf_benchmark_parser.py`:

```python
import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .errors import ImporterError
from .schema import BenchmarkCatalog, ImportedRule, now_iso

_RULE_ID_RE = re.compile(r"^(\d+(?:\.\d+){1,2})\s")
_SECTION_ID_RE = re.compile(r"^(\d+)\s+(.+)$")
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


@dataclass
class BenchmarkParserConfig:
    benchmark_name: str
    appendix_marker: str
    appendix_end_marker: str = "Appendix: Change History"
    classification_words: List[str] = field(default_factory=lambda: ["Scored", "Not Scored"])
    known_versions: List[str] = field(default_factory=list)


def _find_index(text: str, marker: str) -> int:
    idx = text.find(marker)
    if idx == -1:
        raise ImporterError(
            f"Could not locate {marker!r} in the extracted text — this "
            "document's structure doesn't match what this parser expects."
        )
    return idx


def _find_last_index(text: str, marker: str) -> int:
    """Like _find_index, but returns the LAST occurrence. Needed for
    markers that also appear earlier in the document's own Table of
    Contents as a dot-leader entry — the real section is always the last
    occurrence, never the first.
    """
    idx = text.rfind(marker)
    if idx == -1:
        raise ImporterError(
            f"Could not locate {marker!r} in the extracted text — this "
            "document's structure doesn't match what this parser expects."
        )
    return idx


def _parse_summary_table(text: str, config: BenchmarkParserConfig, class_re: "re.Pattern"):
    """Returns an ordered list of (rule_id, section_name, title,
    classification) parsed from the PDF's own Appendix summary table — the
    authoritative anchor list used to carve the body. Never derived by
    scanning the body itself, which would misidentify numbered
    cross-references inside "CIS Controls:" sections as new rules.

    classification is None when no configured classification word was
    found for this row — this can mean either a corrupted/unparseable
    marker on a real rule, or a structural grouping/subsection heading
    (e.g. "4.1 SQL Server - Auditing") that groups several leaf rules and
    was never meant to have a marker. Both cases are included here; the
    caller (parse_benchmark) disambiguates them using body content, since
    that information isn't available at this stage.
    """
    start = _find_last_index(text, config.appendix_marker)
    end = text.find(config.appendix_end_marker, start)
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
            m = class_re.search(joined)
            classification = m.group(1) if m else None
            title = joined[:m.start()].strip() if m else joined.strip()
            anchors.append((pending_id, current_section, title, classification))
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
        section_m = _SECTION_ID_RE.match(line)
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


def parse_benchmark(text: str, config: BenchmarkParserConfig, source_filename: str = "") -> BenchmarkCatalog:
    """Parses CIS Benchmark text (already extracted and cleaned by
    pdf_extract.extract_text) into a BenchmarkCatalog, using config for the
    parts of the document structure that vary between benchmarks (appendix
    heading text, classification vocabulary, benchmark name, which
    versions have actually been verified against real data).
    """
    class_re = re.compile(r"\((" + "|".join(re.escape(w) for w in config.classification_words) + r")\)")

    version_m = _VERSION_RE.search(text)
    benchmark_version = version_m.group(1) if version_m else "unknown"

    anchors = _parse_summary_table(text, config, class_re)

    # Unlike the appendix marker, this marker is safe with the first
    # occurrence: the TOC's own "Recommendations" entry always has trailing
    # dot-leaders/a page number on the same line, so it never matches this
    # exact-line marker (which requires an immediate newline after the word).
    body_start = _find_index(text, "\nRecommendations\n")
    body_end = text.find(config.appendix_marker, body_start)
    if body_end == -1:
        body_end = len(text)
    body = text[body_start:body_end]

    rules = []
    missing_ids = []
    cursor = 0
    for i, (rule_id, section, title, classification) in enumerate(anchors):
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

        if classification is None and not fields:
            # No classification marker AND no recognized body content at
            # all — this was a bare grouping/subsection heading line (e.g.
            # "4.1 SQL Server - Auditing"), not a real rule. Skip it.
            continue

        missing = [lbl for lbl in _REQUIRED_LABELS if lbl not in fields]
        if classification is None:
            missing.append("classification (could not parse from Summary Table)")

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
            classification=classification if classification is not None else "",
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
        benchmark_name=config.benchmark_name,
        benchmark_version=benchmark_version,
        source_filename=source_filename,
        extracted_at=now_iso(),
        version_verified=benchmark_version in config.known_versions,
        rules=rules,
    )
```

Now rewrite `cis_benchmark/importer/aws_parser.py` in full:

```python
from ._pdf_benchmark_parser import BenchmarkParserConfig, parse_benchmark
from .schema import BenchmarkCatalog

_CONFIG = BenchmarkParserConfig(
    benchmark_name="CIS Amazon Web Services Foundations Benchmark",
    appendix_marker="Appendix: Summary Table",
    classification_words=["Scored", "Not Scored"],
    known_versions=["1.2.0"],
)


def parse(text: str, source_filename: str = "") -> BenchmarkCatalog:
    return parse_benchmark(text, _CONFIG, source_filename)
```

Now trim `tests/test_importer_aws_parser.py` down to AWS-config-specific assertions only — replace its full contents with:

```python
from cis_benchmark.importer.aws_parser import parse

# Minimal, clearly-fictional fixture — just enough to verify aws_parser.py
# wires the correct BenchmarkParserConfig (benchmark_name, appendix
# marker, classification vocabulary, known_versions). The shared parsing
# algorithm itself (wrapped titles, TOC collisions, grouping headers,
# incomplete-flagging, etc.) is tested once, generically, in
# tests/test_importer_pdf_benchmark_parser.py — no need to duplicate it
# per cloud.
FIXTURE = '''CIS Amazon Web Services Foundations
Benchmark
v1.2.0 - 01-01-2099

Table of Contents

Recommendations
1 Identity and Access Management
1.1 Avoid using the primary administrative account for routine operations (Scored)
Description:

Do not use the root account for daily tasks.

Rationale:

The root account has unrestricted access to everything.

Remediation:

Stop using the root account for daily tasks.

Appendix: Summary Table
1      Identity and Access Management
1.1    Avoid using the primary administrative account for routine operations (Scored)

Appendix: Change History
Nothing to see here.
'''


def test_aws_parser_uses_correct_benchmark_name():
    catalog = parse(FIXTURE, source_filename="fixture.pdf")
    assert catalog.benchmark_name == "CIS Amazon Web Services Foundations Benchmark"


def test_aws_parser_uses_scored_not_scored_vocabulary():
    catalog = parse(FIXTURE)
    assert catalog.rules[0].classification == "Scored"


def test_aws_parser_known_version_is_verified():
    catalog = parse(FIXTURE)  # fixture uses v1.2.0, which is aws_parser's known_versions
    assert catalog.version_verified is True


def test_aws_parser_unknown_version_is_not_verified():
    unknown_version_text = FIXTURE.replace("v1.2.0 - 01-01-2099", "v9.9.9 - 01-01-2099")
    catalog = parse(unknown_version_text)
    assert catalog.version_verified is False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_importer_pdf_benchmark_parser.py tests/test_importer_aws_parser.py -v`
Expected: PASS (15 + 4 = 19 tests)

Then run the full suite to confirm no other regressions:

Run: `python -m pytest -v`
Expected: PASS (previous 52, minus the 12 old AWS-parser tests removed, plus 15 new shared-engine tests, plus 4 new AWS-config tests, plus 2 new tests from Task 1's `test_importer_schema.py` update — net around 61; the exact count matters less than zero failures)

- [ ] **Step 5: Commit**

```bash
git add cis_benchmark/importer/_pdf_benchmark_parser.py cis_benchmark/importer/aws_parser.py tests/test_importer_pdf_benchmark_parser.py tests/test_importer_aws_parser.py
git commit -m "Extract shared benchmark-parsing engine, refactor AWS parser onto it"
```

---

### Task 3: Azure parser

**Files:**
- Create: `cis_benchmark/importer/azure_parser.py`
- Test: `tests/test_importer_azure_parser.py`
- Modify: `cis_benchmark/cli.py`
- Modify: `tests/test_cli_subcommands.py`

**Interfaces:**
- Consumes: `BenchmarkParserConfig`, `parse_benchmark` (Task 2, `cis_benchmark.importer._pdf_benchmark_parser`).
- Produces: `parse(text: str, source_filename: str = "") -> BenchmarkCatalog` in `azure_parser.py`, matching `aws_parser.parse`'s signature exactly (so it can be dropped into `_IMPORT_PARSERS` the same way).

- [ ] **Step 1: Write the failing test**

Create `tests/test_importer_azure_parser.py`:

```python
from cis_benchmark.importer.azure_parser import parse

# Minimal, clearly-fictional fixture verifying azure_parser.py wires the
# correct config: benchmark name, the wrapped "Appendix: Recommendation
# Summary\nTable" heading (confirmed against the real document during
# design — this fixture reproduces that exact wrap), and the
# Manual/Automated classification vocabulary (not AWS's Scored/Not Scored).
FIXTURE = '''CIS Microsoft Azure Foundations
Benchmark
v1.4.0 - 01-01-2099

Table of Contents

Recommendations
1 Identity and Access Management
1.1 Ensure that 'Example Setting' is 'Enabled' for all Example Users (Manual)
Description:

Example description text.

Rationale:

Example rationale text.

Remediation:

Example remediation text.

Appendix: Recommendation Summary
Table
1        Identity and Access Management
1.1      Ensure that 'Example Setting' is 'Enabled' for all Example Users (Manual)

Appendix: Change History
Nothing to see here.
'''


def test_azure_parser_uses_correct_benchmark_name():
    catalog = parse(FIXTURE, source_filename="fixture.pdf")
    assert catalog.benchmark_name == "CIS Microsoft Azure Foundations Benchmark"


def test_azure_parser_uses_manual_automated_vocabulary():
    catalog = parse(FIXTURE)
    assert catalog.rules[0].classification == "Manual"


def test_azure_parser_handles_wrapped_appendix_heading():
    # If azure_parser's appendix_marker didn't account for the real
    # document's "Appendix: Recommendation Summary\nTable" line wrap, this
    # fixture (which reproduces that exact wrap) would fail to locate the
    # Summary Table at all and raise ImporterError instead of parsing.
    catalog = parse(FIXTURE)
    assert len(catalog.rules) == 1


def test_azure_parser_known_version_is_verified():
    catalog = parse(FIXTURE)  # fixture uses v1.4.0, azure_parser's known version
    assert catalog.version_verified is True


def test_azure_parser_unknown_version_is_not_verified():
    unknown_version_text = FIXTURE.replace("v1.4.0 - 01-01-2099", "v9.9.9 - 01-01-2099")
    catalog = parse(unknown_version_text)
    assert catalog.version_verified is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_importer_azure_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cis_benchmark.importer.azure_parser'`

- [ ] **Step 3: Write minimal implementation**

Create `cis_benchmark/importer/azure_parser.py`:

```python
from ._pdf_benchmark_parser import BenchmarkParserConfig, parse_benchmark
from .schema import BenchmarkCatalog

_CONFIG = BenchmarkParserConfig(
    benchmark_name="CIS Microsoft Azure Foundations Benchmark",
    appendix_marker="Appendix: Recommendation Summary",
    classification_words=["Manual", "Automated"],
    known_versions=["1.4.0"],
)


def parse(text: str, source_filename: str = "") -> BenchmarkCatalog:
    return parse_benchmark(text, _CONFIG, source_filename)
```

Now wire Azure into the CLI. In `cis_benchmark/cli.py`, change the import block (around line 16):
```python
from .importer.aws_parser import parse as parse_aws
```
to:
```python
from .importer.aws_parser import parse as parse_aws
from .importer.azure_parser import parse as parse_azure
```

Change `_IMPORT_PARSERS` (around line 23) from:
```python
_IMPORT_PARSERS = {"aws": parse_aws}
```
to:
```python
_IMPORT_PARSERS = {"aws": parse_aws, "azure": parse_azure}
```

In `_run_import` (around line 208-226), make two changes. First, the error message for an unimplemented cloud should list whatever's actually implemented rather than a hardcoded string that goes stale as more clouds are added:
```python
def _run_import(args):
    if args.cloud not in _IMPORT_PARSERS:
        raise ImporterError(
            f"`cis import --cloud {args.cloud}` is not implemented yet. "
            f"Supported today: {', '.join(sorted(_IMPORT_PARSERS.keys()))}."
        )

    text = extract_text(args.pdf_path)
    catalog = _IMPORT_PARSERS[args.cloud](text, source_filename=os.path.basename(args.pdf_path))

    if not catalog.version_verified:
        print(
            f"Warning: this PDF's version ({catalog.benchmark_version}) hasn't been "
            f"verified against real data for --cloud {args.cloud}. Results may be "
            "inaccurate — treat with extra scrutiny."
        )

    output_path = args.output or os.path.join("imports", f"{args.cloud}_{catalog.benchmark_version}.json")
    try:
        catalog.write(output_path)
    except OSError as e:
        raise ImporterError(f"Could not write output file {output_path}: {e}")

    total = len(catalog.rules)
    incomplete = sum(1 for r in catalog.rules if r.incomplete)
    print(f"Parsed {total} rule(s) ({incomplete} incomplete) -> {output_path}")
```

Now fix the existing CLI test that used `"azure"` as an example of an unimplemented cloud — it's implemented now, so this test would start failing (no error raised) unless updated. In `tests/test_cli_subcommands.py`, find:
```python
def test_run_import_rejects_unimplemented_cloud():
    args = argparse.Namespace(cloud="azure", pdf_path="fake.pdf", output=None)
    with pytest.raises(ImporterError, match="not implemented yet"):
        cli._run_import(args)
```
Change `cloud="azure"` to `cloud="workspace"` (still unimplemented after this task):
```python
def test_run_import_rejects_unimplemented_cloud():
    args = argparse.Namespace(cloud="workspace", pdf_path="fake.pdf", output=None)
    with pytest.raises(ImporterError, match="not implemented yet"):
        cli._run_import(args)
```

Add one new test to the same file confirming Azure is now dispatchable and the version-warning prints when appropriate:
```python
def test_run_import_prints_warning_for_unverified_version(tmp_path, monkeypatch, capsys):
    fake_catalog = BenchmarkCatalog(
        benchmark_name="Fake", benchmark_version="0.0.1",
        source_filename="fake.pdf", extracted_at="now",
        version_verified=False, rules=[],
    )
    monkeypatch.setattr(cli, "extract_text", lambda path: "irrelevant")
    monkeypatch.setattr(cli, "_IMPORT_PARSERS", {"aws": lambda text, source_filename="": fake_catalog})

    args = argparse.Namespace(cloud="aws", pdf_path="fake.pdf", output=str(tmp_path / "out.json"))
    cli._run_import(args)

    captured = capsys.readouterr()
    assert "Warning" in captured.out
    assert "0.0.1" in captured.out
```
(This test needs `BenchmarkCatalog` imported at the top of the file — check the existing `from cis_benchmark.importer.schema import BenchmarkCatalog, ImportedRule` import line and confirm `BenchmarkCatalog` is already there; it is, from the pre-existing tests in this file.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_importer_azure_parser.py tests/test_cli_subcommands.py -v`
Expected: PASS (5 + existing-count-plus-1 tests)

Then the full suite:

Run: `python -m pytest -v`
Expected: PASS, zero failures

- [ ] **Step 5: Manual acceptance check against the real Azure PDF**

The project owner's real Azure PDF is at `CIS_Microsoft_Azure_Foundations_Benchmark_v1.4.0.pdf` in the project root (gitignored, not to be committed — do not read its text content beyond what's needed to run this check and inspect the JSON summary).

```bash
source .venv/bin/activate
cis import CIS_Microsoft_Azure_Foundations_Benchmark_v1.4.0.pdf --cloud azure --output /tmp/azure_verify.json
python3 -c "
import json
from collections import Counter
d = json.load(open('/tmp/azure_verify.json'))
print('total_rules:', d['total_rules'], 'incomplete_rules:', d['incomplete_rules'])
print('version_verified:', d['version_verified'], 'benchmark_version:', d['benchmark_version'])
print(Counter(r['section'] for r in d['rules']))
"
rm -f /tmp/azure_verify.json
```

Expected (verified during design, must match exactly — if it doesn't, stop and investigate before proceeding, the same discipline the AWS build used): `total_rules: 115`, `incomplete_rules: 0`, `version_verified: True`, `benchmark_version: 1.4.0`, sections `{'1. Identity and Access Management': 22, '2. Microsoft Defender for Cloud': 15, '3. Storage Accounts': 12, '4. Database Services': 24, '5. Logging and Monitoring': 17, '6. Networking': 6, '7. Virtual Machines': 7, '8. Other Security Considerations': 7, '9. AppService': 11}`.

- [ ] **Step 6: Commit**

```bash
git add cis_benchmark/importer/azure_parser.py cis_benchmark/cli.py tests/test_importer_azure_parser.py tests/test_cli_subcommands.py
git commit -m "Add Azure benchmark parser, wire into cis import --cloud azure"
```

---

### Task 4: GCP parser

Same shape as Task 3 — GCP's config differs from Azure's only in `benchmark_name` (confirmed identical `appendix_marker` and `classification_words` during design investigation).

**Files:**
- Create: `cis_benchmark/importer/gcp_parser.py`
- Test: `tests/test_importer_gcp_parser.py`
- Modify: `cis_benchmark/cli.py`

**Interfaces:**
- Consumes: `BenchmarkParserConfig`, `parse_benchmark` (Task 2).
- Produces: `parse(text: str, source_filename: str = "") -> BenchmarkCatalog` in `gcp_parser.py`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_importer_gcp_parser.py`:

```python
from cis_benchmark.importer.gcp_parser import parse

FIXTURE = '''CIS Google Cloud Platform Foundation
Benchmark
v1.2.0 - 01-01-2099

Table of Contents

Recommendations
1 Identity and Access Management
1.1 Ensure that federated identity accounts are required (Manual)
Description:

Example description text.

Rationale:

Example rationale text.

Remediation:

Example remediation text.

Appendix: Recommendation Summary
Table
1        Identity and Access Management
1.1      Ensure that federated identity accounts are required (Manual)

Appendix: Change History
Nothing to see here.
'''


def test_gcp_parser_uses_correct_benchmark_name():
    catalog = parse(FIXTURE, source_filename="fixture.pdf")
    # Note: "Foundation", singular — matches CIS's own (inconsistent) naming
    # on the real document, confirmed during design investigation.
    assert catalog.benchmark_name == "CIS Google Cloud Platform Foundation Benchmark"


def test_gcp_parser_uses_manual_automated_vocabulary():
    catalog = parse(FIXTURE)
    assert catalog.rules[0].classification == "Manual"


def test_gcp_parser_handles_wrapped_appendix_heading():
    catalog = parse(FIXTURE)
    assert len(catalog.rules) == 1


def test_gcp_parser_known_version_is_verified():
    catalog = parse(FIXTURE)
    assert catalog.version_verified is True


def test_gcp_parser_unknown_version_is_not_verified():
    unknown_version_text = FIXTURE.replace("v1.2.0 - 01-01-2099", "v9.9.9 - 01-01-2099")
    catalog = parse(unknown_version_text)
    assert catalog.version_verified is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_importer_gcp_parser.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'cis_benchmark.importer.gcp_parser'`

- [ ] **Step 3: Write minimal implementation**

Create `cis_benchmark/importer/gcp_parser.py`:

```python
from ._pdf_benchmark_parser import BenchmarkParserConfig, parse_benchmark
from .schema import BenchmarkCatalog

_CONFIG = BenchmarkParserConfig(
    benchmark_name="CIS Google Cloud Platform Foundation Benchmark",
    appendix_marker="Appendix: Recommendation Summary",
    classification_words=["Manual", "Automated"],
    known_versions=["1.2.0"],
)


def parse(text: str, source_filename: str = "") -> BenchmarkCatalog:
    return parse_benchmark(text, _CONFIG, source_filename)
```

Wire into `cis_benchmark/cli.py`. Change the import block:
```python
from .importer.aws_parser import parse as parse_aws
from .importer.azure_parser import parse as parse_azure
```
to:
```python
from .importer.aws_parser import parse as parse_aws
from .importer.azure_parser import parse as parse_azure
from .importer.gcp_parser import parse as parse_gcp
```

Change `_IMPORT_PARSERS`:
```python
_IMPORT_PARSERS = {"aws": parse_aws, "azure": parse_azure}
```
to:
```python
_IMPORT_PARSERS = {"aws": parse_aws, "azure": parse_azure, "gcp": parse_gcp}
```

(`_run_import`'s error message already lists `_IMPORT_PARSERS.keys()` dynamically from Task 3 — no further change needed there.)

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_importer_gcp_parser.py -v`
Expected: PASS (5 tests)

Then the full suite:

Run: `python -m pytest -v`
Expected: PASS, zero failures

- [ ] **Step 5: Manual acceptance check against the real GCP PDF**

The project owner's real GCP PDF is at `GCP_CIS_Foundation_Benchmark_v1.2.0.pdf` in the project root (gitignored, not to be committed — a duplicate `GCP_CIS_Foundation_Benchmark_v1.2.0 (1).pdf` also exists in the same directory; either works identically, use the one without the `(1)` suffix).

```bash
source .venv/bin/activate
cis import "GCP_CIS_Foundation_Benchmark_v1.2.0.pdf" --cloud gcp --output /tmp/gcp_verify.json
python3 -c "
import json
from collections import Counter
d = json.load(open('/tmp/gcp_verify.json'))
print('total_rules:', d['total_rules'], 'incomplete_rules:', d['incomplete_rules'])
print('version_verified:', d['version_verified'], 'benchmark_version:', d['benchmark_version'])
print(Counter(r['section'] for r in d['rules']))
"
rm -f /tmp/gcp_verify.json
```

Expected (verified during design, must match exactly): `total_rules: 83`, `incomplete_rules: 0`, `version_verified: True`, `benchmark_version: 1.2.0`, sections `{'1. Identity and Access Management': 15, '2. Logging and Monitoring': 12, '3. Networking': 10, '4. Virtual Machines': 11, '5. Storage': 2, '6. Cloud SQL Database Services': 30, '7. BigQuery': 3}`.

- [ ] **Step 6: Commit**

```bash
git add cis_benchmark/importer/gcp_parser.py cis_benchmark/cli.py tests/test_importer_gcp_parser.py
git commit -m "Add GCP benchmark parser, wire into cis import --cloud gcp"
```

---

### Task 5: README documentation

**Files:**
- Modify: `README.md`

**Interfaces:**
- Consumes: nothing new (documentation only).

- [ ] **Step 1: Update the "Importing an Official Benchmark PDF" section**

Find this paragraph in `README.md`:
```
**Getting a PDF:** Download the official benchmark from
[cisecurity.org/cis-benchmarks](https://www.cisecurity.org/cis-benchmarks)
(free CIS account required). Only the AWS Foundations Benchmark is
supported today.
```
Replace with:
```
**Getting a PDF:** Download the official benchmark from
[cisecurity.org/cis-benchmarks](https://www.cisecurity.org/cis-benchmarks)
(free CIS account required). AWS, Azure, and GCP are supported today;
Google Workspace is not yet implemented.
```

Find the example command:
```
cis import /path/to/CIS_AWS_Foundations_Benchmark.pdf --cloud aws
```
Add two more examples right after it:
```
cis import /path/to/CIS_Microsoft_Azure_Foundations_Benchmark.pdf --cloud azure
cis import /path/to/GCP_CIS_Foundation_Benchmark.pdf --cloud gcp
```

- [ ] **Step 2: Document `version_verified` and the version warning**

Right after the paragraph explaining the `incomplete`/`missing_sections` fields, add:
```
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
| AWS | 1.2.0 |
| Azure | 1.4.0 |
| GCP | 1.2.0 |
```

- [ ] **Step 3: Verify every command in the updated sections works by hand**

Run each `cis import ... --cloud X` example from the README (substituting the real filenames already in the project directory) and confirm no typos in flag names or paths.

- [ ] **Step 4: Commit and push**

```bash
git add README.md
git commit -m "Document Azure and GCP support, version_verified warnings"
git push
```
