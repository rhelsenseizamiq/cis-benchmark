import argparse
import os
import sys
from datetime import datetime, timezone

from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.progress import BarColumn, Progress, SpinnerColumn, TaskProgressColumn, TextColumn
from rich.table import Table
from rich.text import Text

from . import __version__
from .core.config import load_settings
from .core.engine import ComplianceEngine
from .importer.aws_parser import parse as parse_aws
from .importer.azure_parser import parse as parse_azure
from .importer.gcp_parser import parse as parse_gcp
from .importer.workspace_parser import parse as parse_workspace
from .importer.errors import ImporterError
from .importer.pdf_extract import extract_text
from .reporters.doc_reporter import DocReporter
from .reporters.excel_reporter import ExcelReporter
from .reporters.html_reporter import HTMLReporter

_IMPORT_PARSERS = {"aws": parse_aws, "azure": parse_azure, "gcp": parse_gcp, "workspace": parse_workspace}
_KNOWN_COMMANDS = {"scan", "import"}

BANNER = """
[bold cyan]   ██████╗██╗███████╗    ██████╗ ███████╗███╗   ██╗██╗  ██╗[/bold cyan]
[bold cyan]  ██╔════╝██║██╔════╝    ██╔══██╗██╔════╝████╗  ██║██║  ██║[/bold cyan]
[bold blue]  ██║     ██║███████╗    ██████╔╝█████╗  ██╔██╗ ██║███████║[/bold blue]
[bold blue]  ██║     ██║╚════██║    ██╔══██╗██╔══╝  ██║╚██╗██║██╔══██║[/bold blue]
[bold magenta]  ╚██████╗██║███████║    ██████╔╝███████╗██║ ╚████║██║  ██║[/bold magenta]
[bold magenta]   ╚═════╝╚═╝╚══════╝    ╚═════╝ ╚══════╝╚═╝  ╚═══╝╚═╝  ╚═╝[/bold magenta]
[bold white]  UNIFIED MULTI-CLOUD COMPLIANCE & CIS BENCHMARK SCANNER[/bold white]
[bold dim]  Targeting: AWS • Azure • GCP • Google Workspace[/bold dim]
"""

STATUS_STYLES = {
    "PASS": "[bold green]✓ PASS[/bold green]",
    "FAIL": "[bold red]✗ FAIL[/bold red]",
    "WARNING": "[bold yellow]⚠️ WARN[/bold yellow]",
    "MANUAL_CHECK": "[bold cyan]🔍 MANUAL[/bold cyan]",
    "ERROR": "[bold magenta]💥 ERROR[/bold magenta]",
}
SEVERITY_STYLES = {
    "CRITICAL": "[bold red]CRITICAL[/bold red]",
    "HIGH": "[yellow]HIGH[/yellow]",
    "MEDIUM": "[blue]MEDIUM[/blue]",
    "LOW": "[dim]LOW[/dim]",
    "INFO": "[dim]INFO[/dim]",
}
PLAIN_STATUS_LABEL = {
    "PASS": "PASS",
    "FAIL": "FAIL",
    "WARNING": "WARN",
    "MANUAL_CHECK": "MANUAL",
    "ERROR": "ERROR",
}


def _generate_reports(summary, out_dir):
    os.makedirs(out_dir, exist_ok=True)

    html_path = HTMLReporter(output_dir=out_dir).generate(summary, filename="cis_compliance_report.html")

    try:
        excel_path = ExcelReporter(output_dir=out_dir).generate(summary, filename="cis_compliance_report.xlsx")
    except Exception:
        excel_path = None

    md_path = DocReporter(output_dir=out_dir).generate_markdown(summary, filename="cis_compliance_report.md")

    return html_path, excel_path, md_path


def _run_plain(engine, out_dir):
    print("=" * 65)
    print(f" CIS UNIFIED CLOUD & WORKSPACE COMPLIANCE AUDIT ENGINE v{__version__}")
    print("=" * 65)

    summary = engine.run_all()
    summary["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    for r in summary["results"]:
        d = r.to_dict()
        label = PLAIN_STATUS_LABEL.get(d["status"], d["status"])
        print(f"[{label:<6}] {d['rule_id']:<10} {d['severity']:<9} {d['title']}")

    print("-" * 65)
    print(
        f"Compliance Score: {summary['score']}% | Evaluated {summary['total_checks']} rules in "
        f"{summary['duration']}s | Passed: {summary['passed']} | Failed: {summary['failed']} | "
        f"Warnings: {summary['warnings']} | Manual Review: {summary['manual']} | Errors: {summary['errors']}"
    )

    print("Generating multi-format compliance reports...")
    html_path, excel_path, md_path = _generate_reports(summary, out_dir)
    print(f"  [OK] HTML Dashboard: {html_path}")
    print(f"  [OK] Excel Workbook: {excel_path or 'N/A (generation failed)'}")
    print(f"  [OK] Markdown Report: {md_path}")


def _run_rich(engine, out_dir):
    console = Console()
    console.clear()
    console.print(Align.center(Text.from_markup(BANNER)))
    console.print()

    target_info = (
        f"[bold white]Target Scope:[/bold white] [cyan]{engine.cloud_filter.upper()}[/cyan]  |  "
        f"[bold white]Domain:[/bold white] [yellow]{engine.target_domain}[/yellow]  |  "
        f"[bold white]Threads:[/bold white] [magenta]{engine.max_workers}[/magenta]"
    )
    console.print(Panel(Align.center(target_info), border_style="blue", title="[bold cyan]Scan Configuration[/bold cyan]"))
    console.print()

    total_rules = len(engine.checks)

    table = Table(title="[bold white]Live Rule Compliance Results[/bold white]", box=None, header_style="bold cyan")
    table.add_column("Rule ID", style="bold white", width=12)
    table.add_column("Section", style="dim white", width=25)
    table.add_column("Benchmark Title", style="white", width=45)
    table.add_column("Severity", width=10)
    table.add_column("Status", width=12)

    with Progress(
        SpinnerColumn("dots", style="cyan"),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(bar_width=40, style="blue", complete_style="green"),
        TaskProgressColumn(),
        console=console,
        expand=True,
    ) as progress:
        task = progress.add_task("[bold cyan]Executing CIS Compliance Rules...[/bold cyan]", total=total_rules)

        def status_cb(res):
            progress.advance(task)

        summary = engine.run_all(status_callback=status_cb)

    summary["timestamp"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    console.print()
    for res in summary["results"]:
        d = res.to_dict()
        st_text = STATUS_STYLES.get(d["status"], d["status"])
        sev_text = SEVERITY_STYLES.get(d["severity"], d["severity"])
        table.add_row(d["rule_id"], d["section"][:24], d["title"][:43], sev_text, st_text)

    console.print(table)
    console.print()

    score = summary["score"]
    score_color = "green" if score >= 80 else ("yellow" if score >= 60 else "red")

    score_text = f"""
[bold white]Overall Compliance Score:[/bold white] [bold {score_color}]{score}%[/bold {score_color}]
[dim]Evaluated {summary['total_checks']} rules in {summary['duration']}s — Passed: {summary['passed']} | Failed: {summary['failed']} | Warnings: {summary['warnings']} | Manual Review: {summary['manual']} | Errors: {summary['errors']}[/dim]
    """
    console.print(Panel(Align.center(score_text.strip()), border_style=score_color, title="[bold white]Executive Summary[/bold white]"))
    console.print()

    with console.status("[bold green]Generating Multi-Format Audit Reports...[/bold green]", spinner="earth"):
        html_path, excel_path, md_path = _generate_reports(summary, out_dir)

    console.print("[bold green]✔ Multi-Format Audit Reports Generated Successfully:[/bold green]")
    console.print(f"  • [cyan]HTML Dashboard:[/cyan] [link=file://{os.path.abspath(html_path)}]{os.path.abspath(html_path)}[/link]")
    if excel_path:
        console.print(f"  • [green]Excel Workbook:[/green]  [link=file://{os.path.abspath(excel_path)}]{os.path.abspath(excel_path)}[/link]")
    else:
        console.print("  • [red]Excel Workbook:[/red]  generation failed")
    console.print(f"  • [yellow]Markdown Report:[/yellow] [link=file://{os.path.abspath(md_path)}]{os.path.abspath(md_path)}[/link]")
    console.print()


def _normalize_argv(argv):
    """Bare `cis --cloud aws` (no explicit subcommand) keeps working by
    defaulting to `scan` — every command documented before the `cis import`
    subcommand was added continues to work completely unchanged.
    """
    if not argv:
        return ["scan"]
    if argv[0] in _KNOWN_COMMANDS or argv[0] in ("-h", "--help", "--version"):
        return list(argv)
    return ["scan"] + list(argv)


def _build_parser(settings):
    parser = argparse.ArgumentParser(prog="cis", description="CIS Unified Multi-Cloud Compliance & Audit CLI")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")

    subparsers = parser.add_subparsers(dest="command")

    scan_parser = subparsers.add_parser("scan", help="Run compliance checks against your cloud accounts (default)")
    scan_parser.add_argument("--cloud", type=str, default="all", choices=["all", "gcp", "workspace", "aws", "azure"], help="Cloud provider target filter")
    scan_parser.add_argument("--domain", type=str, default=settings["google_workspace_domain"], help="Target domain for Workspace checks")
    scan_parser.add_argument("--workers", type=int, default=settings["max_worker_threads"], help="Number of concurrent worker threads")
    scan_parser.add_argument("--output", type=str, default=settings["output_directory"], help="Output directory for generated reports")
    scan_parser.add_argument("--plain", action="store_true", help="Plain, non-interactive output with no colors/progress bar (for cron, CI, or log capture)")

    import_parser = subparsers.add_parser("import", help="Convert an official CIS Benchmark PDF into a structured JSON rule catalog")
    import_parser.add_argument("pdf_path", type=str, help="Path to a downloaded CIS Benchmark PDF")
    import_parser.add_argument("--cloud", type=str, required=True, choices=["aws", "azure", "gcp", "workspace"], help="Which benchmark this PDF is")
    import_parser.add_argument("--output", type=str, default=None, help="Output JSON path (default: imports/<cloud>_<version>.json)")

    return parser


def _run_import(args):
    if args.cloud not in _IMPORT_PARSERS:
        raise ImporterError(
            f"`cis import --cloud {args.cloud}` is not implemented yet. "
            f"Supported today: {', '.join(sorted(_IMPORT_PARSERS.keys()))}."
        )

    text = extract_text(args.pdf_path)
    catalog = _IMPORT_PARSERS[args.cloud](text, source_filename=os.path.basename(args.pdf_path))

    if not catalog.version_verified:
        print(
            f"Warning: this PDF's version ({catalog.benchmark_version}) hasn't been "
            f"verified against real data for --cloud {args.cloud}. Results may be "
            "inaccurate — treat with extra scrutiny."
        )

    output_path = args.output or os.path.join("imports", f"{args.cloud}_{catalog.benchmark_version}.json")
    try:
        catalog.write(output_path)
    except OSError as e:
        raise ImporterError(f"Could not write output file {output_path}: {e}")

    total = len(catalog.rules)
    incomplete = sum(1 for r in catalog.rules if r.incomplete)
    print(f"Parsed {total} rule(s) ({incomplete} incomplete) -> {output_path}")


def main():
    settings = load_settings()
    parser = _build_parser(settings)
    args = parser.parse_args(_normalize_argv(sys.argv[1:]))

    if args.command == "import":
        try:
            _run_import(args)
        except ImporterError as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        return

    engine = ComplianceEngine(max_workers=args.workers, target_domain=args.domain, cloud_filter=args.cloud)
    if args.plain:
        _run_plain(engine, args.output)
    else:
        _run_rich(engine, args.output)


if __name__ == "__main__":
    main()
