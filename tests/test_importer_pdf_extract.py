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


def test_strips_page_footer_lines():
    fake_result = MagicMock(
        returncode=0,
        stdout="Some content\n35 | P a g e\nMore content\n4|Page\nEnd\n",
        stderr="",
    )
    with patch("cis_benchmark.importer.pdf_extract.shutil.which", return_value="/usr/bin/pdftotext"), \
         patch("cis_benchmark.importer.pdf_extract.subprocess.run", return_value=fake_result):
        text = extract_text("doc.pdf")
    assert "P a g e" not in text
    assert "4|Page" not in text
    assert "Some content" in text
    assert "More content" in text
    assert "End" in text


def test_strips_private_use_area_glyphs():
    # U+F06F and U+F0B7 are Private Use Area characters used as
    # checkbox/bullet glyphs by the real PDF's embedded fonts.
    glyph_1 = chr(0xF06F)
    glyph_2 = chr(0xF0B7)
    fake_result = MagicMock(
        returncode=0,
        stdout=f"Title with {glyph_1} glyph and {glyph_2} bullet\n",
        stderr="",
    )
    with patch("cis_benchmark.importer.pdf_extract.shutil.which", return_value="/usr/bin/pdftotext"), \
         patch("cis_benchmark.importer.pdf_extract.subprocess.run", return_value=fake_result):
        text = extract_text("doc.pdf")
    assert glyph_1 not in text
    assert glyph_2 not in text
    assert "Title with" in text
    assert "glyph and" in text
