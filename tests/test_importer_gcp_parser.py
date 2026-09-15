from cis_benchmark.importer.gcp_parser import parse

FIXTURE = '''CIS Google Cloud Platform Foundation
Benchmark
v1.2.0 - 01-01-2099

Table of Contents

Recommendations
1 Identity and Access Management
1.1 Ensure that federated identity accounts are required (Manual)
Description:

Example description text.

Rationale:

Example rationale text.

Remediation:

Example remediation text.

Appendix: Recommendation Summary
Table
1        Identity and Access Management
1.1      Ensure that federated identity accounts are required (Manual)

Appendix: Change History
Nothing to see here.
'''


def test_gcp_parser_uses_correct_benchmark_name():
    catalog = parse(FIXTURE, source_filename="fixture.pdf")
    # Note: "Foundation", singular — matches CIS's own (inconsistent) naming
    # on the real document, confirmed during design investigation.
    assert catalog.benchmark_name == "CIS Google Cloud Platform Foundation Benchmark"


def test_gcp_parser_uses_manual_automated_vocabulary():
    catalog = parse(FIXTURE)
    assert catalog.rules[0].classification == "Manual"


def test_gcp_parser_handles_wrapped_appendix_heading():
    catalog = parse(FIXTURE)
    assert len(catalog.rules) == 1


def test_gcp_parser_known_version_is_verified():
    catalog = parse(FIXTURE)
    assert catalog.version_verified is True


def test_gcp_parser_unknown_version_is_not_verified():
    unknown_version_text = FIXTURE.replace("v1.2.0 - 01-01-2099", "v9.9.9 - 01-01-2099")
    catalog = parse(unknown_version_text)
    assert catalog.version_verified is False


# Regression fixture for the GCP v5.0.0 finding: the real document's
# Summary Table heading changed from the older wrapped
# "Appendix: Recommendation Summary\nTable" to a new single-line
# "Appendix: Summary Table" (matching AWS/Workspace's convention). Both
# forms must keep working since the older, already-verified v1.2.0 real
# document used the wrapped form.
FIXTURE_NEW_HEADING = FIXTURE.replace(
    "v1.2.0 - 01-01-2099", "v5.0.0 - 01-01-2099"
).replace(
    "Appendix: Recommendation Summary\nTable", "Appendix: Summary Table"
)


def test_gcp_parser_handles_new_unwrapped_appendix_heading():
    catalog = parse(FIXTURE_NEW_HEADING)
    assert len(catalog.rules) == 1


def test_gcp_parser_second_known_version_is_verified():
    catalog = parse(FIXTURE_NEW_HEADING)  # fixture uses v5.0.0
    assert catalog.version_verified is True
