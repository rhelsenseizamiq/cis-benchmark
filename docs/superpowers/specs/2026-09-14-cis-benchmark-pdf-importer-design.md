# CIS Benchmark PDF Importer — Design Spec

**Date:** 2026-09-14
**Status:** Approved for implementation
**Scope:** Architectural (new subsystem: `cis_benchmark/importer/`, plus a CLI subcommand restructure)

## Problem

The project's README previously implied its 18 hand-written checks represent
meaningful coverage of the official CIS Benchmarks ("AWS: CIS AWS Foundations
Benchmark v1.5", etc.). In reality the tool implements 18 checks total against
benchmarks that have 50-100+ official recommendations each, using rule IDs
invented by this project rather than CIS's own numbering. That mismatch was
fixed in the README (2026-09-14, commit `a62fa35`), but the deeper ask behind
it — "where's the step that takes the actual CIS Benchmark document and turns
it into something this tool understands?" — was never built. This spec covers
building it.

## Goal

Given an official CIS Benchmark PDF (user-downloaded — see Licensing below),
produce a structured, complete JSON catalog of every recommendation in that
document: ID, title, scored/not-scored, profile level, description, rationale,
audit steps, remediation steps, references, and CIS Controls cross-references.

**This does not generate new automated checks.** A CIS Benchmark PDF describes
recommendations in prose; there is no way to derive working
`aws iam get-account-summary`-calling verification logic from that prose.
Automating a new check is still separate, hand-written work (tracked as the
"real API integrations" phase of this project's broader roadmap). What this
importer buys is an accurate, complete *catalog* — the foundation for an
honest "N of M official rules automated" coverage statistic in a later phase
(explicitly out of scope here — see "Out of scope" below).

## Non-goals / out of scope for this spec

- Cross-referencing imported rules against the existing hand-written checks
  to compute a coverage percentage, or surfacing that in reports. Separate
  future design.
- Parsing benchmarks other than CIS AWS Foundations v1.2.0 in the first
  implementation. The parser is built to generalize (see Architecture), but
  only the AWS pilot ships and is tested against a real file in this pass.
- Any form of automated fetching/downloading of CIS PDFs. CIS Benchmark PDFs
  require free account registration at cisecurity.org; the user downloads the
  file manually and hands the importer a local path.
- A GUI of any kind. This project is CLI-only, permanently, per explicit
  product direction from the project owner.

## Investigation findings (from inspecting a real CIS AWS Foundations
Benchmark v1.2.0 PDF, 158 pages, supplied by the project owner)

- `pdftotext -layout` (poppler-utils) produces clean, consistently-structured
  text. Confirmed by manual extraction and inspection during design.
- Every recommendation follows the template: header line
  `<N.N[.N]> <Title> (Scored|Not Scored)`, then labeled sections in order:
  `Profile Applicability:`, `Description:`, `Rationale:`, optionally
  `Impact:`, then `Audit:`, `Remediation:`, `References:`, `CIS Controls:`,
  and occasionally `Default Value:` / `Additional Information:`.
- An "Appendix: Summary Table" near the end of the document lists every rule
  ID, title, and scored status in one clean, authoritative place — this is
  the anchor list the parser uses, rather than scanning the body blindly.
- **Real wrinkles found by testing extraction, not assumed:**
  - `pdftotext` inserts form-feed (`\f`) characters at page breaks, which can
    attach to the start of a rule-header line and break naive `^regex`
    line-start matching. Must be stripped before parsing.
  - Long titles wrap across two physical lines before `(Scored)`/
    `(Not Scored)` appears — a single-line regex misses the majority of
    rules. The importer must join wrapped header lines before matching.
  - The `CIS Controls:` section contains its own numbered cross-references
    (e.g. `4.5 Use Multifactor Authentication For All Administrative
    Access`) that are syntactically identical to a real rule header. A naive
    "any line starting with `N.N`" scan would misidentify these as new rule
    boundaries, corrupting the parse. Solved by using the Summary Table's
    authoritative rule ID list as anchors — the parser only looks for the
    *specific next expected* rule ID, never an arbitrary number.
  - This specific document is CIS AWS Foundations Benchmark **v1.2.0**
    (2018), not v1.5 as the README previously (incorrectly) stated.

## Licensing

CIS Benchmark PDFs carry CIS's own terms of use (linked on the document's
title page); redistribution rights were not verified as part of this design.
Two defaults follow from that, both already applied:

1. The raw PDF is never committed — `*.pdf` added to `.gitignore`.
2. The importer's generated JSON (which substantially reproduces CIS's
   copyrighted rule text) defaults to writing into a gitignored `imports/`
   directory at the project root, separate from the existing hand-maintained
   `benchmarks/*.json`. A user who has confirmed their own rights under CIS's
   terms can choose to commit it; the tool does not do so by default.

## Architecture

### CLI shape

`cis_benchmark/cli.py` moves from a single flat argparse parser to
subparsers:

- `cis scan [--cloud ...] [--domain ...] [--workers ...] [--output ...] [--plain]`
  — today's behavior, unchanged in every flag and output.
- `cis import <pdf-path> --cloud {aws,azure,gcp,workspace} [--output <path>]`
  — new. Only `aws` is implemented in this pass; the other three choices
  exist in `--cloud`'s choices for forward compatibility but raise a clear
  "not yet implemented" `ImporterError` rather than silently doing nothing.
- Bare `cis --cloud aws ...` (no subcommand) continues to work exactly as
  today by defaulting to `scan` when the first argument isn't a recognized
  subcommand name — every existing test, script, and documented command
  keeps working unchanged.

### New package: `cis_benchmark/importer/`

- **`pdf_extract.py`** — `extract_text(pdf_path: str) -> str`. Shells out to
  `pdftotext -layout <pdf_path> -` via `subprocess`, strips form-feed
  characters from the output. Raises `ImporterError` with an actionable
  message (naming the exact install command for the current platform) if
  `pdftotext` is not on `PATH` — this is a build-time/runtime dependency only
  for `cis import`, not for `cis scan`, and must fail loud and specific, not
  silently.
- **`aws_parser.py`** — `parse(text: str) -> BenchmarkCatalog`. Implements
  the two-pass strategy from Investigation findings: (1) locate and parse the
  Appendix Summary Table into the authoritative ordered
  `(rule_id, title, scored)` list, cross-checked against the Table of
  Contents' rule count as a sanity check (mismatch is a hard error, not a
  warning — it means the document's structure differs from what this parser
  assumes, and guessing further would risk generating confidently-wrong
  output for a CIS security compliance tool); (2) carve the "Recommendations"
  body into per-rule blocks using each authoritative rule_id as the start
  anchor and the next one as the end anchor; (3) within each block, split on
  the fixed section labels, keeping only sections actually present.
- **`schema.py`** — `@dataclass ImportedRule` (id, title, scored: bool,
  profile_level: str, section: str, description: str, rationale: str,
  impact: str | None, audit: str, remediation: str, references: list[str],
  cis_controls: str) and `@dataclass BenchmarkCatalog` (benchmark_name,
  benchmark_version, source_filename, extracted_at, rules: list[ImportedRule])
  with `to_json()` / a `write(path)` helper.
- **`errors.py`** — `class ImporterError(Exception)`, used for every expected
  failure mode (missing `pdftotext`, rule-count mismatch, unimplemented cloud)
  so `cli.py` can catch it and print a clean message instead of a traceback.

### Validation, not silent garbage

After parsing: (a) the Summary-Table-derived count must match the number of
blocks actually carved from the body — mismatch is a hard `ImporterError`;
(b) each block must contain at minimum `Description:`, `Rationale:`, and
`Remediation:` — a block missing any of these is still written to the output
JSON (marked with an `incomplete: true` flag and which sections were
missing) rather than silently dropped or silently treated as complete. The
CLI prints a summary at the end: "Parsed 49/49 rules (0 incomplete)" or
similar, so the user can trust the count before using the output.

## Testing

Real CIS PDF content cannot be committed to the repo (Licensing, above), so
`tests/test_importer/` uses a small **synthetic fixture** — a hand-written
text blob in the test file itself, built to deliberately include the exact
wrinkles found during investigation:

- A rule with a title that wraps across two lines before `(Scored)`.
- A `CIS Controls:` section containing a numbered cross-reference that must
  **not** be parsed as a new rule.
- A form-feed character landing mid-line at a simulated page break.
- One deliberately-truncated rule block (missing `Remediation:`) to verify
  the `incomplete: true` flagging path.
- A deliberate Summary-Table/body count mismatch in a second fixture, to
  verify the hard-error path.

This tests the parsing *logic* against known, controlled inputs — not a copy
of CIS's content. Additionally, during implementation (not as an automated
test, and not committed), the parser will be run against the real file the
project owner supplied, to confirm it handles the actual document correctly
end-to-end — the same manual validation already done by hand during this
design.

`pdf_extract.py`'s `pdftotext` dependency check is tested by mocking
`shutil.which`/`subprocess.run`, not by requiring poppler in CI.

## Rollout

1. `cis_benchmark/importer/` package + CLI subparser restructure.
2. `cis import <pdf> --cloud aws` fully working, tested against the synthetic
   fixtures and manually verified against the real AWS PDF.
3. README updated: new `cis import` usage section, `pdftotext`/poppler as a
   documented prerequisite for that subcommand only, and the AWS benchmark
   version corrected from the incorrect "v1.5" to "v1.2.0" (as verified from
   the actual document).
4. Azure/GCP/Workspace parsers are explicitly future work — `--cloud` accepts
   the values but returns a clear "not yet implemented" error, so the CLI's
   `--help` output is honest about what's supported today.
