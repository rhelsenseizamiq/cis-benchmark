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


def test_strips_bare_page_number_footer_lines():
    fake_result = MagicMock(
        returncode=0,
        stdout="Some content\n                    Page 1\nMore content\n              Page 42\nEnd\n",
        stderr="",
    )
    with patch("cis_benchmark.importer.pdf_extract.shutil.which", return_value="/usr/bin/pdftotext"), \
         patch("cis_benchmark.importer.pdf_extract.subprocess.run", return_value=fake_result):
        text = extract_text("doc.pdf")
    assert "Page 1" not in text
    assert "Page 42" not in text
    assert "Some content" in text
    assert "More content" in text
    assert "End" in text


def test_page_number_footer_regex_does_not_strip_lines_with_extra_content():
    fake_result = MagicMock(
        returncode=0,
        stdout="See Page 1 for details\n",
        stderr="",
    )
    with patch("cis_benchmark.importer.pdf_extract.shutil.which", return_value="/usr/bin/pdftotext"), \
         patch("cis_benchmark.importer.pdf_extract.subprocess.run", return_value=fake_result):
        text = extract_text("doc.pdf")
    assert "See Page 1 for details" in text


def test_strips_confidentiality_watermark_lines():
    fake_result = MagicMock(
        returncode=0,
        stdout="Audit:\n\nCheck the setting.\n\nInternal Only - General\n\nRemediation:\n\nFix it.\n",
        stderr="",
    )
    with patch("cis_benchmark.importer.pdf_extract.shutil.which", return_value="/usr/bin/pdftotext"), \
         patch("cis_benchmark.importer.pdf_extract.subprocess.run", return_value=fake_result):
        text = extract_text("doc.pdf")
    assert "Internal Only - General" not in text
    assert "Check the setting." in text
    assert "Remediation:" in text


def test_strips_summary_table_checkbox_column_artifacts():
    fake_result = MagicMock(
        returncode=0,
        stdout=(
            "1.1       Ensure widgets are configured for the correct baseline        o       o\n"
            "                          (Manual)\n"
        ),
        stderr="",
    )
    with patch("cis_benchmark.importer.pdf_extract.shutil.which", return_value="/usr/bin/pdftotext"), \
         patch("cis_benchmark.importer.pdf_extract.subprocess.run", return_value=fake_result):
        text = extract_text("doc.pdf")
    assert "o       o" not in text
    assert "Ensure widgets are configured for the correct baseline" in text
    assert "(Manual)" in text


def test_strips_checkbox_artifact_with_only_one_space_before_first_o():
    # The gap before the first "o" varies with how much preceding text
    # shares that line — confirmed on a real document where the row's
    # text ran right up to the checkbox column, leaving only one space.
    fake_result = MagicMock(
        returncode=0,
        stdout="Ensure no security groups allow ingress from 0.0.0.0/0 to o        o\n",
        stderr="",
    )
    with patch("cis_benchmark.importer.pdf_extract.shutil.which", return_value="/usr/bin/pdftotext"), \
         patch("cis_benchmark.importer.pdf_extract.subprocess.run", return_value=fake_result):
        text = extract_text("doc.pdf")
    assert "o        o" not in text
    assert "Ensure no security groups allow ingress from 0.0.0.0/0 to" in text


def test_checkbox_artifact_regex_does_not_strip_a_lone_letter_o_in_prose():
    fake_result = MagicMock(
        returncode=0,
        stdout="Enable logging to detect anomalous activity, or investigate further.\n",
        stderr="",
    )
    with patch("cis_benchmark.importer.pdf_extract.shutil.which", return_value="/usr/bin/pdftotext"), \
         patch("cis_benchmark.importer.pdf_extract.subprocess.run", return_value=fake_result):
        text = extract_text("doc.pdf")
    assert text == "Enable logging to detect anomalous activity, or investigate further.\n"
