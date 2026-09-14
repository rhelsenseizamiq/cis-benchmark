# Multi-Cloud Benchmark PDF Importer — Design Spec

**Date:** 2026-09-14
**Status:** Approved for implementation
**Scope:** Architectural (extracts a shared engine out of the existing AWS-only importer; adds Azure and GCP parsers; changes the shared `ImportedRule` schema)
**Supersedes (for scope only, not history):** `docs/superpowers/specs/2026-09-14-cis-benchmark-pdf-importer-design.md`, whose Rollout section explicitly deferred Azure/GCP/Workspace as future work. This spec is that follow-up.

## Problem

The importer currently only understands the CIS AWS Foundations Benchmark PDF's specific structure — `cis import --cloud azure`/`--cloud gcp`/`--cloud workspace` all return "not yet implemented." The goal is to extend real coverage to Azure and GCP now (Workspace follows once its PDF is available, as its own small follow-up — the shared engine built here makes that cheap), using the same investigate-the-real-document-first discipline that caught three real bugs during the AWS build.

## Investigation findings

Both PDFs were inspected directly (`pdftotext -layout`, real extraction via `cis_benchmark.importer.pdf_extract.extract_text`, and the full two-pass parsing algorithm hand-run against the real extracted text) before writing this spec — not assumed from the AWS precedent. Neither PDF is committed to the repo (gitignored `*.pdf`, per the existing Licensing policy).

### CIS Microsoft Azure Foundations Benchmark v1.4.0 (371 pages)

- Same overall per-rule template as AWS: `Profile Applicability:` / `Description:` / `Rationale:` / optional `Impact:` / `Audit:` / `Remediation:` / optional `Default Value:` / `References:` / `CIS Controls:` / optional `Additional Information:`.
- Appendix heading text differs from AWS and **wraps across a line break in the body**: `"Appendix: Recommendation Summary\nTable"` (AWS's was a single line, `"Appendix: Summary Table"`). Searching for the substring `"Appendix: Recommendation Summary"` (without requiring `"Table"` on the same line) as the `.rfind()` anchor works correctly — verified against the real document.
- **Classification vocabulary is different from AWS's `(Scored)`/`(Not Scored)`: Azure uses `(Manual)`/`(Automated)`** — a different concept (whether Microsoft's Graph API/CLI can programmatically audit the control), not CIS's official scoring axis. 195 `(Automated)` + 151 `(Manual)` occurrences across the whole document (rule headers plus body prose mentions); within the isolated Summary Table slice specifically, this cleanly splits 65/50 across 115 real rules.
- **A structural pattern AWS doesn't have:** some sections group rules under a two-level "subsection" numbered line with no classification marker at all — e.g. `4.1 SQL Server - Auditing` groups the real rules `4.1.1`, `4.1.2`, `4.1.3`... Confirmed by direct inspection of the real Summary Table text. A naive parse using AWS's exact logic produces 121 anchors (115 real rules + 6 phantom subsection-header "rules" with no classification, which is itself a giveaway since none of AWS's rules can end up classification-less by construction).
- **Fix, verified against the real document:** in the anchor-building pass, a numbered Summary Table row whose joined text contains **no** classification marker at all is a grouping/subsection header, not a leaf rule — skip it (fold it into `current_section` context only, don't emit an anchor). Re-running with this rule produces exactly 115 anchors, matching the independently-counted `grep -c "^Profile Applicability:"` = 115 exactly, with the 6 subsection headers correctly excluded and titles clean.
- Full body-carving + section-splitting re-verified end to end against the real document (post-fix): 115/115 rules located in the body, 0 incomplete, correct section assignment across all 9 real top-level sections: `{'1. Identity and Access Management': 22, '2. Microsoft Defender for Cloud': 15, '3. Storage Accounts': 12, '4. Database Services': 24, '5. Logging and Monitoring': 17, '6. Networking': 6, '7. Virtual Machines': 7, '8. Other Security Considerations': 7, '9. AppService': 11}` — summing to 121 rows before the 6-header exclusion, 115 after.
- The already-shipped PUA-glyph and page-footer stripping in `pdf_extract.extract_text` (added during the AWS final review) works unmodified for Azure — confirmed 0 PUA characters remain after extraction, despite the raw PDF containing 230 occurrences of the same `U+F06F` glyph AWS had. This fix lives at the cloud-agnostic extraction layer, exactly where it belongs.
- The existing `_RULE_ID_RE` pattern (`\d+(?:\.\d+){1,2}`) already matches Azure's 3-level rule IDs (e.g. `4.1.1`) without modification — verified (64 real occurrences of the 3-level pattern in this document).
- Title page: `"CIS Microsoft Azure Foundations\nBenchmark\nv1.4.0 - 11-26-2021"` — the existing version regex (`v(\d+\.\d+\.\d+)\s*-\s*[\d-]+`) matches unmodified, capturing `1.4.0`.
- `"\nRecommendations\n"` remains a safe body-start marker (single occurrence, confirmed) — the TOC's own mention has trailing dot-leaders/a page number on the same line, same reasoning as AWS.

### CIS Google Cloud Platform Foundation Benchmark v1.2.0 (281 pages)

Note the benchmark's own title says **"Foundation"**, singular — not "Foundations" like AWS/Azure. This is CIS's own inconsistency, not a typo to correct; the config must match the real document exactly.

- Same per-rule template as AWS/Azure.
- Appendix heading: identical shape to Azure's — `"Appendix: Recommendation Summary\nTable"`, same wrap, same `.rfind()` approach applies unmodified with the same marker string as Azure.
- Classification vocabulary: same as Azure — `(Manual)`/`(Automated)` (201 + 48 occurrences document-wide).
- Same subsection-grouping-header pattern as Azure (3 real occurrences: `6.1 MySQL Database`, `6.2 PostgreSQL Database`, `6.3 SQL Server`, each grouping several 3-level real rules) — handled by the same generalized "no marker = grouping header" rule, no GCP-specific logic needed.
- Full pipeline re-verified end to end against the real document: 83/83 rules located, 0 incomplete, 0 missing, sections `{'1. Identity and Access Management': 15, '2. Logging and Monitoring': 12, '3. Networking': 10, '4. Virtual Machines': 11, '5. Storage': 2, '6. Cloud SQL Database Services': 30, '7. BigQuery': 3}`.
- PUA-glyph stripping confirmed working unmodified (0 remaining after extraction).
- Title page: `"CIS Google Cloud Platform Foundation\nBenchmark\nv1.2.0 - 05-01-2021"` — version regex matches unmodified, capturing `1.2.0`.

### Conclusion from the investigation

Azure and GCP's parsing needs are **identical to each other** in every structural respect (appendix heading, classification vocabulary, the grouping-header wrinkle) and differ from AWS only in: the appendix marker text, the classification vocabulary, and the benchmark name string. This is strong, real-data-backed evidence (not a two-cloud coincidence assumed from theory) that a single shared, config-parameterized engine is the right architecture — confirming the direction chosen before writing this spec.

## Non-goals

- Google Workspace Benchmark support — no PDF available yet. Its own follow-up once the file is provided; expected to be cheap given the shared engine, but not assumed to be identical without inspecting the real document first (the same discipline applied to Azure/GCP here).
- Any change to `cis scan` or the four existing hand-written checks.
- Cross-referencing imported rules against which of the hand-written checks automate them ("N of M automated") — still explicitly future work per the original spec.
- Redistributing or committing any real CIS PDF content — unchanged policy from the original spec.

## Architecture

### New module: `cis_benchmark/importer/_pdf_benchmark_parser.py`

The two-pass algorithm currently living inside `aws_parser.py` moves here, generalized:

```python
@dataclass
class BenchmarkParserConfig:
    benchmark_name: str
    appendix_marker: str
    appendix_end_marker: str = "Appendix: Change History"
    classification_words: List[str] = field(default_factory=lambda: ["Scored", "Not Scored"])
    known_versions: List[str] = field(default_factory=list)

def parse_benchmark(text: str, config: BenchmarkParserConfig, source_filename: str = "") -> BenchmarkCatalog: ...
```

Behavior, all already verified against real AWS/Azure/GCP text during investigation:
1. Locate `config.appendix_marker` via `.rfind()` (last occurrence — avoids the TOC dot-leader collision, the same class of bug fixed for AWS's `AWS-1.1`-equivalent Appendix search).
2. Parse the Summary Table into an ordered anchor list `(rule_id, section, title, classification)`, using `config.classification_words` to build the marker regex. **New rule, generalized from the Azure/GCP finding:** a numbered row whose joined text contains no classification marker at all is a grouping header — update `current_section` context if it's a genuine 2-level "subsection" label, otherwise just drop it; do not emit an anchor. (This never triggers for AWS, which has no such headers — safe to generalize.)
3. Carve the `"Recommendations"` body using the anchor list, exactly as AWS's `parse()` does today.
4. Split each block on the fixed label set (unchanged — already cloud-agnostic).
5. Determine `version_verified: bool` by exact string match of the detected version (e.g. `"1.2.0"`) against `config.known_versions` — no prefix/semver-range matching, since CIS doesn't guarantee compatible parsing across even minor version bumps (the whole reason this spec exists is that different benchmark generations use different vocabulary). Never blocks parsing — an unverified version still parses, just gets flagged.

### `ImportedRule` schema change

`scored: bool` → `classification: str`, holding the raw marker text as found (`"Scored"`, `"Not Scored"`, `"Manual"`, `"Automated"`, or whatever a future benchmark uses — no hardcoded enum). This is a breaking change to the AWS parser's existing output field, judged safe now: nothing outside this development session consumes the JSON (gitignored `imports/`, never committed, no downstream integration built yet) — this is the last point before shipping where changing it is free.

### `BenchmarkCatalog` schema addition

New field `version_verified: bool`. `cli.py`'s `_run_import` prints a clear warning when `False`:
```
Warning: this PDF's version (X.X.X) hasn't been verified against real data for --cloud <cloud>. Known-verified versions: <list>. Results may be inaccurate — treat with extra scrutiny.
```
The JSON output carries `"version_verified": false` so this is visible to anything reading the file later, not just the console session that ran the import.

### Cloud-specific modules become thin config wrappers

```python
# aws_parser.py (refactored from its current ~220 lines)
_CONFIG = BenchmarkParserConfig(
    benchmark_name="CIS Amazon Web Services Foundations Benchmark",
    appendix_marker="Appendix: Summary Table",
    classification_words=["Scored", "Not Scored"],
    known_versions=["1.2.0"],
)
def parse(text: str, source_filename: str = "") -> BenchmarkCatalog:
    return parse_benchmark(text, _CONFIG, source_filename)
```

```python
# azure_parser.py (new)
_CONFIG = BenchmarkParserConfig(
    benchmark_name="CIS Microsoft Azure Foundations Benchmark",
    appendix_marker="Appendix: Recommendation Summary",
    classification_words=["Manual", "Automated"],
    known_versions=["1.4.0"],
)
def parse(text: str, source_filename: str = "") -> BenchmarkCatalog:
    return parse_benchmark(text, _CONFIG, source_filename)
```

```python
# gcp_parser.py (new)
_CONFIG = BenchmarkParserConfig(
    benchmark_name="CIS Google Cloud Platform Foundation Benchmark",
    appendix_marker="Appendix: Recommendation Summary",
    classification_words=["Manual", "Automated"],
    known_versions=["1.2.0"],
)
def parse(text: str, source_filename: str = "") -> BenchmarkCatalog:
    return parse_benchmark(text, _CONFIG, source_filename)
```

### CLI wiring

`cis_benchmark/cli.py`'s `_IMPORT_PARSERS` dict grows from `{"aws": parse_aws}` to `{"aws": parse_aws, "azure": parse_azure, "gcp": parse_gcp}`. `workspace` stays absent (still "not implemented yet") until its own follow-up. No other CLI changes — `--cloud`'s `choices` list already includes all four.

## Risks / open questions resolved during investigation

- **"Will the shared engine actually fit a third, unseen cloud (Workspace)?"** Not assumed here — explicitly named as a non-goal requiring its own real-PDF investigation, exactly the discipline that caught the Azure/GCP subsection-header wrinkle neither AWS nor a documentation read would have predicted.
- **"Could the grouping-header-skip rule silently drop a real rule that has a corrupted/unparseable classification marker (like AWS's old 1.18/4.4 bug)?"** No — that failure mode was already fixed at the `extract_text` layer (PUA-glyph stripping), confirmed 0 PUA characters remain in both new documents after extraction. A rule with a genuinely present-but-garbled marker doesn't currently occur in either verified document; if a future version reintroduces it, the "0 classification found → treat as non-rule" path would incorrectly drop that rule rather than flag it incomplete. This is an acceptable, disclosed trade-off given it hasn't manifested in either verified document — not a silent risk we're pretending away, but a real one worth a comment in the code and a mention in the plan's test coverage.

## Testing

Per the existing policy, no real CIS PDF content or extracted text is committed — synthetic fixtures only, this time deliberately fictional from the start (the AWS build had to fix a fixture that accidentally reused real wording; this plan avoids that from the outset).

- `tests/test_importer_pdf_benchmark_parser.py` (new): the shared engine's behavior against cloud-agnostic synthetic fixtures — the two-pass algorithm, the TOC-collision handling (parameterized marker), the grouping-header-skip rule (a fixture reproducing the Azure/GCP subsection pattern), `version_verified` true/false paths.
- `tests/test_importer_aws_parser.py`: trimmed to AWS-config-specific assertions only (the shared logic's tests move out); update `scored` assertions to `classification`.
- `tests/test_importer_azure_parser.py` (new), `tests/test_importer_gcp_parser.py` (new): small config-verification tests confirming each module wires its `BenchmarkParserConfig` correctly (benchmark_name, appendix_marker, classification_words, known_versions) — not re-testing shared logic already covered above.
- Manual acceptance check (not automated, not committed) against the real Azure and GCP PDFs already in this working directory, mirroring the AWS build's Task 5: confirm the actual counts match this spec's investigation numbers (Azure 115/0 incomplete, GCP 83/0 incomplete) end-to-end through the installed `cis import` command, not just the raw algorithm.

## Rollout

1. Extract `_pdf_benchmark_parser.py`, refactor `aws_parser.py` onto it, update `scored`→`classification` everywhere (schema, AWS parser, all existing tests, README if it documents the field). Full existing suite must stay green.
2. Add `azure_parser.py` + tests, wire into `cli.py`. Manual acceptance check against the real Azure PDF.
3. Add `gcp_parser.py` + tests, wire into `cli.py`. Manual acceptance check against the real GCP PDF.
4. README: document `--cloud azure`/`--cloud gcp` as supported, update the `--cloud` choices table, document `version_verified`/the warning behavior, note Workspace is still pending its own PDF.
