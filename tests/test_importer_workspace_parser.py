from cis_benchmark.importer.workspace_parser import parse

# Synthetic fixture exercising every Workspace-specific wrinkle verified
# during design: a single-line (unwrapped) appendix marker, a 3-segment
# rule ID under a 2-segment grouping header, an embedded (L1) profile-level
# tag stripped from the title, a 2-segment version string, and an extra
# appendix (CIS Controls mapping) between the Summary Table and Change
# History that must not corrupt the parsed rule list. No real CIS content.
FIXTURE = '''CIS Google Workspace
Foundations Benchmark
v1.4 - 01-01-2099

Table of Contents

Recommendations
1 Directory
1.1 Users
1.1.1 (L1) Ensure that between two and four global admins are designated (Manual)
Profile Applicability:

 Enterprise Level 1

Description:

Example description text.

Rationale:

Example rationale text.

Remediation:

Example remediation text.

Appendix: Summary Table
1        Directory
1.1      Users
1.1.1    (L1) Ensure that between two and four global admins are designated (Manual)

Appendix: CIS Controls v7 IG 1 Mapped Recommendations
1.1.1    9.9 Require A Second Authentication Factor For Privileged Accounts

Appendix: Change History
Nothing to see here.
'''


def test_workspace_parser_uses_correct_benchmark_name():
    catalog = parse(FIXTURE, source_filename="fixture.pdf")
    assert catalog.benchmark_name == "CIS Google Workspace Foundations Benchmark"


def test_workspace_parser_uses_manual_automated_vocabulary():
    catalog = parse(FIXTURE)
    assert catalog.rules[0].classification == "Manual"


def test_workspace_parser_strips_profile_level_tag_from_title():
    catalog = parse(FIXTURE)
    assert catalog.rules[0].title == "Ensure that between two and four global admins are designated"
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
