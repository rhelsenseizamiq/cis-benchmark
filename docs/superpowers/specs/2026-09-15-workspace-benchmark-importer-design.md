# Google Workspace Benchmark PDF Importer — Design Spec

**Date:** 2026-09-15
**Status:** Approved for implementation
**Scope:** Architectural (generalizes two shared-engine regexes and the Summary Table end-boundary; adds a Workspace parser; adds one small title-cleanup rule to the shared engine)
**Supersedes (for scope only, not history):** `docs/superpowers/specs/2026-09-14-multi-cloud-benchmark-importer-design.md`, whose Non-goals section explicitly deferred Workspace as its own follow-up once a PDF was available. This spec is that follow-up.

## Problem

`cis import --cloud workspace` returns "not yet implemented." A real Google Workspace Foundations Benchmark v1.4 PDF is now available. The goal is to extend the shared parsing engine (built for AWS/Azure/GCP) to cover it, using the same investigate-the-real-document-first discipline that has caught a real bug in every prior cloud added — this one included.

## Investigation findings

The real PDF was inspected directly (`pdftotext -layout`, the real `extract_text()` output, and the full two-pass algorithm hand-run against the real extracted text) before writing this spec. Not committed to the repo (gitignored `*.pdf`).

### CIS Google Workspace Foundations Benchmark v1.4 (299 pages)

- Same overall per-rule template as AWS/Azure/GCP (`Profile Applicability:` / `Description:` / `Rationale:` / optional `Impact:` / `Audit:` / `Remediation:` / optional `Default Value:` / `References:` / `CIS Controls:` / optional `Additional Information:`).
- **Rule IDs go far deeper than any prior cloud: 2 to 6 segments** (e.g. `1.1`, `1.1.1`, `3.1.1.1.1`, `3.1.2.1.1.6`). The shared engine's `_RULE_ID_RE = re.compile(r"^(\d+(?:\.\d+){1,2})\s")` caps at 3 total segments by construction — any deeper ID simply never matches and silently vanishes from parsing. This was the root cause of an initial verification run recovering only 32 of the real 86 rules. **Fix, verified against the real document:** generalize to `re.compile(r"^(\d+(?:\.\d+)+)\s")` (one or more repetitions instead of exactly 1-2). Re-running with this fix recovers all 86 anchors correctly; AWS/Azure/GCP's real max depth is 3, so this is a pure superset — every ID either cloud already produces still matches identically.
- **The Summary Table is directly followed by 8 additional appendices** the other three clouds don't have (`Appendix: CIS Controls v7/v8 IG 1/2/3 Mapped`, `...Unmapped`, twice) sitting between `Appendix: Summary Table` and `Appendix: Change History`. The shared engine currently bounds the Summary Table slice by searching for the literal string `config.appendix_end_marker` (`"Appendix: Change History"` by default) — for Workspace this sweeps in all 8 extra appendices too, producing duplicate/corrupted anchor rows (observed: 102 anchors with the same rule ID repeated 3+ times). **Fix, verified against the real document:** bound the slice by the *next* literal `"Appendix:"` occurrence, whatever it's named, instead of a specific hardcoded string. For AWS/Azure/GCP the next `Appendix:` after their Summary Table already *is* Change History, so this is behavior-preserving for them; `appendix_end_marker` becomes unused and can be removed from `BenchmarkParserConfig`.
- **Version string is 2 segments, not 3:** title page reads `v1.4 - 08-04-2026` (vs. AWS/Azure/GCP's `vX.Y.Z` pattern). The shared `_VERSION_RE = re.compile(r"v(\d+\.\d+\.\d+)\s*-\s*[\d-]+")` requires exactly 3 segments and fails to match, falling back to `benchmark_version = "unknown"`. **Fix, verified against the real document:** generalize to `re.compile(r"v(\d+(?:\.\d+)+)\s*-\s*[\d-]+")`. `known_versions=["1.4"]` for Workspace's config (not `"1.4.0"` — the real title page has no third segment).
- **Classification vocabulary:** `(Manual)`/`(Automated)`, same as Azure/GCP — confirmed 0 `(Automated)` occurrences anywhere in this document; all 86 real rules are `(Manual)`. No schema or engine change needed; `classification_words=["Manual", "Automated"]` in the Workspace config, same as Azure/GCP.
- **Grouping-header pattern, same shape as Azure/GCP** but far more of them given the deeper nesting: 51 rows in the real Summary Table have no classification marker and group nested leaf rules (e.g. `1.1 Users`, `3.1.2.1 Sharing Options`) — all correctly dropped by the existing "no marker + no body fields = grouping header, skip it" rule once the rule-ID regex fix above lets these rows be recognized as anchors in the first place. No new logic needed here beyond the regex fix.
- **New, cosmetic-only wrinkle no other cloud has:** the Summary Table (and the body's rule-header lines) embed a profile-level tag directly before the title, e.g. `1.1.1 (L1) Ensure that between two and four global admins are designated`. This is *not* a new information source — the body's `Profile Applicability:` field already reads `• Enterprise Level 1` for this same rule, and the shared engine's existing unmodified logic (`"Level 2" in profile_raw` / `"Level 1" in profile_raw`) already populates `ImportedRule.profile_level` correctly from that field with zero changes. The `(L1)`/`(L2)` tag in the title is therefore pure redundant decoration that needs stripping so titles read cleanly. **Fix, verified against the real document:** in `_parse_summary_table`'s row-joining step, strip a leading `(L\d)\s*` from the joined text before searching for the classification marker. Confirmed present on all 86/86 real rules, always immediately after the rule ID and before the title text; confirmed safe to apply unconditionally (AWS/Azure/GCP titles never begin with this pattern).
- **Page-footer format differs:** bare `Page N` (right-aligned, e.g. `                                    Page 1`), not AWS/Azure/GCP's `N | P a g e`. The existing `_PAGE_FOOTER_RE` in `pdf_extract.py` only matches the pipe format and leaves these lines in place. **Fix:** add a second, equally strict whole-line regex `^\s*Page\s+\d+\s*$`. Confirmed 299 occurrences (one per page), all matching this exact shape with no trailing content — safe to strip unconditionally; a real AWS/Azure/GCP body line consisting of nothing but the word "Page" and a number is not a realistic collision.
- **New artifact no other cloud has:** a repeating single-line confidentiality watermark, `Internal Only - General`, appearing once per page (300 occurrences) and confirmed leaking into extracted rule body text near page breaks (observed between the end of an Audit section and the following Remediation label). **Fix:** add a third whole-line regex to `pdf_extract.py`, `^\s*Internal Only - General\s*$`, stripped the same way as the footer.
- The already-shipped PUA-glyph stripping in `extract_text()` works unmodified for Workspace — 946 raw PUA occurrences (same `U+F06F` glyph family as the other three clouds), 0 remaining after extraction.
- `"\nRecommendations\n"` remains a safe body-start marker with the same reasoning as AWS/Azure/GCP, though it needed an indentation-tolerant match during verification since Workspace's body has pervasive variable leading whitespace the other three don't (the shared engine's line-processing already strips each line before matching content, so this doesn't require an engine change — verified the existing `.strip()`-based row/label matching in `_parse_summary_table` and `_split_block_into_sections` already tolerates it; only the body-start anchor search itself needed confirming, and it works unmodified since `_find_index` does a plain substring search, not a line-anchored one).
- Full pipeline re-verified end to end against the real document (all fixes applied): **86/86 rules recovered, 0 missing, 0 incomplete**, cross-checked independently against raw label counts (`Profile Applicability:`/`Description:`/`Rationale:`/`Impact:`/`Audit:`/`Remediation:` each occur exactly 86 times in the extracted text). Sections: `{'1. Directory': 3, '3. Apps': 55, '4. Security': 18, '5. Reporting': 2, '6. Rules': 8}` (Workspace has no top-level section `2`, confirmed in the real document — not a bug).

### Conclusion from the investigation

Workspace's structural differences are all real, all confirmed by direct inspection, and all fixable as small, targeted generalizations of the existing shared engine rather than new Workspace-specific branches — consistent with the design direction set by the Azure/GCP build. Three of the five fixes (rule-ID depth, version-string segments, Summary Table end-boundary) are shared-engine changes that are pure supersets of current AWS/Azure/GCP behavior; the other two (page-footer format, watermark) are additive, whole-line-anchored regexes at the extraction layer with the same safety property the existing PUA/footer stripping already has.

## Non-goals

- Re-verifying the shared-engine regex generalizations against real AWS/Azure/GCP PDFs — the existing test suite's synthetic fixtures already exercise the pre-generalization shapes; running them green after the change is sufficient regression evidence, since the change is a strict superset. The already-agreed-upon separate follow-up (checking the newer AWS v7.0.0/Azure v6.0.0/GCP v5.0.0 PDFs against the *current* configs) is unrelated scope and stays its own task, after this one.
- Any change to `cis scan` or the four existing hand-written checks.
- Redistributing or committing any real CIS PDF content — unchanged policy.

## Architecture

### Shared engine changes (`_pdf_benchmark_parser.py`)

```python
_RULE_ID_RE = re.compile(r"^(\d+(?:\.\d+)+)\s")          # was {1,2}
_VERSION_RE = re.compile(r"v(\d+(?:\.\d+)+)\s*-\s*[\d-]+")  # was \d+\.\d+\.\d+
```

`_parse_summary_table`'s end-boundary changes from a configured marker string to the next literal `"Appendix:"`:

```python
start = _find_last_index(text, config.appendix_marker)
end = text.find("Appendix:", start + len(config.appendix_marker))
if end == -1:
    end = len(text)
```

`BenchmarkParserConfig.appendix_end_marker` is removed (no longer used by any cloud — AWS/Azure/GCP relied on it only because it happened to equal "next Appendix:" for them).

`_parse_summary_table`'s `flush()` gains one line, applied unconditionally to the joined row text before the classification search:

```python
_L_TAG_RE = re.compile(r"^\(L\d\)\s*")
...
joined = _L_TAG_RE.sub("", joined.strip())
```

No change to `_split_block_into_sections`, the body-carving loop, `ImportedRule`, or `BenchmarkCatalog` — everything downstream of the anchor list and the extracted text is already cloud-agnostic and handles Workspace correctly once the anchors are correct.

### `pdf_extract.py` additions

```python
_PAGE_NUMBER_FOOTER_RE = re.compile(r"^\s*Page\s+\d+\s*$", re.MULTILINE)
_WATERMARK_RE = re.compile(r"^\s*Internal Only - General\s*$", re.MULTILINE)
```

Applied unconditionally in `extract_text()`, alongside the existing `_PAGE_FOOTER_RE`/`_PUA_GLYPH_RE` stripping — both are whole-line-anchored, so they can only ever remove a line that contains nothing but the footer or watermark text, with no plausible collision against real AWS/Azure/GCP body content.

### New module: `cis_benchmark/importer/workspace_parser.py`

Same thin-wrapper shape as `aws_parser.py`/`azure_parser.py`/`gcp_parser.py`:

```python
_CONFIG = BenchmarkParserConfig(
    benchmark_name="CIS Google Workspace Foundations Benchmark",
    appendix_marker="Appendix: Summary Table",
    classification_words=["Manual", "Automated"],
    known_versions=["1.4"],
)
def parse(text: str, source_filename: str = "") -> BenchmarkCatalog:
    return parse_benchmark(text, _CONFIG, source_filename)
```

### CLI wiring

`cis_benchmark/cli.py`'s `_IMPORT_PARSERS` dict grows from `{"aws": ..., "azure": ..., "gcp": ...}` to include `"workspace": parse_workspace`. `--cloud`'s `choices` list already includes `workspace`.

## Risks / open questions resolved during investigation

- **"Is the rule-ID regex generalization actually a safe superset for AWS/Azure/GCP, or could unbounded depth start matching something it shouldn't?"** The old pattern already accepted a trailing whitespace-terminated numeric-dotted token at line-start; removing the `{1,2}` cap only widens *how many* dot-segments it accepts before the mandatory trailing whitespace — it doesn't change what characters are allowed or loosen the line-start anchor. Confirmed by reasoning, not just precedent; the existing test suite's fixtures (2-3 segment synthetic IDs) will continue to match unchanged, and no existing fixture or real document has non-numeric-dotted content that could newly qualify.
- **"Could stripping `(L\d)` from titles ever eat real content in AWS/Azure/GCP?"** Their titles are always the rule's plain English description with no bracketed prefix of any kind — confirmed by re-reading the Azure/GCP investigation spec's sample titles. The regex only matches at the very start of the string, so it's inert unless a title happens to *begin* with literally `(L` + one digit + `)`, which doesn't occur in either prior spec's verified samples.
- **"Could the two new pdf_extract.py regexes strip real content?"** Both require the *entire* line (after trimming whitespace) to be nothing but the footer/watermark text — a real CIS rule body line consisting of only the word "Page" followed by a number, or only the literal phrase "Internal Only - General", is not a realistic occurrence in AWS/Azure/GCP's real documents.

## Testing

Per existing policy, no real CIS PDF content or extracted text is committed — synthetic fixtures only.

- `tests/test_importer_pdf_benchmark_parser.py`: add cases for the generalized `_RULE_ID_RE` (a synthetic fixture with a 5-6 segment rule ID), the generalized `_VERSION_RE` (a synthetic 2-segment version string), the new "next Appendix:" end-boundary (a synthetic fixture with an extra appendix between Summary Table and Change History), and the `(L\d)` title-stripping rule. Confirm all existing cases in this file still pass unchanged (proving the AWS/Azure/GCP-shaped fixtures are unaffected).
- `tests/test_importer_workspace_parser.py` (new): small config-verification tests confirming the module wires its `BenchmarkParserConfig` correctly (benchmark_name, appendix_marker, classification_words, known_versions) — mirroring `test_importer_azure_parser.py`/`test_importer_gcp_parser.py`, not re-testing shared logic covered above.
- `tests/test_importer_pdf_extract.py`: add cases for the two new stripping regexes (`Page N`-only lines, `Internal Only - General`-only lines), confirming they're removed and confirming a line that merely *contains* these substrings alongside other real text is left alone.
- `tests/test_cli_subcommands.py`: two existing tests use `cloud="workspace"` as their "unimplemented cloud" example (`test_run_import_rejects_unimplemented_cloud`, constructing `argparse.Namespace` directly; `test_main_prints_clean_error_and_exits_1_on_importer_error`, going through real `cli.main()` argv parsing). Once `workspace` is implemented, neither can rely on a real cloud name being simultaneously a valid `--cloud` argparse choice and absent from `_IMPORT_PARSERS` — all 4 choices are now implemented. Fix: `test_run_import_rejects_unimplemented_cloud` bypasses argparse already (constructs `Namespace` directly), so change its `cloud=` value to a synthetic name not in `_IMPORT_PARSERS` (e.g. `"digitalocean"`) — argparse's `choices` list is never consulted on this path. `test_main_prints_clean_error_and_exits_1_on_importer_error` goes through real argv/argparse, so its `--cloud` value must stay one of the 4 real choices (e.g. keep `"workspace"`) while the test additionally monkeypatches `cli._IMPORT_PARSERS` to a dict that omits that key, before calling `cli.main()` — this keeps argparse validation passing while still exercising the runtime "not implemented" branch in `_run_import`.
- Manual acceptance check (not automated, not committed) against the real Workspace PDF already in this working directory, mirroring the AWS/Azure/GCP builds' Task 5 pattern: confirm 86 rules, 0 incomplete, via the installed `cis import --cloud workspace` command end-to-end, not just the raw algorithm.

## Rollout

1. Generalize `_RULE_ID_RE`, `_VERSION_RE`, the Summary Table end-boundary, and add the `(L\d)` title-strip in `_pdf_benchmark_parser.py`; remove the now-unused `appendix_end_marker` field from `BenchmarkParserConfig` (and its default value from any config that set it explicitly, if any do). Full existing suite must stay green — this is the regression check for AWS/Azure/GCP.
2. Add the two new stripping regexes to `pdf_extract.py`.
3. Add `workspace_parser.py` + tests, wire into `cli.py`. Manual acceptance check against the real Workspace PDF.
4. README: document `--cloud workspace` as supported, update the `--cloud` support table.
