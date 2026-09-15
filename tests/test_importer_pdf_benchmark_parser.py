import pytest

from cis_benchmark.importer.errors import ImporterError
from cis_benchmark.importer._pdf_benchmark_parser import BenchmarkParserConfig, parse_benchmark

_AWS_CONFIG = BenchmarkParserConfig(
    benchmark_name="CIS Test Benchmark",
    appendix_marker="Appendix: Summary Table",
    classification_words=["Scored", "Not Scored"],
    known_versions=["9.9.9"],
)

# A synthetic "mini benchmark" exercising every structural wrinkle found
# across the three real CIS PDFs inspected during design: a title that
# wraps across two lines before its classification marker, a CIS Controls
# cross-reference number that must NOT be mistaken for a new rule, and one
# deliberately-incomplete rule (missing Remediation:). No real CIS content.
FIXTURE_HAPPY_PATH = '''CIS Test Benchmark
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

  example iam get-account-summary

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

  example iam list-mfa-devices

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

  example iam get-account-summary

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


def test_parses_all_rules_with_correct_ids_and_order():
    catalog = parse_benchmark(FIXTURE_HAPPY_PATH, _AWS_CONFIG, source_filename="fixture.pdf")
    assert [r.id for r in catalog.rules] == ["1.1", "1.2", "1.3"]


def test_extracts_benchmark_version_and_uses_config_name():
    catalog = parse_benchmark(FIXTURE_HAPPY_PATH, _AWS_CONFIG)
    assert catalog.benchmark_version == "9.9.9"
    assert catalog.benchmark_name == "CIS Test Benchmark"


def test_version_verified_true_when_version_in_known_versions():
    catalog = parse_benchmark(FIXTURE_HAPPY_PATH, _AWS_CONFIG)
    assert catalog.version_verified is True


def test_version_verified_false_when_version_not_in_known_versions():
    config = BenchmarkParserConfig(
        benchmark_name="CIS Test Benchmark",
        appendix_marker="Appendix: Summary Table",
        classification_words=["Scored", "Not Scored"],
        known_versions=["1.0.0"],  # deliberately does not match "9.9.9"
    )
    catalog = parse_benchmark(FIXTURE_HAPPY_PATH, config)
    assert catalog.version_verified is False


def test_wrapped_title_is_joined_correctly():
    catalog = parse_benchmark(FIXTURE_HAPPY_PATH, _AWS_CONFIG)
    rule_1_2 = next(r for r in catalog.rules if r.id == "1.2")
    assert rule_1_2.title == (
        "Ensure a secondary verification factor is required for every "
        "user account that can sign in through the web console"
    )
    assert rule_1_2.classification == "Scored"


def test_cis_controls_cross_reference_is_not_mistaken_for_a_new_rule():
    catalog = parse_benchmark(FIXTURE_HAPPY_PATH, _AWS_CONFIG)
    assert len(catalog.rules) == 3
    assert "9.9" not in [r.id for r in catalog.rules]
    rule_1_1 = next(r for r in catalog.rules if r.id == "1.1")
    assert "9.9 Require A Second Authentication Factor" in rule_1_1.cis_controls


def test_fields_extracted_correctly_for_a_complete_rule():
    catalog = parse_benchmark(FIXTURE_HAPPY_PATH, _AWS_CONFIG)
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
    catalog = parse_benchmark(FIXTURE_HAPPY_PATH, _AWS_CONFIG)
    rule = next(r for r in catalog.rules if r.id == "1.3")
    assert rule.incomplete is True
    assert "Remediation:" in rule.missing_sections
    assert rule.description
    assert rule.profile_level == "Level 2"
    assert rule.classification == "Not Scored"


FIXTURE_MISSING_RULE = '''CIS Test Benchmark
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

  example iam get-account-summary

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


def test_missing_rule_in_body_raises_importer_error():
    with pytest.raises(ImporterError, match="1.2"):
        parse_benchmark(FIXTURE_MISSING_RULE, _AWS_CONFIG)


def test_empty_summary_table_raises_importer_error():
    with pytest.raises(ImporterError):
        parse_benchmark("Recommendations\n\nAppendix: Summary Table\n\nAppendix: Change History\n", _AWS_CONFIG)


FIXTURE_WITH_TOC_COLLISION = (
    "CIS Test Benchmark\nv9.9.9 - 01-01-2099\n\n"
    "Table of Contents\n\n"
    "Recommendations .......................................................... 9\n"
    "Appendix: Summary Table .......................................................... 152\n"
    "Appendix: Change History .......................................................... 155\n\n"
) + FIXTURE_HAPPY_PATH


def test_toc_dot_leader_mention_of_appendix_marker_is_not_mistaken_for_the_real_section():
    """When the appendix marker appears both in the TOC (early, dot-leader
    entry) and as the real section (late), the parser must use the LAST
    occurrence. If it used .find() instead of .rfind(), it would match the
    TOC entry and extract a slice with zero rows.
    """
    catalog = parse_benchmark(FIXTURE_WITH_TOC_COLLISION, _AWS_CONFIG)
    assert [r.id for r in catalog.rules] == ["1.1", "1.2", "1.3"]


def test_trailing_glyph_after_classification_marker_does_not_break_detection():
    glyph = chr(0xF06F)
    text = f'''CIS Test Benchmark
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

  example iam get-account-summary

Remediation:

Fix it.

Appendix: Summary Table
1      Identity and Access Management
1.1    Ensure a control has trailing PDF artifacts after its marker (Scored){glyph}

Appendix: Change History
Nothing to see here.
'''
    catalog = parse_benchmark(text, _AWS_CONFIG)
    rule = catalog.rules[0]
    assert rule.title == "Ensure a control has trailing PDF artifacts after its marker"
    assert rule.classification == "Scored"
    assert "(Scored)" not in rule.title


FIXTURE_MULTI_SECTION = '''CIS Test Benchmark
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

1.2 Ensure access policies are attached only to teams or roles (Scored)
Description:

Policies should not be attached directly to users.

Rationale:

Grouping eases permission management.

Remediation:

Detach direct user policies.

2 Logging and Monitoring
2.1 Ensure activity logging is enabled in all regions (Scored)
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

3.2 Ensure network flow logging is enabled in all virtual networks (Scored)
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
1.2    Ensure access policies are attached only to teams or roles (Scored)
2      Logging and Monitoring
2.1    Ensure activity logging is enabled in all regions (Scored)
3      Networking
3.1    Ensure no security group allows ingress from 0.0.0.0/0 to port 22 (Scored)
3.2    Ensure network flow logging is enabled in all virtual networks (Scored)

Appendix: Change History
Nothing to see here.
'''


def test_section_updates_correctly_between_rule_blocks_in_summary_table():
    catalog = parse_benchmark(FIXTURE_MULTI_SECTION, _AWS_CONFIG, source_filename="fixture.pdf")
    sections_by_id = {r.id: r.section for r in catalog.rules}
    assert sections_by_id["1.1"] == "1. Identity and Access Management"
    assert sections_by_id["1.2"] == "1. Identity and Access Management"
    assert sections_by_id["2.1"] == "2. Logging and Monitoring"
    assert sections_by_id["3.1"] == "3. Networking"
    assert sections_by_id["3.2"] == "3. Networking"
    assert len(set(sections_by_id.values())) == 3


def test_corrupted_marker_on_a_real_rule_is_kept_and_flagged_incomplete():
    """A rule with real body content (Description/Rationale/Remediation all
    present) but an unparseable classification marker must still be
    emitted, flagged incomplete — NOT silently dropped. This is distinct
    from a structural grouping header (next test), which has no body
    content at all.
    """
    text = '''CIS Test Benchmark
v9.9.9 - 01-01-2099

Table of Contents

Recommendations
1 Identity and Access Management
1.1 Ensure a control has a marker with an injected character
Profile Applicability:

 Level 1

Description:

Testing unparseable marker handling.

Rationale:

Testing matters.

Audit:

Run the following command:

  example iam get-account-summary

Remediation:

Fix it.

Appendix: Summary Table
1      Identity and Access Management
1.1    Ensure a control has a marker with an injected character (Not\N{REGISTERED SIGN}Scored)

Appendix: Change History
Nothing to see here.
'''
    catalog = parse_benchmark(text, _AWS_CONFIG)
    assert len(catalog.rules) == 1
    rule = catalog.rules[0]
    assert rule.incomplete is True
    assert any("classification" in m for m in rule.missing_sections)


# Regression fixture for the Azure/GCP grouping-header finding: a Summary
# Table row with a 2-level id, no classification marker anywhere, and NO
# body content at all (just a bare heading line, like Azure's real
# "4.1 SQL Server - Auditing" grouping several 3-level leaf rules) must be
# excluded from the catalog entirely — it isn't a rule. Uses a different
# classification vocabulary (Manual/Automated) than the AWS-flavored
# fixtures above, both to prove config parameterization actually works and
# because this pattern was found in benchmarks that use that vocabulary.
_GENERIC_CONFIG = BenchmarkParserConfig(
    benchmark_name="CIS Test Benchmark 2",
    appendix_marker="Appendix: Recommendation Summary",
    classification_words=["Manual", "Automated"],
    known_versions=["9.9.9"],
)

FIXTURE_GROUPING_HEADER = '''CIS Test Benchmark 2
v9.9.9 - 01-01-2099

Table of Contents

Recommendations
1 Database Services
1.1 Example Database Grouping
1.1.1 Ensure that 'Change Tracking' is set to 'On' (Automated)
Profile Applicability:

 Level 1

Description:

Auditing should be enabled.

Rationale:

Auditing aids incident investigation.

Remediation:

Enable auditing.

1.1.2 Ensure that 'History Window' is 'greater than 90 days' (Manual)
Profile Applicability:

 Level 1

Description:

Longer retention aids investigation.

Rationale:

Short retention loses historical data.

Remediation:

Increase retention to over 90 days.

Appendix: Recommendation Summary
Table
1        Database Services
1.1      Example Database Grouping
1.1.1    Ensure that 'Change Tracking' is set to 'On' (Automated)
1.1.2    Ensure that 'History Window' is 'greater than 90 days' (Manual)

Appendix: Change History
Nothing to see here.
'''


def test_grouping_header_with_no_marker_and_no_body_content_is_excluded():
    catalog = parse_benchmark(FIXTURE_GROUPING_HEADER, _GENERIC_CONFIG)
    ids = [r.id for r in catalog.rules]
    assert ids == ["1.1.1", "1.1.2"]
    assert "1.1" not in ids
    assert len(catalog.rules) == 2


# Regression fixtures for the Workspace finding: rule IDs go up to 6
# segments deep (e.g. real "3.1.2.1.1.6"), far beyond AWS/Azure/GCP's max
# of 3 — the old _RULE_ID_RE (capped at {1,2} extra segments) silently
# failed to match anything deeper, which was the root cause of an initial
# broken run recovering only 32 of 86 real rules. Also exercises multiple
# levels of intermediate grouping headers (2, 3, and 4 segments), each
# with no classification marker and no body content, which must all be
# dropped the same way the existing single-level grouping-header test
# above already proves for a 2-segment header.
FIXTURE_DEEP_NESTING = '''CIS Test Benchmark 2
v9.9.9 - 01-01-2099

Table of Contents

Recommendations
1 Sharing Controls
1.1 Sharing Options
1.1.1 File Sharing
1.1.1.1 External Sharing
1.1.1.1.1 Ensure external file sharing defaults to view-only access (Manual)
Description:

Files shared externally should default to view-only permissions.

Rationale:

View-only defaults reduce accidental data modification by external parties.

Remediation:

Set the external sharing default to view-only.

Appendix: Recommendation Summary
Table
1          Sharing Controls
1.1        Sharing Options
1.1.1      File Sharing
1.1.1.1    External Sharing
1.1.1.1.1  Ensure external file sharing defaults to view-only access (Manual)

Appendix: Change History
Nothing to see here.
'''


def test_rule_id_regex_matches_ids_deeper_than_three_segments():
    catalog = parse_benchmark(FIXTURE_DEEP_NESTING, _GENERIC_CONFIG)
    assert [r.id for r in catalog.rules] == ["1.1.1.1.1"]
    assert catalog.rules[0].classification == "Manual"


def test_intermediate_multi_segment_grouping_headers_are_all_dropped():
    catalog = parse_benchmark(FIXTURE_DEEP_NESTING, _GENERIC_CONFIG)
    ids = [r.id for r in catalog.rules]
    assert "1.1" not in ids
    assert "1.1.1" not in ids
    assert "1.1.1.1" not in ids
    assert len(catalog.rules) == 1


def test_version_regex_accepts_two_segment_version_string():
    text = FIXTURE_HAPPY_PATH.replace("v9.9.9 - 01-01-2099", "v9.9 - 01-01-2099")
    config = BenchmarkParserConfig(
        benchmark_name="CIS Test Benchmark",
        appendix_marker="Appendix: Summary Table",
        classification_words=["Scored", "Not Scored"],
        known_versions=["9.9"],
    )
    catalog = parse_benchmark(text, config)
    assert catalog.benchmark_version == "9.9"
    assert catalog.version_verified is True


# Regression fixture for the Workspace finding: the Summary Table is
# directly followed by an appendix type AWS/Azure/GCP don't have, sitting
# between the Summary Table and Appendix: Change History. The old
# end-boundary logic searched specifically for the literal string
# "Appendix: Change History", which would sweep this extra appendix's
# content into the table slice too (observed as duplicate/corrupted
# anchors on the real document). The row inside the extra appendix below
# deliberately reuses "1.1" as its leading token to prove it would corrupt
# the anchor list if swept in.
FIXTURE_EXTRA_APPENDIX_BEFORE_CHANGE_HISTORY = '''CIS Test Benchmark
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

Appendix: Summary Table
1      Identity and Access Management
1.1    Ensure account root access keys are removed (Scored)

Appendix: CIS Controls Mapped Recommendations
1.1    9.9 Require A Second Authentication Factor For Privileged Accounts

Appendix: Change History
Nothing to see here.
'''


def test_summary_table_boundary_stops_at_next_appendix_not_just_change_history():
    catalog = parse_benchmark(FIXTURE_EXTRA_APPENDIX_BEFORE_CHANGE_HISTORY, _AWS_CONFIG)
    assert [r.id for r in catalog.rules] == ["1.1"]


# Regression fixture for the Workspace finding: the Summary Table (and
# body rule-header lines) embed a profile-level tag directly before the
# title, e.g. (fictional illustration) "1.1.1 (L1) Ensure that between
# two and four example admin accounts are designated". This is cosmetic
# only — profile_level is already correctly populated from the unrelated
# Profile Applicability: body field below (unchanged logic) — the tag
# just needs stripping so the title reads cleanly.
FIXTURE_WITH_PROFILE_LEVEL_TAG = '''CIS Test Benchmark
v9.9.9 - 01-01-2099

Table of Contents

Recommendations
1 Identity and Access Management
1.1 (L1) Ensure account root access keys are removed (Scored)
Profile Applicability:

 Example Org Level 1

Description:

Root access keys should not exist.

Rationale:

Root has unrestricted access.

Remediation:

Remove root access keys.

Appendix: Summary Table
1      Identity and Access Management
1.1    (L1) Ensure account root access keys are removed (Scored)

Appendix: Change History
Nothing to see here.
'''


def test_leading_profile_level_tag_is_stripped_from_title():
    catalog = parse_benchmark(FIXTURE_WITH_PROFILE_LEVEL_TAG, _AWS_CONFIG)
    rule = catalog.rules[0]
    assert rule.title == "Ensure account root access keys are removed"
    assert "(L1)" not in rule.title
    assert rule.classification == "Scored"
    assert rule.profile_level == "Level 1"


# Regression fixture for the Workspace v1.4 real-PDF finding: pdftotext
# -layout preserves that document's own left margin, rendering the
# "Recommendations" heading, every summary-table row, every rule-ID body
# line, and every section label ("Description:", "Rationale:", etc.) with
# a consistent run of leading spaces instead of starting at column 0. The
# old column-0-anchored regexes/string matches silently found zero
# recommendations against this real document even though every unit test
# here (all written with unindented fixtures) stayed green.
FIXTURE_WITH_LEFT_MARGIN_INDENT = '''CIS Test Benchmark
v9.9.9 - 01-01-2099

            Table of Contents

            Recommendations
            1 Identity and Access Management
            1.1 Ensure account root access keys are removed (Scored)
            Profile Applicability:

             Level 1

            Description:

            Root access keys should not exist.

            Rationale:

            Root has unrestricted access.

            Remediation:

            Remove root access keys.

            Appendix: Summary Table
              1      Identity and Access Management
              1.1    Ensure account root access keys are removed (Scored)

            Appendix: Change History
            Nothing to see here.
'''


def test_consistent_left_margin_indent_does_not_hide_rules():
    catalog = parse_benchmark(FIXTURE_WITH_LEFT_MARGIN_INDENT, _AWS_CONFIG)
    assert [r.id for r in catalog.rules] == ["1.1"]
    rule = catalog.rules[0]
    assert rule.title == "Ensure account root access keys are removed"
    assert rule.classification == "Scored"
    assert rule.profile_level == "Level 1"
    assert rule.description == "Root access keys should not exist."
    assert not rule.incomplete


# Regression fixture for a final-review finding: the shared engine's
# per-rule body anchor requires only "<rule id><optional margin>
# <whitespace>" at (optionally indented) line-start. A rule's own "CIS
# Controls:" section lists numbered safeguard cross-references that are
# indented MORE deeply than a genuine rule header, but that depth was
# never checked — so when a safeguard number coincidentally equals a
# LATER real rule's ID, the old anchor pattern binds to that indented
# table row instead of waiting for the real header. That silently
# truncates the earlier rule's cis_controls (the block ends right at the
# collision row, losing every safeguard listed after it — undetectable
# via `incomplete`, since "CIS Controls:" isn't a required label) and can
# also corrupt the later rule's own parsed fields, since the collision
# row becomes that later rule's own search-start cursor and a stray
# label occurrence sitting in the truncated tail can then win the "first
# occurrence" race used by _split_block_into_sections instead of the
# label following the real header. Entirely fictional content — this
# reproduces the collision *class* observed against the real Workspace
# PDF (anchor "4.3" mis-binding into rule "4.2.5.1"'s own CIS Controls
# table, and anchor "6.2" into rule "6.1"'s), not any real CIS wording.
FIXTURE_COLLIDING_CIS_CONTROLS_NUMBER = '''CIS Test Benchmark
v9.9.9 - 01-01-2099

Table of Contents

Recommendations
4 Example Category
4.2 Configure the example legacy widget baseline (Scored)
Profile Applicability:

 Level 1

Description:

Real description for 4.2.

Rationale:

Real rationale for 4.2.

Remediation:

Real remediation for 4.2.

CIS Controls:

9.1 Establish and Maintain a Software Inventory
Track approved software across the fleet.
    4.3 Handle An Unrelated Widget Safeguard Requirement

Description:

Decoy text that must never be mistaken for rule 4.3's real description.

9.2 Address Unauthorized Software
Remove software that is not on the approved software list.

4.3 Configure the example modern widget baseline (Scored)
Profile Applicability:

 Level 1

Description:

Real description for 4.3.

Rationale:

Real rationale for 4.3.

Remediation:

Real remediation for 4.3.

Appendix: Summary Table
4      Example Category
4.2    Configure the example legacy widget baseline (Scored)
4.3    Configure the example modern widget baseline (Scored)

Appendix: Change History
Nothing to see here.
'''


def test_cis_controls_cross_reference_matching_a_later_rule_id_does_not_truncate_or_corrupt():
    catalog = parse_benchmark(FIXTURE_COLLIDING_CIS_CONTROLS_NUMBER, _AWS_CONFIG)
    ids = [r.id for r in catalog.rules]
    assert ids == ["4.2", "4.3"]

    rule_4_2 = next(r for r in catalog.rules if r.id == "4.2")
    rule_4_3 = next(r for r in catalog.rules if r.id == "4.3")

    # (a) The earlier rule's cis_controls must not be truncated at the
    # coincidentally-numbered "4.3" row buried inside its own CIS
    # Controls table — the safeguard row listed after the collision
    # ("9.2 ...") must still be captured, not silently dropped.
    assert "9.1 Establish and Maintain a Software Inventory" in rule_4_2.cis_controls
    assert "9.2 Address Unauthorized Software" in rule_4_2.cis_controls
    assert not rule_4_2.incomplete

    # (b) The later anchor ("4.3") must bind to its own real header, not
    # the coincidental table row inside 4.2's block — proven by its
    # description being the real one, not the decoy text sitting between
    # the collision row and the real header (which a mis-bound block
    # start would otherwise pick up as the "first" Description: match).
    assert rule_4_3.description == "Real description for 4.3."
    assert "Decoy text" not in rule_4_3.description
    assert not rule_4_3.incomplete
