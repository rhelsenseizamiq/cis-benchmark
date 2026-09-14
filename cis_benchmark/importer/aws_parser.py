from ._pdf_benchmark_parser import BenchmarkParserConfig, parse_benchmark
from .schema import BenchmarkCatalog

_CONFIG = BenchmarkParserConfig(
    benchmark_name="CIS Amazon Web Services Foundations Benchmark",
    appendix_marker="Appendix: Summary Table",
    classification_words=["Scored", "Not Scored"],
    known_versions=["1.2.0"],
)


def parse(text: str, source_filename: str = "") -> BenchmarkCatalog:
    return parse_benchmark(text, _CONFIG, source_filename)
