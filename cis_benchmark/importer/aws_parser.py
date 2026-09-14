import re

from .errors import ImporterError
from .schema import BenchmarkCatalog, ImportedRule, now_iso

_RULE_ID_RE = re.compile(r"^(\d+(?:\.\d+){1,2})\s")
_SECTION_ID_RE = re.compile(r"^(\d+)\s+(.+)$")
_SCORED_RE = re.compile(r"\((Scored|Not Scored)\)")
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


def _find_last_index(text: str, marker: str) -> int:
    """Like _find_index, but returns the LAST occurrence. Needed for markers
    (like "Appendix: Summary Table") that also appear earlier in the
    document's own Table of Contents as a dot-leader entry — the real
    section is always the last occurrence, never the first.
    """
    idx = text.rfind(marker)
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
    start = _find_last_index(text, "Appendix: Summary Table")
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
            m = _SCORED_RE.search(joined)
            scored = (m.group(1) == "Scored") if m else None
            title = joined[:m.start()].strip() if m else joined.strip()
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


def parse(text: str, source_filename: str = "") -> BenchmarkCatalog:
    """Parses CIS AWS Foundations Benchmark text (already extracted and
    form-feed-stripped by pdf_extract.extract_text) into a BenchmarkCatalog.
    """
    version_m = _VERSION_RE.search(text)
    benchmark_version = version_m.group(1) if version_m else "unknown"

    anchors = _parse_summary_table(text)

    # Unlike "Appendix: Summary Table", this marker is safe with the first
    # occurrence: the TOC's own "Recommendations" entry always has trailing
    # dot-leaders/a page number on the same line, so it never matches this
    # exact-line marker (which requires an immediate newline after the word).
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
        if scored is None:
            missing.append("scored status (could not parse from Summary Table)")

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

        # Convert AWS-specific scored boolean to classification string
        if scored is True:
            classification = "Scored"
        elif scored is False:
            classification = "Not Scored"
        else:
            classification = "Unknown"

        rules.append(ImportedRule(
            id=rule_id,
            title=title,
            classification=classification,
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
