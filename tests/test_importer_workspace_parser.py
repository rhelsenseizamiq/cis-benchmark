from cis_benchmark.importer.workspace_parser import parse

# Synthetic fixture exercising every Workspace-specific wrinkle verified
# during design: a single-line (unwrapped) appendix marker, a 3-segment
# rule ID under a 2-segment grouping header, an embedded (L1) profile-level
# tag stripped from the title, a 2-segment version string, and an extra
# appendix (CIS Controls mapping) between the Summary Table and Change
# History that must not corrupt the parsed rule list. Completely fictional content.
FIXTURE = '''Example Security Benchmark
for Testing
v1.4 - 01-01-2099

Table of Contents

Recommendations
1 Access Control
1.1 Account Management
1.1.1 (L1) Configure password complexity requirements for test system accounts (Manual)
Profile Applicability:

 Testing Framework Level 1

Description:

This is a fictional rule used for testing purposes only.

Rationale:

Fictional rationale text for test fixture validation.

Remediation:

Fictional remediation procedures for parser testing.

Appendix: Summary Table
1        Access Control
1.1      Account Management
1.1.1    (L1) Configure password complexity requirements for test system accounts (Manual)

Appendix: Related Framework Mappings
1.1.1    X.Y Sample Framework Reference for Rule Testing

Appendix: Change History
Test document with no real content.
'''


def test_workspace_parser_uses_correct_benchmark_name():
    catalog = parse(FIXTURE, source_filename="fixture.pdf")
    assert catalog.benchmark_name == "CIS Google Workspace Foundations Benchmark"


def test_workspace_parser_uses_manual_automated_vocabulary():
    catalog = parse(FIXTURE)
    assert catalog.rules[0].classification == "Manual"


def test_workspace_parser_strips_profile_level_tag_from_title():
    catalog = parse(FIXTURE)
    assert catalog.rules[0].title == "Configure password complexity requirements for test system accounts"
    assert catalog.rules[0].profile_level == "Level 1"


def test_workspace_parser_drops_grouping_header_and_ignores_extra_appendix():
    catalog = parse(FIXTURE)
    ids = [r.id for r in catalog.rules]
    assert ids == ["1.1.1"]
    assert "1.1" not in ids


def test_workspace_parser_known_two_segment_version_is_verified():
    catalog = parse(FIXTURE)
    assert catalog.benchmark_version == "1.4"
    assert catalog.version_verified is True


def test_workspace_parser_unknown_version_is_not_verified():
    unknown_version_text = FIXTURE.replace("v1.4 - 01-01-2099", "v9.9 - 01-01-2099")
    catalog = parse(unknown_version_text)
    assert catalog.version_verified is False
