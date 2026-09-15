import re
import shutil
import subprocess

from .errors import ImporterError

_INSTALL_HINT = (
    "pdftotext (from poppler-utils) is required for `cis import` but was not "
    "found on PATH.\nInstall it with:\n"
    "  macOS:         brew install poppler\n"
    "  Debian/Ubuntu: sudo apt-get install poppler-utils\n"
)

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
# Unicode Private Use Area glyphs (checkbox/bullet symbols from the PDF's
# embedded fonts, e.g. U+F06F, U+F0B7) that pdftotext emits as raw codepoints
# scattered inline in titles and body text.
_PUA_GLYPH_RE = re.compile(r"[-]")
# A Summary Table "Set Correctly / Yes No" checkbox-column artifact some
# benchmarks render as a literal pair of "o" characters (not a PUA glyph)
# trailing the row's title/classification text at a fixed column position —
# corrupts titles when the row wraps across lines. The gap before the
# first "o" varies with how much preceding text shares that line (just 1
# space when the text runs right up to the checkbox column); the gap
# between the two "o"s is the reliable signal, always 2+ spaces (the
# fixed column width) — confirmed against every real PDF on disk, with
# zero matches outside the two real AWS documents that actually have this
# rendering quirk.
_CHECKBOX_ARTIFACT_RE = re.compile(r"\s+o\s{2,}o\s*$", re.MULTILINE)


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

    text = result.stdout.replace("\x0c", "")
    text = _PAGE_FOOTER_RE.sub("", text)
    text = _PAGE_NUMBER_FOOTER_RE.sub("", text)
    text = _WATERMARK_RE.sub("", text)
    text = _CHECKBOX_ARTIFACT_RE.sub("", text)
    text = _PUA_GLYPH_RE.sub("", text)
    return text
