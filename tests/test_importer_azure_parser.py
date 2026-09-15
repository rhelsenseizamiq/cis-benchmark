from cis_benchmark.importer.azure_parser import parse

# Minimal, clearly-fictional fixture verifying azure_parser.py wires the
# correct config: benchmark name, the wrapped "Appendix: Recommendation
# Summary\nTable" heading (confirmed against the real document during
# design — this fixture reproduces that exact wrap), and the
# Manual/Automated classification vocabulary (not AWS's Scored/Not Scored).
FIXTURE = '''CIS Microsoft Azure Foundations
Benchmark
v1.4.0 - 01-01-2099

Table of Contents

Recommendations
1 Identity and Access Management
1.1 Ensure that 'Example Setting' is 'Enabled' for all Example Users (Manual)
Description:

Example description text.

Rationale:

Example rationale text.

Remediation:

Example remediation text.

Appendix: Recommendation Summary
Table
1        Identity and Access Management
1.1      Ensure that 'Example Setting' is 'Enabled' for all Example Users (Manual)

Appendix: Change History
Nothing to see here.
'''


def test_azure_parser_uses_correct_benchmark_name():
    catalog = parse(FIXTURE, source_filename="fixture.pdf")
    assert catalog.benchmark_name == "CIS Microsoft Azure Foundations Benchmark"


def test_azure_parser_uses_manual_automated_vocabulary():
    catalog = parse(FIXTURE)
    assert catalog.rules[0].classification == "Manual"


def test_azure_parser_handles_wrapped_appendix_heading():
    # If azure_parser's appendix_marker didn't account for the real
    # document's "Appendix: Recommendation Summary\nTable" line wrap, this
    # fixture (which reproduces that exact wrap) would fail to locate the
    # Summary Table at all and raise ImporterError instead of parsing.
    catalog = parse(FIXTURE)
    assert len(catalog.rules) == 1


def test_azure_parser_known_version_is_verified():
    catalog = parse(FIXTURE)  # fixture uses v1.4.0, azure_parser's known version
    assert catalog.version_verified is True


def test_azure_parser_unknown_version_is_not_verified():
    unknown_version_text = FIXTURE.replace("v1.4.0 - 01-01-2099", "v9.9.9 - 01-01-2099")
    catalog = parse(unknown_version_text)
    assert catalog.version_verified is False


# Regression fixture for the Azure v6.0.0 finding: the real document's
# Summary Table heading changed from the older wrapped
# "Appendix: Recommendation Summary\nTable" to a new single-line
# "Appendix: Summary Table" (matching AWS/Workspace's convention). Both
# forms must keep working since the older, already-verified v1.4.0 real
# document used the wrapped form.
FIXTURE_NEW_HEADING = FIXTURE.replace(
    "v1.4.0 - 01-01-2099", "v6.0.0 - 01-01-2099"
).replace(
    "Appendix: Recommendation Summary\nTable", "Appendix: Summary Table"
)


def test_azure_parser_handles_new_unwrapped_appendix_heading():
    catalog = parse(FIXTURE_NEW_HEADING)
    assert len(catalog.rules) == 1


def test_azure_parser_second_known_version_is_verified():
    catalog = parse(FIXTURE_NEW_HEADING)  # fixture uses v6.0.0
    assert catalog.version_verified is True
