import os
import html
from typing import Dict, Any

from .. import __version__

STATUS_STYLE = {
    "PASS": ("st-pass", "✓"),
    "FAIL": ("st-fail", "✗"),
    "WARNING": ("st-warn", "⚠️"),
    "MANUAL_CHECK": ("st-manual", "🔍"),
    "ERROR": ("st-error", "💥"),
}


class HTMLReporter:
    def __init__(self, output_dir: str = "./output"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def generate(self, summary: Dict[str, Any], filename: str = "cis_compliance_report.html") -> str:
        filepath = os.path.join(self.output_dir, filename)

        results = summary["results"]

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>CIS Unified Cloud & Workspace Compliance Report</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg: #0f172a;
            --card-bg: #1e293b;
            --text-main: #f8fafc;
            --text-sub: #94a3b8;
            --border: #334155;
            --pass: #22c55e;
            --fail: #ef4444;
            --warning: #f59e0b;
            --manual: #38bdf8;
            --error: #d946ef;
            --accent: #38bdf8;
        }}
        body {{
            font-family: 'Inter', sans-serif;
            background-color: var(--bg);
            color: var(--text-main);
            margin: 0;
            padding: 24px;
        }}
        .header {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            border-bottom: 1px solid var(--border);
            padding-bottom: 16px;
            margin-bottom: 24px;
        }}
        .header h1 {{ font-size: 1.5rem; margin: 0; display: flex; align-items: center; gap: 10px; }}
        .badge {{ background: #0284c7; color: #fff; font-size: 0.8rem; padding: 4px 10px; border-radius: 20px; }}
        .stats-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
            margin-bottom: 32px;
        }}
        .stat-card {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            padding: 20px;
            text-align: center;
        }}
        .stat-card .val {{ font-size: 2.2rem; font-weight: 700; margin-top: 4px; }}
        .stat-card.pass .val {{ color: var(--pass); }}
        .stat-card.fail .val {{ color: var(--fail); }}
        .stat-card.warn .val {{ color: var(--warning); }}
        .stat-card.manual .val {{ color: var(--manual); }}
        .stat-card.error .val {{ color: var(--error); }}
        .stat-card.score .val {{ color: var(--accent); }}

        .table-container {{
            background: var(--card-bg);
            border: 1px solid var(--border);
            border-radius: 12px;
            overflow: hidden;
        }}
        table {{
            width: 100%;
            border-collapse: collapse;
            text-align: left;
        }}
        th, td {{ padding: 14px 18px; border-bottom: 1px solid var(--border); }}
        th {{ background: #0f172a; color: var(--text-sub); font-size: 0.85rem; text-transform: uppercase; letter-spacing: 0.05em; }}
        tr:hover {{ background: rgba(255,255,255,0.02); }}

        .st-pass {{ color: var(--pass); font-weight: 600; display: inline-flex; align-items: center; gap: 6px; }}
        .st-fail {{ color: var(--fail); font-weight: 600; display: inline-flex; align-items: center; gap: 6px; }}
        .st-warn {{ color: var(--warning); font-weight: 600; display: inline-flex; align-items: center; gap: 6px; }}
        .st-manual {{ color: var(--manual); font-weight: 600; display: inline-flex; align-items: center; gap: 6px; }}
        .st-error {{ color: var(--error); font-weight: 600; display: inline-flex; align-items: center; gap: 6px; }}

        .sev-CRITICAL {{ background: rgba(239, 68, 68, 0.2); color: #fca5a5; padding: 2px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; }}
        .sev-HIGH {{ background: rgba(245, 158, 11, 0.2); color: #fde68a; padding: 2px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; }}
        .sev-MEDIUM {{ background: rgba(56, 189, 248, 0.2); color: #bae6fd; padding: 2px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; }}
        .sev-LOW {{ background: rgba(148, 163, 184, 0.2); color: #cbd5e1; padding: 2px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; }}
        .sev-INFO {{ background: rgba(148, 163, 184, 0.2); color: #cbd5e1; padding: 2px 8px; border-radius: 6px; font-size: 0.75rem; font-weight: 600; }}

        .affected {{ font-family: monospace; font-size: 0.8rem; color: #fda4af; margin-top: 4px; }}
    </style>
</head>
<body>
    <div class="header">
        <h1>🛡️ CIS Unified Compliance Audit Report <span class="badge">v{html.escape(__version__)}</span></h1>
        <div style="color: var(--text-sub); font-size: 0.9rem;">Scan Time: {html.escape(str(summary.get('timestamp', 'Just now')))} | Duration: {summary['duration']}s</div>
    </div>

    <div class="stats-grid">
        <div class="stat-card score">
            <div style="color: var(--text-sub); font-size: 0.85rem;">Compliance Score</div>
            <div class="val">{summary['score']}%</div>
        </div>
        <div class="stat-card pass">
            <div style="color: var(--text-sub); font-size: 0.85rem;">Passed Checks</div>
            <div class="val">{summary['passed']}</div>
        </div>
        <div class="stat-card fail">
            <div style="color: var(--text-sub); font-size: 0.85rem;">Failed Checks</div>
            <div class="val">{summary['failed']}</div>
        </div>
        <div class="stat-card warn">
            <div style="color: var(--text-sub); font-size: 0.85rem;">Warnings</div>
            <div class="val">{summary['warnings']}</div>
        </div>
        <div class="stat-card manual">
            <div style="color: var(--text-sub); font-size: 0.85rem;">Manual Review</div>
            <div class="val">{summary.get('manual', 0)}</div>
        </div>
        <div class="stat-card error">
            <div style="color: var(--text-sub); font-size: 0.85rem;">Errors</div>
            <div class="val">{summary.get('errors', 0)}</div>
        </div>
    </div>

    <h2>Detailed Rule Audit Results</h2>
    <div class="table-container">
        <table>
            <thead>
                <tr>
                    <th>Rule ID</th>
                    <th>Section</th>
                    <th>Benchmark Title</th>
                    <th>Severity</th>
                    <th>Status</th>
                    <th>Audit Details & Findings</th>
                </tr>
            </thead>
            <tbody>
"""
        for r in results:
            d = r.to_dict()
            st_cls, icon = STATUS_STYLE.get(d['status'], ("st-warn", "⚠️"))

            aff_html = ""
            if d.get("affected_resources"):
                escaped_items = [html.escape(str(item)) for item in d["affected_resources"]]
                aff_html = "<div class='affected'><strong>Affected Resources:</strong><br/>" + "<br/>".join(escaped_items) + "</div>"

            html_content += f"""
                <tr>
                    <td><strong>{html.escape(d['rule_id'])}</strong></td>
                    <td style="color: var(--text-sub);">{html.escape(d['section'])}</td>
                    <td>{html.escape(d['title'])}</td>
                    <td><span class="sev-{d['severity']}">{html.escape(d['severity'])}</span></td>
                    <td><span class="{st_cls}">{icon} {html.escape(d['status'])}</span></td>
                    <td>
                        {html.escape(d['details'])}
                        {aff_html}
                    </td>
                </tr>
            """

        html_content += """
            </tbody>
        </table>
    </div>
</body>
</html>
"""
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(html_content)

        return filepath
