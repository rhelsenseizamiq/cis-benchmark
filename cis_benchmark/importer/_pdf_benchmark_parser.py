import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from .errors import ImporterError
from .schema import BenchmarkCatalog, ImportedRule, now_iso

# pdftotext -layout preserves each source PDF's own left margin, which
# some benchmarks render as a consistent run of leading spaces before
# every body line, summary-table row, and section label. All line-start
# anchors below tolerate that optional horizontal whitespace so parsing
# doesn't depend on a given PDF happening to have zero left margin.
_RULE_ID_RE = re.compile(r"^[ \t]*(\d+(?:\.\d+)+)\s")
_SECTION_ID_RE = re.compile(r"^[ \t]*(\d+)\s+(.+)$")
_VERSION_RE = re.compile(r"v(\d+(?:\.\d+)+)\s*-\s*[\d-]+")
_L_TAG_RE = re.compile(r"^\(L\d\)\s*")
_RECOMMENDATIONS_HEADING_RE = re.compile(r"\n[ \t]*Recommendations[ \t]*\n")

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
    classification_words: List[str] = field(default_factory=lambda: ["Scored", "Not Scored"])
    known_versions: List[str] = field(default_factory=list)


def _find_last_index(text: str, marker: str) -> int:
    """Finds the LAST occurrence of marker in text. Needed for markers that
    also appear earlier in the document's own Table of Contents as a
    dot-leader entry — the real section is always the last occurrence,
    never the first.
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
    end = text.find("Appendix:", start + len(config.appendix_marker))
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
            joined = _L_TAG_RE.sub("", joined.strip())
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
            pending_lines = [line[rule_m.end():]]
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


_LABEL_RES = {label: re.compile(rf"\n[ \t]*{re.escape(label)}") for label in _LABELS}


def _split_block_into_sections(block: str) -> dict:
    """Splits one rule's raw text block on the fixed CIS section labels,
    keeping only the labels actually present in this block. Tolerates an
    optional left-margin indent before the label, same as the line-start
    anchors above.
    """
    positions = []
    for label in _LABELS:
        m = _LABEL_RES[label].search(block)
        if m:
            positions.append((m.start(), m.end(), label))
    positions.sort()

    sections = {}
    for i, (_start, end, label) in enumerate(positions):
        content_start = end
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
    # exact-line marker (which requires the line to contain nothing but the
    # word itself, modulo the left-margin indent tolerated by the regex).
    body_start_m = _RECOMMENDATIONS_HEADING_RE.search(text)
    if not body_start_m:
        raise ImporterError(
            "Could not locate the 'Recommendations' section heading in the "
            "extracted text — this document's structure doesn't match what "
            "this parser expects."
        )
    body_start = body_start_m.start()
    body_end = text.find(config.appendix_marker, body_start)
    if body_end == -1:
        body_end = len(text)
    body = text[body_start:body_end]

    rules = []
    missing_ids = []
    cursor = 0
    for i, (rule_id, section, title, classification) in enumerate(anchors):
        pattern = re.compile(rf"^[ \t]*{re.escape(rule_id)}\s", re.MULTILINE)
        m = pattern.search(body, cursor)
        if not m:
            missing_ids.append(rule_id)
            continue

        next_start = len(body)
        for next_id, *_rest in anchors[i + 1:]:
            next_pattern = re.compile(rf"^[ \t]*{re.escape(next_id)}\s", re.MULTILINE)
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
