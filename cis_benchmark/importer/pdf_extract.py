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
# Unicode Private Use Area glyphs (checkbox/bullet symbols from the PDF's
# embedded fonts, e.g. U+F06F, U+F0B7) that pdftotext emits as raw codepoints
# scattered inline in titles and body text.
_PUA_GLYPH_RE = re.compile(r"[-]")


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
    text = _PUA_GLYPH_RE.sub("", text)
    return text
