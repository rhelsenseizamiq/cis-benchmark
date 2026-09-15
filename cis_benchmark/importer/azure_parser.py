from ._pdf_benchmark_parser import BenchmarkParserConfig, parse_benchmark
from .schema import BenchmarkCatalog

_CONFIG = BenchmarkParserConfig(
    benchmark_name="CIS Microsoft Azure Foundations Benchmark",
    # v6.0.0 renamed this heading to a single-line "Appendix: Summary
    # Table" (matching AWS/Workspace); the older, already-verified v1.4.0
    # real document used the wrapped "Appendix: Recommendation
    # Summary\nTable" form, kept as a fallback.
    appendix_marker="Appendix: Summary Table",
    appendix_marker_fallbacks=["Appendix: Recommendation Summary"],
    classification_words=["Manual", "Automated"],
    known_versions=["1.4.0", "6.0.0"],
)


def parse(text: str, source_filename: str = "") -> BenchmarkCatalog:
    return parse_benchmark(text, _CONFIG, source_filename)
