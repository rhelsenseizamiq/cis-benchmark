from cis_benchmark.importer.aws_parser import parse

# Minimal, clearly-fictional fixture — just enough to verify aws_parser.py
# wires the correct BenchmarkParserConfig (benchmark_name, appendix
# marker, classification vocabulary, known_versions). The shared parsing
# algorithm itself (wrapped titles, TOC collisions, grouping headers,
# incomplete-flagging, etc.) is tested once, generically, in
# tests/test_importer_pdf_benchmark_parser.py — no need to duplicate it
# per cloud.
FIXTURE = '''CIS Amazon Web Services Foundations
Benchmark
v1.2.0 - 01-01-2099

Table of Contents

Recommendations
1 Identity and Access Management
1.1 Avoid using the primary administrative account for routine operations (Scored)
Description:

Do not use the root account for daily tasks.

Rationale:

The root account has unrestricted access to everything.

Remediation:

Stop using the root account for daily tasks.

Appendix: Summary Table
1      Identity and Access Management
1.1    Avoid using the primary administrative account for routine operations (Scored)

Appendix: Change History
Nothing to see here.
'''


def test_aws_parser_uses_correct_benchmark_name():
    catalog = parse(FIXTURE, source_filename="fixture.pdf")
    assert catalog.benchmark_name == "CIS Amazon Web Services Foundations Benchmark"


def test_aws_parser_uses_scored_not_scored_vocabulary():
    catalog = parse(FIXTURE)
    assert catalog.rules[0].classification == "Scored"


def test_aws_parser_known_version_is_verified():
    catalog = parse(FIXTURE)  # fixture uses v1.2.0, which is aws_parser's known_versions
    assert catalog.version_verified is True


def test_aws_parser_unknown_version_is_not_verified():
    unknown_version_text = FIXTURE.replace("v1.2.0 - 01-01-2099", "v9.9.9 - 01-01-2099")
    catalog = parse(unknown_version_text)
    assert catalog.version_verified is False
