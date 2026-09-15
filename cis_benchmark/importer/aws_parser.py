from ._pdf_benchmark_parser import BenchmarkParserConfig, parse_benchmark
from .schema import BenchmarkCatalog

_CONFIG = BenchmarkParserConfig(
    benchmark_name="CIS Amazon Web Services Foundations Benchmark",
    appendix_marker="Appendix: Summary Table",
    # v7.0.0 switched from Scored/Not Scored to Manual/Automated; both
    # vocabularies are accepted since a real document only ever uses one
    # consistently — a version's PDF never mixes them.
    classification_words=["Scored", "Not Scored", "Manual", "Automated"],
    known_versions=["1.2.0", "7.0.0"],
)


def parse(text: str, source_filename: str = "") -> BenchmarkCatalog:
    return parse_benchmark(text, _CONFIG, source_filename)
