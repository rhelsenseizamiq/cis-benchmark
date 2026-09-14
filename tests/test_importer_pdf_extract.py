import subprocess
from unittest.mock import MagicMock, patch

import pytest

from cis_benchmark.importer.errors import ImporterError
from cis_benchmark.importer.pdf_extract import extract_text


def test_raises_clear_error_when_pdftotext_missing():
    with patch("cis_benchmark.importer.pdf_extract.shutil.which", return_value=None):
        with pytest.raises(ImporterError, match="poppler"):
            extract_text("whatever.pdf")


def test_raises_on_nonzero_exit():
    fake_result = MagicMock(returncode=1, stdout="", stderr="Syntax Error: bad PDF")
    with patch("cis_benchmark.importer.pdf_extract.shutil.which", return_value="/usr/bin/pdftotext"), \
         patch("cis_benchmark.importer.pdf_extract.subprocess.run", return_value=fake_result):
        with pytest.raises(ImporterError, match="Syntax Error"):
            extract_text("broken.pdf")


def test_raises_on_timeout():
    with patch("cis_benchmark.importer.pdf_extract.shutil.which", return_value="/usr/bin/pdftotext"), \
         patch("cis_benchmark.importer.pdf_extract.subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="pdftotext", timeout=60)):
        with pytest.raises(ImporterError, match="timed out"):
            extract_text("huge.pdf")


def test_strips_form_feed_characters():
    fake_result = MagicMock(returncode=0, stdout="1.1 Rule\n\x0cProfile Applicability:\n", stderr="")
    with patch("cis_benchmark.importer.pdf_extract.shutil.which", return_value="/usr/bin/pdftotext"), \
         patch("cis_benchmark.importer.pdf_extract.subprocess.run", return_value=fake_result) as mock_run:
        text = extract_text("clean.pdf")
    assert "\x0c" not in text
    assert "1.1 Rule\nProfile Applicability:\n" == text
    called_args = mock_run.call_args[0][0]
    assert called_args == ["pdftotext", "-layout", "clean.pdf", "-"]
