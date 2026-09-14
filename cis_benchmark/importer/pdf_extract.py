import shutil
import subprocess

from .errors import ImporterError

_INSTALL_HINT = (
    "pdftotext (from poppler-utils) is required for `cis import` but was not "
    "found on PATH.\nInstall it with:\n"
    "  macOS:         brew install poppler\n"
    "  Debian/Ubuntu: sudo apt-get install poppler-utils\n"
)


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

    return result.stdout.replace("\x0c", "")
