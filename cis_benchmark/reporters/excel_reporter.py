import os
from typing import Dict, Any
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

FORMULA_TRIGGER_CHARS = ("=", "+", "-", "@", "\t", "\r")


def _sanitize_cell(value):
    """Neutralizes CSV/Excel formula injection: a cell string starting with
    =, +, -, @ (or a tab/CR) is interpreted as a formula by Excel/LibreOffice
    when the workbook is opened, regardless of how it was written. Affected
    resource names and details come from live cloud resource identifiers
    (bucket names, security group names, etc.) that an attacker could name
    maliciously, so they must be treated as untrusted before writing to a
    spreadsheet cell."""
    if isinstance(value, str) and value.startswith(FORMULA_TRIGGER_CHARS):
        return "'" + value
    return value


class ExcelReporter:
    def __init__(self, output_dir: str = "./output"):
        self.output_dir = output_dir
        os.makedirs(self.output_dir, exist_ok=True)

    def generate(self, summary: Dict[str, Any], filename: str = "cis_compliance_report.xlsx") -> str:
        filepath = os.path.join(self.output_dir, filename)
        wb = openpyxl.Workbook()
        
        # Summary Sheet
        ws_summary = wb.active
        ws_summary.title = "Executive Summary"
        ws_summary.views.sheetView[0].showGridLines = True

        # Header Title
        ws_summary.merge_cells("A1:E1")
        title_cell = ws_summary["A1"]
        title_cell.value = "🛡️ CIS Unified Cloud & Workspace Compliance Audit Summary"
        title_cell.font = Font(name="Calibri", size=16, bold=True, color="FFFFFF")
        title_cell.fill = PatternFill("solid", fgColor="1E293B")
        title_cell.alignment = Alignment(horizontal="left", vertical="center")
        ws_summary.row_dimensions[1].height = 40

        # Stats Cards
        metrics = [
            ("Compliance Score", f"{summary['score']}%", "0284C7"),
            ("Total Checks", summary["total_checks"], "475569"),
            ("Passed", summary["passed"], "16A34A"),
            ("Failed", summary["failed"], "DC2626"),
            ("Warnings", summary["warnings"], "D97706"),
            ("Manual Review Required", summary.get("manual", 0), "0284C7"),
            ("Errors", summary.get("errors", 0), "A21CAF"),
        ]

        row = 3
        for label, val, color in metrics:
            ws_summary.cell(row=row, column=1, value=label).font = Font(bold=True, size=11, color="475569")
            val_cell = ws_summary.cell(row=row, column=2, value=val)
            val_cell.font = Font(bold=True, size=12, color=color)
            row += 1

        # Detailed Findings Sheet
        ws_details = wb.create_sheet(title="Detailed Findings")
        ws_details.views.sheetView[0].showGridLines = True

        headers = ["Rule ID", "Section", "Title", "Severity", "Status", "Rationale", "Remediation", "Affected Resources / Details"]
        ws_details.append(headers)

        # Header Styling
        header_fill = PatternFill("solid", fgColor="0F172A")
        header_font = Font(name="Calibri", size=11, bold=True, color="FFFFFF")
        for col_num, header in enumerate(headers, 1):
            cell = ws_details.cell(row=1, column=col_num)
            cell.fill = header_fill
            cell.font = header_font
            cell.alignment = Alignment(horizontal="center", vertical="center")

        ws_details.row_dimensions[1].height = 28

        # Data Rows
        status_style = {
            "PASS": (PatternFill("solid", fgColor="DCFCE7"), Font(color="15803D", bold=True)),
            "FAIL": (PatternFill("solid", fgColor="FEE2E2"), Font(color="B91C1C", bold=True)),
            "WARNING": (PatternFill("solid", fgColor="FEF3C7"), Font(color="B45309", bold=True)),
            "MANUAL_CHECK": (PatternFill("solid", fgColor="DBEAFE"), Font(color="1D4ED8", bold=True)),
            "ERROR": (PatternFill("solid", fgColor="F3E8FF"), Font(color="7E22CE", bold=True)),
        }

        for r in summary["results"]:
            d = r.to_dict()
            aff = "\n".join(str(item) for item in d.get("affected_resources", []))
            det = f"{d['details']}\n{aff}".strip()

            row_data = [_sanitize_cell(v) for v in (
                d["rule_id"],
                d["section"],
                d["title"],
                d["severity"],
                d["status"],
                d["rationale"],
                d["remediation"],
                det
            )]
            ws_details.append(row_data)
            current_row = ws_details.max_row

            # Status Formatting
            st_cell = ws_details.cell(row=current_row, column=5)
            fill, font = status_style.get(d["status"], (PatternFill("solid", fgColor="F1F5F9"), Font(color="334155", bold=True)))
            st_cell.fill = fill
            st_cell.font = font

        # Auto Adjust Column Widths
        for ws in [ws_summary, ws_details]:
            for col in ws.columns:
                max_len = max(len(str(cell.value or '')) for cell in col)
                col_letter = get_column_letter(col[0].column)
                ws.column_dimensions[col_letter].width = min(max(max_len + 3, 12), 50)

        wb.save(filepath)
        return filepath
