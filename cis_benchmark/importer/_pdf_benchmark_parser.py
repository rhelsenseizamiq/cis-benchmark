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
_VERSION_RE = re.compile(r"[vV](\d+(?:\.\d+)+)\s*-\s*[\d-]+")
_L_TAG_RE = re.compile(r"^\(L\d\)\s*")
_RECOMMENDATIONS_HEADING_RE = re.compile(r"\n[ \t]*Recommendations[ \t]*\n")

# How many leading words of a rule's title to require when anchoring that
# rule's body header line (see _rule_header_pattern below). A prefix, not
# the whole title, because the exact wrapping of a long title in the PDF's
# extracted body text isn't guaranteed to match the Summary Table's own
# joined/re-wrapped version verbatim — but a handful of leading words is
# enough to distinguish a genuine header from a same-numbered row nested
# inside an earlier rule's "CIS Controls:" cross-reference table.
_TITLE_ANCHOR_WORDS = 5

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
    appendix_marker_fallbacks: List[str] = field(default_factory=list)
    classification_words: List[str] = field(default_factory=lambda: ["Scored", "Not Scored"])
    known_versions: List[str] = field(default_factory=list)


def _find_marker(text: str, config: "BenchmarkParserConfig", start_pos: int = 0, last: bool = False) -> Tuple[int, str]:
    """Locates the Summary Table appendix heading, trying config.appendix_marker
    first and falling back to config.appendix_marker_fallbacks in order.
    Some clouds changed this heading's exact wording between benchmark
    generations (e.g. Azure/GCP's older "Appendix: Recommendation
    Summary\\nTable" vs. newer "Appendix: Summary Table") — trying known
    alternates keeps older real documents parseable too, without the
    engine ever guessing which format a given document uses.

    last=True searches for the LAST occurrence (needed for the
    TOC-collision-safe Summary Table search — the real section is always
    the last occurrence, never the first); last=False (the default)
    searches forward from start_pos for the first occurrence.

    Returns (index, matched_marker) — the caller needs matched_marker's
    own length/text, not just where it was found.
    """
    candidates = [config.appendix_marker, *config.appendix_marker_fallbacks]
    for marker in candidates:
        idx = text.rfind(marker) if last else text.find(marker, start_pos)
        if idx != -1:
            return idx, marker
    raise ImporterError(
        f"Could not locate any of {candidates!r} in the extracted text — "
        "this document's structure doesn't match what this parser expects."
    )


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
    start, matched_marker = _find_marker(text, config, last=True)
    end = text.find("Appendix:", start + len(matched_marker))
    if end == -1:
        end = len(text)
    table_text = text[start:end]

    anchors = []
    current_section = ""
    pending_id = None
    pending_lines = []
    pending_indent = None

    def flush():
        nonlocal pending_id, pending_lines, pending_indent
        if pending_id is not None:
            joined = " ".join(l.strip() for l in pending_lines if l.strip())
            joined = _L_TAG_RE.sub("", joined.strip())
            m = class_re.search(joined)
            classification = m.group(1) if m else None
            title = joined[:m.start()].strip() if m else joined.strip()
            anchors.append((pending_id, current_section, title, classification))
        pending_id = None
        pending_lines = []
        pending_indent = None

    for line in table_text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        indent = len(line) - len(line.lstrip(" \t"))

        # A candidate rule-ID/section-ID match is only treated as the
        # start of a genuine new row if it's no more indented than the
        # row currently being accumulated — a more deeply indented line
        # matching the same digit pattern is title continuation text
        # that happens to start with a number (e.g. a real wrapped
        # "...minimum length of\n14 or greater (Automated)", where "14"
        # alone matches the same bare-digit pattern a genuine top-level
        # section id like "2" does). Every genuine ID line sits at one
        # fixed left-margin indent column; every continuation line sits
        # deeper — confirmed on the real AWS v7.0.0 document.
        is_continuation_depth = pending_id is not None and indent > pending_indent

        if not is_continuation_depth:
            rule_m = _RULE_ID_RE.match(line)
            if rule_m:
                flush()
                pending_id = rule_m.group(1)
                pending_indent = indent
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


def _rule_header_pattern(rule_id: str, words: List[str]) -> "re.Pattern":
    """Builds a regex requiring `rule_id` at (optionally indented)
    line-start, followed by an optional "(L1)"/"(L2)" tag and then
    `words` (a prefix of the rule's own title, already split on
    whitespace) — or, if `words` is empty, just the ID.
    """
    tag = r"(?:\(L\d\)\s*)?"
    if words:
        title_prefix = r"\s+".join(re.escape(w) for w in words)
        return re.compile(
            rf"^[ \t]*{re.escape(rule_id)}\s+{tag}{title_prefix}", re.MULTILINE
        )
    return re.compile(rf"^[ \t]*{re.escape(rule_id)}\s", re.MULTILINE)


def _find_rule_header(body: str, pos: int, rule_id: str, title: str) -> Optional["re.Match"]:
    """Searches `body` (from `pos` onward) for this specific rule's
    genuine header line — not a coincidentally same-numbered row inside
    some earlier rule's "CIS Controls:" cross-reference table.

    Requiring only the rule ID at (optionally indented) line-start isn't
    enough: a benchmark's "CIS Controls:" section lists numbered safeguard
    cross-references (e.g. "5.1 Establish and Maintain an Inventory of
    Accounts") that are indented *more* deeply than a genuine rule header,
    and when a safeguard number happens to equal a later real rule's ID, a
    bare ID-plus-whitespace match binds to that table row instead of
    waiting for the real header. The Summary Table already gives us each
    rule's correct title, so require the ID to be followed by (an optional
    tag, then) a prefix of its own title — a coincidental table row's
    trailing text won't match that.

    Tries the longest available title prefix (up to `_TITLE_ANCHOR_WORDS`
    words) first, since that's the strongest discriminator, and only
    relaxes to fewer words — down to a bare ID match as a last resort —
    when no match exists with the stronger prefix anywhere in the
    remaining body. This matters because the Summary Table's own
    row-joining can occasionally trail extra, non-title text onto a
    row (confirmed on the real Workspace PDF for a handful of
    page-break-adjacent grouping headers); without this fallback, a
    genuine rule/grouping-header would go unmatched entirely just because
    its recorded title has a few trailing corrupted words.
    """
    all_words = title.split()
    for n in range(min(_TITLE_ANCHOR_WORDS, len(all_words)), 0, -1):
        m = _rule_header_pattern(rule_id, all_words[:n]).search(body, pos)
        if m:
            return m
    return _rule_header_pattern(rule_id, []).search(body, pos)


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
    _, matched_marker = _find_marker(text, config, last=True)
    body_end = text.find(matched_marker, body_start)
    if body_end == -1:
        body_end = len(text)
    body = text[body_start:body_end]

    rules = []
    missing_ids = []
    cursor = 0
    for i, (rule_id, section, title, classification) in enumerate(anchors):
        m = _find_rule_header(body, cursor, rule_id, title)
        if not m:
            missing_ids.append(rule_id)
            continue

        next_start = len(body)
        for next_id, _next_section, next_title, *_rest in anchors[i + 1:]:
            next_m = _find_rule_header(body, m.end(), next_id, next_title)
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
