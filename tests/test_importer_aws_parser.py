import pytest

from cis_benchmark.importer.errors import ImporterError
from cis_benchmark.importer.aws_parser import parse

# A synthetic "mini benchmark" built to exercise the exact structural
# wrinkles found by inspecting a real CIS AWS Foundations Benchmark PDF
# during design: a title that wraps across two lines before its
# (Scored)/(Not Scored) marker, a CIS Controls cross-reference number
# ("4.5 Use Multifactor...") that must NOT be mistaken for a new rule,
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

4.5 Use Multifactor Authentication For All Administrative Access
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

4.5 Use Multifactor Authentication For All Administrative Access
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
    # phantom "4.5" rule from the CIS Controls cross-reference text.
    assert len(catalog.rules) == 3
    assert "4.5" not in [r.id for r in catalog.rules]
    rule_1_1 = next(r for r in catalog.rules if r.id == "1.1")
    assert "4.5 Use Multifactor Authentication" in rule_1_1.cis_controls


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
