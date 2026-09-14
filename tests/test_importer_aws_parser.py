import pytest

from cis_benchmark.importer.errors import ImporterError
from cis_benchmark.importer.aws_parser import parse

# A synthetic "mini benchmark" built to exercise the exact structural
# wrinkles found by inspecting a real CIS AWS Foundations Benchmark PDF
# during design: a title that wraps across two lines before its
# (Scored)/(Not Scored) marker, a CIS Controls cross-reference number
# ("9.9 Require A Second...") that must NOT be mistaken for a new rule,
# and one deliberately-incomplete rule (missing Remediation:) to exercise
# the incomplete-flagging path. No real CIS content — see spec Licensing.
FIXTURE_HAPPY_PATH = '''CIS Amazon Web Services Foundations
Benchmark
v9.9.9 - 01-01-2099
Terms of Use
Please see the below link for our current terms of use:
https://example.invalid/terms

Table of Contents

Recommendations
1 Identity and Access Management
1.1 Avoid using the primary administrative account for routine operations (Scored)
Profile Applicability:

 Level 1

Description:

Do not use the root account for daily tasks.

Rationale:

The root account has unrestricted access to everything.

Audit:

Run the following command:

  aws iam get-account-summary

Remediation:

Stop using the root account for daily tasks.

References:

   1. CCE-00000-0

CIS Controls:

9.9 Require A Second Authentication Factor For Privileged Accounts
Use multi-factor authentication for all administrative account access.

1.2 Ensure a secondary verification factor is required for every user account that can
sign in through the web console (Scored)
Profile Applicability:

 Level 1

Description:

MFA adds an extra layer of protection on top of a password.

Rationale:

Enabling MFA provides increased security for console access.

Audit:

Run the following command:

  aws iam list-mfa-devices

Remediation:

Enable MFA for all IAM users with a console password.

References:

   1. CCE-00000-1

CIS Controls:

9.9 Require A Second Authentication Factor For Privileged Accounts
Use multi-factor authentication for all administrative account access.

1.3 Ensure this rule is intentionally left incomplete (Not Scored)
Profile Applicability:

 Level 2

Description:

This rule intentionally omits a Remediation section so the importer's
incomplete-flagging path can be tested.

Rationale:

Testing matters.

Audit:

Run the following command:

  aws iam get-account-summary

References:

   1. CCE-00000-2

Appendix: Summary Table
                         Control                                             Set
                                                                          Correctly
                                                                          Yes No
1      Identity and Access Management
1.1    Avoid using the primary administrative account for routine operations (Scored)
1.2    Ensure a secondary verification factor is required for every user
       account that can sign in through the web console (Scored)
1.3    Ensure this rule is intentionally left incomplete (Not Scored)

Appendix: Change History
Nothing to see here.
'''

# Summary Table lists rule 1.2 but the body never actually contains it —
# exercises the hard-error path (a rule the parser can't locate at all,
# as opposed to one it locates but finds incomplete).
FIXTURE_MISSING_RULE = '''CIS Amazon Web Services Foundations
Benchmark
v9.9.9 - 01-01-2099

Table of Contents

Recommendations
1 Identity and Access Management
1.1 Avoid using the primary administrative account for routine operations (Scored)
Profile Applicability:

 Level 1

Description:

Do not use the root account for daily tasks.

Rationale:

The root account has unrestricted access to everything.

Audit:

Run the following command:

  aws iam get-account-summary

Remediation:

Stop using the root account for daily tasks.

References:

   1. CCE-00000-0

Appendix: Summary Table
1      Identity and Access Management
1.1    Avoid using the primary administrative account for routine operations (Scored)
1.2    This rule is listed in the summary table but never appears in the body (Scored)

Appendix: Change History
Nothing to see here.
'''


def test_parses_all_rules_with_correct_ids_and_order():
    catalog = parse(FIXTURE_HAPPY_PATH, source_filename="fixture.pdf")
    assert [r.id for r in catalog.rules] == ["1.1", "1.2", "1.3"]


def test_extracts_benchmark_version_from_title_page():
    catalog = parse(FIXTURE_HAPPY_PATH)
    assert catalog.benchmark_version == "9.9.9"
    assert catalog.benchmark_name == "CIS Amazon Web Services Foundations Benchmark"


def test_wrapped_title_is_joined_correctly():
    catalog = parse(FIXTURE_HAPPY_PATH)
    rule_1_2 = next(r for r in catalog.rules if r.id == "1.2")
    assert rule_1_2.title == (
        "Ensure a secondary verification factor is required for every "
        "user account that can sign in through the web console"
    )
    assert rule_1_2.scored is True


def test_cis_controls_cross_reference_is_not_mistaken_for_a_new_rule():
    catalog = parse(FIXTURE_HAPPY_PATH)
    # There must be exactly 3 rules — a broken parser would produce a
    # phantom "9.9" rule from the CIS Controls cross-reference text.
    assert len(catalog.rules) == 3
    assert "9.9" not in [r.id for r in catalog.rules]
    rule_1_1 = next(r for r in catalog.rules if r.id == "1.1")
    assert "9.9 Require A Second Authentication Factor" in rule_1_1.cis_controls


def test_fields_extracted_correctly_for_a_complete_rule():
    catalog = parse(FIXTURE_HAPPY_PATH)
    rule = next(r for r in catalog.rules if r.id == "1.1")
    assert rule.description == "Do not use the root account for daily tasks."
    assert rule.rationale == "The root account has unrestricted access to everything."
    assert rule.audit.startswith("Run the following command:")
    assert rule.remediation == "Stop using the root account for daily tasks."
    assert rule.references == ["CCE-00000-0"]
    assert rule.profile_level == "Level 1"
    assert rule.section == "1. Identity and Access Management"
    assert rule.incomplete is False
    assert rule.missing_sections == []


def test_incomplete_rule_is_flagged_not_dropped():
    catalog = parse(FIXTURE_HAPPY_PATH)
    rule = next(r for r in catalog.rules if r.id == "1.3")
    assert rule.incomplete is True
    assert "Remediation:" in rule.missing_sections
    assert rule.description  # still captured, just missing one section
    assert rule.profile_level == "Level 2"
    assert rule.scored is False


def test_missing_rule_in_body_raises_importer_error():
    with pytest.raises(ImporterError, match="1.2"):
        parse(FIXTURE_MISSING_RULE)


def test_empty_summary_table_raises_importer_error():
    with pytest.raises(ImporterError):
        parse("Recommendations\n\nAppendix: Summary Table\n\nAppendix: Change History\n")


# Fixture where "Appendix: Summary Table" appears twice: once as a fake TOC
# dot-leader entry (early, with trailing dots and page number like ". . 152"),
# and once as the real section near the end (the actual summary table data).
# This reproduces the exact bug that would occur with .find() — it would
# match the first (TOC) occurrence instead of the last (real) one.
FIXTURE_WITH_TOC_COLLISION = (
    "CIS Amazon Web Services Foundations\nBenchmark\nv9.9.9 - 01-01-2099\n\n"
    "Table of Contents\n\n"
    "Recommendations .......................................................... 9\n"
    "Appendix: Summary Table .......................................................... 152\n"
    "Appendix: Change History .......................................................... 155\n\n"
) + FIXTURE_HAPPY_PATH


def test_toc_dot_leader_mention_of_summary_table_is_not_mistaken_for_the_real_section():
    """Regression test for the rfind() fix. When "Appendix: Summary Table"
    appears both in the Table of Contents (early, as a dot-leader entry)
    and as the real section (late), parse() must use the LAST occurrence
    to find the actual table, not the first. If it used .find() instead of
    .rfind(), it would match the TOC entry, extract a tiny slice with zero
    rules, and raise "found zero recommendations in it".
    """
    catalog = parse(FIXTURE_WITH_TOC_COLLISION)
    assert [r.id for r in catalog.rules] == ["1.1", "1.2", "1.3"]


def test_trailing_glyph_after_scored_marker_does_not_break_detection():
    """Regression test for PDF checkbox-glyph artifacts trailing the (Scored)
    marker. These glyphs (Private Use Area Unicode chars like U+F06F) break
    end-anchored regexes, so the parser must find the marker anywhere and
    take everything before it as the title. This test includes a U+F06F
    character (Private Use Area) after (Scored) in the Summary Table
    to simulate the real PDF artifact.
    """
    # U+F06F is a Private Use Area character used in PDF form glyphs
    glyph = chr(0xF06F)
    text = f'''CIS Amazon Web Services Foundations
Benchmark
v9.9.9 - 01-01-2099

Table of Contents

Recommendations
1 Identity and Access Management
1.1 Ensure a control has trailing PDF artifacts after its marker (Scored)
Profile Applicability:

 Level 1

Description:

Testing trailing artifact handling.

Rationale:

Testing matters.

Audit:

Run the following command:

  aws iam get-account-summary

Remediation:

Fix it.

Appendix: Summary Table
1      Identity and Access Management
1.1    Ensure a control has trailing PDF artifacts after its marker (Scored){glyph}

Appendix: Change History
Nothing to see here.
'''
    catalog = parse(text)
    rule = catalog.rules[0]
    assert rule.title == "Ensure a control has trailing PDF artifacts after its marker"
    assert rule.scored is True
    assert "(Scored)" not in rule.title


# Regression fixture for the Critical section-detection bug: a section
# heading line (no decimal point, e.g. "2 Logging and Monitoring") that
# appears between rule blocks — i.e. right after the previous rule's own
# Summary Table row, before that row has been flushed — must still update
# current_section. Covers 3 distinct top-level sections, each with 1-2
# rules, present in both the body and the Summary Table.
FIXTURE_MULTI_SECTION = '''CIS Amazon Web Services Foundations
Benchmark
v9.9.9 - 01-01-2099

Table of Contents

Recommendations
1 Identity and Access Management
1.1 Ensure account root access keys are removed (Scored)
Description:

Root access keys should not exist.

Rationale:

Root has unrestricted access.

Remediation:

Remove root access keys.

1.2 Ensure IAM policies are attached only to groups or roles (Scored)
Description:

Policies should not be attached directly to users.

Rationale:

Grouping eases permission management.

Remediation:

Detach direct user policies.

2 Logging and Monitoring
2.1 Ensure CloudTrail is enabled in all regions (Scored)
Description:

CloudTrail should be enabled across all regions.

Rationale:

Centralized logging aids incident response.

Remediation:

Enable CloudTrail in all regions.

3 Networking
3.1 Ensure no security group allows ingress from 0.0.0.0/0 to port 22 (Scored)
Description:

Security groups should restrict SSH ingress.

Rationale:

Open SSH exposes hosts to brute force attacks.

Remediation:

Restrict port 22 ingress to known ranges.

3.2 Ensure VPC flow logging is enabled in all VPCs (Scored)
Description:

Flow logs capture network traffic metadata.

Rationale:

Flow logs aid network forensics.

Remediation:

Enable flow logging for every VPC.

Appendix: Summary Table
                         Control                                             Set
                                                                          Correctly
                                                                          Yes No
1      Identity and Access Management
1.1    Ensure account root access keys are removed (Scored)
1.2    Ensure IAM policies are attached only to groups or roles (Scored)
2      Logging and Monitoring
2.1    Ensure CloudTrail is enabled in all regions (Scored)
3      Networking
3.1    Ensure no security group allows ingress from 0.0.0.0/0 to port 22 (Scored)
3.2    Ensure VPC flow logging is enabled in all VPCs (Scored)

Appendix: Change History
Nothing to see here.
'''


def test_section_updates_correctly_between_rule_blocks_in_summary_table():
    """Regression test for the Critical section-misassignment bug: a section
    heading with no decimal point (e.g. "2 Logging and Monitoring") that
    appears in the Summary Table right after the previous rule's row — while
    that row's pending_id is still set, i.e. before flush() runs — must
    still update current_section. Before the fix, the `pending_id is None`
    gate silently skipped section detection in exactly this situation, and
    every rule after the first section's rules was mislabeled with section 1.
    """
    catalog = parse(FIXTURE_MULTI_SECTION, source_filename="fixture.pdf")
    sections_by_id = {r.id: r.section for r in catalog.rules}
    assert sections_by_id["1.1"] == "1. Identity and Access Management"
    assert sections_by_id["1.2"] == "1. Identity and Access Management"
    assert sections_by_id["2.1"] == "2. Logging and Monitoring"
    assert sections_by_id["3.1"] == "3. Networking"
    assert sections_by_id["3.2"] == "3. Networking"
    # Distinct sections must actually be distinct — a broken parser would
    # collapse all of these into "1. Identity and Access Management".
    assert len(set(sections_by_id.values())) == 3


def test_unparseable_scored_marker_is_flagged_incomplete_not_silently_false():
    """Regression test for genuinely unparseable scored markers (glyphs
    injected inside "Not Scored" itself). When the marker cannot be matched,
    scored remains None (not silently False), and the rule is flagged
    incomplete with an explicit missing_sections entry. This simulates glyphs
    injected inside the marker like "(Not<glyph>Scored)" by using a marker
    that the regex cannot parse: "(Not X Scored)" where X breaks the literal
    string match.
    """
    text = '''CIS Amazon Web Services Foundations
Benchmark
v9.9.9 - 01-01-2099

Table of Contents

Recommendations
1 Identity and Access Management
1.1 Ensure a control has a marker with injected glyph

Profile Applicability:

 Level 1

Description:

Testing unparseable marker handling.

Rationale:

Testing matters.

Audit:

Run the following command:

  aws iam get-account-summary

Remediation:

Fix it.

Appendix: Summary Table
1      Identity and Access Management
1.1    Ensure a control has a marker with injected glyph (Not Scored)

Appendix: Change History
Nothing to see here.
'''
    # Create the text but modify the Summary Table entry to have a broken marker
    text_with_broken_marker = text.replace(
        "1.1    Ensure a control has a marker with injected glyph (Not Scored)",
        "1.1    Ensure a control has a marker with injected glyph (Not®Scored)"
    )
    catalog = parse(text_with_broken_marker)
    rule = catalog.rules[0]
    # scored is None internally, but coerced to False in ImportedRule
    assert rule.scored is False
    # But now it's flagged incomplete with an explicit message
    assert rule.incomplete is True
    assert any("scored status" in m for m in rule.missing_sections)
