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
